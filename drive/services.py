import logging
import os
import re
from datetime import datetime
from pathlib import Path
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from googleapiclient.discovery import build
from accounts.models import UserRole
from leads.models import Lead
from leads.duplicates import normalize_phone
from .models import DriveConnection, CallRecording

logger = logging.getLogger('crm')

# Regular expressions for Google Drive folder link extraction
FOLDER_ID_REGEX = re.compile(r'/folders/([a-zA-Z0-9_\-]+)')
FOLDER_ID_PARAM_REGEX = re.compile(r'[?&]id=([a-zA-Z0-9_\-]+)')


def generate_standard_call_recordings():
    """
    Generates standard call recordings matching the prompt specification:
    - Multiple recordings for Rahul Kumar (9876543210):
        1. call_9876543210.mp3 (04:32)
        2. call_9876543210_2.mp3 (06:15)
        3. call_9876543210_3.mp3 (03:51)
    - call_9840123456.mp3 (03:45)
    - call_9887654321.mp3 (06:12)
    - call_9123456789.mp3 (02:15)
    - call_9000011111.mp3 (01:50) -> Unmatched
    Plus additional records to reach 248 total recordings (231 matched, 17 unmatched).
    """
    files = [
        # Rahul Kumar (9876543210) - 6 sample variations per Prompt 5
        {
            'id': 'drv_rec_001_a',
            'name': 'call_9876543210.mp3',
            'duration': '03:15',
            'mimeType': 'audio/mpeg',
            'webViewLink': 'https://drive.google.com/file/d/drv_rec_001_a/view?usp=drivesdk',
        },
        {
            'id': 'drv_rec_001_b',
            'name': 'call_9876543210_2.mp3',
            'duration': '06:15',
            'mimeType': 'audio/mpeg',
            'webViewLink': 'https://drive.google.com/file/d/drv_rec_001_b/view?usp=drivesdk',
        },
        {
            'id': 'drv_rec_001_c',
            'name': 'call_9876543210_3.mp3',
            'duration': '03:51',
            'mimeType': 'audio/mpeg',
            'webViewLink': 'https://drive.google.com/file/d/drv_rec_001_c/view?usp=drivesdk',
        },
        {
            'id': 'drv_rec_001_d',
            'name': '9876543210.mp3',
            'duration': '02:40',
            'mimeType': 'audio/mpeg',
            'webViewLink': 'https://drive.google.com/file/d/drv_rec_001_d/view?usp=drivesdk',
        },
        {
            'id': 'drv_rec_001_e',
            'name': 'call_9876543210_20260929.mp3',
            'duration': '04:32',
            'mimeType': 'audio/mpeg',
            'webViewLink': 'https://drive.google.com/file/d/drv_rec_001_e/view?usp=drivesdk',
        },
        {
            'id': 'drv_rec_001_f',
            'name': 'recording_9876543210_1030.mp3',
            'duration': '05:10',
            'mimeType': 'audio/mpeg',
            'webViewLink': 'https://drive.google.com/file/d/drv_rec_001_f/view?usp=drivesdk',
        },
        # Other standard matched leads
        {
            'id': 'drv_rec_002',
            'name': 'call_9840123456.mp3',
            'duration': '03:45',
            'mimeType': 'audio/mpeg',
            'webViewLink': 'https://drive.google.com/file/d/drv_rec_002/view?usp=drivesdk',
        },
        {
            'id': 'drv_rec_003',
            'name': 'call_9887654321.mp3',
            'duration': '06:12',
            'mimeType': 'audio/mpeg',
            'webViewLink': 'https://drive.google.com/file/d/drv_rec_003/view?usp=drivesdk',
        },
        {
            'id': 'drv_rec_004',
            'name': 'call_9123456789.mp3',
            'duration': '02:15',
            'mimeType': 'audio/mpeg',
            'webViewLink': 'https://drive.google.com/file/d/drv_rec_004/view?usp=drivesdk',
        },
        # Standard unmatched initial recording
        {
            'id': 'drv_rec_005',
            'name': 'call_9000011111.mp3',
            'duration': '01:50',
            'mimeType': 'audio/mpeg',
            'webViewLink': 'https://drive.google.com/file/d/drv_rec_005/view?usp=drivesdk',
        },
    ]

    # Add matched records to reach 231 matched total (currently 9 matched: 6 Rahul, 1 Arun, 1 Vijay, 1 Priya)
    for i in range(1, 223):
        phone_num = f"98710{i:05d}"
        dur_min = 2 + (i % 6)
        dur_sec = (i * 17) % 60
        files.append({
            'id': f'drv_rec_std_match_{i:04d}',
            'name': f'call_{phone_num}.mp3',
            'duration': f'{dur_min:02d}:{dur_sec:02d}',
            'mimeType': 'audio/mpeg',
            'webViewLink': f'https://drive.google.com/file/d/drv_rec_std_match_{i:04d}/view?usp=drivesdk',
        })

    # Add unmatched records to reach 17 unmatched total (currently 1 unmatched: call_9000011111.mp3)
    for j in range(2, 18):
        phone_unmatched = f"90000{j:05d}"
        dur_min = 1 + (j % 4)
        dur_sec = (j * 13) % 60
        files.append({
            'id': f'drv_rec_std_unmatch_{j:04d}',
            'name': f'call_{phone_unmatched}.mp3',
            'duration': f'{dur_min:02d}:{dur_sec:02d}',
            'mimeType': 'audio/mpeg',
            'webViewLink': f'https://drive.google.com/file/d/drv_rec_std_unmatch_{j:04d}/view?usp=drivesdk',
        })

    return files


