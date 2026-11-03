from collections import defaultdict

from django.db import migrations,models


def correct_empty_logic(apps,schema_editor):
    alias=schema_editor.connection.alias
    Part=apps.get_model('club','SubmissionPart')
    Submission=apps.get_model('club','Submission')
    Semester=apps.get_model('club','Semester')
    Total=apps.get_model('club','SemesterMemberTotal')
    Log=apps.get_model('club','ReviewLog')
    placeholders={'','未提交题解思路。','未提交题解思路.','未提交题解思路'}
    affected=defaultdict(set)
    empty_submissions=set()
    for part in Part.objects.using(alias).filter(kind='logic').select_related('submission').iterator(chunk_size=500):
        if part.text_content.strip() not in placeholders:
            continue
        empty=not (part.link or part.upload)
        if empty:empty_submissions.add(part.submission_id)
        points=0 if empty else part.points_awarded
        if part.text_content=='' and part.points_awarded==points:
            continue
        old=part.points_awarded
        Part.objects.using(alias).filter(pk=part.pk).update(text_content='',points_awarded=points)
        if old!=points:
            Log.objects.using(alias).create(submission_id=part.submission_id,part_id=part.pk,
                action='empty_logic_correction',detail={'previous_points':old,'points':points,
                    'reason':'占位或空白题解不计分'})
            if part.status=='approved' and part.submission.is_valid:
                affected[part.submission.semester_id].add(part.submission.member_id)
    ids=sorted(empty_submissions)
    for offset in range(0,len(ids),500):
        for row in Submission.objects.using(alias).filter(pk__in=ids[offset:offset+500]).iterator():
            state=row.duplicate_state
            parts=state.get('parts') if isinstance(state,dict) else None
            logic=parts.get('logic') if isinstance(parts,dict) else None
            if isinstance(logic,dict) and logic.get('points'):
                logic['points']=0
                Submission.objects.using(alias).filter(pk=row.pk).update(duplicate_state=state)
    for semester_id,members in affected.items():
        semester=Semester.objects.using(alias).get(pk=semester_id)
        valid=Submission.objects.using(alias).filter(semester_id=semester_id,member_id__in=members,is_valid=True)
        scores={(r['submission__member_id'],r['submission__week_id']):r['n'] for r in
            Part.objects.using(alias).filter(submission__in=valid,status='approved').order_by().values(
                'submission__member_id','submission__week_id').annotate(n=models.Sum('points_awarded'))}
        counts={(r['member_id'],r['week_id']):r['n'] for r in valid.filter(
            parts__kind='proof',parts__status='approved').order_by().values('member_id','week_id').annotate(
                n=models.Count('pk',distinct=True))}
        weeks=list(semester.weeks.using(alias).filter(is_closed=True))
        for member_id in members:
            qualified=0
            for week in weeks:
                min_score=semester.min_score if week.min_score is None else week.min_score
                min_count=semester.min_submissions if week.min_submissions is None else week.min_submissions
                both=semester.require_both if week.require_both is None else week.require_both
                checks=(scores.get((member_id,week.pk),0)>=min_score,counts.get((member_id,week.pk),0)>=min_count)
                qualified+=int(all(checks) if both else any(checks))
            Total.objects.using(alias).filter(semester_id=semester_id,member_id=member_id).update(
                total_score=sum(score for (mid,wid),score in scores.items() if mid==member_id),qualified_weeks=qualified)


class Migration(migrations.Migration):
    dependencies=[('club','0051_link_tip_ledgers')]
    operations=[migrations.RunPython(correct_empty_logic,migrations.RunPython.noop)]
