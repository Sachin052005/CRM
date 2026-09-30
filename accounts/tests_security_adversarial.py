"""
Phase 6: dedicated adversarial security/permission pass across the 5-role
hierarchy. Focused on the security surface this rework introduced - user
creation/management across roles, and account-state/CSRF edge cases - not a
general CRUD smoke test (that's covered elsewhere).
"""
from django.test import TestCase, Client
from django.test.client import Client as CsrfClient
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch, SalesHeadBranchAccess


def make_role_ladder():
    """One branch with one user of each role, plus an isolated second branch
    for cross-branch checks. Returns a dict of the created objects."""
    branch = Branch.objects.create(name="Adversarial Branch")
    other_branch = Branch.objects.create(name="Adversarial Other Branch")

    admin = User.objects.create_user(
        username="adv_admin", password="pwd12345678", role=UserRole.ADMIN, is_staff=True, is_superuser=True
    )
    sales_head = User.objects.create_user(username="adv_sales_head", password="pwd12345678", role=UserRole.SALES_HEAD)
    SalesHeadBranchAccess.objects.create(sales_head=sales_head, branch=branch)
    branch_head = User.objects.create_user(
        username="adv_branch_head", password="pwd12345678", role=UserRole.BRANCH_HEAD, branch=branch
    )
    counselor = User.objects.create_user(
        username="adv_counselor", password="pwd12345678", role=UserRole.COUNSELOR, branch=branch
    )
    telecaller = User.objects.create_user(
        username="adv_telecaller", password="pwd12345678", role=UserRole.TELECALLER, branch=branch
    )
    return {
        'branch': branch, 'other_branch': other_branch,
        'admin': admin, 'sales_head': sales_head, 'branch_head': branch_head,
        'counselor': counselor, 'telecaller': telecaller,
    }


class DeactivatedAccountLoginTests(TestCase):
    """A deactivated user of any role must never be able to log in or
    continue using an already-authenticated session."""

    def setUp(self):
        self.client = Client()
        self.roles = make_role_ladder()

    def test_deactivated_user_cannot_login_for_every_role(self):
        for key in ('admin', 'sales_head', 'branch_head', 'counselor', 'telecaller'):
            user = self.roles[key]
            user.is_active = False
            user.save(update_fields=['is_active'])

            resp = self.client.post(reverse('login'), {'username': user.username, 'password': 'pwd12345678'})
            self.assertEqual(resp.status_code, 200, f"{key}: expected the login form to be re-rendered (login refused)")
            self.assertFalse(
                resp.wsgi_request.user.is_authenticated,
                f"{key}: a deactivated user must not be logged in"
            )

    def test_deactivation_mid_session_blocks_further_access(self):
        """role_required checks is_active on every request, not just at login -
        a session token stolen or kept alive after deactivation must not work."""
        branch_head = self.roles['branch_head']
        self.client.login(username=branch_head.username, password='pwd12345678')
        ok_resp = self.client.get(reverse('branch_head_dashboard'))
        self.assertEqual(ok_resp.status_code, 200)

        branch_head.is_active = False
        branch_head.save(update_fields=['is_active'])

        blocked_resp = self.client.get(reverse('branch_head_dashboard'))
        self.assertEqual(blocked_resp.status_code, 302, "a deactivated user's existing session must be rejected")
        self.assertTrue(blocked_resp.url.startswith(reverse('login')))
        # Django's own auth backend (ModelBackend.get_user -> user_can_authenticate)
        # already treats a deactivated user's session as anonymous on the very next
        # request - stronger than relying on role_required's own is_active check.
        self.assertFalse(blocked_resp.wsgi_request.user.is_authenticated)


