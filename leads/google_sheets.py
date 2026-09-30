import re
import json
import hashlib
import logging
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.db.models import Count, Q
from accounts.models import User, UserRole
from branches.models import Branch
from channels.models import Channel
from products.models import Product
from activities.utils import log_activity
from .models import (
    Lead,
    LeadStatus,
    GoogleSheetConnection,
    GoogleSheetRowMapping,
    GoogleSheetSyncHistory
)
from .assignment import assign_lead_automatically, assign_new_lead
from .duplicates import find_duplicate_lead, handle_incoming_lead_duplicate, normalize_phone, normalize_email
from .google_sheets_service import (
    extract_spreadsheet_id,
    fetch_spreadsheet_metadata,
    fetch_sheet_data,
    normalize_header,
    check_google_auth_status,
    start_desktop_oauth_flow,
    disconnect_google_oauth,
    get_google_sheets_client
)

logger = logging.getLogger('crm')

# Google Form dynamic header matching definitions
HEADER_PATTERNS = {
    'name': [
        'full name', 'fullname', 'name', 'lead name', 'student name',
        'candidate name', 'applicant name', 'client name', 'person name',
        'student', 'candidate'
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
        'tel', 'telephone', 'cell', 'cell phone'
    ],
    'alternate_phone': [
        'alternate phone', 'alternate mobile', 'alt phone', 'alt mobile',
        'secondary phone', 'alternate number', 'second phone', 'alternate contact',
        'alt phone no', 'alt mobile no'
    ],
    'email': [
        'email address', 'emailaddress', 'email', 'e mail',
        'e mail address', 'mail id', 'mailid', 'email id', 'emailid', 'mail'
    ],
    'product': [
        'interested course', 'interested product', 'course', 'product',
        'program', 'interested in', 'course interested', 'course name', 'stream'
    ],
    'branch': [
        'branch', 'center', 'branch center', 'location', 'city',
        'preferred branch', 'preferred location', 'campus', 'preferred center'
    ],
    'channel': [
        'channel', 'lead source', 'source', 'platform', 'campaign', 'channel name'
    ],
    'status': [
        'status', 'lead status'
    ],
    'notes': [
        'notes', 'remarks', 'comments', 'feedback', 'message', 'query'
    ],
    'gender': [
        'gender', 'sex'
    ],
    'synced': [
        'synced', 'is synced', 'sync status'
    ],
    'timestamp': [
        'timestamp', 'time stamp', 'submission date', 'submitted at', 'date'
    ]
}


def detect_column_mapping(headers: list[str]) -> dict:
    """
    Intelligently maps raw Google Sheet headers to CRM Lead fields.
    Handles Google Form variations automatically.
    Returns: dict with field names as keys and raw sheet header strings as values.
    """
    mapping = {}
    normalized_headers = [(h, normalize_header(h)) for h in headers]

    # Pass 1: Exact matches against defined patterns
    for field, patterns in HEADER_PATTERNS.items():
        if field in mapping:
            continue
        for raw_h, norm_h in normalized_headers:
            if norm_h in patterns:
                mapping[field] = raw_h
                break

    # Pass 2: Containment heuristics for critical fields if unmapped
    for raw_h, norm_h in normalized_headers:
        if 'phone' not in mapping and any(p in norm_h for p in ['phone', 'mobile', 'contact']):
            if not any(alt in norm_h for alt in ['alt', 'alternate', 'second']):
                mapping['phone'] = raw_h
        if 'email' not in mapping and any(p in norm_h for p in ['email', 'mail']):
            mapping['email'] = raw_h
        if 'name' not in mapping and any(p in norm_h for p in ['name', 'student', 'candidate']):
            if not any(sub in norm_h for sub in ['first', 'last', 'user', 'channel', 'branch', 'product']):
                mapping['name'] = raw_h

    return mapping


