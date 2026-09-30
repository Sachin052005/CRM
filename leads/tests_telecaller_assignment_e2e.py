from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, UserRole
from branches.models import Branch
from channels.models import Channel
from products.models import Product
from calls.models import CallHistory
from followups.models import FollowUp
from leads.models import (
    Lead,
    LeadStatus,
    TelecallerLeadSetup,
    LeadSetupConfig,
    AssignmentMethod
)
from leads.assignment import assign_new_lead, apply_branch_lead_distribution


class TelecallerLeadAssignmentE2ETestCase(TestCase):
    """
    End-to-End Test Suite for Telecaller Lead Assignment:
    1. Admin creates telecallers with credentials & verify login.
    2. Admin configures lead assignment percentage (e.g. Arun 40%, Priya 35%, Karthik 25%).
    3. Strict 100% percentage validation (rejection of non-100%).
    4. 100 leads batch distribution to exact percentage quotas.
    5. Admin leads table displays telecaller assignments.
    6. Telecaller login -> My Leads & Dashboard isolation (40, 35, 25).
    7. Cross-telecaller data access authorization check (HTTP 403 Forbidden).
    8. Proportional distribution for subsequent incoming leads.
    9. Protected leads safety (leads with calls/followups/in-progress status are preserved).
    """

    def setUp(self):
        self.client = Client()

        # Clean any preexisting setup or leads
        TelecallerLeadSetup.objects.all().delete()
        Lead.objects.all().delete()

        # Create branch
        self.branch = Branch.objects.create(name="Chennai Main", status="Active")
        self.channel = Channel.objects.create(name="Direct Walk-in", status="Active")
        self.product = Product.objects.create(name="Python Full Stack", price=35000, status="Active")

        # Create Admin
        self.admin_user = User.objects.create_user(
            username="admin_super",
            email="admin@techpanda.com",
            password="AdminPassword@2026",
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True
        )

        # Create Manager
        self.manager_user = User.objects.create_user(
            username="manager_chennai",
            email="manager@techpanda.com",
            password="ManagerPassword@2026",
            role=UserRole.MANAGER,
            branch=self.branch
        )

        # Ensure LeadSetupConfig is in PERCENTAGE mode
        self.lead_config, _ = LeadSetupConfig.objects.get_or_create(
            id=1,
            defaults={'assignment_method': AssignmentMethod.PERCENTAGE}
        )
        self.lead_config.assignment_method = AssignmentMethod.PERCENTAGE
        self.lead_config.save()

    def test_01_admin_creates_telecallers_and_login_works(self):
        """
        Admin creates telecallers via /admin/telecallers/create/ with credentials.
        Each telecaller can authenticate and log into their portal.
        """
        self.client.login(username="admin_super", password="AdminPassword@2026")

        telecaller_data = [
            ("arun_tc", "Arun", "Kumar", "arun@techpanda.com", "9876543210"),
            ("priya_tc", "Priya", "Dharshini", "priya@techpanda.com", "9876543211"),
            ("karthik_tc", "Karthik", "Raja", "karthik@techpanda.com", "9876543212"),
        ]

        for username, first, last, email, phone in telecaller_data:
            response = self.client.post(reverse('admin_telecaller_create'), {
                'first_name': first,
                'last_name': last,
                'username': username,
                'email': email,
                'phone': phone,
                'password': 'Telecaller@2026',
                'confirm_password': 'Telecaller@2026',
                'manager': self.manager_user.id,
                'branch': self.branch.id,
                'is_active': True,
            }, follow=True)
            self.assertEqual(response.status_code, 200)

            # Verify User created in DB
            user = User.objects.get(username=username)
            self.assertEqual(user.role, UserRole.TELECALLER)
            self.assertEqual(user.branch, self.branch)
            self.assertEqual(user.manager, self.manager_user)
            self.assertTrue(user.is_active)

            # Verify TelecallerLeadSetup entry was created for this telecaller
            setup_exists = TelecallerLeadSetup.objects.filter(telecaller=user, branch=self.branch).exists()
            self.assertTrue(setup_exists)

        self.client.logout()

        # Verify each telecaller can log in
        for username, _, _, _, _ in telecaller_data:
            logged_in = self.client.login(username=username, password="Telecaller@2026")
            self.assertTrue(logged_in, f"Telecaller {username} failed to log in.")
            dash_resp = self.client.get(reverse('telecaller_dashboard'))
            self.assertEqual(dash_resp.status_code, 200)
            self.client.logout()

    def _setup_three_telecallers(self):
        """Helper to create Arun, Priya, and Karthik directly."""
        self.arun = User.objects.create_user(
            username="arun_tc",
            first_name="Arun",
            last_name="Kumar",
            email="arun@techpanda.com",
            password="Telecaller@2026",
            role=UserRole.TELECALLER,
            branch=self.branch,
            manager=self.manager_user,
            is_active=True
        )
        self.priya = User.objects.create_user(
            username="priya_tc",
            first_name="Priya",
            last_name="Dharshini",
            email="priya@techpanda.com",
            password="Telecaller@2026",
            role=UserRole.TELECALLER,
            branch=self.branch,
            manager=self.manager_user,
            is_active=True
        )
        self.karthik = User.objects.create_user(
            username="karthik_tc",
            first_name="Karthik",
            last_name="Raja",
            email="karthik@techpanda.com",
            password="Telecaller@2026",
            role=UserRole.TELECALLER,
            branch=self.branch,
            manager=self.manager_user,
            is_active=True
        )

        self.setup_arun, _ = TelecallerLeadSetup.objects.get_or_create(
            telecaller=self.arun, branch=self.branch, defaults={'is_active': True, 'assignment_percentage': 0}
        )
        self.setup_priya, _ = TelecallerLeadSetup.objects.get_or_create(
            telecaller=self.priya, branch=self.branch, defaults={'is_active': True, 'assignment_percentage': 0}
        )
        self.setup_karthik, _ = TelecallerLeadSetup.objects.get_or_create(
            telecaller=self.karthik, branch=self.branch, defaults={'is_active': True, 'assignment_percentage': 0}
        )

    def test_02_lead_setup_strict_100_percent_validation(self):
        """
        Verify that allocations not summing to 100% are rejected and do not change setup.
        """
        self._setup_three_telecallers()
        self.client.login(username="admin_super", password="AdminPassword@2026")

        # Submit non-100% allocation (40 + 35 + 20 = 95%)
        post_data = {
            'action': 'save_branch_allocation',
            'branch_id': self.branch.id,
            'active_telecallers': [self.arun.id, self.priya.id, self.karthik.id],
            f'percentage_{self.arun.id}': 40,
            f'percentage_{self.priya.id}': 35,
            f'percentage_{self.karthik.id}': 20,
        }
        resp = self.client.post(reverse('admin_lead_setup'), post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        # Verify setups were not updated to invalid percentages
        self.setup_arun.refresh_from_db()
        self.assertNotEqual(self.setup_arun.assignment_percentage, 40)

        # Submit valid 100% allocation (40 + 35 + 25 = 100%)
        post_data_valid = {
            'action': 'save_branch_allocation',
            'branch_id': self.branch.id,
            'active_telecallers': [self.arun.id, self.priya.id, self.karthik.id],
            f'percentage_{self.arun.id}': 40,
            f'percentage_{self.priya.id}': 35,
            f'percentage_{self.karthik.id}': 25,
        }
        resp_valid = self.client.post(reverse('admin_lead_setup'), post_data_valid, follow=True)
        self.assertEqual(resp_valid.status_code, 200)

        self.setup_arun.refresh_from_db()
        self.setup_priya.refresh_from_db()
        self.setup_karthik.refresh_from_db()

        self.assertEqual(self.setup_arun.assignment_percentage, 40)
        self.assertEqual(self.setup_priya.assignment_percentage, 35)
        self.assertEqual(self.setup_karthik.assignment_percentage, 25)

    def test_03_end_to_end_100_leads_batch_distribution(self):
        """
        End-to-End:
        1. 100 fresh leads in branch.
        2. Configure Arun 40%, Priya 35%, Karthik 25%.
        3. Save Assignment -> Exactly 40 to Arun, 35 to Priya, 25 to Karthik.
        4. Verify DB persistence and single source of truth.
        """
        self._setup_three_telecallers()

        # Create 100 unassigned leads
        leads = [
            Lead(
                name=f"Student Candidate {i:03d}",
                phone=f"9000000{i:03d}",
                email=f"candidate{i:03d}@example.com",
                branch=self.branch,
                channel=self.channel,
                product=self.product,
                status=LeadStatus.NEW,
                assignment_status='Pending Assignment'
            )
            for i in range(1, 101)
        ]
        Lead.objects.bulk_create(leads)
        self.assertEqual(Lead.objects.filter(branch=self.branch).count(), 100)

        # Admin saves allocation via POST
        self.client.login(username="admin_super", password="AdminPassword@2026")
        post_data = {
            'action': 'save_branch_allocation',
            'branch_id': self.branch.id,
            'active_telecallers': [self.arun.id, self.priya.id, self.karthik.id],
            f'percentage_{self.arun.id}': 40,
            f'percentage_{self.priya.id}': 35,
            f'percentage_{self.karthik.id}': 25,
        }
        resp = self.client.post(reverse('admin_lead_setup'), post_data, follow=True)
        self.assertEqual(resp.status_code, 200)

        # Verify DB counts for each telecaller
        arun_count = Lead.objects.filter(assigned_telecaller=self.arun).count()
        priya_count = Lead.objects.filter(assigned_telecaller=self.priya).count()
        karthik_count = Lead.objects.filter(assigned_telecaller=self.karthik).count()

        self.assertEqual(arun_count, 40, f"Expected 40 leads for Arun, got {arun_count}")
        self.assertEqual(priya_count, 35, f"Expected 35 leads for Priya, got {priya_count}")
        self.assertEqual(karthik_count, 25, f"Expected 25 leads for Karthik, got {karthik_count}")
        self.assertEqual(arun_count + priya_count + karthik_count, 100)

        # Verify each lead has assignment_status='Assigned' and manager set
        for lead in Lead.objects.filter(branch=self.branch):
            self.assertEqual(lead.assignment_status, 'Assigned')
            self.assertEqual(lead.assigned_manager, self.manager_user)
            self.assertIsNotNone(lead.assigned_at)

        # Verify setups have current_leads_assigned counters updated
        self.setup_arun.refresh_from_db()
        self.setup_priya.refresh_from_db()
        self.setup_karthik.refresh_from_db()

        self.assertEqual(self.setup_arun.current_leads_assigned, 40)
        self.assertEqual(self.setup_priya.current_leads_assigned, 35)
        self.assertEqual(self.setup_karthik.current_leads_assigned, 25)

    def test_04_admin_leads_list_displays_assigned_telecallers(self):
        """
        Verify /admin/leads/ displays the assigned telecaller and manager for each lead.
        """
        self._setup_three_telecallers()
        self.setup_arun.assignment_percentage = 40
        self.setup_arun.is_active = True
        self.setup_arun.save()

        self.setup_priya.assignment_percentage = 35
        self.setup_priya.is_active = True
        self.setup_priya.save()

        self.setup_karthik.assignment_percentage = 25
        self.setup_karthik.is_active = True
        self.setup_karthik.save()

        # Create leads and distribute
        for i in range(1, 11):
            Lead.objects.create(
                name=f"Candidate {i}",
                phone=f"98888000{i:02d}",
                branch=self.branch,
                channel=self.channel,
                status=LeadStatus.NEW
            )
        apply_branch_lead_distribution(self.branch)

        self.client.login(username="admin_super", password="AdminPassword@2026")
        resp = self.client.get(reverse('admin_leads_list'))
        self.assertEqual(resp.status_code, 200)

        # Check table contents
        content = resp.content.decode('utf-8')
        self.assertIn("Telecaller", content)
        self.assertIn("Manager", content)
        self.assertIn("Arun", content)
        self.assertIn("Priya", content)

    def test_05_telecaller_login_and_my_leads_isolation(self):
        """
        Verify telecaller login data isolation:
        - Arun sees only Arun's 40 leads in Dashboard and My Leads.
        - Priya sees only Priya's 35 leads.
        - Karthik sees only Karthik's 25 leads.
        """
        self._setup_three_telecallers()
        self.setup_arun.assignment_percentage = 40
        self.setup_arun.is_active = True
        self.setup_arun.save()

        self.setup_priya.assignment_percentage = 35
        self.setup_priya.is_active = True
        self.setup_priya.save()

        self.setup_karthik.assignment_percentage = 25
        self.setup_karthik.is_active = True
        self.setup_karthik.save()

        # Create 100 leads and distribute
        leads = [
            Lead(
                name=f"Lead User {i:03d}",
                phone=f"9111111{i:03d}",
                branch=self.branch,
                status=LeadStatus.NEW
            )
            for i in range(1, 101)
        ]
        Lead.objects.bulk_create(leads)
        apply_branch_lead_distribution(self.branch)

        # 1. Arun's view
        self.client.login(username="arun_tc", password="Telecaller@2026")

        dash_arun = self.client.get(reverse('telecaller_dashboard'))
        self.assertEqual(dash_arun.status_code, 200)
        self.assertEqual(dash_arun.context['my_leads_count'], 40)
        for ld in dash_arun.context['my_leads']:
            self.assertEqual(ld.assigned_telecaller, self.arun)

        leads_arun = self.client.get(reverse('telecaller_leads_list'))
        self.assertEqual(leads_arun.status_code, 200)
        self.assertEqual(leads_arun.context['page_obj'].paginator.count, 40)
        for ld in leads_arun.context['page_obj']:
            self.assertEqual(ld.assigned_telecaller, self.arun)

        self.client.logout()

        # 2. Priya's view
        self.client.login(username="priya_tc", password="Telecaller@2026")

        dash_priya = self.client.get(reverse('telecaller_dashboard'))
        self.assertEqual(dash_priya.status_code, 200)
        self.assertEqual(dash_priya.context['my_leads_count'], 35)

        leads_priya = self.client.get(reverse('telecaller_leads_list'))
        self.assertEqual(leads_priya.status_code, 200)
        self.assertEqual(leads_priya.context['page_obj'].paginator.count, 35)
        for ld in leads_priya.context['page_obj']:
            self.assertEqual(ld.assigned_telecaller, self.priya)

        self.client.logout()

        # 3. Karthik's view
        self.client.login(username="karthik_tc", password="Telecaller@2026")

        dash_karthik = self.client.get(reverse('telecaller_dashboard'))
        self.assertEqual(dash_karthik.status_code, 200)
        self.assertEqual(dash_karthik.context['my_leads_count'], 25)

        leads_karthik = self.client.get(reverse('telecaller_leads_list'))
        self.assertEqual(leads_karthik.status_code, 200)
        self.assertEqual(leads_karthik.context['page_obj'].paginator.count, 25)
        for ld in leads_karthik.context['page_obj']:
            self.assertEqual(ld.assigned_telecaller, self.karthik)

        self.client.logout()

    def test_06_cross_telecaller_lead_access_forbidden(self):
        """
        Security Test:
        Arun must NOT be able to view, edit, or tamper with leads assigned to Priya.
        Returns HTTP 403 Forbidden.
        """
        self._setup_three_telecallers()
        priya_lead = Lead.objects.create(
            name="Confidential Priya Lead",
            phone="9998887771",
            branch=self.branch,
            assigned_telecaller=self.priya,
            assigned_manager=self.manager_user,
            assignment_status='Assigned',
            status=LeadStatus.NEW
        )

        self.client.login(username="arun_tc", password="Telecaller@2026")

        # Attempt to view detail
        resp_detail = self.client.get(reverse('telecaller_lead_detail', args=[priya_lead.pk]))
        self.assertEqual(resp_detail.status_code, 403)

        # Attempt to view edit
        resp_edit_get = self.client.get(reverse('telecaller_lead_edit', args=[priya_lead.pk]))
        self.assertEqual(resp_edit_get.status_code, 403)

        # Attempt to POST edit
        resp_edit_post = self.client.post(reverse('telecaller_lead_edit', args=[priya_lead.pk]), {
            'status': LeadStatus.CONTACTED,
            'notes': 'Hacked notes',
        })
        self.assertEqual(resp_edit_post.status_code, 403)

        # Verify lead status was NOT changed
        priya_lead.refresh_from_db()
        self.assertEqual(priya_lead.status, LeadStatus.NEW)

    def test_07_subsequent_incoming_leads_maintain_proportions(self):
        """
        Verify that new incoming leads after initial batch continue to be assigned
        proportionally according to 40% / 35% / 25%.
        """
        self._setup_three_telecallers()
        self.setup_arun.assignment_percentage = 40
        self.setup_arun.is_active = True
        self.setup_arun.save()

        self.setup_priya.assignment_percentage = 35
        self.setup_priya.is_active = True
        self.setup_priya.save()

        self.setup_karthik.assignment_percentage = 25
        self.setup_karthik.is_active = True
        self.setup_karthik.save()

        # Step 1: Initial 100 leads
        leads = [
            Lead(name=f"Batch 1 Lead {i}", phone=f"9222000{i:03d}", branch=self.branch, status=LeadStatus.NEW)
            for i in range(1, 101)
        ]
        Lead.objects.bulk_create(leads)
        apply_branch_lead_distribution(self.branch)

        # Step 2: Next 20 leads arriving one-by-one (e.g. from Google Sheet or form)
        for j in range(1, 21):
            new_lead = Lead.objects.create(
                name=f"Incoming Lead {j}",
                phone=f"9333000{j:03d}",
                branch=self.branch,
                status=LeadStatus.NEW
            )
            success = assign_new_lead(new_lead, branch=self.branch)
            self.assertTrue(success)

        # Total leads = 120
        # Target shares: 120 * 40% = 48, 120 * 35% = 42, 120 * 25% = 30
        arun_total = Lead.objects.filter(assigned_telecaller=self.arun).count()
        priya_total = Lead.objects.filter(assigned_telecaller=self.priya).count()
        karthik_total = Lead.objects.filter(assigned_telecaller=self.karthik).count()

        self.assertEqual(arun_total, 48)
        self.assertEqual(priya_total, 42)
        self.assertEqual(karthik_total, 30)
        self.assertEqual(arun_total + priya_total + karthik_total, 120)

    def test_08_protected_leads_never_reassigned(self):
        """
        Verify reassignment protection:
        - Leads that are in-progress, have calls, follow-ups, or non-New status
          must NOT be reassigned when a new allocation distribution is applied.
        """
        self._setup_three_telecallers()
        self.setup_arun.assignment_percentage = 50
        self.setup_arun.is_active = True
        self.setup_arun.save()

        self.setup_priya.assignment_percentage = 50
        self.setup_priya.is_active = True
        self.setup_priya.save()

        # Create a lead assigned to Arun with a call and status 'Contacted'
        protected_lead_1 = Lead.objects.create(
            name="Protected Lead with Call",
            phone="9444000001",
            branch=self.branch,
            assigned_telecaller=self.arun,
            assigned_manager=self.manager_user,
            assignment_status='Assigned',
            status=LeadStatus.CONTACTED
        )
        CallHistory.objects.create(
            lead=protected_lead_1,
            caller=self.arun,
            telecaller=self.arun,
            call_status='Completed',
            duration=120
        )

        # Create another lead assigned to Arun with a scheduled follow-up
        protected_lead_2 = Lead.objects.create(
            name="Protected Lead with Followup",
            phone="9444000002",
            branch=self.branch,
            assigned_telecaller=self.arun,
            assigned_manager=self.manager_user,
            assignment_status='Assigned',
            status=LeadStatus.FOLLOW_UP
        )
        FollowUp.objects.create(
            lead=protected_lead_2,
            assigned_user=self.arun,
            telecaller=self.arun,
            follow_up_date=timezone.now().date(),
            status='Pending'
        )

        # Now create 10 fresh leads
        for i in range(10):
            Lead.objects.create(
                name=f"Fresh Lead {i}",
                phone=f"9555000{i:03d}",
                branch=self.branch,
                status=LeadStatus.NEW
            )

        # Change percentages to give Karthik 100% and Arun 0%
        self.setup_arun.assignment_percentage = 0
        self.setup_arun.is_active = False
        self.setup_arun.save()

        self.setup_priya.assignment_percentage = 0
        self.setup_priya.is_active = False
        self.setup_priya.save()

        self.setup_karthik.assignment_percentage = 100
        self.setup_karthik.is_active = True
        self.setup_karthik.save()

        # Trigger reallocation
        apply_branch_lead_distribution(self.branch)

        # Verify protected leads REMAIN with Arun!
        protected_lead_1.refresh_from_db()
        protected_lead_2.refresh_from_db()

        self.assertEqual(protected_lead_1.assigned_telecaller, self.arun)
        self.assertEqual(protected_lead_2.assigned_telecaller, self.arun)

        # Verify all fresh leads were assigned to Karthik
        fresh_karthik = Lead.objects.filter(assigned_telecaller=self.karthik).count()
        self.assertEqual(fresh_karthik, 10)