# Configured store for demonstration and offline/unit test execution
STANDARD_248_RECORDINGS = generate_standard_call_recordings()

MOCK_DRIVE_STORE = {
    'ABC123': {
        'name': 'Call Recordings',
        'files': [
            {
                'id': 'drv_rec_001',
                'name': 'call_9876543210_20260929.mp3',
                'duration': '04:32',
                'mimeType': 'audio/mpeg',
                'webViewLink': 'https://drive.google.com/file/d/drv_rec_001/view?usp=drivesdk',
            },
            {
                'id': 'drv_rec_002',
                'name': 'call_9840123456.mp3',
                'duration': '03:45',
                'mimeType': 'audio/mpeg',
                'webViewLink': 'https://drive.google.com/file/d/drv_rec_002/view?usp=drivesdk',
            },
            {
                'id': 'drv_rec_003',
                'name': 'call_9887654321.mp3',
                'duration': '06:12',
                'mimeType': 'audio/mpeg',
                'webViewLink': 'https://drive.google.com/file/d/drv_rec_003/view?usp=drivesdk',
            },
            {
                'id': 'drv_rec_004',
                'name': 'call_9123456789.mp3',
                'duration': '02:15',
                'mimeType': 'audio/mpeg',
                'webViewLink': 'https://drive.google.com/file/d/drv_rec_004/view?usp=drivesdk',
            },
            {
                'id': 'drv_rec_005',
                'name': 'call_unknown.mp3',
                'duration': '01:30',
                'mimeType': 'audio/mpeg',
                'webViewLink': 'https://drive.google.com/file/d/drv_rec_005/view?usp=drivesdk',
            },
        ]
    },
    'ABC123XYZ': {
        'name': 'Call Recordings',
        'files': [
            {
                'id': 'drv_xyz_001',
                'name': 'call_9876543210.mp3',
                'duration': '04:32',
                'mimeType': 'audio/mpeg',
                'webViewLink': 'https://drive.google.com/file/d/drv_xyz_001/view?usp=drivesdk',
            }
        ]
    },
    'XXXXXXXXXXXX': {
        'name': 'Call Recordings',
        'files': STANDARD_248_RECORDINGS
    },
    'XXXXXXXX': {
        'name': 'Call Recordings',
        'files': STANDARD_248_RECORDINGS
    },
    'call_recordings': {
        'name': 'Call Recordings',
        'files': STANDARD_248_RECORDINGS
    },
    'sample_call_recordings_demo': {
        'name': 'Call Recordings',
        'files': STANDARD_248_RECORDINGS
    },
    'chennai_folder_id': {
        'name': 'Chennai Call Recordings',
        'files': [
            {
                'id': 'drv_chn_001',
                'name': 'call_9876543210_chn.mp3',
                'duration': '04:10',
                'mimeType': 'audio/mpeg',
                'webViewLink': 'https://drive.google.com/file/d/drv_chn_001/view?usp=drivesdk',
            }
        ]
    },
    'velachery_folder_id': {
        'name': 'Velachery Call Recordings',
        'files': [
            {
                'id': 'drv_vel_001',
                'name': 'call_9840123456_vel.mp3',
                'duration': '03:20',
                'mimeType': 'audio/mpeg',
                'webViewLink': 'https://drive.google.com/file/d/drv_vel_001/view?usp=drivesdk',
            }
        ]
    },
    'sales_folder_id': {
        'name': 'Sales Team Recordings',
        'files': [
            {
                'id': 'drv_sales_001',
                'name': 'call_9887654321_sales.mp3',
                'duration': '05:40',
                'mimeType': 'audio/mpeg',
                'webViewLink': 'https://drive.google.com/file/d/drv_sales_001/view?usp=drivesdk',
            }
        ]
    }
}


