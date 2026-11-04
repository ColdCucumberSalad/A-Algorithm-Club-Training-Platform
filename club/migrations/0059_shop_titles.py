from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('club','0058_poker_chip_wallet'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name='shopitem', name='title_definition', field=models.JSONField(blank=True,default=dict,verbose_name='称号外观')),
        migrations.CreateModel(name='OwnedTitle', fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('text',models.CharField(max_length=20)),
            ('definition',models.JSONField(default=dict)),
            ('acquired_at',models.DateTimeField(auto_now_add=True)),
            ('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='owned_titles',to=settings.AUTH_USER_MODEL)),
            ('item',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='title_owners',to='club.shopitem')),
            ('inventory',models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,related_name='owned_title',to='club.userinventory')),
        ], options={'constraints':[models.UniqueConstraint(fields=('user','text'),name='unique_user_owned_title')]}),
    ]
