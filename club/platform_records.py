"""Resumable per-account AC history. Each worker invocation fetches one page."""
import hashlib
import json
import re
from datetime import date, datetime
from urllib.parse import quote, unquote, urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import PlatformBinding, PlatformSolvedRecord, PlatformSolvedBaseline
from .platform_sync import Remote, SyncError
from .platform_credentials import attach
from .platform_solved import day_of, problem_url
from .qoj_pages import profile_rating, accepted_rows


def record(key, stamp=None, title='', url=''):
    return {'problem_key': str(key).lower(), 'solved_on': day_of(stamp) if stamp else None,
            'title': str(title)[:300], 'url': url[:1000]}


def json_page(remote, url):
    text = remote.text(url, headers={'x-lentille-request': 'content-only', 'Referer': 'https://www.luogu.com.cn/'})
    try:
        data = json.loads(text)
    except ValueError:
        match = re.search(r'decodeURIComponent\(("(?:[^"\\]|\\.)*")\)', text)
        if not match:
            raise SyncError('同步失败，请重试') from None
        data = json.loads(unquote(json.loads(match[1])))
    return data.get('data', data.get('currentData', data))


def profile(remote, binding):
    from . import platform_sync as adapters
    if binding.platform == 'qoj':
        html = remote.text('https://qoj.ac/user/profile/' + quote(binding.account, safe=''))
        result = {'display_name': binding.account, 'profile_url': 'https://qoj.ac/user/profile/' + quote(binding.account, safe='')}
        rating = profile_rating(html, binding.account)
        if rating is not None:
            result['rating'] = rating
        return result
    fn = getattr(adapters, binding.platform)
    result = fn(remote, binding.account, include_solved=binding.platform in {'leetcode', 'luogu', 'atcoder'})
    # Luogu aliases are resolved before history is stored.
    if binding.platform == 'luogu':
        match = re.search(r'/user/(\d+)', result.get('profile_url', ''))
        if match:
            result['_canonical_account'] = match[1]
    # Remove the old explanatory labels from account cards.
    result.pop('notes', None)
    result['solved_label'] = '通过题数'
    return result


