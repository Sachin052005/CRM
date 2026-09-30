from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from accounts.models import User, UserRole
from branches.models import Branch, SalesHeadBranchAccess
from channels.models import Channel
from products.models import Product
from leads.models import Lead, LeadStatus
from followups.models import FollowUp, FollowUpStatus
from activities.models import Activity
from followups.forms import AdminFollowUpForm

class AdminFollowUpsModuleTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(username="admin_fu", password="pwd", email="admin_fu@example.com", role=UserRole.ADMIN)

        self.branch1, _ = Branch.objects.get_or_create(name="T. Nagar", defaults={"status": "Active"})
        self.branch2, _ = Branch.objects.get_or_create(name="Velachery", defaults={"status": "Active"})


        self.manager_a = User.objects.create_user(
            username="mgr_a", password="pwd", role=UserRole.SALES_HEAD, branch=self.branch1
        )
        SalesHeadBranchAccess.objects.create(sales_head=self.manager_a, branch=self.branch1)
        self.manager_b = User.objects.create_user(
            username="mgr_b", password="pwd", role=UserRole.SALES_HEAD, branch=self.branch2
        )
        SalesHeadBranchAccess.objects.create(sales_head=self.manager_b, branch=self.branch2)
        self.telecaller_a = User.objects.create_user(
            username="tc_a", password="pwd", role=UserRole.TELECALLER, branch=self.branch1
        )
        self.channel = Channel.objects.create(name="Google Ads")
        self.product = Product.objects.create(name="Data Science", price=45000)


        self.lead = Lead.objects.create(
            name="Rahul Sharma",
            phone="9876543210",
            branch=self.branch1,
            channel=self.channel,
            product=self.product,
            assigned_manager=self.manager_a,
            assigned_telecaller=self.telecaller_a,
            status=LeadStatus.NEW
        )

    def test_followup_with_null_users_loads_without_crashing(self):
        """Regression test for VariableDoesNotExist: Failed lookup for key [username] in None"""
        fu_null = FollowUp.objects.create(
            lead=self.lead,
            assigned_user=None,
            manager=None,
            telecaller=None,
            follow_up_date=timezone.now().date(),
            status=FollowUpStatus.PENDING,
            notes="Historical follow-up with no assigned staff"
        )
        self.client.login(username="admin_fu", password="pwd")
        response = self.client.get(reverse('admin_followups_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rahul Sharma")
        self.assertContains(response, "Unassigned")

    def test_admin_followup_create(self):
        self.client.login(username="admin_fu", password="pwd")
        tomorrow = timezone.now().date() + timedelta(days=1)
        response = self.client.post(reverse('admin_followup_create'), {
            'lead': self.lead.pk,
            'manager': self.manager_a.pk,
            'telecaller': self.telecaller_a.pk,
            'assigned_user': self.telecaller_a.pk,
            'follow_up_date': str(tomorrow),
            'follow_up_time': '10:30',
            'status': FollowUpStatus.PENDING,
            'notes': 'Scheduled demo review session'
        })
        self.assertRedirects(response, reverse('admin_followups_list'))

        fu = FollowUp.objects.filter(notes='Scheduled demo review session').first()
        self.assertIsNotNone(fu)
        self.assertEqual(fu.lead, self.lead)
        self.assertEqual(fu.manager, self.manager_a)
        self.assertEqual(fu.telecaller, self.telecaller_a)
        self.assertEqual(fu.status, FollowUpStatus.PENDING)

        # Activity log check
        activity = Activity.objects.filter(action="Follow-up Created", object_id=str(fu.pk)).first()
        self.assertIsNotNone(activity)
        self.assertEqual(activity.user, self.admin)

    def test_admin_followup_edit(self):
        fu = FollowUp.objects.create(
            lead=self.lead,
            manager=self.manager_a,
            telecaller=self.telecaller_a,
            follow_up_date=timezone.now().date(),
            status=FollowUpStatus.PENDING,
            notes="Initial note"
        )
        self.client.login(username="admin_fu", password="pwd")
        next_week = timezone.now().date() + timedelta(days=7)
        response = self.client.post(reverse('admin_followup_edit', args=[fu.pk]), {
            'lead': self.lead.pk,
            'manager': self.manager_a.pk,
            'telecaller': self.telecaller_a.pk,
            'follow_up_date': str(next_week),
            'status': FollowUpStatus.PENDING,
            'notes': 'Updated note: postponed by client'
        })
        self.assertRedirects(response, reverse('admin_followups_list'))

        fu.refresh_from_db()
        self.assertEqual(fu.follow_up_date, next_week)
        self.assertEqual(fu.notes, 'Updated note: postponed by client')

        activity = Activity.objects.filter(action="Follow-up Edited", object_id=str(fu.pk)).first()
        self.assertIsNotNone(activity)

    def test_admin_followup_reschedule(self):
        past_date = timezone.now().date() - timedelta(days=3)
        fu = FollowUp.objects.create(
            lead=self.lead,
            manager=self.manager_a,
            telecaller=self.telecaller_a,
            follow_up_date=past_date,
            status=FollowUpStatus.PENDING,
            notes="Missed callback"
        )
        self.assertTrue(fu.is_overdue)

        self.client.login(username="admin_fu", password="pwd")
        new_date = timezone.now().date() + timedelta(days=2)
        response = self.client.post(reverse('admin_followup_reschedule', args=[fu.pk]), {
            'follow_up_date': str(new_date),
            'follow_up_time': '16:00',
            'notes': 'Client requested evening callback'
        })
        self.assertRedirects(response, reverse('admin_followups_list'))

        fu.refresh_from_db()
        self.assertEqual(fu.follow_up_date, new_date)
        self.assertEqual(fu.status, FollowUpStatus.PENDING)
        self.assertIn("Rescheduled from", fu.notes)
        self.assertIn("Client requested evening callback", fu.notes)
        self.assertFalse(fu.is_overdue)

        activity = Activity.objects.filter(action="Follow-up Rescheduled", object_id=str(fu.pk)).first()
        self.assertIsNotNone(activity)

    def test_admin_followup_complete_and_cancel_status(self):
        fu = FollowUp.objects.create(
            lead=self.lead,
            manager=self.manager_a,
            telecaller=self.telecaller_a,
            follow_up_date=timezone.now().date(),
            status=FollowUpStatus.PENDING
        )
        self.client.login(username="admin_fu", password="pwd")

        # Complete
        response = self.client.get(reverse('update_followup_status', args=[fu.pk, FollowUpStatus.COMPLETED]))
        self.assertRedirects(response, reverse('admin_followups_list'))
        fu.refresh_from_db()
        self.assertEqual(fu.status, FollowUpStatus.COMPLETED)
        self.assertTrue(Activity.objects.filter(action="Follow-up Completed", object_id=str(fu.pk)).exists())

        # Cancel
        response = self.client.get(reverse('update_followup_status', args=[fu.pk, FollowUpStatus.CANCELLED]))
        self.assertRedirects(response, reverse('admin_followups_list'))
        fu.refresh_from_db()
        self.assertEqual(fu.status, FollowUpStatus.CANCELLED)
        self.assertTrue(Activity.objects.filter(action="Follow-up Cancelled", object_id=str(fu.pk)).exists())

    def test_hierarchy_validation_telecaller_manager_mismatch(self):
        # telecaller_a reports to manager_a, trying to assign to manager_b
        form = AdminFollowUpForm(data={
            'lead': self.lead.pk,
            'manager': self.manager_b.pk,
            'telecaller': self.telecaller_a.pk,
            'follow_up_date': str(timezone.now().date()),
            'status': FollowUpStatus.PENDING,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("Invalid assignment", str(form.errors))

    def test_followup_filters_work_together(self):
        self.client.login(username="admin_fu", password="pwd")

        FollowUp.objects.create(
            lead=self.lead,
            manager=self.manager_a,
            telecaller=self.telecaller_a,
            follow_up_date=timezone.now().date(),
            status=FollowUpStatus.PENDING
        )

        lead2 = Lead.objects.create(
            name="Pooja Patel",
            phone="9876543211",
            branch=self.branch2,
            channel=self.channel,
            product=self.product,
            assigned_manager=self.manager_b,
            status=LeadStatus.NEW
        )
        FollowUp.objects.create(
            lead=lead2,
            manager=self.manager_b,
            follow_up_date=timezone.now().date(),
            status=FollowUpStatus.PENDING
        )

        # Filter by branch 1 + manager_a
        response = self.client.get(reverse('admin_followups_list'), {
            'branch': self.branch1.id,
            'manager': self.manager_a.id,
            'status': 'Pending'
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rahul Sharma")
        self.assertNotContains(response, "Pooja Patel")

    def test_overdue_logic_consistency(self):
        today = timezone.now().date()
        past = today - timedelta(days=2)
        future = today + timedelta(days=2)

        fu_past = FollowUp(lead=self.lead, follow_up_date=past, status=FollowUpStatus.PENDING)
        self.assertTrue(fu_past.is_overdue)
        self.assertEqual(fu_past.display_status, 'Overdue')

        fu_future = FollowUp(lead=self.lead, follow_up_date=future, status=FollowUpStatus.PENDING)
        self.assertFalse(fu_future.is_overdue)
        self.assertEqual(fu_future.display_status, 'Pending')

        fu_done = FollowUp(lead=self.lead, follow_up_date=past, status=FollowUpStatus.COMPLETED)
        self.assertFalse(fu_done.is_overdue)
        self.assertEqual(fu_done.display_status, 'Completed')
