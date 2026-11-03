"""Lifetime solved totals: durable contest ACs + archived/live approved problems."""
from collections import defaultdict
from django.utils import timezone
from django.db import transaction
from .models import SolvedProblemCredit, DatedSolvedProblemCredit, Submission, SubmissionPart, PlatformBinding


def archive_submission_credits(semester):
    rows = Submission.objects.filter(semester=semester, is_valid=True, problem__isnull=False,
        parts__kind=SubmissionPart.PROOF, parts__status=SubmissionPart.APPROVED
    ).values_list('member__user_id', 'problem__identity').distinct()
    SolvedProblemCredit.objects.bulk_create([
        SolvedProblemCredit(user_id=uid, source='submission', problem_key=key) for uid, key in rows
    ], ignore_conflicts=True)
    dated = Submission.objects.filter(semester=semester, is_valid=True, problem__isnull=False,
        parts__kind=SubmissionPart.PROOF, parts__status=SubmissionPart.APPROVED
    ).values_list('member__user_id', 'problem__identity', 'record_date').distinct()
    DatedSolvedProblemCredit.objects.bulk_create([
        DatedSolvedProblemCredit(user_id=uid, source='submission', problem_key=key, solved_on=day)
        for uid, key, day in dated
    ], ignore_conflicts=True, batch_size=500)


@transaction.atomic
def remember_contest_ac(problem):
    contest = problem.participation
    if not problem.accepted or contest.source_data.get('demo'):
        return
    if not PlatformBinding.objects.filter(user_id=contest.user_id, platform=contest.platform, account=contest.account).exists():
        return
    SolvedProblemCredit.objects.get_or_create(user_id=contest.user_id, source='contest',
        problem_key=f'{contest.platform}:{contest.contest_key}:{problem.problem_key}')
    key = f'{contest.platform}:{contest.contest_key}:{problem.problem_key}'
    day = timezone.localdate(problem.accepted_at or contest.starts_at)
    # A later verified timestamp supersedes the earlier contest-date fallback.
    DatedSolvedProblemCredit.objects.filter(user_id=contest.user_id, source='contest',
        problem_key=key).exclude(solved_on=day).delete()
    DatedSolvedProblemCredit.objects.update_or_create(user_id=contest.user_id, source='contest',
        problem_key=key, solved_on=day, defaults={'time_verified':problem.accepted_at is not None})


def _baseline_evidence(user_ids):
    """One ledger for total, semester and heatmap; unknown dates remain numeric only."""
    from datetime import date
    from .models import PlatformSolvedBaseline, ContestProblemProgress
    from .platform_solved import contest_key, problem_url
    today = timezone.localdate()
    items = defaultdict(dict)
    unknown = defaultdict(int)
    baseline_unknown = {}
    baselines = {(b.binding.user_id,b.binding.platform):b for b in
        PlatformSolvedBaseline.objects.filter(binding__user_id__in=user_ids,total__isnull=False,
            captured_at__isnull=False).select_related('binding')}
    def covered(uid,source,key):
        return source=='contest' and (uid,key.split(':',1)[0]) in baselines
    def add(uid,key,day=None,**meta):
        if day and day>today:
            return
        previous=items[uid].get(key)
        if previous is None or day and (previous['date'] is None or day<=previous['date']):
            items[uid][key]={'date':day,**meta}
    for uid,source,key in SolvedProblemCredit.objects.filter(user_id__in=user_ids).values_list('user_id','source','problem_key'):
        if not covered(uid,source,key):
            add(uid,(source,key))
    for uid,source,key,day in DatedSolvedProblemCredit.objects.filter(user_id__in=user_ids,
            time_verified=True).values_list('user_id','source','problem_key','solved_on'):
        if not covered(uid,source,key):
            add(uid,(source,key),day,title=key,url='',source='归档过题记录')
    proofs=Submission.objects.filter(member__user_id__in=user_ids,is_valid=True,problem__isnull=False,
        parts__kind=SubmissionPart.PROOF,parts__status=SubmissionPart.APPROVED).select_related('member','problem')
    for row in proofs:
        add(row.member.user_id,('submission',row.problem.identity),row.record_date,
            title=row.problem.title or row.problem.url,url=row.problem.url,source='本站通过记录')
    for (uid,platform),base in baselines.items():
        dated={}
        for key,value in base.dated_problems.items():
            try:
                day=date.fromisoformat(value)
            except (ValueError,TypeError):
                continue
            if day<=today:
                dated[key]=day
        unknown[uid]+=max(0,base.total-len(dated))
        baseline_unknown[(uid,platform)]=max(0,base.total-len(dated))
        for key,day in dated.items():
            add(uid,('platform',platform+':'+key),day,title=key,
                url=problem_url(platform,key,base.binding.account),source=platform+' · 绑定时过题')
    bindings=set(PlatformBinding.objects.filter(user_id__in=user_ids).values_list('user_id','platform','account'))
    for row in ContestProblemProgress.objects.filter(participation__user_id__in=user_ids,accepted=True).select_related('participation'):
        c=row.participation
        if c.source_data.get('demo') or (c.user_id,c.platform,c.account) not in bindings:
            continue
        base=baselines.get((c.user_id,c.platform))
        day=timezone.localdate(row.accepted_at) if row.accepted_at else None
        if base:
            key=contest_key(row)
            identity=('platform',c.platform+':'+key)
            if row.accepted_at and row.accepted_at<=base.captured_at:
                # An old contest may reveal the date of a baseline solve, but never adds to its total.
                if identity not in items[c.user_id] and baseline_unknown[(c.user_id,c.platform)]>0 and (
                        not base.ids_complete or key in base.problem_ids):
                    baseline_unknown[(c.user_id,c.platform)]-=1
                    unknown[c.user_id]-=1
                    add(c.user_id,identity,day,title=row.title or row.label,url=row.url,source=c.platform+' · 基线日期补全')
                continue
            # Old contests discovered after binding are already part of the baseline.
            if not row.accepted_at or row.accepted_at<=base.captured_at or key in base.problem_ids:
                continue
            # With aggregate-only baselines, old contests might repeat previously solved tasks.
            if not base.ids_complete and c.starts_at<=base.captured_at:
                continue
        else:
            identity=('contest',f'{c.platform}:{c.contest_key}:{row.problem_key}')
        add(c.user_id,identity,day,title=row.title or row.label,url=row.url,source=c.platform+' · 比赛 AC')
    return {uid:{'items':list(items[uid].values()),'undated':unknown[uid]+sum(v['date'] is None for v in items[uid].values()),
                 'total':unknown[uid]+len(items[uid])} for uid in user_ids}


