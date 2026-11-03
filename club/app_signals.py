"""Disabling an account permanently revokes its issued native app tokens."""
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import AppAccessToken


@receiver(post_save, sender=User)
def revoke_disabled_app_tokens(sender, instance, raw=False, using='default', **kwargs):
    if not raw and not instance.is_active:
        AppAccessToken.objects.using(using).filter(user_id=instance.pk, revoked_at__isnull=True).update(revoked_at=timezone.now())
