"""Authenticated, team-scoped poker API with private card projections."""
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import CurrencyBalance, PokerRoom, PokerSeat, TeamMembership
from .views import api_error, api_login_required, body, membership_for
from . import poker_services as poker


def context(request):
    member = membership_for(request)
    if not member or not member.pk or request.user.is_superuser:
        raise ValueError('请使用已加入团队的成员账号进入游戏')
    return member


def response_data(room, member):
    return {'room': poker.room_data(room, member.user_id), 'user_id': member.user_id,
            'balance': CurrencyBalance.objects.filter(user_id=member.user_id).values_list('balance', flat=True).first() or 0,
            'server_time': timezone.now().timestamp()}


@api_login_required
@require_http_methods(['GET', 'POST'])
def rooms(request):
    try:
        member = context(request)
        if request.method == 'POST':
            with transaction.atomic():
                User.objects.select_for_update().get(pk=request.user.pk)
                member = TeamMembership.objects.select_for_update(of=('self',)).select_related('team').get(pk=member.pk, is_active=True)
                room = poker.create_room(member, body(request))
                payload = response_data(room, member)
            return JsonResponse(payload)
        own = PokerSeat.objects.select_related('room').filter(user_id=request.user.pk).first()
        return JsonResponse({'enabled': member.team.currency_enabled, 'user_id': request.user.pk,
            'balance': CurrencyBalance.objects.filter(user_id=request.user.pk).values_list('balance', flat=True).first() or 0,
            'current_room': str(own.room_id) if own and own.room.team_id == member.team_id else None,
            'seated_elsewhere': bool(own and own.room.team_id != member.team_id),
            'rooms': [{'id': str(r.pk), 'name': r.name, 'mode': r.mode, 'max_players': r.max_players,
                       'players': r.seats.count(), 'buy_in': r.buy_in, 'big_blind': r.big_blind,
                       'playing': poker.active(r)} for r in PokerRoom.objects.filter(
                           Q(mode__in=['coins', 'friendly']) | Q(created_by_id=request.user.pk),
                           team=member.team, closed=False).distinct().prefetch_related('seats').order_by('created_at')]})
    except (ValueError, TeamMembership.DoesNotExist) as exc:
        return api_error(str(exc) or '成员信息已失效', 400)


@api_login_required
@require_http_methods(['GET', 'POST'])
def room(request, room_id):
    try:
        member = context(request)
        with transaction.atomic():
            # Same user cannot buy into two rooms in simultaneous requests.
            User.objects.select_for_update().get(pk=request.user.pk)
            member = TeamMembership.objects.select_for_update(of=('self',)).select_related('team').get(pk=member.pk, is_active=True)
            current = PokerRoom.objects.select_for_update().filter(pk=room_id, team_id=member.team_id).first()
            if not current:
                return api_error('房间不存在或无权访问', 404)
            if current.mode == 'practice' and current.created_by_id != request.user.pk:
                return api_error('这是个人练习房间', 404)
            PokerSeat.objects.filter(room=current, user_id=request.user.pk, leaving=False).update(last_seen=timezone.now())
            poker.tick(current)
            if request.method == 'POST':
                # A rejected stale action must not roll back an already due timeout.
                try:
                    with transaction.atomic():
                        poker.operate(current, member, body(request))
                except ValueError as exc:
                    return api_error(str(exc), 409)
            payload = response_data(current, member)
        response = JsonResponse(payload)
        response['Cache-Control'] = 'private, no-store'
        return response
    except (ValueError, TeamMembership.DoesNotExist) as exc:
        return api_error(str(exc) or '成员信息已失效', 400)