class RoleEscalationTests(TestCase):
    """No role may create a user of a role/scope it isn't authorized for,
    even by POSTing directly to another role's creation endpoint."""

    def setUp(self):
        self.client = Client()
        self.roles = make_role_ladder()

    def _user_payload(self, suffix, branch_id=None, extra=None):
        payload = {
            'first_name': 'Esc', 'last_name': 'Alation', 'username': f'escalated_{suffix}',
            'email': f'escalated_{suffix}@example.com', 'phone': '9990001111', 'is_active': 'on',
            'password': 'StrongPass123!', 'confirm_password': 'StrongPass123!',
        }
        if branch_id is not None:
            payload['branch'] = branch_id
        if extra:
            payload.update(extra)
        return payload

    def test_sales_head_cannot_create_another_sales_head(self):
        """There is no Sales-Head-facing 'create Sales Head' endpoint at all -
        confirm the only such endpoint (admin_manager_create) rejects a
        Sales Head who POSTs to it directly."""
        self.client.login(username=self.roles['sales_head'].username, password='pwd12345678')
        resp = self.client.post(reverse('admin_manager_create'), self._user_payload('sh_as_sh'))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(User.objects.filter(username='escalated_sh_as_sh').exists())

    def test_branch_head_cannot_create_sales_head_or_branch_head(self):
        self.client.login(username=self.roles['branch_head'].username, password='pwd12345678')

        resp = self.client.post(reverse('admin_manager_create'), self._user_payload('bh_as_sh'))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(User.objects.filter(username='escalated_bh_as_sh').exists())

        resp2 = self.client.post(
            reverse('admin_branch_head_create'),
            self._user_payload('bh_as_bh', branch_id=self.roles['branch'].id)
        )
        self.assertEqual(resp2.status_code, 302)
        self.assertFalse(User.objects.filter(username='escalated_bh_as_bh').exists())

        resp3 = self.client.post(
            reverse('sales_head_branch_head_create'),
            self._user_payload('bh_as_shbh', branch_id=self.roles['branch'].id)
        )
        self.assertEqual(resp3.status_code, 302)
        self.assertFalse(User.objects.filter(username='escalated_bh_as_shbh').exists())

    def test_counselor_cannot_create_any_user(self):
        self.client.login(username=self.roles['counselor'].username, password='pwd12345678')
        creation_urls = [
            ('admin_manager_create', {}),
            ('admin_branch_head_create', {'branch_id': self.roles['branch'].id}),
            ('sales_head_branch_head_create', {'branch_id': self.roles['branch'].id}),
            ('branch_head_counselor_create', {}),
            ('admin_telecaller_create', {}),
            ('branch_head_telecaller_create', {}),
        ]
        for i, (url_name, kwargs) in enumerate(creation_urls):
            username = f'counselor_escalation_{i}'
            resp = self.client.post(reverse(url_name), self._user_payload(username, **kwargs))
            self.assertIn(resp.status_code, (302, 403, 404), f"{url_name} should refuse a Counselor, got {resp.status_code}")
            self.assertFalse(User.objects.filter(username=f'escalated_{username}').exists(), f"{url_name} let a Counselor create a user")

    def test_telecaller_cannot_create_any_user(self):
        self.client.login(username=self.roles['telecaller'].username, password='pwd12345678')
        creation_urls = [
            ('admin_manager_create', {}),
            ('admin_branch_head_create', {'branch_id': self.roles['branch'].id}),
            ('sales_head_branch_head_create', {'branch_id': self.roles['branch'].id}),
            ('branch_head_counselor_create', {}),
            ('admin_telecaller_create', {}),
            ('branch_head_telecaller_create', {}),
        ]
        for i, (url_name, kwargs) in enumerate(creation_urls):
            username = f'telecaller_escalation_{i}'
            resp = self.client.post(reverse(url_name), self._user_payload(username, **kwargs))
            self.assertIn(resp.status_code, (302, 403, 404), f"{url_name} should refuse a Telecaller, got {resp.status_code}")
            self.assertFalse(User.objects.filter(username=f'escalated_{username}').exists(), f"{url_name} let a Telecaller create a user")

    def test_branch_head_counselor_create_ignores_forged_branch_field(self):
        """BranchHeadCounselorCreateForm has no branch field at all - the
        branch is always the acting Branch Head's own. Confirm a forged
        'branch' POST value can't redirect the new Counselor into another
        branch."""
        branch_head = self.roles['branch_head']
        other_branch = self.roles['other_branch']
        self.client.login(username=branch_head.username, password='pwd12345678')

        payload = self._user_payload('forged_branch', branch_id=other_branch.id)
        self.client.post(reverse('branch_head_counselor_create'), payload)

        created = User.objects.filter(username='escalated_forged_branch').first()
        if created:
            self.assertEqual(created.branch_id, branch_head.branch_id, "forged branch field must be ignored, not honored")


