from django.db import migrations


def add_second_badge(apps,schema_editor):
    Grant=apps.get_model('club','CosmeticGrant')
    Item=apps.get_model('club','ShopItem')
    for source in Grant.objects.filter(kind='theme',key='taffy',inventory__quantity__gt=0).iterator():
        Grant.objects.get_or_create(user_id=source.user_id,inventory_id=source.inventory_id,kind='badge',key='taffy-head')
    Item.objects.filter(item_type='theme',cosmetic_key='taffy',description='全站特殊主题，附赠小塔菲徽章。请管理员设置价格后上架。').update(description='塔菲主题，附赠两枚小塔菲徽章。')


class Migration(migrations.Migration):
    dependencies=[('club','0060_cosmetics')]
    operations=[migrations.RunPython(add_second_badge,migrations.RunPython.noop)]
