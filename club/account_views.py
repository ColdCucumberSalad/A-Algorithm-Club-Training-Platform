"""Global account maintenance, separate from team membership identity."""
import uuid
from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator, InvalidPage
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from .management_views import administrator_required
from .views import api_login_required, api_error, body
from .models import CurrencyBalance, CurrencyTransaction, UserInventory, ShopFulfillment, ShopItem, AccountClosure, TeamMembership, UserProfile, FileDeletion, SubmissionReport, AstrBotNotification, Semester, SemesterMemberTotal


def private(data):
    response=JsonResponse(data);response['Cache-Control']='no-store';return response


def account_data(user):
    closed=AccountClosure.objects.filter(user=user).first()
    return {'id':user.pk,'account':f'已注销账号 #{user.pk}' if closed else user.username,
        'closed':bool(closed),'active':user.is_active,'system_admin':user.is_superuser,
        'joined_at':user.date_joined.isoformat(), 'balance':CurrencyBalance.objects.filter(user=user).values_list('balance',flat=True).first() or 0,
        'teams':[{'id':m.team_id,'member_id':m.pk,'name':m.team.name,'display_name':m.display_name,'role':m.role,'active':m.is_active}
                 for m in user.team_memberships.select_related('team').order_by('pk')]}


@api_login_required
def current_account(request):
    if request.method!='GET':return api_error('仅支持 GET',405)
    if getattr(request,'admin_test_mode',False):return api_error('请退出测试模式后管理全局账号',403)
    return private(account_data(request.user))


@administrator_required
def accounts(request):
    if request.method!='GET':return api_error('仅支持 GET',405)
    q=request.GET.get('q','').strip()[:100]
    query=User.objects.exclude(first_name='CLUB_TEST_SANDBOX').order_by('-pk')
    if q:query=query.filter(Q(username__icontains=q)|Q(team_memberships__display_name__icontains=q)|Q(team_memberships__team__name__icontains=q)).distinct()
    try:page=Paginator(query,20).page(request.GET.get('page','1'))
    except InvalidPage:return api_error('页码无效')
    return private({'accounts':[account_data(user) for user in page], 'total':page.paginator.count,
        'next_page':page.next_page_number() if page.has_next() else None})


@administrator_required
def update_account(request,user_id):
    if request.method=='GET':
        user=User.objects.filter(pk=user_id).exclude(first_name='CLUB_TEST_SANDBOX').first()
        if not user:return api_error('账号不存在',404)
        return private(account_detail(user))
    if request.method!='PATCH':return api_error('仅支持 GET 或 PATCH',405)
    data=body(request)
    if not isinstance(data,dict):return api_error('账号设置格式无效')
    try:
        with transaction.atomic():
            user=User.objects.select_for_update().filter(pk=user_id).first()
            if not user:return api_error('账号不存在',404)
            if user.is_superuser or user.first_name=='CLUB_TEST_SANDBOX' or AccountClosure.objects.filter(user=user).exists():
                return api_error('该账号不可在此修改',403)
            if data.get('action')=='balance':
                value=data.get('balance')
                if type(value) is not int or not -2147483648<=value<=2147483647:return api_error('余额需为 -2147483648 至 2147483647 的整数')
                wallet,_=CurrencyBalance.objects.get_or_create(user=user,defaults={'balance':0})
                wallet=CurrencyBalance.objects.select_for_update().get(pk=wallet.pk)
                if type(data.get('expected_balance')) is not int or wallet.balance!=data['expected_balance']:return api_error('余额已变化，请刷新重试',409)
                from django.contrib.admin.models import LogEntry,CHANGE
                from django.contrib.contenttypes.models import ContentType
                delta=value-wallet.balance;wallet.balance=value;wallet.save(update_fields=['balance','updated_at'])
                LogEntry.objects.create(user=request.user,content_type=ContentType.objects.get_for_model(User),object_id=str(user.pk),object_repr=user.username,action_flag=CHANGE,change_message=f'全局 Coins 调整 {delta:+d}，余额 {value}')
                if delta:
                    member=user.team_memberships.order_by('-is_active','pk').first()
                    CurrencyTransaction.objects.create(user=user,team=member.team if member else None,member=member,amount=delta,balance_after=value,transaction_type='admin_adjust',description='全局账号管理：调整余额',created_by=request.user)
                return private(account_detail(user))
            account,password=data.get('account'),data.get('password','')
            if not isinstance(account,str) or not 3<=len(account.strip())<=150:return api_error('账号需为 3–150 位')
            account=account.strip()
            if account.casefold()=='admin' or account.startswith(('__club_test_','closed_')):return api_error('账号名称为系统保留')
            User._meta.get_field('username').run_validators(account)
            if not isinstance(password,str) or len(password)>128:return api_error('新密码格式无效')
            user.username=account
            if password:
                if len(password)<8:return api_error('新密码至少 8 位')
                validate_password(password,user=user);user.set_password(password)
            user.save(update_fields=['username','password'] if password else ['username'])
    except ValidationError as exc:return api_error('; '.join(exc.messages))
    except IntegrityError:return api_error('账号已被使用',409)
    return private(account_data(user))


