"""Read-only real-team projection plus the current administrator's private records.

No test membership/submission is written into the real team. Mutations still run
as the private ordinary user and therefore cannot edit real-team records.
"""
import copy
import json
import re
from django.http import JsonResponse
from django.db.models import Count, Sum
from django.utils import timezone
from .models import Submission, SubmissionPart, TeamMembership, Week


def json_response(data):
    response=JsonResponse(data)
    response['Cache-Control']='no-store'
    return response


def protect_real(data):
    if isinstance(data,dict):
        for key in ('can_edit','can_delete','can_resubmit','can_reject','can_tip','can_kick','can_manage_role'):
            if key in data:data[key]=False
        if 'account' in data:data['account']=''
        for value in data.values():protect_real(value)
    elif isinstance(data,list):
        for item in data:protect_real(item)
    return data


def test_progress(member,week):
    query=Submission.objects.filter(member=member,is_valid=True)
    if week:
        query=query.filter(record_date__gte=timezone.localdate(week.starts_at),record_date__lt=timezone.localdate(week.ends_at))
    parts=SubmissionPart.objects.filter(submission__in=query,status='approved')
    return (parts.aggregate(n=Sum('points_awarded'))['n'] or 0,
        query.filter(parts__kind='proof',parts__status='approved').distinct().count(),
        query.filter(parts__kind='proof',parts__status='approved').aggregate(n=Count('problem_id',distinct=True))['n'] or 0)


def mark_test(row):
    row['is_test']=True
    row['name']='管理员'
    if 'account' in row:row['account']=''
    return row


def private_request(request,source_week=None):
    clone=copy.copy(request)
    clone.GET=request.GET.copy()
    if source_week or clone.GET.get("week"):
        # The two storage spaces use different week IDs. Filter private records
        # by attributed dates when combining them below, never by real IDs.
        clone.GET.pop('week',None)
    return clone


