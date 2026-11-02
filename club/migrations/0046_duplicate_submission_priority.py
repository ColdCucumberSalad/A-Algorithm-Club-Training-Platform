from django.db import migrations, models
from django.db.models import F
from django.utils import timezone


def backfill(apps, schema_editor):
    Submission = apps.get_model('club', 'Submission')
    rows = Submission.objects.using(schema_editor.connection.alias)
    rows.update(first_submitted_at=F('submitted_at'))
    # Merged legacy duplicates no longer retain an authoritative original URL.
    # Leave them unknown instead of inventing a link that could block the winner.
    for row in rows.filter(is_duplicate=False, problem__isnull=False, problem__aliases__isnull=True).select_related('problem').iterator():
        rows.filter(pk=row.pk).update(original_problem_url=row.problem.url)


class Migration(migrations.Migration):
    dependencies = [('club', '0045_problem_equivalence')]
    operations = [
        migrations.AddField(model_name='submission', name='original_problem_url', field=models.URLField(max_length=1000, blank=True)),
        migrations.AddField(model_name='submission', name='first_submitted_at', field=models.DateTimeField(default=timezone.now, editable=False)),
        migrations.AddField(model_name='submission', name='duplicate_state', field=models.JSONField(default=dict, blank=True)),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
