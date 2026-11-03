"""Global application access, separate from shop stock and browser sessions."""
from django.conf import settings
from django.db import models


class AppAccessToken(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='app_tokens')
    token_hash = models.CharField(max_length=64, unique=True)
    auth_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class AppRateLimit(models.Model):
    # No raw usernames, addresses or credentials in the throttle ledger.
    key = models.CharField(max_length=64, primary_key=True)
    window_start = models.DateTimeField(db_index=True)
    attempts = models.PositiveIntegerField(default=0)


class ProEntitlement(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='pro_entitlements')
    app = models.CharField(max_length=40)
    expires_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'app'], name='unique_user_pro_app')]


class ProRedeemCode(models.Model):
    device_hash = models.CharField(max_length=64, blank=True)
    fulfillment = models.OneToOneField('club.ShopFulfillment', on_delete=models.PROTECT, related_name='pro_code')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='pro_codes')
    app = models.CharField(max_length=40)
    duration_days = models.PositiveIntegerField()
    code_hash = models.CharField(max_length=64, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    redeemed_at = models.DateTimeField(null=True, blank=True)


class ProAudit(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='pro_audits')
    app = models.CharField(max_length=40)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    action = models.CharField(max_length=24)
    request_id = models.UUIDField(unique=True)
    # Store the exact command for safe administrative request replay.
    command = models.JSONField(default=dict)
    code = models.OneToOneField(ProRedeemCode, on_delete=models.PROTECT, null=True, blank=True)
    before_expires_at = models.DateTimeField(null=True, blank=True)
    after_expires_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']
