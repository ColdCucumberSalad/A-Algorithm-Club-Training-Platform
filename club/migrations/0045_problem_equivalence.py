from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('club', '0044_merge_tracker_notifications')]
    operations = [
        migrations.AddField(model_name='problem', name='canonical', field=models.ForeignKey(
            null=True, blank=True, on_delete=django.db.models.deletion.PROTECT, related_name='aliases', to='club.problem')),
        migrations.AddField(model_name='submission', name='is_duplicate', field=models.BooleanField(default=False)),
        migrations.CreateModel(name='ProblemComparison', fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('first_title', models.CharField(max_length=200)),
            ('second_title', models.CharField(max_length=200)),
            ('same', models.BooleanField()),
            ('checked_at', models.DateTimeField(auto_now=True)),
            ('first', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='club.problem')),
            ('second', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='club.problem')),
        ], options={'constraints':[models.UniqueConstraint(fields=('first','second'), name='unique_problem_comparison')]}),
    ]
