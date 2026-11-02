"""Versioned administrator edits without taking ownership or changing submission dates."""
import re
from django.contrib.auth.models import User
from django.db import transaction
from django.http import JsonResponse
from .views import api_login_required,api_error,body,membership_for,serialize_submission,score_part
from .models import Submission,SubmissionPart,Semester,ReviewLog
from .services import refresh_totals


@api_login_required
def edit_submission(request,submission_id):
    if request.method not in ('GET','PATCH'):return api_error('仅支持 GET 或 PATCH',405)
    viewer=membership_for(request)
    if not request.user.is_superuser and (not viewer or not viewer.is_admin):return api_error('需要管理权限',403)
    query=Submission.objects.filter(pk=submission_id).select_related('member','problem','week','semester')
    if not request.user.is_superuser:query=query.filter(team=viewer.team)
    target=query.first()
    if not target:return api_error('提交不存在',404)
    if target.member.user_id==request.user.pk:return api_error('不能通过管理入口编辑自己的提交，请使用本人提交入口',403)
    if getattr(request,'admin_test_mode',False):return api_error('请退出测试模式后管理题解',403)
    if request.method=='GET':return JsonResponse({'submission':serialize_submission(target)})
    data=body(request)
    if not isinstance(data,dict):return api_error('题解格式无效')
    for key,limit in [('logic',50000),('blog',100000),('code',200000)]:
        if not isinstance(data.get(key,''),str) or len(data.get(key,''))>limit:return api_error('题解内容过长或格式无效')
    language=data.get('code_language','text')
    if language not in {'text','cpp','c','python','java','javascript','typescript','go','rust','csharp','kotlin','swift','sql','bash'}:return api_error('代码语言无效')
    if not data.get('code','').strip():return api_error('请填写解题代码')
    with transaction.atomic():
        User.objects.select_for_update().get(pk=target.member.user_id)
        semester=Semester.objects.select_for_update().get(pk=target.semester_id)
        target=Submission.objects.select_for_update(of=('self',)).select_related('member','week','problem','semester').get(pk=target.pk)
        if semester.archived_at:return api_error('已归档学期不能编辑',409)
        if type(data.get('version')) is not int or data['version']!=target.version:return api_error('题解已经变化，请重新打开后编辑',409)
        target.parts.filter(kind__in=['logic','blog','code']).delete()
        for kind in ('logic','blog','code'):
            text=data.get(kind,'').strip() if kind!='code' else data[kind]
            if not text:continue
            if kind=='code':
                fence='`'*max(3,max((len(run) for run in re.findall(r'`+',text)),default=0)+1)
                text=f'{fence}{language}\n{text}\n{fence}'
            part=SubmissionPart(submission=target,kind=kind,text_content=text,status='approved' if target.is_valid else 'rejected')
            part.points_awarded=score_part(part) if target.is_valid else 0
            part.save()
        target.version+=1;target.save(update_fields=['version'])
        # Changes invalidate the old material version; leave an explicit review trail.
        from django.utils import timezone
        target.reports.filter(status='pending').update(status='dismissed',resolved_by=request.user,resolved_at=timezone.now(),note='管理员已修改题解，请按新版本核对')
        target.likes.all().delete()
        ReviewLog.objects.create(submission=target,actor=request.user,action='admin_edit',detail={'version':target.version})
        refresh_totals(semester)
    return JsonResponse({'ok':True,'submission':serialize_submission(target)})
