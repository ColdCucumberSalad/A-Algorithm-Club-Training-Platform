from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('club', '0055_card_activation_receipt')]

    operations = [
        migrations.AddField(model_name='shopitem', name='allow_multiple_purchase',
            field=models.BooleanField(default=False, verbose_name='允许单次多购')),
        migrations.AddField(model_name='shopfulfillment', name='api_num',
            field=models.PositiveIntegerField(blank=True, null=True)),
    ]
