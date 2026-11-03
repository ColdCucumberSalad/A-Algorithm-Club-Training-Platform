"""Administrator-only session sandbox. Real credentials and privileges are unchanged."""
import uuid
from django.contrib.auth.models import User
from django.db import transaction
from django.http import JsonResponse
from .models import Team, TeamMembership, Semester

USER_KEY = 'admin_test_user'
TEAM_KEY = 'admin_test_team'
TARGET_KEY = 'admin_test_target'

def target_teams():
    return Team.objects.exclude(memberships__user_id__in=User.objects.filter(first_name='CLUB_TEST_SANDBOX',password__startswith='!').values('pk'))

def sandbox_code(admin, target):
    return 'TST-'+uuid.uuid5(uuid.NAMESPACE_URL,f'club-test:{admin.pk}:{target.pk}').hex[:24]

def clear_test_session(request):
    previous=request.session.pop('admin_test_previous_team',None)
    request.session.pop(USER_KEY,None);request.session.pop(TEAM_KEY,None);request.session.pop(TARGET_KEY,None)
    if previous is not None:request.session['team_id']=previous
    else:request.session.pop('team_id',None)

class AdminTestModeMiddleware:
    def __init__(self, get_response): self.get_response = get_response
    def __call__(self, request):
        request.admin_test_mode = False
        # Authentication must remain reachable even with an expired/legacy sandbox.
        if request.path in ('/api/auth/login','/api/auth/logout') and request.method=='POST':
            if request.session.get(USER_KEY):clear_test_session(request)
            return self.get_response(request)
        if request.path.startswith('/api/') and request.session.get(USER_KEY):
            admin = request.user
            if not admin.is_authenticated or not admin.is_active or not admin.is_superuser:
                return JsonResponse({'error':'测试模式仅限有效的系统管理员会话'}, status=403)
            if request.path == '/api/admin-test-mode':
                return self.get_response(request)
            if request.path == '/api/team/select' and request.method == 'POST':
                from .views import body
                return activate(request,admin,body(request).get('team_id'))
            target=target_teams().filter(pk=request.session.get(TARGET_KEY)).first()
            if not target:
                clear_test_session(request)
                return self.get_response(request)
            request.test_target_team=target
            member = TeamMembership.objects.select_related('user','team').filter(
                user_id=request.session[USER_KEY], team_id=request.session.get(TEAM_KEY),
                team__created_by=admin, user__first_name='CLUB_TEST_SANDBOX',
                user__is_superuser=False, user__is_staff=False, is_active=True).first()
            if not member or member.user.has_usable_password() or member.team.code!=sandbox_code(admin,target):
                return JsonResponse({'error':'测试环境已失效，请重新登录管理员'}, status=403)
            request.test_mode_admin = admin
            request.admin_test_mode = True
            request.user = member.user
            request.session['team_id'] = member.team_id
            if request.path.startswith(('/api/auth/','/api/team/')) or (request.path.startswith('/api/profile') and request.method not in ('GET','HEAD')):
                return JsonResponse({'error':'测试模式不修改账号、团队归属或平台绑定；请先退出测试模式'}, status=403)
            if request.method=='GET':
                from .admin_test_overlay import overlay
                response=overlay(request,self.get_response)
                if response is not None:return response
        return self.get_response(request)

def sandbox_week(team, day):
    from .semester_calendar import semester_bounds, semester_name
    from .services import build_weeks
    from django.utils import timezone
    start,end = semester_bounds(day)
    semester,_ = Semester.objects.get_or_create(team=team, starts_on=start, defaults={
        'ends_on':end,'name':semester_name(start),'is_active':start<=timezone.localdate()<=end,
        'calendar_managed':True})
    build_weeks(semester)
    return semester,semester.weeks.get(starts_at__date__lte=day, ends_at__date__gt=day)

def toggle(request):
    from .views import body
    if request.method != 'POST': return JsonResponse({'error':'仅支持 POST'},status=405)
    admin = getattr(request,'test_mode_admin',request.user)
    if not admin.is_authenticated or not admin.is_active or not admin.is_superuser:
        return JsonResponse({'error':'仅系统管理员可切换测试模式'},status=403)
    enabled = body(request).get('enabled')
    if not isinstance(enabled,bool): return JsonResponse({'error':'enabled 必须为布尔值'},status=400)
    if enabled:
        data=body(request)
        target=data.get('team_id') or request.session.get(TARGET_KEY) or request.session.get('team_id')
        return activate(request,admin,target)
    else:
        previous=request.session.pop('admin_test_previous_team',None)
        request.session.pop(USER_KEY,None);request.session.pop(TEAM_KEY,None);request.session.pop(TARGET_KEY,None)
        if previous is not None: request.session['team_id']=previous
        else: request.session.pop('team_id',None)
    request.session.cycle_key()
    return JsonResponse({'ok':True,'test_mode':enabled})

@transaction.atomic
def activate(request,admin,target_id):
    try: target=target_teams().filter(pk=int(target_id)).first()
    except (ValueError,TypeError): target=None
    if not target: return JsonResponse({'error':'请先选择一个已有的真实团队作为测试对象'},status=403)
    user,_=User.objects.get_or_create(username=f'__club_test_{admin.pk}',defaults={'first_name':'CLUB_TEST_SANDBOX','password':'!'})
    user=User.objects.select_for_update().get(pk=user.pk)
    if user.first_name!='CLUB_TEST_SANDBOX' or user.has_usable_password() or user.is_staff or user.is_superuser:
        return JsonResponse({'error':'测试账号标识冲突'},status=409)
    team,_=Team.objects.get_or_create(code=sandbox_code(admin,target),defaults={'name':target.name+'（管理员私有测试）','created_by':admin})
    if team.created_by_id!=admin.pk: return JsonResponse({'error':'测试空间冲突'},status=409)
    team.name=(target.name+'（管理员私有测试）')[:80]
    for field in ('currency_enabled','daily_checkin_reward','problem_rewards','reward_settings'): setattr(team,field,getattr(target,field))
    team.save(update_fields=['name','currency_enabled','daily_checkin_reward','problem_rewards','reward_settings'])
    TeamMembership.objects.get_or_create(user=user,team=team,defaults={'display_name':'管理员测试用户'})
    from django.utils import timezone
    today=timezone.localdate()
    semester,_=sandbox_week(team,today)
    source=target.semesters.filter(is_active=True,archived_at__isnull=True,starts_on__lte=today,ends_on__gte=today).first()
    if source:
        fields=['min_score','min_submissions','require_both','screenshot_points','logic_points','blog_points']
        for field in fields:setattr(semester,field,getattr(source,field))
        semester.save(update_fields=fields)
    if not request.session.get(USER_KEY):request.session['admin_test_previous_team']=request.session.get('team_id')
    request.session[USER_KEY]=user.pk;request.session[TEAM_KEY]=team.pk;request.session[TARGET_KEY]=target.pk
    request.session['team_id']=team.pk
    request.session.cycle_key()
    return JsonResponse({'ok':True,'test_mode':True,'target_team':{'id':target.pk,'name':target.name}})
