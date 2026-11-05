from django.conf import settings
from django.db import migrations,models
import django.db.models.deletion
import unicodedata


def configure_pendants(apps,schema_editor):
    Item=apps.get_model('club','ShopItem')
    Purchase=apps.get_model('club','Purchase')
    Grant=apps.get_model('club','PurchaseBadgeGrant')
    for item in Item.objects.using(schema_editor.connection.alias).filter(item_type='physical').iterator():
        name=''.join(unicodedata.normalize('NFKC',item.name).casefold().split())
        if name!='rbc挂坠':continue
        item.gift_badge_key='rbc-pendant';item.save(update_fields=['gift_badge_key'])
        purchases=Purchase.objects.using(schema_editor.connection.alias).filter(item_id=item.pk).select_related('member').order_by('pk')
        for purchase in purchases.iterator():
            if not purchase.fulfillments.exclude(status='reclaimed').exists():continue
            Grant.objects.using(schema_editor.connection.alias).get_or_create(user_id=purchase.member.user_id,key='rbc-pendant',defaults={'purchase_id':purchase.pk})


class Migration(migrations.Migration):
    dependencies=[('club','0064_merge_extension_categories_and_cosmetics'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.AddField(model_name='shopitem',name='gift_badge_key',field=models.CharField(max_length=40,blank=True)),
        migrations.CreateModel(name='PurchaseBadgeGrant',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('key',models.CharField(max_length=40)),
            ('created_at',models.DateTimeField(auto_now_add=True)),
            ('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='purchase_badges',to=settings.AUTH_USER_MODEL)),
            ('purchase',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='gift_badges',to='club.purchase')),
        ],options={'constraints':[models.UniqueConstraint(fields=['user','key'],name='unique_user_purchase_badge')]}),
        migrations.RunPython(configure_pendants,migrations.RunPython.noop),
    ]