def overlay(request,get_response):
    path=request.path
    if path == '/api/showcase' and request.GET.get('all') == '1':
        return None
    if re.fullmatch(r'/api/problems/\d+/submissions', path):
        return None
    combined=path in ('/api/members','/api/leaderboard','/api/dashboard','/api/showcase') or (path=='/api/submissions' and request.GET.get('mine')!='1')
    detail=bool(re.fullmatch(r'/api/(members/\d+/(history|avatar|profile)|problems/\d+/submissions|attachments/\d+)',path))
    if not combined and not detail and path!='/api/semesters':return None
    from .views import membership_for,active_semester,active_week,leaderboard_rows_for
    member=membership_for(request)
    source=request.test_target_team
    real=copy.copy(request)
    real.user=request.test_mode_admin
    real.session=dict(request.session,team_id=source.pk)
    real.admin_test_mode=False
    real.test_target_team=None
    if path=='/api/semesters':return get_response(real)
    history=re.fullmatch(r'/api/members/(\d+)/history',path)
    if history and int(history[1])==member.pk:
        from .views import serialize_submission
        from .services import qualified
        term=request.GET.get('semester')
        number=request.GET.get('week')
        if (term and not term.isdigit()) or (number and not number.isdigit()):
            return JsonResponse({'error':'学期或周次无效'},status=400)
        sem=source.semesters.filter(pk=term).first() if term else active_semester(source)
        if not sem:return JsonResponse({'error':'学期不存在'},status=404)
        selected=sem.weeks.filter(number=number).first() if number else None
        if number and not selected:return JsonResponse({'error':'周次不存在'},status=404)
        query=Submission.objects.filter(member=member,is_valid=True,record_date__gte=sem.starts_on,record_date__lte=sem.ends_on).select_related('week','semester','problem','member').prefetch_related('parts')
        if selected:query=query.filter(record_date__gte=timezone.localdate(selected.starts_at),record_date__lt=timezone.localdate(selected.ends_at))
        score=SubmissionPart.objects.filter(submission__in=query,status='approved').aggregate(n=Sum('points_awarded'))['n'] or 0
        count=query.filter(parts__kind='proof',parts__status='approved').distinct().count()
        return json_response({'member':{'id':member.pk,'name':'管理员'},'summary':{'score':score,'submissions':count,'qualified':qualified(score,count,selected) if selected else None},'submissions':[dict(serialize_submission(item),is_test=True) for item in query],'test_overlay':True})
    if detail:
        # Admin rights authorize reading the selected team's material only.
        match=re.fullmatch(r'/api/attachments/(\d+)',path)
        if match and not SubmissionPart.objects.filter(pk=match[1],submission__team_id__in=[source.pk,member.team_id]).exists():
            return JsonResponse({'error':'附件不存在'},status=404)
        real_response=get_response(real)
        if real_response.status_code==404:return get_response(request)
        if real_response.get('Content-Type','').startswith('application/json') and real_response.status_code==200:
            return json_response(protect_real(json.loads(real_response.content)))
        return real_response
    real_response=get_response(real)
    if real_response.status_code!=200:return real_response
    real_data=protect_real(json.loads(real_response.content))
    semester=active_semester(source)
    week=active_week(semester) if semester else None
    private=get_response(private_request(request,week))
    if private.status_code!=200:return private
    data=json.loads(private.content)
    if path=='/api/members':
        score,count,ac=test_progress(member,week)
        for row in data['members']:
            if row['id']==member.pk:row.update(score=score,submissions=count,ac_problems=ac);mark_test(row)
        real_data['members']+=data['members']
        real_data['team_name']=source.name
        data=real_data
    elif path=='/api/leaderboard':
        rows=real_data['rows']+[mark_test(row) for row in data['rows']]
        rows.sort(key=lambda row:(row['value'] is None,-(row['value'] or 0),row['name'].casefold(),row['memberId']))
        last=object();rank=None
        for index,row in enumerate(rows,1):
            if row['value'] is None:row['rank']=None
            else:
                if row['value']!=last:rank=index
                row['rank']=rank;last=row['value']
        real_data['rows']=rows;data=real_data
    elif path=='/api/dashboard':
        score,count,_=test_progress(member,week)
        rows=leaderboard_rows_for(source,semester,week) if week else []
        rows.append({'memberId':member.pk,'name':member.display_name,'score':score,'submissions':count})
        rows.sort(key=lambda row:(-row['score'],-row['submissions'],row['name']))
        data['score']=score;data['submissions']=count
        data['stats'].update(rank=next(i for i,row in enumerate(rows,1) if row['memberId']==member.pk),memberCount=len(rows),previousRank=None)
        data['team']={'id':source.pk,'name':source.name}
        if data.get('semester') and real_data.get('semester'):
            private_id=data['semester']['id'];data['semester']=dict(real_data['semester'],id=private_id)
        if data.get('current_week') and real_data.get('current_week'):
            private_id=data['current_week']['id'];data['current_week']=dict(real_data['current_week'],id=private_id)
    elif path=='/api/submissions':
        items=data['submissions']
        if request.GET.get('week'):
            selected=Week.objects.filter(pk=request.GET['week'],semester__team=source).first()
            if selected:
                start=timezone.localdate(selected.starts_at).isoformat();end=timezone.localdate(selected.ends_at).isoformat()
                items=[item for item in items if start<=item['record_date']<end]
            else:items=[]
        for item in items:item['is_test']=True
        real_data['submissions']+=items
        real_data['submissions'].sort(key=lambda item:(item['record_date'],item['submitted_at'],item['id']),reverse=True)
        data=real_data
    elif path=='/api/showcase':
        selected=Week.objects.filter(pk=request.GET.get('week') or real_data.get('week'),semester__team=source).first()
        ids=Submission.objects.filter(member=member,is_valid=True)
        search=request.GET.get('q','').strip()[:200]
        if search and search not in ('管理员',member.display_name):
            from django.db.models import Q
            ids=ids.filter(Q(problem__title__icontains=search)|Q(problem__url__icontains=search))
        if selected:ids=ids.filter(record_date__gte=timezone.localdate(selected.starts_at),record_date__lt=timezone.localdate(selected.ends_at))
        if request.GET.get('page','1')=='1':
            groups=ids.values('problem_id','problem__title','problem__url').annotate(count=Count('id')).order_by('-problem_id')[:20]
            private_rows=[{'id':row['problem_id'],'title':row['problem__title'] or row['problem__url'],'url':row['problem__url'],'count':row['count'],'members':['管理员'],'is_test':True} for row in groups]
            real_data['problems']=private_rows+real_data['problems']
        data=real_data
    data['test_overlay']=True
    return json_response(data)
