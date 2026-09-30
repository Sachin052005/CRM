import unittest
from io import StringIO
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.core.management import call_command
from accounts.models import User, UserRole
from branches.models import Branch
from channels.models import Channel
from products.models import Product
from leads.models import (
    Lead,
    LeadStatus,
    GoogleSheetConnection,
    GoogleSheetRowMapping,
    GoogleSheetSyncHistory
)
from leads.google_sheets_service import (
    extract_spreadsheet_id,
    normalize_header,
    check_google_auth_status,
)
from leads.google_sheets import (
    detect_column_mapping,
    compute_mapped_hash,
    assign_lead_to_team,
    sync_google_sheet,
)

class GoogleSheetsIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.create(name="Bangalore Central")
        self.channel = Channel.objects.create(name="Google Sheets")
        self.product = Product.objects.create(name="Data Science Master", price=45000)

        self.admin_user = User.objects.create_superuser(
            username="admin_test", password="adminpassword", email="admin@techpanda.com", role=UserRole.ADMIN
        )
        self.manager = User.objects.create_user(
            username="mgr_sheet", password="pwd", role=UserRole.MANAGER, branch=self.branch
        )
        self.telecaller = User.objects.create_user(
            username="tc_sheet", password="pwd", role=UserRole.TELECALLER,
            branch=self.branch, manager=self.manager
        )

        self.valid_sheet_url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0"
        self.sheet_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"

        self.connection = GoogleSheetConnection.objects.create(
            name="Offline Campaigns Sheet",
            spreadsheet_url=self.valid_sheet_url,
            spreadsheet_id=self.sheet_id,
            worksheet_name="Form Responses 1",
            branch=self.branch,
            assignment_method='Automatic',
            field_mapping={
                "name": "Full Name",
                "phone": "Mobile Number",
                "email": "Email Address",
                "course": "Interested Course",
                "city": "City"
            },
            is_active=True,
            created_by=self.admin_user
        )

    def test_extract_spreadsheet_id(self):
        """Verify URL parser extracts ID from various Google Sheet URL formats."""
        # Standard edit URL
        self.assertEqual(
            extract_spreadsheet_id(self.valid_sheet_url),
            "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        )
        # URL with /view
        url2 = "https://docs.google.com/spreadsheets/d/2CxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/view"
        self.assertEqual(
            extract_spreadsheet_id(url2),
            "2CxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        )
        # Raw alphanumeric ID
        raw_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        self.assertEqual(extract_spreadsheet_id(raw_id), raw_id)
        # Invalid URL
        self.assertIsNone(extract_spreadsheet_id("https://google.com/search?q=test"))
        self.assertIsNone(extract_spreadsheet_id(""))

    def test_normalize_header(self):
        """Verify header normalization collapses spaces, removes special chars, and lowercases."""
        self.assertEqual(normalize_header("  Full   Name  "), "full name")
        self.assertEqual(normalize_header("Email_Address"), "email address")
        self.assertEqual(normalize_header("PHONE-NUMBER"), "phone number")
        self.assertEqual(normalize_header("Timestamp"), "timestamp")
        self.assertEqual(normalize_header(""), "")

    def test_detect_column_mapping_google_forms(self):
        """Verify Google Form headers are dynamically and intelligently mapped."""
        google_form_headers = [
            "Timestamp",
            "Full Name",
            "Gender",
            "Phone Number",
            "Email address",
            "Interested Course",
            "Preferred Location",
            "Synced"
        ]
        mapping = detect_column_mapping(google_form_headers)
        self.assertEqual(mapping.get('name'), "Full Name")
        self.assertEqual(mapping.get('phone'), "Phone Number")
        self.assertEqual(mapping.get('email'), "Email address")
        self.assertEqual(mapping.get('product'), "Interested Course")
        self.assertEqual(mapping.get('branch'), "Preferred Location")
        self.assertEqual(mapping.get('gender'), "Gender")
        self.assertEqual(mapping.get('synced'), "Synced")
        self.assertEqual(mapping.get('timestamp'), "Timestamp")

    def test_compute_mapped_hash(self):
        """Verify hash generation detects data modifications."""
        row1 = {"name": "Alice Smith", "phone": "9876500001", "email": "alice@test.com"}
        row2 = {"name": "Alice Smith", "phone": "9876500001", "email": "alice@test.com"}
        row3 = {"name": "Alice Johnson", "phone": "9876500001", "email": "alice@test.com"}
        
        hash1 = compute_mapped_hash(row1)
        hash2 = compute_mapped_hash(row2)
        hash3 = compute_mapped_hash(row3)

        self.assertEqual(hash1, hash2)
        self.assertNotEqual(hash1, hash3)

    def test_assign_lead_to_team_hierarchy(self):
        """Verify assigned telecaller always reports to assigned manager."""
        sample_lead = Lead(name="Test", phone="9900000000")
        assign_lead_to_team(sample_lead, self.branch, method='Automatic')
        self.assertEqual(sample_lead.assigned_manager, self.manager)
        self.assertEqual(sample_lead.assigned_telecaller, self.telecaller)
        self.assertEqual(sample_lead.assigned_telecaller.manager, sample_lead.assigned_manager)

    @patch('leads.google_sheets.fetch_sheet_data')
    def test_sync_google_sheet_insert_and_update(self, mock_fetch):
        """Test full one-way sync: insert new row, skip unchanged, update modified, and handle deleted."""
        initial_headers = ["Full Name", "Mobile Number", "Email Address", "Interested Course", "City"]
        initial_rows = [
            {"Full Name": "John Doe", "Mobile Number": "9876543201", "Email Address": "john@test.com", "Interested Course": "Data Science Master", "City": "Bangalore"},
            {"Full Name": "Jane Smith", "Mobile Number": "9876543202", "Email Address": "jane@test.com", "Interested Course": "Data Science Master", "City": "Bangalore"}
        ]
        mock_fetch.return_value = (initial_headers, initial_rows)

        history1 = sync_google_sheet(self.connection)
        self.assertEqual(history1['status'], 'Completed')
        self.assertEqual(history1['rows_checked'], 2)
        self.assertEqual(history1['new_leads'], 2)
        self.assertEqual(history1['updated_leads'], 0)
        self.assertEqual(history1['skipped'], 0)

        # Verify leads created
        lead_john = Lead.objects.get(phone="9876543201")
        self.assertEqual(lead_john.name, "John Doe")
        self.assertEqual(lead_john.source, "Google Sheets")
        self.assertTrue(lead_john.is_offline)
        self.assertEqual(lead_john.branch, self.branch)
        self.assertEqual(lead_john.product, self.product)
        self.assertEqual(lead_john.assigned_manager, self.manager)
        self.assertEqual(lead_john.assigned_telecaller, self.telecaller)

        # Verify mapping records
        mapping_john = GoogleSheetRowMapping.objects.get(connection=self.connection, lead=lead_john)
        self.assertEqual(mapping_john.source_status, 'Active')

        # Step 2: Re-sync identical data -> should skip both (Idempotency test: 0 duplicates)
        history2 = sync_google_sheet(self.connection)
        self.assertEqual(history2['status'], 'Completed')
        self.assertEqual(history2['rows_checked'], 2)
        self.assertEqual(history2['new_leads'], 0)
        self.assertEqual(history2['updated_leads'], 0)
        self.assertEqual(history2['skipped'], 2)

        # Step 3: Modify row 1 (John -> Jonathan), remove row 2 (Jane deleted from sheet)
        updated_rows = [
            {"Full Name": "Jonathan Doe", "Mobile Number": "9876543201", "Email Address": "jonathan@test.com", "Interested Course": "Data Science Master", "City": "Bangalore"}
        ]
        mock_fetch.return_value = (initial_headers, updated_rows)

        history3 = sync_google_sheet(self.connection)
        self.assertEqual(history3['status'], 'Completed')
        self.assertEqual(history3['rows_checked'], 1)
        self.assertEqual(history3['new_leads'], 0)
        self.assertEqual(history3['updated_leads'], 1)

        lead_john.refresh_from_db()
        self.assertEqual(lead_john.name, "Jonathan Doe")
        self.assertEqual(lead_john.email, "jonathan@test.com")

        # Verify Jane's lead is NOT deleted from CRM, but marked as Removed from source
        lead_jane = Lead.objects.get(phone="9876543202")
        self.assertIsNotNone(lead_jane)
        mapping_jane = GoogleSheetRowMapping.objects.get(connection=self.connection, lead=lead_jane)
        self.assertEqual(mapping_jane.source_status, 'Removed from source')

    @patch('leads.google_sheets.fetch_sheet_data')
    def test_sync_preserves_unmapped_google_form_fields(self, mock_fetch):
        """Verify unmapped fields like Gender, College, Experience are saved in lead notes."""
        headers = ["Full Name", "Phone Number", "Email", "Gender", "College", "Experience"]
        rows = [
            {
                "Full Name": "Kavitha Raj",
                "Phone Number": "9876543222",
                "Email": "kavitha@test.com",
                "Gender": "Female",
                "College": "Anna University",
                "Experience": "Fresher"
            }
        ]
        mock_fetch.return_value = (headers, rows)

        # Sync connection without explicit field mapping -> auto-detects
        conn2 = GoogleSheetConnection.objects.create(
            name="College Form",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/2Bxikavitha12345/edit",
            spreadsheet_id="2Bxikavitha12345",
            worksheet_name="Form Responses 1",
            is_active=True,
            created_by=self.admin_user
        )
        res = sync_google_sheet(conn2)
        self.assertEqual(res['new_leads'], 1)

        lead = Lead.objects.get(phone="9876543222")
        self.assertEqual(lead.name, "Kavitha Raj")
        self.assertIn("Gender: Female", lead.notes)
        self.assertIn("College: Anna University", lead.notes)

    @patch('leads.google_sheets.fetch_sheet_data')
    def test_sync_row_error_does_not_halt_sync(self, mock_fetch):
        """Verify that a row with invalid phone does not crash the entire sync."""
        headers = ["Full Name", "Mobile Number", "Email Address"]
        rows = [
            {"Full Name": "Good Lead 1", "Mobile Number": "9876543203", "Email Address": "good1@test.com"},
            {"Full Name": "Bad Lead No Phone No Email", "Mobile Number": "", "Email Address": ""},
            {"Full Name": "Good Lead 2", "Mobile Number": "9876543204", "Email Address": "good2@test.com"},
        ]
        mock_fetch.return_value = (headers, rows)

        history = sync_google_sheet(self.connection)
        self.assertEqual(history['status'], 'Completed with Errors')
        self.assertEqual(history['new_leads'], 2)
        self.assertEqual(history['failed'], 1)
        self.assertIn("Row 3", history['errors'][0])

        # Both valid leads must be present
        self.assertTrue(Lead.objects.filter(phone="9876543203").exists())
        self.assertTrue(Lead.objects.filter(phone="9876543204").exists())

    def test_admin_offline_leads_view(self):
        """Admin can access offline leads page and see connection option."""
        self.client.login(username="admin_test", password="adminpassword")
        response = self.client.get(reverse('admin_offline_leads'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OFFLINE LEADS")
        self.assertContains(response, "Add Google Sheet")

    def test_role_security_offline_leads(self):
        """Non-admin users cannot access admin offline leads or connect sheets."""
        self.client.login(username="mgr_sheet", password="pwd")
        response = self.client.get(reverse('admin_offline_leads'))
        self.assertEqual(response.status_code, 302)

        self.client.login(username="tc_sheet", password="pwd")
        response2 = self.client.get(reverse('admin_offline_leads'))
        self.assertEqual(response2.status_code, 302)

    def test_toggle_google_sheet_connection(self):
        """Admin can pause and resume a Google Sheet connection."""
        self.client.login(username="admin_test", password="adminpassword")
        url = reverse('admin_google_sheet_toggle', args=[self.connection.pk])
        
        # Toggle to inactive
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.connection.refresh_from_db()
        self.assertFalse(self.connection.is_active)

        # Toggle back to active
        self.client.post(url)
        self.connection.refresh_from_db()
        self.assertTrue(self.connection.is_active)

    def test_history_view(self):
        """Admin can view the sync history page of a connection."""
        GoogleSheetSyncHistory.objects.create(
            connection=self.connection,
            status='Completed',
            rows_checked=15,
            new_leads=5,
            updated_leads=2,
            skipped=8,
            failed=0
        )
        self.client.login(username="admin_test", password="adminpassword")
        url = reverse('admin_google_sheet_history', args=[self.connection.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Synchronization Runs")
        self.assertContains(response, "Offline Campaigns Sheet")

    @patch('leads.management.commands.sync_google_sheet.check_google_auth_status')
    @patch('leads.google_sheets.fetch_sheet_data')
    def test_sync_google_sheet_management_command(self, mock_fetch, mock_auth):
        """Test python manage.py sync_google_sheet management command."""
        mock_auth.return_value = {
            'is_authenticated': True,
            'credentials_exist': True,
            'error_message': None,
            'configured_sheet_id': '',
            'configured_sheet_tab': 'Form Responses 1',
        }
        mock_fetch.return_value = (
            ["Full Name", "Phone Number", "Email"],
            [{"Full Name": "Cmd Lead", "Phone Number": "9876500999", "Email": "cmd@test.com"}]
        )

        out = StringIO()
        call_command('sync_google_sheet', connection=self.connection.pk, stdout=out)
        output = out.getvalue()
        self.assertIn("Google Sheets Sync", output)
        self.assertIn("Sync completed successfully.", output)
        self.assertTrue(Lead.objects.filter(phone="9876500999").exists())

    @patch('leads.views.validate_spreadsheet_access')
    @patch('leads.views.sync_google_sheet')
    def test_connect_endpoint_auto_imports_and_auto_assigns(self, mock_sync, mock_validate):
        """Admin connects with only URL and Name; verifies validation, auto-detection, auto-import, and assignment."""
        mock_validate.return_value = (
            True,
            "new_sheet_123456",
            "Form Responses 1",
            ["Full Name", "Mobile Number", "Email Address", "Interested Course"],
            "Offline Walk-in Leads",
            None
        )
        mock_sync.return_value = {
            'status': 'Completed',
            'rows_checked': 5,
            'new_leads': 5,
            'updated_leads': 0,
            'skipped': 0,
            'failed': 0
        }

        self.client.login(username="admin_test", password="adminpassword")
        url = reverse('admin_google_sheet_connect')
        payload = {
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/new_sheet_123456/edit',
            'name': 'Campaign Sheet 2026'
        }
        response = self.client.post(url, payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['sheet_title'], 'Campaign Sheet 2026')
        self.assertEqual(data['worksheet'], 'Form Responses 1')
        self.assertEqual(data['new_leads'], 5)

        conn = GoogleSheetConnection.objects.get(spreadsheet_id="new_sheet_123456")
        self.assertEqual(conn.name, "Campaign Sheet 2026")
        self.assertEqual(conn.assignment_method, "Automatic")
        self.assertIn("name", conn.field_mapping)
        self.assertIn("phone", conn.field_mapping)
        mock_sync.assert_called_once()

    @patch('leads.views.validate_spreadsheet_access')
    def test_connect_endpoint_invalid_url_returns_error(self, mock_validate):
        """Invalid Google Spreadsheet URL or inaccessible sheet returns error and does not import."""
        mock_validate.return_value = (
            False,
            None,
            None,
            [],
            '',
            'Invalid Google Spreadsheet URL or permission denied.'
        )

        self.client.login(username="admin_test", password="adminpassword")
        url = reverse('admin_google_sheet_connect')
        response = self.client.post(url, {'spreadsheet_url': 'https://invalid-url.com'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid Google Spreadsheet URL', data['error'])

    @patch('leads.google_sheets.fetch_sheet_data')
    def test_sync_preserves_crm_lead_status(self, mock_fetch):
        """Modifying sheet row updates fields (Name, Phone, etc.) but strictly preserves CRM status."""
        headers = ["Full Name", "Mobile Number", "Email Address", "Interested Course", "City"]
        rows = [
            {"Full Name": "Suresh Kumar", "Mobile Number": "9876543301", "Email Address": "suresh@test.com", "Interested Course": "Data Science Master", "City": "Bangalore"}
        ]
        mock_fetch.return_value = (headers, rows)

        # First sync creates lead
        res1 = sync_google_sheet(self.connection)
        self.assertEqual(res1['new_leads'], 1)
        lead = Lead.objects.get(phone="9876543301")
        self.assertEqual(lead.status, LeadStatus.NEW)

        # CRM user updates status to 'Follow-up'
        lead.status = LeadStatus.FOLLOW_UP
        lead.save()

        # Sheet row changes name and email
        updated_rows = [
            {"Full Name": "Suresh K. Sharma", "Mobile Number": "9876543301", "Email Address": "suresh.sharma@test.com", "Interested Course": "Data Science Master", "City": "Bangalore"}
        ]
        mock_fetch.return_value = (headers, updated_rows)

        # Second sync
        res2 = sync_google_sheet(self.connection)
        self.assertEqual(res2['updated_leads'], 1)

        lead.refresh_from_db()
        self.assertEqual(lead.name, "Suresh K. Sharma")
        self.assertEqual(lead.email, "suresh.sharma@test.com")
        # Critical verification: Status remains Follow-up (not overwritten by sheet sync)
        self.assertEqual(lead.status, LeadStatus.FOLLOW_UP)

    def test_lead_status_update_endpoint(self):
        """Admin updates lead status via AJAX API: updates DB, creates follow-up, logs activity, returns target URL."""
        lead = Lead.objects.create(
            name="Rohit Verma",
            phone="9876543302",
            status=LeadStatus.NEW,
            assigned_manager=self.manager,
            assigned_telecaller=self.telecaller
        )
        self.client.login(username="admin_test", password="adminpassword")

        # 1. Update to Interested
        url = reverse('admin_lead_update_status', args=[lead.pk])
        resp = self.client.post(url, {'status': 'Interested'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['new_status'], 'Interested')
        self.assertIn('interested', data['target_url'])
        lead.refresh_from_db()
        self.assertEqual(lead.status, LeadStatus.INTERESTED)

        # 2. Update to Follow-up -> should auto-create pending FollowUp record
        resp2 = self.client.post(url, {'status': 'Follow-up'})
        self.assertEqual(resp2.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.status, LeadStatus.FOLLOW_UP)
        from followups.models import FollowUp
        fu = FollowUp.objects.filter(lead=lead).first()
        self.assertIsNotNone(fu)
        self.assertEqual(fu.assigned_user, self.telecaller)

        # 3. Update to Discussion
        resp3 = self.client.post(url, {'status': 'Discussion'})
        self.assertEqual(resp3.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.status, LeadStatus.DISCUSSION)

    def test_7s_offline_leads_data_api(self):
        """7-second polling endpoint returns rendered HTML and pagination."""
        Lead.objects.create(
            name="Offline Student",
            phone="9876543303",
            source="Google Sheets",
            is_offline=True,
            status=LeadStatus.INTERESTED
        )
        self.client.login(username="admin_test", password="adminpassword")
        url = reverse('admin_offline_leads_data_api')
        resp = self.client.get(url + '?sync=0')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertIn('Offline Student', data['html'])
        self.assertIn('Interested', data['html'])

    def test_status_pipeline_views(self):
        """All 6 status-specific pipeline views render with 200 OK and show matching leads."""
        lead_interested = Lead.objects.create(name="Interested Lead", phone="9876500001", status=LeadStatus.INTERESTED)
        lead_demo = Lead.objects.create(name="Demo Lead", phone="9876500002", status=LeadStatus.DEMO_SCHEDULED)
        lead_converted = Lead.objects.create(name="Converted Lead", phone="9876500003", status=LeadStatus.CONVERTED)
        lead_lost = Lead.objects.create(name="Lost Lead", phone="9876500004", status=LeadStatus.LOST)
        lead_later = Lead.objects.create(name="Later Lead", phone="9876500005", status=LeadStatus.LATER)
        lead_disc = Lead.objects.create(name="Discussion Lead", phone="9876500006", status=LeadStatus.DISCUSSION)

        self.client.login(username="admin_test", password="adminpassword")

        pages = [
            (reverse('admin_interested_leads'), "Interested Lead"),
            (reverse('admin_demo_scheduled_leads'), "Demo Lead"),
            (reverse('admin_converted_leads'), "Converted Lead"),
            (reverse('admin_lost_leads'), "Lost Lead"),
            (reverse('admin_later_leads'), "Later Lead"),
            (reverse('admin_discussion_leads'), "Discussion Lead"),
        ]

        for url, lead_name in pages:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, lead_name)

    def test_google_sheet_connect_zero_auth_and_result_payload(self):
        """
        Verify Google Sheet connection without authentication requirement:
        - Connects directly using Google Sheet link
        - Returns Section 8 connection result fields (Not Required, 3 seconds, etc.)
        - Defaults name to 'Student Enquiries' if none provided
        """
        self.client.login(username="admin_test", password="adminpassword")
        test_url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0"

        with patch('leads.google_sheets.fetch_sheet_data') as mock_fetch, \
             patch('leads.google_sheets.fetch_spreadsheet_metadata') as mock_meta:
            mock_meta.return_value = {
                'id': '1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms',
                'title': 'Student Enquiries',
                'tabs': ['Sheet1']
            }
            mock_fetch.return_value = (
                ['Full Name', 'Mobile Number', 'Branch', 'Course'],
                [
                    ['Arun Kumar', '9876543210', 'Chennai', 'Python FullStack'],
                    ['Priya S', '9876543211', 'Madurai', 'Data Analytics']
                ]
            )

            resp = self.client.post(reverse('admin_google_sheet_connect'), {
                'spreadsheet_url': test_url,
                'name': ''
            })

            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data['success'])
            self.assertEqual(data['sheet_title'], 'Student Enquiries')
            self.assertEqual(data['auth_status'], 'Not Required')
            self.assertEqual(data['live_import'], 'Active')
            self.assertEqual(data['refresh_interval'], '3 seconds')
            self.assertIn('last_sync_time', data)
            self.assertIn('next_refresh_time', data)
            self.assertGreaterEqual(data['leads_imported'], 2)

    def test_google_sheet_delete_ajax_and_lead_preservation(self):
        """
        Verify disconnecting Google Sheet via AJAX:
        - Stops live connection
        - Preserves all imported leads in the CRM database
        """
        self.client.login(username="admin_test", password="adminpassword")

        # Create lead associated with connection
        lead = Lead.objects.create(
            name="Preserved Student",
            phone="9876599999",
            source="Google Sheets",
            is_offline=True
        )
        GoogleSheetRowMapping.objects.create(
            connection=self.connection,
            row_identifier="2",
            row_index=2,
            row_data_hash="test_hash_preserved",
            lead=lead
        )

        resp = self.client.post(
            reverse('admin_google_sheet_delete', args=[self.connection.id]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])

        # Connection is removed
        self.assertFalse(GoogleSheetConnection.objects.filter(id=self.connection.id).exists())

        # Lead is preserved!
        lead.refresh_from_db()
        self.assertEqual(lead.name, "Preserved Student")
        self.assertEqual(lead.phone, "9876599999")

    def test_offline_leads_live_3second_metadata_and_sheets_cards(self):
        """
        Verify admin_offline_leads_data_api returns 3-second live updates,
        timestamps, and connected sheets cards list.
        """
        self.client.login(username="admin_test", password="adminpassword")
        url = reverse('admin_offline_leads_data_api') + '?sync=0'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        self.assertTrue(data['success'])
        self.assertIn('last_sync_time', data)
        self.assertIn('next_refresh_time', data)
        self.assertIn('timestamp', data)
        self.assertIn('connected_sheets', data)
        self.assertGreaterEqual(len(data['connected_sheets']), 1)

        sheet_entry = data['connected_sheets'][0]
        self.assertEqual(sheet_entry['id'], self.connection.id)
        self.assertEqual(sheet_entry['name'], self.connection.name)
        self.assertEqual(sheet_entry['status'], 'Connected')
        self.assertIn('last_sync', sheet_entry)
        self.assertIn('next_refresh', sheet_entry)

    def test_offline_leads_page_sections_and_google_form_live_fetch(self):
        """
        Verify Offline Leads page per prompt 7:
        - Displays OFFLINE LEADS header
        - Displays single [ + Add Google Sheet ] option
        - Displays LIVE LEADS section
        - Displays LIVE LEAD FETCHING ACTIVE and Auto Refresh: Every 3 seconds
        - Displays ADD GOOGLE SHEET modal with 'Google Form Link' and 'Connect & Fetch Leads'
        """
        self.client.login(username="admin_test", password="adminpassword")
        resp = self.client.get(reverse('admin_offline_leads_list'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Check required elements
        self.assertIn('OFFLINE LEADS', content)
        self.assertIn('LIVE LEADS', content)
        self.assertIn('LIVE LEAD FETCHING ACTIVE', content)
        self.assertIn('Auto Refresh: Every 3 seconds', content)
        self.assertIn('ADD GOOGLE SHEET', content)
        self.assertIn('Google Form Link', content)
        self.assertIn('Connect & Fetch Leads', content)


