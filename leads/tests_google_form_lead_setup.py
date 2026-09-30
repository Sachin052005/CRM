from datetime import timedelta
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, UserRole
from branches.models import Branch
from channels.models import Channel
from leads.models import (
    Lead, LeadStatus, GoogleFormConnection, LeadSetupConfig,
    TelecallerLeadSetup, DuplicateLeadRecord, AssignmentMethod
)
from leads.assignment import assign_lead_to_branch_telecaller
from leads.duplicates import process_incoming_lead_with_10day_rule


class GoogleFormAndLeadSetupTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Create Admin
        self.admin_user, _ = User.objects.get_or_create(
            username='admin_test',
            defaults={
                'email': 'admin@test.com',
                'role': UserRole.ADMIN,
                'is_superuser': True,
                'is_staff': True
            }
        )
        self.admin_user.set_password('TechPanda@2026')
        self.admin_user.save()

        # Create Branches
        self.branch_tnagar, _ = Branch.objects.get_or_create(name='T. Nagar', defaults={'status': 'Active'})
        self.branch_velachery, _ = Branch.objects.get_or_create(name='Velachery', defaults={'status': 'Active'})
        self.branch_tambaram, _ = Branch.objects.get_or_create(name='Tambaram', defaults={'status': 'Active'})

        # Create Telecallers in T. Nagar
        self.tc_ravi, _ = User.objects.get_or_create(
            username='ravi_tc',
            defaults={
                'first_name': 'Ravi',
                'role': UserRole.TELECALLER,
                'branch': self.branch_tnagar
            }
        )
        self.tc_ravi.branch = self.branch_tnagar
        self.tc_ravi.set_password('TechPanda@2026')
        self.tc_ravi.save()

        self.tc_meena, _ = User.objects.get_or_create(
            username='meena_tc',
            defaults={
                'first_name': 'Meena',
                'role': UserRole.TELECALLER,
                'branch': self.branch_tnagar
            }
        )
        self.tc_meena.branch = self.branch_tnagar
        self.tc_meena.set_password('TechPanda@2026')
        self.tc_meena.save()

        self.tc_suresh, _ = User.objects.get_or_create(
            username='suresh_tc',
            defaults={
                'first_name': 'Suresh',
                'role': UserRole.TELECALLER,
                'branch': self.branch_tnagar
            }
        )
        self.tc_suresh.branch = self.branch_tnagar
        self.tc_suresh.set_password('TechPanda@2026')
        self.tc_suresh.save()

        # Create Telecallers in Velachery
        self.tc_priya, _ = User.objects.get_or_create(
            username='priya_tc',
            defaults={
                'first_name': 'Priya',
                'role': UserRole.TELECALLER,
                'branch': self.branch_velachery
            }
        )
        self.tc_priya.branch = self.branch_velachery
        self.tc_priya.set_password('TechPanda@2026')
        self.tc_priya.save()

        self.tc_karthik, _ = User.objects.get_or_create(
            username='karthik_tc',
            defaults={
                'first_name': 'Karthik',
                'role': UserRole.TELECALLER,
                'branch': self.branch_velachery
            }
        )
        self.tc_karthik.branch = self.branch_velachery
        self.tc_karthik.set_password('TechPanda@2026')
        self.tc_karthik.save()

        # Create Channel
        self.channel, _ = Channel.objects.get_or_create(name='Google Form', defaults={'status': 'Active'})

        # Log in Admin
        self.client.force_login(self.admin_user)

    def test_google_form_connect_without_authentication(self):
        """
        Test connecting Google Form using only URL with zero Google authentication.
        """
        form_url = 'https://docs.google.com/forms/d/e/1FAIpQLSc_test123/viewform'
        response = self.client.post(reverse('admin_google_form_connect'), {
            'form_url': form_url
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('Leads will be fetched automatically', data['message'])

        conn = GoogleFormConnection.objects.first()
        self.assertIsNotNone(conn)
        self.assertTrue(conn.is_active)
        self.assertEqual(conn.form_url, form_url)
        self.assertEqual(conn.last_sync_status, 'Connected')

    def test_google_form_disconnect(self):
        """
        Test disconnecting active Google Form connection.
        """
        GoogleFormConnection.objects.create(
            name='Google Form Leads',
            form_url='https://docs.google.com/forms/d/e/123/viewform',
            is_active=True
        )

        response = self.client.post(reverse('admin_google_form_disconnect'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        conn = GoogleFormConnection.objects.first()
        self.assertFalse(conn.is_active)

    def test_offline_leads_live_sync_api(self):
        """
        Test that offline leads data API returns 3-second live updates metadata.
        """
        GoogleFormConnection.objects.create(
            name='Google Form Leads',
            form_url='https://docs.google.com/forms/d/e/123/viewform',
            is_active=True
        )

        response = self.client.get(reverse('admin_offline_leads_data_api'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['google_form_connected'])
        self.assertEqual(data['google_form_url'], 'https://docs.google.com/forms/d/e/123/viewform')
        self.assertIn('timestamp', data)

    def test_branch_telecaller_assignment_strict_isolation(self):
        """
        Verify that a lead for T. Nagar is NEVER assigned to a Velachery Telecaller.
        """
        # Configure T. Nagar setups
        TelecallerLeadSetup.objects.create(
            telecaller=self.tc_ravi,
            branch=self.branch_tnagar,
            assignment_percentage=50,
            lead_count=50,
            is_active=True
        )
        TelecallerLeadSetup.objects.create(
            telecaller=self.tc_meena,
            branch=self.branch_tnagar,
            assignment_percentage=50,
            lead_count=50,
            is_active=True
        )

        lead = Lead.objects.create(
            name='Ramesh',
            phone='9840112233',
            branch=self.branch_tnagar
        )

        assign_lead_to_branch_telecaller(lead, branch=self.branch_tnagar)
        lead.refresh_from_db()

        self.assertIn(lead.assigned_telecaller, [self.tc_ravi, self.tc_meena])
        self.assertNotEqual(lead.assigned_telecaller, self.tc_priya)
        self.assertNotEqual(lead.assigned_telecaller, self.tc_karthik)

    def test_duplicate_lead_10_day_rule_within_10_days(self):
        """
        If the same lead submits details through one branch and the same lead details
        are found in another branch within 10 days, treat as duplicate.
        Do NOT create a normal lead record. Store duplicate info in DuplicateLeadRecord.
        """
        # 1. Lead submitted in Branch A (T. Nagar)
        original_lead, is_dup1, _ = process_incoming_lead_with_10day_rule(
            lead_data={
                'name': 'Arun Kumar',
                'phone': '9876543210',
                'email': 'arun@example.com',
                'status': 'Interested'
            },
            branch=self.branch_tnagar
        )
        self.assertFalse(is_dup1)
        self.assertEqual(original_lead.branch, self.branch_tnagar)

        # 2. Same lead submits in Branch B (Velachery) 2 days later (within 10 days)
        lead_result, is_dup2, dup_rec = process_incoming_lead_with_10day_rule(
            lead_data={
                'name': 'Arun Kumar',
                'phone': '9876543210',
                'email': 'arun@example.com',
                'status': 'New'
            },
            branch=self.branch_velachery
        )

        self.assertTrue(is_dup2)
        self.assertIsNotNone(dup_rec)
        self.assertEqual(dup_rec.original_lead, original_lead)
        self.assertEqual(dup_rec.branch, self.branch_velachery)

        # Total normal leads count for Arun Kumar should remain 1
        leads_count = Lead.objects.filter(phone='9876543210').count()
        self.assertEqual(leads_count, 1)

    def test_duplicate_lead_10_day_rule_after_10_days(self):
        """
        If the same lead submits through another branch after 10 days,
        treat submission as a valid new lead.
        """
        # 1. Original lead created 15 days ago
        original_lead = Lead.objects.create(
            name='Arun Kumar',
            phone='9876543210',
            email='arun@example.com',
            branch=self.branch_tnagar,
            created_at=timezone.now() - timedelta(days=15)
        )
        # Manually overwrite auto_now_add for test
        Lead.objects.filter(id=original_lead.id).update(created_at=timezone.now() - timedelta(days=15))
        original_lead.refresh_from_db()

        # 2. Same lead submits 15 days later in Velachery
        new_lead, is_dup, dup_rec = process_incoming_lead_with_10day_rule(
            lead_data={
                'name': 'Arun Kumar',
                'phone': '9876543210',
                'email': 'arun@example.com'
            },
            branch=self.branch_velachery
        )

        self.assertFalse(is_dup)
        self.assertIsNone(dup_rec)
        self.assertNotEqual(new_lead.id, original_lead.id)
        self.assertEqual(new_lead.branch, self.branch_velachery)

        # Should now have 2 normal leads
        self.assertEqual(Lead.objects.filter(phone='9876543210').count(), 2)

    def test_view_duplicate_info_modal_endpoint(self):
        """
        Test the [ View Duplicate ] JSON endpoint returning original + duplicate details.
        """
        lead = Lead.objects.create(
            name='Arun Kumar',
            phone='9876543210',
            email='arun@example.com',
            branch=self.branch_tnagar,
            status=LeadStatus.INTERESTED
        )
        DuplicateLeadRecord.objects.create(
            original_lead=lead,
            name='Arun Kumar',
            phone='9876543210',
            email='arun@example.com',
            branch=self.branch_velachery,
            branch_name='Velachery',
            notes='Same lead details detected within 10 days.'
        )

        response = self.client.get(reverse('admin_lead_duplicate_info', args=[lead.pk]))
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertTrue(data['success'])
        self.assertEqual(data['lead']['name'], 'Arun Kumar')
        self.assertEqual(data['lead']['branch'], 'T. Nagar')
        self.assertEqual(len(data['duplicate_records']), 1)
        self.assertEqual(data['duplicate_records'][0]['branch'], 'Velachery')
        self.assertIn('Same lead details detected within 10 days.', data['duplicate_records'][0]['notes'])

    def test_lead_setup_page_and_configuration(self):
        """
        Test Settings -> Lead Setup page, assignment method update and rule saving.
        """
        response = self.client.get(reverse('admin_lead_setup'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'LEAD SETUP')
        self.assertContains(response, 'ASSIGNMENT METHOD')
        self.assertContains(response, 'Percentage Based')
        self.assertContains(response, 'Number Of Leads Based')

        # Update method to COUNT
        post_res = self.client.post(reverse('admin_lead_setup'), {
            'action': 'update_method',
            'assignment_method': 'COUNT'
        })
        self.assertEqual(post_res.status_code, 302)
        config = LeadSetupConfig.objects.first()
        self.assertEqual(config.assignment_method, AssignmentMethod.COUNT)

        # Save assignment for a telecaller
        post_save = self.client.post(reverse('admin_lead_setup'), {
            'action': 'save_assignment',
            'branch_id': self.branch_tnagar.id,
            'telecaller_id': self.tc_ravi.id,
            'assignment_percentage': 45,
            'lead_count': 60
        })
        self.assertEqual(post_save.status_code, 302)

        setup = TelecallerLeadSetup.objects.get(telecaller=self.tc_ravi, branch=self.branch_tnagar)
        self.assertEqual(setup.assignment_percentage, 45)
        self.assertEqual(setup.lead_count, 60)

    def test_extra_telecaller_handling(self):
        """
        Verify that adding a new Telecaller to a branch automatically makes them
        available in Settings -> Lead Setup.
        """
        new_tc = User.objects.create_user(
            username='new_staff_tc',
            first_name='Staff Member',
            role=UserRole.TELECALLER,
            branch=self.branch_tnagar,
            password='TechPanda@2026'
        )

        response = self.client.get(reverse('admin_lead_setup'))
        self.assertEqual(response.status_code, 200)

        # Check TelecallerLeadSetup was automatically created
        setup_exists = TelecallerLeadSetup.objects.filter(telecaller=new_tc, branch=self.branch_tnagar).exists()
        self.assertTrue(setup_exists)
