import io
import logging
import re
import urllib.parse
import urllib.request
from typing import Any
from .google_sheets_parser import parse_csv_content, clean_and_deduplicate_headers, sanitize_cell_value

logger = logging.getLogger('crm')

# Regex to match spreadsheet ID from Google Docs URL
SPREADSHEET_ID_REGEX = re.compile(r'/spreadsheets/d/([a-zA-Z0-9-_]{15,100})')
# Regex to match GID (worksheet tab identifier)
GID_REGEX = re.compile(r'[#&?]gid=([0-9]+)')

# Permitted Google domains to prevent SSRF
ALLOWED_GOOGLE_HOSTS = {
    'docs.google.com',
    'drive.google.com',
    'spreadsheets.google.com'
}

MAX_SPREADSHEET_BYTES = 10 * 1024 * 1024  # 10 MB limit


def validate_url(url: str) -> tuple[bool, str | None]:
    """
    Validates that a URL is a well-formed Google Sheets link on an allowed Google domain.
    Prevents SSRF and arbitrary host access.
    Returns: (is_valid, error_message)
    """
    if not url or not isinstance(url, str):
        return False, "Google Spreadsheet URL cannot be empty."

    url = url.strip()
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False, "Invalid URL structure."

    if parsed.scheme.lower() not in ('http', 'https'):
        return False, "URL must use HTTPS protocol."

    netloc = parsed.netloc.lower().split(':')[0]
    if netloc not in ALLOWED_GOOGLE_HOSTS:
        return False, f"Invalid domain '{netloc}'. Only Google Sheets URLs on docs.google.com are supported."

    if '/spreadsheets/d/' not in parsed.path:
        return False, "URL does not contain a valid Google Spreadsheet path (/spreadsheets/d/<id>)."

    s_id = extract_spreadsheet_id(url)
    if not s_id:
        return False, "Could not extract a valid Google Spreadsheet ID from the URL."

    return True, None


def extract_spreadsheet_id(url_or_id: str) -> str | None:
    """
    Extracts the spreadsheet ID string from a Google Sheets URL or validates a raw ID.
    Example: https://docs.google.com/spreadsheets/d/1ABCXYZ123456789/edit -> '1ABCXYZ123456789'
    """
    if not url_or_id or not isinstance(url_or_id, str):
        return None

    raw = url_or_id.strip()
    match = SPREADSHEET_ID_REGEX.search(raw)
    if match:
        return match.group(1)

    # If already a bare alphanumeric ID (min 15 chars, max 100 chars)
    if re.match(r'^[a-zA-Z0-9-_]{15,100}$', raw):
        return raw

    return None


def extract_gid(url: str) -> str | None:
    """
    Extracts the numeric GID (sheet tab ID) from a Google Sheet URL.
    Example: .../edit#gid=12345678 -> '12345678'
    Returns '0' if no explicit gid parameter is found.
    """
    if not url or not isinstance(url, str):
        return '0'

    match = GID_REGEX.search(url.strip())
    if match:
        return match.group(1)

    return '0'


def build_fetch_url(spreadsheet_id: str, gid: str = None, sheet_name: str = None) -> str:
    """
    Constructs the primary public CSV export endpoint for a given spreadsheet and tab.
    Priority:
    1. If sheet_name is given and not 'Sheet1': uses gviz/tq?tqx=out:csv&sheet=<name>
    2. If gid is given and not '0': uses gviz/tq?tqx=out:csv&gid=<gid>
    3. Default: gviz/tq?tqx=out:csv
    """
    base = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv"
    if sheet_name and sheet_name.strip() and sheet_name.strip().lower() != 'sheet1':
        encoded_name = urllib.parse.quote(sheet_name.strip())
        return f"{base}&sheet={encoded_name}"
    if gid and gid.strip() and gid.strip() != '0':
        return f"{base}&gid={gid.strip()}"
    return base


