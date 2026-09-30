from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch
from leads.models import Lead, LeadStatus, LeadOwnerType, LeadStatusHistory


class BranchHeadLeadViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.get_or_create(name="BHL Branch")[0]
        self.other_branch = Branch.objects.get_or_create(name="BHL Other Branch")[0]

        self.branch_head = User.objects.create_user(
            username="bhl_branchhead", password="pwd12345678", role=UserRole.BRANCH_HEAD, branch=self.branch
        )
        self.lead = Lead.objects.create(name="BHL Lead", phone="9000000010", branch=self.branch)
        self.other_lead = Lead.objects.create(name="BHL Other Lead", phone="9000000011", branch=self.other_branch)

    def test_branch_head_leads_list_scoped_to_own_branch(self):
        self.client.login(username="bhl_branchhead", password="pwd12345678")
        resp = self.client.get(reverse('branch_head_leads_list'))
        self.assertContains(resp, 'BHL Lead')
        self.assertNotContains(resp, 'BHL Other Lead')

    def test_branch_head_cannot_view_lead_from_other_branch(self):
        self.client.login(username="bhl_branchhead", password="pwd12345678")
        resp = self.client.get(reverse('branch_head_lead_detail', args=[self.other_lead.pk]))
        self.assertEqual(resp.status_code, 404)


class CounselorLeadViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.get_or_create(name="CLV Branch")[0]

        self.counselor = User.objects.create_user(
            username="clv_counselor", password="pwd12345678", role=UserRole.COUNSELOR, branch=self.branch
        )
        self.other_counselor = User.objects.create_user(
            username="clv_other_counselor", password="pwd12345678", role=UserRole.COUNSELOR, branch=self.branch
        )

        self.my_lead = Lead.objects.create(
            name="CLV My Lead", phone="9000000020", branch=self.branch,
            assigned_counselor=self.counselor, current_owner_type=LeadOwnerType.COUNSELOR,
            status=LeadStatus.VISITED,
        )
        self.other_lead = Lead.objects.create(
            name="CLV Other Lead", phone="9000000021", branch=self.branch,
            assigned_counselor=self.other_counselor, current_owner_type=LeadOwnerType.COUNSELOR,
        )

    def test_counselor_leads_list_only_shows_own_leads(self):
        self.client.login(username="clv_counselor", password="pwd12345678")
        resp = self.client.get(reverse('counselor_leads_list'))
        self.assertContains(resp, 'CLV My Lead')
        self.assertNotContains(resp, 'CLV Other Lead')

    def test_counselor_cannot_view_another_counselors_lead(self):
        self.client.login(username="clv_counselor", password="pwd12345678")
        resp = self.client.get(reverse('counselor_lead_detail', args=[self.other_lead.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_counselor_update_status_transitions_and_records_history(self):
        self.client.login(username="clv_counselor", password="pwd12345678")
        resp = self.client.post(
            reverse('counselor_lead_update_status', args=[self.my_lead.pk]),
            {'status': LeadStatus.COUNSELING, 'remarks': 'Had a great session.'}
        )
        self.assertRedirects(resp, reverse('counselor_lead_detail', args=[self.my_lead.pk]))

        self.my_lead.refresh_from_db()
        self.assertEqual(self.my_lead.status, LeadStatus.COUNSELING)

        history = LeadStatusHistory.objects.filter(lead=self.my_lead).order_by('-created_at').first()
        self.assertIsNotNone(history)
        self.assertEqual(history.old_status, LeadStatus.VISITED)
        self.assertEqual(history.new_status, LeadStatus.COUNSELING)
