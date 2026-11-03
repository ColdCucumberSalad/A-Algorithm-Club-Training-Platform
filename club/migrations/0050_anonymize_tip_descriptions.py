import re

from django.db import migrations


def anonymize_tip_descriptions(apps, schema_editor):
    Transaction=apps.get_model('club','CurrencyTransaction')
    rows=Transaction.objects.using(schema_editor.connection.alias).filter(
        transaction_type__in=['tip_sent','tip_received']).only('pk','transaction_type','description').order_by('pk')
    batch=[]
    for row in rows.iterator(chunk_size=500):
        matches=re.findall(r'提交\s*#([0-9]+)',row.description)
        if matches:
            row.description=(f'打赏提交 #{matches[-1]}' if row.transaction_type=='tip_sent'
                else f'收到提交 #{matches[-1]} 的打赏')
        else:
            row.description='打赏支出' if row.transaction_type=='tip_sent' else '收到打赏'
        batch.append(row)
        if len(batch)==500:
            Transaction.objects.using(schema_editor.connection.alias).bulk_update(batch,['description'])
            batch=[]
    if batch:
        Transaction.objects.using(schema_editor.connection.alias).bulk_update(batch,['description'])


class Migration(migrations.Migration):
    dependencies=[('club','0049_currency_transaction_big_amount')]
    operations=[migrations.RunPython(anonymize_tip_descriptions,migrations.RunPython.noop)]
