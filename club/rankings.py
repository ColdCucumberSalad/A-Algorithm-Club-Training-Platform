from .cosmetics import badge_data,frame_data
"""Team-scoped rankings built solely from stored account and activity data."""
import math
from collections import defaultdict
from datetime import timedelta
from django.utils import timezone
from .models import TeamMembership, CheckinRecord, Submission, PlatformBinding, CurrencyBalance
from .member_titles import title_data, titles_data
from .grades import cohort_data

RATING_PLATFORMS = {
    'codeforces':'Codeforces', 'atcoder':'AtCoder', 'nowcoder':'牛客', 'luogu':'洛谷',
    'leetcode_cn':'LeetCode 中国站', 'leetcode_us':'LeetCode 国际站',
}


def ranking_data(member, scope, platform='codeforces', period='semester'):
    if scope == 'solved' and period not in {'semester', 'all'}:
        raise ValueError('请选择学期榜或总榜')
    semester = None
    members = list(TeamMembership.objects.filter(team=member.team, is_active=True,
        user__is_active=True, user__is_superuser=False).order_by('id'))
    from .models import UserProfile
    from .avatar_images import url_for
    profiles = {p.user_id: p for p in UserProfile.objects.filter(user_id__in=[m.user_id for m in members])}
    if scope == 'wealth':
        from .grades import grade_on
        members = [m for m in members if grade_on(profiles.get(m.user_id)) != 4]
    cosmetic_members=[m for m in members if m.worn_badge or m.worn_avatar_frame]
    if cosmetic_members:
        from .models import CosmeticGrant
        from .cosmetic_terms import active_term
        cached=defaultdict(dict)
        for user_id,kind,key,end in CosmeticGrant.objects.filter(active_term(),user_id__in=[m.user_id for m in cosmetic_members],kind__in=['badge','frame'],inventory__quantity__gt=0).values_list('user_id','kind','key','expires_at'):
            slot=(kind,key)
            if slot not in cached[user_id] or cached[user_id][slot] is not None and (end is None or end>cached[user_id][slot]):cached[user_id][slot]=end
        for m in cosmetic_members:m._cosmetic_owned=cached[m.user_id]
    rows = {m.pk: {'memberId':m.pk, 'name':m.display_name, 'title':title_data(m), 'titles':titles_data(m), 'badge':badge_data(m),'avatar_frame':frame_data(m), 'cohort':cohort_data(profiles.get(m.user_id)), 'isCurrent':m.pk==member.pk,
        'avatar':url_for(profiles.get(m.user_id), m.pk, 'small')} for m in members}
    if scope == 'checkin':
        days = defaultdict(set)
        for mid, day in CheckinRecord.objects.filter(member_id__in=rows, checkin_date__lte=timezone.localdate()).values_list('member_id','checkin_date'):
            days[mid].add(day)
        for mid, day in Submission.objects.filter(member_id__in=rows, is_valid=True, record_date__lte=timezone.localdate()).values_list('member_id','record_date'):
            days[mid].add(day)
        today = timezone.localdate()
        for mid, row in rows.items():
            cursor = today if today in days[mid] else today-timedelta(days=1)
            streak = 0
            while cursor in days[mid]:
                streak += 1
                cursor -= timedelta(days=1)
            row.update(value=streak, unit='天', detail='当前连续签到')
    elif scope == 'solved':
        from .solved import lifetime_solved_counts, semester_solved_counts
        ids = [m.user_id for m in members]
        if period == 'all':
            totals = lifetime_solved_counts(ids)
        else:
            from .views import active_semester
            semester = active_semester(member.team)
            totals = semester_solved_counts(ids, semester)
        for m in members:
            rows[m.pk].update(value=totals.get(m.user_id, 0), unit='题', detail='累计过题' if period == 'all' else '本学期过题')
    elif scope == 'wealth':
        wallets = dict(CurrencyBalance.objects.filter(user_id__in=[m.user_id for m in members]).values_list('user_id','balance'))
        balances = {m.pk:wallets.get(m.user_id,0) for m in members}
        for mid,row in rows.items(): row.update(value=balances.get(mid,0), unit='RBC Coins', detail='当前余额')
    else:
        if platform not in RATING_PLATFORMS:
            raise ValueError('请选择有效的竞赛平台')
        db_platform = 'leetcode' if platform.startswith('leetcode_') else platform
        bindings = PlatformBinding.objects.filter(user_id__in=[m.user_id for m in members],platform=db_platform)
        if platform == 'leetcode_cn': bindings = bindings.filter(account__startswith='cn:')
        if platform == 'leetcode_us': bindings = bindings.exclude(account__startswith='cn:')
        selected = {}
        for binding in bindings.order_by('id'):
            value = (binding.snapshot or {}).get('rating')
            try:
                value = float(value)
                if isinstance((binding.snapshot or {}).get('rating'), bool) or not math.isfinite(value) or value < 0:
                    continue
            except (TypeError, ValueError):
                continue
            previous = selected.get(binding.user_id)
            if previous is None or value > float(previous.snapshot['rating']):
                selected[binding.user_id] = binding
        # Keep unrated members visible when they have a binding.
        for binding in bindings.order_by('id'):
            selected.setdefault(binding.user_id, binding)
        bindings = selected
        for m in members:
            binding = bindings.get(m.user_id)
            if not binding:
                del rows[m.pk]
                continue
            value = (binding.snapshot or {}).get('rating')
            try:
                if isinstance(value,bool): raise ValueError()
                value = float(value)
                if not math.isfinite(value) or value < 0: raise ValueError()
                value = round(value,2)
                if value.is_integer(): value = int(value)
            except (TypeError,ValueError,OverflowError): value = None
            rows[m.pk].update(value=value, unit='Rating', detail=binding.account,
                synced_at=binding.synced_at.isoformat() if binding.synced_at else None)
    result = sorted(rows.values(),key=lambda r:(r['value'] is None, -(r['value'] or 0),r['name'].casefold(),r['memberId']))
    last = object(); rank = None
    for index,row in enumerate(result,1):
        if row['value'] is None: row['rank'] = None
        else:
            if row['value'] != last: rank = index
            row['rank'] = rank
            last = row['value']
    return {'scope':scope, 'platform':platform if scope=='rating' else None,
            'period':period if scope=='solved' else None,
            'semester':{'id':semester.pk, 'name':semester.name, 'start':semester.starts_on.isoformat(), 'end':semester.ends_on.isoformat()} if semester else None,
            'platforms':RATING_PLATFORMS, 'rows':result}
