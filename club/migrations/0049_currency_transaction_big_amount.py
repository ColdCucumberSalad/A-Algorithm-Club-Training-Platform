from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('club', '0048_merge_account_problem_branches')]
    operations = [
        migrations.AlterField(model_name='currencytransaction', name='amount',
            field=models.BigIntegerField(verbose_name='变动金额')),
    ]
