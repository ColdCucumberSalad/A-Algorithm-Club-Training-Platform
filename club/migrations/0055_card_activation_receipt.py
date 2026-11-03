from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('club', '0054_card_consumed')]

    operations = [
        migrations.AddField(
            model_name='proredeemcode', name='activation_token_hash',
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name='proredeemcode', name='activation_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
