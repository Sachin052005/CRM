"""
Tests for the Google Sheet "Channel / Source" -> Lead.channel attribution pipeline.

Root cause under test: admin_google_sheet_connect previously ignored the
'channel_id' / 'branch_id' fields submitted by the Add Spreadsheet form, so every
imported lead silently fell back to the generic "Google Sheets" channel instead of
the Channel/Source the admin actually selected (e.g. Walk-in, Facebook, Instagram).
"""
import json
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch
from channels.models import Channel
from leads.models import Lead, GoogleSheetConnection


def _rows(prefix, count, start_digit='7'):
    """Builds `count` distinct lead rows as dicts, each with a unique 10-digit phone."""
    return [
        {'_row_index': i + 2, 'Name': f'{prefix} Lead {i+1}', 'Phone': f'9{start_digit}{i:08d}'}
        for i in range(count)
    ]


class GoogleSheetChannelMappingTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='channel_map_admin',
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
        self.google_sheets_channel = Channel.objects.create(name='Google Sheets', status='Active')
        self.anna_nagar, _ = Branch.objects.get_or_create(name='Anna Nagar', defaults={'status': 'Active'})

    def _connect(self, url, channel, rows, branch=None, name=None):
        headers = ['Name', 'Phone']
        with patch('leads.views.fetch_sheet_data', return_value=(headers, rows)), \
             patch('leads.views.fetch_spreadsheet_metadata', return_value={'title': name or 'Sheet'}), \
             patch('leads.google_sheets.fetch_sheet_data', return_value=(headers, rows)):
            payload = {
                'name': name or f'Sheet for {channel.name}',
                'spreadsheet_url': url,
                'channel_id': str(channel.id),
            }
            if branch:
                payload['branch_id'] = str(branch.id)
            res = self.client.post(reverse('admin_google_sheet_connect'), payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get('success'), data)
        return GoogleSheetConnection.objects.get(spreadsheet_url__icontains=url.split('/d/')[1].split('/')[0])

    # TEST 1 - Walk-in
    def test_walk_in_channel_mapping(self):
        self._connect(
            'https://docs.google.com/spreadsheets/d/walkin_sheet_1/edit',
            self.walk_in, _rows('WalkIn', 10, '1')
        )
        self.assertEqual(Lead.objects.filter(channel=self.walk_in).count(), 10)
        self.assertEqual(Lead.objects.filter(channel=self.google_sheets_channel).count(), 0)

    # TEST 2 - Facebook
    def test_facebook_channel_mapping(self):
        self._connect(
            'https://docs.google.com/spreadsheets/d/fb_sheet_1/edit',
            self.facebook, _rows('FB', 20, '2')
        )
        self.assertEqual(Lead.objects.filter(channel=self.facebook).count(), 20)

    # TEST 3 - Instagram
    def test_instagram_channel_mapping(self):
        self._connect(
            'https://docs.google.com/spreadsheets/d/ig_sheet_1/edit',
            self.instagram, _rows('IG', 15, '3')
        )
        self.assertEqual(Lead.objects.filter(channel=self.instagram).count(), 15)

    # TEST 4 - Multiple Walk-in sheets aggregate
    def test_multiple_walk_in_sheets_aggregate(self):
        self._connect(
            'https://docs.google.com/spreadsheets/d/walkin_sheet_a/edit',
            self.walk_in, _rows('WalkInA', 10, '4')
        )
        self._connect(
            'https://docs.google.com/spreadsheets/d/walkin_sheet_b/edit',
            self.walk_in, _rows('WalkInB', 20, '5')
        )
        self.assertEqual(Lead.objects.filter(channel=self.walk_in).count(), 30)
        self.assertEqual(GoogleSheetConnection.objects.filter(channel=self.walk_in).count(), 2)

    # TEST 5 - Multiple Facebook sheets aggregate
    def test_multiple_facebook_sheets_aggregate(self):
        self._connect(
            'https://docs.google.com/spreadsheets/d/fb_sheet_a/edit',
            self.facebook, _rows('FBA', 10, '6')
        )
        self._connect(
            'https://docs.google.com/spreadsheets/d/fb_sheet_b/edit',
            self.facebook, _rows('FBB', 25, '7')
        )
        self.assertEqual(Lead.objects.filter(channel=self.facebook).count(), 35)

    # TEST 6 - Different channels stay independent, Google Sheets is NOT auto-assigned
    def test_different_channels_stay_independent(self):
        self._connect('https://docs.google.com/spreadsheets/d/mix_fb/edit', self.facebook, _rows('MixFB', 10, '8'))
        self._connect('https://docs.google.com/spreadsheets/d/mix_ig/edit', self.instagram, _rows('MixIG', 20, '9'))
        self._connect('https://docs.google.com/spreadsheets/d/mix_wi/edit', self.walk_in, _rows('MixWI', 30, '0'))
        self._connect('https://docs.google.com/spreadsheets/d/mix_ga/edit', self.google_ads, _rows('MixGA', 40, '1'))

        self.assertEqual(Lead.objects.filter(channel=self.facebook).count(), 10)
        self.assertEqual(Lead.objects.filter(channel=self.instagram).count(), 20)
        self.assertEqual(Lead.objects.filter(channel=self.walk_in).count(), 30)
        self.assertEqual(Lead.objects.filter(channel=self.google_ads).count(), 40)
        self.assertEqual(Lead.objects.filter(channel=self.google_sheets_channel).count(), 0)

    # TEST 7 - Existing spreadsheet connection preserved when a new one is added
    def test_existing_spreadsheet_preserved_when_second_added(self):
        conn_a = self._connect(
            'https://docs.google.com/spreadsheets/d/preserve_a/edit',
            self.walk_in, _rows('PreserveA', 5, '2')
        )
        self._connect(
            'https://docs.google.com/spreadsheets/d/preserve_b/edit',
            self.facebook, _rows('PreserveB', 7, '3')
        )

        conn_a.refresh_from_db()
        self.assertTrue(conn_a.is_active)
        self.assertEqual(conn_a.channel_id, self.walk_in.id)
        self.assertEqual(Lead.objects.filter(channel=self.walk_in).count(), 5)
        self.assertEqual(Lead.objects.filter(channel=self.facebook).count(), 7)
        self.assertEqual(GoogleSheetConnection.objects.count(), 2)

    # TEST 9 - Branch attribution
    def test_branch_attribution(self):
        self._connect(
            'https://docs.google.com/spreadsheets/d/branch_sheet/edit',
            self.walk_in, _rows('BranchLead', 4, '4'), branch=self.anna_nagar
        )
        self.assertEqual(Lead.objects.filter(branch=self.anna_nagar, channel=self.walk_in).count(), 4)

    # Section 25 exception: explicitly selecting "Google Sheets" legitimately counts there
    def test_explicit_google_sheets_channel_selection_counts_there(self):
        self._connect(
            'https://docs.google.com/spreadsheets/d/explicit_gs/edit',
            self.google_sheets_channel, _rows('ExplicitGS', 6, '5')
        )
        self.assertEqual(Lead.objects.filter(channel=self.google_sheets_channel).count(), 6)

    # TEST 11 - Re-sync does not duplicate leads
    def test_resync_does_not_duplicate_leads(self):
        url = 'https://docs.google.com/spreadsheets/d/resync_sheet/edit'
        rows = _rows('Resync', 8, '6')
        self._connect(url, self.walk_in, rows)
        self.assertEqual(Lead.objects.filter(channel=self.walk_in).count(), 8)

        # Re-connect the SAME spreadsheet again with the same rows
        self._connect(url, self.walk_in, rows, name='Resync Sheet (re-sync)')
        self.assertEqual(Lead.objects.filter(channel=self.walk_in).count(), 8)
        self.assertEqual(GoogleSheetConnection.objects.filter(spreadsheet_url=url).count(), 1)

    # Lead Setup (admin_leads_list) must show these leads using the same canonical data
    def test_lead_setup_shows_channel_mapped_leads(self):
        self._connect(
            'https://docs.google.com/spreadsheets/d/leadsetup_fb/edit',
            self.facebook, _rows('LeadSetupFB', 3, '7')
        )
        resp = self.client.get(reverse('admin_leads_list'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn('LeadSetupFB Lead 1', content)

    # Lead Channels page must reflect real per-channel Lead counts
    def test_lead_channels_page_counts_real_leads(self):
        self._connect(
            'https://docs.google.com/spreadsheets/d/channels_page_wi/edit',
            self.walk_in, _rows('ChPageWI', 9, '8')
        )
        resp = self.client.get(reverse('admin_channels_list'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        # The Walk-in row must show 9 leads
        self.walk_in.refresh_from_db()
        self.assertIn('Walk-in', content)
        self.assertEqual(Channel.objects.get(pk=self.walk_in.pk).leads.count(), 9)
