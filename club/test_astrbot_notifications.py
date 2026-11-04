import uuid
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import requests
from django.contrib.auth.models import User
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone

from .astrbot_notifications import (
    deliver_pending,
    queue_notification,
    queue_weekly_reminders,
)
from .currency_services import purchase_item
from .models import (
    AstrBotNotification,
    CurrencyBalance,
    Semester,
    ShopItem,
    Submission,
    SubmissionPart,
    Team,
    TeamMembership,
    TeamNotificationSettings,
    UserProfile,
)
from .problem_parser import key_cipher
from .services import build_weeks


@override_settings(
    ASTRBOT_NOTIFY_URL="https://bot.example/club/notify", ASTRBOT_NOTIFY_TOKEN="t" * 32
)
class NotificationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("notification-member")
        self.team = Team.objects.create(
            name="Test", code="NOTIFY", created_by=self.user, currency_enabled=True
        )
        self.member = TeamMembership.objects.create(
            team=self.team, user=self.user, display_name="小明"
        )
        CurrencyBalance.objects.create(team=self.team, member=self.member, balance=100)
        TeamNotificationSettings.objects.create(
            team=self.team,
            enabled=True,
            encrypted_api_token=key_cipher().encrypt(("t" * 32).encode()).decode(),
        )

    def queue(self):
        return queue_notification("test:1", "item_used", self.team, "使用通知")

    def test_outbox_rolls_back_with_business_transaction(self):
        with self.assertRaises(ValueError), transaction.atomic():
            self.queue()
            raise ValueError()
        self.assertFalse(AstrBotNotification.objects.exists())

    def test_purchase_physical_only_and_idempotent(self):
        item = ShopItem.objects.create(
            team=self.team, name="杯子", price=3, item_type="physical"
        )
        token = str(uuid.uuid4())
        purchase_item(self.member, item.pk, 2, token)
        purchase_item(self.member, item.pk, 2, token)
        row = AstrBotNotification.objects.get()
        self.assertEqual(row.payload["event_type"], "physical_purchase")
        self.assertEqual(row.payload["data"]["quantity"], 2)
        item = ShopItem.objects.create(
            team=self.team, name="道具", price=3, item_type="consumable"
        )
        purchase_item(self.member, item.pk)
        self.assertEqual(AstrBotNotification.objects.count(), 1)

    @override_settings(ASTRBOT_NOTIFY_URL="")
    def test_disabled_does_not_queue(self):
        self.assertIsNone(self.queue())
        self.assertEqual(deliver_pending(), 0)

    def test_makeup_ticket_use_notifies_once(self):
        from .currency_services import makeup_checkin
        from .models import UserInventory

        today = timezone.localdate()
        Semester.objects.create(
            team=self.team,
            name="当前学期",
            starts_on=today - timedelta(days=14),
            ends_on=today + timedelta(days=14),
        )
        ticket = ShopItem.objects.create(
            team=self.team, name="补签券", price=1, item_type="makeup_ticket"
        )
        UserInventory.objects.create(
            team=self.team, member=self.member, item=ticket, quantity=2
        )
        day = today - timedelta(days=1)
        self.assertFalse(makeup_checkin(self.member, day)["already_open"])
        self.assertTrue(makeup_checkin(self.member, day)["already_open"])
        row = AstrBotNotification.objects.get()
        self.assertEqual(row.payload["event_type"], "item_used")
        self.assertIn(day.isoformat(), row.payload["text"])

    @patch("club.astrbot_notifications.requests.post")
    def test_delivery_requires_positive_ack_and_retries_stable_id(self, post):
        row = self.queue()
        post.side_effect = requests.Timeout()
        self.assertEqual(deliver_pending(), 0)
        row.refresh_from_db()
        self.assertIsNone(row.delivered_at)
        self.assertEqual(row.attempts, 1)
        event_id = post.call_args.kwargs["json"]["event_id"]
        row.next_attempt_at = timezone.now() - timedelta(seconds=1)
        row.save()
        post.side_effect = None
        post.return_value = Mock(status_code=200, json=lambda: {"ok": True})
        self.assertEqual(deliver_pending(), 1)
        self.assertEqual(post.call_args.kwargs["json"]["event_id"], event_id)
        self.assertFalse(post.call_args.kwargs["allow_redirects"])
        self.assertEqual(deliver_pending(), 0)

    @patch("club.astrbot_notifications.requests.post")
    def test_redirect_or_false_ack_is_not_success(self, post):
        row = self.queue()
        for status, body in [(302, {"ok": True}), (200, {"ok": False})]:
            post.return_value = Mock(status_code=status, json=lambda body=body: body)
            row.next_attempt_at = timezone.now() - timedelta(seconds=1)
            row.save()
            self.assertEqual(deliver_pending(), 0)
            row.refresh_from_db()
            self.assertIsNone(row.delivered_at)

    def test_sunday_time_thresholds_zero_submissions_and_deduplication(self):
        UserProfile.objects.create(user=self.user, admission_year=2026)
        now = datetime(2026, 11, 8, 21, tzinfo=ZoneInfo("Asia/Shanghai"))
        semester = Semester.objects.create(
            team=self.team,
            name="Fall",
            starts_on=now.date() - timedelta(days=6),
            ends_on=now.date() + timedelta(days=7),
            min_score=99,
        )
        build_weeks(semester)
        week = semester.weeks.get(starts_at__lte=now, ends_at__gt=now)
        for name, count, score in [("合格", 4, 6), ("积分低", 4, 5), ("次数少", 3, 6)]:
            user = User.objects.create_user(name)
            UserProfile.objects.create(user=user, admission_year=2025)
            member = TeamMembership.objects.create(
                team=self.team, user=user, display_name=name
            )
            for index in range(count):
                sub = Submission.objects.create(
                    team=self.team, member=member, semester=semester, week=week
                )
                SubmissionPart.objects.create(
                    submission=sub,
                    kind="proof",
                    status="approved",
                    points_awarded=score if index == 0 else 0,
                )
            # Pending and rejected parts must not affect approved scores or counts.
            sub = Submission.objects.create(
                team=self.team, member=member, semester=semester, week=week
            )
            SubmissionPart.objects.create(
                submission=sub, kind="proof", status="pending", points_awarded=99
            )
        inactive = User.objects.create_user("inactive", is_active=False)
        TeamMembership.objects.create(
            team=self.team, user=inactive, display_name="停用"
        )
        self.assertEqual(queue_weekly_reminders(now - timedelta(minutes=1)), 0)
        self.assertEqual(queue_weekly_reminders(now - timedelta(days=1)), 0)
        self.assertEqual(queue_weekly_reminders(now), 1)
        self.assertEqual(queue_weekly_reminders(now + timedelta(hours=1)), 0)
        row = AstrBotNotification.objects.get()
        self.assertTrue(row.payload["text"].startswith("本周尚未达标的同学有："))
        self.assertEqual(
            {r["name"] for r in row.payload["data"]["members"]},
            {"小明", "积分低", "次数少"},
        )

    def cohort_member(self, name, year, **user_fields):
        user = User.objects.create_user(name, **user_fields)
        UserProfile.objects.create(user=user, admission_year=year)
        return TeamMembership.objects.create(
            team=self.team, user=user, display_name=name
        )

    def weekly_time(self):
        now = datetime(2026, 11, 8, 21, tzinfo=ZoneInfo("Asia/Shanghai"))
        Semester.objects.create(
            team=self.team, name="Fall", starts_on=now.date() - timedelta(days=6),
            ends_on=now.date() + timedelta(days=7),
        )
        return now

    def test_latest_registered_cohort_moves_window_across_the_site(self):
        now = self.weekly_time()
        for year in (2024, 2025, 2026):
            self.cohort_member(str(year), year)
        self.cohort_member("停用账号", 2026, is_active=False)
        inactive = self.cohort_member("停用成员", 2026)
        inactive.is_active = False
        inactive.save()
        UserProfile.objects.update_or_create(
            user=User.objects.get(username="admin"), defaults={"admission_year": 2099}
        )
        self.assertEqual(queue_weekly_reminders(now), 1)
        self.assertEqual(
            {r["name"] for r in AstrBotNotification.objects.get().payload["data"]["members"]},
            {"2025", "2026"},
        )
        # A registered user without any team still advances the global window.
        newest = User.objects.create_user("newest-unjoined")
        UserProfile.objects.create(user=newest, admission_year=2027)
        AstrBotNotification.objects.all().delete()
        self.assertEqual(queue_weekly_reminders(now), 1)
        self.assertEqual(
            {r["name"] for r in AstrBotNotification.objects.get().payload["data"]["members"]},
            {"2026"},
        )
        self.cohort_member("2027", 2027)
        AstrBotNotification.objects.all().delete()
        queue_weekly_reminders(now)
        self.assertEqual(
            {r["name"] for r in AstrBotNotification.objects.get().payload["data"]["members"]},
            {"2026", "2027"},
        )

    def test_cohort_gap_does_not_include_older_registered_cohort(self):
        now = self.weekly_time()
        self.cohort_member("十二分队", 2024)
        self.cohort_member("十四分队", 2026)
        queue_weekly_reminders(now)
        self.assertEqual(
            [r["name"] for r in AstrBotNotification.objects.get().payload["data"]["members"]],
            ["十四分队"],
        )

    def test_missing_or_invalid_cohorts_do_not_enter_reminders(self):
        now = self.weekly_time()
        self.cohort_member("未填写", None)
        self.cohort_member("无效分队", 2012)
        queue_weekly_reminders(now)
        payload = AstrBotNotification.objects.get().payload
        self.assertEqual(payload["data"]["members"], [])
        self.assertIn("最近两个分队", payload["text"])

    def test_first_cohort_does_not_include_invalid_previous_year(self):
        now = self.weekly_time()
        self.cohort_member("第一分队", 2013)
        self.cohort_member("无效分队", 2012)
        queue_weekly_reminders(now)
        self.assertEqual(
            [r["name"] for r in AstrBotNotification.objects.get().payload["data"]["members"]],
            ["第一分队"],
        )