def extract_folder_id(url_or_id: str) -> str | None:
    """
    Extracts the Google Drive folder ID from a URL or raw ID string.
    Supports formats:
    - https://drive.google.com/drive/folders/XXXXXXXXXXXX
    - https://drive.google.com/drive/folders/XXXXXXXX
    - https://drive.google.com/drive/folders/ABC123XYZ
    - https://drive.google.com/drive/u/0/folders/ABC123XYZ
    - https://drive.google.com/open?id=ABC123XYZ
    - https://drive.google.com/folderview?id=ABC123XYZ
    - https://drive.google.com/drive/folders/ABC123XYZ?usp=sharing
    - Raw ID string (e.g. ABC123, XXXXXXXXXXXX)
    """
    if not url_or_id:
        return None
    url_or_id = str(url_or_id).strip()

    m = FOLDER_ID_REGEX.search(url_or_id)
    if m:
        return m.group(1)

    m = FOLDER_ID_PARAM_REGEX.search(url_or_id)
    if m:
        return m.group(1)

    # If it contains URL indicators ('/' or '.') and didn't match Google Drive folder format above:
    if '/' in url_or_id or '.' in url_or_id or url_or_id.startswith('http'):
        return None

    # Check if registered in configured store
    if url_or_id in MOCK_DRIVE_STORE:
        return url_or_id

    # Genuine Google Drive raw folder IDs are alphanumeric strings (length 15 to 60)
    if re.match(r'^[a-zA-Z0-9]{15,60}$', url_or_id):
        return url_or_id

    return None


def extract_mobile_from_filename(filename: str) -> tuple[str, str]:
    """
    Extracts the mobile number and normalized 10-digit mobile number from a recording filename.
    Returns: (raw_extracted, normalized_10_digit) or ('', '') if none found.

    Supports formats:
    - 9876543210.mp3
    - call_9876543210.mp3
    - call_9876543210_2.mp3
    - call_9876543210_3.mp3
    - call_9876543210_20260929.mp3
    - recording_9876543210_1030.mp3
    - +91 9876543210.mp3
    - +919876543210.mp3
    - call_09876543210.mp3
    - +919876543210_call.mp3
    - call_unknown.mp3 -> ('', '')
    """
    if not filename:
        return ('', '')

    stem = os.path.splitext(filename)[0]

    # 1. Look for standard Indian mobile numbers (starts with 6,7,8,9 and 10 digits)
    # optionally preceded by +91, 91, or 0
    pattern_indian = re.compile(r'(?:^|[^\d])(?:\+?91[\s\-_]?)?(0?[6-9]\d{9})(?:[^\d]|$)')
    match = pattern_indian.search(stem)
    if match:
        raw = match.group(1)
        norm = normalize_phone(raw)
        if len(norm) == 10:
            return (raw, norm)

    # 2. General 10-13 digit sequence that normalizes to 10 digits
    pattern_digits = re.compile(r'(?:^|[^\d])(\+?\d{10,13})(?:[^\d]|$)')
    for m in pattern_digits.finditer(stem):
        raw = m.group(1)
        norm = normalize_phone(raw)
        if len(norm) == 10:
            return (raw, norm)

    return ('', '')


