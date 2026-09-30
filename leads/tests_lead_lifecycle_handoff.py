from django.test import TestCase
from accounts.models import User, UserRole
from accounts.permissions import can_view_lead
from branches.models import Branch, SalesHeadBranchAccess
from leads.models import Lead, LeadStatus, LeadOwnerType, LeadAssignmentHistory, LeadStatusHistory
from leads.handoff_service import change_lead_status


class LeadLifecycleHandoffTests(TestCase):
    """
    Lead -> Branch -> Telecaller -> Interested -> Visit -> Counselor -> Counseling -> Joined.
    Verifies branch stability, assignment/status history, the automatic telecaller->counselor
    handoff on Visit Scheduled, and cross-role/cross-branch visibility.
    """

    def setUp(self):
        self.branch = Branch.objects.create(name="Lifecycle Branch")
        self.other_branch = Branch.objects.create(name="Other Branch")

        self.admin = User.objects.create_user(
            username="lh_admin", password="pwd", role=UserRole.ADMIN, is_staff=True, is_superuser=True
        )
        self.sales_head = User.objects.create_user(username="lh_sales_head", password="pwd", role=UserRole.SALES_HEAD)
        SalesHeadBranchAccess.objects.create(sales_head=self.sales_head, branch=self.branch)
        self.branch_head = User.objects.create_user(
            username="lh_branch_head", password="pwd", role=UserRole.BRANCH_HEAD, branch=self.branch
        )
        self.counselor = User.objects.create_user(
            username="lh_counselor", password="pwd", role=UserRole.COUNSELOR, branch=self.branch
        )
        self.telecaller = User.objects.create_user(
            username="lh_telecaller", password="pwd", role=UserRole.TELECALLER, branch=self.branch
        )

        self.other_branch_head = User.objects.create_user(
            username="lh_other_branch_head", password="pwd", role=UserRole.BRANCH_HEAD, branch=self.other_branch
        )
        self.other_counselor = User.objects.create_user(
            username="lh_other_counselor", password="pwd", role=UserRole.COUNSELOR, branch=self.other_branch
        )
        self.other_telecaller = User.objects.create_user(
            username="lh_other_telecaller", password="pwd", role=UserRole.TELECALLER, branch=self.other_branch
        )

        self.lead = Lead.objects.create(
            name="Lifecycle Lead",
            phone="9000000001",
            branch=self.branch,
            assigned_telecaller=self.telecaller,
            current_owner_type=LeadOwnerType.TELECALLER,
            status=LeadStatus.NEW,
        )

    def test_full_lifecycle_and_handoff(self):
        telecaller_stages = [LeadStatus.CONTACTED, LeadStatus.INTERESTED, LeadStatus.VISIT_SCHEDULED]
        counselor_stages = [LeadStatus.VISITED, LeadStatus.COUNSELING, LeadStatus.JOINED]
        transitions = telecaller_stages + counselor_stages

        for status in telecaller_stages:
            change_lead_status(self.lead, status, self.telecaller, remarks=f"moved to {status}")
            self.lead.refresh_from_db()

        # Auto handoff must have fired exactly when VISIT_SCHEDULED was reached
        self.assertEqual(self.lead.assigned_counselor, self.counselor)
        self.assertEqual(self.lead.current_owner_type, LeadOwnerType.COUNSELOR)
        self.assertEqual(self.lead.assigned_telecaller, self.telecaller, "telecaller kept for traceability")

        for status in counselor_stages:
            change_lead_status(self.lead, status, self.counselor, remarks=f"moved to {status}")
            self.lead.refresh_from_db()

        self.assertEqual(self.lead.status, LeadStatus.JOINED)
        self.assertEqual(self.lead.branch, self.branch, "branch must never change through the lifecycle")

        # Assignment history recorded the handoff
        handoff = LeadAssignmentHistory.objects.filter(lead=self.lead, to_role='COUNSELOR').first()
        self.assertIsNotNone(handoff)
        self.assertEqual(handoff.to_user, self.counselor)
        self.assertEqual(handoff.from_role, UserRole.TELECALLER)

        # Status history recorded every transition, in order, with correct old/new values
        history = list(LeadStatusHistory.objects.filter(lead=self.lead).order_by('created_at'))
        self.assertEqual(len(history), len(transitions))
        expected_old = [LeadStatus.NEW] + transitions[:-1]
        for record, expected_old_status, expected_new_status in zip(history, expected_old, transitions):
            self.assertEqual(record.old_status, expected_old_status)
            self.assertEqual(record.new_status, expected_new_status)

        # Visibility: same-branch roles and Admin can see the lead
        self.assertTrue(can_view_lead(self.counselor, self.lead))
        self.assertTrue(can_view_lead(self.branch_head, self.lead))
        self.assertTrue(can_view_lead(self.sales_head, self.lead))
        self.assertTrue(can_view_lead(self.admin, self.lead))

        # Visibility: a different branch's equivalent roles must NOT see the lead
        self.assertFalse(can_view_lead(self.other_telecaller, self.lead))
        self.assertFalse(can_view_lead(self.other_counselor, self.lead))
        self.assertFalse(can_view_lead(self.other_branch_head, self.lead))
