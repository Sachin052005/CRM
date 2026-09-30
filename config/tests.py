from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole

class EndToEndIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.admin = User.objects.create_superuser(username="priya_test", password="123", email="edppriya@test.com")
        self.manager = User.objects.create_user(username="mgr_test", password="123", role=UserRole.SALES_HEAD)
        self.telecaller = User.objects.create_user(
            username="tc_test", password="123", role=UserRole.TELECALLER
        )

    def test_public_pages(self):
        urls = ['login', 'admin_login', 'manager_login', 'telecaller_login', 'manager_register', 'telecaller_register']
        for u in urls:
            res = self.client.get(reverse(u))
            self.assertEqual(res.status_code, 200, f"Failed on URL: {u}")

    def test_admin_pages(self):
        self.client.login(username='priya_test', password='123')
        urls = [
            'admin_dashboard',
            'admin_managers_list',
            'admin_manager_create',
            'admin_branch_heads_list',
            'admin_branch_head_create',
            'admin_telecallers_list',
            'admin_telecaller_create',
            'admin_leads_list',
            'admin_lead_create',
            'admin_leads_import',
            'admin_followups_list',
            'admin_calls_list',
            'admin_channels_list',
            'admin_products_list',
            'admin_branches_list',
            'admin_reports',
            'admin_activities_list'
        ]
        for u in urls:
            res = self.client.get(reverse(u))
            self.assertEqual(res.status_code, 200, f"Failed on admin URL: {u}")

    def test_manager_pages(self):
        self.client.login(username='mgr_test', password='123')
        urls = [
            'manager_dashboard',
            'manager_telecallers_list',
            'sales_head_branch_heads_list',
            'manager_leads_list',
            'manager_followups_list',
            'manager_calls_list',
            'manager_reports',
            'manager_activities_list'
        ]
        for u in urls:
            res = self.client.get(reverse(u))
            self.assertEqual(res.status_code, 200, f"Failed on manager URL: {u}")

    def test_telecaller_pages(self):
        self.client.login(username='tc_test', password='123')
        urls = [
            'telecaller_dashboard',
            'telecaller_leads_list',
            'telecaller_followups_list',
            'telecaller_calls_list',
            'telecaller_activities_list'
        ]
        for u in urls:
            res = self.client.get(reverse(u))
            self.assertEqual(res.status_code, 200, f"Failed on telecaller URL: {u}")
