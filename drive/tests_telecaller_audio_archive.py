from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from accounts.models import User, UserRole
from branches.models import Branch
from leads.models import Lead, LeadStatus
from drive.models import DriveConnection, CallRecording
from drive.services import (
    sync_drive_connection,
    validate_and_connect_drive_folder,
    MOCK_DRIVE_STORE,
    STANDARD_SILENT_MP3,
)


class TelecallerDriveAudioArchiveTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Branch
        self.branch = Branch.objects.get_or_create(name='T. Nagar', defaults={'status': 'Active'})[0]

        # Counselor for telecallers
        self.counselor = User.objects.create_user(
            username='counselor_audio',
            password='Password@123',
            role=UserRole.COUNSELOR,
            branch=self.branch,
            is_active=True
        )

        # Telecaller A
        self.telecaller_a = User.objects.create_user(
            username='telecaller_a',
            password='Password@123',
            role=UserRole.TELECALLER,
            branch=self.branch,
            counselor=self.counselor,
            is_active=True
        )

        # Telecaller B
        self.telecaller_b = User.objects.create_user(
            username='telecaller_b',
            password='Password@123',
            role=UserRole.TELECALLER,
            branch=self.branch,
            counselor=self.counselor,
            is_active=True
        )

        # Lead for Telecaller A
        self.lead_a = Lead.objects.create(
            name='Customer Alpha',
            phone='9876543210',
            status=LeadStatus.INTERESTED,
            assigned_telecaller=self.telecaller_a,
            branch=self.branch
        )

        # Lead for Telecaller B
        self.lead_b = Lead.objects.create(
            name='Customer Beta',
            phone='9840123456',
            status=LeadStatus.NEW,
            assigned_telecaller=self.telecaller_b,
            branch=self.branch
        )

    def test_complete_6_step_telecaller_audio_sync_lifecycle(self):
        """
        Executes the exact 6-step lifecycle required by the prompt:
        Step 1: Connect folder containing audio1, audio2, audio3.
                Verify 3 audio records saved in MySQL with binary data and telecaller ownership.
        Step 2: Run 10-second sync.
                Verify no duplicate records created in MySQL.
        Step 3: Add audio4 to Drive.
                Verify sync downloads and archives audio4 into MySQL (now 4 records).
        Step 4: Delete audio2 from Drive (files in Drive: audio1, audio3, audio4).
                Verify sync KEEPS audio2 in MySQL archive (audio2 NOT deleted).
        Step 5: Query MySQL and verify audio2 and all 4 audio files remain available and streamable.
        Step 6: Disconnect Drive folder.
                Verify future sync stops and all 4 audio files remain permanently in MySQL.
        """
        self.client.login(username='telecaller_a', password='Password@123')

        mock_folder_id = 'test_folder_lifecycle_123'
        drive_folder_state = [
            {'id': 'file_001', 'name': 'call_9876543210_1.mp3', 'mimeType': 'audio/mpeg', 'duration': '03:10', 'audio_data': b'BINARY_AUDIO_1_DATA'},
            {'id': 'file_002', 'name': 'call_9876543210_2.mp3', 'mimeType': 'audio/mpeg', 'duration': '04:20', 'audio_data': b'BINARY_AUDIO_2_DATA'},
            {'id': 'file_003', 'name': 'call_9876543210_3.mp3', 'mimeType': 'audio/mpeg', 'duration': '02:45', 'audio_data': b'BINARY_AUDIO_3_DATA'},
        ]

        def mock_fetch_drive_data(folder_id):
            return True, "", {'name': 'Telecaller Calls', 'files': list(drive_folder_state)}

        with patch('drive.services.fetch_drive_folder_data', side_effect=mock_fetch_drive_data):
            # -------------------------------------------------------------
            # STEP 1: Connect folder from Telecaller login
            # -------------------------------------------------------------
            connect_url = reverse('drive_connect')
            response = self.client.post(connect_url, {
                'folder_url': f'https://drive.google.com/drive/folders/{mock_folder_id}',
                'folder_name': 'My Recordings'
            })
            self.assertEqual(response.status_code, 302)

            connection = DriveConnection.objects.get(folder_id=mock_folder_id)
            self.assertEqual(connection.created_by, self.telecaller_a)
            self.assertEqual(connection.connection_status, 'Connected')
            self.assertTrue(connection.is_active)

            # Check MySQL storage for 3 files
            recordings = CallRecording.objects.filter(source_folder_id=mock_folder_id).order_by('drive_file_id')
            self.assertEqual(recordings.count(), 3)
            rec1 = recordings.filter(drive_file_id='file_001').first()
            self.assertIsNotNone(rec1)
            self.assertEqual(bytes(rec1.audio_data), b'BINARY_AUDIO_1_DATA')
            self.assertEqual(rec1.file_size, len(b'BINARY_AUDIO_1_DATA'))
            self.assertEqual(rec1.telecaller, self.telecaller_a)

            # -------------------------------------------------------------
            # STEP 2: 10-second sync run -> No duplicates created
            # -------------------------------------------------------------
            api_sync_url = reverse('drive_api_sync', args=[connection.pk])
            sync_resp = self.client.get(api_sync_url)
            self.assertEqual(sync_resp.status_code, 200)
            data = sync_resp.json()
            self.assertTrue(data['success'])
            self.assertEqual(data['new_files'], 0)
            self.assertEqual(CallRecording.objects.filter(source_folder_id=mock_folder_id).count(), 3)

            # -------------------------------------------------------------
            # STEP 3: Add audio4 to Drive -> Detected and saved to MySQL
            # -------------------------------------------------------------
            drive_folder_state.append({
                'id': 'file_004',
                'name': 'call_9876543210_4.mp3',
                'mimeType': 'audio/mpeg',
                'duration': '05:15',
                'audio_data': b'BINARY_AUDIO_4_DATA'
            })

            sync_resp = self.client.get(api_sync_url)
            self.assertEqual(sync_resp.status_code, 200)
            data = sync_resp.json()
            self.assertTrue(data['success'])
            self.assertEqual(data['new_files'], 1)
            self.assertEqual(CallRecording.objects.filter(source_folder_id=mock_folder_id).count(), 4)
            rec4 = CallRecording.objects.get(drive_file_id='file_004')
            self.assertEqual(bytes(rec4.audio_data), b'BINARY_AUDIO_4_DATA')

            # -------------------------------------------------------------
            # STEP 4: Delete audio2 from Drive -> MySQL MUST KEEP audio2!
            # -------------------------------------------------------------
            # Remove file_002 from simulated Drive folder
            drive_folder_state[:] = [f for f in drive_folder_state if f['id'] != 'file_002']
            self.assertEqual(len(drive_folder_state), 3)  # Only 1, 3, 4 in Drive

            sync_resp = self.client.get(api_sync_url)
            self.assertEqual(sync_resp.status_code, 200)

            # CRITICAL VERIFICATION: file_002 MUST STILL EXIST IN MYSQL ARCHIVE!
            rec2 = CallRecording.objects.filter(drive_file_id='file_002').first()
            self.assertIsNotNone(rec2, "audio2.mp3 was deleted from MySQL when deleted from Drive! It must be kept!")
            self.assertEqual(bytes(rec2.audio_data), b'BINARY_AUDIO_2_DATA')
            self.assertEqual(CallRecording.objects.filter(source_folder_id=mock_folder_id).count(), 4)

            # -------------------------------------------------------------
            # STEP 5: Verify MySQL audio files remain accessible and streamable
            # -------------------------------------------------------------
            stream_url = reverse('drive_stream_recording', args=[rec2.pk])
            stream_resp = self.client.get(stream_url)
            self.assertEqual(stream_resp.status_code, 200)
            self.assertEqual(stream_resp.content, b'BINARY_AUDIO_2_DATA')
            self.assertEqual(stream_resp['Content-Type'], 'audio/mpeg')

            # -------------------------------------------------------------
            # STEP 6: Disconnect Drive folder -> Future sync stops, MySQL audio remains
            # -------------------------------------------------------------
            disconnect_url = reverse('drive_disconnect', args=[connection.pk])
            disc_resp = self.client.post(disconnect_url)
            self.assertEqual(disc_resp.status_code, 302)

            connection.refresh_from_db()
            self.assertEqual(connection.connection_status, 'Disconnected')
            self.assertFalse(connection.is_active)

            # Future sync stops
            sync_resp_disc = self.client.get(api_sync_url)
            data_disc = sync_resp_disc.json()
            self.assertFalse(data_disc['is_connected'])

            # All 4 audio files STILL exist in MySQL!
            self.assertEqual(CallRecording.objects.filter(source_folder_id=mock_folder_id).count(), 4)

    def test_telecaller_ownership_and_security_isolation(self):
        """
        Verify strict telecaller isolation:
        Telecaller A's folder and audio records cannot be viewed, synced, disconnected, or streamed by Telecaller B.
        """
        # Create connection for Telecaller A
        conn_a = DriveConnection.objects.create(
            name="Telecaller A Folder",
            folder_url="https://drive.google.com/drive/folders/folder_a_sec",
            folder_id="folder_a_sec",
            connection_status="Connected",
            is_active=True,
            created_by=self.telecaller_a
        )
        rec_a = CallRecording.objects.create(
            drive_connection=conn_a,
            telecaller=self.telecaller_a,
            lead=self.lead_a,
            source_folder_id="folder_a_sec",
            drive_file_id="rec_a_sec_01",
            file_name="call_telecaller_a.mp3",
            audio_data=b'SECRET_A_AUDIO',
            file_size=len(b'SECRET_A_AUDIO'),
            mime_type="audio/mpeg"
        )

        # Login as Telecaller B
        self.client.login(username='telecaller_b', password='Password@123')

        # 1. Dashboard does not show Telecaller A's folder or recording
        dash_resp = self.client.get(reverse('drive_dashboard'))
        self.assertEqual(dash_resp.status_code, 200)
        self.assertNotContains(dash_resp, "Telecaller A Folder")
        self.assertNotContains(dash_resp, "call_telecaller_a.mp3")

        # 2. Telecaller B cannot sync Telecaller A's folder via API
        sync_api_resp = self.client.get(reverse('drive_api_sync', args=[conn_a.pk]))
        self.assertEqual(sync_api_resp.status_code, 403)

        # 3. Telecaller B cannot sync Telecaller A's folder via POST
        sync_post_resp = self.client.post(reverse('drive_sync', args=[conn_a.pk]))
        self.assertEqual(sync_post_resp.status_code, 403)

        # 4. Telecaller B cannot disconnect Telecaller A's folder
        disc_resp = self.client.post(reverse('drive_disconnect', args=[conn_a.pk]))
        self.assertEqual(disc_resp.status_code, 403)
        conn_a.refresh_from_db()
        self.assertEqual(conn_a.connection_status, "Connected")

        # 5. Telecaller B cannot stream Telecaller A's audio
        stream_resp = self.client.get(reverse('drive_stream_recording', args=[rec_a.pk]))
        self.assertEqual(stream_resp.status_code, 403)

    def test_concurrent_sync_protection(self):
        """
        Verify that overlapping 10-second sync jobs are blocked while a sync is in progress.
        """
        conn = DriveConnection.objects.create(
            name="Concurrent Test Folder",
            folder_url="https://drive.google.com/drive/folders/folder_concurrent",
            folder_id="folder_concurrent",
            connection_status="Connected",
            is_active=True,
            is_syncing=True,  # Simulate another job currently running
            created_by=self.telecaller_a
        )

        success, msg, created, matched = sync_drive_connection(conn, triggered_by=self.telecaller_a)
        self.assertFalse(success)
        self.assertIn("already running", msg.lower())

    def test_renamed_file_in_drive_updates_metadata_without_duplicate(self):
        """
        Verify that if an audio file is renamed in Drive (same stable drive_file_id),
        the existing MySQL record is updated and NO duplicate record is created.
        """
        conn = DriveConnection.objects.create(
            name="Rename Test",
            folder_url="https://drive.google.com/drive/folders/rename_test_folder",
            folder_id="rename_test_folder",
            connection_status="Connected",
            is_active=True,
            created_by=self.telecaller_a
        )

        # Initial file
        files_v1 = [
            {'id': 'stable_id_01', 'name': 'call_9876543210_old.mp3', 'mimeType': 'audio/mpeg', 'audio_data': b'AUDIO_RENAME'}
        ]
        with patch('drive.services.fetch_drive_folder_data', return_value=(True, "", {'name': 'Rename Test', 'files': files_v1})):
            sync_drive_connection(conn, triggered_by=self.telecaller_a)

        self.assertEqual(CallRecording.objects.filter(drive_file_id='stable_id_01').count(), 1)
        rec = CallRecording.objects.get(drive_file_id='stable_id_01')
        self.assertEqual(rec.file_name, 'call_9876543210_old.mp3')

        # Renamed in Drive
        files_v2 = [
            {'id': 'stable_id_01', 'name': 'call_9876543210_new_renamed.mp3', 'mimeType': 'audio/mpeg', 'audio_data': b'AUDIO_RENAME'}
        ]
        with patch('drive.services.fetch_drive_folder_data', return_value=(True, "", {'name': 'Rename Test', 'files': files_v2})):
            sync_drive_connection(conn, triggered_by=self.telecaller_a)

        # Verify no duplicate created, and name updated
        self.assertEqual(CallRecording.objects.filter(drive_file_id='stable_id_01').count(), 1)
        rec.refresh_from_db()
        self.assertEqual(rec.file_name, 'call_9876543210_new_renamed.mp3')
        self.assertEqual(bytes(rec.audio_data), b'AUDIO_RENAME')

    def test_non_audio_files_are_ignored(self):
        """
        Verify that unrelated files (.pdf, .xlsx, .txt) in the Drive folder are ignored.
        """
        conn = DriveConnection.objects.create(
            name="Audio Filter Test",
            folder_url="https://drive.google.com/drive/folders/filter_folder",
            folder_id="filter_folder",
            connection_status="Connected",
            is_active=True,
            created_by=self.telecaller_a
        )

        files = [
            {'id': 'audio_f_1', 'name': 'call_01.mp3', 'mimeType': 'audio/mpeg', 'audio_data': b'MP3_DATA'},
            {'id': 'doc_f_1', 'name': 'notes.pdf', 'mimeType': 'application/pdf', 'content': b'PDF_DATA'},
            {'id': 'sheet_f_1', 'name': 'leads.xlsx', 'mimeType': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 'content': b'XLSX_DATA'},
            {'id': 'txt_f_1', 'name': 'readme.txt', 'mimeType': 'text/plain', 'content': b'TXT_DATA'},
        ]
        with patch('drive.services.fetch_drive_folder_data', return_value=(True, "", {'name': 'Filter Test', 'files': files})):
            success, message, created, matched = sync_drive_connection(conn, triggered_by=self.telecaller_a)
            self.assertTrue(success)

        # Only 1 audio file should be archived
        self.assertEqual(CallRecording.objects.filter(drive_connection=conn).count(), 1)
        self.assertTrue(CallRecording.objects.filter(drive_file_id='audio_f_1').exists())
        self.assertFalse(CallRecording.objects.filter(drive_file_id='doc_f_1').exists())