@override_settings(
    ASTRBOT_NOTIFY_URL="https://bot.example/club/notify", ASTRBOT_NOTIFY_TOKEN="t" * 32
)
class ShopEventTests(TestCase):
    from .test_shop_fulfillment import ShopFulfillmentTests as Fixtures

    def setUp(self):
        self.Fixtures.setUp(self)
        TeamNotificationSettings.objects.create(
            team=self.team,
            enabled=True,
            encrypted_api_token=key_cipher().encrypt(("t" * 32).encode()).decode(),
        )

    login = Fixtures.login
    post = Fixtures.post
    item = Fixtures.item

    def test_consumable_use_notifies_once(self):
        item = self.item("consumable")
        purchase_item(self.member, item.pk)
        inventory = self.member.inventory.get(item=item)
        token = {"request_id": str(uuid.uuid4())}
        for _ in range(2):
            response = self.post(
                self.owner, f"/api/currency/inventory/{inventory.pk}/use", token
            )
            self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            AstrBotNotification.objects.get().payload["event_type"], "item_used"
        )

    def test_card_redemption_does_not_leak_code(self):
        from .shop_fulfillment import append_codes

        item = self.item()
        append_codes(item, ["SECRET-CARD-CODE"])
        purchase_item(self.member, item.pk)
        from .models import ShopFulfillment

        unit = ShopFulfillment.objects.get()
        from django.test import RequestFactory

        from .shop_fulfillment import redeem

        request = RequestFactory().post(
            "/redeem", "{}", content_type="application/json"
        )
        request.user = self.user
        request.session = {"team_id": self.team.pk}
        self.assertEqual(redeem(request, unit.pk).status_code, 200)
        self.assertEqual(redeem(request, unit.pk).status_code, 200)
        self.assertNotIn(
            "SECRET-CARD-CODE", str(AstrBotNotification.objects.get().payload)
        )


@override_settings(
    ASTRBOT_NOTIFY_URL="https://bot.example/club/notify", ASTRBOT_NOTIFY_TOKEN="t" * 32
)
class ReportEventTests(TestCase):
    from .test_community import CommunityTests as Fixtures

    def setUp(self):
        self.Fixtures.setUp(self)
        TeamNotificationSettings.objects.create(
            team=self.team,
            enabled=True,
            encrypted_api_token=key_cipher().encrypt(("t" * 32).encode()).decode(),
        )

    image = Fixtures.image
    post = Fixtures.post
    submit = Fixtures.submit
    report = Fixtures.report

    def test_duplicate_report_sends_one_event(self):
        submission = self.submit()
        self.assertEqual(self.report(submission).status_code, 200)
        self.assertEqual(self.report(submission).status_code, 200)
        row = AstrBotNotification.objects.get()
        self.assertEqual(row.payload["event_type"], "submission_report")
