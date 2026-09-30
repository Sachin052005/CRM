from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch, SalesHeadBranchAccess
from leads.models import Lead


class LeadUrlManipulationTests(TestCase):
    """
    Direct-ID manipulation checks (spec section 43/44): a user must never gain access
    to another branch's/role's data simply by changing an id in the URL.
    """

    def setUp(self):
        self.client = Client()
        self.branch_a = Branch.objects.create(name="Sec Branch A")
        self.branch_b = Branch.objects.create(name="Sec Branch B")

        self.admin = User.objects.create_user(
            username="sec_admin", password="pwd12345678", role=UserRole.ADMIN, is_staff=True, is_superuser=True
        )

        self.telecaller_a = User.objects.create_user(
            username="sec_tc_a", password="pwd12345678", role=UserRole.TELECALLER, branch=self.branch_a
        )
        self.telecaller_b = User.objects.create_user(
            username="sec_tc_b", password="pwd12345678", role=UserRole.TELECALLER, branch=self.branch_b
        )

        self.sales_head_a = User.objects.create_user(
            username="sec_sh_a", password="pwd12345678", role=UserRole.SALES_HEAD
        )
        SalesHeadBranchAccess.objects.create(sales_head=self.sales_head_a, branch=self.branch_a)

        self.lead_a = Lead.objects.create(
            name="Sec Lead A", phone="9000000101", branch=self.branch_a, assigned_telecaller=self.telecaller_a
        )
        self.lead_b = Lead.objects.create(
            name="Sec Lead B", phone="9000000102", branch=self.branch_b, assigned_telecaller=self.telecaller_b
        )

    def test_telecaller_cannot_view_lead_from_other_branch(self):
        self.client.login(username="sec_tc_a", password="pwd12345678")
        resp = self.client.get(reverse('telecaller_lead_detail', args=[self.lead_b.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_telecaller_cannot_edit_lead_from_other_branch_via_post(self):
        self.client.login(username="sec_tc_a", password="pwd12345678")
        resp = self.client.post(reverse('telecaller_lead_edit', args=[self.lead_b.pk]), {
            'notes': 'attempted tamper', 'status': 'Contacted',
        })
        self.assertEqual(resp.status_code, 403)
        self.lead_b.refresh_from_db()
        self.assertNotEqual(self.lead_b.notes, 'attempted tamper')

    def test_telecaller_can_view_own_branch_lead(self):
        self.client.login(username="sec_tc_a", password="pwd12345678")
        resp = self.client.get(reverse('telecaller_lead_detail', args=[self.lead_a.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_sales_head_cannot_view_telecaller_from_inaccessible_branch(self):
        self.client.login(username="sec_sh_a", password="pwd12345678")
        resp = self.client.get(reverse('manager_telecaller_detail', args=[self.telecaller_b.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_sales_head_can_view_telecaller_from_accessible_branch(self):
        self.client.login(username="sec_sh_a", password="pwd12345678")
        resp = self.client.get(reverse('manager_telecaller_detail', args=[self.telecaller_a.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_admin_is_not_branch_restricted(self):
        """Sanity check: branch-scoping fixes elsewhere must not accidentally lock admin out."""
        self.client.login(username="sec_admin", password="pwd12345678")
        for lead in (self.lead_a, self.lead_b):
            resp = self.client.get(reverse('admin_lead_detail', args=[lead.pk]))
            self.assertEqual(resp.status_code, 200)
        for tc in (self.telecaller_a, self.telecaller_b):
            resp = self.client.get(reverse('admin_telecaller_detail', args=[tc.pk]))
            self.assertEqual(resp.status_code, 200)


class DirectApiAccessTests(TestCase):
    """Admin-only JSON endpoints must reject non-admin roles, not leak data."""

    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.create(name="Sec API Branch")
        self.admin = User.objects.create_user(
            username="api_admin", password="pwd12345678", role=UserRole.ADMIN, is_staff=True, is_superuser=True
        )
        self.sales_head = User.objects.create_user(username="api_sh", password="pwd12345678", role=UserRole.SALES_HEAD)
        self.telecaller = User.objects.create_user(
            username="api_tc", password="pwd12345678", role=UserRole.TELECALLER, branch=self.branch
        )

    def test_non_admin_cannot_access_offline_leads_data_api(self):
        # admin_required (role_required) redirects a role mismatch away (302)
        # rather than returning a raw 403 - confirm the redirect happens and no
        # JSON data leaks through, not a specific status code that doesn't match
        # how this decorator actually behaves.
        for username in ("api_sh", "api_tc"):
            self.client.login(username=username, password="pwd12345678")
            resp = self.client.get(reverse('admin_offline_leads_data_api'))
            self.assertEqual(resp.status_code, 302, f"{username} should be redirected away from the offline leads data API")
            self.client.logout()

    def test_non_admin_cannot_access_offline_leads_status_api(self):
        for username in ("api_sh", "api_tc"):
            self.client.login(username=username, password="pwd12345678")
            resp = self.client.get(reverse('admin_offline_leads_status_api'))
            self.assertEqual(resp.status_code, 302, f"{username} should be redirected away from the offline leads status API")
            self.client.logout()

    def test_admin_can_access_both_apis(self):
        self.client.login(username="api_admin", password="pwd12345678")
        self.assertEqual(self.client.get(reverse('admin_offline_leads_data_api')).status_code, 200)
        self.assertEqual(self.client.get(reverse('admin_offline_leads_status_api')).status_code, 200)