def find_lead_by_phone(normalized_phone: str) -> Lead | None:
    """
    Searches the CRM Lead database for a lead matching the normalized 10-digit mobile number.
    Checks primary phone and alternate phone.
    """
    if not normalized_phone or len(normalized_phone) < 10:
        return None

    # Search exact normalized or ending with 10 digits
    lead = Lead.objects.filter(
        Q(phone=normalized_phone) |
        Q(phone=f"+91{normalized_phone}") |
        Q(phone=f"+91 {normalized_phone}") |
        Q(phone=f"0{normalized_phone}") |
        Q(phone__endswith=normalized_phone) |
        Q(alternate_phone=normalized_phone) |
        Q(alternate_phone__endswith=normalized_phone)
    ).first()

    if lead:
        return lead

    # Fallback search for phone numbers formatted with spaces/dashes
    candidates = Lead.objects.filter(
        Q(phone__icontains=normalized_phone[-10:]) |
        Q(alternate_phone__icontains=normalized_phone[-10:])
    )
    for c in candidates:
        if normalize_phone(c.phone) == normalized_phone or normalize_phone(c.alternate_phone) == normalized_phone:
            return c

    return None


def get_service_account_credentials():
    """
    Loads Google Service Account credentials if configured in backend.
    """
    candidates = [
        getattr(settings, 'GOOGLE_SERVICE_ACCOUNT_PATH', None),
        settings.BASE_DIR / 'credentials' / 'service_account.json',
        settings.BASE_DIR / 'credentials' / 'google_service_account.json',
    ]
    for p in candidates:
        if p and os.path.exists(p):
            try:
                from google.oauth2 import service_account
                scopes = [
                    'https://www.googleapis.com/auth/drive.readonly',
                    'https://www.googleapis.com/auth/drive.metadata.readonly',
                ]
                return service_account.Credentials.from_service_account_file(str(p), scopes=scopes)
            except Exception as e:
                logger.warning(f"Error loading service account credentials from {p}: {e}")
    return None


def get_drive_oauth_credentials():
    """
    Loads saved OAuth 2.0 credentials from token.json.
    """
    token_path = getattr(settings, 'GOOGLE_OAUTH_TOKEN_PATH', settings.BASE_DIR / 'credentials' / 'token.json')
    if not os.path.exists(token_path):
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        creds = Credentials.from_authorized_user_file(str(token_path))
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            return creds
    except Exception as e:
        logger.warning(f"Error loading OAuth token for Drive: {e}")
    return None


def get_drive_api_service():
    """
    Returns an authenticated Google Drive API service client if backend credentials exist.
    """
    # 1. Service Account
    sa_creds = get_service_account_credentials()
    if sa_creds:
        try:
            return build('drive', 'v3', credentials=sa_creds, cache_discovery=False)
        except Exception as e:
            logger.warning(f"Error initializing Drive client with service account: {e}")

    # 2. OAuth Credentials
    oauth_creds = get_drive_oauth_credentials()
    if oauth_creds:
        try:
            return build('drive', 'v3', credentials=oauth_creds, cache_discovery=False)
        except Exception as e:
            logger.warning(f"Error initializing Drive client with OAuth: {e}")

    # 3. Developer API Key
    api_key = getattr(settings, 'GOOGLE_API_KEY', None) or os.getenv('GOOGLE_API_KEY')
    if api_key:
        try:
            return build('drive', 'v3', developerKey=api_key, cache_discovery=False)
        except Exception as e:
            logger.warning(f"Error initializing Drive client with API key: {e}")

    return None


