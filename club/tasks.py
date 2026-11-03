from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from .models import CleanupJob, Semester, FileDeletion, Problem
from django.core.files.storage import default_storage
from .services import build_weeks, cleanup_semester, settle_week, validate_week_dates


@shared_task(soft_time_limit=115, time_limit=120)
def send_astrbot_notifications():
    from .astrbot_notifications import deliver_pending, queue_weekly_reminders
    queued = queue_weekly_reminders()
    return {'weekly_queued': queued, 'delivered': deliver_pending(limit=3)}


@shared_task
def settle_and_cleanup():
    now = timezone.now()
    from .semester_calendar import ensure_current_semester
    from .models import Team
    for team in Team.objects.filter(semesters__calendar_managed=True).distinct():
        ensure_current_semester(team)
    from .retirement import sync_retirement_subsidies
    retirement = sync_retirement_subsidies()
    purge_files()
    Problem.objects.filter(status__in=['pending', 'running'], requested_at__lt=now - timedelta(minutes=10)).update(status='failed', error='任务超时，请手动重新解析')
    blocked_semesters = []
    for semester in Semester.objects.filter(Q(is_active=True) | Q(calendar_managed=True), archived_at__isnull=True):
        build_weeks(semester)
        try:
            validate_week_dates(semester)
        except ValidationError:
            blocked_semesters.append(semester.pk)
            continue
        for week in semester.weeks.filter(ends_at__lte=now, is_closed=False):
            settle_week(week)
        if semester.cleanup_at and semester.cleanup_at <= now:
            CleanupJob.objects.get_or_create(semester=semester, defaults={'scheduled_for': semester.cleanup_at})
    retryable = Q(status__in=['scheduled', 'failed']) | Q(status='running', started_at__lt=now - timedelta(minutes=10))
    for job in CleanupJob.objects.filter(retryable, scheduled_for__lte=now):
        run_cleanup.delay(job.pk)
    return {'checked_at': now.isoformat(), 'needs_week_repair': blocked_semesters, 'retirement': retirement}


@shared_task
def run_cleanup(job_id):
    job = CleanupJob.objects.select_related('semester').filter(pk=job_id).first()
    if not job:
        return {'status':'cancelled'}
    result = cleanup_semester(job.semester, enforce_schedule=True)
    if result is None:
        return {'status':'cancelled'}
    deleted, files = result
    return {'status': 'completed', 'deleted': deleted, 'files': files}


@shared_task
def resolve_problem(problem_id, generation, mode):
    from .problem_parser import resolve
    resolve(problem_id, generation, mode)


@shared_task
def purge_files():
    for entry in FileDeletion.objects.order_by('pk')[:500]:
        try:
            default_storage.delete(entry.name)
            entry.delete()
        except Exception:
            FileDeletion.objects.filter(pk=entry.pk).update(error='文件删除失败，等待重试')


