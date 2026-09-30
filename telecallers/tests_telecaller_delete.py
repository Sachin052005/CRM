from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, UserRole
from branches.models import Branch
from channels.models import Channel
from products.models import Product
from calls.models import CallHistory
from followups.models import FollowUp
from activities.models import Activity
from leads.models import Lead, LeadStatus, TelecallerLeadSetup
from leads.assignment import assign_new_lead


class TelecallerDeleteFlowTestCase(TestCase):
    """
    Test suite for Telecaller Delete flow on Admin Telecallers page (/admin/telecallers/):
    1. Create a new telecaller and verify credentials login.
    2. Assign leads, calls, follow-ups, and activities to the telecaller.
    3. Open Admin -> Telecallers: verify Edit and Delete actions are present.
    4. Test GET delete confirmation page.
    5. Test Cancel behavior (no changes).
    6. Test POST delete execution:
       - Telecaller account deleted/removed from User table.
       - Old credentials cannot log in.
       - Removed from Admin -> Telecallers list.
       - Existing leads remain in database, preserved with assigned_telecaller=None and status='Unassigned'.
       - Lead calls, follow-ups, activities, and history remain completely intact.
       - Telecaller removed from TelecallerLeadSetup.
       - Admin can reassign affected leads to another active telecaller.
    7. Test Security: Telecaller or Manager cannot access delete endpoint.
    8. Safe Delete: Attempting to delete non-existent telecaller or admin self-deletion fails safely.
    """

    def setUp(self):
        self.client = Client()

        # Clean any preexisting setup
        TelecallerLeadSetup.objects.all().delete()
        Lead.objects.all().delete()

        # Branch, Channel, Product
        self.branch = Branch.objects.create(name="Chennai Central", status="Active")
        self.channel = Channel.objects.create(name="Direct", status="Active")
        self.product = Product.objects.create(name="Full Stack Dev", price=30000, status="Active")

        # Admin user
        self.admin_user = User.objects.create_user(
            username="admin_user",
            email="admin@techpanda.com",
            password="AdminPassword@2026",
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True
        )

        # Sales Head user (formerly "Manager")
        self.manager_user = User.objects.create_user(
            username="manager_user",
            email="manager@techpanda.com",
            password="ManagerPassword@2026",
            role=UserRole.SALES_HEAD,
            branch=self.branch
        )

        # Telecaller to be deleted
        self.telecaller = User.objects.create_user(
            username="arun_01",
            first_name="Arun",
            last_name="Kumar",
            email="arun01@techpanda.com",
            password="Password@123",
            role=UserRole.TELECALLER,
            branch=self.branch,
            is_active=True
        )

        # Setup entry for Arun
        self.setup_arun = TelecallerLeadSetup.objects.create(
            telecaller=self.telecaller,
            branch=self.branch,
            assignment_percentage=50,
            is_active=True
        )

        # Another active telecaller (Priya)
        self.priya = User.objects.create_user(
            username="priya_01",
            first_name="Priya",
            last_name="S",
            email="priya01@techpanda.com",
            password="Password@123",
            role=UserRole.TELECALLER,
            branch=self.branch,
            is_active=True
        )
        self.setup_priya = TelecallerLeadSetup.objects.create(
            telecaller=self.priya,
            branch=self.branch,
            assignment_percentage=50,
            is_active=True
        )

    def test_01_telecaller_initial_login_works(self):
        """Step 1 & 2: Verify the telecaller can log in with their created credentials."""
        logged_in = self.client.login(username="arun_01", password="Password@123")
        self.assertTrue(logged_in)
        resp = self.client.get(reverse('telecaller_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.client.logout()

    def test_02_admin_telecallers_page_has_actions_and_modal(self):
        """Step 4: Verify Admin -> Telecallers displays Edit, Delete, and Confirmation modal."""
        self.client.login(username="admin_user", password="AdminPassword@2026")
        resp = self.client.get(reverse('admin_telecallers_list'))
        self.assertEqual(resp.status_code, 200)

        content = resp.content.decode('utf-8')
        # Table headers and contents
        self.assertIn("Telecaller", content)
        self.assertIn("arun_01", content)
        self.assertIn("Arun Kumar", content)
        self.assertIn("Edit", content)
        self.assertIn("Delete", content)
        # Modal elements
        self.assertIn("deleteTelecallerModal", content)
        self.assertIn("Are you sure you want to delete this telecaller?", content)
        self.assertIn("The telecaller will no longer be able to log in", content)

    def test_03_get_delete_confirmation_page(self):
        """Step 6: Visiting delete URL via GET renders confirmation page without deleting."""
        self.client.login(username="admin_user", password="AdminPassword@2026")
        resp = self.client.get(reverse('admin_telecaller_delete', args=[self.telecaller.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'admin/telecaller_confirm_delete.html')

        # Verify telecaller still exists
        self.assertTrue(User.objects.filter(pk=self.telecaller.pk).exists())

    def test_04_end_to_end_delete_flow_and_lead_preservation(self):
        """
        Complete Delete Flow:
        1. Telecaller has 5 assigned leads.
        2. Lead 1 has completed calls.
        3. Lead 2 has scheduled follow-ups.
        4. Telecaller has logged activities.
        5. Admin deletes telecaller via POST.
        6. Verify telecaller user is removed from database.
        7. Verify old credentials cannot log in.
        8. Verify telecaller is removed from /admin/telecallers/ list.
        9. Verify ALL 5 leads remain in database, with assigned_telecaller=None and status='Unassigned'.
        10. Verify call history, follow-ups, and activities are 100% preserved.
        11. Verify telecaller removed from TelecallerLeadSetup.
        12. Verify Admin can reassign affected leads to another active telecaller (Priya).
        """
        # Create 5 leads assigned to Arun
        leads = []
        for i in range(1, 6):
            lead = Lead.objects.create(
                name=f"Lead Student {i}",
                phone=f"987650000{i}",
                email=f"lead{i}@example.com",
                branch=self.branch,
                channel=self.channel,
                product=self.product,
                assigned_telecaller=self.telecaller,
                assigned_manager=self.manager_user,
                assignment_status='Assigned',
                status=LeadStatus.NEW
            )
            leads.append(lead)

        # Attach Call to Lead 1
        call = CallHistory.objects.create(
            lead=leads[0],
            caller=self.telecaller,
            telecaller=self.telecaller,
            call_status='Completed',
            duration=95,
            notes='Initial inquiry discussion'
        )

        # Attach FollowUp to Lead 2
        followup = FollowUp.objects.create(
            lead=leads[1],
            assigned_user=self.telecaller,
            telecaller=self.telecaller,
            follow_up_date=timezone.now().date(),
            status='Pending',
            notes='Follow-up for enrollment'
        )

        # Log Activity for Telecaller
        activity = Activity.objects.create(
            user=self.telecaller,
            action="Lead Updated",
            description="Arun updated notes for Lead Student 1",
            object_type="Lead",
            object_id=str(leads[0].pk)
        )

        # Verify initial counts
        self.assertEqual(Lead.objects.filter(assigned_telecaller=self.telecaller).count(), 5)
        self.assertEqual(CallHistory.objects.filter(lead=leads[0]).count(), 1)
        self.assertEqual(FollowUp.objects.filter(lead=leads[1]).count(), 1)
        self.assertEqual(Activity.objects.filter(object_id=str(leads[0].pk)).count(), 1)

        # Admin logs in and performs POST Delete
        self.client.login(username="admin_user", password="AdminPassword@2026")
        delete_url = reverse('admin_telecaller_delete', args=[self.telecaller.pk])
        resp = self.client.post(delete_url, follow=True)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Telecaller deleted successfully.")

        # 1. Telecaller account removed from User table
        self.assertFalse(User.objects.filter(username="arun_01").exists())
        self.assertFalse(User.objects.filter(pk=self.telecaller.pk).exists())

        # 2. Old credentials cannot log in
        self.client.logout()
        login_attempt = self.client.login(username="arun_01", password="Password@123")
        self.assertFalse(login_attempt, "Deleted telecaller was still able to log in!")

        # 3. Telecaller removed from Admin -> Telecallers list
        self.client.login(username="admin_user", password="AdminPassword@2026")
        list_resp = self.client.get(reverse('admin_telecallers_list'))
        self.assertEqual(list_resp.status_code, 200)
        self.assertNotContains(list_resp, "arun_01")

        # 4. Existing leads PRESERVED in CRM with assigned_telecaller=None and status='Unassigned'
        self.assertEqual(Lead.objects.filter(branch=self.branch).count(), 5)
        for lead in Lead.objects.filter(branch=self.branch):
            self.assertIsNone(lead.assigned_telecaller)
            self.assertEqual(lead.assignment_status, 'Unassigned')
            self.assertIn("deleted", lead.pending_assignment_reason.lower())

        # 5. Lead history, calls, follow-ups, and activities remain intact!
        call.refresh_from_db()
        self.assertEqual(call.lead, leads[0])
        self.assertEqual(call.duration, 95)
        self.assertEqual(call.notes, 'Initial inquiry discussion')

        followup.refresh_from_db()
        self.assertEqual(followup.lead, leads[1])
        self.assertEqual(followup.status, 'Pending')
        self.assertEqual(followup.notes, 'Follow-up for enrollment')

        activity.refresh_from_db()
        self.assertEqual(activity.action, "Lead Updated")
        self.assertEqual(activity.object_id, str(leads[0].pk))

        # 6. Telecaller removed from TelecallerLeadSetup
        self.assertFalse(TelecallerLeadSetup.objects.filter(telecaller_id=self.telecaller.pk).exists())

        # 7. Admin can reassign affected leads to another active telecaller (Priya)
        self.setup_priya.assignment_percentage = 100
        self.setup_priya.save()

        for lead in Lead.objects.filter(branch=self.branch):
            reassigned = assign_new_lead(lead, branch=self.branch)
            self.assertTrue(reassigned)
            lead.refresh_from_db()
            self.assertEqual(lead.assigned_telecaller, self.priya)
            self.assertEqual(lead.assignment_status, 'Assigned')

        self.assertEqual(Lead.objects.filter(assigned_telecaller=self.priya).count(), 5)

    def test_05_security_non_admin_cannot_delete(self):
        """Telecallers and Managers must NOT be able to delete telecaller accounts."""
        delete_url = reverse('admin_telecaller_delete', args=[self.telecaller.pk])

        # Telecaller tries to delete
        self.client.login(username="priya_01", password="Password@123")
        resp_tc = self.client.post(delete_url)
        # Should be redirected to their workspace or forbidden
        self.assertNotEqual(resp_tc.status_code, 200)
        # Verify Arun was NOT deleted
        self.assertTrue(User.objects.filter(username="arun_01").exists())
        self.client.logout()

        # Manager tries to delete
        self.client.login(username="manager_user", password="ManagerPassword@2026")
        resp_mgr = self.client.post(delete_url)
        self.assertNotEqual(resp_mgr.status_code, 200)
        # Verify Arun was NOT deleted
        self.assertTrue(User.objects.filter(username="arun_01").exists())
        self.client.logout()

    def test_06_safe_delete_non_existent_and_self_deletion(self):
        """Attempting to delete non-existent user or self fails gracefully."""
        self.client.login(username="admin_user", password="AdminPassword@2026")

        # Non-existent ID (999999)
        resp_404 = self.client.post(reverse('admin_telecaller_delete', args=[999999]), follow=True)
        self.assertEqual(resp_404.status_code, 200)
        self.assertContains(resp_404, "Telecaller not found.")

        # Admin attempting to delete their own account
        resp_self = self.client.post(reverse('admin_telecaller_delete', args=[self.admin_user.pk]), follow=True)
        self.assertEqual(resp_self.status_code, 200)
        # Admin still exists
        self.assertTrue(User.objects.filter(username="admin_user").exists())
