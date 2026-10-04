from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch

from accounts.models import User, UserRole
from branches.models import Branch
from channels.models import Channel
from products.models import Product
from leads.models import (
    Lead, LeadStatus, GoogleSheetConnection, DuplicateLeadRecord,
    LeadSetupConfig, TelecallerLeadSetup, AssignmentMethod
)
from leads.assignment import assign_new_lead
from leads.duplicates import process_incoming_lead_with_10day_rule
from leads.google_sheets import sync_google_sheet


class MasterFiveProblemsTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch_a = Branch.objects.create(name="Chennai", status="Active")
        self.branch_b = Branch.objects.create(name="Bangalore", status="Active")

        self.admin = User.objects.create_user(
            username="admin_tester",
            email="admin@techpanda.test",
            password="TestPassword@123",
            role=UserRole.ADMIN,
            is_active=True
        )

        self.telecaller_a1 = User.objects.create_user(
            username="tc_anand_1",
            first_name="Anand",
            last_name="Kumar",
            email="anand@techpanda.test",
            password="TestPassword@123",
            role=UserRole.TELECALLER,
            branch=self.branch_a,
            is_active=True
        )
        self.telecaller_a2 = User.objects.create_user(
            username="tc_chennai_2",
            first_name="Sita",
            last_name="Devi",
            email="sita@techpanda.test",
            password="TestPassword@123",
            role=UserRole.TELECALLER,
            branch=self.branch_a,
            is_active=True
        )

        self.channel = Channel.objects.create(name="Google Sheets", status="Active")

    # =========================================================================
    # PROBLEM 1: Persistent Google Sheet Connections & Auto Refresh
    # =========================================================================
    def test_problem_1_persistent_google_sheet_connection(self):
        """
        Connection status must remain ACTIVE even if sync fails.
        FAILED sync does not disconnect the sheet.
        """
        sheet = GoogleSheetConnection.objects.create(
            name="Test Sheet",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/1BxiMVsTest123/edit",
            spreadsheet_id="1BxiMVsTest123",
            worksheet_name="Sheet1",
            branch=self.branch_a,
            channel=self.channel,
            is_active=True,
            connection_status="ACTIVE",
            last_sync_status="Connected"
        )

        # Simulate sync failure (empty headers / network timeout)
        result = sync_google_sheet(sheet, headers=[], rows=[])
        self.assertEqual(result['status'], 'Failed')

        sheet.refresh_from_db()
        self.assertEqual(sheet.connection_status, "ACTIVE")
        self.assertTrue(sheet.is_active)
        self.assertEqual(sheet.last_sync_status, "Failed")

        # Simulate next retry succeeding
        success_headers = ["Name", "Phone", "Email"]
        success_rows = [{"_row_index": 2, "Name": "Alice", "Phone": "9876543210", "Email": "alice@test.com"}]
        result2 = sync_google_sheet(sheet, headers=success_headers, rows=success_rows)
        self.assertEqual(result2['status'], 'Success')

        sheet.refresh_from_db()
        self.assertEqual(sheet.connection_status, "ACTIVE")
        self.assertTrue(sheet.is_active)
        self.assertEqual(sheet.last_sync_status, "Success")

    # =========================================================================
    # PROBLEM 2: Lead Setup — Strict Percentage Assignment (100% Validation)
    # =========================================================================
    def test_problem_2_strict_percentage_allocation_and_100pct_validation(self):
        """
        Lead Setup assignment must strictly enforce 100% percentage validation.
        Allocation != 100% must be rejected.
        Allocation == 100% must be saved and applied cleanly.
        """
        self.client.login(username="admin_tester", password="TestPassword@123")
        TelecallerLeadSetup.objects.filter(branch=self.branch_a).delete()

        # 1. Invalid: sum is 80%
        res_invalid = self.client.post(reverse('admin_lead_setup'), {
            'action': 'save_branch_allocation',
            'branch_id': self.branch_a.id,
            'active_telecallers': [self.telecaller_a1.id, self.telecaller_a2.id],
            f'percentage_{self.telecaller_a1.id}': 50,
            f'percentage_{self.telecaller_a2.id}': 30,
        })
        self.assertRedirects(res_invalid, reverse('admin_lead_setup'))
        # Should not have created active setups with 80%
        self.assertEqual(TelecallerLeadSetup.objects.filter(branch=self.branch_a, is_active=True).count(), 0)

        # 2. Valid: 60% + 40% = 100%
        res_valid = self.client.post(reverse('admin_lead_setup'), {
            'action': 'save_branch_allocation',
            'branch_id': self.branch_a.id,
            'active_telecallers': [self.telecaller_a1.id, self.telecaller_a2.id],
            f'percentage_{self.telecaller_a1.id}': 60,
            f'percentage_{self.telecaller_a2.id}': 40,
        })
        self.assertRedirects(res_valid, reverse('admin_lead_setup'))

        setup1 = TelecallerLeadSetup.objects.get(telecaller=self.telecaller_a1, branch=self.branch_a)
        setup2 = TelecallerLeadSetup.objects.get(telecaller=self.telecaller_a2, branch=self.branch_a)
        self.assertEqual(setup1.assignment_percentage, 60)
        self.assertEqual(setup2.assignment_percentage, 40)
        self.assertEqual(setup1.lead_count, 0)
        self.assertEqual(setup2.lead_count, 0)

        # 3. Test assignment algorithm with 60/40 weighted split
        lead1 = Lead.objects.create(name="Student 1", phone="9000000001", branch=self.branch_a)
        lead2 = Lead.objects.create(name="Student 2", phone="9000000002", branch=self.branch_a)

        assigned1 = assign_new_lead(lead1, branch=self.branch_a)
        assigned2 = assign_new_lead(lead2, branch=self.branch_a)
        self.assertTrue(assigned1)
        self.assertTrue(assigned2)
        lead1.refresh_from_db()
        lead2.refresh_from_db()
        self.assertIsNotNone(lead1.assigned_telecaller)
        self.assertIsNotNone(lead2.assigned_telecaller)

    # =========================================================================
    # PROBLEM 3: Single Plus Icon on Add Buttons
    # =========================================================================
    def test_problem_3_single_plus_buttons(self):
        """
        Verify that Add Telecaller and Add Drive buttons do not duplicate the plus symbol.
        """
        self.client.login(username="admin_tester", password="TestPassword@123")

        # 1. Lead Setup page
        res_setup = self.client.get(reverse('admin_lead_setup'))
        self.assertNotContains(res_setup, "+ + Add Telecaller")
        self.assertNotContains(res_setup, "++ Add Telecaller")
        self.assertContains(res_setup, "Add Telecaller Assignment")

        # 2. Drive Dashboard page
        res_drive = self.client.get(reverse('drive_dashboard'))
        self.assertNotContains(res_drive, "+ + Add Drive")
        self.assertNotContains(res_drive, "++ Add Drive")

    # =========================================================================
    # PROBLEM 4: Duplicate Leads — 10-Day Cross-Branch Rule & Unified Table
    # =========================================================================
    def test_problem_4_rule_a_cross_branch_within_10_days(self):
        """
        Rule A: Within 10 days:
        - Lead submitted to Branch B within 10 days of Branch A remains associated with Branch A.
        - No second active lead created in Branch B.
        - DuplicateLeadRecord created with duplicate status.
        """
        orig_lead = Lead.objects.create(
            name="Rahul Sharma",
            phone="9876501234",
            email="rahul@test.com",
            branch=self.branch_a,
            status=LeadStatus.NEW
        )

        incoming_data = {
            'name': 'Rahul Sharma',
            'phone': '9876501234',
            'email': 'rahul@test.com',
            'branch': 'Bangalore'
        }

        lead, is_dup, dup_rec = process_incoming_lead_with_10day_rule(
            incoming_data, branch=self.branch_b, source="Google Form", user=self.admin
        )

        self.assertTrue(is_dup)
        self.assertEqual(lead.id, orig_lead.id)
        self.assertEqual(lead.branch, self.branch_a)
        # Verify no second lead created
        self.assertEqual(Lead.objects.filter(phone="9876501234").count(), 1)
        self.assertIsNotNone(dup_rec)
        self.assertEqual(dup_rec.status, 'DUPLICATE')

    def test_problem_4_rule_b_cross_branch_after_10_days(self):
        """
        Rule B: After >10 days:
        - Lead submitted to Branch B after >10 days creates a new active lead in Branch B.
        - Old lead in Branch A is marked Historical/Inactive (never physically deleted).
        - Previous history recorded in notes.
        """
        # Create original lead 15 days ago
        orig_lead = Lead.objects.create(
            name="Pooja Patel",
            phone="9876509999",
            email="pooja@test.com",
            branch=self.branch_a,
            status=LeadStatus.NEW
        )
        Lead.objects.filter(id=orig_lead.id).update(
            created_at=timezone.now() - timedelta(days=15)
        )
        orig_lead.refresh_from_db()

        incoming_data = {
            'name': 'Pooja Patel',
            'phone': '9876509999',
            'email': 'pooja@test.com',
            'branch': 'Bangalore'
        }

        new_lead, is_dup, dup_rec = process_incoming_lead_with_10day_rule(
            incoming_data, branch=self.branch_b, source="Google Form", user=self.admin
        )

        self.assertFalse(is_dup)
        self.assertNotEqual(new_lead.id, orig_lead.id)
        self.assertEqual(new_lead.branch, self.branch_b)
        self.assertEqual(new_lead.status, LeadStatus.NEW)
        self.assertIn("Previous history", new_lead.notes)

        # Original lead in Branch A must still exist and be marked Historical
        orig_lead.refresh_from_db()
        self.assertEqual(orig_lead.status, LeadStatus.HISTORICAL)
        self.assertIn("Historical/Inactive", orig_lead.notes)
        self.assertEqual(Lead.objects.filter(phone="9876509999").count(), 2)

    def test_problem_4_unified_duplicate_leads_table(self):
        """
        Verify the Duplicate Leads review page renders ONE unified table with the required columns.
        """
        self.client.login(username="admin_tester", password="TestPassword@123")

        orig = Lead.objects.create(name="Divya", phone="9876543219", branch=self.branch_a)
        DuplicateLeadRecord.objects.create(
            original_lead=orig,
            name="Divya",
            phone="9876543219",
            email="divya@test.com",
            branch=self.branch_b,
            branch_name="Bangalore",
            status="DUPLICATE",
            notes="Same lead details detected within 10 days."
        )

        res = self.client.get(reverse('admin_duplicate_leads'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "DUPLICATE LEADS")
        self.assertContains(res, "Student")
        self.assertContains(res, "Phone")
        self.assertContains(res, "Original Branch")
        self.assertContains(res, "Duplicate Branch")
        self.assertContains(res, "Days Difference")
        self.assertContains(res, "Keep Single Lead")

    # =========================================================================
    # PROBLEM 5: Removed Pages & Clean Navigation
    # =========================================================================
    def test_problem_5_removed_pages_and_navigation(self):
        """
        Products, System, Integrations, and Configuration removed from navigation.
        Accessing routes redirects cleanly without 404 or 500 errors.
        Underlying database table products_product is preserved.
        """
        self.client.login(username="admin_tester", password="TestPassword@123")

        # 1. Navigation does not contain removed links
        res_dash = self.client.get(reverse('admin_dashboard'))
        self.assertNotContains(res_dash, '<span class="nav-text">Products</span>')
        self.assertNotContains(res_dash, '<div class="nav-section-title">System</div>')
        self.assertNotContains(res_dash, '<span class="nav-text">Integrations</span>')
        self.assertNotContains(res_dash, '<span class="nav-text">Configuration</span>')

        # 2. Direct route access cleanly redirects to admin_dashboard
        res_prod = self.client.get(reverse('admin_products_list'))
        self.assertRedirects(res_prod, reverse('admin_dashboard'))

        res_config = self.client.get(reverse('admin_configuration'))
        self.assertRedirects(res_config, reverse('admin_dashboard'))

        # 3. Database table products_product is preserved and queryable
        product = Product.objects.create(name="Python Full Stack", status="Active")
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())
