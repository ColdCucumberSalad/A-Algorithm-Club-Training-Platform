from django.core.paginator import Paginator
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, F, Max, Q
from django.http import JsonResponse
from django.utils import timezone

from .models import Problem, ReviewLog, Semester, Submission, SubmissionLike, SubmissionPart, SubmissionReport, Week
from .services import refresh_totals
from .views import api_error, api_login_required, membership_for, active_semester, active_week, serialize_submission, body


def page_items(request, queryset, size=20):
    try:
        number = int(request.GET.get('page', '1'))
        if number < 1:
            raise ValueError()
    except ValueError:
        return None
    pager = Paginator(queryset, size)
    page = pager.get_page(number)
    return page


@api_login_required
def showcase(request):
    if request.method != 'GET':
        return api_error('仅支持GET', 405)
    member = membership_for(request)
    if not member:
        return api_error('未加入当前团队', 403)
    if request.GET.get('all') == '1':
        return showcase_all(request, member)
    selected = request.GET.get('week')
    semester = active_semester(member.team)
    current_week = active_week(semester) if semester else None
    weeks = Week.objects.filter(semester__team=member.team, semester__archived_at__isnull=True,
                                starts_at__lte=timezone.now()).select_related('semester').order_by('-starts_at')
    if selected:
        if not selected.isdigit():
            return api_error('周次编号无效')
        week = weeks.filter(pk=selected).first()
        if not week:
            return api_error('周次不存在', 404)
    else:
        week = current_week or weeks.first()
    items = Submission.objects.filter(team=member.team, week=week, is_valid=True, semester__archived_at__isnull=True, problem__isnull=False)
    query = request.GET.get('q', '').strip()[:200]
    if query:
        items = items.filter(Q(problem__title__icontains=query) | Q(problem__url__icontains=query) | Q(member__display_name__icontains=query))
    grouped = items.values('problem_id', 'problem__url', 'problem__title').annotate(count=Count('id'), latest=Max('submitted_at')).order_by('-latest', '-problem_id')
    page = page_items(request, grouped)
    if page is None:
        return api_error('页码无效')
    groups = list(page.object_list)
    names = {}
    for pid, name in items.filter(problem_id__in=[g['problem_id'] for g in groups]).values_list('problem_id', 'member__display_name').distinct():
        names.setdefault(pid, []).append(name)
    return JsonResponse({'week': week.pk if week else None,
        'current_week': current_week.pk if current_week else None,
        'weeks': [{'id': w.pk, 'label': f'{w.semester.name} · 第{w.number}周'} for w in weeks],
        'problems': [{'id': g['problem_id'], 'title': g['problem__title'] or g['problem__url'], 'url': g['problem__url'], 'count': g['count'], 'members': sorted(names.get(g['problem_id'], []))} for g in groups],
        'next': page.next_page_number() if page.has_next() else None})


def showcase_all(request, member):
    """All visible weeks; the sandbox adds only this administrator's records."""
    sandbox = bool(getattr(request, 'admin_test_mode', False))
    team = request.test_target_team if sandbox else member.team
    scope = Q(team=team)
    if sandbox:
        scope |= Q(member=member)
    items = Submission.objects.filter(scope, is_valid=True,
        semester__archived_at__isnull=True, problem__isnull=False).select_related('week', 'semester', 'problem', 'member').order_by('-record_date', '-submitted_at', '-id')
    real_weeks = list(Week.objects.filter(semester__team=team,
        semester__archived_at__isnull=True).select_related('semester').order_by('-starts_at'))
    query = request.GET.get('q', '').strip()[:200].casefold()
    groups = {}
    for item in items:
        week = item.week
        private = sandbox and item.team_id != team.pk
        if private:
            week = next((w for w in real_weeks if timezone.localdate(w.starts_at) <= item.record_date < timezone.localdate(w.ends_at)), None)
            if week is None:
                continue
        name = '管理员' if private else item.member.display_name
        key = (week.pk, item.problem_id)
        row = groups.setdefault(key, {'id': item.problem_id,
            'title': item.problem.title or item.problem.url,
            'url': item.problem.url, 'count': 0, 'members': set(),
            'week_id': week.pk, 'week_label': f'{week.semester.name} · 第{week.number}周',
            '_starts': week.starts_at, '_latest': item.submitted_at})
        row['count'] += 1
        row['members'].add(name)
    rows = sorted(groups.values(), key=lambda row: (row['_starts'], row['_latest'], row['id']), reverse=True)
    if query:
        rows = [row for row in rows if query in ' '.join([row['title'], row['url'], row['week_label'], *row['members']]).casefold()]
    page = page_items(request, rows)
    if page is None:
        return api_error('页码无效')
    result = []
    for row in page:
        result.append({key: sorted(value) if key == 'members' else value for key, value in row.items() if not key.startswith('_')})
    return JsonResponse({'problems': result, 'next': page.next_page_number() if page.has_next() else None})


