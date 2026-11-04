from django.contrib.auth.models import User
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .views import api_login_required,api_error,body,membership_for
from .models import TeamMembership,UserProfile
from . import cosmetics


@api_login_required
@require_http_methods(['GET','POST'])
@transaction.atomic
def library(request):
    if request.method=='POST':
        # Same user lock used by shop purchases/admin inventory grants.
        User.objects.select_for_update().get(pk=request.user.pk)
        data=body(request);kind=data.get('kind');key=data.get('key','')
        if kind not in ('theme','badge','frame') or not isinstance(key,str):
            return api_error('外观选择无效')
        if key and key not in cosmetics.owned_keys(request.user.pk,kind):
            return api_error('尚未拥有该外观，或物品已被收回',409)
        if kind in ('badge','frame'):
            member=membership_for(request)
            if not member or not member.pk:return api_error('请先加入团队',403)
            member=TeamMembership.objects.select_for_update().get(pk=member.pk,is_active=True)
            field='worn_badge' if kind=='badge' else 'worn_avatar_frame'
            setattr(member,field,key);member.save(update_fields=[field])
        else:
            profile,_=UserProfile.objects.get_or_create(user=request.user)
            profile.active_theme=key;profile.save(update_fields=['active_theme'])
    member=membership_for(request)
    response=JsonResponse({**cosmetics.state(request.user),'badge':cosmetics.badge_data(member) if member else None,'avatar_frame':cosmetics.frame_data(member) if member else None})
    response['Cache-Control']='private, no-store'
    return response
