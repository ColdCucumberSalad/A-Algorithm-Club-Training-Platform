from django.db import migrations,models


def seed_assets(apps,schema_editor):
    Asset=apps.get_model('club','CosmeticAsset');Grant=apps.get_model('club','CosmeticGrant')
    roles=('pageBackground','surface','surfaceElevated','separator','labelPrimary','labelSecondary','labelTertiary','fill','accent','overlayDim')
    palettes={
      'light':dict(zip(roles,('#fff3f7','#fff9fb','#fffafd','#e8cdd8','#513d46','#92717e','#a98a97','#f9eaf0','#b96c88','#36252e99'))),
      'dark':dict(zip(roles,('#24151f','#2c1d26','#30212a','#60424f','#f3e6ec','#bca1af','#a68a99','#3d2834','#dfa0b7','#160c12bd'))),
    }
    definitions=[
      {'kind':'theme','key':'taffy','name':'塔菲 · 小菲滚轴','icon':'/static/cosmetics/taffy-original-head.svg','poster':'/static/cosmetics/taffy-scroll.jpg','background':'/static/cosmetics/taffy-scroll.jpg','palettes':palettes},
      {'kind':'badge','key':'taffy','name':'小塔菲 · 原版','icon':'/static/cosmetics/taffy-original-head.svg'},
      {'kind':'frame','key':'taffy-goggles','name':'塔菲护目镜','icon':'/static/cosmetics/taffy-goggles-frame.svg','geometry':{'scale':1.25,'x':-.125,'y':-.225}},
      {'kind':'badge','key':'rbc-pendant','name':'RBC 挂坠纪念徽章','icon':'/static/cosmetics/rbc-pendant-badge.png'},
    ]
    for definition in definitions:
        definition={**definition,'duration_days':0,'description':''}
        Asset.objects.using(schema_editor.connection.alias).get_or_create(kind=definition['kind'],key=definition['key'],defaults={'name':definition['name'],'definition':definition})
        Grant.objects.using(schema_editor.connection.alias).filter(kind=definition['kind'],key=definition['key'],definition={}).update(definition=definition)


class Migration(migrations.Migration):
    dependencies=[('club','0065_rbc_pendant_badge')]
    operations=[
      migrations.AddField(model_name='shopitem',name='cosmetic_bundle',field=models.JSONField(default=list,blank=True)),
      migrations.AddField(model_name='purchase',name='cosmetic_snapshot',field=models.JSONField(default=list,blank=True)),
      migrations.AddField(model_name='cosmeticgrant',name='definition',field=models.JSONField(default=dict,blank=True)),
      migrations.CreateModel(name='CosmeticAsset',fields=[
        ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
        ('key',models.CharField(max_length=40)),('kind',models.CharField(max_length=10)),('name',models.CharField(max_length=100)),
        ('definition',models.JSONField(default=dict)),('revision',models.PositiveIntegerField(default=1)),
        ('is_active',models.BooleanField(default=True)),('updated_at',models.DateTimeField(auto_now=True)),
      ],options={'constraints':[models.UniqueConstraint(fields=['kind','key'],name='unique_cosmetic_asset_kind_key')]}),
      migrations.RunPython(seed_assets,migrations.RunPython.noop),
    ]