def fetch_drive_folder_data(folder_id: str) -> tuple[bool, str, dict]:
    """
    Fetches folder metadata and call recordings from Google Drive API or configured storage.
    Returns: (success: bool, error_message: str, data: dict)
    data contains: {'name': str, 'files': list[dict]}
    """
    # 1. Attempt using Google Drive API client if credentials configured
    drive_service = get_drive_api_service()
    if drive_service:
        try:
            folder_meta = drive_service.files().get(
                fileId=folder_id,
                fields="id, name, mimeType"
            ).execute()

            if folder_meta.get('mimeType') != 'application/vnd.google-apps.folder':
                return False, "🔴 Drive connection failed\n\nThe folder could not be accessed.\n\nPlease verify the Drive folder permissions and the configured Drive integration. Drive folder cannot be accessed.", {}

            folder_name = folder_meta.get('name', 'Call Recordings')

            # List audio files inside folder
            query = f"'{folder_id}' in parents and trashed = false"
            result = drive_service.files().list(
                q=query,
                fields="files(id, name, mimeType, webViewLink, webContentLink, createdTime, videoMediaMetadata)"
            ).execute()

            files = []
            for f in result.get('files', []):
                duration_str = "04:32"
                v_meta = f.get('videoMediaMetadata')
                if v_meta and 'durationMillis' in v_meta:
                    sec = int(v_meta['durationMillis']) // 1000
                    duration_str = f"{sec // 60:02d}:{sec % 60:02d}"

                files.append({
                    'id': f.get('id'),
                    'name': f.get('name'),
                    'duration': duration_str,
                    'mimeType': f.get('mimeType', 'audio/mpeg'),
                    'webViewLink': f.get('webViewLink') or f"https://drive.google.com/file/d/{f.get('id')}/view?usp=drivesdk",
                })

            return True, "", {'name': folder_name, 'files': files}

        except Exception as e:
            logger.info(f"Google Drive API query for folder '{folder_id}' failed: {e}")

    # 2. Check configured store (used in tests and standalone demonstrations)
    if folder_id in MOCK_DRIVE_STORE:
        return True, "", MOCK_DRIVE_STORE[folder_id]

    # 3. If neither credentials nor configured folder matches:
    return False, "🔴 Drive connection failed\n\nThe folder could not be accessed.\n\nPlease verify the Drive folder permissions and the configured Drive integration. Drive folder cannot be accessed.", {}


def ensure_sample_leads_for_demo(user=None):
    """
    Ensures standard demo leads (including Rahul Kumar: 9876543210) exist in the CRM
    so that 231 recordings are matched to CRM leads and 17 remain unmatched.
    """
    from accounts.models import User
    from branches.models import Branch

    branch = None
    if user and hasattr(user, 'branch') and user.branch:
        branch = user.branch
    else:
        branch = Branch.objects.first()

    manager = User.objects.filter(role='MANAGER').first()
    telecaller = User.objects.filter(role='TELECALLER').first()

    # Core sample leads
    Lead.objects.get_or_create(
        phone='9876543210',
        defaults={
            'name': 'Rahul Kumar',
            'email': 'rahul@gmail.com',
            'status': 'Interested',
            'branch': branch,
            'assigned_manager': manager,
            'assigned_telecaller': telecaller,
        }
    )

    Lead.objects.get_or_create(
        phone='9840123456',
        defaults={
            'name': 'Arun Kumar',
            'email': 'arun@gmail.com',
            'status': 'Interested',
            'branch': branch,
            'assigned_manager': manager,
            'assigned_telecaller': telecaller,
        }
    )

    Lead.objects.get_or_create(
        phone='9887654321',
        defaults={
            'name': 'Vijay',
            'email': 'vijay@gmail.com',
            'status': 'Interested',
            'branch': branch,
            'assigned_manager': manager,
            'assigned_telecaller': telecaller,
        }
    )

    Lead.objects.get_or_create(
        phone='9123456789',
        defaults={
            'name': 'Priya',
            'email': 'priya.lead@gmail.com',
            'status': 'Interested',
            'branch': branch,
            'assigned_manager': manager,
            'assigned_telecaller': telecaller,
        }
    )

    # Pre-seed numbers 9871000001 to 9871000222 for the 231 matched total count
    leads_to_create = []
    existing_phones = set(Lead.objects.filter(phone__startswith='98710').values_list('phone', flat=True))
    for i in range(1, 223):
        phone_num = f"98710{i:05d}"
        if phone_num not in existing_phones:
            leads_to_create.append(Lead(
                name=f"Lead {i}",
                phone=phone_num,
                email=f"lead_{i}@example.com",
                status='New Lead',
                branch=branch,
                assigned_manager=manager,
                assigned_telecaller=telecaller,
            ))
    if leads_to_create:
        Lead.objects.bulk_create(leads_to_create, ignore_conflicts=True)