def history_page(remote, binding, state):
    platform, account = binding.platform, binding.account
    page = state.get('page', 1)
    rows, next_state = [], dict(state)
    next_state['page'] = page + 1
    cutoff = 0 if state.get('full') else max(0, state.get('cursor', 0) - 86400)
    stamps, ids = [], []
    complete = True
    if platform == 'codeforces':
        size = 1000
        data = remote.json(f'https://codeforces.com/api/user.status?handle={quote(account,safe="")}&from={(page-1)*size+1}&count={size}')
        if data.get('status') != 'OK' or not isinstance(data.get('result'), list):
            raise SyncError('同步失败，请重试')
        submissions = data['result']
        for item in submissions:
            stamps.append(item.get('creationTimeSeconds', 0)); ids.append(item.get('id'))
            p = item.get('problem') or {}
            if item.get('verdict') == 'OK' and p.get('contestId') and p.get('index'):
                key = f"{p['contestId']}:{p['index']}".lower()
                rows.append(record(key, item.get('creationTimeSeconds'), p.get('name', ''), problem_url(platform,key,account)))
        done = len(submissions) < size or bool(cutoff and stamps and min(stamps) < cutoff)
    elif platform == 'atcoder':
        cursor = state.get('next_second', 0 if state.get('full') else cutoff)
        submissions = remote.json(f'https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user={quote(account,safe="")}&from_second={cursor}')
        if not isinstance(submissions, list):
            raise SyncError('同步失败，请重试')
        for item in submissions:
            if str(item.get('user_id',account)).casefold() != account.casefold():
                raise SyncError('账号不匹配')
            stamps.append(item.get('epoch_second', 0)); ids.append(item.get('id'))
            if item.get('result') == 'AC' and item.get('problem_id'):
                key = item['problem_id'].lower()
                rows.append(record(key, item.get('epoch_second'), url=problem_url(platform,key,account)))
        done = len(submissions) < 500
        if not done and (not stamps or min(stamps) == max(stamps)):
            raise SyncError('同步失败，请重试')
        next_state['next_second'] = max(stamps, default=cursor) + 1
    elif platform == 'luogu':
        data = json_page(remote, 'https://www.luogu.com.cn/user/' + account + '/practice')
        passed = data.get('passed')
        if not isinstance(passed, list):
            raise SyncError('同步失败，请重试')
        for item in passed:
            key = item if isinstance(item, str) else item.get('pid', item.get('problemId', item.get('id')))
            if key:
                rows.append(record(key, title=item.get('title','') if isinstance(item,dict) else '', url=problem_url(platform,str(key),account)))
        done = True
        next_state['reported_total'] = len(rows)
    elif platform == 'qoj':
        if not remote.credentials.get('cookie'):
            raise SyncError('请填写 QOJ Cookie')
        html = remote.text(f'https://qoj.ac/submissions?submitter={quote(account,safe="")}&min_score=100&max_score=100&page={page}')
        soup, accepted = accepted_rows(html, account)
        for tr, link, key in accepted:
            text = tr.get_text(' ',strip=True)
            stamp = html_stamp(text)
            if stamp:
                stamps.append(stamp)
            ids.append(text)
            rows.append(record(key, stamp, link.get_text(' ',strip=True), 'https://qoj.ac/problem/'+key))
        done = not has_next(soup,page) or bool(cutoff and stamps and min(stamps)<cutoff)
    elif platform == 'nowcoder':
        html = remote.text(f'https://ac.nowcoder.com/acm/contest/profile/{account}/practice-coding?languageCategoryFilter=-1&orderType=DESC&page={page}&pageSize=200&statusTypeFilter=5', headers={'Referer':'https://ac.nowcoder.com/'})
        if not re.search(r'window\.curUser\.id\s*=\s*["\']'+re.escape(account)+r'["\']',html):
            raise SyncError('同步失败，请重试')
        soup = BeautifulSoup(html,'html.parser')
        if not soup.select_one('table'):
            raise SyncError('同步失败，请重试')
        for tr in soup.select('table tr'):
            link = next((a for a in tr.select('a[href]') if re.search(r'/acm/(?:problem/\d+|contest/\d+/[A-Za-z0-9]+)$',a['href'].rstrip('/'))),None)
            if not link:
                continue
            key = link['href'].rstrip('/').split('/acm/')[-1].lower()
            text = tr.get_text(' ',strip=True); stamp = html_stamp(text)
            if stamp:
                stamps.append(stamp)
            ids.append(text)
            rows.append(record(key,stamp,link.get_text(' ',strip=True),urljoin('https://ac.nowcoder.com',link['href'])))
        done = not has_next(soup,page) and len(rows)<200
        if cutoff and stamps and min(stamps)<cutoff:
            done = True
    elif platform == 'leetcode':
        china = account.startswith('cn:'); user = account[3:] if china else account
        host = 'https://leetcode.cn' if china else 'https://leetcode.com'
        endpoint = host + ('/graphql/noj-go/' if china else '/graphql/')
        def graphql(query, variables):
            data = remote.json(endpoint, payload={'query':query,'variables':variables}, headers={'Referer':host+'/'})
            if data.get('errors') or not data.get('data'):
                raise SyncError('同步失败，请重试')
            return data['data']
        if remote.credentials.get('cookie'):
            identity = graphql('query { userStatus { isSignedIn username userSlug } }',{})['userStatus']
            if not identity.get('isSignedIn') or user.casefold() not in {str(identity.get('username','')).casefold(),str(identity.get('userSlug','')).casefold()}:
                raise SyncError('Cookie 与账号不匹配')
            query = 'query($offset:Int!,$limit:Int!){submissionList(offset:$offset,limit:$limit){hasNext submissions{statusDisplay title titleSlug timestamp}}}'
            data = graphql(query,{'offset':(page-1)*20,'limit':20})['submissionList']
            submissions = data.get('submissions')
            if not isinstance(submissions,list):
                raise SyncError('同步失败，请重试')
            for item in submissions:
                stamp = int(item.get('timestamp',0)); stamps.append(stamp); ids.append(item)
                if item.get('statusDisplay','').casefold() in {'accepted','通过','已通过'} and item.get('titleSlug'):
                    key=item['titleSlug'].lower()
                    rows.append(record(key,stamp,item.get('title',''),host+'/problems/'+key+'/'))
            done = not data.get('hasNext') or bool(cutoff and stamps and min(stamps)<cutoff)
        else:
            query = ('query($u:String!){recentACSubmissions(userSlug:$u){submitTime question{titleSlug title}}}' if china else
                     'query($u:String!){recentAcSubmissionList(username:$u,limit:20){titleSlug title timestamp}}')
            data=graphql(query,{'u':user})
            submissions=data.get('recentACSubmissions' if china else 'recentAcSubmissionList')
            if not isinstance(submissions,list):
                raise SyncError('同步失败，请重试')
            for item in submissions:
                p=item.get('question',{}) if china else item
                if p.get('titleSlug'):
                    rows.append(record(p['titleSlug'],item.get('submitTime' if china else 'timestamp'),p.get('title',''),host+'/problems/'+p['titleSlug']+'/'))
            done=True; complete=False
    else:
        raise SyncError('不支持的平台')
    signature = hashlib.sha256(json.dumps(ids,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if ids and signature == state.get('signature'):
        raise SyncError('同步失败，请重试')
    next_state.update(signature=signature, max_stamp=max([state.get('max_stamp',0)]+stamps),
                      pages=state.get('pages',0)+1, complete=complete)
    return rows,next_state,done


def html_stamp(text):
    match=re.search(r'\b(20\d\d-\d\d-\d\d[ T]\d\d:\d\d(?::\d\d)?)\b',text)
    if not match:
        return None
    try:
        return datetime.fromisoformat(match[1]).replace(tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
    except ValueError:
        return None


def has_next(soup,page):
    for a in soup.select('a[href]'):
        if 'disabled' in a.get('class',[]) or a.find_parent(class_='disabled'):
            continue
        if a.get('rel') == ['next'] or a.get_text(strip=True) in {'下一页','Next','›','»','>'}:
            return True
        if re.search(r'[?&]page='+str(page+1)+r'(?:&|$)',a['href']):
            return True
    return False


def store(binding,rows):
    merged = {}
    for item in rows:
        item=dict(item); key=item.pop('problem_key')
        if item.get('solved_on'):
            item['solved_on']=date.fromisoformat(item['solved_on'])
        old = merged.get(key)
        if old and old['solved_on'] and (not item['solved_on'] or old['solved_on'] < item['solved_on']):
            item['solved_on'] = old['solved_on']
        merged[key] = item
    existing = {r.problem_key:r for r in PlatformSolvedRecord.objects.filter(binding=binding,problem_key__in=merged)}
    records = []
    for key, item in merged.items():
        old = existing.get(key)
        if old:
            if old.solved_on and (not item['solved_on'] or old.solved_on < item['solved_on']):
                item['solved_on']=old.solved_on
            for field in ('title','url'):
                if not item.get(field):
                    item[field]=getattr(old,field)
        records.append(PlatformSolvedRecord(binding=binding,problem_key=key,**item))
    PlatformSolvedRecord.objects.bulk_create(records,batch_size=300,update_conflicts=True,
        unique_fields=['binding','problem_key'],update_fields=['solved_on','title','url'])


def run_step(binding_id,token):
    binding=PlatformBinding.objects.filter(pk=binding_id,sync_token=token,status='pending').first()
    if not binding:
        return
    remote=Remote()
    expected=dict(binding.sync_state)
    try:
        attach(remote,binding)
        state=dict(expected)
        result=None; rows=[]; done=False
        if state.get('phase')=='profile':
            result=profile(remote,binding)
            state.update(phase='records',page=1)
        else:
            rows,state,done=history_page(remote,binding,state)
        with transaction.atomic():
            current=PlatformBinding.objects.select_for_update().filter(pk=binding_id,sync_token=token,status='pending').first()
            if not current or current.sync_state != expected:
                return
            if result is not None:
                canonical=result.pop('_canonical_account',None)
                if canonical and canonical != current.account:
                    if PlatformBinding.objects.filter(user_id=current.user_id,platform=current.platform,normalized_account=canonical).exclude(pk=current.pk).exists():
                        raise SyncError('账号已添加')
                    current.account=canonical
                # Preserve last successful fields when an optional profile field is absent.
                current.snapshot=dict(current.snapshot,**result)
            store(current,rows)
            state['count']=current.solved_records.count()
            if done:
                state.update(phase='done',cursor=max(state.get('cursor',0),state.get('max_stamp',0)))
                if current.platform in {'qoj','codeforces','nowcoder'}:
                    current.snapshot['solved']=state['count']
                if 'reported_total' in state:
                    current.snapshot['solved']=state['reported_total']
                current.snapshot['solved_label']='通过题数'
                current.synced_at=timezone.now();current.status='ready'
                keys=list(current.solved_records.values_list('problem_key',flat=True))
                dates={r.problem_key:r.solved_on.isoformat() for r in current.solved_records.exclude(solved_on=None)}
                PlatformSolvedBaseline.objects.update_or_create(binding=current,defaults={
                    'total':current.snapshot.get('solved',len(keys)),'problem_ids':keys,'dated_problems':dates,
                    'ids_complete':state.get('complete',False),'captured_at':timezone.now(),'checked_at':timezone.now(),'error':'','notes':[]})
            current.sync_state=state
            current.requested_at=timezone.now()
            current.error=''
            current.save()
            if done and current.platform == 'qoj' and current.encrypted_credentials:
                from .tasks import enqueue_qoj_overlay
                transaction.on_commit(lambda: enqueue_qoj_overlay(binding_id))
            if not done:
                from .tasks import sync_platform_binding
                transaction.on_commit(lambda: sync_platform_binding.apply_async(args=[binding_id,token],countdown=1))
    except Exception as exc:
        message=str(exc)[:240] if isinstance(exc,SyncError) else '同步失败，请重试'
        PlatformBinding.objects.filter(pk=binding_id,sync_token=token,sync_state=expected).update(status='failed',error=message)
    finally:
        remote.session.close()
