from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, UserRole
from leads.models import (
    Lead,
    LeadStatus,
    GoogleSheetConnection,
    GoogleSheetRowMapping,
    GoogleFormConnection
)


class GoogleSheetLiveLeadFetchTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Admin user
        self.admin = User.objects.create_user(
            username='admin_sheets_user',
            password='Password@123',
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True
        )

        # Clear existing data to test initial clean state
        GoogleSheetConnection.objects.all().delete()
        GoogleFormConnection.objects.all().delete()
        Lead.objects.filter(is_offline=True).delete()

    def test_section_1_add_google_sheet_modal_and_clean_start(self):
        """
        Section 1 & Initial State:
        - When no spreadsheet is connected, page starts clean with no leads.
        - Displays [ + Add Google Sheet ] option.
        - Modal has 'Spreadsheet Name', 'Google Spreadsheet Link',
          'The system will fetch leads only from this connected spreadsheet.',
          'Live Fetching: Enabled', 'Refresh Interval: Every 3 seconds',
          'Connect & Fetch Leads', 'Cancel'.
        """
        self.client.login(username='admin_sheets_user', password='Password@123')
        resp = self.client.get(reverse('admin_offline_leads_list'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn("+ Add Google Sheet", content)
        self.assertIn("No Connected Spreadsheets", content)
        self.assertIn("ADD GOOGLE SHEET", content)
        self.assertIn("Spreadsheet Name", content)
        self.assertIn("Google Spreadsheet Link", content)
        self.assertIn("The system will fetch leads only from this connected spreadsheet.", content)
        self.assertIn("Live Fetching:", content)
        self.assertIn("Refresh Interval:", content)
        self.assertIn("Every 3 seconds", content)
        self.assertIn("Connect & Fetch Leads", content)
        self.assertIn("Cancel", content)

    def test_section_2_connect_single_google_sheet(self):
        """
        Section 2:
        Connect a spreadsheet:
        - Saved as individual lead source.
        - Displays CONNECTED GOOGLE SHEET.
        - Displays Spreadsheet: Student Enquiries, 🟢 Connected,
          Source: Connected Spreadsheet Only, Live Sync: 🟢 Active,
          Refresh Interval: Every 3 seconds, Last Fetch, Next Fetch,
          [ View Leads ], [ Sync Now ], [ Disconnect ].
        """
        self.client.login(username='admin_sheets_user', password='Password@123')
        post_url = reverse('admin_google_sheet_connect')
        payload = {
            'name': 'Student Enquiries',
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0'
        }
        res = self.client.post(post_url, payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('sheet_title'), 'Student Enquiries')

        # Now view the page
        resp = self.client.get(reverse('admin_offline_leads_list'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn("CONNECTED GOOGLE SHEET", content)
        self.assertIn("Spreadsheet: Student Enquiries", content)
        self.assertIn("🟢 Connected", content)
        self.assertIn("Source:", content)
        self.assertIn("Connected Spreadsheet Only", content)
        self.assertIn("Live Sync:", content)
        self.assertIn("🟢 Active", content)
        self.assertIn("Refresh Interval:", content)
        self.assertIn("Every 3 seconds", content)
        self.assertIn("Last Fetch:", content)
        self.assertIn("Next Fetch:", content)
        self.assertIn("View Leads", content)
        self.assertIn("Sync Now", content)
        self.assertIn("Disconnect", content)

    def test_section_3_fetch_only_connected_spreadsheet_isolated_source(self):
        """
        Section 3:
        CRM fetches leads ONLY from the connected spreadsheet.
        Does NOT mix data from Meta/Facebook, Website, or Manual leads.
        """
        self.client.login(username='admin_sheets_user', password='Password@123')

        # Create unrelated leads from other sources
        Lead.objects.create(name="Meta Lead", phone="9888811111", email="meta@example.com", source="Meta", is_offline=False)
        Lead.objects.create(name="Website Lead", phone="9888822222", email="web@example.com", source="Website", is_offline=False)
        Lead.objects.create(name="Manual Lead", phone="9888833333", email="manual@example.com", source="Manual", is_offline=False)

        # Connect Google Sheet
        self.client.post(reverse('admin_google_sheet_connect'), {
            'name': 'Student Enquiries',
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0'
        })

        # Fetch offline leads API
        api_res = self.client.get(reverse('admin_offline_leads_data_api'))
        self.assertEqual(api_res.status_code, 200)
        data = api_res.json()

        # Must contain spreadsheet leads
        self.assertIn("Arun Kumar", data['html'])
        self.assertIn("Priya", data['html'])
        self.assertIn("Karthik", data['html'])
        self.assertIn("Student Enquiries", data['html'])

        # Must NOT contain unrelated leads
        self.assertNotIn("Meta Lead", data['html'])
        self.assertNotIn("Website Lead", data['html'])
        self.assertNotIn("Manual Lead", data['html'])

    def test_section_4_and_5_live_fetching_system_time(self):
        """
        Section 4 & 5:
        Live fetching uses CRM server/system time for Last Fetch and Next Fetch.
        Next fetch is exactly 3 seconds after current fetch.
        """
        self.client.login(username='admin_sheets_user', password='Password@123')
        self.client.post(reverse('admin_google_sheet_connect'), {
            'name': 'Student Enquiries',
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0'
        })

        api_res = self.client.get(reverse('admin_offline_leads_data_api'))
        self.assertEqual(api_res.status_code, 200)
        data = api_res.json()

        self.assertTrue(data['success'])
        self.assertTrue(data['is_connected'])
        self.assertIn('last_fetch_time', data)
        self.assertIn('next_fetch_time', data)
        # Verify valid non-empty time strings with AM/PM
        self.assertTrue('AM' in data['last_fetch_time'] or 'PM' in data['last_fetch_time'])
        self.assertTrue('AM' in data['next_fetch_time'] or 'PM' in data['next_fetch_time'])

    def test_section_7_existing_lead_handling_no_duplicates(self):
        """
        Section 7:
        Repeated 3-second fetches do NOT create duplicates of existing leads.
        """
        self.client.login(username='admin_sheets_user', password='Password@123')
        self.client.post(reverse('admin_google_sheet_connect'), {
            'name': 'Student Enquiries',
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0'
        })

        initial_count = Lead.objects.filter(is_offline=True).count()

        # Simulate subsequent 3-second fetch cycles
        self.client.get(reverse('admin_offline_leads_data_api'))
        self.client.get(reverse('admin_offline_leads_data_api'))
        self.client.get(reverse('admin_offline_leads_data_api'))

        subsequent_count = Lead.objects.filter(is_offline=True).count()
        self.assertEqual(initial_count, subsequent_count)

    def test_section_8_multiple_google_spreadsheets_and_disconnect(self):
        """
        Section 8:
        Admin can connect multiple spreadsheets using [ + Add Google Sheet ]:
        1. Student Enquiries – T. Nagar
        2. Student Enquiries – Velachery
        3. Student Enquiries – Tambaram

        Each spreadsheet remains identifiable as a separate source.
        Disconnecting a spreadsheet stops fetching from that spreadsheet.
        """
        self.client.login(username='admin_sheets_user', password='Password@123')

        # Connect Sheet 1: T. Nagar
        res1 = self.client.post(reverse('admin_google_sheet_connect'), {
            'name': 'Student Enquiries – T. Nagar',
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0'
        })
        conn1_id = res1.json()['connection_id']

        # Connect Sheet 2: Velachery
        res2 = self.client.post(reverse('admin_google_sheet_connect'), {
            'name': 'Student Enquiries – Velachery',
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/2BxiVelacherySpreadsheet12345/edit#gid=0'
        })
        conn2_id = res2.json()['connection_id']

        # Connect Sheet 3: Tambaram
        res3 = self.client.post(reverse('admin_google_sheet_connect'), {
            'name': 'Student Enquiries – Tambaram',
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/3BxiTambaramSpreadsheet67890/edit#gid=0'
        })
        conn3_id = res3.json()['connection_id']

        # Check Page renders multiple cards
        resp = self.client.get(reverse('admin_offline_leads_list'))
        content = resp.content.decode('utf-8')

        self.assertIn("CONNECTED GOOGLE SHEETS", content)
        self.assertIn("Student Enquiries – T. Nagar", content)
        self.assertIn("Student Enquiries – Velachery", content)
        self.assertIn("Student Enquiries – Tambaram", content)
        self.assertIn("+ Add Google Sheet", content)

        # Disconnect Sheet 2 (Velachery)
        disc_res = self.client.post(f"/admin/offline-leads/google-sheet/{conn2_id}/disconnect/")
        self.assertEqual(disc_res.status_code, 200)
        self.assertTrue(disc_res.json()['success'])

        # Verify Velachery connection is removed, T. Nagar and Tambaram remain
        self.assertFalse(GoogleSheetConnection.objects.filter(id=conn2_id).exists())
        self.assertTrue(GoogleSheetConnection.objects.filter(id=conn1_id).exists())
        self.assertTrue(GoogleSheetConnection.objects.filter(id=conn3_id).exists())

    def test_section_9_offline_leads_display_columns_and_total(self):
        """
        Section 9:
        OFFLINE LEADS
        🟢 LIVE SYNC ACTIVE
        Auto Fetch: Every 3 seconds
        Last Updated: [System Time]
        Table columns: Name | Phone | Email | Source
        Total Leads: 3
        """
        self.client.login(username='admin_sheets_user', password='Password@123')
        self.client.post(reverse('admin_google_sheet_connect'), {
            'name': 'Student Enquiries',
            'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0'
        })

        resp = self.client.get(reverse('admin_offline_leads_list'))
        content = resp.content.decode('utf-8')

        self.assertIn("OFFLINE LEADS", content)
        self.assertIn("🟢 LIVE SYNC ACTIVE", content)
        self.assertIn("Auto Fetch:", content)
        self.assertIn("Every 3 seconds", content)
        self.assertIn("Last Updated:", content)

        # Column headers
        self.assertIn("Name", content)
        self.assertIn("Phone", content)
        self.assertIn("Email", content)
        self.assertIn("Source", content)

        # Lead details
        self.assertIn("Arun Kumar", content)
        self.assertIn("98765xxxxx", content)
        self.assertIn("arun@example.com", content)
        self.assertIn("Student Enquiries", content)

        self.assertIn("Priya", content)
        self.assertIn("91234xxxxx", content)
        self.assertIn("priya@example.com", content)

        self.assertIn("Karthik", content)
        self.assertIn("99887xxxxx", content)
        self.assertIn("karthik@example.com", content)

        # Total Leads
        self.assertIn("Total Leads:", content)
        self.assertIn("3", content)
