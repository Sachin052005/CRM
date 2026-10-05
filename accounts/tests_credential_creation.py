from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch, SalesHeadBranchAccess
from leads.models import TelecallerLeadSetup
from managers.forms import AdminManagerCreateForm
from branch_heads.forms import BranchHeadCreateForm, BranchHeadCounselorCreateForm
from counselors.forms import AdminCounselorCreateForm
from telecallers.forms import AdminTelecallerCreateForm, BranchHeadTelecallerCreateForm


class CredentialCreationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username="testadmin",
            email="admin@test.com",
            password="AdminPassword123!",
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True
        )
        self.branch_a = Branch.objects.get_or_create(name="Branch Alpha", status="Active")[0]
        self.branch_b = Branch.objects.get_or_create(name="Branch Beta", status="Active")[0]

        # Pre-existing counselor for telecaller assignment tests
        self.counselor_a = User.objects.create_user(
            username="counselor_alpha",
            email="counselor_a@test.com",
            password="Password123!",
            role=UserRole.COUNSELOR,
            branch=self.branch_a,
            is_active=True
        )

    def test_admin_create_sales_head_view_and_form(self):
        """Admin creates a Sales Head via /admin/managers/create/.
        Must NOT raise ValueError: 'AdminManagerCreateForm' has no field named 'counselor'.
        Must create User with role=SALES_HEAD."""
        self.client.login(username="testadmin", password="AdminPassword123!")

        url = reverse('admin_manager_create')
        data = {
            'first_name': 'Sales',
            'last_name': 'Leader',
            'username': 'saleshead_new',
            'email': 'saleshead_new@test.com',
            'phone': '9876543210',
            'password': 'ComplexPassword123!',
            'confirm_password': 'ComplexPassword123!',
            'branches': [self.branch_a.id, self.branch_b.id],
            'is_active': 'on'
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('admin_managers_list'))

        user = User.objects.get(username='saleshead_new')
        self.assertEqual(user.role, UserRole.SALES_HEAD)
        self.assertIsNone(user.counselor)
        self.assertTrue(user.check_password('ComplexPassword123!'))

        # Verify branch access
        access_branches = set(SalesHeadBranchAccess.objects.filter(sales_head=user).values_list('branch_id', flat=True))
        self.assertEqual(access_branches, {self.branch_a.id, self.branch_b.id})

    def test_admin_create_branch_head_view_and_form(self):
        """Admin creates a Branch Head via /admin/branch-heads/create/.
        Must NOT raise ValueError: 'BranchHeadCreateForm' has no field named 'counselor'.
        Must create User with role=BRANCH_HEAD."""
        self.client.login(username="testadmin", password="AdminPassword123!")

        url = reverse('admin_branch_head_create')
        data = {
            'first_name': 'Branch',
            'last_name': 'Director',
            'username': 'branchhead_new',
            'email': 'branchhead_new@test.com',
            'phone': '9876543211',
            'branch': self.branch_a.id,
            'password': 'ComplexPassword123!',
            'confirm_password': 'ComplexPassword123!',
            'is_active': 'on'
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('admin_branch_heads_list'))

        user = User.objects.get(username='branchhead_new')
        self.assertEqual(user.role, UserRole.BRANCH_HEAD)
        self.assertEqual(user.branch, self.branch_a)
        self.assertIsNone(user.counselor)
        self.assertTrue(user.check_password('ComplexPassword123!'))

    def test_admin_create_counselor_view_and_form(self):
        """Admin creates a Counselor via /admin/counselors/create/.
        Must NOT raise ValueError: 'AdminCounselorCreateForm' has no field named 'counselor'.
        Must create User with role=COUNSELOR."""
        self.client.login(username="testadmin", password="AdminPassword123!")

        url = reverse('admin_counselor_create')
        data = {
            'first_name': 'Senior',
            'last_name': 'Counselor',
            'username': 'counselor_new',
            'email': 'counselor_new@test.com',
            'phone': '9876543212',
            'branch': self.branch_a.id,
            'password': 'ComplexPassword123!',
            'confirm_password': 'ComplexPassword123!',
            'is_active': 'on'
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('admin_counselors_list'))

        user = User.objects.get(username='counselor_new')
        self.assertEqual(user.role, UserRole.COUNSELOR)
        self.assertEqual(user.branch, self.branch_a)
        self.assertIsNone(user.counselor)
        self.assertTrue(user.check_password('ComplexPassword123!'))

    def test_admin_create_telecaller_success(self):
        """Admin creates a Telecaller via /admin/telecallers/create/ assigned to an active Counselor.
        Must create User with role=TELECALLER, correct counselor and inherited branch."""
        self.client.login(username="testadmin", password="AdminPassword123!")

        url = reverse('admin_telecaller_create')
        data = {
            'first_name': 'Active',
            'last_name': 'Caller',
            'username': 'telecaller_new',
            'email': 'telecaller_new@test.com',
            'phone': '9876543213',
            'counselor': self.counselor_a.id,
            'branch': self.branch_a.id,
            'password': 'ComplexPassword123!',
            'confirm_password': 'ComplexPassword123!',
            'is_active': 'on'
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('admin_telecallers_list'))

        user = User.objects.get(username='telecaller_new')
        self.assertEqual(user.role, UserRole.TELECALLER)
        self.assertEqual(user.counselor, self.counselor_a)
        self.assertEqual(user.branch, self.branch_a)
        self.assertTrue(user.check_password('ComplexPassword123!'))

        # Verify TelecallerLeadSetup was created
        setup_exists = TelecallerLeadSetup.objects.filter(telecaller=user, branch=self.branch_a).exists()
        self.assertTrue(setup_exists)

    def test_admin_create_telecaller_missing_counselor_validation(self):
        """Creating a Telecaller without a Counselor must fail validation gracefully.
        Must NOT raise 500 or ValueError; must return form error on 'counselor' field."""
        self.client.login(username="testadmin", password="AdminPassword123!")

        url = reverse('admin_telecaller_create')
        data = {
            'first_name': 'No',
            'last_name': 'Counselor',
            'username': 'telecaller_nocounselor',
            'email': 'telecaller_nocounselor@test.com',
            'phone': '9876543214',
            'counselor': '',  # Missing counselor
            'branch': self.branch_a.id,
            'password': 'ComplexPassword123!',
            'confirm_password': 'ComplexPassword123!',
            'is_active': 'on'
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertIn('counselor', form.errors)
        self.assertFalse(User.objects.filter(username='telecaller_nocounselor').exists())

    def test_admin_create_telecaller_mismatched_branch_counselor(self):
        """Assigning a counselor from Branch A while selecting Branch B should fail with branch mismatch error."""
        self.client.login(username="testadmin", password="AdminPassword123!")

        url = reverse('admin_telecaller_create')
        data = {
            'first_name': 'Mismatch',
            'last_name': 'Branch',
            'username': 'telecaller_mismatch',
            'email': 'telecaller_mismatch@test.com',
            'phone': '9876543215',
            'counselor': self.counselor_a.id,  # Branch Alpha
            'branch': self.branch_b.id,       # Branch Beta
            'password': 'ComplexPassword123!',
            'confirm_password': 'ComplexPassword123!',
            'is_active': 'on'
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertIn('counselor', form.errors)
        self.assertFalse(User.objects.filter(username='telecaller_mismatch').exists())

    def test_branch_head_counselor_create_form(self):
        """BranchHeadCounselorCreateForm must assign role=COUNSELOR and not fail on counselor validation."""
        form = BranchHeadCounselorCreateForm(data={
            'first_name': 'BH',
            'last_name': 'Counselor',
            'username': 'bh_counselor_1',
            'email': 'bh_counselor_1@test.com',
            'phone': '9876543216',
            'password': 'ComplexPassword123!',
            'confirm_password': 'ComplexPassword123!',
            'is_active': True,
        })
        self.assertTrue(form.is_valid(), form.errors)
        counselor = form.save(commit=True, branch=self.branch_a)
        self.assertEqual(counselor.role, UserRole.COUNSELOR)
        self.assertEqual(counselor.branch, self.branch_a)
        self.assertIsNone(counselor.counselor)

    def test_branch_head_telecaller_create_form(self):
        """BranchHeadTelecallerCreateForm must assign role=TELECALLER and require counselor."""
        # Valid case
        form = BranchHeadTelecallerCreateForm(branch=self.branch_a, data={
            'first_name': 'BH',
            'last_name': 'Telecaller',
            'username': 'bh_telecaller_1',
            'email': 'bh_telecaller_1@test.com',
            'phone': '9876543217',
            'counselor': self.counselor_a.id,
            'password': 'ComplexPassword123!',
            'confirm_password': 'ComplexPassword123!',
            'is_active': True,
        })
        self.assertTrue(form.is_valid(), form.errors)
        telecaller = form.save(commit=True)
        self.assertEqual(telecaller.role, UserRole.TELECALLER)
        self.assertEqual(telecaller.branch, self.branch_a)
        self.assertEqual(telecaller.counselor, self.counselor_a)

        # Missing counselor case
        form_invalid = BranchHeadTelecallerCreateForm(branch=self.branch_a, data={
            'first_name': 'BH',
            'last_name': 'Telecaller2',
            'username': 'bh_telecaller_2',
            'email': 'bh_telecaller_2@test.com',
            'phone': '9876543218',
            'counselor': '',
            'password': 'ComplexPassword123!',
            'confirm_password': 'ComplexPassword123!',
            'is_active': True,
        })
        self.assertFalse(form_invalid.is_valid())
        self.assertIn('counselor', form_invalid.errors)
