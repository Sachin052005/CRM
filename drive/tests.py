import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from accounts.models import User, UserRole
from branches.models import Branch, SalesHeadBranchAccess
from leads.models import Lead, LeadStatus
from drive.models import DriveConnection, CallRecording
from drive.services import (
    extract_folder_id,
    extract_mobile_from_filename,
    find_lead_by_phone,
    validate_and_connect_drive_folder,
    sync_drive_connection,
    retry_matching_unmatched_recordings,
    get_user_recordings_queryset,
    MOCK_DRIVE_STORE,
)


class DriveModuleIntegrationTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Branch
        self.branch = Branch.objects.create(name='Chennai Central', status='Active')
        self.branch_b = Branch.objects.create(name='Chennai North', status='Active')

        # Admin user
        self.admin = User.objects.create_user(
            username='admin_drive_user',
            password='Password@123',
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True
        )

        # Manager user (Sales Head, has access only to self.branch)
        self.manager = User.objects.create_user(
            username='manager_drive_user',
            password='Password@123',
            role=UserRole.SALES_HEAD,
            branch=self.branch
        )
        SalesHeadBranchAccess.objects.create(sales_head=self.manager, branch=self.branch)

        # Telecaller 1 (in manager's branch)
        self.telecaller1 = User.objects.create_user(
            username='telecaller1_drive_user',
            password='Password@123',
            role=UserRole.TELECALLER,
            branch=self.branch
        )

        # Telecaller 2 (different branch, not under this manager)
        self.telecaller2 = User.objects.create_user(
            username='telecaller2_drive_user',
            password='Password@123',
            role=UserRole.TELECALLER,
            branch=self.branch_b
        )

        # Leads
        # Rahul Kumar - 9876543210 (Assigned to telecaller1)
        self.lead_rahul = Lead.objects.create(
            name='Rahul Kumar',
            phone='9876543210',
            email='rahul@gmail.com',
            status=LeadStatus.INTERESTED,
            assigned_manager=self.manager,
            assigned_telecaller=self.telecaller1,
            branch=self.branch
        )

        # Priya Sharma - 9840123456 (Assigned to telecaller2)
        self.lead_priya = Lead.objects.create(
            name='Priya Sharma',
            phone='+919840123456',
            email='priya@gmail.com',
            status=LeadStatus.NEW,
            assigned_telecaller=self.telecaller2,
            branch=self.branch_b
        )

        # Clean Drive storage
        DriveConnection.objects.all().delete()
        CallRecording.objects.all().delete()

    # -------------------------------------------------------------
    # 1. Sidebar Navigation Tests (Section 1)
    # -------------------------------------------------------------
    def test_sidebar_drive_item_visible_for_all_three_roles(self):
        """
        Verify that ☁️ Drive menu item is visible for Admin, Manager, and Telecaller.
        """
        roles = [
            (self.admin, 'admin_dashboard'),
            (self.manager, 'manager_dashboard'),
            (self.telecaller1, 'telecaller_dashboard'),
        ]

        for user, dashboard_url_name in roles:
            self.client.login(username=user.username, password='Password@123')
            resp = self.client.get(reverse(dashboard_url_name))
            self.assertEqual(resp.status_code, 200)
            content = resp.content.decode('utf-8')
            self.assertIn('/drive/', content, f"Drive URL not in sidebar for {user.username}")
            self.assertIn('Drive', content, f"Drive text not in sidebar for {user.username}")
            self.client.logout()

    # -------------------------------------------------------------
    # 2. Drive URL Validation & Connection (Section 2, 3, 20)
    # -------------------------------------------------------------
    def test_extract_folder_id_helper(self):
        """
        Test regex extraction of Google Drive folder IDs.
        """
        self.assertEqual(extract_folder_id('https://drive.google.com/drive/folders/ABC123XYZ'), 'ABC123XYZ')
        self.assertEqual(extract_folder_id('https://drive.google.com/drive/u/0/folders/ABC123XYZ'), 'ABC123XYZ')
        self.assertEqual(extract_folder_id('https://drive.google.com/drive/folders/ABC123XYZ?usp=sharing'), 'ABC123XYZ')
        self.assertEqual(extract_folder_id('https://drive.google.com/open?id=ABC123XYZ'), 'ABC123XYZ')
        self.assertEqual(extract_folder_id('ABC123XYZ'), 'ABC123XYZ')
        self.assertIsNone(extract_folder_id('not-a-valid-url'))
        self.assertIsNone(extract_folder_id('https://google.com'))

    def test_invalid_drive_url_error_handling(self):
        """
        Section 20: Entering an invalid Drive URL returns:
        🔴 Invalid Drive folder link. Please enter a valid Google Drive folder URL.
        """
        self.client.login(username=self.admin.username, password='Password@123')
        resp = self.client.post(reverse('drive_connect'), {'folder_url': 'invalid_url_here'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn('Invalid Drive folder link', content)

    def test_inaccessible_drive_folder_error_handling(self):
        """
        Section 20: Entering an inaccessible/unauthorized Drive folder link returns:
        🔴 Drive folder cannot be accessed.
        """
        self.client.login(username=self.admin.username, password='Password@123')
        resp = self.client.post(
            reverse('drive_connect'),
            {'folder_url': 'https://drive.google.com/drive/folders/unauthorized_folder_999'},
            follow=True
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn('Drive folder cannot be accessed', content)
        self.assertEqual(DriveConnection.objects.count(), 0)

    def test_valid_drive_connection_and_matching(self):
        """
        Section 3 & 5: Connecting a valid Drive folder successfully imports files and matches leads.
        """
        self.client.login(username=self.admin.username, password='Password@123')
        resp = self.client.post(
            reverse('drive_connect'),
            {
                'folder_url': 'https://drive.google.com/drive/folders/ABC123',
                'folder_name': 'Call Recordings'
            },
            follow=True
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Success message
        self.assertIn('Drive Connected Successfully', content)

        # Connection created
        self.assertEqual(DriveConnection.objects.count(), 1)
        conn = DriveConnection.objects.first()
        self.assertEqual(conn.name, 'Call Recordings')
        self.assertEqual(conn.folder_id, 'ABC123')

        # Check call recordings created
        # In mock ABC123:
        # drv_rec_001: call_9876543210_20260929.mp3 -> Rahul Kumar (Matched)
        # drv_rec_002: call_9840123456.mp3 -> Priya Sharma (Matched)
        # drv_rec_003: call_9887654321.mp3 -> Unmatched
        # drv_rec_004: call_9123456789.mp3 -> Unmatched
        # drv_rec_005: call_unknown.mp3 -> Unmatched (No number)
        recordings = CallRecording.objects.filter(drive_connection=conn)
        self.assertEqual(recordings.count(), 5)

        rec_rahul = CallRecording.objects.get(drive_file_id='drv_rec_001')
        self.assertEqual(rec_rahul.match_status, 'MATCHED')
        self.assertEqual(rec_rahul.lead, self.lead_rahul)
        self.assertEqual(rec_rahul.normalized_mobile_number, '9876543210')

        rec_priya = CallRecording.objects.get(drive_file_id='drv_rec_002')
        self.assertEqual(rec_priya.match_status, 'MATCHED')
        self.assertEqual(rec_priya.lead, self.lead_priya)

        rec_unmatched = CallRecording.objects.get(drive_file_id='drv_rec_004')
        self.assertEqual(rec_unmatched.match_status, 'UNMATCHED')
        self.assertIsNone(rec_unmatched.lead)
        self.assertIn('No matching CRM lead found', rec_unmatched.unmatched_reason)

        rec_no_num = CallRecording.objects.get(drive_file_id='drv_rec_005')
        self.assertEqual(rec_no_num.match_status, 'UNMATCHED')
        self.assertIn('could not be identified', rec_no_num.unmatched_reason)

    # -------------------------------------------------------------
    # 3. Mobile Number Extraction (Section 6)
    # -------------------------------------------------------------
    def test_mobile_number_extraction_formats(self):
        """
        Verify phone extraction from various common filename patterns.
        """
        patterns = [
            ('9876543210.mp3', '9876543210'),
            ('call_9876543210.mp3', '9876543210'),
            ('call_9876543210_20260929.mp3', '9876543210'),
            ('recording_9876543210_1030.mp3', '9876543210'),
            ('+919876543210_call.mp3', '9876543210'),
            ('call_09876543210.mp3', '9876543210'),
            ('call_+919876543210_afternoon.wav', '9876543210'),
            ('call_unknown.mp3', ''),
            ('recording_test.wav', ''),
        ]

        for filename, expected_normalized in patterns:
            raw, norm = extract_mobile_from_filename(filename)
            self.assertEqual(
                norm,
                expected_normalized,
                f"Failed extraction for {filename}: expected {expected_normalized}, got {norm}"
            )

    # -------------------------------------------------------------
    # 4. Lead Details Integration (Section 8, 9, 23)
    # -------------------------------------------------------------
    def test_lead_details_call_recordings_section_admin(self):
        """
        Admin Lead Details page must show CALL RECORDINGS section with audio player and Open in Drive.
        """
        # Connect Drive folder
        validate_and_connect_drive_folder('https://drive.google.com/drive/folders/ABC123')

        self.client.login(username=self.admin.username, password='Password@123')
        resp = self.client.get(reverse('admin_lead_detail', args=[self.lead_rahul.pk]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn('CALL RECORDINGS', content)
        self.assertIn('call_9876543210_20260929.mp3', content)
        self.assertIn('04:32', content)
        self.assertIn('Source: Drive', content)
        self.assertIn('<audio controls', content)
        self.assertIn('Open in Drive', content)

    def test_lead_details_call_recordings_section_manager(self):
        """
        Manager Lead Details page displays CALL RECORDINGS for permitted leads.
        """
        validate_and_connect_drive_folder('https://drive.google.com/drive/folders/ABC123')

        self.client.login(username=self.manager.username, password='Password@123')
        resp = self.client.get(reverse('manager_lead_detail', args=[self.lead_rahul.pk]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn('CALL RECORDINGS', content)
        self.assertIn('call_9876543210_20260929.mp3', content)
        self.assertIn('<audio controls', content)
        self.assertIn('Open in Drive', content)

    def test_lead_details_call_recordings_section_telecaller(self):
        """
        Telecaller Lead Details page displays CALL RECORDINGS for assigned leads.
        """
        validate_and_connect_drive_folder('https://drive.google.com/drive/folders/ABC123')

        self.client.login(username=self.telecaller1.username, password='Password@123')
        resp = self.client.get(reverse('telecaller_lead_detail', args=[self.lead_rahul.pk]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn('CALL RECORDINGS', content)
        self.assertIn('call_9876543210_20260929.mp3', content)
        self.assertIn('<audio controls', content)
        self.assertIn('Open in Drive', content)

    # -------------------------------------------------------------
    # 5. Duplicate Prevention (Section 11)
    # -------------------------------------------------------------
    def test_duplicate_prevention_on_repeated_sync(self):
        """
        Repeated synchronization of the same Drive folder must never create duplicate recordings.
        """
        ok, msg, conn = validate_and_connect_drive_folder('https://drive.google.com/drive/folders/ABC123')
        self.assertTrue(ok)
        initial_count = CallRecording.objects.count()
        self.assertEqual(initial_count, 5)

        # Trigger sync again
        success, sync_msg, new_files, matched = sync_drive_connection(conn)
        self.assertTrue(success)
        self.assertEqual(new_files, 0)
        self.assertEqual(CallRecording.objects.count(), initial_count)

    # -------------------------------------------------------------
    # 6. Unmatched Recordings & Retry Matching (Section 10)
    # -------------------------------------------------------------
    def test_retry_matching_when_new_lead_created(self):
        """
        Section 10: Recordings without matching leads start as UNMATCHED.
        When a new lead is added and Retry Matching is clicked, it attaches to the new lead.
        """
        validate_and_connect_drive_folder('https://drive.google.com/drive/folders/ABC123')

        # drv_rec_004 has phone 9123456789
        rec = CallRecording.objects.get(drive_file_id='drv_rec_004')
        self.assertEqual(rec.match_status, 'UNMATCHED')
        self.assertIsNone(rec.lead)

        # Create new lead with 9123456789
        new_lead = Lead.objects.create(
            name='Kavitha S',
            phone='9123456789',
            status=LeadStatus.NEW,
            branch=self.branch
        )

        # Trigger Retry Matching
        self.client.login(username=self.admin.username, password='Password@123')
        resp = self.client.post(reverse('drive_retry_matching'), follow=True)
        self.assertEqual(resp.status_code, 200)

        # Verify recording is now matched
        rec.refresh_from_db()
        self.assertEqual(rec.match_status, 'MATCHED')
        self.assertEqual(rec.lead, new_lead)

    # -------------------------------------------------------------
    # 7. Multiple Drive Links (Section 17 & 18)
    # -------------------------------------------------------------
    def test_multiple_drive_folders_support(self):
        """
        Section 17 & 18: System supports multiple connected Drive folders.
        """
        validate_and_connect_drive_folder('https://drive.google.com/drive/folders/chennai_folder_id', 'Chennai Call Recordings')
        validate_and_connect_drive_folder('https://drive.google.com/drive/folders/velachery_folder_id', 'Velachery Call Recordings')
        validate_and_connect_drive_folder('https://drive.google.com/drive/folders/sales_folder_id', 'Sales Team Recordings')

        self.assertEqual(DriveConnection.objects.count(), 3)

        self.client.login(username=self.admin.username, password='Password@123')
        resp = self.client.get(reverse('drive_dashboard'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        self.assertIn('Chennai Call Recordings', content)
        self.assertIn('Velachery Call Recordings', content)
        self.assertIn('Sales Team Recordings', content)
        self.assertIn('Connected Folders', content)

    # -------------------------------------------------------------
    # 8. Role-Based Scoping (Section 13, 14, 15, 16)
    # -------------------------------------------------------------
    def test_role_based_recordings_visibility(self):
        """
        Verify that Admin sees all recordings, Manager sees their team's recordings,
        and Telecaller sees only their assigned recordings.
        """
        validate_and_connect_drive_folder('https://drive.google.com/drive/folders/ABC123')

        # Admin: sees all 5 recordings
        admin_qs = get_user_recordings_queryset(self.admin)
        self.assertEqual(admin_qs.count(), 5)

        # Manager: sees recordings for leads assigned to manager or telecaller1 (Rahul Kumar)
        # Priya Sharma belongs to telecaller2 (not under this manager)
        manager_qs = get_user_recordings_queryset(self.manager)
        self.assertEqual(manager_qs.count(), 1)
        self.assertEqual(manager_qs.first().lead, self.lead_rahul)

        # Telecaller 1: sees only Rahul Kumar recording
        tc1_qs = get_user_recordings_queryset(self.telecaller1)
        self.assertEqual(tc1_qs.count(), 1)
        self.assertEqual(tc1_qs.first().lead, self.lead_rahul)

        # Telecaller 2: sees only Priya Sharma recording
        tc2_qs = get_user_recordings_queryset(self.telecaller2)
        self.assertEqual(tc2_qs.count(), 1)
        self.assertEqual(tc2_qs.first().lead, self.lead_priya)

    def test_audio_stream_permission_security(self):
        """
        Section 16: Telecaller cannot stream audio for a lead assigned to another telecaller.
        """
        validate_and_connect_drive_folder('https://drive.google.com/drive/folders/ABC123')
        rec_priya = CallRecording.objects.get(drive_file_id='drv_rec_002') # Assigned to telecaller2

        # Telecaller 1 tries to access Priya's audio stream -> 403 Forbidden
        self.client.login(username=self.telecaller1.username, password='Password@123')
        resp = self.client.get(reverse('drive_stream_recording', args=[rec_priya.pk]))
        self.assertEqual(resp.status_code, 403)

        # Telecaller 2 (assigned telecaller) accesses Priya's audio stream -> 200 OK
        self.client.login(username=self.telecaller2.username, password='Password@123')
        resp2 = self.client.get(reverse('drive_stream_recording', args=[rec_priya.pk]))
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2['Content-Type'], 'audio/mpeg')

    # -------------------------------------------------------------
    # 9. Search and Filters (Section 19)
    # -------------------------------------------------------------
    def test_search_and_filters_drive_dashboard(self):
        """
        Section 19: Search by mobile number, file name, and status filter.
        """
        validate_and_connect_drive_folder('https://drive.google.com/drive/folders/ABC123')
        self.client.login(username=self.admin.username, password='Password@123')

        # Filter by mobile number
        resp = self.client.get(reverse('drive_dashboard') + '?search_mobile=9876543210')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('call_9876543210_20260929.mp3', resp.content.decode('utf-8'))
        self.assertNotIn('call_9840123456.mp3', resp.content.decode('utf-8'))

        # Filter by status: Matched
        resp_matched = self.client.get(reverse('drive_dashboard') + '?status=Matched')
        self.assertEqual(resp_matched.status_code, 200)
        content_matched = resp_matched.content.decode('utf-8')
        self.assertIn('call_9876543210_20260929.mp3', content_matched)
        self.assertNotIn('call_unknown.mp3', content_matched)

        # Filter by status: Unmatched
        resp_unmatched = self.client.get(reverse('drive_dashboard') + '?status=Unmatched')
        self.assertEqual(resp_unmatched.status_code, 200)
        content_unmatched = resp_unmatched.content.decode('utf-8')
        self.assertIn('call_unknown.mp3', content_unmatched)
        self.assertNotIn('call_9876543210_20260929.mp3', content_unmatched)

    # -------------------------------------------------------------
    # 10. Prompt 5 Specification Exact Requirements Tests
    # -------------------------------------------------------------
    def test_prompt5_invalid_drive_url_exact_error_message(self):
        """
        Prompt 5 Section 5: Invalid Drive link must return exact error:
        🔴 Unable to connect to Drive
        The Drive folder link is invalid.
        Please enter a valid Google Drive folder link.
        """
        self.client.login(username=self.admin.username, password='Password@123')
        resp = self.client.post(reverse('drive_connect'), {'folder_url': 'invalid_url_here'}, follow=True)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn('Unable to connect to Drive', content)
        self.assertIn('The Drive folder link is invalid', content)
        self.assertIn('Please enter a valid Google Drive folder link', content)

    def test_prompt5_inaccessible_drive_folder_exact_error_message(self):
        """
        Prompt 5 Section 6: Inaccessible Drive folder must return exact error:
        🔴 Drive connection failed
        The folder could not be accessed.
        Please verify the Drive folder permissions and the configured Drive integration.
        """
        self.client.login(username=self.admin.username, password='Password@123')
        resp = self.client.post(
            reverse('drive_connect'),
            {'folder_url': 'https://drive.google.com/drive/folders/unauthorized_folder_999'},
            follow=True
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn('Drive connection failed', content)
        self.assertIn('The folder could not be accessed', content)
        self.assertIn('Please verify the Drive folder permissions and the configured Drive integration', content)

    def test_prompt5_standard_248_recordings_and_rahul_kumar_matching(self):
        """
        Prompt 5 Sections 7, 8, 9, 10, 11:
        - Connects 248 recordings folder
        - Verifies 248 recordings found, 231 matched, 17 unmatched
        - Verifies multiple recordings match Rahul Kumar (9876543210):
          call_9876543210.mp3, call_9876543210_2.mp3, call_9876543210_3.mp3,
          9876543210.mp3, call_9876543210_20260929.mp3, recording_9876543210_1030.mp3
        - Verifies Lead Details page for Rahul Kumar has CALL RECORDINGS with:
          Source: Google Drive, Match Status: 🟢 Automatically Matched, [ ▶ Play ], [ Open in Drive ]
        """
        self.client.login(username=self.admin.username, password='Password@123')
        resp = self.client.post(
            reverse('drive_connect'),
            {'folder_url': 'https://drive.google.com/drive/folders/XXXXXXXXXXXX'},
            follow=True
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Check UI shows exact success card values
        self.assertIn('DRIVE CONNECTED SUCCESSFULLY', content)
        self.assertIn('Connected Folder:', content)
        self.assertIn('Folder Link:', content)
        self.assertIn('https://drive.google.com/drive/folders/XXXXXXXXXXXX', content)
        self.assertIn('Recordings Found:', content)
        self.assertIn('248', content)
        self.assertIn('Matched Leads:', content)
        self.assertIn('231', content)
        self.assertIn('Unmatched Recordings:', content)
        self.assertIn('17', content)
        self.assertIn('Sync Status:', content)
        self.assertIn('Active', content)

        # Check DB counts
        conn = DriveConnection.objects.get(folder_id='XXXXXXXXXXXX')
        total_recs = CallRecording.objects.filter(drive_connection=conn).count()
        matched_recs = CallRecording.objects.filter(drive_connection=conn, match_status='MATCHED').count()
        unmatched_recs = CallRecording.objects.filter(drive_connection=conn, match_status='UNMATCHED').count()
        self.assertEqual(total_recs, 248)
        self.assertEqual(matched_recs, 231)
        self.assertEqual(unmatched_recs, 17)

        # Check Rahul Kumar (9876543210) has multiple recordings attached
        rahul_recs = CallRecording.objects.filter(lead=self.lead_rahul).values_list('file_name', flat=True)
        expected_files = [
            'call_9876543210.mp3',
            'call_9876543210_2.mp3',
            'call_9876543210_3.mp3',
            '9876543210.mp3',
            'call_9876543210_20260929.mp3',
            'recording_9876543210_1030.mp3',
        ]
        for f in expected_files:
            self.assertIn(f, rahul_recs, f"File {f} not matched to Rahul Kumar")

        # Verify Lead Details page for Rahul Kumar across all roles
        for user, detail_url_name in [
            (self.admin, 'admin_lead_detail'),
            (self.manager, 'manager_lead_detail'),
            (self.telecaller1, 'telecaller_lead_detail')
        ]:
            self.client.login(username=user.username, password='Password@123')
            det_resp = self.client.get(reverse(detail_url_name, args=[self.lead_rahul.pk]))
            self.assertEqual(det_resp.status_code, 200)
            det_content = det_resp.content.decode('utf-8')
            self.assertIn('CALL RECORDINGS', det_content)
            self.assertIn('Source: Google Drive', det_content)
            self.assertIn('Automatically Matched', det_content)
            self.assertIn('<audio controls', det_content)
            self.assertIn('▶ Play', det_content)
            self.assertIn('Open in Drive', det_content)
            self.client.logout()

    def test_prompt5_disconnected_state_ui(self):
        """
        When no drive folder is connected, the UI shows '🔴 Not Connected'
        and 'Connect Call Recording Drive'.
        """
        self.client.login(username=self.admin.username, password='Password@123')
        resp = self.client.get(reverse('drive_dashboard'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn('Connect Call Recording Drive', content)
        self.assertIn('CONNECT DRIVE', content)
        self.assertIn('🔴 Not Connected', content)
        self.assertIn('🟡 Connecting to Drive...', content)