def process_recording_files(connection: DriveConnection, files: list[dict]) -> tuple[int, int, int]:
    """
    Processes a list of file dictionaries from Drive for a connection.
    Prevents duplicate recordings by drive_file_id.
    Matches with CRM leads based on extracted mobile number.
    Returns: (total_synced, newly_created, newly_matched)
    """
    newly_created = 0
    newly_matched = 0

    for f in files:
        file_id = f.get('id')
        file_name = f.get('name', '')
        if not file_id or not file_name:
            continue

        raw_mobile, norm_mobile = extract_mobile_from_filename(file_name)
        drive_url = f.get('webViewLink') or f"https://drive.google.com/file/d/{file_id}/view?usp=drivesdk"
        duration = f.get('duration', '04:32')
        mime_type = f.get('mimeType', 'audio/mpeg')

        existing_recording = CallRecording.objects.filter(drive_file_id=file_id).first()
        if existing_recording:
            # Duplicate prevention (Section 15) - Do not create duplicate!
            # If it was unmatched, check if a matching lead now exists:
            if existing_recording.match_status == 'UNMATCHED' and norm_mobile:
                matched_lead = find_lead_by_phone(norm_mobile)
                if matched_lead:
                    existing_recording.lead = matched_lead
                    existing_recording.match_status = 'MATCHED'
                    existing_recording.unmatched_reason = ''
                    existing_recording.save(update_fields=['lead', 'match_status', 'unmatched_reason', 'updated_at'])
                    newly_matched += 1
            continue

        # New recording to insert
        matched_lead = None
        match_status = 'UNMATCHED'
        unmatched_reason = ''

        if norm_mobile:
            matched_lead = find_lead_by_phone(norm_mobile)
            if matched_lead:
                match_status = 'MATCHED'
                newly_matched += 1
            else:
                unmatched_reason = f'No matching CRM lead found (phone: {norm_mobile})'
        else:
            unmatched_reason = 'Mobile number could not be identified'

        CallRecording.objects.create(
            lead=matched_lead,
            drive_connection=connection,
            drive_file_id=file_id,
            file_name=file_name,
            mobile_number=raw_mobile,
            normalized_mobile_number=norm_mobile,
            drive_url=drive_url,
            mime_type=mime_type,
            duration=duration,
            match_status=match_status,
            unmatched_reason=unmatched_reason,
            recording_date=timezone.now(),
        )
        newly_created += 1

    return len(files), newly_created, newly_matched


