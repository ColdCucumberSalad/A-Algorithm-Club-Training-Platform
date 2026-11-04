"""Durable API notifications. Never contact the bot inside a business transaction."""

from datetime import timedelta
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import (
    AstrBotNotification,
    Semester,
    TeamMembership,
    TeamNotificationSettings,
    UserProfile,
)
from .notification_config import EVENT_FLAGS
from .problem_parser import key_cipher
from .services import build_weeks, progress_rows


def enabled():
    return bool(settings.ASTRBOT_NOTIFY_URL)


def queue_notification(event_key, event_type, team, text, **data):
    if not enabled():
        return None
    flag = EVENT_FLAGS.get(event_type)
    if (
        not flag
        or not TeamNotificationSettings.objects.filter(
            team=team, enabled=True, encrypted_api_token__gt="", **{flag: True}
        ).exists()
    ):
        return None
    row, _ = AstrBotNotification.objects.get_or_create(
        event_key=event_key,
        defaults={
            "payload": {
                "event_type": event_type,
                "team_id": team.pk,
                "team_name": team.name,
                "text": text,
                "data": data,
            },
        },
    )
    return row


def notify_purchase(purchase):
    if purchase.item.item_type != "physical":
        return
    queue_notification(
        f"purchase:{purchase.pk}",
        "physical_purchase",
        purchase.team,
        f"【实物商品购买】{purchase.member.display_name} 购买了 {purchase.item.name} ×{purchase.quantity}"
        f"，请及时处理发货。\n订单编号：{purchase.pk}",
        purchase_id=purchase.pk,
        member_id=purchase.member_id,
        quantity=purchase.quantity,
        item_id=purchase.item_id,
    )


def notify_item_use(unit):
    purchase = unit.purchase
    queue_notification(
        f"item-use:{unit.pk}",
        "item_used",
        purchase.team,
        f"【商品使用】{purchase.member.display_name} 使用了 {unit.item_name} ×1。\n使用记录：{unit.pk}",
        fulfillment_id=unit.pk,
        member_id=purchase.member_id,
        item_id=purchase.item_id,
    )


def notify_report(report, member):
    target = report.submission
    queue_notification(
        f"report:{report.pk}:{report.generation}",
        "submission_report",
        target.team,
        f"【提交举报】{member.display_name} 举报了 {target.member.display_name} 的提交。"
        f"\n提交编号：{target.pk}，版本：{report.version}，理由：{report.reason}，请及时审核。",
        report_id=report.pk,
        submission_id=target.pk,
        version=report.version,
    )


def queue_weekly_reminders(now=None):
    if not enabled():
        return 0
    now = now or timezone.now()
    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    # Use registered cohorts across the site, even before they join a team.
    latest_year = UserProfile.objects.filter(
        user__is_superuser=False, admission_year__gte=2013
    ).aggregate(latest=Max("admission_year"))["latest"]
    admission_years = (
        list(range(max(2013, latest_year - 1), latest_year + 1)) if latest_year else []
    )
    created = 0
    for semester in Semester.objects.filter(
        is_active=True,
        archived_at__isnull=True,
        starts_on__lte=local.date(),
        ends_on__gte=local.date(),
        team__notification_settings__enabled=True,
        team__notification_settings__qualification_enabled=True,
        team__notification_settings__review_weekday=local.weekday(),
        team__notification_settings__encrypted_api_token__gt="",
    ).select_related("team__notification_settings"):
        config = semester.team.notification_settings
        # Catch up on the scheduled day, after the selected local time.
        if local.time().replace(tzinfo=None) < config.review_time:
            continue
        with transaction.atomic():
            semester = Semester.objects.select_for_update().get(pk=semester.pk)
            if not semester.is_active or semester.archived_at:
                continue
            build_weeks(semester)
            week = semester.weeks.filter(starts_at__lte=now, ends_at__gt=now).first()
            if not week:
                continue
            key = f"weekly:{semester.pk}:week:{week.pk}"
            if AstrBotNotification.objects.filter(event_key=key).exists():
                continue
            members = list(
                TeamMembership.objects.filter(
                    team=semester.team,
                    is_active=True,
                    user__is_active=True,
                    user__is_superuser=False,
                    user__personal_profile__admission_year__in=admission_years,
                ).order_by("display_name", "pk")
            )
            scores, counts = progress_rows(
                semester, week, member_ids=[m.pk for m in members]
            )
            rows = [
                {
                    "member_id": m.pk,
                    "name": m.display_name,
                    "score": scores.get(m.pk, 0),
                    "valid_submissions": counts.get(m.pk, 0),
                }
                for m in members
                if scores.get(m.pk, 0) < 6 or counts.get(m.pk, 0) < 4
            ]
            text = "本周尚未达标的同学有：\n" + (
                "\n".join(
                    f"{r['name']}（积分 {r['score']}，有效提交 {r['valid_submissions']}）"
                    for r in rows
                )
                if rows
                else "无，最近两个分队本周没有未达标同学。"
            )
            queue_notification(
                key,
                "weekly_unqualified",
                semester.team,
                text,
                semester_id=semester.pk,
                week_id=week.pk,
                members=rows,
                min_score=6,
                min_submissions=4,
                checked_at=now.isoformat(),
            )
            created += 1
    return created


def deliver_pending(limit=50):
    if not enabled():
        return 0
    sent = 0
    for _ in range(limit):
        with transaction.atomic():
            row = (
                AstrBotNotification.objects.select_for_update(skip_locked=True)
                .filter(
                    delivered_at__isnull=True,
                    cancelled_at__isnull=True,
                    next_attempt_at__lte=timezone.now(),
                )
                .order_by("created_at")
                .first()
            )
            if row is None:
                break
            flag = EVENT_FLAGS.get(row.payload.get("event_type"))
            config = TeamNotificationSettings.objects.filter(
                team_id=row.payload.get("team_id"), enabled=True
            ).first()
            if (
                not config
                or not flag
                or not getattr(config, flag)
                or not config.encrypted_api_token
            ):
                row.cancelled_at = timezone.now()
                row.last_error = "通知已关闭，取消发送"
                row.save(update_fields=["cancelled_at", "last_error"])
                continue
            row.attempts += 1
            try:
                response = requests.post(
                    settings.ASTRBOT_NOTIFY_URL,
                    json={**row.payload, "event_id": str(row.pk)},
                    headers={
                        "Authorization": "Bearer "
                        + key_cipher()
                        .decrypt(config.encrypted_api_token.encode())
                        .decode()
                    },
                    timeout=(3, 20),
                    allow_redirects=False,
                )
                if response.status_code != 200 or response.json().get("ok") is not True:
                    raise ValueError("API did not acknowledge delivery")
            except (requests.RequestException, ValueError, AttributeError):
                row.last_error = "AstrBot 通知发送失败，等待重试"
                row.next_attempt_at = timezone.now() + timedelta(
                    seconds=min(3600, 30 * 2 ** min(row.attempts, 7))
                )
            else:
                row.delivered_at = timezone.now()
                row.last_error = ""
                sent += 1
            row.save(
                update_fields=[
                    "attempts",
                    "next_attempt_at",
                    "last_error",
                    "delivered_at",
                ]
            )
    return sent
