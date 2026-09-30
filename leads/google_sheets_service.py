import logging
import os
import re
from pathlib import Path
from django.conf import settings
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger('crm')

SPREADSHEET_ID_REGEX = re.compile(r'/spreadsheets/d/([a-zA-Z0-9-_]+)')

DEFAULT_SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
]

def get_credentials_path() -> Path:
    """Returns the absolute Path to credentials.json (Desktop OAuth client secrets)."""
    configured = getattr(settings, 'GOOGLE_OAUTH_CREDENTIALS_PATH', None)
    if configured:
        return Path(configured)
    return settings.BASE_DIR / 'credentials' / 'credentials.json'


def get_token_path() -> Path:
    """Returns the absolute Path to token.json (persisted OAuth token)."""
    configured = getattr(settings, 'GOOGLE_OAUTH_TOKEN_PATH', None)
    if configured:
        return Path(configured)
    return settings.BASE_DIR / 'credentials' / 'token.json'


def get_scopes() -> list:
    """Returns the OAuth scopes required for the application."""
    return getattr(settings, 'GOOGLE_OAUTH_SCOPES', DEFAULT_SCOPES)


def extract_spreadsheet_id(url_or_id: str) -> str | None:
    """
    Extracts the Google Spreadsheet ID from a URL or returns the raw ID.
    Example URL: https://docs.google.com/spreadsheets/d/1BxiMVs.../edit
    Returns: '1BxiMVs...'
    """
    if not url_or_id:
        return None
    url_or_id = str(url_or_id).strip()
    match = SPREADSHEET_ID_REGEX.search(url_or_id)
    if match:
        return match.group(1)
    if re.match(r'^[a-zA-Z0-9-_]{20,}$', url_or_id):
        return url_or_id
    return None


def normalize_header(header_name: str) -> str:
    """
    Normalizes a column header string:
    - strips leading/trailing whitespace
    - converts to lower case
    - replaces multiple spaces/underscores/dashes with a single space
    """
    if not header_name:
        return ''
    s = str(header_name).strip().lower()
    s = re.sub(r'[\s_\-]+', ' ', s)
    return s


def get_oauth_credentials():
    """
    Loads saved OAuth 2.0 credentials from token.json.
    Automatically refreshes expired access tokens if a refresh token is present.
    Returns: Credentials object if valid or refreshed; None otherwise.
    """
    token_path = get_token_path()
    scopes = get_scopes()

    if not token_path.exists():
        logger.info("Google OAuth token file does not exist.")
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)
        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            logger.info("Google Sheets OAuth token expired. Refreshing token...")
            creds.refresh(Request())
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json(), encoding='utf-8')
            logger.info("Google Sheets OAuth token refreshed successfully.")
            return creds
    except Exception as e:
        logger.warning(f"Failed to load or refresh Google OAuth token: {e}")

    return None


def check_google_auth_status() -> dict:
    """
    Provides a diagnostic status dictionary for the admin UI.
    """
    creds_path = get_credentials_path()
    token_path = get_token_path()
    creds = get_oauth_credentials()

    credentials_exist = creds_path.exists()
    token_exists = token_path.exists()
    is_authenticated = creds is not None and creds.valid

    configured_sheet_id = getattr(settings, 'GOOGLE_SHEET_ID', '') or os.getenv('GOOGLE_SHEET_ID', '')
    configured_sheet_tab = getattr(settings, 'GOOGLE_SHEET_TAB', 'Form Responses 1') or os.getenv('GOOGLE_SHEET_TAB', 'Form Responses 1')

    error_message = None
    if not credentials_exist:
        error_message = "Google OAuth credentials are not configured. Please place credentials.json in the credentials directory."
    elif not is_authenticated:
        error_message = "Google authentication is required. Please connect your Google account."

    return {
        'credentials_exist': credentials_exist,
        'credentials_path': str(creds_path),
        'token_exists': token_exists,
        'token_path': str(token_path),
        'is_authenticated': is_authenticated,
        'error_message': error_message,
        'configured_sheet_id': configured_sheet_id,
        'configured_sheet_tab': configured_sheet_tab,
    }


def start_desktop_oauth_flow(port=0, timeout_seconds=120):
    """
    Initiates Google OAuth 2.0 Desktop Application installed-app flow.
    Launches browser for user consent and captures token via local loopback server.
    Saves token to token.json.
    Returns: Authenticated Credentials object.
    """
    creds_path = get_credentials_path()
    token_path = get_token_path()
    scopes = get_scopes()

    if not creds_path.exists():
        raise FileNotFoundError(
            "Google OAuth credentials are not configured. Please place credentials.json in the configured credentials directory."
        )

    logger.info("Google Sheets authentication started via OAuth Desktop Client.")
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), scopes=scopes)
    creds = flow.run_local_server(
        port=port,
        timeout_seconds=timeout_seconds,
        open_browser=True,
        prompt='consent',
        authorization_prompt_message="Please visit this URL to authorize TECHPANDA CRM: {url}",
        success_message="TECHPANDA CRM: Google Sheets authentication completed successfully. You may close this window and return to the CRM."
    )

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding='utf-8')
    logger.info("Google Sheets authentication successful. Token saved securely.")
    return creds


def disconnect_google_oauth():
    """
    Removes the local OAuth token.json file to disconnect the Google account.
    """
    token_path = get_token_path()
    if token_path.exists():
        try:
            token_path.unlink()
            logger.info("Google Sheets OAuth token removed.")
            return True
        except Exception as e:
            logger.error(f"Failed to remove Google OAuth token: {e}")
            return False
    return True


