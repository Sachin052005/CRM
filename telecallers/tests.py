from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch
from activities.models import Activity

class TelecallerAssignmentTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(username="admin_assign", password="pwd")
        self.branch = Branch.objects.create(name="North Campus")
        self.mgr_1 = User.objects.create_user(username="mgr_one", password="pwd", role=UserRole.MANAGER, branch=self.branch)
        self.mgr_2 = User.objects.create_user(username="mgr_two", password="pwd", role=UserRole.MANAGER, branch=self.branch)
        self.telecaller = User.objects.create_user(
            username="tc_switch", password="pwd", role=UserRole.TELECALLER, manager=self.mgr_1, branch=self.branch
        )

    def test_admin_reassigns_telecaller(self):
        self.client.login(username='admin_assign', password='pwd')
        response = self.client.post(reverse('admin_telecaller_assign', args=[self.telecaller.pk]), {
            'manager': self.mgr_2.pk
        })
        self.assertRedirects(response, reverse('admin_telecallers_list'))

        self.telecaller.refresh_from_db()
        self.assertEqual(self.telecaller.manager, self.mgr_2)

        # Verify activity was recorded
        act = Activity.objects.filter(action="Telecaller Reassigned").first()
        self.assertIsNotNone(act)
        self.assertIn("mgr_one", act.description)
        self.assertIn("mgr_two", act.description)

    def test_admin_change_telecaller_password(self):
        self.client.login(username='admin_assign', password='pwd')
        url = reverse('admin_telecaller_change_password', args=[self.telecaller.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        post_response = self.client.post(url, {
            'new_password1': 'NewCallerSecret123!',
            'new_password2': 'NewCallerSecret123!'
        })
        self.assertRedirects(post_response, reverse('admin_telecaller_detail', args=[self.telecaller.pk]))

        self.telecaller.refresh_from_db()
        self.assertTrue(self.telecaller.check_password('NewCallerSecret123!'))

