import unittest
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, UserRole
from branches.models import Branch
from leads.models import (
    Lead,
    LeadStatus,
    GoogleSheetConnection,
    DuplicateLeadRecord,
)
from leads.duplicates import (
    mask_phone,
    process_spreadsheet_row_duplicate_rules,
)


class MultiSpreadsheetLiveConnectionTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Admin User
        self.admin = User.objects.create_user(
            username='admin_multi_sheet',
            password='AdminPassword@2026',
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True
        )

        # Branches
        self.branch_tnagar, _ = Branch.objects.get_or_create(name='T. Nagar', defaults={'status': 'Active'})
        self.branch_velachery, _ = Branch.objects.get_or_create(name='Velachery', defaults={'status': 'Active'})
        self.branch_tambaram, _ = Branch.objects.get_or_create(name='Tambaram', defaults={'status': 'Active'})

        # Clean state
        GoogleSheetConnection.objects.all().delete()
        DuplicateLeadRecord.objects.all().delete()
        Lead.objects.all().delete()

    def test_section_1_and_7_empty_state_and_top_right_add_spreadsheet_button(self):
        """
        Section 1 & 7:
        - Clean state: 'No spreadsheet connected.'
        - Top-right corner button: '[ + Add Spreadsheet ]'
        - Add Spreadsheet modal contains Name, URL, '[ Connect Spreadsheet ]', '[ Cancel ]'
        """
        self.client.login(username='admin_multi_sheet', password='AdminPassword@2026')
        resp = self.client.get(reverse('admin_offline_leads_list'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Section 1: Header and button
        self.assertIn("OFFLINE LEADS", content)
        self.assertIn("+ Add Spreadsheet", content)
        self.assertIn("ADD SPREADSHEET", content)
        self.assertIn("Spreadsheet Name", content)
        self.assertIn("Spreadsheet URL", content)
        self.assertIn("Connect Spreadsheet", content)
        self.assertIn("Cancel", content)

        # Section 7: Clean empty state
        self.assertIn("No spreadsheet connected.", content)

    @patch('leads.views.fetch_sheet_data')
    def test_section_2_and_3_direct_connection_and_dynamic_columns_and_phone_unmasked(self, mock_fetch):
        """
        Section 2 & 3:
        - Direct connection without authentication
        - Displays status card: '🟢 Live Connected', 'Spreadsheet:', 'Last Refresh:', 'Auto Refresh: Every 10 seconds'
        - Dynamic table with actual columns
        - Phone number is displayed as actually imported, not masked (master prompt Section 28/52)
        """
        headers = ['Student Name', 'Mobile Number', 'Email Address', 'Specialization']
        rows = [
            {'_row_index': 2, 'Student Name': 'Arun Kumar', 'Mobile Number': '9876543210', 'Email Address': 'arun@example.com', 'Specialization': 'Full Stack'},
            {'_row_index': 3, 'Student Name': 'Priya S', 'Mobile Number': '9123456780', 'Email Address': 'priya@example.com', 'Specialization': 'Data Science'}
        ]
        mock_fetch.return_value = (headers, rows)

        self.client.login(username='admin_multi_sheet', password='AdminPassword@2026')
        sheet_url = "https://docs.google.com/spreadsheets/d/1BxiMVsTNagarSheet/edit"

        res = self.client.post(reverse('admin_google_sheet_connect'), {
            'name': 'Student Enquiries – T. Nagar',
            'spreadsheet_url': sheet_url
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_connected'])
        self.assertEqual(data['headers'], headers)
        self.assertEqual(data['total_rows'], 2)

        # Check view rendering
        resp = self.client.get(reverse('admin_offline_leads_list'))
        content = resp.content.decode('utf-8')

        # Status card
        self.assertIn("🟢 Live Connected", content)
        self.assertIn("Student Enquiries – T. Nagar", content)
        self.assertIn("Auto Refresh:", content)
        self.assertIn("Every 10 seconds", content)

        # Dynamic headers
        for h in headers:
            self.assertIn(f"<th>{h}</th>", content)

        # Actual phone numbers displayed, not masked
        self.assertIn("9876543210", content)
        self.assertIn("9123456780", content)

    @patch('leads.views.fetch_sheet_data')
    def test_section_6_multiple_spreadsheet_connections(self, mock_fetch):
        """
        Section 6:
        The [+ Add Spreadsheet] option must support multiple spreadsheet connections.
        Connecting Spreadsheet B must NOT deactivate Spreadsheet A!
        Both connections remain active and tracked.
        """
        self.client.login(username='admin_multi_sheet', password='AdminPassword@2026')

        # Connect Spreadsheet 1 (T. Nagar)
        mock_fetch.return_value = (
            ['Name', 'Phone', 'Course'],
            [{'_row_index': 2, 'Name': 'Arun', 'Phone': '9876543210', 'Course': 'Python'}]
        )
        res1 = self.client.post(reverse('admin_google_sheet_connect'), {
            'name': 'Student Enquiries – T. Nagar',
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/sheet_tnagar_111/edit'
        })
        self.assertTrue(res1.json()['success'])

        # Connect Spreadsheet 2 (Velachery)
        mock_fetch.return_value = (
            ['Student Name', 'Contact', 'Program'],
            [{'_row_index': 2, 'Student Name': 'Vijay', 'Contact': '9988776655', 'Program': 'Java'}]
        )
        res2 = self.client.post(reverse('admin_google_sheet_connect'), {
            'name': 'Student Enquiries – Velachery',
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/sheet_velachery_222/edit'
        })
        self.assertTrue(res2.json()['success'])

        # Verify BOTH connections exist and are active in database
        active_conns = GoogleSheetConnection.objects.filter(is_active=True)
        self.assertEqual(active_conns.count(), 2)

        # Verify both cards appear in CONNECTED SPREADSHEETS
        resp = self.client.get(reverse('admin_offline_leads_list'))
        content = resp.content.decode('utf-8')

        self.assertIn("Student Enquiries – T. Nagar", content)
        self.assertIn("Student Enquiries – Velachery", content)
        self.assertIn("2 Active Connections", content)

    @patch('leads.views.fetch_sheet_data')
    def test_section_4_and_5_10_second_refresh_and_new_lead_detection(self, mock_fetch):
        """
        Section 4 & 5:
        10-second automatic polling detects new row added to connected spreadsheet.
        """
        self.client.login(username='admin_multi_sheet', password='AdminPassword@2026')

        initial_headers = ['Name', 'Phone']
        initial_rows = [
            {'_row_index': 2, 'Name': 'Kavitha', 'Phone': '9812345678'}
        ]
        mock_fetch.return_value = (initial_headers, initial_rows)

        self.client.post(reverse('admin_google_sheet_connect'), {
            'name': 'Live Sheet Test',
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/sheet_poll_333/edit'
        })

        # Initial check
        api_res1 = self.client.get(reverse('admin_offline_leads_data_api'))
        self.assertEqual(api_res1.json()['total_rows'], 1)

        # New lead added in spreadsheet
        updated_rows = list(initial_rows) + [
            {'_row_index': 3, 'Name': 'Deepak', 'Phone': '9899001122'}
        ]
        mock_fetch.return_value = (initial_headers, updated_rows)

        # Next 10-second check detects new row
        api_res2 = self.client.get(reverse('admin_offline_leads_data_api'))
        data2 = api_res2.json()
        self.assertEqual(data2['total_rows'], 2)
        self.assertIn(['Deepak', '9899001122'], data2['rows'])

    def test_section_8_and_11_duplicate_flow_same_branch(self):
        """
        Section 8 & 11:
        Row found in spreadsheet -> existing lead found with SAME BRANCH:
        -> Treat as DUPLICATE.
        -> Stored in DuplicateLeadRecord.
        -> Does not create another normal lead in Lead.objects.
        """
        # Create existing lead in T. Nagar
        orig_lead = Lead.objects.create(
            name="Suresh Kumar",
            phone="9876543210",
            email="suresh@example.com",
            branch=self.branch_tnagar,
            source="Manual",
            is_offline=False
        )

        row_data = {
            'Name': 'Suresh Kumar',
            'Phone': '9876543210',
            'Email': 'suresh@example.com',
            'Branch': 'T. Nagar'
        }

        lead, is_dup, dup_rec = process_spreadsheet_row_duplicate_rules(
            row_data=row_data,
            headers=['Name', 'Phone', 'Email', 'Branch'],
            user=self.admin
        )

        self.assertTrue(is_dup)
        self.assertIsNotNone(dup_rec)
        self.assertEqual(dup_rec.status, 'DUPLICATE')
        self.assertEqual(dup_rec.original_lead, orig_lead)
        # Total normal leads remain 1
        self.assertEqual(Lead.objects.count(), 1)
        # Duplicate record created
        self.assertEqual(DuplicateLeadRecord.objects.count(), 1)

    def test_section_9_and_11_cross_branch_within_10_days_rule(self):
        """
        Section 9 & 11:
        Same lead details submitted from a DIFFERENT BRANCH WITHIN 10 DAYS:
        -> Treat as DUPLICATE.
        -> Warning: '⚠ Same lead details detected in another branch within 10 days.'
        -> Status: DUPLICATE.
        -> Do not create duplicate normal lead in the main Leads list.
        -> Sent to Duplicate Leads section.
        """
        # Create original lead in T. Nagar 3 days ago (<= 10 days)
        three_days_ago = timezone.now() - timedelta(days=3)
        orig_lead = Lead.objects.create(
            name="Ananya Sharma",
            phone="9876500000",
            email="ananya@example.com",
            branch=self.branch_tnagar,
            source="Student Enquiries – T. Nagar",
            is_offline=True
        )
        Lead.objects.filter(pk=orig_lead.pk).update(created_at=three_days_ago)
        orig_lead.refresh_from_db()

        # New submission for Ananya from Velachery branch within 10 days
        row_data = {
            'Name': 'Ananya Sharma',
            'Phone': '9876500000',
            'Email': 'ananya@example.com',
            'Branch': 'Velachery'
        }

        lead, is_dup, dup_rec = process_spreadsheet_row_duplicate_rules(
            row_data=row_data,
            headers=['Name', 'Phone', 'Email', 'Branch'],
            user=self.admin
        )

        self.assertTrue(is_dup)
        self.assertIsNotNone(dup_rec)
        self.assertEqual(dup_rec.status, 'DUPLICATE')
        self.assertEqual(dup_rec.original_lead, orig_lead)
        self.assertEqual(dup_rec.branch, self.branch_velachery)
        self.assertIn("⚠ Same lead details detected in another branch within 10 days.", dup_rec.notes)
        # No extra normal lead created
        self.assertEqual(Lead.objects.count(), 1)
        # Registered under duplicate records
        self.assertEqual(DuplicateLeadRecord.objects.count(), 1)

    def test_section_10_and_11_cross_branch_after_10_days_new_lead(self):
        """
        Section 10 & 11:
        Same lead details submitted from a DIFFERENT BRANCH AFTER 10 DAYS:
        -> Treat as a NEW LEAD!
        -> Create normal lead record in the CRM.
        -> Appears in normal live leads list.
        """
        # Create original lead in T. Nagar 15 days ago (> 10 days)
        fifteen_days_ago = timezone.now() - timedelta(days=15)
        orig_lead = Lead.objects.create(
            name="Rahul Verma",
            phone="9876511111",
            email="rahul@example.com",
            branch=self.branch_tnagar,
            source="Student Enquiries – T. Nagar",
            is_offline=True
        )
        Lead.objects.filter(pk=orig_lead.pk).update(created_at=fifteen_days_ago)
        orig_lead.refresh_from_db()

        # New submission for Rahul from Velachery after 10 days
        row_data = {
            'Name': 'Rahul Verma',
            'Phone': '9876511111',
            'Email': 'rahul@example.com',
            'Branch': 'Velachery'
        }

        lead, is_dup, dup_rec = process_spreadsheet_row_duplicate_rules(
            row_data=row_data,
            headers=['Name', 'Phone', 'Email', 'Branch'],
            user=self.admin
        )

        # Must be treated as NEW LEAD
        self.assertFalse(is_dup)
        self.assertIsNone(dup_rec)
        self.assertEqual(lead.name, "Rahul Verma")
        self.assertEqual(lead.branch, self.branch_velachery)
        self.assertNotEqual(lead.id, orig_lead.id)
        # Now 2 valid normal leads in CRM
        self.assertEqual(Lead.objects.count(), 2)

    def test_section_12_and_13_duplicate_leads_view_and_cards(self):
        """
        Section 12 & 13:
        - Offline leads page has '[ Duplicate Leads (X) ]' button.
        - /admin/duplicate-leads/ renders cards with:
          * Lead Name
          * Phone masked as 98765xxxxx
          * Email
          * Original Branch & Submission Date
          * Duplicate Branch & Submission Date
          * Warning banner: '⚠ Same lead details detected in another branch within 10 days.'
          * Status: DUPLICATE
          * Button: [ View Original Lead ]
          * Button: [ Keep Single Lead ]
        """
        # Create original lead
        orig_lead = Lead.objects.create(
            name="Divya R",
            phone="9876522222",
            email="divya@example.com",
            branch=self.branch_tnagar,
            source="Student Enquiries – T. Nagar",
            is_offline=True
        )

        # Create duplicate record
        dup_rec = DuplicateLeadRecord.objects.create(
            original_lead=orig_lead,
            name="Divya R",
            phone="9876522222",
            email="divya@example.com",
            branch=self.branch_velachery,
            branch_name="Velachery",
            status="DUPLICATE",
            notes="⚠ Same lead details detected in another branch within 10 days.",
            source="Student Enquiries – Velachery",
            data_payload={'Name': 'Divya R', 'Phone': '9876522222', 'Branch': 'Velachery'}
        )

        self.client.login(username='admin_multi_sheet', password='AdminPassword@2026')

        # 1. Offline leads page has [ Duplicate Leads (1) ] button
        resp_off = self.client.get(reverse('admin_offline_leads_list'))
        content_off = resp_off.content.decode('utf-8')
        self.assertIn("Duplicate Leads", content_off)
        self.assertIn("1", content_off)

        # 2. View /admin/duplicate-leads/
        resp_dup = self.client.get(reverse('admin_duplicate_leads'))
        self.assertEqual(resp_dup.status_code, 200)
        content_dup = resp_dup.content.decode('utf-8')

        # Check required fields
        self.assertIn("Divya R", content_dup)
        self.assertIn("98765xxxxx", content_dup)
        self.assertNotIn("9876522222", content_dup)
        self.assertIn("divya@example.com", content_dup)
        self.assertIn("T. Nagar", content_dup)
        self.assertIn("Velachery", content_dup)
        self.assertIn("DUPLICATE", content_dup)
        self.assertIn("⚠ Same lead details detected in another branch within 10 days.", content_dup)
        self.assertIn("[ View Original Lead ]", content_dup)
        self.assertIn(f"/admin/leads/{orig_lead.id}/", content_dup)
        self.assertIn("[ Keep Single Lead ]", content_dup)