@shared_task(soft_time_limit=155, time_limit=165, priority=2)
def sync_platform_binding(binding_id, token):
    from .models import PlatformBinding
    modern = PlatformBinding.objects.filter(pk=binding_id, sync_token=token).first()
    if modern and modern.sync_state.get('version') == 2:
        from .platform_records import run_step
        return run_step(binding_id, token)
    from django.db import transaction
    from .models import PlatformBinding, PlatformSolvedBaseline
    from .platform_sync import fetch_snapshot, SyncError
    binding = PlatformBinding.objects.filter(pk=binding_id, sync_token=token, status='pending').first()
    if not binding:
        return
    try:
        baseline = PlatformSolvedBaseline.objects.filter(binding=binding, total__isnull=False).first()
        snapshot = fetch_snapshot(binding.platform, binding.account, include_solved=baseline is None)
        baseline_data = snapshot.pop('_solved_baseline', None)
        with transaction.atomic():
            current = PlatformBinding.objects.select_for_update().filter(pk=binding_id, sync_token=token,
                account=binding.account, status='pending').first()
            if not current:
                return
            if baseline is None and baseline_data is not None:
                defaults={'checked_at':timezone.now(),'error':baseline_data.get('error',''),
                    'notes':baseline_data.get('notes',[])}
                if 'total' in baseline_data:
                    defaults.update(total=baseline_data['total'],problem_ids=baseline_data.get('problem_ids',[]), ids_complete=baseline_data.get('ids_complete',False),
                        dated_problems=baseline_data.get('dated_problems',{}),captured_at=timezone.now())
                baseline,_=PlatformSolvedBaseline.objects.update_or_create(binding=current,defaults=defaults)
            if baseline and baseline.total is not None:
                snapshot['solved']=baseline.total
                snapshot['solved_label']='绑定时过题基线（后续比赛 AC 计入榜单）'
                snapshot.setdefault('notes',[]).extend(baseline.notes)
            elif baseline_data and baseline_data.get('error'):
                snapshot.setdefault('notes',[]).append('过题基线未建立：'+baseline_data['error'])
            PlatformBinding.objects.filter(pk=current.pk).update(
                snapshot=snapshot, status='ready', error='', synced_at=timezone.now())
    except Exception as exc:
        # Do not expose credentials, URLs with user input, or response bodies.
        message = str(exc)[:240] if isinstance(exc, SyncError) else '平台数据读取失败，请稍后重试或检查账号与凭据'
        with transaction.atomic():
            current=PlatformBinding.objects.select_for_update().filter(pk=binding_id,sync_token=token,account=binding.account).first()
            if current:
                PlatformSolvedBaseline.objects.get_or_create(binding=current,defaults={'error':message})
                PlatformBinding.objects.filter(pk=current.pk).update(status='failed', error=message)


def _contest_sync_is_current(user_id, token):
    from .models import ContestSyncState
    return ContestSyncState.objects.filter(user_id=user_id,token=token,status='pending',
        user__is_active=True,user__account_closure__isnull=True).exists()


def _lock_contest_sync_state(user_id, token):
    """Inside a write transaction: user first, then sync state and history rows."""
    from django.contrib.auth.models import User
    from .models import AccountClosure,ContestSyncState
    user=User.objects.select_for_update().filter(pk=user_id).first()
    if not user or not user.is_active or AccountClosure.objects.filter(user=user).exists():
        return None
    return ContestSyncState.objects.select_for_update().filter(
        user_id=user_id,token=token,status='pending').first()


@shared_task(soft_time_limit=750, time_limit=780)
def discover_contest_progress(user_id, token):
    from django.db import transaction
    from .models import ContestParticipation, PlatformBinding
    from .contest_progress_sources import discover, Remote, SyncError
    if not _contest_sync_is_current(user_id,token):
        return
    pending = []
    messages = {}
    for binding in PlatformBinding.objects.filter(user_id=user_id):
        if not _contest_sync_is_current(user_id,token):
            return
        if binding.platform == 'qoj':
            continue
        remote = Remote()
        try:
            rows = discover(remote, binding.platform, binding.account)
            with transaction.atomic():
                state = _lock_contest_sync_state(user_id,token)
                if not state:
                    return
                if not PlatformBinding.objects.filter(pk=binding.pk, account=binding.account).exists():
                    continue
                state.progressed_at=timezone.now();state.save(update_fields=['progressed_at'])
                for row in rows:
                    key = row.pop('contest_key')
                    c, _ = ContestParticipation.objects.update_or_create(user_id=user_id, platform=binding.platform,
                        account=binding.account, contest_key=key, defaults=row)
                    pending.append(c.pk)
            messages[binding.platform] = f'已获取 {len(rows)} 场参赛记录'
        except Exception as exc:
            messages[binding.platform] = str(exc)[:240] if isinstance(exc, SyncError) else '比赛历史同步失败，保留已有记录'
        finally:
            remote.session.close()
    with transaction.atomic():
        state = _lock_contest_sync_state(user_id,token)
        if not state:
            return
        state.progressed_at=timezone.now()
        state.messages = messages; state.total = state.remaining = len(pending)
        state.status = 'pending' if pending else 'ready'; state.finished_at = None if pending else timezone.now(); state.save()
        for pk in pending:
            transaction.on_commit(lambda pk=pk: enqueue_hydration(pk, token))