def validate_spreadsheet_access(spreadsheet_url: str, worksheet_name: str = None):
    """
    Validates spreadsheet URL/ID, checks OAuth permissions, verifies worksheet exists,
    and returns available column headers.
    Returns: (is_valid, spreadsheet_id, worksheet_name, headers, sheet_title, error_message)
    """
    spreadsheet_id = extract_spreadsheet_id(spreadsheet_url)
    if not spreadsheet_id:
        return False, None, None, [], '', "Invalid Google Spreadsheet URL."

    try:
        meta = fetch_spreadsheet_metadata(spreadsheet_id)
    except FileNotFoundError as e:
        return False, spreadsheet_id, worksheet_name, [], '', str(e)
    except PermissionError as e:
        return False, spreadsheet_id, worksheet_name, [], '', str(e)
    except Exception as e:
        return False, spreadsheet_id, worksheet_name, [], '', str(e)

    sheet_title = meta.get('title', 'Google Sheet')
    available_tabs = meta.get('tabs', [])

    if not available_tabs:
        return False, spreadsheet_id, None, [], sheet_title, "The Google Sheet does not contain any worksheets/tabs."

    resolved_worksheet = worksheet_name
    if not resolved_worksheet or resolved_worksheet.strip() == '':
        form_tab = next((t for t in available_tabs if t.strip().lower() == 'form responses 1'), None)
        sheet1_tab = next((t for t in available_tabs if t.strip().lower() == 'sheet1'), None)
        resolved_worksheet = form_tab or sheet1_tab or available_tabs[0]
    else:
        # Match case-insensitively
        matched = next((t for t in available_tabs if t.strip().lower() == resolved_worksheet.strip().lower()), None)
        if matched:
            resolved_worksheet = matched
        else:
            # Fallback to Form Responses 1, Sheet1, or first tab
            form_tab = next((t for t in available_tabs if t.strip().lower() == 'form responses 1'), None)
            sheet1_tab = next((t for t in available_tabs if t.strip().lower() == 'sheet1'), None)
            resolved_worksheet = form_tab or sheet1_tab or available_tabs[0]

    try:
        headers, _ = fetch_sheet_data(spreadsheet_id, resolved_worksheet)
        if not headers:
            return False, spreadsheet_id, resolved_worksheet, [], sheet_title, "The Google Sheet does not contain any lead records or headers."
        return True, spreadsheet_id, resolved_worksheet, headers, sheet_title, None
    except Exception as e:
        return False, spreadsheet_id, resolved_worksheet, [], sheet_title, str(e)


def fetch_spreadsheet_rows(spreadsheet_id: str, worksheet_name: str):
    """
    Fetches rows using the OAuth Google Sheets API client.
    Maintained for backwards compatibility.
    """
    return fetch_sheet_data(spreadsheet_id, worksheet_name)


def compute_mapped_hash(data_dict: dict) -> str:
    """
    Computes a deterministic SHA-256 hash for mapped fields to detect row content changes.
    """
    canonical_str = json.dumps(data_dict, sort_keys=True)
    return hashlib.sha256(canonical_str.encode('utf-8')).hexdigest()


def assign_lead_to_team(lead: Lead, branch: Branch = None, method: str = 'Automatic'):
    """
    Applies role-based assignment rules:
    - Lead -> Branch -> Active Sales Head (with access to that branch) -> Active Telecaller in that branch.
    """
    if method != 'Automatic':
        return

    managers = User.objects.filter(role=UserRole.SALES_HEAD, is_active=True)
    if branch:
        branch_managers = managers.filter(branch_access__branch=branch)
        if branch_managers.exists():
            managers = branch_managers

    assigned_manager = managers.annotate(cnt=Count('manager_leads')).order_by('cnt', 'id').first()
    if assigned_manager:
        lead.assigned_manager = assigned_manager

        # Find telecallers in this branch
        telecallers = User.objects.filter(
            role=UserRole.TELECALLER,
            is_active=True
        )
        if branch:
            branch_tc = telecallers.filter(branch=branch)
            if branch_tc.exists():
                telecallers = branch_tc

        assigned_telecaller = telecallers.annotate(cnt=Count('telecaller_leads')).order_by('cnt', 'id').first()
        if assigned_telecaller:
            lead.assigned_telecaller = assigned_telecaller


