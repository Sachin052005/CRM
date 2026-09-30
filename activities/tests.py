from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from activities.models import Notification
from activities.services import create_notification

class NotificationSystemTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="notif_user",
            password="testpassword123",
            role=UserRole.TELECALLER
        )

    def test_create_and_query_notification(self):
        notif = create_notification(
            recipient=self.user,
            title="Lead Assigned",
            message="You have a new inquiry.",
            notification_type="lead_assigned"
        )
        self.assertIsNotNone(notif)
        self.assertEqual(notif.recipient, self.user)
        self.assertFalse(notif.is_read)

    def test_notifications_api(self):
        self.client.login(username="notif_user", password="testpassword123")
        notif = create_notification(
            recipient=self.user,
            title="Test Notice",
            message="Notice body",
            notification_type="info"
        )

        response = self.client.get(reverse('get_notifications_api'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['unread_count'], 1)
        self.assertEqual(len(data['notifications']), 1)
        self.assertEqual(data['notifications'][0]['title'], "Test Notice")

        # Mark single as read
        mark_res = self.client.post(reverse('mark_notification_read_api', args=[notif.pk]))
        self.assertEqual(mark_res.status_code, 200)
        notif.refresh_from_db()
        self.assertTrue(notif.is_read)

        # Mark all as read
        create_notification(recipient=self.user, title="Notice 2", message="Body 2")
        self.client.post(reverse('mark_all_notifications_read_api'))
        self.assertEqual(Notification.objects.filter(recipient=self.user, is_read=False).count(), 0)
