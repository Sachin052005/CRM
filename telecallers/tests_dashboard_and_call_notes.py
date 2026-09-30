from datetime import timedelta
from django.test import TestCase, Client
from django.utils import timezone
from accounts.models import User, UserRole
from branches.models import Branch
from leads.models import Lead, LeadStatus
from calls.models import CallHistory, CallStatus, CallOutcome
from followups.models import FollowUp, FollowUpStatus

class TelecallerDashboardAndCallNotesTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Chennai Main", status="Active")
        
        # Telecallers
        self.arun = User.objects.create_user(
            username="arun_tele",
            email="arun@techpanda.test",
            password="password123",
            role=UserRole.TELECALLER,
            branch=self.branch,
            first_name="Arun",
            last_name="Kumar"
        )
        self.priya = User.objects.create_user(
            username="priya_tele",
            email="priya@techpanda.test",
            password="password123",
            role=UserRole.TELECALLER,
            branch=self.branch,
            first_name="Priya",
            last_name="Sharma"
        )

        self.client_arun = Client()
        self.client_arun.login(username="arun_tele", password="password123")

        self.client_priya = Client()
        self.client_priya.login(username="priya_tele", password="password123")

    def test_dashboard_summary_cards_and_scoping(self):
        """
        Verify the 6 summary cards are computed strictly from leads assigned to the logged-in telecaller.
        """
        today = timezone.now().date()
        now = timezone.now()

        # --- Arun's Leads ---
        # 1. Fresh lead today
        lead_fresh = Lead.objects.create(
            name="Fresh Lead Arun",
            phone="9876543201",
            branch=self.branch,
            assigned_telecaller=self.arun,
            assigned_at=now
        )

        # 2. Today's follow-up lead (assigned 3 days ago)
        date_3_days_ago = now - timedelta(days=3)
        lead_fu = Lead.objects.create(
            name="Followup Lead Arun",
            phone="9876543202",
            branch=self.branch,
            assigned_telecaller=self.arun,
            assigned_at=date_3_days_ago
        )
        Lead.objects.filter(pk=lead_fu.pk).update(created_at=date_3_days_ago)
        FollowUp.objects.create(
            lead=lead_fu,
            telecaller=self.arun,
            follow_up_date=today,
            status=FollowUpStatus.PENDING
        )

        # 3. Pending call today (lead assigned 2 days ago)
        date_2_days_ago = now - timedelta(days=2)
        lead_pending_call = Lead.objects.create(
            name="Pending Call Lead Arun",
            phone="9876543203",
            branch=self.branch,
            assigned_telecaller=self.arun,
            assigned_at=date_2_days_ago
        )
        Lead.objects.filter(pk=lead_pending_call.pk).update(created_at=date_2_days_ago)
        CallHistory.objects.create(
            lead=lead_pending_call,
            caller=self.arun,
            call_started_at=now,
            call_status=CallStatus.INITIATED,
            notes_completed=False
        )

        # 4. Untouched for 7 days (last contact 8 days ago, created 10 days ago)
        date_10_days_ago = now - timedelta(days=10)
        date_8_days_ago = now - timedelta(days=8)
        lead_untouched_7 = Lead.objects.create(
            name="Untouched 7 Days Lead Arun",
            phone="9876543204",
            branch=self.branch,
            assigned_telecaller=self.arun,
            assigned_at=date_10_days_ago
        )
        Lead.objects.filter(pk=lead_untouched_7.pk).update(created_at=date_10_days_ago)
        CallHistory.objects.create(
            lead=lead_untouched_7,
            caller=self.arun,
            call_started_at=date_8_days_ago,
            call_status=CallStatus.COMPLETED,
            notes_completed=True
        )

        # Lead touched yesterday: created 10 days ago, contacted yesterday -> MUST NOT be in 7 days untouched
        lead_touched_yesterday = Lead.objects.create(
            name="Touched Yesterday Lead Arun",
            phone="9876543205",
            branch=self.branch,
            assigned_telecaller=self.arun,
            assigned_at=date_10_days_ago
        )
        Lead.objects.filter(pk=lead_touched_yesterday.pk).update(created_at=date_10_days_ago)
        CallHistory.objects.create(
            lead=lead_touched_yesterday,
            caller=self.arun,
            call_started_at=now - timedelta(days=1),
            call_status=CallStatus.COMPLETED,
            notes_completed=True
        )

        # 5. Untouched for 15 days (contacted 16 days ago, created 20 days ago)
        date_20_days_ago = now - timedelta(days=20)
        date_16_days_ago = now - timedelta(days=16)
        lead_untouched_15 = Lead.objects.create(
            name="Untouched 15 Days Lead Arun",
            phone="9876543206",
            branch=self.branch,
            assigned_telecaller=self.arun,
            assigned_at=date_20_days_ago
        )
        Lead.objects.filter(pk=lead_untouched_15.pk).update(created_at=date_20_days_ago)
        CallHistory.objects.create(
            lead=lead_untouched_15,
            caller=self.arun,
            call_started_at=date_16_days_ago,
            call_status=CallStatus.COMPLETED,
            notes_completed=True
        )

        # 6. Call Not Picked (assigned 5 days ago)
        date_5_days_ago = now - timedelta(days=5)
        lead_not_picked = Lead.objects.create(
            name="Not Picked Lead Arun",
            phone="9876543207",
            branch=self.branch,
            assigned_telecaller=self.arun,
            assigned_at=date_5_days_ago
        )
        Lead.objects.filter(pk=lead_not_picked.pk).update(created_at=date_5_days_ago)
        CallHistory.objects.create(
            lead=lead_not_picked,
            caller=self.arun,
            call_started_at=now - timedelta(hours=2),
            call_status=CallStatus.COMPLETED,
            call_outcome=CallOutcome.NO_ANSWER,
            notes_completed=True
        )

        # --- Priya's Leads (Isolation Verification) ---
        # Priya has 2 fresh leads, 0 followups, 0 pending calls
        Lead.objects.create(
            name="Fresh Lead Priya 1",
            phone="9123456701",
            branch=self.branch,
            assigned_telecaller=self.priya,
            assigned_at=now
        )
        Lead.objects.create(
            name="Fresh Lead Priya 2",
            phone="9123456702",
            branch=self.branch,
            assigned_telecaller=self.priya,
            assigned_at=now
        )

        # Check Arun's Dashboard
        resp_arun = self.client_arun.get('/telecaller/dashboard/')
        self.assertEqual(resp_arun.status_code, 200)
        ctx_arun = resp_arun.context

        self.assertEqual(ctx_arun['fresh_leads_today_count'], 1)
        self.assertEqual(ctx_arun['todays_followups_count'], 1)
        self.assertEqual(ctx_arun['pending_calls_today_count'], 1)
        # Untouched 7 days: lead_untouched_7 (contacted 8d ago) and lead_untouched_15 (contacted 16d ago)
        self.assertEqual(ctx_arun['not_touched_7_count'], 2)
        # Untouched 15 days: lead_untouched_15 (contacted 16d ago)
        self.assertEqual(ctx_arun['not_touched_15_count'], 1)
        # Call not picked: lead_not_picked
        self.assertEqual(ctx_arun['call_not_picked_count'], 1)

        # Verify cards and text are in Arun's rendered HTML
        html_arun = resp_arun.content.decode('utf-8')
        self.assertIn("Fresh Leads Today", html_arun)
        self.assertIn("Today's Follow-ups", html_arun)
        self.assertIn("Pending Calls Today", html_arun)
        self.assertIn("Not Touched — 7 Days", html_arun)
        self.assertIn("Not Touched — 15 Days", html_arun)
        self.assertIn("Call Not Picked", html_arun)
        self.assertIn("TODAY'S WORK", html_arun)

        # Check Priya's Dashboard (Strict Scoping: Priya only sees her metrics)
        resp_priya = self.client_priya.get('/telecaller/dashboard/')
        self.assertEqual(resp_priya.status_code, 200)
        ctx_priya = resp_priya.context

        self.assertEqual(ctx_priya['fresh_leads_today_count'], 2)
        self.assertEqual(ctx_priya['todays_followups_count'], 0)
        self.assertEqual(ctx_priya['pending_calls_today_count'], 0)
        self.assertEqual(ctx_priya['not_touched_7_count'], 0)
        self.assertEqual(ctx_priya['not_touched_15_count'], 0)
        self.assertEqual(ctx_priya['call_not_picked_count'], 0)

    def test_dashboard_filter_links(self):
        """
        Test that clicking 'View Leads', 'View Follow-ups', and 'View Calls'
        navigates to correctly filtered lists.
        """
        today = timezone.now().date()
        now = timezone.now()

        lead1 = Lead.objects.create(
            name="Lead One", phone="9990001111", branch=self.branch,
            assigned_telecaller=self.arun, assigned_at=now
        )
        lead2 = Lead.objects.create(
            name="Lead Two", phone="9990002222", branch=self.branch,
            assigned_telecaller=self.arun
        )
        # Make lead2 untouched for 10 days
        Lead.objects.filter(pk=lead2.pk).update(created_at=now - timedelta(days=10))

        lead3 = Lead.objects.create(
            name="Lead Three", phone="9990003333", branch=self.branch,
            assigned_telecaller=self.arun
        )
        CallHistory.objects.create(
            lead=lead3, caller=self.arun, call_started_at=now,
            call_outcome=CallOutcome.NO_ANSWER, notes_completed=True
        )

        FollowUp.objects.create(
            lead=lead1, telecaller=self.arun, follow_up_date=today, status=FollowUpStatus.PENDING
        )

        # 1. Filter fresh today
        r = self.client_arun.get('/telecaller/leads/?filter=fresh_today')
        self.assertEqual(r.status_code, 200)
        leads_list = list(r.context['page_obj'])
        self.assertIn(lead1, leads_list)
        self.assertNotIn(lead2, leads_list)

        # 2. Filter untouched 7 days
        r = self.client_arun.get('/telecaller/leads/?filter=untouched_7')
        self.assertEqual(r.status_code, 200)
        leads_list = list(r.context['page_obj'])
        self.assertIn(lead2, leads_list)
        self.assertNotIn(lead1, leads_list)

        # 3. Filter call not picked
        r = self.client_arun.get('/telecaller/leads/?filter=not_picked')
        self.assertEqual(r.status_code, 200)
        leads_list = list(r.context['page_obj'])
        self.assertIn(lead3, leads_list)
        self.assertNotIn(lead1, leads_list)

        # 4. Filter followups today
        r = self.client_arun.get('/telecaller/followups/?status=today')
        self.assertEqual(r.status_code, 200)
        fu_list = list(r.context['page_obj'])
        self.assertEqual(len(fu_list), 1)
        self.assertEqual(fu_list[0].lead, lead1)

    def test_mandatory_call_notes_lock_and_blocking(self):
        """
        Verify end-to-end mandatory call-notes lock:
        1. Call starts for Lead A
        2. Call ends
        3. Attempting to call Lead B is strictly BLOCKED by backend (HTTP 400, blocked=true)
        4. Attempting to save empty / whitespace notes is rejected
        5. Saving valid notes completes previous call, writes to Lead.notes, and unlocks next call
        6. Attempting to call Lead B now succeeds
        """
        lead_a = Lead.objects.create(
            name="Lead Alpha", phone="9876500001", branch=self.branch, assigned_telecaller=self.arun
        )
        lead_b = Lead.objects.create(
            name="Lead Beta", phone="9876500002", branch=self.branch, assigned_telecaller=self.arun
        )

        # 1. Start Call with Lead Alpha
        start_res = self.client_arun.post('/calls/start/', {'lead_id': lead_a.id})
        self.assertEqual(start_res.status_code, 200)
        start_data = start_res.json()
        self.assertTrue(start_data['success'])
        call_id = start_data['call_id']

        # Verify call record is in DB with notes_completed=False
        call_record = CallHistory.objects.get(pk=call_id)
        self.assertFalse(call_record.notes_completed)

        # 2. End Call with duration 45s
        end_res = self.client_arun.post(f'/calls/{call_id}/end/', {'duration': 45})
        self.assertEqual(end_res.status_code, 200)
        self.assertTrue(end_res.json()['success'])

        # 3. Try to call Lead Beta while notes for Lead Alpha are pending -> MUST BE BLOCKED
        blocked_res = self.client_arun.post('/calls/start/', {'lead_id': lead_b.id})
        self.assertEqual(blocked_res.status_code, 400)
        blocked_data = blocked_res.json()
        self.assertTrue(blocked_data['blocked'])
        self.assertEqual(blocked_data['error'], 'call_notes_required')
        self.assertEqual(blocked_data['pending_call']['lead_id'], lead_a.id)

        # Multi-tab test: Calling via GET or direct access is also blocked
        blocked_get = self.client_arun.get(f'/calls/start/?lead_id={lead_b.id}')
        self.assertEqual(blocked_get.status_code, 400)
        self.assertTrue(blocked_get.json()['blocked'])

        # 4. Attempt to complete call with empty or whitespace-only notes -> MUST BE REJECTED
        empty_notes_res = self.client_arun.post(
            '/calls/complete/',
            {'call_id': call_id, 'lead_id': lead_a.id, 'duration': 45, 'notes': '   ', 'call_outcome': 'Interested'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(empty_notes_res.status_code, 400)
        self.assertIn("Call Notes are required", empty_notes_res.json()['error'])

        # Lock is STILL active
        lock_check = self.client_arun.get('/calls/lock-check/').json()
        self.assertTrue(lock_check['has_lock'])

        # 5. Save valid call notes
        valid_notes = "Customer interested in Full-Stack program. Requested demo tomorrow at 3 PM."
        complete_res = self.client_arun.post(
            '/calls/complete/',
            {
                'call_id': call_id,
                'lead_id': lead_a.id,
                'duration': 45,
                'notes': valid_notes,
                'call_outcome': 'Interested',
                'lead_status': 'Interested'
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(complete_res.status_code, 200)
        complete_data = complete_res.json()
        self.assertTrue(complete_data['success'])

        # Verify call record is now marked notes_completed=True
        call_record.refresh_from_db()
        self.assertTrue(call_record.notes_completed)
        self.assertEqual(call_record.call_status, CallStatus.COMPLETED)
        self.assertEqual(call_record.notes, valid_notes)

        # Verify notes appended to Lead model
        lead_a.refresh_from_db()
        self.assertIn(valid_notes, lead_a.notes)
        self.assertEqual(lead_a.status, 'Interested')

        # Lock is cleared
        lock_check2 = self.client_arun.get('/calls/lock-check/').json()
        self.assertFalse(lock_check2['has_lock'])

        # 6. Now calling Lead Beta succeeds!
        start_beta_res = self.client_arun.post('/calls/start/', {'lead_id': lead_b.id})
        self.assertEqual(start_beta_res.status_code, 200)
        self.assertTrue(start_beta_res.json()['success'])

    def test_telecaller_isolation_lock(self):
        """
        Verify that Arun's active call lock does NOT block Priya from calling her leads.
        """
        lead_arun = Lead.objects.create(
            name="Arun Lead", phone="9876511111", branch=self.branch, assigned_telecaller=self.arun
        )
        lead_priya = Lead.objects.create(
            name="Priya Lead", phone="9876522222", branch=self.branch, assigned_telecaller=self.priya
        )

        # Arun starts call
        arun_call = self.client_arun.post('/calls/start/', {'lead_id': lead_arun.id})
        self.assertEqual(arun_call.status_code, 200)

        # Arun is locked
        arun_lock = self.client_arun.get('/calls/lock-check/').json()
        self.assertTrue(arun_lock['has_lock'])

        # Priya checks lock -> should NOT have lock
        priya_lock = self.client_priya.get('/calls/lock-check/').json()
        self.assertFalse(priya_lock['has_lock'])

        # Priya can start call on her lead without any hindrance
        priya_call = self.client_priya.post('/calls/start/', {'lead_id': lead_priya.id})
        self.assertEqual(priya_call.status_code, 200)
        self.assertTrue(priya_call.json()['success'])

    def test_unauthorized_lead_call_blocked(self):
        """
        Verify telecaller cannot call a lead assigned to another telecaller.
        """
        lead_priya = Lead.objects.create(
            name="Priya Private Lead", phone="9876533333", branch=self.branch, assigned_telecaller=self.priya
        )
        # Arun tries to call Priya's lead -> 403 Forbidden
        res = self.client_arun.post('/calls/start/', {'lead_id': lead_priya.id})
        self.assertEqual(res.status_code, 403)