class CrossBranchAccessTests(TestCase):
    """URL manipulation across branches must never succeed for non-admin roles."""

    def setUp(self):
        self.client = Client()
        self.roles = make_role_ladder()
        from leads.models import Lead
        self.other_branch_head = User.objects.create_user(
            username='adv_other_branch_head', password='pwd12345678', role=UserRole.BRANCH_HEAD, branch=self.roles['other_branch']
        )
        self.other_counselor = User.objects.create_user(
            username='adv_other_counselor', password='pwd12345678', role=UserRole.COUNSELOR, branch=self.roles['other_branch']
        )
        self.other_telecaller = User.objects.create_user(
            username='adv_other_telecaller', password='pwd12345678', role=UserRole.TELECALLER, branch=self.roles['other_branch']
        )
        self.other_branch_lead = Lead.objects.create(
            name="Other Branch Lead", phone="8880001111",
            branch=self.roles['other_branch'], assigned_telecaller=self.other_telecaller
        )

    def test_branch_head_cannot_view_other_branch_lead_via_url(self):
        self.client.login(username=self.roles['branch_head'].username, password='pwd12345678')
        resp = self.client.get(reverse('branch_head_lead_detail', args=[self.other_branch_lead.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_counselor_cannot_view_other_branch_lead_via_url(self):
        self.client.login(username=self.roles['counselor'].username, password='pwd12345678')
        resp = self.client.get(reverse('counselor_lead_detail', args=[self.other_branch_lead.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_telecaller_cannot_view_other_branch_lead_via_url(self):
        self.client.login(username=self.roles['telecaller'].username, password='pwd12345678')
        resp = self.client.get(reverse('telecaller_lead_detail', args=[self.other_branch_lead.pk]))
        self.assertEqual(resp.status_code, 403)

    def test_sales_head_without_access_cannot_view_other_branch_data(self):
        """Sales Head only has SalesHeadBranchAccess to 'branch', not
        'other_branch' - confirm they can't reach a Branch Head who lives
        in the branch they were never granted."""
        self.client.login(username=self.roles['sales_head'].username, password='pwd12345678')
        resp = self.client.get(reverse('sales_head_branch_head_detail', args=[self.other_branch_head.pk]))
        self.assertEqual(resp.status_code, 404)


class JsonEndpointRoleGatingTests(TestCase):
    """JSON-returning endpoints must be just as role-gated as HTML pages -
    returning JSON instead of a rendered page is not itself a security
    boundary."""

    def setUp(self):
        self.client = Client()
        self.roles = make_role_ladder()

    def test_non_admin_cannot_reach_admin_only_json_endpoints(self):
        for key in ('sales_head', 'branch_head', 'counselor', 'telecaller'):
            self.client.login(username=self.roles[key].username, password='pwd12345678')
            resp = self.client.post(
                reverse('admin_google_sheet_test_new'),
                {'spreadsheet_url': 'https://docs.google.com/spreadsheets/d/fake/edit'}
            )
            self.assertEqual(resp.status_code, 302, f"{key} should be redirected away from an admin-only JSON endpoint")
            self.client.logout()


class CsrfEnforcementTests(TestCase):
    """Confirm Django's CSRF protection is actually active on representative
    state-changing endpoints (i.e. nothing has accidentally disabled it)."""

    def setUp(self):
        self.csrf_client = CsrfClient(enforce_csrf_checks=True)
        self.roles = make_role_ladder()

    def test_post_without_csrf_token_is_rejected(self):
        self.csrf_client.login(username=self.roles['admin'].username, password='pwd12345678')
        resp = self.csrf_client.post(
            reverse('admin_branch_head_toggle_status', args=[self.roles['branch_head'].pk])
        )
        self.assertEqual(resp.status_code, 403, "a POST without a CSRF token must be rejected")

        self.roles['branch_head'].refresh_from_db()
        self.assertTrue(self.roles['branch_head'].is_active, "the toggle must not have taken effect")
