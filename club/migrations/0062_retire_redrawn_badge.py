from django.db import migrations


def retire_badge(apps,schema_editor):
    Grant=apps.get_model('club','CosmeticGrant')
    Member=apps.get_model('club','TeamMembership')
    Item=apps.get_model('club','ShopItem')
    Inventory=apps.get_model('club','UserInventory')
    Grant.objects.filter(kind='badge',key='taffy-head').delete()
    Member.objects.filter(worn_badge='taffy-head').update(worn_badge='')
    # Keep purchase/coin history even when retiring a cosmetic.
    Inventory.objects.filter(item__item_type='badge',item__cosmetic_key='taffy-head').update(quantity=0)
    Item.objects.filter(item_type='badge',cosmetic_key='taffy-head').update(is_active=False)
    Item.objects.filter(item_type='theme',cosmetic_key='taffy',description='塔菲主题，附赠两枚小塔菲徽章。').update(description='塔菲主题，附赠小塔菲徽章。')


class Migration(migrations.Migration):
    dependencies=[('club','0061_taffy_badge_pair')]
    operations=[migrations.RunPython(retire_badge,migrations.RunPython.noop)]
