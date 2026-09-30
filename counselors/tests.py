from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch


class CounselorPortalTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.get_or_create(name="Counselor Portal Branch")[0]

        self.counselor = User.objects.create_user(
            username="cp_counselor", password="pwd12345678", role=UserRole.COUNSELOR, branch=self.branch
        )
        self.other_counselor = User.objects.create_user(
            username="cp_other_counselor", password="pwd12345678", role=UserRole.COUNSELOR, branch=self.branch
        )

        self.my_telecaller = User.objects.create_user(
            username="cp_my_telecaller", password="pwd12345678", role=UserRole.TELECALLER,
            branch=self.branch, counselor=self.counselor
        )
        self.other_telecaller = User.objects.create_user(
            username="cp_other_telecaller", password="pwd12345678", role=UserRole.TELECALLER,
            branch=self.branch, counselor=self.other_counselor
        )

    def test_counselor_dashboard_renders_and_scopes_to_self(self):
        self.client.login(username="cp_counselor", password="pwd12345678")
        resp = self.client.get(reverse('counselor_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['my_leads_count'], 0)

    def test_counselor_telecallers_list_only_shows_own_telecallers(self):
        self.client.login(username="cp_counselor", password="pwd12345678")
        resp = self.client.get(reverse('counselor_telecallers_list'))
        self.assertContains(resp, 'cp_my_telecaller')
        self.assertNotContains(resp, 'cp_other_telecaller')