def enqueue_hydration(contest_id, token):
    try:
        hydrate_contest_progress.apply_async(args=[contest_id,token],retry=False)
    except Exception:
        from .models import ContestSyncState,ContestParticipation
        contest=ContestParticipation.objects.filter(pk=contest_id).first()
        if contest:
            ContestSyncState.objects.filter(user_id=contest.user_id,token=token).update(
                status='failed',messages={'system':'比赛任务未能入队，请重新同步；已有进度已保留'})


@shared_task(soft_time_limit=155, time_limit=165)
def hydrate_contest_progress(contest_id, token):
    from django.db import transaction
    from .models import ContestParticipation, ContestProblemProgress, PlatformBinding
    from .contest_progress_sources import hydrate, Remote, SyncError
    c = ContestParticipation.objects.filter(pk=contest_id).first()
    if not c or str(c.hydrated_token)==str(token) or not _contest_sync_is_current(c.user_id,token):
        return
    remote = Remote(); rows = None; error = ''
    try:
        rows, error = hydrate(remote, c)
    except Exception as exc:
        error = str(exc)[:240] if isinstance(exc, SyncError) else '比赛题目或正式榜单暂不可读取，请稍后同步'
    finally:
        remote.session.close()
    verified_ends_at=c.ends_at
    with transaction.atomic():
        state = _lock_contest_sync_state(c.user_id,token)
        if not state:
            return
        c = ContestParticipation.objects.select_for_update().get(pk=c.pk)
        if str(c.hydrated_token) == str(token):
            return
        c.hydrated_token = token
        c.save(update_fields=['hydrated_token'])
        if PlatformBinding.objects.filter(user=c.user, platform=c.platform, account=c.account).exists():
            if rows is not None and (not error or not c.detail_complete):
                c.ends_at=verified_ends_at
                keys = [row['problem_key'] for row in rows]
                for row in rows:
                    key = row.pop('problem_key')
                    ContestProblemProgress.objects.update_or_create(participation=c, problem_key=key, defaults=row)
                ContestProblemProgress.objects.filter(participation=c).exclude(problem_key__in=keys).delete()
                c.detail_complete = not bool(error)
            c.sync_error = error; c.save()
        state.progressed_at=timezone.now()
        state.remaining = max(0, state.remaining-1)
        if not state.remaining:
            state.status = 'ready'; state.finished_at = timezone.now()
        state.save()


@shared_task(priority=0)
def refresh_contest_calendar():
    from .contest_views import refresh_calendar
    snapshots = refresh_calendar(force=True)
    return {platform: {'updated_at': row['updated_at'], 'error': row['error']} for platform,row in snapshots.items()}


@shared_task(priority=0)
def refresh_tracker_catalogs():
    from .tracker_sources import KINDS
    from .tracker_views import queue_refresh
    for kind in KINDS:
        queue_refresh(kind, True)


