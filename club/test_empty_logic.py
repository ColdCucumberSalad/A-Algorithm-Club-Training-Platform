import json
from unittest.mock import patch

from django.test import TestCase

from . import test_community as fixtures
from .models import Submission,SubmissionPart,SemesterMemberTotal
from .services import approve_submission_parts,score_part
from .views import serialize_part


class EmptyLogicTests(TestCase):
    setUp=fixtures.CommunityTests.setUp
    image=fixtures.CommunityTests.image

    def submit(self,logic=''):
        with patch('club.problem_parser.get_problem',return_value=self.problem):
            response=self.client.post('/api/submissions',{'week_id':self.week.pk,'problem_url':self.problem.url,
                'proof':self.image(),'code':'int main() {}','logic':logic})
        self.assertEqual(response.status_code,201,response.content)
        return Submission.objects.get(pk=response.json()['submission']['id'])

    def test_placeholder_submission_has_no_logic_part_or_extra_points(self):
        row=self.submit(' \n未提交题解思路。\t ')
        self.assertFalse(row.parts.filter(kind='logic').exists())
        total=SemesterMemberTotal.objects.get(member=self.author_member)
        self.assertEqual((total.total_score,total.total_submissions),(1,1))

    def test_blank_submission_has_no_logic_points(self):
        row=self.submit(' \n\t ')
        self.assertFalse(row.parts.filter(kind='logic').exists())
        self.assertEqual(SemesterMemberTotal.objects.get(member=self.author_member).total_score,1)

    def test_editing_to_placeholder_removes_logic_score_without_removing_proof(self):
        row=self.submit('Real solution')
        proof=row.parts.get(kind='proof').upload.name
        with patch('club.problem_parser.get_problem',return_value=self.problem):
            response=self.client.post(f'/api/submissions/{row.pk}/edit',{'week_id':self.week.pk,
                'version':row.version,'problem_url':self.problem.url,'code':'int main() {}','logic':'未提交题解思路。'})
        self.assertEqual(response.status_code,201,response.content)
        self.assertFalse(row.parts.filter(kind='logic').exists())
        self.assertEqual(row.parts.get(kind='proof').upload.name,proof)
        self.assertEqual(SemesterMemberTotal.objects.get(member=self.author_member).total_score,1)

    def test_admin_edit_does_not_award_placeholder_logic(self):
        row=self.submit('Real solution')
        self.client.force_login(self.owner)
        response=self.client.patch(f'/api/management/submissions/{row.pk}',json.dumps({
            'version':row.version,'logic':'未提交题解思路。','blog':'','code':'int main() {}','code_language':'cpp'}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertFalse(row.parts.filter(kind='logic').exists())
        self.assertEqual(SemesterMemberTotal.objects.get(member=self.author_member).total_score,1)

    def test_placeholder_cannot_be_approved_or_exposed_as_scoring_content(self):
        row=self.submit()
        part=SubmissionPart.objects.create(submission=row,kind='logic',text_content='未提交题解思路。',status='pending')
        self.assertEqual(approve_submission_parts(self.owner,self.team,part_ids=[part.pk]),0)
        part.refresh_from_db()
        self.assertEqual((part.status,part.points_awarded),('pending',0))
        for text in ('',' \n\t ','未提交题解思路。','未提交题解思路','未提交题解思路.'):
            part.text_content=text;part.points_awarded=9
            self.assertFalse(part.has_content)
            self.assertEqual(score_part(part),0)
            self.assertEqual((serialize_part(part)['text'],serialize_part(part)['points']),('',0))
        part.text_content='未提交题解思路。现在补充完整证明：逐项求和。'
        self.assertTrue(part.has_content)
        self.assertEqual(score_part(part),self.semester.logic_points)
