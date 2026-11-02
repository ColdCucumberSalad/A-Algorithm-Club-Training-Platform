"""Tip ledgers retain submission references without storing identity snapshots."""
import re


def transaction_description(kind, description='', *, submission_id=None, counterparty_name=None):
    if kind not in {'tip_sent','tip_received'}:
        return description
    if submission_id is None:
        matches=re.findall(r'提交\s*#([0-9]+)',description)
        submission_id=matches[-1] if matches else None
    if submission_id is None:
        if counterparty_name:
            return f'打赏 {counterparty_name}' if kind=='tip_sent' else f'收到 {counterparty_name} 的打赏'
        return '打赏支出' if kind=='tip_sent' else '收到打赏'
    if counterparty_name:
        return (f'打赏 {counterparty_name} 的提交 #{submission_id}' if kind=='tip_sent'
            else f'收到 {counterparty_name} 对提交 #{submission_id} 的打赏')
    return f'打赏提交 #{submission_id}' if kind=='tip_sent' else f'收到提交 #{submission_id} 的打赏'


def ledger_description(entry):
    if entry.transaction_type not in {'tip_sent','tip_received'} or not entry.tip_id:
        return transaction_description(entry.transaction_type,entry.description)
    tip=entry.tip
    member=tip.sender if entry.transaction_type=='tip_received' else tip.recipient
    user=member.user if member else (tip.sender_user if entry.transaction_type=='tip_received' else None)
    if user and (not user.is_active or hasattr(user,'account_closure')):
        name='已注销用户'
    else:
        name=member.display_name if member else '原团队成员'
    return transaction_description(entry.transaction_type,entry.description,
        submission_id=tip.submission_id,counterparty_name=name)
