"""Issue shop cards with a purchased duration snapshot."""
import hashlib
import secrets

from .models import ProRedeemCode
from .problem_parser import key_cipher

APP_KEY = 'rbc_helper'
MAX_DURATION_DAYS = 36500


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def issue_code(unit, owner):
    if unit.pro_app != APP_KEY or not unit.pro_duration_days:
        raise ValueError('Pro 商品配置无效，请联系管理员')
    code = 'RBC-' + secrets.token_hex(24).upper()
    ProRedeemCode.objects.create(fulfillment=unit, owner=owner, app=unit.pro_app,
        duration_days=unit.pro_duration_days, code_hash=fingerprint(code))
    # The shop fulfillment is the sole encrypted recoverable copy, visible to its buyer.
    unit.encrypted_code = key_cipher().encrypt(code.encode()).decode()
    return code
