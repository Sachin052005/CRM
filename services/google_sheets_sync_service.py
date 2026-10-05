import hashlib
import json
import logging
import re
from typing import Any
from django.db import transaction
from django.utils import timezone

from .google_sheets_service import fetch_sheet
from .google_sheets_parser import detect_field_mapping, normalize_header_name
from leads.models import (
    Lead,
    LeadStatus,
    GoogleSheetConnection,
    GoogleSheetRowMapping,
    GoogleSheetSyncHistory,
)
from leads.assignment import assign_new_lead
from leads.duplicates import (
    find_duplicate_lead,
    normalize_phone,
    normalize_email,
)
from channels.models import Channel
from branches.models import Branch
from products.models import Product

logger = logging.getLogger('crm')


def compute_row_hash(data_dict: dict) -> str:
    """Computes deterministic SHA-256 hash for mapped fields to detect cell changes."""
    canonical = json.dumps(data_dict, sort_keys=True)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def get_field_value(row_dict: dict, mapped_col: str, *candidate_names: str) -> str:
    """
    Retrieves cell value safely with exact match, fallback candidate names,
    and normalized key lookup.
    """
    if mapped_col and mapped_col in row_dict and row_dict[mapped_col] is not None:
        v = str(row_dict[mapped_col]).strip()
        if v:
            return v

    for cand in candidate_names:
        if cand and cand in row_dict and row_dict[cand] is not None:
            v = str(row_dict[cand]).strip()
            if v:
                return v

    # Normalized lookup
    norm_map = {normalize_header_name(k): v for k, v in row_dict.items() if k is not None}
    search_keys = [mapped_col] + list(candidate_names)
    for sk in search_keys:
        if sk:
            nsk = normalize_header_name(str(sk))
            if nsk in norm_map and norm_map[nsk] is not None:
                v = str(norm_map[nsk]).strip()
                if v:
                    return v

    return ''


