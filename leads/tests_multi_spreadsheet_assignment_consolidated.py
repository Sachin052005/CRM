from io import StringIO
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.core.management import call_command
from django.utils import timezone
from accounts.models import User, UserRole
from branches.models import Branch
from channels.models import Channel
from products.models import Product
from followups.models import FollowUp, FollowUpStatus
from leads.models import (
    Lead,
    LeadStatus,
    GoogleSheetConnection,
    GoogleSheetRowMapping,
    GoogleSheetSyncHistory,
    TelecallerLeadSetup,
    LeadSetupConfig,
    AssignmentMethod,
    DuplicateLeadRecord
)
from leads.assignment import assign_new_lead, retry_pending_assignments
from leads.google_sheets import (
    sync_google_sheet,
    sync_all_active_spreadsheets,
    normalize_phone,
    normalize_email
)


class MultiSpreadsheetAssignmentConsolidatedTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Clean existing test data if any
        TelecallerLeadSetup.objects.all().delete()
        Lead.objects.all().delete()
        GoogleSheetConnection.objects.all().delete()

        # Branches
        self.branch_a, _ = Branch.objects.get_or_create(name="T. Nagar", defaults={'status': "Active"})
        self.branch_b, _ = Branch.objects.get_or_create(name="Velachery", defaults={'status': "Active"})

        # Channel & Product
        self.channel_offline, _ = Channel.objects.get_or_create(name="Offline Leads", defaults={'status': "Active"})
        self.channel_social, _ = Channel.objects.get_or_create(name="Instagram & Facebook", defaults={'status': "Active"})
        self.product_python, _ = Product.objects.get_or_create(name="Python Full Stack", defaults={'price': 30000, 'status': "Active"})

        # Admin user
        self.admin_user, _ = User.objects.get_or_create(
            username="admin_test",
            defaults={
                'email': "admin@techpanda.com",
                'role': UserRole.ADMIN
            }
        )
        self.admin_user.set_password("TechPanda@2026")
        self.admin_user.save()

        # Telecallers for Branch A
        self.tc_a1, _ = User.objects.get_or_create(
            username="ravi_tc",
            defaults={
                'first_name': "Ravi",
                'email': "ravi@techpanda.com",
                'role': UserRole.TELECALLER,
                'branch': self.branch_a,
                'is_active': True
            }
        )
        self.tc_a1.branch = self.branch_a
        self.tc_a1.set_password("TechPanda@2026")
        self.tc_a1.save()

        self.tc_a2, _ = User.objects.get_or_create(
            username="suresh_tc",
            defaults={
                'first_name': "Suresh",
                'email': "suresh@techpanda.com",
                'role': UserRole.TELECALLER,
                'branch': self.branch_a,
                'is_active': True
            }
        )
        self.tc_a2.branch = self.branch_a
        self.tc_a2.set_password("TechPanda@2026")
        self.tc_a2.save()

        # Telecallers for Branch B
        self.tc_b1, _ = User.objects.get_or_create(
            username="priya_tc",
            defaults={
                'first_name': "Priya",
                'email': "priya@techpanda.com",
                'role': UserRole.TELECALLER,
                'branch': self.branch_b,
                'is_active': True
            }
        )
        self.tc_b1.branch = self.branch_b
        self.tc_b1.set_password("TechPanda@2026")
        self.tc_b1.save()

        self.tc_b2, _ = User.objects.get_or_create(
            username="karthik_tc",
            defaults={
                'first_name': "Karthik",
                'email': "karthik@techpanda.com",
                'role': UserRole.TELECALLER,
                'branch': self.branch_b,
                'is_active': True
            }
        )
        self.tc_b2.branch = self.branch_b
        self.tc_b2.set_password("TechPanda@2026")
        self.tc_b2.save()

        # Initial Lead Setup Config
        self.config, _ = LeadSetupConfig.objects.get_or_create(
            defaults={'assignment_method': AssignmentMethod.PERCENTAGE}
        )

    # =========================================================================
    # PROBLEM 1: MULTI-SPREADSHEET IMPORT & DEDUPLICATION TESTS
    # =========================================================================

    def test_unlimited_multi_spreadsheet_connections(self):
        """
        Verify that multiple spreadsheets can be connected simultaneously without
        deactivating or overwriting existing connections.
        """
        self.client.force_login(self.admin_user)

        with patch('leads.views.fetch_sheet_data') as mock_fetch, \
             patch('leads.views.fetch_spreadsheet_metadata') as mock_meta, \
             patch('leads.views.sync_google_sheet') as mock_sync:
            mock_fetch.return_value = (['Name', 'Phone', 'Email', 'Course'], [])
            mock_meta.return_value = {'title': 'Offline Enquiries Sheet'}
            mock_sync.return_value = {'new_leads': 0, 'updated_leads': 0, 'skipped': 0, 'failed': 0, 'rows_checked': 0}

            # Connect sheet 1
            res1 = self.client.post(reverse('admin_google_sheet_connect'), {
                'spreadsheet_name': 'Offline Leads Sheet',
                'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/1VQtamlwByzXJ29hLnxZXPvQauPim361MnjWtenxnEKQ/edit',
            })
            self.assertEqual(res1.status_code, 200)

            # Connect sheet 2
            mock_meta.return_value = {'title': 'Instagram Campaigns Sheet'}
            res2 = self.client.post(reverse('admin_google_sheet_connect'), {
                'spreadsheet_name': 'Instagram Leads Sheet',
                'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/1bYHCxtWY15x9AMn1cmRT0AkiSEXyBafbgAGEyvI-BFY/edit',
            })
            self.assertEqual(res2.status_code, 200)

            # Connect sheet 3
            mock_meta.return_value = {'title': 'College Walkins Sheet'}
            res3 = self.client.post(reverse('admin_google_sheet_connect'), {
                'spreadsheet_name': 'College Walkins',
                'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/1CCollegeWalkinsSheet1234567890abcdef/edit',
            })
            self.assertEqual(res3.status_code, 200)

        # All 3 connections must remain active simultaneously
        active_conns = GoogleSheetConnection.objects.filter(is_active=True)
        self.assertEqual(active_conns.count(), 3)
        names = list(active_conns.values_list('name', flat=True))
        self.assertIn('Offline Leads Sheet', names)
        self.assertIn('Instagram Leads Sheet', names)
        self.assertIn('College Walkins', names)

    def test_phone_and_email_normalization(self):
        """
        Verify phone formatting stripping spaces, dashes, +91, 0 prefix,
        and email trimming / lowercase normalization.
        """
        self.assertEqual(normalize_phone("+91 98765 43210"), "9876543210")
        self.assertEqual(normalize_phone("+91-9876543210"), "9876543210")
        self.assertEqual(normalize_phone("09876543210"), "9876543210")
        self.assertEqual(normalize_phone(" 98765-43210 "), "9876543210")
        self.assertEqual(normalize_phone("9876543210"), "9876543210")

        self.assertEqual(normalize_email("  Test.User@Example.COM  "), "test.user@example.com")

    def test_multi_spreadsheet_deduplication_consolidation(self):
        """
        When Sheet 1 imports a lead with phone 9876543210, and Sheet 2 imports a lead
        with the same phone 9876543210:
        1. A duplicate Lead record is NOT created.
        2. GoogleSheetRowMapping for Sheet 2 is attached to the existing lead.
        3. Existing assigned telecaller and status are preserved.
        4. Secondary branch is registered if different.
        """
        # Configure Branch A allocation to 100%
        TelecallerLeadSetup.objects.create(
            telecaller=self.tc_a1, branch=self.branch_a, assignment_percentage=100, is_active=True
        )

        conn1 = GoogleSheetConnection.objects.create(
            name="Offline Leads Sheet",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/11111111111111111111111111111111111111111111/edit",
            spreadsheet_id="11111111111111111111111111111111111111111111",
            worksheet_name="Sheet1",
            channel=self.channel_offline,
            branch=self.branch_a,
            is_active=True
        )

        conn2 = GoogleSheetConnection.objects.create(
            name="Social Media Sheet",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/22222222222222222222222222222222222222222222/edit",
            spreadsheet_id="22222222222222222222222222222222222222222222",
            worksheet_name="Sheet1",
            channel=self.channel_social,
            branch=self.branch_b,
            is_active=True
        )

        sheet1_headers = ['Student Name', 'Mobile Number', 'Email ID', 'Course']
        sheet1_rows = [
            ['Anand Kumar', '+91 98765 43210', 'anand@gmail.com', 'Python Full Stack']
        ]

        sheet2_headers = ['Full Name', 'Contact Phone', 'Email', 'Preferred Branch']
        sheet2_rows = [
            ['Anand K', '9876543210', 'anand@gmail.com', 'Velachery']
        ]

        # Sync Sheet 1
        with patch('leads.google_sheets.fetch_sheet_data', return_value=(sheet1_headers, sheet1_rows)):
            res1 = sync_google_sheet(conn1)
            self.assertEqual(res1['new_leads'], 1)

        self.assertEqual(Lead.objects.count(), 1)
        lead = Lead.objects.first()
        self.assertEqual(lead.phone, "9876543210")
        self.assertEqual(lead.assigned_telecaller, self.tc_a1)
        self.assertEqual(lead.branch, self.branch_a)
        self.assertEqual(lead.assignment_status, 'Assigned')

        # Sync Sheet 2 (has the exact same phone)
        with patch('leads.google_sheets.fetch_sheet_data', return_value=(sheet2_headers, sheet2_rows)):
            res2 = sync_google_sheet(conn2)
            self.assertEqual(res2['new_leads'], 0)
            self.assertEqual(res2['updated_leads'], 1)

        # Still strictly 1 unique lead in CRM database!
        self.assertEqual(Lead.objects.count(), 1)
        lead.refresh_from_db()

        # Telecaller remains preserved
        self.assertEqual(lead.assigned_telecaller, self.tc_a1)

        # Both connections mapped to this lead
        mappings = GoogleSheetRowMapping.objects.filter(lead=lead)
        self.assertEqual(mappings.count(), 2)
        conn_ids = list(mappings.values_list('connection_id', flat=True))
        self.assertIn(conn1.id, conn_ids)
        self.assertIn(conn2.id, conn_ids)

        # Secondary branch registered
        self.assertIn("Velachery", lead.get_all_branch_names())

    def test_disconnect_preserves_leads(self):
        """
        Disconnecting a spreadsheet marks it inactive but keeps all imported leads preserved.
        """
        self.client.force_login(self.admin_user)
        conn = GoogleSheetConnection.objects.create(
            name="Test Sheet",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/33333333333333333333333333333333333333333333/edit",
            spreadsheet_id="33333333333333333333333333333333333333333333",
            is_active=True
        )
        lead = Lead.objects.create(
            name="Keerthi",
            phone="9123456780",
            source="Test Sheet",
            is_offline=True
        )
        GoogleSheetRowMapping.objects.create(
            connection=conn,
            lead=lead,
            row_identifier="row_2",
            row_index=2
        )

        res = self.client.post(reverse('admin_google_sheet_disconnect', args=[conn.id]))
        self.assertEqual(res.status_code, 200)

        conn.refresh_from_db()
        self.assertFalse(conn.is_active)
        self.assertEqual(conn.last_sync_status, 'Disconnected')

        # Lead is PRESERVED
        self.assertTrue(Lead.objects.filter(pk=lead.pk).exists())

    # =========================================================================
    # PROBLEM 2: TELECALLER CHECKBOXES & STRICT 100% ALLOCATION TESTS
    # =========================================================================

    def test_allocation_strict_100_percent_accepted(self):
        """
        Sum of checked telecallers equals exactly 100%:
        Accepted, saved atomically to database.
        """
        self.client.force_login(self.admin_user)

        res = self.client.post(reverse('admin_lead_setup'), {
            'action': 'save_branch_allocation',
            'branch_id': self.branch_a.id,
            'active_telecallers': [self.tc_a1.id, self.tc_a2.id],
            f'percentage_{self.tc_a1.id}': 60,
            f'percentage_{self.tc_a2.id}': 40,
            f'lead_count_{self.tc_a1.id}': 60,
            f'lead_count_{self.tc_a2.id}': 40,
        })
        self.assertEqual(res.status_code, 302)

        s1 = TelecallerLeadSetup.objects.get(telecaller=self.tc_a1, branch=self.branch_a)
        s2 = TelecallerLeadSetup.objects.get(telecaller=self.tc_a2, branch=self.branch_a)
        self.assertTrue(s1.is_active)
        self.assertEqual(s1.assignment_percentage, 60)
        self.assertTrue(s2.is_active)
        self.assertEqual(s2.assignment_percentage, 40)

    def test_allocation_less_than_100_percent_rejected(self):
        """
        Sum < 100% (e.g. 50% + 40% = 90%):
        Rejected with clear error message; not saved to database.
        """
        self.client.force_login(self.admin_user)

        res = self.client.post(
            reverse('admin_lead_setup'),
            {
                'action': 'save_branch_allocation',
                'branch_id': self.branch_a.id,
                'active_telecallers': [self.tc_a1.id, self.tc_a2.id],
                f'percentage_{self.tc_a1.id}': 50,
                f'percentage_{self.tc_a2.id}': 40,
            },
            headers={'x-requested-with': 'XMLHttpRequest'}
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data['success'])
        self.assertIn("90%", data['error'])
        self.assertIn("100%", data['error'])

    def test_allocation_greater_than_100_percent_rejected(self):
        """
        Sum > 100% (e.g. 70% + 40% = 110%):
        Rejected with clear error message; not saved to database.
        """
        self.client.force_login(self.admin_user)

        res = self.client.post(
            reverse('admin_lead_setup'),
            {
                'action': 'save_branch_allocation',
                'branch_id': self.branch_a.id,
                'active_telecallers': [self.tc_a1.id, self.tc_a2.id],
                f'percentage_{self.tc_a1.id}': 70,
                f'percentage_{self.tc_a2.id}': 40,
            },
            headers={'x-requested-with': 'XMLHttpRequest'}
        )
        self.assertEqual(res.status_code, 400)
        data = res.json()
        self.assertFalse(data['success'])
        self.assertIn("110%", data['error'])
        self.assertIn("100%", data['error'])

    def test_unchecked_telecaller_excluded_from_allocation(self):
        """
        When a telecaller is unchecked, they must be set to is_active=False
        and their percentage does not count towards the 100% total.
        """
        self.client.force_login(self.admin_user)

        # Initial setup: both active
        TelecallerLeadSetup.objects.create(
            telecaller=self.tc_a1, branch=self.branch_a, assignment_percentage=50, is_active=True
        )
        TelecallerLeadSetup.objects.create(
            telecaller=self.tc_a2, branch=self.branch_a, assignment_percentage=50, is_active=True
        )

        # Now submit only tc_a1 checked with 100%, tc_a2 not in active_telecallers
        res = self.client.post(reverse('admin_lead_setup'), {
            'action': 'save_branch_allocation',
            'branch_id': self.branch_a.id,
            'active_telecallers': [self.tc_a1.id],
            f'percentage_{self.tc_a1.id}': 100,
            f'lead_count_{self.tc_a1.id}': 100,
        })
        self.assertEqual(res.status_code, 302)

        s1 = TelecallerLeadSetup.objects.get(telecaller=self.tc_a1, branch=self.branch_a)
        s2 = TelecallerLeadSetup.objects.get(telecaller=self.tc_a2, branch=self.branch_a)

        self.assertTrue(s1.is_active)
        self.assertEqual(s1.assignment_percentage, 100)

        # tc_a2 is excluded
        self.assertFalse(s2.is_active)
        self.assertEqual(s2.assignment_percentage, 0)

    # =========================================================================
    # PROBLEM 3: AUTOMATIC CONTINUOUS ASSIGNMENT ENGINE TESTS
    # =========================================================================

    def test_weighted_gap_distribution_50_30_20(self):
        """
        Verify that 10 incoming leads are distributed strictly according
        to 50% vs 30% vs 20% allocation using the largest allocation gap rule.
        """
        # Create third telecaller for Branch A
        tc_a3 = User.objects.create_user(
            username="meena_tc", first_name="Meena", password="pwd",
            role=UserRole.TELECALLER, branch=self.branch_a, is_active=True
        )

        TelecallerLeadSetup.objects.create(
            telecaller=self.tc_a1, branch=self.branch_a, assignment_percentage=50, is_active=True
        )
        TelecallerLeadSetup.objects.create(
            telecaller=self.tc_a2, branch=self.branch_a, assignment_percentage=30, is_active=True
        )
        TelecallerLeadSetup.objects.create(
            telecaller=tc_a3, branch=self.branch_a, assignment_percentage=20, is_active=True
        )

        assigned_counts = {self.tc_a1.id: 0, self.tc_a2.id: 0, tc_a3.id: 0}

        for i in range(10):
            lead = Lead.objects.create(
                name=f"Student {i+1}",
                phone=f"900000000{i}",
                branch=self.branch_a,
                source="Offline Leads"
            )
            success = assign_new_lead(lead, branch=self.branch_a)
            self.assertTrue(success)
            lead.refresh_from_db()
            tc = lead.assigned_telecaller
            self.assertIsNotNone(tc)
            assigned_counts[tc.id] += 1

        # Exactly 50% (5 leads), 30% (3 leads), 20% (2 leads)
        self.assertEqual(assigned_counts[self.tc_a1.id], 5)
        self.assertEqual(assigned_counts[self.tc_a2.id], 3)
        self.assertEqual(assigned_counts[tc_a3.id], 2)

    def test_branch_isolation_in_assignment(self):
        """
        A lead for Branch B (Velachery) must NEVER be assigned to a Branch A (T. Nagar) telecaller.
        """
        TelecallerLeadSetup.objects.create(
            telecaller=self.tc_a1, branch=self.branch_a, assignment_percentage=100, is_active=True
        )
        TelecallerLeadSetup.objects.create(
            telecaller=self.tc_b1, branch=self.branch_b, assignment_percentage=100, is_active=True
        )

        lead_b = Lead.objects.create(
            name="Velachery Student",
            phone="9871112233",
            branch=self.branch_b,
            source="Offline Leads"
        )
        success = assign_new_lead(lead_b, branch=self.branch_b)
        self.assertTrue(success)
        lead_b.refresh_from_db()
        self.assertEqual(lead_b.assigned_telecaller, self.tc_b1)
        self.assertNotEqual(lead_b.assigned_telecaller, self.tc_a1)

    def test_pending_assignment_when_branch_unconfigured_and_retry(self):
        """
        When branch allocation does not equal 100%:
        - Lead is marked 'Pending Assignment' with clear reason.
        - Application does NOT crash.
        - Once branch is configured to 100%, retry_pending_assignments automatically assigns it.
        """
        # Branch B has NO setups configured yet
        lead_pending = Lead.objects.create(
            name="Unassigned Student",
            phone="9879998877",
            branch=self.branch_b,
            source="Offline Leads"
        )
        success = assign_new_lead(lead_pending, branch=self.branch_b)
        self.assertFalse(success)
        lead_pending.refresh_from_db()
        self.assertIsNone(lead_pending.assigned_telecaller)

        lead_pending.refresh_from_db()
        self.assertEqual(lead_pending.assignment_status, 'Pending Assignment')
        self.assertIn("allocation", lead_pending.pending_assignment_reason.lower())

        # Now configure Branch B allocation to 100% (Priya 60%, Karthik 40%)
        TelecallerLeadSetup.objects.create(
            telecaller=self.tc_b1, branch=self.branch_b, assignment_percentage=60, is_active=True
        )
        TelecallerLeadSetup.objects.create(
            telecaller=self.tc_b2, branch=self.branch_b, assignment_percentage=40, is_active=True
        )

        # Retry pending assignments
        assigned, remaining = retry_pending_assignments(branch=self.branch_b, user=self.admin_user)
        self.assertEqual(assigned, 1)
        self.assertEqual(remaining, 0)

        lead_pending.refresh_from_db()
        self.assertEqual(lead_pending.assignment_status, 'Assigned')
        self.assertIsNotNone(lead_pending.assigned_telecaller)
        self.assertIn(lead_pending.assigned_telecaller, [self.tc_b1, self.tc_b2])

    # =========================================================================
    # PROBLEM 4: TELECALLER LOGIN VISIBILITY & 403 FORBIDDEN TESTS
    # =========================================================================

    def test_telecaller_leads_list_scoped_strictly(self):
        """
        Telecaller sees ONLY leads assigned to their account on /telecaller/leads/.
        """
        # Assign lead 1 to tc_a1, lead 2 to tc_a2
        lead1 = Lead.objects.create(
            name="Lead for Ravi",
            phone="9811111111",
            branch=self.branch_a,
            assigned_telecaller=self.tc_a1,
            assignment_status='Assigned'
        )
        lead2 = Lead.objects.create(
            name="Lead for Suresh",
            phone="9822222222",
            branch=self.branch_a,
            assigned_telecaller=self.tc_a2,
            assignment_status='Assigned'
        )

        # Log in as Ravi
        self.client.force_login(self.tc_a1)
        res = self.client.get(reverse('telecaller_leads_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Lead for Ravi")
        self.assertNotContains(res, "Lead for Suresh")

    def test_telecaller_unauthorized_lead_access_returns_403(self):
        """
        When telecaller attempts to access another telecaller's lead:
        Returns HTTP 403 Forbidden.
        """
        lead_suresh = Lead.objects.create(
            name="Lead for Suresh",
            phone="9822222222",
            branch=self.branch_a,
            assigned_telecaller=self.tc_a2,
            assignment_status='Assigned'
        )

        # Ravi tries to view Suresh's lead
        self.client.force_login(self.tc_a1)
        res_detail = self.client.get(reverse('telecaller_lead_detail', args=[lead_suresh.pk]))
        self.assertEqual(res_detail.status_code, 403)

        # Ravi tries to edit Suresh's lead
        res_edit = self.client.get(reverse('telecaller_lead_edit', args=[lead_suresh.pk]))
        self.assertEqual(res_edit.status_code, 403)

    def test_telecaller_unauthorized_followup_returns_403(self):
        """
        When telecaller attempts to modify another telecaller's follow-up:
        Returns HTTP 403 Forbidden.
        """
        lead_suresh = Lead.objects.create(
            name="Lead for Suresh",
            phone="9822222222",
            branch=self.branch_a,
            assigned_telecaller=self.tc_a2,
            assignment_status='Assigned'
        )
        followup = FollowUp.objects.create(
            lead=lead_suresh,
            telecaller=self.tc_a2,
            status=FollowUpStatus.PENDING,
            follow_up_date=timezone.now().date(),
            follow_up_time=timezone.now().time()
        )

        self.client.force_login(self.tc_a1)
        res = self.client.post(reverse('update_followup_status', args=[followup.pk, 'Completed']))
        self.assertEqual(res.status_code, 403)

    # =========================================================================
    # PROBLEM 5: ADMIN CONSOLIDATED ALL LEADS TESTS
    # =========================================================================

    def test_admin_leads_list_consolidation_and_filters(self):
        """
        Verify /admin/leads/ consolidates all leads, displays source spreadsheet badges,
        and accurately filters by Spreadsheet, Branch, Assignment Status, and Date.
        """
        conn_off = GoogleSheetConnection.objects.create(
            name="Offline Campaigns",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/off123/edit",
            spreadsheet_id="off123",
            is_active=True
        )
        conn_soc = GoogleSheetConnection.objects.create(
            name="Social Inquiries",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/soc456/edit",
            spreadsheet_id="soc456",
            is_active=True
        )

        # Lead from Offline Campaigns
        l1 = Lead.objects.create(
            name="Ramesh",
            phone="9800000001",
            branch=self.branch_a,
            source="Offline Campaigns",
            assignment_status='Assigned',
            assigned_telecaller=self.tc_a1
        )
        GoogleSheetRowMapping.objects.create(connection=conn_off, lead=l1, row_identifier="r1", row_index=2)

        # Lead from Social Inquiries
        l2 = Lead.objects.create(
            name="Sita",
            phone="9800000002",
            branch=self.branch_b,
            source="Social Inquiries",
            assignment_status='Pending Assignment',
            pending_assignment_reason="Branch Velachery allocation != 100%"
        )
        GoogleSheetRowMapping.objects.create(connection=conn_soc, lead=l2, row_identifier="r2", row_index=2)

        # Manual Lead
        l3 = Lead.objects.create(
            name="Deepak",
            phone="9800000003",
            branch=self.branch_a,
            source="Manual Entry",
            assignment_status='Unassigned'
        )

        self.client.force_login(self.admin_user)

        # 1. Total Distinct Leads: 3
        res_all = self.client.get(reverse('admin_leads_list'))
        self.assertEqual(res_all.status_code, 200)
        self.assertEqual(res_all.context['page_obj'].paginator.count, 3)
        self.assertContains(res_all, "Offline Campaigns")
        self.assertContains(res_all, "Social Inquiries")
        self.assertContains(res_all, "Pending")

        # 2. Filter by Source Spreadsheet (Offline Campaigns)
        res_sheet = self.client.get(reverse('admin_leads_list'), {'spreadsheet': conn_off.id})
        self.assertEqual(res_sheet.context['page_obj'].paginator.count, 1)
        self.assertEqual(res_sheet.context['page_obj'][0].name, "Ramesh")

        # 3. Filter by Assignment Status (Pending Assignment)
        res_pending = self.client.get(reverse('admin_leads_list'), {'assignment_status': 'Pending Assignment'})
        self.assertEqual(res_pending.context['page_obj'].paginator.count, 1)
        self.assertEqual(res_pending.context['page_obj'][0].name, "Sita")

        # 4. Filter by Branch (Branch A)
        res_branch = self.client.get(reverse('admin_leads_list'), {'branch': self.branch_a.id})
        self.assertEqual(res_branch.context['page_obj'].paginator.count, 2)