def sync_google_sheet(connection: GoogleSheetConnection, triggered_by=None):
    """
    Full live synchronization engine for a GoogleSheetConnection:
    1. Reads rows from Google Sheet via OAuth API client in a single bulk request.
    2. Builds/applies column mapping (dynamically detecting Google Form headers if not mapped).
    3. Detects new rows -> creates Lead & RowMapping.
    4. Detects updated rows -> updates existing Lead (One-Way Sheet -> CRM).
    5. Detects deleted rows -> marks RowMapping 'Removed from source' (preserves Lead).
    6. Preserves unmapped fields (e.g. Gender, College, etc.) in Lead notes.
    7. Creates Activities & SyncHistory audit record.
    """
    logger.info(f"Google Sheets synchronization started for '{connection.name}' (ID: {connection.spreadsheet_id}).")

    if not connection.is_active:
        logger.info(f"Synchronization skipped: Connection '{connection.name}' is paused.")
        return {
            'status': 'Paused',
            'rows_checked': 0,
            'new_leads': 0,
            'updated_leads': 0,
            'skipped': 0,
            'failed': 0,
            'errors': ["Connection is paused."]
        }

    try:
        headers, rows = fetch_sheet_data(connection.spreadsheet_id, connection.worksheet_name)
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Google Sheets synchronization failed for '{connection.name}': {error_msg}")
        GoogleSheetSyncHistory.objects.create(
            connection=connection,
            rows_checked=0,
            new_leads=0,
            updated_leads=0,
            skipped=0,
            failed=0,
            status='Failed',
            error_summary=f"Spreadsheet read failure: {error_msg}"
        )
        connection.last_sync_time = timezone.now()
        connection.last_sync_status = 'Failed'
        connection.save(update_fields=['last_sync_time', 'last_sync_status'])
        return {
            'status': 'Failed',
            'rows_checked': 0,
            'new_leads': 0,
            'updated_leads': 0,
            'skipped': 0,
            'failed': 1,
            'errors': [error_msg]
        }

    # If field_mapping is empty, auto-detect from headers
    mapping = connection.field_mapping or {}
    detected = detect_column_mapping(headers)
    for k, v in detected.items():
        if k not in mapping or not mapping[k]:
            mapping[k] = v

    total_rows = len(rows)
    new_leads = 0
    updated_leads = 0
    skipped = 0
    failed = 0
    assigned_leads = 0
    errors = []
    seen_row_identifiers = set()

    default_channel = connection.channel
    if not default_channel:
        default_channel = Channel.objects.filter(name__iexact='Google Sheets').first() or Channel.objects.first()

    name_col = mapping.get('name')
    first_name_col = mapping.get('first_name')
    last_name_col = mapping.get('last_name')
    phone_col = mapping.get('phone')
    alt_phone_col = mapping.get('alternate_phone')
    email_col = mapping.get('email')
    product_col = mapping.get('product') or mapping.get('course')
    branch_col = mapping.get('branch') or mapping.get('center') or mapping.get('city')
    channel_col = mapping.get('channel') or mapping.get('source')
    status_col = mapping.get('status')
    notes_col = mapping.get('notes') or mapping.get('remarks')
    synced_col = mapping.get('synced')
    gender_col = mapping.get('gender')

    for loop_idx, r in enumerate(rows, start=2):
        if isinstance(r, (list, tuple)):
            r_dict = {'_row_index': loop_idx}
            for col_idx, h in enumerate(headers):
                if col_idx < len(r):
                    r_dict[h] = r[col_idx]
            r = r_dict

        row_idx = r.get('_row_index') or loop_idx
        row_id = f"{connection.spreadsheet_id}_{connection.worksheet_name}_row_{row_idx}"
        seen_row_identifiers.add(row_id)

        # Extract values
        name_val = (r.get(name_col) if name_col else '') or r.get('Name') or r.get('Lead Name') or r.get('Full Name') or ''
        if not name_val and (first_name_col or last_name_col):
            fn = str(r.get(first_name_col, '') if first_name_col else '').strip()
            ln = str(r.get(last_name_col, '') if last_name_col else '').strip()
            name_val = f"{fn} {ln}".strip()

        phone_val = (r.get(phone_col) if phone_col else '') or r.get('Phone') or r.get('Mobile') or r.get('Phone Number') or ''
        alt_phone_val = (r.get(alt_phone_col) if alt_phone_col else '') or r.get('Alternate Phone') or r.get('Alt Phone') or ''
        email_val = (r.get(email_col) if email_col else '') or r.get('Email') or ''
        product_val = (r.get(product_col) if product_col else '') or r.get('Product') or r.get('Course') or ''
        branch_val = (r.get(branch_col) if branch_col else '') or r.get('Branch') or ''
        channel_val = (r.get(channel_col) if channel_col else '') or r.get('Channel') or ''
        status_val = (r.get(status_col) if status_col else '') or r.get('Status') or ''
        notes_val = (r.get(notes_col) if notes_col else '') or r.get('Notes') or r.get('Remarks') or ''
        gender_val = (r.get(gender_col) if gender_col else '') or r.get('Gender') or ''

        name_val = str(name_val).strip()
        phone_val = str(phone_val).strip()
        alt_phone_val = str(alt_phone_val).strip()
        email_val = str(email_val).strip()
        gender_val = str(gender_val).strip()

        # Compile unmapped columns from Google Form responses into extra info so no data is lost
        extra_fields = []
        mapped_headers = set(filter(None, [
            name_col, first_name_col, last_name_col, phone_col, alt_phone_col,
            email_col, product_col, branch_col, channel_col, status_col, notes_col, synced_col
        ]))
        for h_key, h_val in r.items():
            if h_key.startswith('_') or h_key in mapped_headers:
                continue
            if h_val and str(h_val).strip():
                extra_fields.append(f"{h_key}: {str(h_val).strip()}")

        if gender_val and 'gender' not in [normalize_header(x.split(':')[0]) for x in extra_fields]:
            extra_fields.insert(0, f"Gender: {gender_val}")

        if extra_fields:
            extra_notes_text = " | ".join(extra_fields)
            if notes_val:
                notes_val = f"{notes_val} | [Form Data]: {extra_notes_text}"
            else:
                notes_val = f"[Form Data]: {extra_notes_text}"

        # Row validation: Name and at least Phone or Email are required
        if not name_val or (not phone_val and not email_val):
            failed += 1
            if not name_val:
                errors.append(f"Row {row_idx}: Name is missing.")
            else:
                errors.append(f"Row {row_idx}: Both Phone and Email are missing.")
            continue

        # If phone is missing but email exists, set a placeholder so model requirement is satisfied
        if not phone_val and email_val:
            phone_val = f"NoPhone-{email_val[:12]}"

        # Normalize phone and email
        norm_phone = normalize_phone(phone_val)
        if norm_phone and not norm_phone.startswith('NoPhone-'):
            phone_val = norm_phone
        email_val = normalize_email(email_val)
        norm_alt = normalize_phone(alt_phone_val)
        if norm_alt and not norm_alt.startswith('NoPhone-'):
            alt_phone_val = norm_alt

        # Truncate phone to max 20 chars
        if len(phone_val) > 20:
            phone_val = phone_val[:20]

        # Resolve Product & Branch
        product_obj = None
        if product_val:
            product_obj = Product.objects.filter(name__iexact=product_val).first()

        branch_obj = connection.branch
        if branch_val:
            b_found = Branch.objects.filter(Q(name__iexact=branch_val) | Q(name__icontains=branch_val)).first()
            if b_found:
                branch_obj = b_found
        if not branch_obj:
            branch_obj = Branch.objects.filter(status='Active').first() or Branch.objects.first()

        # Resolve Channel
        channel_obj = default_channel
        if channel_val:
            c_found = Channel.objects.filter(Q(name__iexact=channel_val) | Q(name__icontains=channel_val)).first()
            if c_found:
                channel_obj = c_found

        # Resolve Status
        resolved_status = LeadStatus.NEW
        for code, label in LeadStatus.choices:
            if status_val.lower() == code.lower() or status_val.lower() == label.lower():
                resolved_status = code
                break

        mapped_dict = {
            'name': name_val,
            'phone': phone_val,
            'email': email_val,
            'product': product_obj.id if product_obj else None,
            'branch': branch_obj.id if branch_obj else None,
            'status': resolved_status,
            'notes': notes_val
        }
        current_hash = compute_mapped_hash(mapped_dict)

        # Check existing row mapping for this connection and row_id
        row_mapping = GoogleSheetRowMapping.objects.filter(
            connection=connection,
            row_identifier=row_id
        ).select_related('lead').first()

        if row_mapping:
            lead = row_mapping.lead
            if row_mapping.row_data_hash != current_hash:
                changes = []
                if lead.name != name_val:
                    changes.append(f"Name: '{lead.name}' -> '{name_val}'")
                    lead.name = name_val
                if lead.phone != phone_val:
                    changes.append(f"Phone: '{lead.phone}' -> '{phone_val}'")
                    lead.phone = phone_val
                if email_val and lead.email != email_val:
                    changes.append(f"Email: '{lead.email}' -> '{email_val}'")
                    lead.email = email_val
                if product_obj and lead.product != product_obj:
                    changes.append(f"Product: '{lead.product}' -> '{product_obj.name}'")
                    lead.product = product_obj
                if branch_obj and lead.branch != branch_obj:
                    changes.append(f"Branch: '{lead.branch}' -> '{branch_obj.name}'")
                    lead.branch = branch_obj
                # Never overwrite CRM-managed telecaller assignment, follow-ups, or status
                if notes_val and notes_val not in lead.notes:
                    lead.notes = f"{lead.notes}\n[Sheet Update]: {notes_val}".strip()
                    changes.append("Notes updated")

                lead.save()
                row_mapping.row_data_hash = current_hash
                row_mapping.row_index = row_idx
                row_mapping.source_status = 'Active'
                row_mapping.save()

                if changes:
                    log_activity(
                        user=triggered_by or connection.created_by,
                        action="Lead Updated from Google Sheet",
                        description=f"Row {row_idx} of '{connection.name}' updated lead '{lead.name}': {', '.join(changes)}.",
                        object_type="Lead",
                        object_id=lead.pk
                    )
                updated_leads += 1
            else:
                if row_mapping.source_status != 'Active' or row_mapping.row_index != row_idx:
                    row_mapping.source_status = 'Active'
                    row_mapping.row_index = row_idx
                    row_mapping.save(update_fields=['source_status', 'row_index', 'updated_at'])
                skipped += 1

        else:
            # Check for existing lead across CRM by phone, email, or name
            norm_phone = normalize_phone(phone_val)
            norm_email = normalize_email(email_val)
            existing_lead = find_duplicate_lead(phone=norm_phone, email=norm_email, name=name_val)

            if existing_lead:
                # Associate additional source row with existing lead (preserve CRM fields & assignments)
                if branch_obj and existing_lead.branch and branch_obj != existing_lead.branch:
                    existing_lead.secondary_branches.add(branch_obj)

                if notes_val and notes_val not in existing_lead.notes:
                    existing_lead.notes = f"{existing_lead.notes}\n[Additional Source {connection.name}]: {notes_val}".strip()
                    existing_lead.save(update_fields=['notes', 'updated_at'])

                GoogleSheetRowMapping.objects.create(
                    connection=connection,
                    lead=existing_lead,
                    row_identifier=row_id,
                    row_index=row_idx,
                    row_data_hash=current_hash,
                    source_status='Active'
                )
                updated_leads += 1

            else:
                # Create brand new Lead
                lead_source = connection.name or 'Google Sheets'
                new_lead_obj = Lead(
                    name=name_val,
                    phone=phone_val,
                    email=email_val,
                    alternate_phone=alt_phone_val,
                    channel=channel_obj,
                    source=lead_source,
                    is_offline=True,
                    product=product_obj,
                    branch=branch_obj,
                    status=resolved_status,
                    notes=notes_val
                )
                new_lead_obj.save()

                if connection.assignment_method == 'Automatic':
                    assigned = assign_new_lead(
                        new_lead_obj,
                        branch=branch_obj,
                        source=f"Google Sheet '{connection.name}'",
                        triggered_by=triggered_by or connection.created_by
                    )
                    if assigned:
                        assigned_leads += 1

                GoogleSheetRowMapping.objects.create(
                    connection=connection,
                    lead=new_lead_obj,
                    row_identifier=row_id,
                    row_index=row_idx,
                    row_data_hash=current_hash,
                    source_status='Active'
                )

                log_activity(
                    user=triggered_by or connection.created_by,
                    action="Lead Created from Google Sheet",
                    description=f"Created lead '{new_lead_obj.name}' ({new_lead_obj.phone}) from row {row_idx} of '{connection.name}'.",
                    object_type="Lead",
                    object_id=new_lead_obj.pk
                )
                new_leads += 1

    # Check for deleted rows from sheet (RowMappings in DB not seen in current sheet)
    deleted_mappings = GoogleSheetRowMapping.objects.filter(
        connection=connection,
        source_status='Active'
    ).exclude(row_identifier__in=seen_row_identifiers)

    if deleted_mappings.exists():
        deleted_count = deleted_mappings.count()
        deleted_mappings.update(source_status='Removed from source', updated_at=timezone.now())
        errors.append(f"{deleted_count} lead(s) marked 'Removed from source' (preserved in CRM).")

    # Finalize Sync History
    sync_status = 'Completed'
    if failed > 0 and (new_leads > 0 or updated_leads > 0 or skipped > 0):
        sync_status = 'Completed with Errors'
    elif failed > 0 and new_leads == 0 and updated_leads == 0:
        sync_status = 'Failed'

    history = GoogleSheetSyncHistory.objects.create(
        connection=connection,
        rows_checked=total_rows,
        new_leads=new_leads,
        updated_leads=updated_leads,
        skipped=skipped,
        failed=failed,
        assigned_leads=assigned_leads,
        status=sync_status,
        error_summary="\n".join(errors[:50])
    )

    connection.last_sync_time = timezone.now()
    connection.last_sync_status = sync_status
    connection.last_sync_error = "\n".join(errors[:5]) if errors else ""
    connection.total_leads_imported = connection.row_mappings.count()
    connection.save(update_fields=['last_sync_time', 'last_sync_status', 'last_sync_error', 'total_leads_imported', 'updated_at'])

    logger.info(
        f"Google Sheets synchronization completed for '{connection.name}': "
        f"Status: {sync_status} | Rows: {total_rows} | New: {new_leads} | Updated: {updated_leads} | Skipped: {skipped} | Failed: {failed} | Assigned: {assigned_leads}"
    )

    return {
        'status': sync_status,
        'rows_checked': total_rows,
        'new_leads': new_leads,
        'updated_leads': updated_leads,
        'skipped': skipped,
        'failed': failed,
        'assigned_leads': assigned_leads,
        'errors': errors
    }


