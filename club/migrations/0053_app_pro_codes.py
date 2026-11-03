from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('club', '0052_correct_empty_logic_scores'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(model_name='shopitem', name='pro_app', field=models.CharField(blank=True, max_length=40)),
        migrations.AddField(model_name='shopitem', name='pro_duration_days', field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.AddField(model_name='shopfulfillment', name='pro_app', field=models.CharField(blank=True, max_length=40)),
        migrations.AddField(model_name='shopfulfillment', name='pro_duration_days', field=models.PositiveIntegerField(blank=True, null=True)),
        migrations.CreateModel(name='AppRateLimit', fields=[
            ('key', models.CharField(max_length=64, primary_key=True, serialize=False)),
            ('window_start', models.DateTimeField(db_index=True)),
            ('attempts', models.PositiveIntegerField(default=0)),
        ]),
        migrations.CreateModel(name='ProEntitlement', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('app', models.CharField(max_length=40)),
            ('expires_at', models.DateTimeField(blank=True, null=True)),
            ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pro_entitlements', to=settings.AUTH_USER_MODEL)),
        ], options={'constraints': [models.UniqueConstraint(fields=('user', 'app'), name='unique_user_pro_app')]}),
        migrations.CreateModel(name='ProRedeemCode', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('app', models.CharField(max_length=40)),
            ('duration_days', models.PositiveIntegerField()),
            ('code_hash', models.CharField(max_length=64, unique=True)),
            ('issued_at', models.DateTimeField(auto_now_add=True)),
            ('redeemed_at', models.DateTimeField(blank=True, null=True)),
            ('fulfillment', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='pro_code', to='club.shopfulfillment')),
            ('owner', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='pro_codes', to=settings.AUTH_USER_MODEL)),
        ]),
    ]