def sync_connection(
    connection: GoogleSheetConnection,
    triggered_by=None,
    headers: list[str] = None,
    rows: list[dict] = None
) -> dict:
    """
    Synchronizes a connected Google Sheet directly into MySQL using Django ORM.
    Zero authentication - connects strictly to publicly accessible Google Sheets.
    
    Workflow:
    1. Fetches latest live spreadsheet rows from public Google export endpoint.
    2. Dynamically reconciles column mapping against current sheet headers.
    3. Processes rows inside an atomic transaction:
       - Creates new Leads and RowMappings
       - Updates existing Leads if sheet content changed
       - Tracks unchanged rows
       - Flags removed rows without deleting CRM history
    4. Audits sync in GoogleSheetSyncHistory and updates GoogleSheetConnection.
    5. Returns structured synchronization summary.
    """
    start_time = timezone.now()
    logger.info(
        f"Synchronizing Google Sheet '{connection.name}' (ID: {connection.spreadsheet_id}, Tab: {connection.worksheet_name})."
    )

    if not connection.is_active:
        return {
            'success': True,
            'status': 'Paused',
            'total_rows': 0,
            'created': 0,
            'updated': 0,
            'unchanged': 0,
            'skipped': 0,
            'errors': 0,
            'last_synced_at': start_time.isoformat(),
            'message': 'Connection is currently paused.'
        }

    # Step 1: Fetch latest sheet data if not pre-supplied
    if headers is None and rows is None:
        try:
            gid_val = getattr(connection, 'gid', None) or '0'
            headers, rows = fetch_sheet(
                spreadsheet_id=connection.spreadsheet_id,
                gid=gid_val,
                sheet_name=connection.worksheet_name
            )
        except PermissionError as e:
            err_msg = str(e)
            logger.warning(f"Public access denied for sheet '{connection.name}': {err_msg}")
            _record_failed_sync(connection, err_msg)
            return {
                'success': False,
                'status': 'Failed',
                'total_rows': 0,
                'created': 0,
                'updated': 0,
                'unchanged': 0,
                'skipped': 0,
                'errors': 1,
                'last_synced_at': timezone.now().isoformat(),
                'error_messages': [err_msg]
            }
        except Exception as e:
            err_msg = f"Network or fetch error: {e}"
            logger.error(f"Error fetching sheet '{connection.name}': {err_msg}")
            _record_failed_sync(connection, err_msg)
            return {
                'success': False,
                'status': 'Failed',
                'total_rows': 0,
                'created': 0,
                'updated': 0,
                'unchanged': 0,
                'skipped': 0,
                'errors': 1,
                'last_synced_at': timezone.now().isoformat(),
                'error_messages': [err_msg]
            }

    if not headers or not any(headers):
        err_msg = (
            f"The Google Sheet '{connection.name}' returned no columns or headers. "
            "Please ensure the sheet contains column headers and is shared publicly."
        )
        logger.warning(err_msg)
        _record_failed_sync(connection, err_msg)
        return {
            'success': False,
            'status': 'Failed',
            'total_rows': 0,
            'created': 0,
            'updated': 0,
            'unchanged': 0,
            'skipped': 0,
            'errors': 1,
            'last_synced_at': timezone.now().isoformat(),
            'error_messages': [err_msg]
        }

    # Step 2: Reconcile column mappings dynamically
    mapping = dict(connection.field_mapping or {})
    detected = detect_field_mapping(headers)
    header_lookup = {normalize_header_name(h): h for h in headers}

    reconciled_mapping: dict[str, str] = {}
    for k, v in mapping.items():
        if k in ('headers', 'rows'):
            continue
        if v and isinstance(v, str):
            norm_v = normalize_header_name(v)
            if v in headers:
                reconciled_mapping[k] = v
            elif norm_v in header_lookup:
                reconciled_mapping[k] = header_lookup[norm_v]
            elif k in detected and detected[k] in headers:
                reconciled_mapping[k] = detected[k]
        elif k in detected:
            reconciled_mapping[k] = detected[k]

    for k, v in detected.items():
        if k not in reconciled_mapping or not reconciled_mapping[k]:
            reconciled_mapping[k] = v

    total_rows = len(rows)
    created_count = 0
    updated_count = 0
    unchanged_count = 0
    skipped_count = 0
    errors_list: list[str] = []
    seen_row_identifiers: set[str] = set()

    default_channel = connection.channel
    if not default_channel:
        default_channel = Channel.objects.filter(name__iexact='Google Sheets').first() or Channel.objects.first()

    name_col = reconciled_mapping.get('name')
    first_name_col = reconciled_mapping.get('first_name')
    last_name_col = reconciled_mapping.get('last_name')
    phone_col = reconciled_mapping.get('phone')
    alt_phone_col = reconciled_mapping.get('alternate_phone')
    email_col = reconciled_mapping.get('email')
    product_col = reconciled_mapping.get('product')
    branch_col = reconciled_mapping.get('branch')
    channel_col = reconciled_mapping.get('channel')
    status_col = reconciled_mapping.get('status')
    notes_col = reconciled_mapping.get('notes')
    gender_col = reconciled_mapping.get('gender')

    # Step 3: Process rows inside an atomic transaction
    with transaction.atomic():
        for loop_idx, r in enumerate(rows, start=2):
            if isinstance(r, (list, tuple)):
                r_dict = {'_row_index': loop_idx}
                for c_idx, h in enumerate(headers):
                    if c_idx < len(r):
                        r_dict[h] = str(r[c_idx]).strip()
                r = r_dict

            row_idx = r.get('_row_index') or loop_idx
            gid_part = getattr(connection, 'gid', None) or '0'
            row_id = f"{connection.spreadsheet_id}_{gid_part}_{connection.worksheet_name}_row_{row_idx}"
            seen_row_identifiers.add(row_id)

            # Extract cell values with multi-candidate fallbacks
            name_val = get_field_value(r, name_col, 'Full name', 'Full Name', 'Name', 'Lead Name', 'Student Name', 'Candidate Name', 'பெயர்')
            if not name_val and (first_name_col or last_name_col):
                fn = get_field_value(r, first_name_col, 'First Name', 'FirstName', 'First')
                ln = get_field_value(r, last_name_col, 'Last Name', 'LastName', 'Last')
                name_val = f"{fn} {ln}".strip()

            phone_val = get_field_value(r, phone_col, 'Phone number', 'Phone Number', 'Mobile Number', 'Mobile number', 'Phone', 'Mobile', 'Contact', 'கைபேசி', 'தொலைபேசி')
            alt_phone_val = get_field_value(r, alt_phone_col, 'Alternate Phone', 'Alt Phone', 'Alternate Mobile', 'Secondary Phone')
            email_val = get_field_value(r, email_col, 'Email', 'Email Address', 'Mail Id', 'Mail', 'மின்னஞ்சல்')
            product_val = get_field_value(r, product_col, 'Product', 'Course', 'Wat course are you looking for ?', 'What course are you looking for?', 'Courses', 'Interested Course', 'படிப்பு')
            branch_val = get_field_value(r, branch_col, 'Branch', 'City', 'Preferred Branch', 'Location', 'Center', 'கிளை')
            channel_val = get_field_value(r, channel_col, 'Channel', 'Lead Source', 'Source', 'Platform')
            status_val = get_field_value(r, status_col, 'Status', 'Lead Status')
            notes_val = get_field_value(r, notes_col, 'Notes', 'Remarks', 'Comments / Questions', 'What you looking for?', 'What is your current status?', 'Comments', 'Feedback', 'குறிப்புகள்')
            gender_val = get_field_value(r, gender_col, 'Gender', 'Sex', 'பாலினம்')

            # Empty row detection
            if not name_val and not phone_val and not email_val:
                skipped_count += 1
                continue

            # Fallback name for WhatsApp / online inquiries with mobile/email only
            if not name_val:
                if phone_val:
                    digits = re.sub(r'[^0-9]', '', str(phone_val))
                    disp_digits = digits[-10:] if len(digits) >= 10 else digits
                    name_val = f"{connection.name} Lead ({disp_digits})"
                elif email_val:
                    name_val = f"{connection.name} Lead ({email_val.split('@')[0]})"
                else:
                    name_val = f"{connection.name} Lead"

            # Validate contactability
            if not phone_val and not email_val:
                errors_list.append(f"Row {row_idx}: Both Phone and Email are missing.")
                skipped_count += 1
                continue

            # Normalization
            norm_phone = normalize_phone(phone_val)
            if norm_phone:
                phone_val = norm_phone
            if len(phone_val) > 20:
                phone_val = phone_val[:20]

            email_val = normalize_email(email_val)
            norm_alt = normalize_phone(alt_phone_val)
            if norm_alt:
                alt_phone_val = norm_alt

            # Resolve Foreign Keys: Branch, Product, Channel
            branch_obj = connection.branch
            if branch_val:
                b_found = Branch.objects.filter(name__icontains=branch_val).first()
                if b_found:
                    branch_obj = b_found
            if not branch_obj:
                branch_obj = Branch.objects.filter(status='Active').first() or Branch.objects.first()

            product_obj = None
            if product_val:
                product_obj = Product.objects.filter(name__icontains=product_val).first()

            channel_obj = default_channel
            if channel_val:
                c_found = Channel.objects.filter(name__icontains=channel_val).first()
                if c_found:
                    channel_obj = c_found

            resolved_status = LeadStatus.NEW
            for code, label in LeadStatus.choices:
                if status_val.lower() == code.lower() or status_val.lower() == label.lower():
                    resolved_status = code
                    break

            # Preserve unmapped form fields in notes
            extra_fields = []
            mapped_cols = set(filter(None, [
                name_col, first_name_col, last_name_col, phone_col, alt_phone_col,
                email_col, product_col, branch_col, channel_col, status_col, notes_col, gender_col
            ]))
            for hk, hv in r.items():
                if hk.startswith('_') or hk in mapped_cols:
                    continue
                if hv and str(hv).strip():
                    extra_fields.append(f"{hk}: {str(hv).strip()}")

            if gender_val and 'gender' not in [normalize_header_name(x.split(':')[0]) for x in extra_fields]:
                extra_fields.insert(0, f"Gender: {gender_val}")

            if extra_fields:
                extra_str = " | ".join(extra_fields)
                notes_val = f"{notes_val} | [Form Data]: {extra_str}".strip(' |')

            # Build hash for change detection
            mapped_snapshot = {
                'name': name_val,
                'phone': phone_val,
                'email': email_val,
                'product': product_obj.id if product_obj else None,
                'branch': branch_obj.id if branch_obj else None,
                'status': resolved_status,
                'notes': notes_val
            }
            row_hash = compute_row_hash(mapped_snapshot)

            # Check existing RowMapping (idempotent upsert via external row identifier)
            row_mapping = GoogleSheetRowMapping.objects.filter(
                connection=connection,
                row_identifier=row_id
            ).select_related('lead').first()

            if row_mapping:
                lead = row_mapping.lead
                if row_mapping.row_data_hash != row_hash:
                    # Update changed lead fields (One-way Sheet -> CRM)
                    lead.name = name_val
                    lead.phone = phone_val
                    if email_val:
                        lead.email = email_val
                    if product_obj:
                        lead.product = product_obj
                    if branch_obj:
                        lead.branch = branch_obj
                    if notes_val and notes_val not in (lead.notes or ''):
                        lead.notes = f"{lead.notes or ''}\n[Sheet Update]: {notes_val}".strip()
                    lead.save()

                    row_mapping.row_data_hash = row_hash
                    row_mapping.row_index = row_idx
                    row_mapping.source_status = 'Active'
                    row_mapping.save()
                    updated_count += 1
                else:
                    # Content unchanged
                    if row_mapping.source_status != 'Active' or row_mapping.row_index != row_idx:
                        row_mapping.source_status = 'Active'
                        row_mapping.row_index = row_idx
                        row_mapping.save(update_fields=['source_status', 'row_index', 'updated_at'])
                    unchanged_count += 1

            else:
                # Row not yet mapped: check for existing duplicate Lead across CRM
                existing_lead = find_duplicate_lead(phone=phone_val, email=email_val, name=name_val)

                if existing_lead:
                    if branch_obj and existing_lead.branch and branch_obj != existing_lead.branch:
                        existing_lead.secondary_branches.add(branch_obj)

                    if notes_val and notes_val not in (existing_lead.notes or ''):
                        existing_lead.notes = f"{existing_lead.notes or ''}\n[Additional Source {connection.name}]: {notes_val}".strip()
                        existing_lead.save(update_fields=['notes', 'updated_at'])

                    GoogleSheetRowMapping.objects.create(
                        connection=connection,
                        lead=existing_lead,
                        row_identifier=row_id,
                        row_index=row_idx,
                        row_data_hash=row_hash,
                        source_status='Active'
                    )
                    updated_count += 1

                else:
                    # Insert brand new Lead into MySQL
                    new_lead = Lead.objects.create(
                        name=name_val,
                        phone=phone_val,
                        email=email_val,
                        alternate_phone=alt_phone_val,
                        channel=channel_obj,
                        source=connection.name,
                        is_offline=True,
                        product=product_obj,
                        branch=branch_obj,
                        status=resolved_status,
                        notes=notes_val
                    )

                    if connection.assignment_method == 'Automatic':
                        assign_new_lead(
                            new_lead,
                            branch=branch_obj,
                            source=f"Google Sheet '{connection.name}'",
                            triggered_by=triggered_by or connection.created_by
                        )

                    GoogleSheetRowMapping.objects.create(
                        connection=connection,
                        lead=new_lead,
                        row_identifier=row_id,
                        row_index=row_idx,
                        row_data_hash=row_hash,
                        source_status='Active'
                    )
                    created_count += 1

        # Check for deleted rows from sheet (preserve CRM lead, update source status)
        if total_rows > 0:
            removed_mappings = GoogleSheetRowMapping.objects.filter(
                connection=connection,
                source_status='Active'
            ).exclude(row_identifier__in=seen_row_identifiers)
            if removed_mappings.exists():
                removed_mappings.update(source_status='Removed from source', updated_at=timezone.now())

    # Step 4: Audit sync history & update connection state
    sync_status = 'Success'
    if errors_list and (created_count > 0 or updated_count > 0 or unchanged_count > 0):
        sync_status = 'Completed with Errors'
    elif errors_list and created_count == 0 and updated_count == 0 and unchanged_count == 0:
        sync_status = 'Failed'

    GoogleSheetSyncHistory.objects.create(
        connection=connection,
        rows_checked=total_rows,
        new_leads=created_count,
        updated_leads=updated_count,
        skipped=skipped_count + unchanged_count,
        failed=len(errors_list),
        assigned_leads=created_count,
        status=sync_status,
        error_summary="\n".join(errors_list[:50])
    )

    reconciled_mapping['headers'] = headers
    reconciled_mapping['rows'] = rows
    connection.field_mapping = reconciled_mapping
    connection.last_sync_time = timezone.now()
    connection.last_sync_status = sync_status
    connection.last_sync_error = "\n".join(errors_list[:5]) if errors_list else ""
    connection.total_leads_imported = connection.row_mappings.count()
    connection.connection_status = 'ACTIVE'
    connection.save(update_fields=[
        'field_mapping', 'last_sync_time', 'last_sync_status',
        'last_sync_error', 'total_leads_imported', 'connection_status', 'updated_at'
    ])

    logger.info(
        f"Sync completed for '{connection.name}': Status={sync_status} | Rows={total_rows} | "
        f"Created={created_count} | Updated={updated_count} | Unchanged={unchanged_count} | Skipped={skipped_count} | Errors={len(errors_list)}"
    )

    return {
        'success': sync_status in ('Success', 'Completed with Errors'),
        'status': sync_status,
        'total_rows': total_rows,
        'rows_checked': total_rows,
        'created': created_count,
        'new_leads': created_count,
        'updated': updated_count,
        'updated_leads': updated_count,
        'unchanged': unchanged_count,
        'skipped': skipped_count,
        'errors': len(errors_list),
        'failed': len(errors_list),
        'assigned_leads': created_count,
        'last_synced_at': connection.last_sync_time.isoformat(),
        'error_messages': errors_list,
        'errors_list': errors_list,
        'message': f"Sync complete! {total_rows} rows checked: {created_count} created, {updated_count} updated, {unchanged_count} unchanged, {skipped_count} skipped."
    }


def _record_failed_sync(connection: GoogleSheetConnection, err_msg: str):
    """Safely updates connection and writes audit record on connection/fetch error."""
    now = timezone.now()
    GoogleSheetSyncHistory.objects.create(
        connection=connection,
        rows_checked=0,
        new_leads=0,
        updated_leads=0,
        skipped=0,
        failed=1,
        status='Failed',
        error_summary=err_msg
    )
    connection.last_sync_time = now
    connection.last_sync_status = 'Failed'
    connection.last_sync_error = err_msg
    connection.connection_status = 'ACTIVE'  # Remains ACTIVE for automatic retry
    connection.save(update_fields=['last_sync_time', 'last_sync_status', 'last_sync_error', 'connection_status', 'updated_at'])
