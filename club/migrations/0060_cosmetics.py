from django.conf import settings
from django.db import migrations,models
import django.db.models.deletion


def stock_themes(apps,schema_editor):
    Team=apps.get_model('club','Team');Item=apps.get_model('club','ShopItem')
    for team in Team.objects.filter(currency_enabled=True).iterator():
        if not Item.objects.filter(team=team,item_type='theme',cosmetic_key='taffy').exists():
            Item.objects.create(team=team,name='塔菲 · 小菲滚轴',description='全站特殊主题，附赠小塔菲徽章。请管理员设置价格后上架。',item_type='theme',cosmetic_key='taffy',price=1,stock=-1,is_active=False)


class Migration(migrations.Migration):
    dependencies=[('club','0059_shop_titles'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.AddField(model_name='shopitem',name='cosmetic_key',field=models.CharField(blank=True,max_length=40)),
        migrations.AddField(model_name='teammembership',name='worn_badge',field=models.CharField(blank=True,max_length=40)),
        migrations.AddField(model_name='userprofile',name='active_theme',field=models.CharField(blank=True,max_length=40)),
        migrations.CreateModel(name='CosmeticGrant',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('kind',models.CharField(max_length=10)),('key',models.CharField(max_length=40)),
            ('created_at',models.DateTimeField(auto_now_add=True)),
            ('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='cosmetic_grants',to=settings.AUTH_USER_MODEL)),
            ('inventory',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='cosmetic_grants',to='club.userinventory')),
        ],options={'constraints':[models.UniqueConstraint(fields=['inventory','kind','key'],name='unique_inventory_cosmetic')]}),
        migrations.RunPython(stock_themes,migrations.RunPython.noop),
    ]
