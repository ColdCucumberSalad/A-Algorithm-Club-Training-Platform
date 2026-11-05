from datetime import timedelta
from django.db.models import Q
from django.utils import timezone


def active_term(now=None):
    return Q(expires_at__isnull=True)|Q(expires_at__gt=now or timezone.now())


def purchase_terms(item,now=None):
    days=item.cosmetic_duration_days if item.item_type in ('title','theme','badge','frame','cosmetic') else 0
    if type(days) is not int or not 0<=days<=36500:
        raise ValueError('有效时长需为 0（永久）或 1–36500 天')
    return {'cosmetic_duration_days':days,
            'cosmetic_expires_at':(now or timezone.now())+timedelta(days=days) if days else None}
