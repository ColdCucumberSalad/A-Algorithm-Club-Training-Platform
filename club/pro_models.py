"""Card verification state, separate from shop stock and browser sessions."""
from django.conf import settings
from django.db import models


class AppRateLimit(models.Model):
    # No raw usernames, addresses or credentials in the throttle ledger.
    key = models.CharField(max_length=64, primary_key=True)
    window_start = models.DateTimeField(db_index=True)
    attempts = models.PositiveIntegerField(default=0)


class ProRedeemCode(models.Model):
    fulfillment = models.OneToOneField('club.ShopFulfillment', on_delete=models.PROTECT, related_name='pro_code')
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='pro_codes')
    app = models.CharField(max_length=40)
    duration_days = models.PositiveIntegerField()
    code_hash = models.CharField(max_length=64, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    consumed_at = models.DateTimeField(null=True, blank=True)