def solved_evidence(user_ids):
    """Use stable problem identities to combine all bound accounts."""
    from datetime import date
    from .models import PlatformSolvedRecord, PlatformSolvedBaseline, ContestProblemProgress, TrackerCatalog
    from .platform_solved import contest_key, problem_url
    user_ids=list(user_ids)
    bindings=list(PlatformBinding.objects.filter(user_id__in=user_ids))
    modern={b.user_id for b in bindings if b.sync_state.get('version') == 2}
    result=_baseline_evidence([uid for uid in user_ids if uid not in modern]) if len(modern)<len(user_ids) else {}
    items=defaultdict(dict)
    accounts={(b.user_id,b.platform,b.account) for b in bindings}
    leetcode_regions=defaultdict(set)
    for binding in bindings:
        if binding.platform=='leetcode':
            leetcode_regions[binding.user_id].add('cn' if binding.account.startswith('cn:') else 'us')
    today=timezone.localdate()
    nc_aliases={}
    catalog=TrackerCatalog.objects.filter(kind='nowcoder').first()
    if catalog:
        for event in catalog.contests:
            for p in event['problems']:
                aliases=[p['key']]+p.get('aliases',[])
                canonical=next((key for key in aliases if key.startswith('problem/')),p['key'])
                for key in aliases:nc_aliases[key.lower()]=canonical.lower()
    def identity(platform,key,uid=None):
        prefix=platform
        if platform=='leetcode':
            regions=leetcode_regions[uid]
            # Current bindings govern both old credits and live evidence. When
            # both regions are bound, share identities and keep the larger floor.
            prefix='leetcode_'+next(iter(regions)) if len(regions)==1 else 'leetcode'
        if platform=='nowcoder':key=nc_aliases.get(key.lower(),key)
        return prefix+':'+key.lower()
    def add(uid,key,day=None,title='',url='',source=''):
        if not key or uid not in modern or day and day>today:return
        old=items[uid].get(key)
        if old is None or day and (old['date'] is None or day<old['date']):
            items[uid][key]={'date':day,'title':title or key,'url':url,'source':source}
    for row in PlatformSolvedRecord.objects.filter(binding__user_id__in=modern).select_related('binding'):
        b=row.binding
        add(b.user_id,identity(b.platform,row.problem_key,b.user_id),row.solved_on,row.title,row.url,b.platform)
    baselines = list(PlatformSolvedBaseline.objects.filter(binding__user_id__in=modern).select_related('binding'))
    for base in baselines:
        b=base.binding
        for key in set(base.problem_ids)|set(base.dated_problems):
            try:day=date.fromisoformat(base.dated_problems[key]) if key in base.dated_problems else None
            except (TypeError,ValueError):day=None
            add(b.user_id,identity(b.platform,key,b.user_id),day,key,problem_url(b.platform,key,b.account),b.platform)
    progress=list(ContestProblemProgress.objects.filter(participation__user_id__in=modern,accepted=True).select_related('participation'))
    historical_aliases={}
    for row in progress:
        c=row.participation
        raw=f'{c.platform}:{c.contest_key}:{row.problem_key}'.lower()
        historical_aliases[(c.user_id,raw)]=identity(c.platform,contest_key(row),c.user_id)
    def ledger_key(uid,key):
        if (uid,key.lower()) in historical_aliases:return historical_aliases[(uid,key.lower())]
        parts=key.lower().split(':')
        if parts[0]=='atcoder' and len(parts)>=3:
            problem=parts[-1].lower()
            return 'atcoder:'+(problem if problem.startswith(parts[1].lower()+'_') else parts[1].lower()+'_'+problem)
        if parts[0]=='nowcoder' and len(parts)==3:
            return identity('nowcoder',f'contest/{parts[1]}/{parts[2]}')
        if parts[0] in {'leetcode','leetcode_cn','leetcode_us'} and len(parts)>=2:
            return identity('leetcode',parts[-1],uid=uid)
        return key.lower()
    for credit in SolvedProblemCredit.objects.filter(user_id__in=modern):
        add(credit.user_id,ledger_key(credit.user_id,credit.problem_key),source='过题记录')
    for credit in DatedSolvedProblemCredit.objects.filter(user_id__in=modern,time_verified=True):
        add(credit.user_id,ledger_key(credit.user_id,credit.problem_key),credit.solved_on,source='过题记录')
    for row in Submission.objects.filter(member__user_id__in=modern,is_valid=True,problem__isnull=False,
            parts__kind=SubmissionPart.PROOF,parts__status=SubmissionPart.APPROVED).select_related('member','problem'):
        key=row.problem.identity.lower()
        if key.startswith(('leetcode:','leetcode_cn:','leetcode_us:')):
            key=ledger_key(row.member.user_id,key)
        if key.startswith('nowcoder:'):key=identity('nowcoder',key.split(':',1)[1])
        add(row.member.user_id,key,row.record_date,row.problem.title,row.problem.url,'训练记录')
    for row in progress:
        c=row.participation
        if c.source_data.get('demo') or (c.user_id,c.platform,c.account) not in accounts:continue
        day=timezone.localdate(row.accepted_at) if row.accepted_at else None
        add(c.user_id,identity(c.platform,contest_key(row),c.user_id),day,row.title,row.url,c.platform)
    # Aggregate totals are evidence even when an upstream only exposes recent history.
    # Fill missing identities numerically, never invent dates or add a second copy
    # of a solve when its detailed record is eventually discovered.
    floors = defaultdict(dict)
    for base in baselines:
        if base.total is None or base.captured_at is None:
            continue
        b = base.binding
        prefix = identity(b.platform, '', b.user_id)
        raw_keys = set(base.problem_ids) | set(base.dated_problems)
        known = {identity(b.platform, key, b.user_id) for key in raw_keys}
        # A raw history can contain multiple proven aliases of the same task.
        # Do not restore those duplicates as anonymous solves via the floor.
        baseline_total = max(0, base.total - (len(raw_keys) - len(known)))
        captured_day = timezone.localdate(base.captured_at)
        # Only a complete baseline proves that an absent task is new. With an
        # incomplete baseline, a later AC may simply be a repeat of an old task.
        increments = sum(key.startswith(prefix) and key not in known
                         and value['date'] is not None and value['date'] > captured_day
                         for key, value in items[b.user_id].items()) if base.ids_complete else 0
        # Multiple accounts on the same platform may overlap: retain the largest
        # confirmed total rather than summing unknown identities across accounts.
        floors[b.user_id][prefix] = max(floors[b.user_id].get(prefix, 0), baseline_total + increments)
    for uid in modern:
        missing = sum(max(0, total - sum(key.startswith(prefix) for key in items[uid]))
                      for prefix, total in floors[uid].items())
        result[uid] = {'items': list(items[uid].values()), 'total': len(items[uid]) + missing,
                       'undated': sum(v['date'] is None for v in items[uid].values()) + missing}
    return result


def lifetime_solved_counts(user_ids):
    return {uid:data['total'] for uid,data in solved_evidence(user_ids).items()}


def semester_solved_counts(user_ids, semester):
    if not semester:
        return {}
    end=min(semester.ends_on,timezone.localdate())
    return {uid:sum(item['date'] is not None and semester.starts_on<=item['date']<=end
                    for item in data['items']) for uid,data in solved_evidence(user_ids).items()}