@shared_task(soft_time_limit=155, time_limit=165, priority=0)
def refresh_tracker_catalog(kind, token):
    from django.db import transaction
    from .models import TrackerCatalog
    from .platform_sync import Remote
    from .tracker_sources import fetch, qoj_problems
    from .tracker_ratings import board_index, enrich
    from bs4 import BeautifulSoup
    catalog = TrackerCatalog.objects.filter(kind=kind, token=token, status='pending').first()
    if not catalog:
        return
    expected = dict(catalog.refresh_state)
    from copy import deepcopy
    state = deepcopy(expected)
    remote = Remote()
    try:
        items = {c['id']: c for c in catalog.contests}
        done = False
        if state.get('phase') == 'enrich':
            ids = list(state['ids'])
            if ids:
                cid = ids.pop(0)
                event = dict(items[cid])
                event['problems'] = [dict(p) for p in event['problems']]
                try:
                    enrich(remote,event,state['boards'])
                except Exception:
                    pass
                items[cid] = event
            state['ids'] = ids
            done = not ids
        else:
            batch,state,finished = fetch(kind,remote,state)
            seen = set(state.get('seen',[]))
            new_ids = {c['id'] for c in batch}
            if kind == 'nowcoder' and batch and new_ids.issubset(seen):
                raise ValueError('repeated catalog page')
            seen.update(new_ids);state['seen'] = sorted(seen)
            for event in batch:
                previous = items.get(event['id'])
                if previous:
                    old = {p['key']:p for p in previous['problems']}
                    for p in event['problems']:
                        prior = old.get(p['key'])
                        if prior:
                            if p['title'] == p['label']:p['title'] = prior['title']
                            for name in ('tier','difficulty_source','accepted_teams','total_teams'):
                                if name in prior:p[name] = prior[name]
                    if not event['problems']:event['problems'] = previous['problems']
                items[event['id']] = event
            done = finished
            if finished and kind == 'icpc':
                state.update(phase='enrich',boards=board_index(remote),ids=sorted(seen))
                done = not state['ids']
        if done and not items:
            raise ValueError('empty catalog')
        with transaction.atomic():
            current = TrackerCatalog.objects.select_for_update().filter(pk=catalog.pk,token=token,status='pending').first()
            if not current or current.refresh_state != expected:
                return
            current.contests = list(items.values())
            current.error = ''
            current.refresh_state = {} if done else state
            current.requested_at = timezone.now()
            if done:
                current.status = 'ready';current.updated_at = timezone.now()
            current.save()
            if done and kind == 'icpc':
                from .models import PlatformBinding
                for binding_id in PlatformBinding.objects.filter(platform='qoj').exclude(encrypted_credentials='').values_list('id',flat=True):
                    transaction.on_commit(lambda pk=binding_id: enqueue_qoj_overlay(pk))
            if not done:
                transaction.on_commit(lambda: refresh_tracker_catalog.apply_async(args=[kind,token],countdown=1))
    except Exception:
        import logging
        logging.getLogger(__name__).exception('Tracker catalog refresh failed: %s',kind)
        TrackerCatalog.objects.filter(pk=catalog.pk,token=token,refresh_state=expected).update(status='failed',error='目录更新失败，请重试')
    finally:
        remote.session.close()


def enqueue_qoj_overlay(binding_id):
    import uuid
    from .models import PlatformBinding, QojCatalogOverlay, TrackerCatalog
    binding = PlatformBinding.objects.filter(pk=binding_id,platform='qoj').first()
    catalog = TrackerCatalog.objects.filter(kind='icpc').first()
    if not binding or not binding.encrypted_credentials or not catalog:
        return
    with transaction.atomic():
        overlay,_ = QojCatalogOverlay.objects.get_or_create(binding=binding)
        overlay = QojCatalogOverlay.objects.select_for_update().get(pk=overlay.pk)
        overlay.queue = [c['id'] for c in catalog.contests if c['id'] not in overlay.contests]
        overlay.token = uuid.uuid4()
        overlay.status = 'pending' if overlay.queue else 'ready'
        overlay.error = ''
        overlay.updated_at = timezone.now()
        overlay.save()
        token = str(overlay.token)
        if overlay.queue:
            transaction.on_commit(lambda: refresh_qoj_overlay.delay(binding_id,token,str(binding.sync_token)))


