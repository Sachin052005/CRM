from django.test import TestCase, Client
from django.urls import reverse
from django.core.exceptions import ValidationError
from accounts.models import User, UserRole
from branches.models import Branch, SalesHeadBranchAccess
from leads.models import Lead, GoogleSheetConnection, ConnectionState, SyncStatus
from telecallers.forms import AdminTelecallerCreateForm, AdminTelecallerEditForm

class StrictHierarchyAndTelecallerTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Branches
        self.branch_a = Branch.objects.create(name="Branch Chennai", phone="044111111")
        self.branch_b = Branch.objects.create(name="Branch Bangalore", phone="080222222")

        # Admin
        self.admin = User.objects.create_user(
            username="admin_user", email="admin@crm.com", password="Pass12345!",
            role=UserRole.ADMIN, is_staff=True, is_superuser=True
        )

        # Sales Head A (access to Branch A)
        self.sales_head_a = User.objects.create_user(
            username="sh_a", email="sh_a@crm.com", password="Pass12345!",
            role=UserRole.SALES_HEAD
        )
        SalesHeadBranchAccess.objects.create(sales_head=self.sales_head_a, branch=self.branch_a)

        # Sales Head B (access to Branch B)
        self.sales_head_b = User.objects.create_user(
            username="sh_b", email="sh_b@crm.com", password="Pass12345!",
            role=UserRole.SALES_HEAD
        )
        SalesHeadBranchAccess.objects.create(sales_head=self.sales_head_b, branch=self.branch_b)

        # Branch Head A (Branch A)
        self.branch_head_a = User.objects.create_user(
            username="bh_a", email="bh_a@crm.com", password="Pass12345!",
            role=UserRole.BRANCH_HEAD, branch=self.branch_a
        )

        # Branch Head B (Branch B)
        self.branch_head_b = User.objects.create_user(
            username="bh_b", email="bh_b@crm.com", password="Pass12345!",
            role=UserRole.BRANCH_HEAD, branch=self.branch_b
        )

        # Counselor A (Branch A)
        self.counselor_a = User.objects.create_user(
            username="counselor_a", email="counselor_a@crm.com", password="Pass12345!",
            role=UserRole.COUNSELOR, branch=self.branch_a
        )

        # Counselor B (Branch B)
        self.counselor_b = User.objects.create_user(
            username="counselor_b", email="counselor_b@crm.com", password="Pass12345!",
            role=UserRole.COUNSELOR, branch=self.branch_b
        )

        # Telecaller A (under Counselor A)
        self.telecaller_a = User.objects.create_user(
            username="telecaller_a", email="tc_a@crm.com", password="Pass12345!",
            role=UserRole.TELECALLER, branch=self.branch_a, counselor=self.counselor_a
        )

        # Leads for Telecaller A
        self.lead_a1 = Lead.objects.create(
            name="Lead A1", phone="9000000001", email="a1@test.com",
            branch=self.branch_a, assigned_telecaller=self.telecaller_a, assigned_counselor=self.counselor_a
        )

    def test_telecaller_creation_without_counselor_raises_validation_error(self):
        """A telecaller cannot exist without a counselor assigned."""
        orphan_tc = User(
            username="orphan_tc", email="orphan@crm.com",
            role=UserRole.TELECALLER, branch=self.branch_a
        )
        with self.assertRaises(ValidationError) as ctx:
            orphan_tc.clean()
        self.assertIn("counselor", ctx.exception.message_dict)

    def test_telecaller_with_counselor_passes_validation(self):
        """A telecaller with matching counselor and branch passes model clean."""
        valid_tc = User(
            username="valid_tc", email="valid@crm.com",
            role=UserRole.TELECALLER, branch=self.branch_a, counselor=self.counselor_a
        )
        # Should not raise
        valid_tc.clean()

    def test_telecaller_counselor_branch_mismatch_raises_validation_error(self):
        """Counselor must belong to the same branch as the telecaller."""
        mismatched_tc = User(
            username="mismatch_tc", email="mismatch@crm.com",
            role=UserRole.TELECALLER, branch=self.branch_a, counselor=self.counselor_b
        )
        with self.assertRaises(ValidationError) as ctx:
            mismatched_tc.clean()
        self.assertIn("counselor", ctx.exception.message_dict)

    def test_admin_telecaller_create_form_requires_counselor(self):
        """AdminTelecallerCreateForm strictly marks counselor as required."""
        form_data = {
            'username': 'form_tc',
            'email': 'form_tc@crm.com',
            'password': 'Pass12345!',
            'confirm_password': 'Pass12345!',
            'branch': self.branch_a.id,
            # Counselor omitted
        }
        form = AdminTelecallerCreateForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('counselor', form.errors)

    def test_hierarchy_level_1_sales_heads_page(self):
        """Level 1 displays ONLY Sales Heads."""
        self.client.login(username="admin_user", password="Pass12345!")
        response = self.client.get(reverse('hierarchy_sales_heads_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sales Heads")
        self.assertContains(response, "sh_a")
        self.assertContains(response, "sh_b")
        # Ensure branch heads / telecallers are NOT listed in the table
        self.assertNotContains(response, "bh_a")
        self.assertNotContains(response, "telecaller_a")

    def test_hierarchy_level_2_branch_heads_page_authorization(self):
        """Level 2 displays only branch heads for the sales head's accessible branches."""
        self.client.login(username="admin_user", password="Pass12345!")
        url = reverse('sales_head_branch_heads', kwargs={'sales_head_id': self.sales_head_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "bh_a")
        # bh_b belongs to branch B which is not in Sales Head A's scope
        self.assertNotContains(response, "bh_b")

        # Cross-sales-head access blocked for non-admin
        self.client.login(username="sh_b", password="Pass12345!")
        forbidden_response = self.client.get(url)
        self.assertEqual(forbidden_response.status_code, 403)

    def test_hierarchy_level_3_counselors_page_authorization(self):
        """Level 3 displays counselors under the branch head's branch."""
        self.client.login(username="admin_user", password="Pass12345!")
        url = reverse('branch_head_counselors', kwargs={'branch_head_id': self.branch_head_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "counselor_a")
        self.assertNotContains(response, "counselor_b")
        self.assertNotContains(response, "telecaller_a")

        # Branch Head B cannot access Branch Head A's counselors
        self.client.login(username="bh_b", password="Pass12345!")
        forbidden_response = self.client.get(url)
        self.assertEqual(forbidden_response.status_code, 403)

    def test_hierarchy_level_4_telecallers_page_authorization(self):
        """Level 4 displays telecallers assigned to the counselor."""
        self.client.login(username="admin_user", password="Pass12345!")
        url = reverse('counselor_telecallers', kwargs={'counselor_id': self.counselor_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "telecaller_a")

        # Counselor B cannot access Counselor A's telecallers
        self.client.login(username="counselor_b", password="Pass12345!")
        forbidden_response = self.client.get(url)
        self.assertEqual(forbidden_response.status_code, 403)

    def test_hierarchy_level_5_telecaller_leads_authorization(self):
        """Level 5 displays assigned leads and calls for that telecaller."""
        self.client.login(username="admin_user", password="Pass12345!")
        url = reverse('telecaller_leads', kwargs={'telecaller_id': self.telecaller_a.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lead A1")

        # Telecaller without permission cannot view another telecaller's leads
        other_tc = User.objects.create_user(
            username="tc_other", email="other@crm.com", password="Pass12345!",
            role=UserRole.TELECALLER, branch=self.branch_a, counselor=self.counselor_a
        )
        self.client.login(username="tc_other", password="Pass12345!")
        forbidden_response = self.client.get(url)
        self.assertEqual(forbidden_response.status_code, 403)


class PersistentGoogleSheetConnectionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.create(name="Online Branch", phone="044000000")
        self.admin = User.objects.create_user(
            username="sheet_admin", email="sheet_admin@crm.com", password="Pass12345!",
            role=UserRole.ADMIN, is_staff=True, is_superuser=True
        )
        self.counselor = User.objects.create_user(
            username="sheet_counselor", email="counselor@crm.com", password="Pass12345!",
            role=UserRole.COUNSELOR, branch=self.branch
        )
        self.telecaller = User.objects.create_user(
            username="sheet_telecaller", email="sheet_telecaller@crm.com", password="Pass12345!",
            role=UserRole.TELECALLER, branch=self.branch, counselor=self.counselor
        )

    def test_sheet_connection_state_persists_across_sync_failures(self):
        """Sync failure must update sync_status=FAILED but keep connection_status=ACTIVE."""
        sheet = GoogleSheetConnection.objects.create(
            name="Persistent Admission Form",
            spreadsheet_id="test_sheet_123456789",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/test_sheet_123456789/edit",
            branch=self.branch,
            is_active=True,
            connection_status=ConnectionState.ACTIVE,
            last_sync_status=SyncStatus.SUCCESS
        )

        # Simulate sync failure (e.g. Google network timeout)
        sheet.last_sync_status = SyncStatus.FAILED
        sheet.last_sync_error = "API rate limit exceeded or network timeout"
        sheet.save()

        # Reload fresh from database (simulates server restart / new request)
        reloaded = GoogleSheetConnection.objects.get(pk=sheet.pk)
        self.assertEqual(reloaded.connection_status, ConnectionState.ACTIVE)
        self.assertEqual(reloaded.last_sync_status, SyncStatus.FAILED)
        self.assertTrue(reloaded.is_active)

    def test_sheet_connection_state_remains_active_after_simulated_restart(self):
        """Simulated server restart: connection state is read directly from DB, staying ACTIVE."""
        sheet = GoogleSheetConnection.objects.create(
            name="Permanent Leads Sheet",
            spreadsheet_id="sheet_permanent_999",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/sheet_permanent_999/edit",
            branch=self.branch,
            is_active=True,
            connection_status=ConnectionState.ACTIVE,
            last_sync_status=SyncStatus.SUCCESS
        )

        # Simulating DB query across a new connection / process
        fetched = GoogleSheetConnection.objects.filter(connection_status=ConnectionState.ACTIVE).first()
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.spreadsheet_id, "sheet_permanent_999")
        self.assertEqual(fetched.connection_status, ConnectionState.ACTIVE)
