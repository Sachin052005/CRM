from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch, SalesHeadBranchAccess
from leads.models import Lead, LeadStatus
from calls.models import CallHistory
from followups.models import FollowUp, FollowUpStatus
from activities.models import Activity

class CallExecutionAndPersistenceTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.create(name="Calls Test Branch")
        self.manager = User.objects.create_user(username="mgr_call", password="pwd", role=UserRole.SALES_HEAD, branch=self.branch)
        SalesHeadBranchAccess.objects.create(sales_head=self.manager, branch=self.branch)
        self.telecaller = User.objects.create_user(
            username="tc_call", password="pwd", role=UserRole.TELECALLER, branch=self.branch
        )
        self.lead = Lead.objects.create(
            name="Vikram Singh",
            phone="9876500000",
            assigned_sales_head=self.manager,
            assigned_telecaller=self.telecaller,
            status=LeadStatus.NEW
        )

    def test_call_completion_persists_callhistory_and_activity(self):
        self.client.login(username='tc_call', password='pwd')
        
        response = self.client.post(reverse('complete_call_record'), {
            'lead_id': self.lead.pk,
            'duration': 145,  # 2m 25s
            'call_outcome': 'Interested',
            'lead_status': 'Interested',
            'notes': 'Candidate wants demo class tomorrow',
            'follow_up_date': '2026-09-25',
            'follow_up_time': '14:00'
        })

        # 1. Call record exists in database
        call = CallHistory.objects.filter(lead=self.lead).first()
        self.assertIsNotNone(call)
        self.assertEqual(call.duration, 145)
        self.assertEqual(call.call_outcome, 'Interested')
        self.assertEqual(call.caller, self.telecaller)
        self.assertEqual(call.manager, self.manager)

        # 2. Lead status updated
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, LeadStatus.INTERESTED)
        self.assertIn("Candidate wants demo class tomorrow", self.lead.notes)

        # 3. Scheduled follow-up created
        followup = FollowUp.objects.filter(lead=self.lead).first()
        self.assertIsNotNone(followup)
        self.assertEqual(str(followup.follow_up_date), '2026-09-25')
        self.assertEqual(followup.status, FollowUpStatus.PENDING)

        # 4. Activity created
        activity = Activity.objects.filter(action="Call Completed").first()
        self.assertIsNotNone(activity)
        self.assertEqual(activity.user, self.telecaller)

    def test_unauthorized_call_logging_returns_403(self):
        other_caller = User.objects.create_user(username="other_caller", password="pwd", role=UserRole.TELECALLER)
        self.client.login(username='other_caller', password='pwd')
        
        response = self.client.post(reverse('complete_call_record'), {
            'lead_id': self.lead.pk,
            'duration': 60,
            'call_outcome': 'Interested',
        })
        self.assertEqual(response.status_code, 403)

    def test_call_detail_recording_unavailable(self):
        admin = User.objects.create_superuser(username="admin_call_view", password="pwd")
        call = CallHistory.objects.create(
            lead=self.lead,
            caller=self.telecaller,
            duration=45,
            recording_url=""
        )
        self.client.login(username='admin_call_view', password='pwd')
        response = self.client.get(reverse('admin_call_detail', args=[call.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No recording available")

    def test_calls_list_with_null_users_loads_without_crashing(self):
        """Regression test: call with null manager and null telecaller must load cleanly"""
        call = CallHistory.objects.create(
            lead=self.lead,
            caller=self.telecaller,
            manager=None,
            telecaller=None,
            duration=90,
            notes="Legacy call record"
        )
        admin = User.objects.create_superuser(username="admin_call_list", password="pwd")
        self.client.login(username='admin_call_list', password='pwd')
        response = self.client.get(reverse('admin_calls_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Vikram Singh")
        self.assertContains(response, "Unassigned")

    def test_admin_call_create_and_activity_logging(self):
        admin = User.objects.create_superuser(username="admin_call_creator", password="pwd")
        self.client.login(username='admin_call_creator', password='pwd')

        response = self.client.post(reverse('admin_call_create'), {
            'lead': self.lead.pk,
            'caller': self.telecaller.pk,
            'manager': self.manager.pk,
            'telecaller': self.telecaller.pk,
            'call_status': 'Completed',
            'call_outcome': 'Interested',
            'call_started_at': '2026-09-23 10:00:00',
            'call_ended_at': '2026-09-23 10:05:00',
            'duration': 300,
            'notes': 'Manual call entry by administrator'
        })
        self.assertRedirects(response, reverse('admin_calls_list'))

        call = CallHistory.objects.filter(notes='Manual call entry by administrator').first()
        self.assertIsNotNone(call)
        self.assertEqual(call.duration, 300)
        self.assertEqual(call.manager, self.manager)

        activity = Activity.objects.filter(action="Call Created", object_id=str(call.pk)).first()
        self.assertIsNotNone(activity)

    def test_admin_call_create_hierarchy_mismatch_rejected(self):
        other_manager = User.objects.create_user(username="other_mgr", password="pwd", role=UserRole.SALES_HEAD)
        admin = User.objects.create_superuser(username="admin_call_check", password="pwd")
        self.client.login(username='admin_call_check', password='pwd')

        # telecaller reports to self.manager, not other_manager
        response = self.client.post(reverse('admin_call_create'), {
            'lead': self.lead.pk,
            'caller': self.telecaller.pk,
            'manager': other_manager.pk,
            'telecaller': self.telecaller.pk,
            'call_status': 'Completed',
            'call_outcome': 'Interested',
            'call_started_at': '2026-09-23 10:00:00',
            'duration': 120,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid assignment")