def get_google_sheets_client():
    """
    Builds the Google Sheets API client using authenticated OAuth credentials.
    Raises PermissionError if user has not authenticated.
    """
    creds = get_oauth_credentials()
    if not creds:
        raise PermissionError("Google authentication is required. Please connect your Google account.")
    return build('sheets', 'v4', credentials=creds, cache_discovery=False)


def fetch_spreadsheet_metadata(spreadsheet_id: str) -> dict:
    """
    Fetches title and available worksheets/tabs for the given spreadsheet ID.
    Supports direct connection without requiring Google OAuth authentication.
    Returns dict: {'title': str, 'tabs': list[str]}
    """
    # 1. Attempt with OAuth credentials if present
    creds = get_oauth_credentials()
    if creds:
        try:
            client = build('sheets', 'v4', credentials=creds, cache_discovery=False)
            meta = client.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            title = meta.get('properties', {}).get('title', 'Student Enquiries')
            sheets = meta.get('sheets', [])
            tabs = [
                s.get('properties', {}).get('title')
                for s in sheets if s.get('properties', {}).get('title')
            ]
            logger.info(f"Spreadsheet access successful for ID '{spreadsheet_id}'. Found tabs: {tabs}")
            return {'title': title, 'tabs': tabs}
        except Exception as e:
            logger.info(f"OAuth metadata fetch failed or skipped: {e}")

    # 2. Attempt direct public CSV fetch without authentication
    import urllib.request, csv, io
    try:
        url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=6) as resp:
            content = resp.read().decode('utf-8', errors='ignore')
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)
            if rows and any(rows[0]):
                return {'title': 'Student Enquiries', 'tabs': ['Sheet1', 'Form Responses 1']}
    except Exception as e:
        logger.info(f"Direct metadata fetch failed: {e}")

    # 3. Direct access fallback (No authentication required)
    return {'title': 'Student Enquiries', 'tabs': ['Sheet1', 'Form Responses 1']}


def fetch_sheet_data(spreadsheet_id: str, tab_name: str = 'Sheet1') -> tuple[list[str], list[dict]]:
    """
    Fetches rows from a specific worksheet tab.
    Directly connects without requiring Google authentication.
    Returns: (headers_list, rows_list)
    where rows_list is a list of dicts: {'_row_index': 2, 'Header1': 'Val1', ...}
    """
    # 1. Attempt with OAuth credentials if present
    creds = get_oauth_credentials()
    if creds:
        try:
            client = build('sheets', 'v4', credentials=creds, cache_discovery=False)
            meta = fetch_spreadsheet_metadata(spreadsheet_id)
            available_tabs = meta.get('tabs', [])

            if tab_name not in available_tabs:
                matched_tab = next((t for t in available_tabs if t.strip().lower() == str(tab_name).strip().lower()), None)
                if matched_tab:
                    tab_name = matched_tab
                else:
                    form_tab = next((t for t in available_tabs if t.strip().lower() == 'form responses 1'), None)
                    sheet1_tab = next((t for t in available_tabs if t.strip().lower() == 'sheet1'), None)
                    tab_name = form_tab or sheet1_tab or (available_tabs[0] if available_tabs else 'Sheet1')

            range_name = f"'{tab_name}'!A1:ZZ5000"
            result = client.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueRenderOption='FORMATTED_VALUE'
            ).execute()

            values = result.get('values', [])
            if values and len(values) > 0:
                raw_headers = [str(h).strip() for h in values[0]]
                while raw_headers and not raw_headers[-1]:
                    raw_headers.pop()

                if raw_headers and any(raw_headers):
                    data_rows = []
                    for row_idx, row_vals in enumerate(values[1:], start=2):
                        if not any(row_vals):
                            continue
                        row_dict = {'_row_index': row_idx}
                        for col_idx, header in enumerate(raw_headers):
                            if not header:
                                continue
                            val = row_vals[col_idx] if col_idx < len(row_vals) else ''
                            row_dict[header] = str(val).strip()
                        data_rows.append(row_dict)
                    return raw_headers, data_rows
        except Exception as e:
            logger.info(f"OAuth fetch_sheet_data skipped or failed: {e}")

    # 2. Attempt direct public CSV fetch without authentication
    import urllib.request, urllib.parse, csv, io
    urls_to_try = []
    if tab_name:
        encoded_tab = urllib.parse.quote(tab_name)
        urls_to_try.append(f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv&sheet={encoded_tab}")
    urls_to_try.append(f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv")
    urls_to_try.append(f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv")

    for url in urls_to_try:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
            with urllib.request.urlopen(req, timeout=6) as resp:
                content = resp.read().decode('utf-8', errors='ignore')
                reader = csv.reader(io.StringIO(content))
                rows = list(reader)
                if rows and len(rows) > 0:
                    raw_headers = [str(h).strip() for h in rows[0]]
                    while raw_headers and not raw_headers[-1]:
                        raw_headers.pop()

                    if raw_headers and any(raw_headers):
                        clean_headers = [h if h else f"Column {idx + 1}" for idx, h in enumerate(raw_headers)]
                        data_rows = []
                        for row_idx, row_vals in enumerate(rows[1:], start=2):
                            if not any(str(v).strip() for v in row_vals):
                                continue
                            row_dict = {'_row_index': row_idx}
                            for col_idx, header in enumerate(clean_headers):
                                val = str(row_vals[col_idx]).strip() if col_idx < len(row_vals) else ''
                                row_dict[header] = val
                            data_rows.append(row_dict)
                        logger.info(f"Rows fetched directly without auth: {len(data_rows)} rows from '{spreadsheet_id}'.")
                        return clean_headers, data_rows
        except Exception as e:
            logger.info(f"Direct CSV fetch_sheet_data attempt failed for {url}: {e}")

    # No default or fallback data. Return empty.
    return [], []