def community_submission(item, viewer):
    data = serialize_submission(item)
    data.update(likes=item.likes.count(), liked=item.likes.filter(user=viewer.user).exists(),
                can_tip=bool(viewer.pk and viewer.is_active and viewer.team.currency_enabled and item.member.is_active and item.member.user_id != viewer.user_id and not item.semester.archived_at),
                reported=item.reports.filter(version=item.version, reporter=viewer.user).exists(),
                own=item.member.user_id == viewer.user_id, can_reject=viewer.is_admin and item.member.user_id != viewer.user_id and not item.semester.archived_at, archived=bool(item.semester.archived_at))
    return data


@api_login_required
def problem_submissions(request, problem_id):
    if request.method != 'GET':
        return api_error('仅支持GET', 405)
    member = membership_for(request)
    if not member:
        return api_error('未加入当前团队', 403)
    items = Submission.objects.filter(team=member.team, problem_id=problem_id, is_valid=True, semester__archived_at__isnull=True).select_related('problem', 'member', 'week', 'semester').prefetch_related('parts', 'likes', 'reports').order_by('-record_date', '-submitted_at', '-id')
    if not items.exists():
        return api_error('该题目不存在或没有可见提交', 404)
    problem = items.first().problem
    query = request.GET.get('q', '').strip()[:200]
    if query:
        items = items.filter(Q(problem__title__icontains=query) | Q(problem__url__icontains=query) | Q(member__display_name__icontains=query))
    page = page_items(request, items)
    if page is None:
        return api_error('页码无效')
    return JsonResponse({'problem': {'id': problem.pk, 'title': problem.title or problem.url, 'url': problem.url},
                         'submissions': [community_submission(s, member) for s in page],
                         'next': page.next_page_number() if page.has_next() else None})


@api_login_required
@transaction.atomic
def tip_submission(request, submission_id):
    import uuid
    from .models import TeamMembership, SubmissionTip, CurrencyBalance
    from .currency_services import get_or_create_balance, deduct_currency, add_currency
    if request.method != 'POST':
        return api_error('仅支持 POST',405)
    member=membership_for(request)
    if not member or not member.pk or request.user.is_superuser:
        return api_error('仅团队成员可打赏',403)
    data=body(request);amount=data.get('amount')
    if type(amount) is not int or not 1 <= amount <= 2147483647:
        return api_error('打赏数量必须为正整数',400)
    try:
        token=uuid.UUID(str(data.get('request_id','')))
    except ValueError:
        return api_error('打赏请求编号无效，请重新打开弹窗',400)
    target=Submission.objects.filter(pk=submission_id,team_id=member.team_id).first()
    if not target:return api_error('提交不存在',404)
    Semester.objects.select_for_update().get(pk=target.semester_id)
    target=Submission.objects.select_for_update().filter(pk=submission_id,team_id=member.team_id).first()
    if not target:return api_error('提交不存在',404)
    members=list(TeamMembership.objects.select_for_update().filter(pk__in=[member.pk,target.member_id]).order_by('pk'))
    sender=next((m for m in members if m.pk==member.pk),None)
    recipient=next((m for m in members if m.pk==target.member_id),None)
    prior=SubmissionTip.objects.filter(request_id=token).first()
    if prior:
        if prior.sender_user_id!=request.user.pk or prior.submission_id!=target.pk or prior.amount!=amount:
            return api_error('打赏请求编号已被使用',409)
        return JsonResponse({'ok':True,'amount':prior.amount,'duplicate':True})
    if not sender or not recipient or not sender.is_active or not recipient.is_active or recipient.user_id==sender.user_id:
        return api_error('不能打赏自己或已退出的成员',403)
    if not member.team.currency_enabled:
        return api_error('当前团队未启用 RBC Coins',403)
    if not target.is_valid or target.semester.archived_at:
        return api_error('该提交已退回或归档，无法打赏',409)
    balances=[get_or_create_balance(m) for m in members]
    locked={b.member_id:b for b in CurrencyBalance.objects.select_for_update().filter(pk__in=[b.pk for b in balances]).order_by('pk')}
    if locked[sender.pk].balance < amount:
        return api_error('RBC Coins 余额不足',400)
    if locked[recipient.pk].balance+amount > 2147483647:
        return api_error('收款方余额已达上限',400)
    from django.db import IntegrityError
    try:
        with transaction.atomic():
            SubmissionTip.objects.create(request_id=token,team=member.team,sender_user=request.user,sender=sender,recipient=recipient,submission=target,amount=amount)
    except IntegrityError:
        return api_error('打赏请求编号已被使用',409)
    deduct_currency(sender,amount,'tip_sent',f'打赏 {recipient.display_name} 的提交 #{target.pk}')
    add_currency(recipient,amount,'tip_received',f'收到 {sender.display_name} 对提交 #{target.pk} 的打赏')
    return JsonResponse({'ok':True,'amount':amount,'recipient':recipient.display_name})


