import json
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from . import test_community as fixtures
from .models import Submission, Week, TeamMembership

class AdminTestModeTests(TestCase):
    setUp = fixtures.CommunityTests.setUp
    image = fixtures.CommunityTests.image
    def enable(self):
        self.admin=User.objects.get_or_create(username='admin',defaults={'is_superuser':True,'is_staff':True,'password':'!'})[0]
        self.client.force_login(self.admin)
        session=self.client.session;session['team_id']=self.team.pk;session.save()
        response=self.toggle(True)
        self.assertEqual(response.status_code,200,response.content)
        return self.client.get('/api/dashboard').json()
    def toggle(self,value):
        return self.client.post('/api/admin-test-mode',json.dumps({'enabled':value}),content_type='application/json')
    def submit(self,week,day=None,proof=None):
        return self.client.post('/api/submissions',{'week_id':week,'record_date':(day or timezone.localdate()).isoformat(),'problem_url':fixtures.URL,'proof':proof or self.image()})
    def test_gallery_and_detail_combine_private_and_real_solutions(self):
        real = Submission.objects.create(team=self.team, member=self.author_member, semester=self.semester, week=self.week, problem=self.problem)
        dashboard = self.enable()
        private = self.submit(dashboard['current_week']['id'])
        self.assertEqual(private.status_code, 201, private.content)
        private_id = private.json()['submission']['id']
        Submission.objects.filter(pk=private_id).update(problem=self.problem)
        gallery = self.client.get('/api/showcase?all=1').json()
        self.assertEqual(gallery['problems'][0]['count'], 2)
        detail = self.client.get(f'/api/problems/{self.problem.pk}/submissions', {'cursor': ''}).json()
        self.assertEqual({r['id'] for r in detail['submissions']}, {real.pk, private_id})
        real_row = next(r for r in detail['submissions'] if r['id'] == real.pk)
        self.assertFalse(real_row['can_reject'])
        self.assertFalse(real_row['can_tip'])
        self.assertFalse(real_row['own'])

    def test_ordinary_user_cannot_enable_or_forge_session(self):
        self.assertEqual(self.toggle(True).status_code,403)
        s=self.client.session;s['admin_test_user']=self.author.pk;s['admin_test_team']=self.team.pk;s.save()
        self.assertEqual(self.client.get('/api/me').status_code,403)
    def test_enter_exit_and_reuse_preserve_admin_and_real_team(self):
        self.enable()
        me=self.client.get('/api/me').json()
        self.assertTrue(me['test_mode']);self.assertFalse(me['site_admin']);self.assertTrue(me['can_submit'])
        self.assertNotEqual(me['team']['id'],self.team.pk)
        uid=self.client.session['admin_test_user'];team=me['team']['id']
        self.assertEqual(self.toggle(False).status_code,200)
        me=self.client.get('/api/me').json();self.assertTrue(me['site_admin']);self.assertFalse(me['test_mode'])
        self.assertEqual(me['team']['id'],self.team.pk)
        self.assertEqual(self.toggle(True).status_code,200)
        self.assertEqual(self.client.session['admin_test_user'],uid)
        self.assertEqual(self.client.session['admin_test_team'],team)
        self.assertEqual(TeamMembership.objects.filter(team=self.team).count(),3)
    def test_duplicate_closed_week_and_old_dates_are_test_only(self):
        dashboard=self.enable();week=dashboard['current_week']['id']
        Week.objects.filter(pk=week).update(is_closed=True)
        for _ in range(2):
            response=self.submit(week);self.assertEqual(response.status_code,201,response.content)
        old=timezone.localdate()-timedelta(days=240)
        response=self.submit(week,old);self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(Submission.objects.filter(team=self.team).count(),0)
        self.assertEqual(Submission.objects.count(),3)
        self.assertFalse(self.client.get('/api/me').json()['site_admin'])
    def test_upload_validation_and_team_boundaries_remain(self):
        dashboard=self.enable();week=dashboard['current_week']['id']
        bad=SimpleUploadedFile('bad.png',b'not an image',content_type='image/png')
        self.assertEqual(self.submit(week,proof=bad).status_code,400)
        self.assertEqual(self.submit(self.week.pk).status_code,404)
        self.assertEqual(self.client.post('/api/team/select',json.dumps({'team_id':self.team.pk}),content_type='application/json').status_code,200)
        self.assertEqual(Submission.objects.count(),0)
    def test_test_submission_allows_blank_url_and_proof_and_still_scores(self):
        dashboard=self.enable();week=dashboard['current_week']['id']
        for fields in ({}, {}, {'problem_url':fixtures.URL}, {'proof':self.image()}):
            response=self.client.post('/api/submissions',dict(week_id=week,**fields))
            self.assertEqual(response.status_code,201,response.content)
        submissions=Submission.objects.order_by('pk')
        self.assertEqual(submissions.count(),4)
        self.assertNotEqual(submissions[0].problem_id,submissions[1].problem_id)
        self.assertEqual(submissions[0].problem.url,'')
        for submission in submissions:
            part=submission.parts.get(kind='proof')
            self.assertEqual(part.status,'approved')
            self.assertGreater(part.points_awarded,0)
        private=self.client.get('/api/submissions?mine=1').json()['submissions']
        item=private[0]
        response=self.client.post(f"/api/submissions/{item['id']}/edit",{
            'week_id':item['week_id'],'version':item['version'],'problem_url':''})
        self.assertEqual(response.status_code,201,response.content)
        self.assertEqual(Submission.objects.filter(team=self.team).count(),0)
    def test_normal_submission_still_requires_url_and_proof(self):
        self.assertEqual(self.client.post('/api/submissions',{'week_id':self.week.pk,'problem_url':fixtures.URL}).status_code,400)
        self.assertEqual(self.client.post('/api/submissions',{'week_id':self.week.pk,'proof':self.image()}).status_code,400)
        self.assertEqual(Submission.objects.count(),0)
    def test_revoked_admin_cannot_keep_bypass(self):
        self.enable();User.objects.filter(pk=self.admin.pk).update(is_superuser=False)
        self.assertEqual(self.client.get('/api/me').status_code,403)
    def test_switch_requires_csrf(self):
        admin=User.objects.get_or_create(username='admin',defaults={'is_superuser':True,'is_staff':True,'password':'!'})[0]
        c=Client(enforce_csrf_checks=True);c.force_login(admin)
        self.assertEqual(c.post('/api/admin-test-mode',json.dumps({'enabled':True}),content_type='application/json').status_code,403)

    def test_invalid_sandbox_can_exit_without_granting_member_access(self):
        self.enable()
        uid=self.client.session['admin_test_user']
        User.objects.filter(pk=uid).update(first_name='invalid')
        self.assertEqual(self.client.get('/api/me').status_code,403)
        self.assertEqual(self.toggle(False).status_code,200)
        self.assertTrue(self.client.get('/api/me').json()['site_admin'])

    def test_ordinary_users_cannot_join_private_sandbox(self):
        self.enable()
        code=self.client.get('/api/me').json()['team']['code']
        self.toggle(False)
        self.client.force_login(self.reader)
        response=self.client.post('/api/auth/join',json.dumps({'team_code':code,'name':'outsider'}),content_type='application/json')
        self.assertEqual(response.status_code,403,response.content)

    def test_selected_team_context_and_private_records_are_not_visible_to_members(self):
        dashboard=self.enable()
        me=self.client.get('/api/me').json()
        self.assertEqual(me['test_target_team']['id'],self.team.pk)
        response=self.submit(dashboard['current_week']['id']);self.assertEqual(response.status_code,201,response.content)
        record=Submission.objects.get(pk=response.json()['submission']['id'])
        self.assertNotEqual(record.team_id,self.team.pk)
        member_id=record.member_id
        attachment=record.parts.get(kind='proof').pk
        self.toggle(False);self.client.force_login(self.reader)
        members=self.client.get('/api/members').json()['members']
        self.assertNotIn(member_id,[m['id'] for m in members])
        self.assertNotEqual(self.client.get(f'/api/attachments/{attachment}').status_code,200)
        self.assertEqual(Submission.objects.filter(team=self.team).count(),0)
        payload=self.client.get('/api/submissions').json()
        self.assertNotIn(record.pk,[r['id'] for r in payload['submissions']])
    def test_switching_targets_keeps_separate_records_and_copies_settings(self):
        from .models import Team,Semester
        self.enable()
        first=self.client.session['admin_test_team']
        other=Team.objects.create(name='Other',code='OTHER',created_by=self.owner,daily_checkin_reward=7)
        Semester.objects.create(team=other,name='Other semester',starts_on=timezone.localdate()-timedelta(days=7),ends_on=timezone.localdate()+timedelta(days=30),min_score=42)
        response=self.client.post('/api/team/select',json.dumps({'team_id':other.pk}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        me=self.client.get('/api/me').json();self.assertEqual(me['test_target_team']['id'],other.pk)
        second=self.client.session['admin_test_team'];self.assertNotEqual(first,second)
        self.assertEqual(Team.objects.get(pk=second).daily_checkin_reward,7)
        self.assertEqual(Team.objects.get(pk=second).semesters.get(is_active=True).min_score,42)
        self.client.post('/api/team/select',json.dumps({'team_id':self.team.pk}),content_type='application/json')
        self.assertEqual(self.client.session['admin_test_team'],first)

    def test_relogin_recovers_legacy_test_session(self):
        self.enable()
        self.admin.set_password('test-password');self.admin.save()
        self.client.force_login(self.admin)
        session=self.client.session;session.pop('admin_test_target',None);session.save()
        response=self.client.post('/api/auth/login',json.dumps({'account':'admin','password':'test-password'}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        me=self.client.get('/api/me').json();self.assertTrue(me['site_admin']);self.assertFalse(me['test_mode'])
    def test_logout_remains_available_during_test_mode(self):
        self.enable()
        self.assertEqual(self.client.post('/api/auth/logout').status_code,200)
        self.assertEqual(self.client.get('/api/me').status_code,401)
    def test_legacy_target_missing_restores_admin_without_login(self):
        self.enable()
        session=self.client.session;session.pop('admin_test_target',None);session.save()
        me=self.client.get('/api/me').json()
        self.assertTrue(me['site_admin']);self.assertFalse(me['test_mode'])

    def test_overlay_includes_real_members_and_private_ranking_only_for_admin(self):
        from django.test import Client
        from .models import SubmissionPart
        real=Submission.objects.create(team=self.team,member=self.author_member,semester=self.semester,week=self.week,problem=self.problem,record_date=timezone.localdate())
        SubmissionPart.objects.create(submission=real,kind='proof',status='approved',points_awarded=5)
        normal=Client();normal.force_login(self.reader)
        baseline=normal.get('/api/leaderboard?scope=solved').json()
        dashboard=self.enable();private_week=dashboard['current_week']['id']
        response=self.submit(private_week);self.assertEqual(response.status_code,201,response.content)
        record=Submission.objects.get(pk=response.json()['submission']['id'])
        members=self.client.get('/api/members').json()['members']
        self.assertIn(self.author_member.pk,[r['id'] for r in members])
        self.assertIn(self.owner_member.pk,[r['id'] for r in members])
        self.assertEqual(len(members),4)
        test=next(r for r in members if r.get('is_test'))
        self.assertEqual(test['id'],record.member_id);self.assertEqual(test['score'],1)
        self.assertTrue(all(not r['can_kick'] for r in members))
        board=self.client.get('/api/leaderboard?scope=solved').json()
        self.assertEqual(len(board['rows']),4)
        current=next(r for r in board['rows'] if r['isCurrent'])
        self.assertTrue(current['is_test']);self.assertEqual(current['value'],1);self.assertEqual(current['rank'],1)
        summary=self.client.get('/api/dashboard').json()
        self.assertEqual(summary['stats']['memberCount'],4)
        self.assertEqual(summary['stats']['rank'],2)
        self.assertEqual(summary['score'],1)
        self.assertEqual(normal.get('/api/leaderboard?scope=solved').json(),baseline)
        self.assertNotIn(record.member_id,[r['id'] for r in normal.get('/api/members').json()['members']])
        private_part=record.parts.get(kind='proof').pk
        self.assertNotEqual(normal.get(f'/api/attachments/{private_part}').status_code,200)
        self.assertEqual(self.client.put(f'/api/submissions/{real.pk}/like').status_code,404)
        self.assertEqual(Submission.objects.filter(team=self.team).count(),1)
    def test_overlay_real_and_private_submission_readers(self):
        from .models import SubmissionPart
        real=Submission.objects.create(team=self.team,member=self.author_member,semester=self.semester,week=self.week,problem=self.problem,record_date=timezone.localdate())
        part=SubmissionPart.objects.create(submission=real,kind='proof',status='approved',points_awarded=1,upload=self.image())
        dashboard=self.enable()
        response=self.submit(dashboard['current_week']['id']);self.assertEqual(response.status_code,201,response.content)
        private_id=response.json()['submission']['id']
        listing=self.client.get('/api/submissions').json()['submissions']
        self.assertEqual({r['id'] for r in listing},{real.pk,private_id})
        self.assertFalse(next(r for r in listing if r['id']==real.pk)['can_edit'])
        self.assertEqual({r['id'] for r in self.client.get('/api/submissions?mine=1').json()['submissions']},{private_id})
        history=self.client.get(f'/api/members/{self.author_member.pk}/history')
        self.assertEqual(history.status_code,200,history.content)
        gallery=self.client.get('/api/showcase').json()
        self.assertIn(self.problem.pk,[r['id'] for r in gallery['problems']])
        self.assertTrue(any(r.get('is_test') for r in gallery['problems']))
        self.assertEqual(self.client.get(f'/api/problems/{self.problem.pk}/submissions').status_code,200)
        self.assertEqual(self.client.get(f'/api/attachments/{part.pk}').status_code,200)
        self.assertIn(self.semester.pk,[s['id'] for s in self.client.get('/api/semesters').json()['semesters']])
        own=Submission.objects.get(pk=private_id)
        history=self.client.get(f'/api/members/{own.member_id}/history?semester={self.semester.pk}&week={self.week.number}')
        self.assertEqual(history.status_code,200,history.content)
        self.assertEqual(history.json()['summary']['submissions'],1)
