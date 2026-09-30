from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch
from branches.utils import get_admin_selected_branch, set_admin_selected_branch

class BranchAndFilterTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="adminuser",
            email="admin@test.com",
            password="adminpassword123",
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True
        )
        self.branch1 = Branch.objects.get_or_create(name="T. Nagar", defaults={'status': 'Active'})[0]
        self.branch2 = Branch.objects.get_or_create(name="Velachery", defaults={'status': 'Active'})[0]

    def test_standard_six_branches_exist(self):
        expected_branches = ['T. Nagar', 'Velachery', 'Sholinganallur', 'Anna Nagar', 'Tambaram', 'Porur']
        for name in expected_branches:
            self.assertTrue(Branch.objects.filter(name=name).exists(), f"Branch {name} should exist in database.")

    def test_set_active_branch_session(self):
        self.client.login(username="adminuser", password="adminpassword123")
        response = self.client.post(reverse('set_active_branch'), {
            'branch_id': self.branch1.id,
            'next': reverse('admin_dashboard')
        })
        self.assertRedirects(response, reverse('admin_dashboard'))
        self.assertEqual(self.client.session['selected_branch_id'], self.branch1.id)

        # Set to all
        response = self.client.post(reverse('set_active_branch'), {
            'branch_id': 'all',
            'next': reverse('admin_dashboard')
        })
        self.assertEqual(self.client.session['selected_branch_id'], 'all')
