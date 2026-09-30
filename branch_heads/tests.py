from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch, SalesHeadBranchAccess


class BranchHeadManagementTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="bh_testadmin", password="adminpassword123",
            role=UserRole.ADMIN, is_staff=True, is_superuser=True
        )
        self.branch1 = Branch.objects.get_or_create(name="BH Branch One")[0]
        self.branch2 = Branch.objects.get_or_create(name="BH Branch Two")[0]

        self.sales_head = User.objects.create_user(
            username="bh_saleshead", password="pwd12345678", role=UserRole.SALES_HEAD
        )
        SalesHeadBranchAccess.objects.create(sales_head=self.sales_head, branch=self.branch1)

        self.other_sales_head = User.objects.create_user(
            username="bh_other_saleshead", password="pwd12345678", role=UserRole.SALES_HEAD
        )
        SalesHeadBranchAccess.objects.create(sales_head=self.other_sales_head, branch=self.branch2)

    def _create_payload(self, branch_id):
        return {
            'first_name': 'Test', 'last_name': 'Head', 'username': 'newbranchhead',
            'email': 'newbranchhead@example.com', 'phone': '9990001111',
            'branch': branch_id, 'is_active': 'on',
            'password': 'StrongPass123!', 'confirm_password': 'StrongPass123!',
        }

    def test_admin_can_create_branch_head_for_any_branch(self):
        self.client.login(username="bh_testadmin", password="adminpassword123")
        resp = self.client.post(reverse('admin_branch_head_create'), self._create_payload(self.branch2.id))
        self.assertRedirects(resp, reverse('admin_branch_heads_list'))
        bh = User.objects.get(username='newbranchhead')
        self.assertEqual(bh.role, UserRole.BRANCH_HEAD)
        self.assertEqual(bh.branch_id, self.branch2.id)

    def test_sales_head_can_create_branch_head_for_accessible_branch(self):
        self.client.login(username="bh_saleshead", password="pwd12345678")
        resp = self.client.post(reverse('sales_head_branch_head_create'), self._create_payload(self.branch1.id))
        self.assertRedirects(resp, reverse('sales_head_branch_heads_list'))
        bh = User.objects.get(username='newbranchhead')
        self.assertEqual(bh.branch_id, self.branch1.id)

    def test_sales_head_cannot_create_branch_head_for_inaccessible_branch(self):
        self.client.login(username="bh_saleshead", password="pwd12345678")
        resp = self.client.post(reverse('sales_head_branch_head_create'), self._create_payload(self.branch2.id))
        self.assertEqual(resp.status_code, 200)  # form re-rendered with errors, not redirected
        self.assertFalse(User.objects.filter(username='newbranchhead').exists())

    def test_sales_head_branch_heads_list_scoped_to_accessible_branches(self):
        bh1 = User.objects.create_user(username='bh_in_scope', password='pwd12345678', role=UserRole.BRANCH_HEAD, branch=self.branch1)
        bh2 = User.objects.create_user(username='bh_out_of_scope', password='pwd12345678', role=UserRole.BRANCH_HEAD, branch=self.branch2)

        self.client.login(username="bh_saleshead", password="pwd12345678")
        resp = self.client.get(reverse('sales_head_branch_heads_list'))
        self.assertContains(resp, 'bh_in_scope')
        self.assertNotContains(resp, 'bh_out_of_scope')

    def test_sales_head_cannot_access_other_sales_heads_branch_head_detail(self):
        bh2 = User.objects.create_user(username='bh_out_of_scope2', password='pwd12345678', role=UserRole.BRANCH_HEAD, branch=self.branch2)

        self.client.login(username="bh_saleshead", password="pwd12345678")
        resp = self.client.get(reverse('sales_head_branch_head_detail', args=[bh2.pk]))
        self.assertEqual(resp.status_code, 404)

        resp_edit = self.client.get(reverse('sales_head_branch_head_edit', args=[bh2.pk]))
        self.assertEqual(resp_edit.status_code, 404)


class BranchHeadOwnPortalTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch1 = Branch.objects.get_or_create(name="BHP Branch One")[0]
        self.branch2 = Branch.objects.get_or_create(name="BHP Branch Two")[0]

        self.branch_head = User.objects.create_user(
            username="bhp_branchhead", password="pwd12345678", role=UserRole.BRANCH_HEAD, branch=self.branch1
        )
        self.other_branch_head = User.objects.create_user(
            username="bhp_other_branchhead", password="pwd12345678", role=UserRole.BRANCH_HEAD, branch=self.branch2
        )

    def _counselor_payload(self):
        return {
            'first_name': 'Test', 'last_name': 'Counselor', 'username': 'newcounselor',
            'email': 'newcounselor@example.com', 'phone': '9990002222', 'is_active': 'on',
            'password': 'StrongPass123!', 'confirm_password': 'StrongPass123!',
        }

    def test_branch_head_can_create_counselor_with_auto_inherited_branch(self):
        self.client.login(username="bhp_branchhead", password="pwd12345678")
        resp = self.client.post(reverse('branch_head_counselor_create'), self._counselor_payload())
        self.assertRedirects(resp, reverse('branch_head_counselors_list'))

        counselor = User.objects.get(username='newcounselor')
        self.assertEqual(counselor.role, UserRole.COUNSELOR)
        self.assertEqual(counselor.branch_id, self.branch1.id)

    def test_branch_head_dashboard_renders_and_scopes_to_own_branch(self):
        User.objects.create_user(username='bhp_counselor', password='pwd12345678', role=UserRole.COUNSELOR, branch=self.branch1)
        User.objects.create_user(username='bhp_other_counselor', password='pwd12345678', role=UserRole.COUNSELOR, branch=self.branch2)

        self.client.login(username="bhp_branchhead", password="pwd12345678")
        resp = self.client.get(reverse('branch_head_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['counselors_count'], 1)

    def test_branch_head_cannot_access_counselor_from_another_branch(self):
        other_counselor = User.objects.create_user(
            username='bhp_foreign_counselor', password='pwd12345678', role=UserRole.COUNSELOR, branch=self.branch2
        )
        self.client.login(username="bhp_branchhead", password="pwd12345678")
        resp = self.client.get(reverse('branch_head_counselor_detail', args=[other_counselor.pk]))
        self.assertEqual(resp.status_code, 404)
