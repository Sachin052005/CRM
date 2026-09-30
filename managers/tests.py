from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch, SalesHeadBranchAccess

class ManagerManagementTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="testadmin",
            password="adminpassword123",
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True
        )
        self.branch1 = Branch.objects.get_or_create(name="T. Nagar")[0]
        self.branch2 = Branch.objects.get_or_create(name="Velachery")[0]

        self.manager1 = User.objects.create_user(
            username="mgr_tnagar",
            password="oldpassword123",
            role=UserRole.SALES_HEAD,
            branch=self.branch1
        )
        SalesHeadBranchAccess.objects.create(sales_head=self.manager1, branch=self.branch1)
        self.manager2 = User.objects.create_user(
            username="mgr_velachery",
            password="oldpassword123",
            role=UserRole.SALES_HEAD,
            branch=self.branch2
        )
        SalesHeadBranchAccess.objects.create(sales_head=self.manager2, branch=self.branch2)

    def test_admin_change_manager_password(self):
        self.client.login(username="testadmin", password="adminpassword123")
        url = reverse('admin_manager_change_password', args=[self.manager1.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_response = self.client.post(url, {
            'new_password1': 'BrandNewPass123!',
            'new_password2': 'BrandNewPass123!'
        })
        self.assertRedirects(post_response, reverse('admin_manager_detail', args=[self.manager1.pk]))

        # Verify new password authenticates
        self.manager1.refresh_from_db()
        self.assertTrue(self.manager1.check_password('BrandNewPass123!'))

    def test_admin_managers_list_branch_filter(self):
        self.client.login(username="testadmin", password="adminpassword123")
        # Session branch filter
        session = self.client.session
        session['selected_branch_id'] = self.branch1.id
        session.save()

        response = self.client.get(reverse('admin_managers_list'))
        self.assertContains(response, "mgr_tnagar")
        self.assertNotContains(response, "mgr_velachery")
