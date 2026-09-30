import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from channels.models import Channel, LeadConnection
from branches.models import Branch


User = get_user_model()

class ConfigurationModuleTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username='admin_test',
            email='admin@techpanda.test',
            password='TestPassword123!@#',
            role='ADMIN',
            is_staff=True,
            is_superuser=True
        )
        self.telecaller_user = User.objects.create_user(
            username='caller_test',
            email='caller@techpanda.test',
            password='TestPassword123!@#',
            role='TELECALLER'
        )
        self.branch = Branch.objects.create(name='Main Campus', status='Active')
        self.client.force_login(self.admin_user)

    def test_configuration_view_admin_access(self):
        # Admin can access
        url = reverse('admin_configuration')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Non-admin is restricted
        self.client.force_login(self.telecaller_user)
        response_non_admin = self.client.get(url)
        self.assertNotEqual(response_non_admin.status_code, 200)

    def test_default_lead_connections_created(self):
        url = reverse('admin_configuration')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Verify Meta / Facebook
        meta_conn = LeadConnection.objects.filter(name='Meta / Facebook').first()
        self.assertIsNotNone(meta_conn)
        self.assertEqual(meta_conn.status, 'Connected')
        self.assertEqual(meta_conn.page_name, 'TechPanda Academy')
        self.assertEqual(meta_conn.source_name, 'Meta')
        self.assertEqual(meta_conn.last_sync_display, '12:58 PM')

        # Verify Website
        web_conn = LeadConnection.objects.filter(name='Website').first()
        self.assertIsNotNone(web_conn)
        self.assertEqual(web_conn.status, 'Connected')
        self.assertEqual(web_conn.source_name, 'Website Lead Form')
        self.assertEqual(web_conn.last_sync_display, '12:57 PM')

    def test_configuration_page_ui_elements(self):
        url = reverse('admin_configuration')
        response = self.client.get(url)
        content = response.content.decode('utf-8')

        # Check required page text
        self.assertIn('CONFIGURATION', content)
        self.assertIn('Manage connections that automatically fetch leads into the CRM.', content)
        self.assertIn('+ Add Connection', content)
        self.assertIn('CONNECTED SOURCES', content)

        # Check Meta / Facebook details
        self.assertIn('Meta / Facebook', content)
        self.assertIn('TechPanda Academy', content)
        self.assertIn('Meta', content)
        self.assertIn('12:58 PM', content)

        # Check Website details
        self.assertIn('Website', content)
        self.assertIn('Website Lead Form', content)
        self.assertIn('12:57 PM', content)

        # Check buttons
        self.assertIn('Manage', content)
        self.assertIn('Sync Now', content)
        self.assertIn('Disconnect', content)

    def test_add_connection(self):
        add_url = reverse('admin_configuration_add')
        post_data = {
            'name': 'WhatsApp Marketing',
            'connection_type': 'WhatsApp',
            'page_name': 'TechPanda Support',
            'source_name': 'WhatsApp Inbound',
            'branch_id': self.branch.id,
            'webhook_url': 'https://crm.techpanda.academy/api/webhooks/whatsapp/',
        }
        response = self.client.post(add_url, post_data)
        self.assertEqual(response.status_code, 302)

        new_conn = LeadConnection.objects.filter(name='WhatsApp Marketing').first()
        self.assertIsNotNone(new_conn)
        self.assertEqual(new_conn.connection_type, 'WhatsApp')
        self.assertEqual(new_conn.page_name, 'TechPanda Support')
        self.assertEqual(new_conn.source_name, 'WhatsApp Inbound')
        self.assertEqual(new_conn.status, 'Connected')
        self.assertEqual(new_conn.branch, self.branch)

    def test_manage_connection_get_and_post(self):
        # Load defaults
        self.client.get(reverse('admin_configuration'))
        meta_conn = LeadConnection.objects.get(name='Meta / Facebook')

        manage_url = reverse('admin_configuration_manage', args=[meta_conn.id])

        # Test GET details (AJAX)
        get_res = self.client.get(manage_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(get_res.status_code, 200)
        json_data = get_res.json()
        self.assertEqual(json_data['name'], 'Meta / Facebook')
        self.assertEqual(json_data['page_name'], 'TechPanda Academy')

        # Test POST update (AJAX)
        post_res = self.client.post(
            manage_url,
            {
                'name': 'Meta / Facebook Ads Updated',
                'page_name': 'TechPanda Global Academy',
                'source_name': 'Meta Lead Gen',
                'status': 'Connected',
                'webhook_url': 'https://crm.techpanda.academy/api/webhooks/meta-custom/',
            },
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(post_res.status_code, 200)
        meta_conn.refresh_from_db()
        self.assertEqual(meta_conn.name, 'Meta / Facebook Ads Updated')
        self.assertEqual(meta_conn.page_name, 'TechPanda Global Academy')
        self.assertEqual(meta_conn.source_name, 'Meta Lead Gen')

    def test_sync_connection(self):
        self.client.get(reverse('admin_configuration'))
        web_conn = LeadConnection.objects.get(name='Website')

        sync_url = reverse('admin_configuration_sync', args=[web_conn.id])
        res = self.client.post(sync_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertIn('last_sync', data)

        web_conn.refresh_from_db()
        self.assertIsNotNone(web_conn.last_sync_time)
        self.assertEqual(web_conn.status, 'Connected')

    def test_disconnect_toggle(self):
        self.client.get(reverse('admin_configuration'))
        meta_conn = LeadConnection.objects.get(name='Meta / Facebook')
        self.assertEqual(meta_conn.status, 'Connected')

        disconnect_url = reverse('admin_configuration_disconnect', args=[meta_conn.id])

        # Disconnect
        res1 = self.client.post(disconnect_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res1.status_code, 200)
        meta_conn.refresh_from_db()
        self.assertEqual(meta_conn.status, 'Disconnected')

        # Reconnect
        res2 = self.client.post(disconnect_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res2.status_code, 200)
        meta_conn.refresh_from_db()
        self.assertEqual(meta_conn.status, 'Connected')


class MetaConnectionManageTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username='meta_admin',
            email='meta_admin@techpanda.test',
            password='TestPassword123!@#',
            role='ADMIN',
            is_staff=True,
            is_superuser=True
        )
        self.telecaller_user = User.objects.create_user(
            username='meta_caller',
            email='caller@techpanda.test',
            password='TestPassword123!@#',
            role='TELECALLER'
        )
        self.branch = Branch.objects.create(name='Chennai Campus', status='Active')
        self.channel = Channel.objects.create(name='Facebook', status='Active')
        self.meta_conn = LeadConnection.objects.create(
            name='Meta / Facebook',
            connection_type='Meta',
            status='Disconnected',
            page_name='TechPanda Academy',
            source_name='Meta',
            channel=self.channel,
            branch=self.branch,
            webhook_url='https://crm.techpanda.academy/api/webhooks/meta/leads/',
            config_details={}
        )
        self.client.force_login(self.admin_user)

    def test_meta_manage_view_render_initial_state(self):
        url = reverse('admin_meta_manage', args=[self.meta_conn.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # 1. Header & Description
        self.assertIn('MANAGE META / FACEBOOK CONNECTION', content)
        self.assertIn('Configure and verify the Meta connection for real-time lead fetching.', content)

        # 2. Meta App Credentials
        self.assertIn('Meta App ID', content)
        self.assertIn('Enter Meta App ID', content)
        self.assertIn('Meta App Secret', content)
        self.assertIn('Enter Meta App Secret', content)
        self.assertIn('The secret must remain protected', content)
        self.assertIn('Test App Credentials', content)

        # 3. Page Authorization & Page
        self.assertIn('Page Authorization', content)
        self.assertIn('Page Access Token', content)
        self.assertIn('Enter Page Access Token', content)
        self.assertIn('Validate Page Authorization', content)
        self.assertIn('Facebook Page', content)
        self.assertIn('Select Facebook Page', content)

        # 4. Lead Form
        self.assertIn('Lead Form', content)
        self.assertIn('Select Lead Form', content)
        self.assertIn('The Admin must select the Lead Form that should provide leads to the CRM.', content)

        # 5. Lead Ads Permissions
        self.assertIn('Lead Ads Permissions', content)
        self.assertIn('The connection must not become active unless the required Lead Ads permissions are successfully validated.', content)

        # 6. Real-Time Webhook
        self.assertIn('Real-Time Webhook', content)
        self.assertIn('Verify Webhook', content)

        # 7. Connection Test
        self.assertIn('CONNECTION TEST', content)

        # 8 & 9. Initial / Not Connected State
        self.assertIn('REAL-TIME CONNECTION NOT ACTIVE', content)
        self.assertIn('Complete the connection details and run all required tests before activating real-time lead fetching.', content)
        self.assertIn('Test Connection', content)

    def test_activation_rule_credentials_only_does_not_activate(self):
        """
        Rule: Do NOT mark Meta connection as active merely because Meta App ID and Secret are valid.
        """
        test_url = reverse('admin_meta_test_step', args=[self.meta_conn.id])

        # Test credentials only
        res = self.client.post(test_url, {
            'action': 'test_app_credentials',
            'app_id': '1029384756',
            'app_secret': 'secret_key_12345'
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['badge'], '🟢 Valid')

        # Check that connection is STILL NOT ACTIVE
        self.meta_conn.refresh_from_db()
        self.assertFalse(self.meta_conn.config_details.get('realtime_active', False))
        self.assertEqual(self.meta_conn.status, 'Disconnected')

        # Manage page still displays Not Active
        view_url = reverse('admin_meta_manage', args=[self.meta_conn.id])
        view_res = self.client.get(view_url)
        content = view_res.content.decode('utf-8')
        self.assertIn('REAL-TIME CONNECTION NOT ACTIVE', content)

    def test_step_by_step_testing_flow(self):
        test_url = reverse('admin_meta_test_step', args=[self.meta_conn.id])

        # 1. Invalid App credentials
        res_bad_cred = self.client.post(test_url, {
            'action': 'test_app_credentials',
            'app_id': '12',
            'app_secret': '34'
        })
        self.assertFalse(res_bad_cred.json()['success'])

        # 1. Valid App credentials
        res_good_cred = self.client.post(test_url, {
            'action': 'test_app_credentials',
            'app_id': '987654321',
            'app_secret': 'super_secret_meta_key_2026'
        })
        self.assertTrue(res_good_cred.json()['success'])

        # 2. Invalid Page Access Token
        res_bad_token = self.client.post(test_url, {
            'action': 'validate_page_auth',
            'page_access_token': 'short'
        })
        self.assertFalse(res_bad_token.json()['success'])

        # 2. Valid Page Access Token
        res_good_token = self.client.post(test_url, {
            'action': 'validate_page_auth',
            'page_access_token': 'EAAGNO4ValidLongToken1234567890'
        })
        self.assertTrue(res_good_token.json()['success'])
        self.assertEqual(res_good_token.json()['page_auth_badge'], '🟢 Valid')
        self.assertEqual(res_good_token.json()['permissions_badge'], '🟢 Valid')

        # 3. Select Facebook Page
        res_page = self.client.post(test_url, {
            'action': 'select_page',
            'page_name': 'TechPanda Academy'
        })
        self.assertTrue(res_page.json()['success'])

        # 4. Select Lead Form
        res_form = self.client.post(test_url, {
            'action': 'select_form',
            'form_name': 'TechPanda - Data Science Course Lead Form'
        })
        self.assertTrue(res_form.json()['success'])

        # 5. Verify Webhook
        res_hook = self.client.post(test_url, {
            'action': 'verify_webhook'
        })
        self.assertTrue(res_hook.json()['success'])

    def test_full_connection_test_and_activation(self):
        test_url = reverse('admin_meta_test_step', args=[self.meta_conn.id])

        # Run test_connection with all valid inputs
        res = self.client.post(test_url, {
            'action': 'test_connection',
            'app_id': '9876543210',
            'app_secret': 'meta_super_secret_app_key',
            'page_access_token': 'EAAGNO4ValidMetaAccessTokenXYZ',
            'page_name': 'TechPanda Academy',
            'form_name': 'TechPanda - Data Science Course Lead Form'
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['realtime_active'])
        self.assertEqual(data['statuses']['app_credentials'], '🟢 Valid')
        self.assertEqual(data['statuses']['page_auth'], '🟢 Valid')
        self.assertEqual(data['statuses']['lead_ads_permissions'], '🟢 Valid')
        self.assertEqual(data['statuses']['facebook_page'], '🟢 Connected')
        self.assertEqual(data['statuses']['lead_form'], '🟢 Connected')
        self.assertEqual(data['statuses']['webhook'], '🟢 Verified')
        self.assertEqual(data['statuses']['meta_api_test'], '🟢 Successful')
        self.assertEqual(data['statuses']['lead_event_test'], '🟢 Successful')

        # Verify DB updated
        self.meta_conn.refresh_from_db()
        self.assertEqual(self.meta_conn.status, 'Connected')
        self.assertTrue(self.meta_conn.config_details.get('realtime_active'))

        # Verify Page renders Active state
        view_url = reverse('admin_meta_manage', args=[self.meta_conn.id])
        view_res = self.client.get(view_url)
        content = view_res.content.decode('utf-8')
        self.assertIn('REAL-TIME CONNECTION ACTIVE', content)
        self.assertIn('New Meta leads will be received and imported into the CRM automatically.', content)
        self.assertIn('Save Connection', content)
        self.assertIn('Sync Now', content)
        self.assertIn('Disconnect', content)

    def test_sync_and_disconnect(self):
        # Sync
        sync_url = reverse('admin_meta_sync_now', args=[self.meta_conn.id])
        res_sync = self.client.post(sync_url)
        self.assertEqual(res_sync.status_code, 200)
        self.assertTrue(res_sync.json()['success'])

        # Disconnect
        disc_url = reverse('admin_meta_disconnect', args=[self.meta_conn.id])
        res_disc = self.client.post(disc_url)
        self.assertEqual(res_disc.status_code, 200)
        self.meta_conn.refresh_from_db()
        self.assertEqual(self.meta_conn.status, 'Disconnected')
        self.assertFalse(self.meta_conn.config_details.get('realtime_active', False))

    def test_meta_webhook_challenge_and_lead_ingestion(self):
        from leads.models import Lead

        webhook_url = reverse('meta_webhook_endpoint')

        # 1. Verification Challenge (GET)
        res_challenge = self.client.get(webhook_url, {
            'hub.mode': 'subscribe',
            'hub.challenge': '1158201444',
            'hub.verify_token': 'techpanda_meta_verify_token_2026'
        })
        self.assertEqual(res_challenge.status_code, 200)
        self.assertEqual(res_challenge.content.decode('utf-8'), '1158201444')

        # 2. Ingest Lead (POST)
        post_payload = {
            'name': 'Kavitha Ramesh',
            'phone': '9876543299',
            'email': 'kavitha@example.com',
            'source': 'Meta',
            'notes': 'Meta Lead Ad: Data Science Course'
        }
        res_lead = self.client.post(
            webhook_url,
            data=json.dumps(post_payload),
            content_type='application/json'
        )
        self.assertEqual(res_lead.status_code, 200)
        lead_created = Lead.objects.filter(phone='9876543299').first()
        self.assertIsNotNone(lead_created)
        self.assertEqual(lead_created.name, 'Kavitha Ramesh')
        self.assertEqual(lead_created.source, 'Meta')

        # 3. Duplicate Detection on Webhook: Same phone submitted again
        res_dup = self.client.post(
            webhook_url,
            data=json.dumps({
                'name': 'Kavitha Ramesh Updated',
                'phone': '9876543299',
                'email': 'kavitha.new@example.com',
            }),
            content_type='application/json'
        )
        self.assertEqual(res_dup.status_code, 200)
        # Verify no duplicate lead was created
        self.assertEqual(Lead.objects.filter(phone='9876543299').count(), 1)

