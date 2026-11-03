from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


def merge_wallets(apps, schema_editor):
    Balance=apps.get_model('club','CurrencyBalance')
    Ledger=apps.get_model('club','CurrencyTransaction')
    Membership=apps.get_model('club','TeamMembership')
    Ledger.objects.filter(member_id__isnull=False).update(user_id=models.Subquery(Membership.objects.filter(pk=models.OuterRef('member_id')).values('user_id')[:1]))
    for uid in Balance.objects.values_list('member__user_id',flat=True).distinct():
        if uid is None: continue
        rows=list(Balance.objects.filter(member__user_id=uid).order_by('pk'))
        total=sum(row.balance for row in rows)
        if not -2147483648 <= total <= 2147483647:
            raise ValueError('合并后余额超出范围，请先核对账号 %s 的余额' % uid)
        first=rows[0]
        Balance.objects.filter(pk__in=[row.pk for row in rows[1:]]).delete()
        Balance.objects.filter(pk=first.pk).update(user_id=uid,balance=total)


class Migration(migrations.Migration):
    dependencies=[('club','0045_account_closure_report_reasons'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.AddField(model_name='currencybalance',name='user',field=models.OneToOneField(null=True,on_delete=django.db.models.deletion.CASCADE,related_name='coin_wallet',to=settings.AUTH_USER_MODEL)),
        migrations.AlterField(model_name='currencybalance',name='team',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='currency_balances',to='club.team')),
        migrations.AlterField(model_name='currencybalance',name='member',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='currency_balance',to='club.teammembership')),
        migrations.AddField(model_name='teammembership',name='worn_titles',field=models.JSONField(blank=True,default=None,null=True)),
        migrations.AddField(model_name='currencytransaction',name='user',field=models.ForeignKey(null=True,on_delete=django.db.models.deletion.CASCADE,related_name='coin_transactions',to=settings.AUTH_USER_MODEL)),
        migrations.AlterField(model_name='currencytransaction',name='team',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='currency_transactions',to='club.team')),
        migrations.AlterField(model_name='currencytransaction',name='member',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='currency_transactions',to='club.teammembership')),
        migrations.RunPython(merge_wallets, migrations.RunPython.noop),
    ]
