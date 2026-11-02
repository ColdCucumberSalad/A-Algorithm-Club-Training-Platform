from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):
    dependencies=[('club','0044_merge_tracker_notifications'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.AddField(model_name='submissionreport',name='reason',field=models.CharField(max_length=500,blank=True)),
        migrations.AddField(model_name='submissionreport',name='generation',field=models.PositiveIntegerField(default=1)),
        migrations.AlterField(model_name='submissionreport',name='status',field=models.CharField(max_length=12,default='pending',choices=[('pending','待处理'),('dismissed','已驳回'),('rejected','已退回'),('cancelled','已取消')])),
        migrations.CreateModel(name='AccountClosure',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('closed_at',models.DateTimeField(auto_now_add=True)),
            ('user',models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,related_name='account_closure',to=settings.AUTH_USER_MODEL)),
            ('closed_by',models.ForeignKey(null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='closed_accounts',to=settings.AUTH_USER_MODEL)),
        ]),
    ]
