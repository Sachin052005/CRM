from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch
from leads.models import Lead, LeadStatus, GoogleFormConnection, GoogleSheetConnection


class OfflineLeadsPrompt7Tests(TestCase):
    def setUp(self):
        self.client = Client()

        # Admin user
        self.admin = User.objects.create_user(
            username='admin_p7',
            password='AdminPassword@2026',
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True
        )

        # Clear any preexisting connections
        GoogleFormConnection.objects.all().delete()
        GoogleSheetConnection.objects.all().delete()
        Lead.objects.filter(is_offline=True).delete()

    def test_offline_leads_starts_with_no_leads_displayed(self):
        """
        Section 1: The Offline Leads page should start with no leads displayed.
        """
        self.client.login(username='admin_p7', password='AdminPassword@2026')
        response = self.client.get(reverse('admin_offline_leads_list'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn("OFFLINE LEADS", content)
        self.assertIn("No leads currently displayed", content)
        self.assertNotIn("Arun Kumar", content)
        self.assertNotIn("Priya", content)

    def test_single_add_google_sheet_option_and_modal_form(self):
        """
        Section 2 & 3:
        Single lead-source connection option: [ + Add Google Sheet ]
        Add Google Sheet Form modal:
          ADD GOOGLE SHEET
          Name (Enter Source Name)
          Google Form Link (Enter Google Form Link)
          [ Connect & Fetch Leads ]
        """
        self.client.login(username='admin_p7', password='AdminPassword@2026')
        response = self.client.get(reverse('admin_offline_leads_list'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Single button option
        self.assertIn("+ Add Google Sheet", content)
        self.assertNotIn("+ Upload Excel", content)

        # Modal fields
        self.assertIn("ADD GOOGLE SHEET", content)
        self.assertIn("Enter Source Name", content)
        self.assertIn("Google Form Link", content)
        self.assertIn("Enter Google Form Link", content)
        self.assertIn("Connect & Fetch Leads", content)

    def test_direct_google_form_connection_and_seeding(self):
        """
        Section 4, 6 & 7:
        Direct Google Form connection:
        - No authentication required.
        - Fetches 5 leads automatically.
        - Automatically assigns telecallers.
        """
        self.client.login(username='admin_p7', password='AdminPassword@2026')
        connect_url = reverse('admin_google_form_connect')
        payload = {
            'name': 'Tamil Nadu College Campaign',
            'form_url': 'https://docs.google.com/forms/d/e/1FAIpQLScXtestGoogleFormCampaign2026/viewform'
        }
        res = self.client.post(connect_url, payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'))
        self.assertEqual(data.get('leads_fetched'), 5)
        self.assertEqual(data.get('new_leads'), 5)

        # Check DB records
        leads = Lead.objects.filter(is_offline=True).order_by('name')
        self.assertEqual(leads.count(), 5)

        # Arun Kumar -> T. Nagar -> Ravi
        arun = Lead.objects.get(name="Arun Kumar", is_offline=True)
        self.assertEqual(arun.branch.name, "T. Nagar")
        self.assertEqual(arun.assigned_telecaller.first_name, "Ravi")
        self.assertEqual(arun.masked_phone, "98765xxxxx")

        # Priya -> Velachery -> Meena
        priya = Lead.objects.get(name="Priya", is_offline=True)
        self.assertEqual(priya.branch.name, "Velachery")
        self.assertEqual(priya.assigned_telecaller.first_name, "Meena")
        self.assertEqual(priya.masked_phone, "91234xxxxx")

        # Karthik -> Tambaram -> Suresh
        karthik = Lead.objects.get(name="Karthik", is_offline=True)
        self.assertEqual(karthik.branch.name, "Tambaram")
        self.assertEqual(karthik.assigned_telecaller.first_name, "Suresh")
        self.assertEqual(karthik.masked_phone, "99887xxxxx")

        # Vijay -> T. Nagar -> Ravi
        vijay = Lead.objects.get(name="Vijay", is_offline=True)
        self.assertEqual(vijay.branch.name, "T. Nagar")
        self.assertEqual(vijay.assigned_telecaller.first_name, "Ravi")
        self.assertEqual(vijay.masked_phone, "99876xxxxx")

        # Siva -> T. Nagar -> Ravi
        siva = Lead.objects.get(name="Siva", is_offline=True)
        self.assertEqual(siva.branch.name, "T. Nagar")
        self.assertEqual(siva.assigned_telecaller.first_name, "Ravi")
        self.assertEqual(siva.status, LeadStatus.FOLLOW_UP)
        self.assertEqual(siva.masked_phone, "98761xxxxx")

    def test_automatic_3second_live_fetching_api(self):
        """
        Section 5: Live API returns 3-second auto refresh interval and rendered rows.
        """
        self.client.login(username='admin_p7', password='AdminPassword@2026')
        # First connect
        self.client.post(reverse('admin_google_form_connect'), {
            'name': 'Campaign',
            'form_url': 'https://docs.google.com/forms/d/e/1FAIpQLScXtest/viewform'
        })

        # Fetch live data api
        api_url = reverse('admin_offline_leads_data_api')
        res = self.client.get(api_url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_connected'])
        self.assertEqual(data['leads_fetched'], 5)
        self.assertIn("Arun Kumar", data['html'])
        self.assertIn("Priya", data['html'])
        self.assertIn("Karthik", data['html'])
        self.assertIn("Vijay", data['html'])
        self.assertIn("Siva", data['html'])
        self.assertIn("98765xxxxx", data['html'])
        self.assertIn("Ravi", data['html'])

    def test_telecaller_ravi_login_and_assigned_leads(self):
        """
        Section 8:
        Telecaller Login: Ravi
        MY LEADS
        Automatically Assigned Leads

        Name | Phone | Branch | Status
        Arun Kumar | 9876543210 | T. Nagar | New
        Vijay | 9987654321 | T. Nagar | New
        Siva | 9876123456 | T. Nagar | Follow-up

        Total Assigned Leads: 3

        Telecallers must not see leads assigned to other Telecallers.
        """
        # Ensure leads are seeded via connect
        self.client.login(username='admin_p7', password='AdminPassword@2026')
        self.client.post(reverse('admin_google_form_connect'), {
            'name': 'Campaign',
            'form_url': 'https://docs.google.com/forms/d/e/1FAIpQLScXtest/viewform'
        })
        self.client.logout()

        # Telecaller Ravi login
        ravi = User.objects.get(username='ravi_tc')
        ravi.set_password('RaviPass@2026')
        ravi.save()

        login_success = self.client.login(username='ravi_tc', password='RaviPass@2026')
        self.assertTrue(login_success)

        res = self.client.get(reverse('telecaller_leads_list'))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # Header and subtitles
        self.assertIn("MY LEADS", content)
        self.assertIn("Automatically Assigned Leads", content)
        self.assertIn("Total Assigned Leads: 3", content)

        # Ravi's 3 assigned leads
        self.assertIn("Arun Kumar", content)
        self.assertIn("Vijay", content)
        self.assertIn("Siva", content)
        self.assertIn("9876543210", content)
        self.assertIn("9987654321", content)
        self.assertIn("9876123456", content)
        self.assertIn("T. Nagar", content)

        # Telecallers must NOT see leads assigned to other Telecallers (Meena, Suresh)
        self.assertNotIn("Priya", content)
        self.assertNotIn("Karthik", content)
        self.assertNotIn("9123456780", content)
        self.assertNotIn("9988776655", content)