@api_login_required
@transaction.atomic
def reaction(request, submission_id, kind):
    if request.method not in ({'PUT', 'DELETE'} if kind == 'like' else {'POST'}):
        return api_error('请求方法无效', 405)
    member = membership_for(request)
    if not member:
        return api_error('未加入当前团队', 403)
    target = Submission.objects.filter(pk=submission_id, team=member.team).first()
    if not target:
        return api_error('提交不存在', 404)
    semester = Semester.objects.select_for_update().get(pk=target.semester_id)
    target = Submission.objects.select_for_update().filter(pk=submission_id, is_valid=True).first()
    if not target or semester.archived_at:
        return api_error('提交已退回或归档', 409)
    if target.member_id == member.pk:
        return api_error('不能对自己的提交点赞或举报', 403)
    if kind == 'like':
        if request.method == 'PUT':
            SubmissionLike.objects.get_or_create(submission=target, user=request.user)
        else:
            target.likes.filter(user=request.user).delete()
        return JsonResponse({'ok': True, 'likes': target.likes.count(), 'liked': request.method == 'PUT'})
    report, created = SubmissionReport.objects.get_or_create(submission=target, version=target.version, reporter=request.user)
    if created:
        from .astrbot_notifications import notify_report
        notify_report(report, member)
    return JsonResponse({'ok': True})


@api_login_required
def report_queue(request):
    member = membership_for(request)
    if not request.user.is_superuser and (not member or not member.is_admin):
        return api_error('需要当前团队管理权限', 403)
    if request.method != 'GET':
        return api_error('仅支持GET', 405)
    items = Submission.objects.filter(is_valid=True, semester__archived_at__isnull=True,
        reports__status='pending', reports__version=F('version'))
    if not request.user.is_superuser:
        items = items.filter(team=member.team)
    items = items.distinct().select_related('team', 'problem', 'member', 'week', 'semester').prefetch_related('parts').order_by('submitted_at', 'id')
    query = request.GET.get('q', '').strip()[:200]
    if query:
        items = items.filter(Q(problem__title__icontains=query) | Q(problem__url__icontains=query) | Q(member__display_name__icontains=query))
    page = page_items(request, items)
    if page is None:
        return api_error('页码无效')
    rows = []
    for item in page:
        data = serialize_submission(item)
        data['team_name'] = item.team.name
        data['reports'] = item.reports.filter(status='pending', version=item.version).count()
        data['can_resolve'] = item.member.user_id != request.user.pk
        rows.append(data)
    return JsonResponse({'submissions': rows, 'next': page.next_page_number() if page.has_next() else None})


@api_login_required
@transaction.atomic
def resolve_report(request, submission_id, direct=False):
    if request.method != 'POST':
        return api_error('仅支持POST', 405)
    member = membership_for(request)
    if not request.user.is_superuser and (not member or not member.is_admin):
        return api_error('需要当前团队管理权限', 403)
    targets = Submission.objects.filter(pk=submission_id)
    if not request.user.is_superuser:
        targets = targets.filter(team=member.team)
    target = targets.first()
    if not target:
        return api_error('提交不存在', 404)
    User.objects.select_for_update().get(pk=target.member.user_id)
    from .problem_equivalence import lock_user_semesters, rebalance_submissions
    lock_user_semesters(target.member.user_id, [target.semester_id])
    semester = Semester.objects.select_for_update().get(pk=target.semester_id)
    target = Submission.objects.select_for_update().filter(pk=submission_id).first()
    if not target or semester.archived_at:
        return api_error('材料已清理或学期已归档', 409)
    if target.member.user_id == request.user.pk:
        return api_error('不能处理自己的提交', 403)
    if not target.is_valid:
        return api_error('该提交已退回', 409)
    data = body(request)
    if data.get('version') != target.version:
        return api_error('提交版本已变化，请刷新', 409)
    action = 'reject' if direct else data.get('action')
    note = str(data.get('note', '')).strip()
    if action not in {'dismiss', 'reject'} or (action == 'reject' and not note) or len(note) > 500:
        return api_error('请选择处理方式，退回理由为1至500字')
    reports = target.reports.filter(status='pending', version=target.version)
    if not direct and not reports.exists():
        return api_error('举报已处理，请刷新', 409)
    plan = None
    if action == 'reject':
        from .reward_recovery import authorize
        plan, error = authorize(request, target, 'reject', data)
        if error is not None:
            return error
    reports.update(status='rejected' if action == 'reject' else 'dismissed', resolved_by=request.user, resolved_at=timezone.now(), note=note)
    if action == 'reject':
        target.is_valid = False
        target.rejection_note = note
        target.save(update_fields=['is_valid', 'rejection_note'])
        target.parts.update(status='rejected', points_awarded=0, review_note=note, reviewed_at=timezone.now(), reviewed_by=request.user)
        if target.problem_id:
            rebalance_submissions(target.member.user_id, target.problem_id, lost_records=[target])
        from .currency_services import reconcile_submission_day
        reconcile_submission_day(target.member, target.record_date, semester, recoveries=plan['recoveries'], reopen_makeup=False)
        refresh_totals(semester)
    ReviewLog.objects.create(submission=target, actor=request.user, action=('direct_' if direct else 'report_') + action, detail={'version': target.version, 'note': note})
    return JsonResponse({'ok': True})
