"""
Tests for connection-specific connect/disconnect isolation across Google Sheet
(and Google Form) connections.

Root causes under test:
1. admin_google_sheet_disconnect fell back to deactivating EVERY GoogleSheetConnection
   (and every GoogleFormConnection) when no connection_id was supplied.
2. admin_google_form_disconnect unconditionally deactivated every GoogleSheetConnection
   and deleted every offline Lead, regardless of whether any Google Sheet was involved.
3. Connection identity was keyed on spreadsheet_id alone, so a second worksheet/tab of
   the SAME spreadsheet silently overwrote the first tab's connection instead of
   coexisting as an independent connection.
"""
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from channels.models import Channel
from leads.models import Lead, GoogleSheetConnection, GoogleFormConnection


def _rows(prefix, count, start_digit='7'):
    return [
        {'_row_index': i + 2, 'Name': f'{prefix} Lead {i+1}', 'Phone': f'9{start_digit}{i:08d}'}
        for i in range(count)
    ]


class MultiSpreadsheetIsolationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='isolation_admin',
            password='AdminPassword@2026',
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.admin)
        self.walk_in = Channel.objects.create(name='Walk-in', status='Active')
        self.facebook = Channel.objects.create(name='Facebook', status='Active')
        self.instagram = Channel.objects.create(name='Instagram', status='Active')
        self.google_ads = Channel.objects.create(name='Google Ads', status='Active')

    def _connect(self, spreadsheet_id, channel, rows, worksheet_name=None):
        url = f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit'
        headers = ['Name', 'Phone']
        with patch('leads.views.fetch_sheet_data', return_value=(headers, rows)), \
             patch('leads.views.fetch_spreadsheet_metadata', return_value={'title': spreadsheet_id}), \
             patch('leads.google_sheets.fetch_sheet_data', return_value=(headers, rows)):
            payload = {
                'name': f'Sheet {spreadsheet_id}',
                'spreadsheet_url': url,
                'channel_id': str(channel.id),
            }
            if worksheet_name:
                payload['worksheet_name'] = worksheet_name
            res = self.client.post(reverse('admin_google_sheet_connect'), payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'), data)
        return GoogleSheetConnection.objects.get(pk=data['connection_id'])

    # Master prompt Tests A/B/C (section 46) and Test 47 (4 spreadsheets)
    def test_connecting_additional_spreadsheets_never_deactivates_existing_ones(self):
        conn_a = self._connect('sheet_A', self.walk_in, _rows('A', 5, '1'))
        self.assertTrue(conn_a.is_active)

        conn_b = self._connect('sheet_B', self.facebook, _rows('B', 5, '2'))
        conn_a.refresh_from_db()
        self.assertTrue(conn_a.is_active)
        self.assertTrue(conn_b.is_active)

        conn_c = self._connect('sheet_C', self.instagram, _rows('C', 5, '3'))
        conn_a.refresh_from_db()
        conn_b.refresh_from_db()
        self.assertTrue(conn_a.is_active)
        self.assertTrue(conn_b.is_active)
        self.assertTrue(conn_c.is_active)

        conn_d = self._connect('sheet_D', self.google_ads, _rows('D', 5, '4'))
        for c in (conn_a, conn_b, conn_c):
            c.refresh_from_db()
            self.assertTrue(c.is_active)
        self.assertTrue(conn_d.is_active)
        self.assertEqual(GoogleSheetConnection.objects.filter(is_active=True).count(), 4)

    # Master prompt Test 48 - disconnect is connection-specific, reconnect restores it
    def test_disconnect_is_connection_specific_and_reconnect_works(self):
        conn_a = self._connect('disc_A', self.walk_in, _rows('DA', 3, '5'))
        conn_b = self._connect('disc_B', self.facebook, _rows('DB', 3, '6'))
        conn_c = self._connect('disc_C', self.instagram, _rows('DC', 3, '7'))
        conn_d = self._connect('disc_D', self.google_ads, _rows('DD', 3, '8'))

        disc_res = self.client.post(
            reverse('admin_google_sheet_disconnect', args=[conn_b.id])
        )
        self.assertEqual(disc_res.status_code, 200)

        conn_a.refresh_from_db()
        conn_b.refresh_from_db()
        conn_c.refresh_from_db()
        conn_d.refresh_from_db()
        self.assertTrue(conn_a.is_active)
        self.assertFalse(conn_b.is_active)
        self.assertTrue(conn_c.is_active)
        self.assertTrue(conn_d.is_active)

        # Leads already imported from B must NOT be deleted by disconnect
        self.assertEqual(Lead.objects.filter(channel=self.facebook).count(), 3)

        # Reconnect B
        self._connect('disc_B', self.facebook, _rows('DB', 3, '6'))
        conn_a.refresh_from_db()
        conn_b.refresh_from_db()
        conn_c.refresh_from_db()
        conn_d.refresh_from_db()
        self.assertTrue(conn_a.is_active)
        self.assertTrue(conn_b.is_active)
        self.assertTrue(conn_c.is_active)
        self.assertTrue(conn_d.is_active)

    # Disconnect with no connection_id must be rejected, not wipe everything (Section 7/70)
    def test_disconnect_without_id_does_not_globally_wipe_connections(self):
        conn_a = self._connect('noid_A', self.walk_in, _rows('NA', 2, '9'))
        conn_b = self._connect('noid_B', self.facebook, _rows('NB', 2, '0'))

        res = self.client.post(reverse('admin_offline_leads_disconnect'))
        self.assertEqual(res.status_code, 400)

        conn_a.refresh_from_db()
        conn_b.refresh_from_db()
        self.assertTrue(conn_a.is_active)
        self.assertTrue(conn_b.is_active)

    # Master prompt Test 58 - Google Form disconnect must not affect Google Sheets
    def test_google_form_disconnect_does_not_affect_google_sheets(self):
        conn_a = self._connect('gf_isolation_A', self.walk_in, _rows('GFA', 4, '1'))
        conn_b = self._connect('gf_isolation_B', self.facebook, _rows('GFB', 4, '2'))

        gform = GoogleFormConnection.objects.create(
            name='Google Form Leads',
            form_url='https://docs.google.com/forms/d/e/abc/viewform',
            is_active=True,
        )

        res = self.client.post(reverse('admin_google_form_disconnect'))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()['success'])

        gform.refresh_from_db()
        conn_a.refresh_from_db()
        conn_b.refresh_from_db()
        self.assertFalse(gform.is_active)
        self.assertTrue(conn_a.is_active)
        self.assertTrue(conn_b.is_active)

        # Leads from both sheets must still exist - Google Form disconnect must not delete them
        self.assertEqual(Lead.objects.filter(channel=self.walk_in).count(), 4)
        self.assertEqual(Lead.objects.filter(channel=self.facebook).count(), 4)

    # Master prompt Section 5 - same spreadsheet, two worksheets/tabs, two independent connections
    def test_same_spreadsheet_different_worksheet_creates_independent_connection(self):
        conn_tab1 = self._connect(
            'shared_sheet_id', self.walk_in, _rows('Tab1', 3, '3'), worksheet_name='WalkInTab'
        )
        conn_tab2 = self._connect(
            'shared_sheet_id', self.facebook, _rows('Tab2', 3, '4'), worksheet_name='FacebookTab'
        )

        self.assertNotEqual(conn_tab1.id, conn_tab2.id)
        conn_tab1.refresh_from_db()
        self.assertTrue(conn_tab1.is_active)
        self.assertTrue(conn_tab2.is_active)
        self.assertEqual(conn_tab1.channel_id, self.walk_in.id)
        self.assertEqual(conn_tab2.channel_id, self.facebook.id)
        self.assertEqual(Lead.objects.filter(channel=self.walk_in).count(), 3)
        self.assertEqual(Lead.objects.filter(channel=self.facebook).count(), 3)
        self.assertEqual(
            GoogleSheetConnection.objects.filter(spreadsheet_id='shared_sheet_id').count(), 2
        )
