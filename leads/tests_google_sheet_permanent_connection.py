"""
Acceptance tests for: "Connected until explicit Disconnect - sync failure is not disconnection."

Verifies the specific scenarios from the Google Sheet permanent-connection master prompt
that are not already covered by tests_multi_spreadsheet_isolation.py (which already proves
connect/disconnect isolation across multiple connections) or tests_google_sheets.py (which
already proves basic pause/resume toggling).

This file focuses on what those do NOT cover: that a SYNC FAILURE - as opposed to an
explicit user Disconnect/Pause - never changes connection_state (is_active), never affects
sibling connections, and that previously-synced data, History, and "View in Table" all keep
working through repeated failures, across requests (simulating browser refresh / a fresh
Django process reading only from the database).
"""
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from channels.models import Channel
from leads.models import Lead, GoogleSheetConnection, GoogleSheetSyncHistory
from leads.google_sheets import sync_google_sheet


def _rows(prefix, count, start_digit='1'):
    return [
        {'_row_index': i + 2, 'Name': f'{prefix} Lead {i+1}', 'Phone': f'9{start_digit}{i:08d}'}
        for i in range(count)
    ]


class GoogleSheetPermanentConnectionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='perm_admin',
            password='AdminPassword@2026',
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True,
        )
        self.client.force_login(self.admin)
        self.walk_in = Channel.objects.create(name='Walk-in', status='Active')
        self.facebook = Channel.objects.create(name='Facebook', status='Active')
        self.instagram = Channel.objects.create(name='Instagram', status='Active')

    def _connect(self, spreadsheet_id, channel, rows):
        url = f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit'
        headers = ['Name', 'Phone']
        with patch('leads.views.fetch_sheet_data', return_value=(headers, rows)), \
             patch('leads.views.fetch_spreadsheet_metadata', return_value={'title': spreadsheet_id}), \
             patch('leads.google_sheets.fetch_sheet_data', return_value=(headers, rows)):
            res = self.client.post(reverse('admin_google_sheet_connect'), {
                'name': f'Sheet {spreadsheet_id}',
                'spreadsheet_url': url,
                'channel_id': str(channel.id),
            })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'), data)
        return GoogleSheetConnection.objects.get(pk=data['connection_id'])

    # 1 & 2. Connection remains ACTIVE after a sync failure, and after repeated failures.
    def test_connection_remains_active_after_sync_failure(self):
        conn = self._connect('fail_A', self.walk_in, _rows('FA', 3, '1'))
        self.assertTrue(conn.is_active)

        with patch('leads.google_sheets.fetch_sheet_data', side_effect=Exception('Temporary Google API error')):
            result = sync_google_sheet(conn, triggered_by=self.admin)

        self.assertEqual(result['status'], 'Failed')
        conn.refresh_from_db()
        self.assertTrue(conn.is_active, "Connection must remain ACTIVE after a sync failure.")
        self.assertEqual(conn.last_sync_status, 'Failed')

        # Repeat the failure a second and third time - still must not deactivate.
        for _ in range(2):
            with patch('leads.google_sheets.fetch_sheet_data', side_effect=Exception('Temporary network error')):
                sync_google_sheet(conn, triggered_by=self.admin)
            conn.refresh_from_db()
            self.assertTrue(conn.is_active, "Repeated sync failures must never deactivate the connection.")
            self.assertEqual(conn.last_sync_status, 'Failed')

    # 3 & 4. Retry continues after failure, and a successful retry flips sync status to Success.
    def test_retry_after_failure_can_succeed(self):
        conn = self._connect('fail_B', self.facebook, _rows('FB', 3, '2'))

        with patch('leads.google_sheets.fetch_sheet_data', side_effect=Exception('Simulated outage')):
            sync_google_sheet(conn, triggered_by=self.admin)
        conn.refresh_from_db()
        self.assertTrue(conn.is_active)
        self.assertEqual(conn.last_sync_status, 'Failed')

        # Next retry succeeds.
        with patch('leads.google_sheets.fetch_sheet_data', return_value=(['Name', 'Phone'], _rows('FB2', 2, '3'))):
            result = sync_google_sheet(conn, triggered_by=self.admin)

        self.assertNotEqual(result['status'], 'Failed')
        conn.refresh_from_db()
        self.assertTrue(conn.is_active)
        self.assertIn(conn.last_sync_status, ('Completed', 'Connected'))

    # 7. Resume restores ACTIVE state and automatic sync resumes (not already covered:
    #    the existing pause/resume test only toggles, it never forces a failure afterwards).
    def test_resume_then_sync_failure_stays_active(self):
        conn = self._connect('pause_A', self.instagram, _rows('PA', 2, '4'))

        self.client.post(reverse('admin_google_sheet_toggle', args=[conn.pk]))  # Pause
        conn.refresh_from_db()
        self.assertFalse(conn.is_active)

        self.client.post(reverse('admin_google_sheet_toggle', args=[conn.pk]))  # Resume
        conn.refresh_from_db()
        self.assertTrue(conn.is_active)

        with patch('leads.google_sheets.fetch_sheet_data', side_effect=Exception('API error after resume')):
            sync_google_sheet(conn, triggered_by=self.admin)
        conn.refresh_from_db()
        self.assertTrue(conn.is_active, "A sync failure after Resume must not re-pause/disconnect the connection.")

    # 8. One failed sheet does not affect another - specifically failure, not just connect/disconnect.
    def test_one_connection_failure_does_not_affect_sibling_connections(self):
        conn_a = self._connect('multi_A', self.walk_in, _rows('MA', 2, '5'))
        conn_b = self._connect('multi_B', self.facebook, _rows('MB', 2, '6'))
        conn_c = self._connect('multi_C', self.instagram, _rows('MC', 2, '7'))

        with patch('leads.google_sheets.fetch_sheet_data', side_effect=Exception('B is down')):
            sync_google_sheet(conn_b, triggered_by=self.admin)

        conn_a.refresh_from_db()
        conn_b.refresh_from_db()
        conn_c.refresh_from_db()
        self.assertTrue(conn_a.is_active)
        self.assertTrue(conn_b.is_active)
        self.assertTrue(conn_c.is_active)
        self.assertEqual(conn_b.last_sync_status, 'Failed')
        self.assertNotEqual(conn_a.last_sync_status, 'Failed')
        self.assertNotEqual(conn_c.last_sync_status, 'Failed')

        # Now fail A too - B's prior failure must not have changed, C stays unaffected.
        with patch('leads.google_sheets.fetch_sheet_data', side_effect=Exception('A is down too')):
            sync_google_sheet(conn_a, triggered_by=self.admin)
        conn_a.refresh_from_db()
        conn_b.refresh_from_db()
        conn_c.refresh_from_db()
        self.assertTrue(conn_a.is_active and conn_a.last_sync_status == 'Failed')
        self.assertTrue(conn_b.is_active and conn_b.last_sync_status == 'Failed')
        self.assertTrue(conn_c.is_active)
        self.assertNotEqual(conn_c.last_sync_status, 'Failed')

    # 9 & 10. "Browser refresh" / "Django restart" preserve state - proven by reading the
    # connection fresh from the database in an entirely new query/request, not from any
    # in-memory/session/cache value.
    def test_state_persists_across_fresh_db_reads(self):
        conn = self._connect('persist_A', self.walk_in, _rows('PE', 2, '8'))
        with patch('leads.google_sheets.fetch_sheet_data', side_effect=Exception('fails')):
            sync_google_sheet(conn, triggered_by=self.admin)

        # Simulate "browser refresh": a brand new GET request to the page.
        resp = self.client.get(reverse('admin_offline_leads'))
        self.assertEqual(resp.status_code, 200)

        # Simulate "Django restart": re-fetch the row via an entirely fresh ORM query
        # (not conn.refresh_from_db() on the same Python object - a brand new lookup).
        reloaded = GoogleSheetConnection.objects.get(pk=conn.pk)
        self.assertTrue(reloaded.is_active)
        self.assertEqual(reloaded.last_sync_status, 'Failed')

    # 11 & 15. "View in Table" keeps working, and previously imported leads remain
    # available, after a failed sync.
    def test_view_in_table_and_leads_survive_a_failed_sync(self):
        conn = self._connect('view_A', self.facebook, _rows('VA', 3, '9'))
        self.assertEqual(Lead.objects.filter(channel=self.facebook).count(), 3)

        with patch('leads.google_sheets.fetch_sheet_data', side_effect=Exception('down')):
            sync_google_sheet(conn, triggered_by=self.admin)

        # Leads imported before the failure must still be there.
        self.assertEqual(Lead.objects.filter(channel=self.facebook).count(), 3)

        # "View in Table" = selecting this sheet on the Offline Leads page.
        resp = self.client.get(reverse('admin_offline_leads'), {'sheet_id': conn.pk})
        self.assertEqual(resp.status_code, 200)

        # The live-refresh polling API must also keep serving this connection, not report
        # it as disconnected.
        api_resp = self.client.get(reverse('admin_offline_leads_data_api'), {'sheet_id': conn.pk})
        self.assertEqual(api_resp.status_code, 200)
        api_data = api_resp.json()
        self.assertTrue(api_data.get('is_connected'))

    # 12. Manual "Sync Now" failure does not disconnect.
    def test_sync_now_button_failure_does_not_disconnect(self):
        conn = self._connect('syncnow_A', self.instagram, _rows('SN', 2, '0'))

        with patch('leads.google_sheets.fetch_sheet_data', side_effect=Exception('manual sync fails')):
            resp = self.client.post(reverse('admin_google_sheet_sync_now', args=[conn.pk]))

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['success'])  # the sync itself reports failure...
        conn.refresh_from_db()
        self.assertTrue(conn.is_active)  # ...but the connection is untouched.
        self.assertEqual(conn.last_sync_status, 'Failed')

    # 13. "Test" connection failure does not disconnect.
    def test_test_connection_failure_does_not_disconnect(self):
        conn = self._connect('test_A', self.walk_in, _rows('TA', 2, '1'))

        # admin_google_sheet_test calls the fetch_sheet_data/fetch_spreadsheet_metadata
        # names bound into the leads.views module itself (imported from leads.google_sheets),
        # not the leads.google_sheets module directly - patch the name the view actually calls.
        with patch('leads.views.fetch_sheet_data', side_effect=Exception('test fails')):
            resp = self.client.post(reverse('admin_google_sheet_test', args=[conn.pk]))

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()['success'])
        conn.refresh_from_db()
        self.assertTrue(conn.is_active, "A failed connection Test must never disconnect the sheet.")

    # 14. Sync history records the failure (and does not erase prior successful entries).
    def test_sync_history_records_failures_without_losing_prior_entries(self):
        # _connect() itself performs an initial sync (via admin_google_sheet_connect), so
        # one GoogleSheetSyncHistory row already exists before any explicit sync_google_sheet
        # call below - assert against that baseline rather than assuming zero.
        conn = self._connect('hist_A', self.facebook, _rows('HA', 2, '2'))
        baseline_count = GoogleSheetSyncHistory.objects.filter(connection=conn).count()
        self.assertEqual(baseline_count, 1)

        with patch('leads.google_sheets.fetch_sheet_data', return_value=(['Name', 'Phone'], _rows('HA2', 1, '3'))):
            sync_google_sheet(conn, triggered_by=self.admin)
        self.assertEqual(GoogleSheetSyncHistory.objects.filter(connection=conn).count(), baseline_count + 1)

        with patch('leads.google_sheets.fetch_sheet_data', side_effect=Exception('history fail test')):
            sync_google_sheet(conn, triggered_by=self.admin)

        histories = GoogleSheetSyncHistory.objects.filter(connection=conn).order_by('timestamp')
        self.assertEqual(histories.count(), baseline_count + 2, "The failure must be recorded as a NEW history row, not overwrite the prior one.")
        self.assertEqual(histories.last().status, 'Failed')
        self.assertIn('history fail test', histories.last().error_summary)

    # Explicit disconnect remains the only thing that can move a connection OUT of ACTIVE,
    # and it still only touches the targeted connection even when that connection had
    # already failed its last sync.
    def test_disconnect_after_failure_affects_only_that_connection(self):
        conn_a = self._connect('discfail_A', self.walk_in, _rows('DFA', 2, '4'))
        conn_b = self._connect('discfail_B', self.facebook, _rows('DFB', 2, '5'))

        with patch('leads.google_sheets.fetch_sheet_data', side_effect=Exception('B failing before disconnect')):
            sync_google_sheet(conn_b, triggered_by=self.admin)
        conn_b.refresh_from_db()
        self.assertTrue(conn_b.is_active)
        self.assertEqual(conn_b.last_sync_status, 'Failed')

        resp = self.client.post(reverse('admin_google_sheet_disconnect', args=[conn_b.pk]))
        self.assertEqual(resp.status_code, 200)

        conn_a.refresh_from_db()
        conn_b.refresh_from_db()
        self.assertTrue(conn_a.is_active)
        self.assertFalse(conn_b.is_active)
        self.assertEqual(conn_b.last_sync_status, 'Disconnected')

        # Leads already imported from B remain.
        self.assertEqual(Lead.objects.filter(channel=self.facebook).count(), 2)
