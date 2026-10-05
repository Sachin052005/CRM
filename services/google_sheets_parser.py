import csv
import io
import re
import unicodedata
from typing import Any

# Patterns for dynamic CRM header mapping
HEADER_PATTERNS = {
    'name': [
        'full name', 'fullname', 'name', 'lead name', 'student name',
        'candidate name', 'applicant name', 'client name', 'person name',
        'student', 'candidate', 'பெயர்'
    ],
    'first_name': [
        'first name', 'firstname', 'given name'
    ],
    'last_name': [
        'last name', 'lastname', 'surname', 'family name'
    ],
    'phone': [
        'phone number', 'phonenumber', 'phone', 'mobile number',
        'mobilenumber', 'mobile', 'contact number', 'contactnumber',
        'contact', 'whatsapp number', 'whatsapp', 'contact phone',
        'phone no', 'phoneno', 'mobile no', 'mobileno', 'contact no', 'contactno',
        'tel', 'telephone', 'cell', 'cell phone', 'தொலைபேசி', 'கைபேசி'
    ],
    'alternate_phone': [
        'alternate phone', 'alternate mobile', 'alt phone', 'alt mobile',
        'secondary phone', 'alternate number', 'second phone', 'alternate contact',
        'alt phone no', 'alt mobile no'
    ],
    'email': [
        'email address', 'emailaddress', 'email', 'e mail',
        'e mail address', 'mail id', 'mailid', 'email id', 'emailid', 'mail',
        'மின்னஞ்சல்'
    ],
    'product': [
        'interested course', 'interested product', 'course', 'product',
        'program', 'interested in', 'course interested', 'course name', 'stream',
        'wat course are you looking for ?', 'wat course are you looking for',
        'what course are you looking for ?', 'what course are you looking for',
        'courses', 'விருப்பமான படிப்பு'
    ],
    'branch': [
        'branch', 'center', 'branch center', 'location', 'city',
        'preferred branch', 'preferred location', 'campus', 'preferred center',
        'கிளை', 'இடம்'
    ],
    'channel': [
        'channel', 'lead source', 'source', 'platform', 'campaign', 'channel name'
    ],
    'status': [
        'status', 'lead status'
    ],
    'notes': [
        'notes', 'remarks', 'comments', 'feedback', 'message', 'query',
        'comments / questions', 'comments/questions',
        'what you looking for?', 'what you looking for',
        'what is your current status?', 'what is your current status',
        'requirement', 'conservation step', 'qualification', 'குறிப்புகள்'
    ],
    'gender': [
        'gender', 'sex', 'பாலினம்'
    ],
}


def normalize_header_name(header: str) -> str:
    """
    Normalizes a column header string:
    - strips leading/trailing whitespace
    - converts to lowercase while preserving Unicode (e.g. Tamil, Hindi, accented characters)
    - collapses consecutive spaces, tabs, and underscores into a single space
    """
    if header is None:
        return ''
    s = unicodedata.normalize('NFKC', str(header)).strip().lower()
    s = re.sub(r'[\s_\-]+', ' ', s)
    return s.strip()


def sanitize_cell_value(val: Any) -> str:
    """
    Sanitizes imported cell values.
    Prevents formula injection attacks (=, +, -, @ prefix) if exported back to CSV/Excel.
    """
    if val is None:
        return ''
    s = unicodedata.normalize('NFKC', str(val)).strip()
    if s and s[0] in ('=', '+', '-', '@', '\t', '\r'):
        # Prepend apostrophe to neutralize spreadsheet formula execution
        return "'" + s
    return s


def clean_and_deduplicate_headers(raw_headers: list[str]) -> list[str]:
    """
    Produces clean, non-empty, and unique header names for all columns.
    Handles duplicate headers safely without silently dropping columns.
    """
    seen: dict[str, int] = {}
    cleaned: list[str] = []

    for idx, raw in enumerate(raw_headers):
        clean = str(raw).strip() if raw is not None else ''
        if not clean:
            clean = f"Column_{idx + 1}"

        lower_key = clean.lower()
        if lower_key in seen:
            seen[lower_key] += 1
            unique_name = f"{clean}_{seen[lower_key]}"
        else:
            seen[lower_key] = 1
            unique_name = clean

        cleaned.append(unique_name)

    return cleaned


def parse_csv_content(csv_text: str) -> tuple[list[str], list[dict[str, str]]]:
    """
    Parses raw CSV content string into clean headers and a list of row dictionaries.
    Each row dictionary includes a special '_row_index' field (1-indexed matching Google Sheet row).
    """
    if not csv_text or not csv_text.strip():
        return [], []

    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return [], []

    raw_headers = [str(h).strip() for h in rows[0]]
    # Strip trailing empty header columns
    while raw_headers and not raw_headers[-1]:
        raw_headers.pop()

    if not raw_headers or not any(raw_headers):
        return [], []

    headers = clean_and_deduplicate_headers(raw_headers)
    data_rows: list[dict[str, str]] = []

    for row_idx, row_vals in enumerate(rows[1:], start=2):
        # Skip completely empty rows
        if not any(str(v).strip() for v in row_vals):
            continue

        row_dict: dict[str, str] = {'_row_index': row_idx}
        for col_idx, h_name in enumerate(headers):
            val = row_vals[col_idx] if col_idx < len(row_vals) else ''
            row_dict[h_name] = sanitize_cell_value(val)

        data_rows.append(row_dict)

    return headers, data_rows


def detect_field_mapping(headers: list[str]) -> dict[str, str]:
    """
    Intelligently maps raw Google Sheet headers to CRM Lead fields.
    Resilient to naming variations, casings, and form question titles.
    """
    mapping: dict[str, str] = {}
    normalized_headers = [(h, normalize_header_name(h)) for h in headers]

    # Pass 1: Exact matches against defined patterns
    for field, patterns in HEADER_PATTERNS.items():
        if field in mapping:
            continue
        for raw_h, norm_h in normalized_headers:
            if norm_h in patterns:
                mapping[field] = raw_h
                break

    # Pass 2: Substring heuristics for key fields if not yet mapped
    for raw_h, norm_h in normalized_headers:
        if 'phone' not in mapping and any(p in norm_h for p in ['phone', 'mobile', 'contact', 'கைபேசி', 'தொலைபேசி']):
            if not any(alt in norm_h for alt in ['alt', 'alternate', 'second']):
                mapping['phone'] = raw_h
        if 'email' not in mapping and any(p in norm_h for p in ['email', 'mail', 'மின்னஞ்சல்']):
            mapping['email'] = raw_h
        if 'name' not in mapping and any(p in norm_h for p in ['name', 'student', 'candidate', 'பெயர்']):
            if not any(sub in norm_h for sub in ['first', 'last', 'user', 'channel', 'branch', 'product']):
                mapping['name'] = raw_h
        if 'product' not in mapping and any(p in norm_h for p in ['course', 'product', 'program', 'stream', 'படிப்பு']):
            mapping['product'] = raw_h
        if 'branch' not in mapping and any(p in norm_h for p in ['branch', 'center', 'city', 'location', 'campus', 'கிளை']):
            mapping['branch'] = raw_h

    return mapping