def sync_all_active_spreadsheets(triggered_by=None) -> list[dict]:
    """
    Synchronizes all active GoogleSheetConnection records in the CRM.
    Used by background workers, schedulers, and admin batch actions.
    """
    results = []
    active_conns = GoogleSheetConnection.objects.filter(is_active=True).order_by('id')
    for conn in active_conns:
        try:
            res = sync_google_sheet(conn, triggered_by=triggered_by)
            results.append({'connection_id': conn.id, 'name': conn.name, 'result': res})
        except Exception as e:
            logger.error(f"Error syncing spreadsheet '{conn.name}': {e}")
            results.append({'connection_id': conn.id, 'name': conn.name, 'error': str(e)})
    return results


def sync_default_environment_sheet(triggered_by=None) -> tuple[GoogleSheetConnection | None, dict]:
    """
    Synchronizes the Google Sheet configured in environment variables (GOOGLE_SHEET_ID and GOOGLE_SHEET_TAB).
    Creates or updates the GoogleSheetConnection record automatically.
    Returns: (connection, result_dict)
    """
    sheet_id = getattr(settings, 'GOOGLE_SHEET_ID', '') or os.getenv('GOOGLE_SHEET_ID', '')
    sheet_tab = getattr(settings, 'GOOGLE_SHEET_TAB', 'Form Responses 1') or os.getenv('GOOGLE_SHEET_TAB', 'Form Responses 1')

    if not sheet_id:
        return None, {
            'status': 'Failed',
            'rows_checked': 0,
            'new_leads': 0,
            'updated_leads': 0,
            'skipped': 0,
            'failed': 1,
            'errors': ["GOOGLE_SHEET_ID is not configured in environment or settings."]
        }

    conn, _ = GoogleSheetConnection.objects.get_or_create(
        spreadsheet_id=sheet_id,
        worksheet_name=sheet_tab,
        defaults={
            'name': f"Form Responses ({sheet_id[:8]})",
            'spreadsheet_url': f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit",
            'assignment_method': 'Automatic',
            'created_by': triggered_by,
            'last_sync_status': 'Connected'
        }
    )

    result = sync_google_sheet(conn, triggered_by=triggered_by)
    return conn, result
