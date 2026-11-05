from . import cosmetic_views, cosmetic_admin
from django.urls import path
from . import poker_views
from . import extension_views
from . import account_views, admin_submission_views
from . import member_management
from . import notification_views
from .activity_views import training_activity
from . import profile_views
from . import platform_account_views
from . import tracker_views
from . import platform_rewards
from . import contest_progress_views

from . import contest_views, daily_views, views, community_views as community, management_views as management, currency_views as currency
from . import system_management_views as system_management

from .admin_test_mode import toggle as toggle_test_mode

from . import shop_fulfillment
from . import app_views

urlpatterns = [
    path('poker/rooms', poker_views.rooms),
    path('poker/rooms/chips', poker_views.chips),
    path('poker/rooms/<uuid:room_id>', poker_views.room),

    path('app/cards/verify', app_views.card_verify),
    path('app/cards/confirm', app_views.card_confirm),
    path('management/submissions/<int:submission_id>',admin_submission_views.edit_submission),
    path('profile/titles/wear', profile_views.wear_title),
    path('profile/cosmetics', cosmetic_views.library),
    path('account',account_views.current_account),
    path('account/close',account_views.close_account),
    path('management/accounts',account_views.accounts),
    path('management/accounts/<int:user_id>',account_views.update_account),
    path('management/accounts/<int:user_id>/close',account_views.close_account),
    path('management/accounts/<int:user_id>/inventory',account_views.account_inventory),
    path('management/teams/<int:team_id>/notifications', notification_views.notification_settings),
    path('auth/registration-options', views.registration_options),
    path('members/<int:member_id>/profile', profile_views.member_profile),
    path('management/teams/<int:team_id>/members', member_management.member_list),
    path('management/teams/<int:team_id>/members/<int:member_id>/settings', member_management.member_settings),
    path('management/teams/<int:team_id>/members/<int:member_id>/inventory', member_management.inventory_settings),
    path('profile/platform-rewards/claim', platform_rewards.claim),
    path('trackers/<str:kind>', tracker_views.tracker),
    path('trackers/<str:kind>/refresh', tracker_views.tracker, {'refresh': True}),
    path('profile/platforms/<str:platform>/accounts', platform_account_views.accounts),
    path('profile/platform-accounts/sync', platform_account_views.sync),
    path('profile/platform-accounts/<int:binding_id>', platform_account_views.account_detail),
    path("currency/inventory/<int:unit_id>/redeem", shop_fulfillment.redeem),
    path("currency/inventory/<int:inventory_id>/use", shop_fulfillment.use_consumable),
    path("submissions/<int:submission_id>/reversal-preview", views.submission_reversal_preview),
    path("currency/admin/dispatch", shop_fulfillment.dispatch_inbox),
    path("admin-test-mode", toggle_test_mode),
    path('training-activity', training_activity),
    path('management/site-updates', system_management.site_updates),
    path('management/password', system_management.change_admin_password),
    path('management/backups', system_management.backup_collection),
    path('management/backups/import', system_management.import_backup),
    path('management/backups/<uuid:backup_id>', system_management.backup_detail),
    path('management/backups/<uuid:backup_id>/restore', system_management.restore_backup),
    path('management/system-operations/<uuid:operation_id>', system_management.operation_status),
    path('extensions/builtin/poker', extension_views.builtin_category),
    path('extensions', extension_views.resources),
    path('extensions/<int:resource_id>', extension_views.resources),
    path('extensions/<int:resource_id>/download', extension_views.asset),
    path('extensions/<int:resource_id>/cover', extension_views.asset, {'cover': True}),
    path('profile/password', profile_views.change_password),
    path('submissions/<int:submission_id>/tip', community.tip_submission),
    path('management/platform-query', management.platform_query_settings),
    path('contests/progress', contest_progress_views.progress),
    path('contests/claim', contest_progress_views.claim),
    path("semesters", views.semesters),
    path("attachments/<int:part_id>", views.attachment),
    path("csrf", views.api_csrf),
    path("auth/join", views.join_team),
    path("auth/login", views.login_view),
    path("auth/register", views.register_account),
    path("auth/logout", views.logout_view),
    path("auth/create-team", views.create_team),
    path("team/select", views.select_team),
    path("me", views.me),
    path("profile", profile_views.profile),
    path("profile/avatar", profile_views.avatar),
    path("members/<int:member_id>/avatar", profile_views.avatar),
    path("profile/platforms/<str:platform>", profile_views.platform_binding),
    path("dashboard", views.dashboard),
    path("daily-challenges", daily_views.daily_links),
    path("contests", contest_views.contest_calendar),
    path("members", views.members),
    path("members/<int:member_id>/history", views.member_history),
    path("submissions", views.submissions),
    path("showcase", community.showcase),
    path("problems/<int:problem_id>/submissions", community.problem_submissions),
    path("submissions/<int:submission_id>/resubmit", views.submissions),
    path("submissions/<int:submission_id>/edit", views.submissions, {"edit": True}),
    path("submissions/<int:submission_id>", views.delete_own_submission),
    path("submissions/<int:submission_id>/like", community.reaction, {"kind": "like"}),
    path("submissions/<int:submission_id>/report", community.reaction, {"kind": "report"}),
    path("management", management.workspace),
    path("management/parser", management.parser_settings),
    path("management/parser/test", management.test_parser),
    path("management/problems", management.problem_queue),
    path("management/problems/<int:problem_id>", management.update_problem),
    path("management/problems/<int:problem_id>/retry", management.retry_problem),
    path("management/teams/<int:team_id>/members/<int:member_id>", management.kick_member),
    path("management/teams/<int:team_id>/settings", management.team_configuration),
    path("management/teams/<int:team_id>/cleanup", management.team_cleanup_schedule),
    path("management/managers", management.assign_manager),
    path("management/teams/<int:team_id>", management.delete_team),
    path("submissions/<int:submission_id>/reject", community.resolve_report, {"direct": True}),
    path("admin/reports", community.report_queue),
    path("admin/reports/<int:submission_id>/resolve", community.resolve_report),
    path("leaderboard", views.leaderboard),
    path("admin/team-settings", views.team_settings),
    path("export", views.export_xlsx),

    # Declarative cosmetic resources and theme packages.
    path('management/cosmetic-assets', cosmetic_admin.assets),
    path('management/cosmetic-assets/upload', cosmetic_admin.upload),
    path('management/cosmetic-assets/package', cosmetic_admin.package),
    path('management/cosmetic-assets/import', cosmetic_admin.import_package),
    path('cosmetic-assets/media/<str:filename>', cosmetic_admin.media),

    # Currency system endpoints
    path("currency/balance", currency.api_currency_balance),
    path("currency/icon/<int:team_id>", currency.api_currency_icon),
    path("currency/transactions", currency.api_currency_transactions),
    path("currency/checkin", currency.api_currency_checkin),
    path("currency/checkin/makeup", currency.api_currency_makeup_checkin),
    path("currency/checkin/calendar", currency.api_currency_checkin_calendar),
    path("currency/contest/submit", currency.api_contest_submission),
    path("currency/shop/items", currency.api_shop_items),
    path("currency/shop/items/<int:item_id>/icon", currency.api_shop_item_icon),
    path("currency/shop/purchase", currency.api_shop_purchase),
    path("currency/inventory", currency.api_user_inventory),

    # Admin currency endpoints
    path("currency/admin/adjust", currency.api_admin_adjust_balance),
    path("currency/admin/config", currency.api_admin_currency_config),
    path("currency/admin/shop", currency.api_admin_shop_items),
]