@shared_task(soft_time_limit=155,time_limit=165,priority=0)
def refresh_qoj_overlay(binding_id,token,binding_token):
    from .models import PlatformBinding, QojCatalogOverlay
    from .platform_credentials import attach
    from .platform_sync import Remote, SyncError
    from .tracker_sources import qoj_problems
    from bs4 import BeautifulSoup
    binding = PlatformBinding.objects.filter(pk=binding_id,sync_token=binding_token).first()
    overlay = QojCatalogOverlay.objects.filter(binding_id=binding_id,token=token,status='pending').first()
    if not binding or not overlay or not overlay.queue:
        return
    expected = list(overlay.queue)
    cid = expected[0]
    remote = Remote()
    try:
        attach(remote,binding)
        soup = BeautifulSoup(remote.text('https://qoj.ac/contest/'+cid),'html.parser')
        if soup.select_one('input[name=password]'):
            raise SyncError('请更新 QOJ Cookie')
        problems = qoj_problems(soup)
        if not problems:
            raise SyncError('题目同步失败，请重试')
        with transaction.atomic():
            current = QojCatalogOverlay.objects.select_for_update().filter(binding_id=binding_id,token=token,status='pending').first()
            if not current or current.queue != expected or not PlatformBinding.objects.filter(pk=binding_id,sync_token=binding_token).exists():
                return
            current.contests = dict(current.contests,**{cid:problems})
            current.queue = expected[1:]
            current.updated_at = timezone.now()
            current.status = 'pending' if current.queue else 'ready'
            current.save()
            if current.queue:
                transaction.on_commit(lambda: refresh_qoj_overlay.apply_async(args=[binding_id,token,binding_token],countdown=1))
    except Exception as exc:
        QojCatalogOverlay.objects.filter(binding_id=binding_id,token=token,queue=expected).update(status='failed',error=str(exc)[:240] if isinstance(exc,SyncError) else '题目同步失败，请重试')
    finally:
        remote.session.close()


@shared_task(soft_time_limit=50, time_limit=60)
def sweep_poker_rooms():
    from .models import PokerRoom
    from .poker_services import sweep_room
    for room_id in PokerRoom.objects.filter(closed=False).values_list('pk', flat=True).iterator():
        sweep_room(room_id)

@shared_task(priority=8)
def sync_bound_accounts_nightly(day=None):
    """One account at a time, at least 30 seconds between dispatch checks.

    Failed accounts require manual recovery; never retry bad credentials in a loop.
    The daily marker survives worker restarts and duplicate scheduler messages.
    """
    from django.db import connection
    from .models import PlatformBinding, TeamMembership
    from .platform_account_views import start
    from .profile_views import lock_active_member
    now = timezone.now()
    today = timezone.localdate().isoformat()
    day = day or today
    if day != today:
        return {'status': 'expired'}
    # Release timeout-update binding locks before acquiring any user locks.
    # Manual retries lock user -> membership -> binding and may run concurrently.
    with transaction.atomic():
        PlatformBinding.objects.filter(status='pending', requested_at__lt=now-timedelta(minutes=30)).update(
            status='failed', error='同步超时，请手动重试')
    with transaction.atomic():
        # Serialize duplicate dispatchers across processes without a new model.
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_try_advisory_xact_lock(%s)', [230041])
            if not cursor.fetchone()[0]:
                return {'status': 'busy'}
        pending = PlatformBinding.objects.filter(status='pending')
        if pending.exists():
            transaction.on_commit(lambda: sync_bound_accounts_nightly.apply_async(
                kwargs={'day': day}, countdown=30, priority=8))
            return {'status': 'waiting'}
        candidates = PlatformBinding.objects.filter(
            user__is_active=True,
            user_id__in=TeamMembership.objects.filter(is_active=True).values('user_id'),
            status='ready').filter(Q(synced_at__isnull=True) | Q(synced_at__lt=now-timedelta(hours=12))).order_by('pk')
        binding = None
        for candidate in candidates:
            if candidate.sync_state.get('auto_sync_day') == day:
                continue
            member_id = TeamMembership.objects.filter(user_id=candidate.user_id, is_active=True).values_list('pk', flat=True).first()
            # Match manual sync/account closure lock order: user, membership,
            # then binding. Never lock all joined users and bindings at once.
            if not member_id or not lock_active_member(candidate.user_id, member_id):
                continue
            current = PlatformBinding.objects.select_for_update().filter(pk=candidate.pk).first()
            if (not current or current.status != 'ready'
                    or current.sync_state.get('auto_sync_day') == day
                    or current.synced_at and current.synced_at >= now-timedelta(hours=12)):
                continue
            binding = current
            break
        if binding is None:
            return {'status': 'complete'}
        start(binding, False)
        binding.sync_state['auto_sync_day'] = day
        binding.save(update_fields=['sync_state'])
        transaction.on_commit(lambda: sync_bound_accounts_nightly.apply_async(
            kwargs={'day': day}, countdown=30, priority=8))
        return {'status': 'started', 'binding_id': binding.pk}
