from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch, SalesHeadBranchAccess

class AccountsAndAuthTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.create(name="Central Campus", phone="9999988888")

        # Admin user
        self.admin = User.objects.create_user(
            username="testadmin",
            email="admin@test.com",
            password="adminpassword123",
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True
        )

        # Sales Head user (formerly "Manager")
        self.manager = User.objects.create_user(
            username="testmanager",
            email="manager@test.com",
            password="managerpassword123",
            role=UserRole.SALES_HEAD,
            branch=self.branch
        )
        SalesHeadBranchAccess.objects.create(sales_head=self.manager, branch=self.branch)

        # Telecaller user
        self.telecaller = User.objects.create_user(
            username="testtelecaller",
            email="telecaller@test.com",
            password="callerpassword123",
            role=UserRole.TELECALLER,
            branch=self.branch
        )

    def test_admin_login_and_redirect(self):
        response = self.client.post(reverse('admin_login'), {
            'username': 'testadmin',
            'password': 'adminpassword123'
        })
        self.assertRedirects(response, reverse('admin_dashboard'))

    def test_manager_registration_and_login(self):
        # Registration
        reg_response = self.client.post(reverse('manager_register'), {
            'first_name': 'John',
            'last_name': 'Manager',
            'username': 'newmanager',
            'email': 'newmanager@test.com',
            'phone': '9876543210',
            'password': 'safePassword123!',
            'confirm_password': 'safePassword123!'
        })
        self.assertRedirects(reg_response, reverse('manager_login'))
        new_mgr = User.objects.get(username='newmanager')
        self.assertEqual(new_mgr.role, UserRole.SALES_HEAD)

        # Login
        login_response = self.client.post(reverse('manager_login'), {
            'username': 'newmanager',
            'password': 'safePassword123!'
        })
        self.assertRedirects(login_response, reverse('manager_dashboard'))

    def test_telecaller_registration_and_login(self):
        # Registration
        reg_response = self.client.post(reverse('telecaller_register'), {
            'first_name': 'Alice',
            'last_name': 'Caller',
            'username': 'newcaller',
            'email': 'newcaller@test.com',
            'phone': '9876543211',
            'password': 'safePassword123!',
            'confirm_password': 'safePassword123!'
        })
        self.assertRedirects(reg_response, reverse('telecaller_login'))
        new_tc = User.objects.get(username='newcaller')
        self.assertEqual(new_tc.role, UserRole.TELECALLER)

        # Login
        login_response = self.client.post(reverse('telecaller_login'), {
            'username': 'newcaller',
            'password': 'safePassword123!'
        })
        self.assertRedirects(login_response, reverse('telecaller_dashboard'))

    def test_unauthorized_dashboard_access_blocked(self):
        # Telecaller trying to access Admin dashboard
        self.client.login(username='testtelecaller', password='callerpassword123')
        response = self.client.get(reverse('admin_dashboard'))
        # Should redirect to telecaller dashboard
        self.assertRedirects(response, reverse('telecaller_dashboard'))

        # Manager trying to access Admin dashboard
        self.client.login(username='testmanager', password='managerpassword123')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertRedirects(response, reverse('manager_dashboard'))

    def test_manager_telecaller_relationship(self):
        from accounts.permissions import get_accessible_branch_ids
        self.assertIn(self.telecaller.branch_id, get_accessible_branch_ids(self.manager))
        self.assertIn(self.branch, [access.branch for access in self.manager.branch_access.all()])

    def test_login_with_email(self):
        # Admin email login
        response = self.client.post(reverse('login'), {
            'username': 'admin@test.com',
            'password': 'adminpassword123'
        })
        self.assertRedirects(response, reverse('admin_dashboard'))

        # Telecaller email login
        self.client.logout()
        response = self.client.post(reverse('login'), {
            'username': 'telecaller@test.com',
            'password': 'callerpassword123'
        })
        self.assertRedirects(response, reverse('telecaller_dashboard'))

    def test_password_reset_views(self):
        response = self.client.get(reverse('password_reset'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reset Password")

    def test_strong_password_rules(self):
        from accounts.validators import ComplexityValidator
        from django.core.exceptions import ValidationError

        validator = ComplexityValidator(min_length=8)

        # Valid strong password
        validator.validate("ValidStrongPass123!")

        # Too short
        with self.assertRaises(ValidationError) as ctx:
            validator.validate("Short1!")
        self.assertTrue(any("at least 8 characters" in msg for msg in ctx.exception.messages))

        # Missing uppercase
        with self.assertRaises(ValidationError) as ctx:
            validator.validate("nouppercase123!")
        self.assertTrue(any("uppercase letter" in msg for msg in ctx.exception.messages))

        # Missing lowercase
        with self.assertRaises(ValidationError) as ctx:
            validator.validate("NOLOWERCASE123!")
        self.assertTrue(any("lowercase letter" in msg for msg in ctx.exception.messages))

        # Missing digit
        with self.assertRaises(ValidationError) as ctx:
            validator.validate("NoDigitsHere!!")
        self.assertTrue(any("numeric digit" in msg for msg in ctx.exception.messages))

        # Missing special character
        with self.assertRaises(ValidationError) as ctx:
            validator.validate("NoSpecialChar123")
        self.assertTrue(any("special character" in msg for msg in ctx.exception.messages))

        # Contains username
        with self.assertRaises(ValidationError) as ctx:
            user = User(username="rajesh", email="rajesh@test.com")
            validator.validate("SecretRajesh123!", user=user)
        self.assertTrue(any("contain your username" in msg for msg in ctx.exception.messages))


class LeadPermissionFunctionsTests(TestCase):
    """Covers the centralized lead/user authorization helpers added for the hierarchy rework."""

    def setUp(self):
        self.branch_a = Branch.objects.create(name="Perm Branch A")
        self.branch_b = Branch.objects.create(name="Perm Branch B")

        self.admin = User.objects.create_user(
            username="perm_admin", password="pwd", role=UserRole.ADMIN, is_staff=True, is_superuser=True
        )
        self.sales_head_a = User.objects.create_user(username="perm_sh_a", password="pwd", role=UserRole.SALES_HEAD)
        SalesHeadBranchAccess.objects.create(sales_head=self.sales_head_a, branch=self.branch_a)
        self.branch_head_a = User.objects.create_user(
            username="perm_bh_a", password="pwd", role=UserRole.BRANCH_HEAD, branch=self.branch_a
        )
        self.branch_head_b = User.objects.create_user(
            username="perm_bh_b", password="pwd", role=UserRole.BRANCH_HEAD, branch=self.branch_b
        )
        self.counselor_a = User.objects.create_user(
            username="perm_counselor_a", password="pwd", role=UserRole.COUNSELOR, branch=self.branch_a
        )
        self.telecaller_a = User.objects.create_user(
            username="perm_tc_a", password="pwd", role=UserRole.TELECALLER, branch=self.branch_a
        )
        self.telecaller_b = User.objects.create_user(
            username="perm_tc_b", password="pwd", role=UserRole.TELECALLER, branch=self.branch_b
        )

    def test_can_reassign_lead_rejects_cross_branch_target(self):
        from accounts.permissions import can_reassign_lead
        from leads.models import Lead

        lead = Lead.objects.create(name="Perm Lead", phone="9000000010", branch=self.branch_a)

        # Sales Head A may reassign within branch A...
        self.assertTrue(can_reassign_lead(self.sales_head_a, lead, self.telecaller_a))
        # ...but not to a telecaller belonging to branch B.
        self.assertFalse(can_reassign_lead(self.sales_head_a, lead, self.telecaller_b))
        # Admin may override across branches.
        self.assertTrue(can_reassign_lead(self.admin, lead, self.telecaller_b))

    def test_can_create_user_role_scoping(self):
        from accounts.permissions import can_create_user

        # Admin can create anyone anywhere.
        self.assertTrue(can_create_user(self.admin, UserRole.SALES_HEAD, self.branch_a))

        # Sales Head can create a Branch Head only in an accessible branch.
        self.assertTrue(can_create_user(self.sales_head_a, UserRole.BRANCH_HEAD, self.branch_a))
        self.assertFalse(can_create_user(self.sales_head_a, UserRole.BRANCH_HEAD, self.branch_b))
        self.assertFalse(can_create_user(self.sales_head_a, UserRole.COUNSELOR, self.branch_a))

        # Branch Head can create Counselors/Telecallers only in their own branch.
        self.assertTrue(can_create_user(self.branch_head_a, UserRole.COUNSELOR, self.branch_a))
        self.assertTrue(can_create_user(self.branch_head_a, UserRole.TELECALLER, self.branch_a))
        self.assertFalse(can_create_user(self.branch_head_a, UserRole.COUNSELOR, self.branch_b))
        self.assertFalse(can_create_user(self.branch_head_a, UserRole.BRANCH_HEAD, self.branch_a))

        # Counselor can create only Telecallers in their own branch.
        self.assertTrue(can_create_user(self.counselor_a, UserRole.TELECALLER, self.branch_a))
        self.assertFalse(can_create_user(self.counselor_a, UserRole.TELECALLER, self.branch_b))
        self.assertFalse(can_create_user(self.counselor_a, UserRole.COUNSELOR, self.branch_a))

        # Telecaller cannot create anyone.
        self.assertFalse(can_create_user(self.telecaller_a, UserRole.TELECALLER, self.branch_a))

    def test_can_manage_user_scoping(self):
        from accounts.permissions import can_manage_user

        self.assertTrue(can_manage_user(self.sales_head_a, self.branch_head_a))
        self.assertFalse(can_manage_user(self.sales_head_a, self.branch_head_b))
        self.assertTrue(can_manage_user(self.branch_head_a, self.telecaller_a))
        self.assertFalse(can_manage_user(self.branch_head_a, self.telecaller_b))
        self.assertFalse(can_manage_user(self.telecaller_a, self.telecaller_b))

