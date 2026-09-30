from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch
from leads.models import Lead

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


class ErrorPageTests(TestCase):
    """Confirms Django renders our custom 403 page, not its default, for a real
    PermissionDenied raised by object-level authorization checks."""

    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.create(name="ErrorPageTestBranch")
        self.telecaller = User.objects.create_user(
            username="errpage_tc", password="pwd12345678", role=UserRole.TELECALLER, branch=self.branch
        )
        other_telecaller = User.objects.create_user(
            username="errpage_tc_other", password="pwd12345678", role=UserRole.TELECALLER, branch=self.branch
        )
        self.other_lead = Lead.objects.create(
            name="Not Mine", phone="9990000000", branch=self.branch, assigned_telecaller=other_telecaller
        )

    def test_permission_denied_renders_custom_403_page(self):
        self.client.login(username="errpage_tc", password="pwd12345678")
        resp = self.client.get(reverse('telecaller_lead_detail', args=[self.other_lead.pk]))
        self.assertEqual(resp.status_code, 403)
        content = resp.content.decode()
        self.assertIn("Access Denied", content)
        self.assertNotIn("403 Forbidden", content)


class CleanErrorMessageTests(TestCase):
    """A failed lead import must show a clean message, never the raw exception text."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username="cleanerr_admin", password="pwd12345678", email="cleanerr_admin@test.com"
        )
        self.client.login(username="cleanerr_admin", password="pwd12345678")

    def test_corrupt_xlsx_upload_shows_clean_message_not_raw_exception(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        corrupt_file = SimpleUploadedFile(
            "leads.xlsx", b"this is not a real xlsx file", content_type="application/vnd.openxmlformats"
        )
        resp = self.client.post(reverse('admin_leads_import'), {'file': corrupt_file}, follow=True)
        content = resp.content.decode()
        self.assertIn("Unable to process the file", content)
        self.assertNotIn("BadZipFile", content)
        self.assertNotIn("Traceback", content)
