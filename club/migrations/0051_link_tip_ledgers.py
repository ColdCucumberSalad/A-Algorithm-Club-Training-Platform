from bisect import bisect_right
from collections import defaultdict
import re

from django.db import migrations, models
import django.db.models.deletion


def link_legacy_tips(apps, schema_editor):
    Tip=apps.get_model('club','SubmissionTip')
    Ledger=apps.get_model('club','CurrencyTransaction')
    alias=schema_editor.connection.alias
    groups=defaultdict(list)
    for tip in Tip.objects.using(alias).select_related('sender','recipient').order_by('created_at','pk'):
        if tip.submission_id is None:
            continue
        sender_id=tip.sender_user_id or (tip.sender.user_id if tip.sender else None)
        recipient_id=tip.recipient.user_id if tip.recipient else None
        for kind,member_id,user_id in [('tip_sent',tip.sender_id,sender_id),('tip_received',tip.recipient_id,recipient_id)]:
            if user_id:
                groups[(kind,tip.team_id,member_id,user_id,str(tip.submission_id),tip.amount)].append(tip)
    times={key:[tip.created_at for tip in tips] for key,tips in groups.items()}
    previous={}
    used=set()
    batch=[]
    rows=Ledger.objects.using(alias).filter(transaction_type__in=['tip_sent','tip_received']).select_related('member').order_by('created_at','pk')
    for row in rows.iterator(chunk_size=500):
        if ((row.transaction_type=='tip_sent' and row.amount>=0)
                or (row.transaction_type=='tip_received' and row.amount<=0)):
            continue
        matches=re.findall(r'提交\s*#([0-9]+)',row.description)
        user_id=row.user_id or (row.member.user_id if row.member else None)
        if not matches or not user_id:
            continue
        key=(row.transaction_type,row.team_id,row.member_id,user_id,matches[-1],abs(row.amount))
        prior=previous.get(key)
        previous[key]=row.created_at
        tips=groups.get(key,[])
        dates=times.get(key,[])
        lo=bisect_right(dates,prior) if prior is not None else 0
        hi=bisect_right(dates,row.created_at)
        candidates=[tip for tip in tips[lo:hi] if (tip.pk,row.transaction_type) not in used]
        # Receipts are created before their ledgers in one serialized transfer.
        # Missing/ambiguous history remains unlinked; never guess the identity.
        if len(candidates)!=1:
            continue
        row.tip_id=candidates[0].pk
        used.add((row.tip_id,row.transaction_type))
        batch.append(row)
        if len(batch)==500:
            Ledger.objects.using(alias).bulk_update(batch,['tip'])
            batch=[]
    if batch:
        Ledger.objects.using(alias).bulk_update(batch,['tip'])


class Migration(migrations.Migration):
    dependencies=[('club','0050_anonymize_tip_descriptions')]
    operations=[
        migrations.AddField(model_name='currencytransaction',name='tip',
            field=models.ForeignKey(null=True,blank=True,on_delete=django.db.models.deletion.SET_NULL,
                related_name='ledger_entries',to='club.submissiontip')),
        migrations.RunPython(link_legacy_tips,migrations.RunPython.noop),
        migrations.AddConstraint(model_name='currencytransaction',constraint=models.UniqueConstraint(
            fields=['tip','transaction_type'],name='unique_tip_ledger_direction')),
    ]
