from django.db import migrations,models


def grant_existing_frames(apps,schema_editor):
    Grant=apps.get_model('club','CosmeticGrant')
    for source in Grant.objects.filter(kind='theme',key='taffy',inventory__quantity__gt=0).iterator():
        Grant.objects.get_or_create(user_id=source.user_id,inventory_id=source.inventory_id,kind='frame',key='taffy-goggles',defaults={'expires_at':source.expires_at})


class Migration(migrations.Migration):
    dependencies=[('club','0062_retire_redrawn_badge')]
    operations=[
        migrations.AddField(model_name='shopitem',name='cosmetic_duration_days',field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='purchase',name='cosmetic_duration_days',field=models.PositiveIntegerField(default=0)),
        migrations.AddField(model_name='purchase',name='cosmetic_expires_at',field=models.DateTimeField(null=True,blank=True)),
        migrations.AddField(model_name='ownedtitle',name='expires_at',field=models.DateTimeField(null=True,blank=True)),
        migrations.AddField(model_name='cosmeticgrant',name='expires_at',field=models.DateTimeField(null=True,blank=True)),
        migrations.AddField(model_name='teammembership',name='worn_avatar_frame',field=models.CharField(max_length=40,blank=True)),
        migrations.RunPython(grant_existing_frames,migrations.RunPython.noop),
    ]
