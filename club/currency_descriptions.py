"""Tip ledgers retain submission references without storing identity snapshots."""
import re


def transaction_description(kind, description='', *, submission_id=None):
    if kind not in {'tip_sent','tip_received'}:
        return description
    if submission_id is None:
        matches=re.findall(r'提交\s*#([0-9]+)',description)
        submission_id=matches[-1] if matches else None
    if submission_id is None:
        return '打赏支出' if kind=='tip_sent' else '收到打赏'
    return f'打赏提交 #{submission_id}' if kind=='tip_sent' else f'收到提交 #{submission_id} 的打赏'
