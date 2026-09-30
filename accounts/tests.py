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

