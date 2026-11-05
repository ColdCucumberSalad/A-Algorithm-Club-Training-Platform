from .cosmetic_terms import active_term,purchase_terms
"""Permanent shop titles are account-owned; wearing remains a team choice."""
from django.db.models import Q
from .member_titles import validate_title
from .models import OwnedTitle, UserInventory


def ensure_available(user_id, item, quantity):
    if quantity != 1:
        raise ValueError('称号每次只能获得一件')
    definition = validate_title(item.title_definition)
    if not definition:
        raise ValueError('商品尚未配置称号，请联系管理员')
    if OwnedTitle.objects.filter(active_term(),user_id=user_id, inventory__quantity__gt=0,expires_at__isnull=True).filter(Q(item=item) | Q(text=definition['text'])).exists():
        raise ValueError('已拥有该称号，无需重复购买或发放')
    return definition


def award(member, item, quantity, purchase=None):
    definition = ensure_available(member.user_id, item, quantity)
    from django.utils import timezone
    from datetime import timedelta
    now=timezone.now()
    prior=OwnedTitle.objects.select_related('inventory').filter(user_id=member.user_id,text=definition['text']).first()
    prior_valid=prior and prior.inventory.quantity>0 and (prior.expires_at is None or prior.expires_at>now)
    inventory, _ = UserInventory.objects.get_or_create(team=item.team, member=member, item=item)
    inventory.quantity = 1
    inventory.save(update_fields=['quantity'])
    if prior and prior.inventory_id!=inventory.pk:UserInventory.objects.filter(pk=prior.inventory_id).update(quantity=0)
    days=item.cosmetic_duration_days
    expires=max(now,prior.expires_at if prior_valid and prior.expires_at else now)+timedelta(days=days) if days else None
    if purchase:
        purchase.cosmetic_expires_at=expires;purchase.save(update_fields=['cosmetic_expires_at'])
    OwnedTitle.objects.update_or_create(user_id=member.user_id, text=definition['text'],
        defaults={'item':item,'inventory':inventory,'definition':definition,'expires_at':expires})
