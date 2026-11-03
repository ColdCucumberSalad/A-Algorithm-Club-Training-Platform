from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def convert_existing_tables(apps, schema_editor):
    Room = apps.get_model('club', 'PokerRoom')
    Seat = apps.get_model('club', 'PokerSeat')
    # Existing real-money tables stored one Coin per unit. Preserve their value,
    # including committed bets and unsettled payouts, at the new exchange rate.
    for room in Room.objects.filter(mode='coins').iterator():
        room.buy_in *= 1000
        room.big_blind *= 1000
        hand = room.hand
        for key in ('big_blind', 'current_bet', 'min_raise'):
            if key in hand:
                hand[key] *= 1000
        for player in hand.get('players', {}).values():
            for key in ('stack', 'bet', 'total', 'acted_at'):
                if player.get(key) is not None:
                    player[key] *= 1000
        result = hand.get('result')
        if result:
            result['payouts'] = {uid: value * 1000 for uid, value in result['payouts'].items()}
            for pot in result['pots']:
                pot['amount'] *= 1000
        room.version += 1
        room.save(update_fields=['buy_in', 'big_blind', 'hand', 'version'])
        Seat.objects.filter(room=room).update(stack=models.F('stack') * 1000)


def reverse_empty_tables(apps, schema_editor):
    # Permit schema-only test/empty-install rollback without discarding assets.
    from django.db.migrations.exceptions import IrreversibleError
    if (apps.get_model('club', 'PokerChipBalance').objects.exists()
            or apps.get_model('club', 'PokerRoom').objects.filter(mode='coins').exists()):
        raise IrreversibleError('有筹码钱包或正式牌桌数据时，不能直接回退筹码换算迁移')


class Migration(migrations.Migration):
    dependencies = [('club', '0057_api_card_multiple_purchase'), ('club', '0056_merge_poker_and_app_cards'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name='PokerChipBalance', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('balance', models.PositiveBigIntegerField(default=0)),
            ('user', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                related_name='poker_chips', to=settings.AUTH_USER_MODEL)),
        ]),
        migrations.AlterField(model_name='pokerroom', name='buy_in', field=models.PositiveIntegerField(default=1000)),
        migrations.RunPython(convert_existing_tables, reverse_empty_tables),
    ]
