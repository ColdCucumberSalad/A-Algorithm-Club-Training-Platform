from django.db import migrations,models


def snapshot_gifts(apps,schema_editor):
    Gift=apps.get_model('club','PurchaseBadgeGrant');Asset=apps.get_model('club','CosmeticAsset')
    for asset in Asset.objects.using(schema_editor.connection.alias).filter(kind='badge').iterator():
        Gift.objects.using(schema_editor.connection.alias).filter(key=asset.key,definition={}).update(definition={**asset.definition,'revision':asset.revision})


class Migration(migrations.Migration):
    dependencies=[('club','0066_universal_cosmetics')]
    operations=[
        migrations.AddField(model_name='purchasebadgegrant',name='definition',field=models.JSONField(default=dict,blank=True)),
        migrations.RunPython(snapshot_gifts,migrations.RunPython.noop),
    ]
