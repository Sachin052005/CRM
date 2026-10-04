import unittest
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from leads.models import (
    Lead,
    GoogleSheetConnection,
    GoogleFormConnection
)


class OfflineLeadsLiveSpreadsheetTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Admin User
        self.admin = User.objects.create_user(
            username='admin_live_sheet',
            password='AdminPassword@2026',
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True
        )

        # Clear existing data to test initial clean state
        GoogleSheetConnection.objects.all().delete()
        GoogleFormConnection.objects.all().delete()
        Lead.objects.filter(is_offline=True).delete()

    def test_section_1_and_7_clean_start_add_spreadsheet_url_no_leads(self):
        """
        Section 1 & 7:
        When no spreadsheet is connected, show only:
          OFFLINE LEADS
          Add Spreadsheet URL
          [ Paste Spreadsheet URL ]
          [ Connect ]
          No spreadsheet connected.
        Do not display a lead table until a spreadsheet has been successfully connected.
        """
        self.client.login(username='admin_live_sheet', password='AdminPassword@2026')
        response = self.client.get(reverse('admin_offline_leads_list'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Required minimal content
        self.assertIn("OFFLINE LEADS", content)
        self.assertIn("Add Spreadsheet URL", content)
        self.assertIn("Paste Spreadsheet URL", content)
        self.assertIn("Connect", content)
        self.assertIn("No spreadsheet connected.", content)

        # Table should NOT be displayed when not connected
        self.assertIn('id="connectedState" style="display: none;"', content)
        self.assertNotIn("LIVE SPREADSHEET DATA", content.split('id="connectedState" style="display: none;"')[0])

    @patch('leads.views.fetch_sheet_data')
    def test_section_2_3_real_time_spreadsheet_connection_and_dynamic_columns(self, mock_fetch):
        """
        Section 2 & 3:
        Connects directly to the provided spreadsheet URL.
        Reads actual columns and actual rows.
        Generates table using those exact columns.
        """
        sample_headers = ['Name', 'Phone', 'Email', 'Course']
        sample_rows = [
            {'_row_index': 2, 'Name': 'Arun Kumar', 'Phone': '9876543210', 'Email': 'arun@gmail.com', 'Course': 'Python'},
            {'_row_index': 3, 'Name': 'Priya', 'Phone': '9123456780', 'Email': 'priya@gmail.com', 'Course': 'Data Science'},
            {'_row_index': 4, 'Name': 'Karthik', 'Phone': '9988776655', 'Email': 'karthik@gmail.com', 'Course': 'Django'},
        ]
        mock_fetch.return_value = (sample_headers, sample_rows)

        self.client.login(username='admin_live_sheet', password='AdminPassword@2026')
        sheet_url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0"

        # POST Connect
        res = self.client.post(reverse('admin_google_sheet_connect'), {
            'spreadsheet_url': sheet_url
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_connected'])
        self.assertEqual(data['headers'], sample_headers)
        self.assertEqual(data['total_rows'], 3)

        # GET Page
        resp = self.client.get(reverse('admin_offline_leads_list'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn("Spreadsheet:", content)
        self.assertIn(sheet_url, content)
        self.assertIn("🟢 Connected", content)
        self.assertIn("LIVE SPREADSHEET DATA", content)

        # Dynamic columns
        for h in sample_headers:
            self.assertIn(f"<th>{h}</th>", content)

        # Data rows (actual phone number displayed, not masked - see master prompt Section 28/52)
        self.assertIn("Arun Kumar", content)
        self.assertIn("9876543210", content)
        self.assertIn("arun@gmail.com", content)
        self.assertIn("Python", content)

        self.assertIn("Priya", content)
        self.assertIn("9123456780", content)
        self.assertIn("priya@gmail.com", content)
        self.assertIn("Data Science", content)

        self.assertIn("Karthik", content)
        self.assertIn("9988776655", content)
        self.assertIn("karthik@gmail.com", content)
        self.assertIn("Django", content)

    @patch('leads.views.fetch_sheet_data')
    def test_section_3_custom_non_standard_columns_not_assumed(self, mock_fetch):
        """
        Section 3:
        The system must NOT assume fixed columns such as Name, Phone, Email, or Course.
        Connects a spreadsheet with completely different arbitrary columns.
        """
        custom_headers = ['Student ID', 'Applicant', 'Contact No', 'Location', 'Degree', 'Club']
        custom_rows = [
            {
                '_row_index': 2,
                'Student ID': 'STU-101',
                'Applicant': 'Rohan Sharma',
                'Contact No': '9811223344',
                'Location': 'Mumbai',
                'Degree': 'B.Tech CS',
                'Club': 'Robotics'
            }
        ]
        mock_fetch.return_value = (custom_headers, custom_rows)

        self.client.login(username='admin_live_sheet', password='AdminPassword@2026')
        sheet_url = "https://docs.google.com/spreadsheets/d/2CxiMVsCustomCols12345/edit"

        res = self.client.post(reverse('admin_google_sheet_connect'), {
            'spreadsheet_url': sheet_url
        })
        self.assertEqual(res.status_code, 200)

        resp = self.client.get(reverse('admin_offline_leads_list'))
        content = resp.content.decode('utf-8')

        # Verifies table generates the actual columns
        for col in custom_headers:
            self.assertIn(f"<th>{col}</th>", content)

        self.assertIn("STU-101", content)
        self.assertIn("Rohan Sharma", content)
        self.assertIn("Mumbai", content)
        self.assertIn("B.Tech CS", content)
        self.assertIn("Robotics", content)

    @patch('leads.views.fetch_sheet_data')
    def test_section_4_and_5_live_data_refresh_and_new_lead_update(self, mock_fetch):
        """
        Section 4 & 5:
        10-second live check detects new lead/row added to connected spreadsheet.
        Returns updated data for automatic frontend DOM update.
        """
        self.client.login(username='admin_live_sheet', password='AdminPassword@2026')

        # Initial 2 rows
        initial_headers = ['Name', 'Phone']
        initial_rows = [
            {'_row_index': 2, 'Name': 'Arun Kumar', 'Phone': '9876543210'},
            {'_row_index': 3, 'Name': 'Priya', 'Phone': '9123456780'},
        ]
        mock_fetch.return_value = (initial_headers, initial_rows)

        sheet_url = "https://docs.google.com/spreadsheets/d/3DxiMVsLiveCheck12345/edit"
        self.client.post(reverse('admin_google_sheet_connect'), {'spreadsheet_url': sheet_url})

        # 10-second polling API check before new row
        api_res1 = self.client.get(reverse('admin_offline_leads_data_api'))
        self.assertEqual(api_res1.status_code, 200)
        data1 = api_res1.json()
        self.assertTrue(data1['is_connected'])
        self.assertEqual(data1['total_rows'], 2)

        # New row added to spreadsheet: Karthik
        updated_rows = list(initial_rows) + [
            {'_row_index': 4, 'Name': 'Karthik', 'Phone': '9988776655'}
        ]
        mock_fetch.return_value = (initial_headers, updated_rows)

        # Next 10-second refresh cycle detects change
        api_res2 = self.client.get(reverse('admin_offline_leads_data_api'))
        self.assertEqual(api_res2.status_code, 200)
        data2 = api_res2.json()
        self.assertEqual(data2['total_rows'], 3)
        self.assertIn(['Karthik', '9988776655'], data2['rows'])

    @patch('leads.views.fetch_sheet_data')
    def test_section_6_only_connected_spreadsheet_data_strictly_isolated(self, mock_fetch):
        """
        Section 6:
        Only connected spreadsheet data is displayed.
        No Meta leads, Website leads, or unrelated leads mixed in.
        """
        # Create unrelated leads
        Lead.objects.create(name="Meta Facebook Lead", phone="9911111111", email="meta@example.com", source="Meta", is_offline=False)
        Lead.objects.create(name="Website Lead", phone="9922222222", email="web@example.com", source="Website", is_offline=False)
        Lead.objects.create(name="Manual CRM Lead", phone="9933333333", email="manual@example.com", source="Manual", is_offline=False)

        mock_fetch.return_value = (
            ['Name', 'Course'],
            [{'_row_index': 2, 'Name': 'Sheet Lead Only', 'Course': 'AI Mastery'}]
        )

        self.client.login(username='admin_live_sheet', password='AdminPassword@2026')
        sheet_url = "https://docs.google.com/spreadsheets/d/4ExiMVsIsolatedSource/edit"
        self.client.post(reverse('admin_google_sheet_connect'), {'spreadsheet_url': sheet_url})

        resp = self.client.get(reverse('admin_offline_leads_list'))
        content = resp.content.decode('utf-8')

        # Only spreadsheet data
        self.assertIn("Sheet Lead Only", content)
        self.assertIn("AI Mastery", content)

        # Never mixes unrelated leads
        self.assertNotIn("Meta Facebook Lead", content)
        self.assertNotIn("Website Lead", content)
        self.assertNotIn("Manual CRM Lead", content)

    def test_section_8_no_authentication_ui(self):
        """
        Section 8:
        Do not show any authentication process, OAuth screen, credential form, or auth UI.
        """
        self.client.login(username='admin_live_sheet', password='AdminPassword@2026')
        response = self.client.get(reverse('admin_offline_leads_list'))
        content = response.content.decode('utf-8')

        self.assertNotIn("OAuth", content)
        self.assertNotIn("credentials.json", content)
        self.assertNotIn("Google Authentication", content)
        self.assertNotIn("Authorize", content)

    @patch('leads.views.fetch_sheet_data')
    def test_section_9_disconnect_flow(self, mock_fetch):
        """
        Section 9:
        Disconnect action stops live sync and restores clean unconnected state.
        """
        mock_fetch.return_value = (['Name'], [{'_row_index': 2, 'Name': 'Lead A'}])
        self.client.login(username='admin_live_sheet', password='AdminPassword@2026')

        sheet_url = "https://docs.google.com/spreadsheets/d/5FxiMVsDisconnect/edit"
        self.client.post(reverse('admin_google_sheet_connect'), {'spreadsheet_url': sheet_url})
        conn = GoogleSheetConnection.objects.get(spreadsheet_id='5FxiMVsDisconnect')

        # Disconnect (connection-specific - disconnect must always target one connection_id)
        disc_res = self.client.post(reverse('admin_offline_leads_disconnect'), {'connection_id': conn.id})
        self.assertEqual(disc_res.status_code, 200)
        self.assertTrue(disc_res.json()['success'])
        self.assertFalse(disc_res.json()['is_connected'])

        # Page after disconnect
        resp = self.client.get(reverse('admin_offline_leads_list'))
        content = resp.content.decode('utf-8')
        self.assertIn("No spreadsheet connected.", content)