def fetch_sheet(
    spreadsheet_id: str,
    gid: str = None,
    sheet_name: str = None,
    timeout: int = 8
) -> tuple[list[str], list[dict[str, str]]]:
    """
    Fetches latest data from a publicly accessible Google Sheet without any authentication.
    Tries multiple fallback endpoints in order:
    1. Google Visualization CSV API with sheet tab name
    2. Google Visualization CSV API with gid
    3. Standard Google Sheets export URL (export?format=csv)
    Returns: (headers_list, rows_list_of_dicts)
    """
    urls_to_try: list[str] = []

    if sheet_name and sheet_name.strip():
        encoded_name = urllib.parse.quote(sheet_name.strip())
        urls_to_try.append(
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv&sheet={encoded_name}"
        )

    if gid and gid.strip():
        urls_to_try.append(
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv&gid={gid.strip()}"
        )
        urls_to_try.append(
            f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv&gid={gid.strip()}"
        )

    # General fallback endpoints
    urls_to_try.append(f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/gviz/tq?tqx=out:csv")
    urls_to_try.append(f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=csv")

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) CRM-GoogleSheetsIntegration/2.0'}

    last_error = None
    for fetch_url in urls_to_try:
        try:
            req = urllib.request.Request(fetch_url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as response:
                # Check HTTP status
                status_code = getattr(response, 'status', 200)
                if status_code != 200:
                    continue

                raw_bytes = response.read(MAX_SPREADSHEET_BYTES)
                content = raw_bytes.decode('utf-8', errors='ignore')

                # Check if Google returned an HTML login page or access denied page
                if '<!DOCTYPE html>' in content or '<html' in content.lower():
                    if 'accounts.google.com' in content or 'ServiceLogin' in content:
                        raise PermissionError(
                            "This Google Sheet is private or requires Google login. "
                            "Please set link sharing to 'Anyone with the link can view' and try again."
                        )

                parsed_headers, parsed_rows = parse_csv_content(content)
                if parsed_headers:
                    logger.info(
                        f"Successfully fetched {len(parsed_rows)} rows from public endpoint '{fetch_url}'."
                    )
                    return parsed_headers, parsed_rows

        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise PermissionError(
                    "This Google Sheet is not publicly accessible (HTTP 403/401). "
                    "Please set sharing to 'Anyone with the link' and try again."
                )
            elif e.code == 404:
                last_error = f"Google Sheet or specified tab could not be found (HTTP 404)."
            else:
                last_error = f"HTTP Error {e.code} while fetching Google Sheet."
        except urllib.error.URLError as e:
            last_error = f"Network connection error while reaching Google Sheets: {e.reason}"
        except TimeoutError:
            last_error = "Connection to Google Sheets timed out. Please try again."
        except PermissionError:
            raise
        except Exception as e:
            last_error = str(e)

    if last_error:
        logger.warning(f"Failed to fetch public Google Sheet '{spreadsheet_id}': {last_error}")
    return [], []


def parse_sheet(raw_csv_content: str) -> tuple[list[str], list[dict[str, str]]]:
    """
    Parses raw CSV content into clean headers and structured row dictionaries.
    Wrapper around parse_csv_content for service interface conformity.
    """
    return parse_csv_content(raw_csv_content)


def normalize_rows(
    raw_headers: list[str],
    raw_rows: list[list[Any]]
) -> tuple[list[str], list[dict[str, str]]]:
    """
    Converts list-of-lists rows into clean header-keyed dictionaries with normalized headers.
    """
    headers = clean_and_deduplicate_headers(raw_headers)
    data_rows: list[dict[str, str]] = []

    for idx, row_vals in enumerate(raw_rows, start=2):
        if not any(str(v).strip() for v in row_vals if v is not None):
            continue
        row_dict: dict[str, str] = {'_row_index': idx}
        for c_idx, h_name in enumerate(headers):
            val = row_vals[c_idx] if c_idx < len(row_vals) else ''
            row_dict[h_name] = sanitize_cell_value(val)
        data_rows.append(row_dict)

    return headers, data_rows