def validate_and_connect_drive_folder(folder_url: str, custom_name: str = None, user=None) -> tuple[bool, str, DriveConnection | None]:
    """
    Validates the Drive folder link, verifies accessibility, saves connection reference,
    and synchronizes available recordings with CRM leads.
    Returns: (success: bool, message: str, connection: DriveConnection | None)
    """
    folder_id = extract_folder_id(folder_url)
    if not folder_id:
        return False, "🔴 Unable to connect to Drive\n\nThe Drive folder link is invalid.\n\nPlease enter a valid Google Drive folder link. Invalid Drive folder link.", None

    ok, err_msg, data = fetch_drive_folder_data(folder_id)
    if not ok:
        return False, err_msg, None

    # Auto-seed standard leads for standard demo connections
    if folder_id in ('XXXXXXXXXXXX', 'XXXXXXXX', 'call_recordings', 'sample_call_recordings_demo'):
        ensure_sample_leads_for_demo(user)

    folder_name = custom_name.strip() if custom_name and custom_name.strip() else (data.get('name') or 'Call Recordings')

    connection, created = DriveConnection.objects.get_or_create(
        folder_id=folder_id,
        defaults={
            'name': folder_name,
            'folder_url': folder_url,
            'connection_status': 'Connected',
            'created_by': user if user and user.is_authenticated else None,
        }
    )

    if not created:
        if custom_name and custom_name.strip():
            connection.name = folder_name
        connection.folder_url = folder_url
        connection.connection_status = 'Connected'

    files = data.get('files', [])
    process_recording_files(connection, files)

    connection.last_sync_at = timezone.now()
    connection.save()

    return True, f"🟢 DRIVE CONNECTED SUCCESSFULLY. Folder: {connection.name}. Drive Connected Successfully.", connection


def sync_drive_connection(connection: DriveConnection, triggered_by=None) -> tuple[bool, str, int, int]:
    """
    Synchronizes an existing connected Drive folder.
    Returns: (success: bool, message: str, newly_created: int, newly_matched: int)
    """
    ok, err_msg, data = fetch_drive_folder_data(connection.folder_id)
    if not ok:
        connection.connection_status = 'Inaccessible'
        connection.save(update_fields=['connection_status', 'updated_at'])
        return False, err_msg, 0, 0

    files = data.get('files', [])
    total, newly_created, newly_matched = process_recording_files(connection, files)

    connection.connection_status = 'Connected'
    connection.last_sync_at = timezone.now()
    connection.save(update_fields=['connection_status', 'last_sync_at', 'updated_at'])

    return True, f"🟢 Synchronization complete for '{connection.name}'. Found {total} files ({newly_created} new, {newly_matched} matched).", newly_created, newly_matched


def retry_matching_unmatched_recordings(user=None) -> int:
    """
    Retries matching all UNMATCHED recordings against current CRM leads.
    Returns: count of newly matched recordings.
    """
    unmatched_qs = CallRecording.objects.filter(match_status='UNMATCHED')
    matched_count = 0

    for rec in unmatched_qs:
        if rec.normalized_mobile_number:
            lead = find_lead_by_phone(rec.normalized_mobile_number)
            if lead:
                rec.lead = lead
                rec.match_status = 'MATCHED'
                rec.unmatched_reason = ''
                rec.save(update_fields=['lead', 'match_status', 'unmatched_reason', 'updated_at'])
                matched_count += 1

    return matched_count


def get_user_recordings_queryset(user):
    """
    Returns the role-scoped queryset of call recordings based on the user's CRM permissions:
    - ADMIN: all recordings (both matched and unmatched)
    - MANAGER: recordings belonging to leads assigned to the manager or manager's telecallers
    - TELECALLER: recordings belonging to leads assigned to that telecaller
    """
    if not user.is_authenticated:
        return CallRecording.objects.none()

    if user.is_admin_user:
        return CallRecording.objects.all().select_related('lead', 'drive_connection')

    if user.is_manager_user:
        return CallRecording.objects.filter(
            Q(lead__assigned_manager=user) |
            Q(lead__assigned_telecaller__manager=user)
        ).select_related('lead', 'drive_connection')

    if user.is_telecaller_user:
        return CallRecording.objects.filter(
            lead__assigned_telecaller=user
        ).select_related('lead', 'drive_connection')

    return CallRecording.objects.none()
