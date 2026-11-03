from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('club', '0053_app_pro_codes')]

    operations = [
        migrations.AddField(
            model_name='proredeemcode', name='consumed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
