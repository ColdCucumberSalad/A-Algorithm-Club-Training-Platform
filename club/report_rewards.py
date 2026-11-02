"""Optional, version-bound report decisions settle global Coins atomically."""
from .models import CurrencyBalance,CurrencyTransaction,TeamMembership


def validate_settings(data, reports, author_id):
    if not isinstance(data,dict) or set(data)-{'reward_each','author_penalty','reporter_ids'}:
        raise ValueError('举报 Coins 设置格式无效')
    reward,penalty=data.get('reward_each',1),data.get('author_penalty',1)
    if any(type(value) is not int or not 0<=value<=100 for value in (reward,penalty)):
        raise ValueError('举报奖励和扣除金额需为 0–100 的整数，0 表示不调整')
    selected=data.get('reporter_ids')
    eligible={report.reporter_id for report in reports if report.reporter.is_active and report.reporter_id!=author_id}
    if not isinstance(selected,list) or any(type(uid) is not int for uid in selected) or not set(selected)<=eligible:
        raise ValueError('奖励名单已变化或含无效举报者，请重新打开举报窗口')
    return {'reward_each':reward,'author_penalty':penalty,'reporter_ids':sorted(set(selected))}


def settle(target,settings,actor):
    # Caller holds every involved account lock, followed by semester/submission locks.
    deltas={uid:settings['reward_each'] for uid in settings['reporter_ids'] if settings['reward_each']}
    if settings['author_penalty']:deltas[target.member.user_id]=-settings['author_penalty']
    wallets={}
    for uid in sorted(deltas):
        wallet,_=CurrencyBalance.objects.get_or_create(user_id=uid,defaults={'balance':0})
        wallet=CurrencyBalance.objects.select_for_update().get(pk=wallet.pk)
        if not -2147483648<=wallet.balance+deltas[uid]<=2147483647:
            raise ValueError('举报 Coins 调整超出余额范围，本次处理未保存')
        wallets[uid]=wallet
    members={member.user_id:member for member in TeamMembership.objects.filter(team=target.team,user_id__in=deltas)}
    for uid,delta in deltas.items():
        wallet=wallets[uid];wallet.balance+=delta;wallet.save(update_fields=['balance','updated_at'])
        CurrencyTransaction.objects.create(user_id=uid,team=target.team,member=members.get(uid),
            amount=delta,balance_after=wallet.balance,created_by=actor,
            transaction_type='report_reward' if delta>0 else 'report_penalty',
            description=f'提交 #{target.pk} 版本 {target.version} 举报成立：'+('有效举报奖励' if delta>0 else '被举报扣除'))
    return {**settings,'rewarded_count':len(settings['reporter_ids']) if settings['reward_each'] else 0,
        'reward_total':settings['reward_each']*len(settings['reporter_ids'])}