@transaction.atomic
def close_user(user_id,actor):
    user=User.objects.select_for_update().get(pk=user_id)
    if user.is_superuser or user.first_name=='CLUB_TEST_SANDBOX':raise ValueError('不能注销系统管理员或内部测试身份')
    if AccountClosure.objects.filter(user=user).exists():return False
    list(Semester.objects.select_for_update().filter(
        team_id__in=user.team_memberships.values('team_id')).order_by('pk'))
    memberships=list(TeamMembership.objects.select_for_update().filter(user=user).order_by('pk'))
    for member in memberships:
        name=f'已注销用户·{user.pk}-{member.pk}'
        while TeamMembership.objects.filter(team_id=member.team_id,display_name=name).exclude(pk=member.pk).exists():name='已注销用户·'+uuid.uuid4().hex[:12]
        member.display_name=name;member.is_active=False;member.role='member';member.member_title=[]
        member.save(update_fields=['display_name','is_active','role','member_title'])
        SemesterMemberTotal.objects.filter(member=member).update(display_name=name)
    profile=UserProfile.objects.filter(user=user).first()
    if profile and profile.avatar:
        from .avatar_images import thumbnail_name
        for name in (profile.avatar.name,thumbnail_name(profile.avatar.name)):
            if name:FileDeletion.objects.get_or_create(name=name)
        profile.avatar='';profile.save(update_fields=['avatar'])
    user.platform_bindings.all().delete()
    # Keep historical reward proofs, clearing reusable public-account snapshots.
    user.contest_participations.update(account='',source_data={},sync_error='')
    pending=list(SubmissionReport.objects.filter(reporter=user,status='pending').values_list('pk',flat=True))
    SubmissionReport.objects.filter(pk__in=pending).update(status='cancelled',resolved_at=timezone.now())
    AstrBotNotification.objects.filter(payload__report_id__in=pending,delivered_at__isnull=True).update(cancelled_at=timezone.now())
    user.username='closed_'+uuid.uuid4().hex;user.email='';user.first_name='';user.last_name=''
    user.is_active=False;user.set_unusable_password();user.save(update_fields=['username','email','first_name','last_name','is_active','password'])
    user.groups.clear()
    AccountClosure.objects.create(user=user,closed_by=actor)
    return True


@api_login_required
def close_account(request,user_id=None):
    if request.method!='POST':return api_error('仅支持 POST',405)
    if getattr(request,'admin_test_mode',False):return api_error('请退出测试模式后管理全局账号',403)
    admin=user_id is not None
    if admin and not request.user.is_superuser:return api_error('仅系统管理员可注销其他账号',403)
    data=body(request)
    if not isinstance(data,dict):return api_error('注销请求格式无效')
    if data.get('confirmation')!='注销账号':return api_error('请输入“注销账号”确认')
    password=data.get('admin_password' if admin else 'password')
    if not isinstance(password,str) or not request.user.check_password(password):return api_error('当前密码不正确',403)
    target=User.objects.filter(pk=user_id if admin else request.user.pk).first()
    if not target:return api_error('账号不存在',404)
    try:
        with transaction.atomic():
            target=User.objects.select_for_update().get(pk=target.pk)
            if admin and data.get('account')!=target.username:return api_error('账号信息已变化，请刷新后重试',409)
            close_user(target.pk,request.user)
    except ValueError as exc:return api_error(str(exc),403)
    if not admin:logout(request)
    return private({'ok':True,'logout':not admin})


def account_detail(user):
    data=account_data(user)
    data['inventory']=list(UserInventory.objects.filter(member__user=user).select_related('item','team').values('id','item_id','quantity','item__name','item__item_type','team__name'))
    data['units']=list(ShopFulfillment.objects.filter(purchase__member__user=user).values('id','item_name','status','purchase__team__name'))
    teams=list(user.team_memberships.values_list('team_id',flat=True))
    data['items']=list(ShopItem.objects.filter(team_id__in=teams,is_active=True).values('id','name','team_id','team__name'))
    return data


@administrator_required
def account_inventory(request,user_id):
    if request.method!='POST':return api_error('仅支持 POST',405)
    user=User.objects.filter(pk=user_id,is_active=True,is_superuser=False).exclude(first_name='CLUB_TEST_SANDBOX').first()
    if not user:return api_error('账号不存在或已停用',404)
    data=body(request)
    if not isinstance(data,dict):return api_error('背包请求格式无效')
    from .currency_services import positive_id
    try:
        for key in ('inventory_id','unit_id','item_id'):
            if key in data:data[key]=positive_id(data[key])
    except ValueError as exc:return api_error(str(exc))
    member=None
    if data.get('action')=='quantity':
        inv=UserInventory.objects.filter(pk=data.get('inventory_id'),member__user=user).select_related('member').first()
        member=inv.member if inv else None
    elif data.get('action')=='revoke':
        unit=ShopFulfillment.objects.filter(pk=data.get('unit_id'),purchase__member__user=user).select_related('purchase__member').first()
        member=unit.purchase.member if unit else None
    elif data.get('action')=='grant':
        item=ShopItem.objects.filter(pk=data.get('item_id')).first()
        member=user.team_memberships.filter(team_id=item.team_id).first() if item else None
    if not member:return api_error('未找到该账号的物品或对应团队身份',404)
    from .member_management import inventory_settings
    request.global_inventory_user_id=user.pk
    response=inventory_settings(request,member.team_id,member.pk)
    return private(account_detail(user)) if response.status_code==200 else response
