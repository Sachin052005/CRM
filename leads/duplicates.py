import re
from datetime import timedelta
from collections import defaultdict
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from .models import Lead
from branches.models import Branch
from activities.utils import log_activity


def normalize_phone(phone):
    """
    Normalizes a phone number by stripping country codes (+91), spaces, hyphens,
    parentheses, leading zeros, and extracting the clean 10-digit number.
    """
    if not phone:
        return ''
    raw = str(phone).strip()
    if raw.startswith('NoPhone-'):
        return raw

    # Remove all non-digits
    digits = re.sub(r'\D', '', raw)

    # If starts with 91 and has 12 digits, strip country code
    if len(digits) == 12 and digits.startswith('91'):
        digits = digits[2:]
    # If 11 digits and starts with 0, strip leading 0
    elif len(digits) == 11 and digits.startswith('0'):
        digits = digits[1:]

    return digits


def normalize_email(email):
    """
    Normalizes an email address to lowercase stripped string.
    """
    if not email:
        return ''
    return str(email).strip().lower()


def find_duplicate_lead(phone=None, email=None, name=None, exclude_id=None):
    """
    Checks whether a matching lead already exists in the CRM.
    Matches primarily by normalized phone number, then by email address,
    and optionally checks matching name + normalized phone.
    """
    clean_phone = normalize_phone(phone)
    clean_email = normalize_email(email)

    qs = Lead.objects.all()
    if exclude_id:
        qs = qs.exclude(id=exclude_id)

    # 1. Match by phone
    if clean_phone and not clean_phone.startswith('NoPhone-'):
        # Check exact or endswith 10 digits
        if len(clean_phone) >= 10:
            target_10 = clean_phone[-10:]
            lead_by_phone = qs.filter(
                Q(phone=clean_phone) | Q(phone__endswith=target_10) | Q(alternate_phone__endswith=target_10)
            ).first()
            if lead_by_phone:
                return lead_by_phone
        else:
            lead_by_phone = qs.filter(phone=clean_phone).first()
            if lead_by_phone:
                return lead_by_phone

    # 2. Match by email
    if clean_email:
        lead_by_email = qs.filter(email__iexact=clean_email).first()
        if lead_by_email:
            return lead_by_email

    return None


def handle_incoming_lead_duplicate(existing_lead, incoming_data, branch=None, user=None, source_label='Import'):
    """
    Updates and retains the existing Lead record instead of creating a second CRM lead.
    Supports multiple branches: if the incoming record comes from a different branch,
    it registers the branch under existing_lead.secondary_branches.
    Preserves existing staff assignments and existing valid information.
    """
    updated_fields = []

    # Handle branch assignment & multiple branches
    if branch:
        if not existing_lead.branch:
            existing_lead.branch = branch
            updated_fields.append('branch')
        elif existing_lead.branch != branch:
            existing_lead.secondary_branches.add(branch)

    # Update name if newer provided
    new_name = incoming_data.get('name') or incoming_data.get('lead name')
    if new_name:
        clean_new_name = str(new_name).strip()
        if clean_new_name and existing_lead.name != clean_new_name:
            existing_lead.name = clean_new_name
            updated_fields.append('name')

    new_email = incoming_data.get('email')
    if new_email and not existing_lead.email:
        existing_lead.email = str(new_email).strip().lower()
        updated_fields.append('email')

    new_alt_phone = incoming_data.get('alternate_phone') or incoming_data.get('alt_phone')
    if new_alt_phone and not existing_lead.alternate_phone:
        existing_lead.alternate_phone = str(new_alt_phone).strip()
        updated_fields.append('alternate_phone')

    new_product = incoming_data.get('product')
    if new_product and not existing_lead.product:
        existing_lead.product = new_product
        updated_fields.append('product')

    new_channel = incoming_data.get('channel')
    if new_channel and not existing_lead.channel:
        existing_lead.channel = new_channel
        updated_fields.append('channel')

    # Merge notes without overwriting
    new_notes = incoming_data.get('notes') or incoming_data.get('remarks')
    if new_notes:
        note_str = str(new_notes).strip()
        if note_str and note_str not in (existing_lead.notes or ''):
            branch_tag = branch.name if branch else source_label
            if existing_lead.notes:
                existing_lead.notes = f"{existing_lead.notes}\n[{branch_tag}]: {note_str}".strip()
            else:
                existing_lead.notes = f"[{branch_tag}]: {note_str}"
            updated_fields.append('notes')

    if updated_fields:
        updated_fields.append('updated_at')
        existing_lead.save(update_fields=updated_fields)

    # Audit log
    branch_name = branch.name if branch else 'N/A'
    log_activity(
        user=user,
        action="Duplicate Lead Retained",
        description=f"Incoming lead '{existing_lead.name}' ({existing_lead.phone}) for branch '{branch_name}' retained as single unique lead #{existing_lead.id}.",
        object_type="Lead",
        object_id=existing_lead.pk
    )

    return existing_lead


def detect_all_duplicate_groups():
    """
    Scans the CRM database to detect all duplicate lead groups.
    Groups are identified by:
    1. Multiple Lead records with the same normalized phone number.
    2. Multiple Lead records with the same email.
    3. A single Lead record that has multiple branches associated (secondary_branches).

    Returns:
        tuple (groups_list, total_groups_count)
    """
    all_leads = Lead.objects.all().select_related('branch', 'channel', 'product').prefetch_related('secondary_branches')

    # Map by normalized phone
    phone_to_leads = defaultdict(list)
    email_to_leads = defaultdict(list)
    multi_branch_leads = []

    for lead in all_leads:
        clean_phone = normalize_phone(lead.phone)
        if clean_phone and len(clean_phone) >= 7 and not clean_phone.startswith('NoPhone-'):
            target_key = clean_phone[-10:] if len(clean_phone) >= 10 else clean_phone
            phone_to_leads[target_key].append(lead)

        clean_email = normalize_email(lead.email)
        if clean_email:
            email_to_leads[clean_email].append(lead)

        if lead.secondary_branches.exists():
            multi_branch_leads.append(lead)

    processed_lead_ids = set()
    groups = []
    group_counter = 1

    # 1. Process phone duplicate groups (multiple DB records)
    for target_key, leads in phone_to_leads.items():
        if len(leads) > 1:
            group_leads = [l for l in leads if l.id not in processed_lead_ids]
            if len(group_leads) >= 2:
                # Collect all unique branches across these leads
                branches = []
                for l in group_leads:
                    for b in l.get_all_branches():
                        if b and b.name not in branches:
                            branches.append(b.name)

                primary = group_leads[0]
                groups.append({
                    'group_id': group_counter,
                    'group_label': f"Duplicate Group {group_counter:02d}",
                    'name': primary.name,
                    'phone': primary.phone,
                    'email': primary.email or '',
                    'branches': branches,
                    'lead_ids': [l.id for l in group_leads],
                    'lead_ids_str': ','.join(str(l.id) for l in group_leads),
                    'leads': group_leads,
                    'is_single_record': False,
                    'lead_count': len(group_leads),
                })
                group_counter += 1
                for l in group_leads:
                    processed_lead_ids.add(l.id)

    # 2. Process email duplicate groups (multiple DB records)
    for clean_email, leads in email_to_leads.items():
        if len(leads) > 1:
            group_leads = [l for l in leads if l.id not in processed_lead_ids]
            if len(group_leads) >= 2:
                branches = []
                for l in group_leads:
                    for b in l.get_all_branches():
                        if b and b.name not in branches:
                            branches.append(b.name)

                primary = group_leads[0]
                groups.append({
                    'group_id': group_counter,
                    'group_label': f"Duplicate Group {group_counter:02d}",
                    'name': primary.name,
                    'phone': primary.phone,
                    'email': clean_email,
                    'branches': branches,
                    'lead_ids': [l.id for l in group_leads],
                    'lead_ids_str': ','.join(str(l.id) for l in group_leads),
                    'leads': group_leads,
                    'is_single_record': False,
                    'lead_count': len(group_leads),
                })
                group_counter += 1
                for l in group_leads:
                    processed_lead_ids.add(l.id)

    # 3. Process leads that already maintain multiple branches under a single record
    for lead in multi_branch_leads:
        if lead.id not in processed_lead_ids:
            branches = lead.get_all_branch_names()
            if len(branches) >= 2:
                groups.append({
                    'group_id': group_counter,
                    'group_label': f"Duplicate Group {group_counter:02d}",
                    'name': lead.name,
                    'phone': lead.phone,
                    'email': lead.email or '',
                    'branches': branches,
                    'lead_ids': [lead.id],
                    'lead_ids_str': str(lead.id),
                    'leads': [lead],
                    'is_single_record': True,
                    'lead_count': 1,
                })
                group_counter += 1
                processed_lead_ids.add(lead.id)

    return groups, len(groups)


def keep_single_lead_for_group(lead_ids, user=None):
    """
    Consolidates multiple duplicate Lead records into a single unique Lead record.
    - Picks the primary lead (earliest created / most complete).
    - Transfers and retains valid details (email, notes, alternate phones, products).
    - Merges branches into primary_lead.secondary_branches.
    - Re-parents calls, follow-ups, activity logs, and sheet mappings to the primary lead.
    - Deletes duplicate copies, retaining exactly ONE unique lead record.
    - Logs audit activity.
    """
    if isinstance(lead_ids, str):
        lead_ids = [int(i.strip()) for i in lead_ids.split(',') if i.strip().isdigit()]

    if not lead_ids:
        raise ValueError("No valid lead IDs provided for consolidation.")

    with transaction.atomic():
        leads = list(Lead.objects.filter(id__in=lead_ids).order_by('id'))
        if not leads:
            raise ValueError("No leads found matching the provided IDs.")

        if len(leads) == 1:
            # Already a single record!
            primary_lead = leads[0]
            log_activity(
                user=user,
                action="Single Lead Maintained",
                description=f"Confirmed single unique lead '{primary_lead.name}' ({primary_lead.phone}) across branches: {', '.join(primary_lead.get_all_branch_names())}.",
                object_type="Lead",
                object_id=primary_lead.id
            )
            return primary_lead

        primary_lead = leads[0]
        other_leads = leads[1:]

        from followups.models import FollowUp
        from calls.models import CallHistory
        from activities.models import Activity

        for dup in other_leads:
            # Merge branch
            if dup.branch and dup.branch != primary_lead.branch:
                primary_lead.secondary_branches.add(dup.branch)
            for b in dup.secondary_branches.all():
                if b != primary_lead.branch:
                    primary_lead.secondary_branches.add(b)

            # Merge email
            if not primary_lead.email and dup.email:
                primary_lead.email = dup.email

            # Merge alt phone
            if not primary_lead.alternate_phone and dup.alternate_phone:
                primary_lead.alternate_phone = dup.alternate_phone

            # Merge product
            if not primary_lead.product and dup.product:
                primary_lead.product = dup.product

            # Merge channel
            if not primary_lead.channel and dup.channel:
                primary_lead.channel = dup.channel

            # Merge notes
            if dup.notes:
                b_name = dup.branch.name if dup.branch else 'Branch'
                if dup.notes not in (primary_lead.notes or ''):
                    if primary_lead.notes:
                        primary_lead.notes = f"{primary_lead.notes}\n[Merged from {b_name}]: {dup.notes}".strip()
                    else:
                        primary_lead.notes = f"[Merged from {b_name}]: {dup.notes}"

            # Re-parent related foreign keys
            FollowUp.objects.filter(lead=dup).update(lead=primary_lead)
            CallHistory.objects.filter(lead=dup).update(lead=primary_lead)
            dup.sheet_mappings.update(lead=primary_lead)
            Activity.objects.filter(object_type='Lead', object_id=dup.id).update(object_id=primary_lead.id)

            # Delete the redundant duplicate record
            dup.delete()

        primary_lead.save()

        log_activity(
            user=user,
            action="Duplicate Leads Consolidated",
            description=f"Consolidated duplicate records for '{primary_lead.name}' ({primary_lead.phone}) into single unique lead #{primary_lead.id}. Maintained branches: {', '.join(primary_lead.get_all_branch_names())}.",
            object_type="Lead",
            object_id=primary_lead.id
        )

        return primary_lead


def process_incoming_lead_with_10day_rule(lead_data, branch=None, source="Google Form", user=None):
    """
    Implements Duplicate Lead Detection (10-Day Rule):
    - If the same lead submits details through one branch and the same lead details
      are found in another branch within 10 days, treat the new record as a duplicate.
      The duplicate record does not create another normal lead record in the main Leads list.
      Instead, it keeps the original lead and stores duplicate details in DuplicateLeadRecord.
    - If the same lead submits details through another branch after 10 days,
      treat the submission as a valid new lead! Create normal lead and process Telecaller assignment.
    
    Returns:
        tuple (lead, is_duplicate, duplicate_record)
    """
    from .models import DuplicateLeadRecord, LeadStatus
    from .assignment import assign_lead_to_branch_telecaller
    from channels.models import Channel

    name = str(lead_data.get('name') or lead_data.get('lead name') or '').strip()
    phone = str(lead_data.get('phone') or lead_data.get('phone_number') or lead_data.get('mobile') or '').strip()
    email = str(lead_data.get('email') or '').strip()

    # Resolve branch
    incoming_branch = branch
    if not incoming_branch:
        branch_str = str(lead_data.get('branch') or lead_data.get('Branch') or '').strip()
        if branch_str:
            incoming_branch = Branch.objects.filter(name__iexact=branch_str).first() or \
                              Branch.objects.filter(name__icontains=branch_str).first()

    # Search for matching lead
    existing_lead = find_duplicate_lead(phone=phone, email=email, name=name)

    if existing_lead:
        # Check time difference
        now = timezone.now()
        time_diff = now - existing_lead.created_at
        days_diff = time_diff.total_seconds() / 86400.0

        is_same_branch = (
            (existing_lead.branch and incoming_branch and existing_lead.branch == incoming_branch) or
            (not existing_lead.branch and not incoming_branch)
        )

        clean_payload = {}
        if isinstance(lead_data, dict):
            for k, v in lead_data.items():
                if hasattr(v, 'name'):
                    clean_payload[k] = str(v.name)
                elif hasattr(v, 'pk'):
                    clean_payload[k] = str(v.pk)
                elif isinstance(v, (str, int, float, bool)) or v is None:
                    clean_payload[k] = v
                else:
                    clean_payload[k] = str(v)

        if is_same_branch:
            # ─────────────────────────────────────────────────────────
            # SAME BRANCH -> DUPLICATE!
            # ─────────────────────────────────────────────────────────
            dup_rec = DuplicateLeadRecord.objects.create(
                original_lead=existing_lead,
                name=name or existing_lead.name,
                phone=phone or existing_lead.phone,
                email=email or existing_lead.email,
                branch=incoming_branch,
                branch_name=incoming_branch.name if incoming_branch else str(lead_data.get('branch', '')),
                status='DUPLICATE',
                notes=lead_data.get('notes') or 'Same lead details detected in same branch.',
                source=source,
                data_payload=clean_payload
            )
            return (existing_lead, True, dup_rec)

        elif days_diff <= 10.0:
            # ─────────────────────────────────────────────────────────
            # DIFFERENT BRANCH WITHIN 10 DAYS -> DUPLICATE!
            # ─────────────────────────────────────────────────────────
            dup_rec = DuplicateLeadRecord.objects.create(
                original_lead=existing_lead,
                name=name or existing_lead.name,
                phone=phone or existing_lead.phone,
                email=email or existing_lead.email,
                branch=incoming_branch,
                branch_name=incoming_branch.name if incoming_branch else str(lead_data.get('branch', '')),
                status='DUPLICATE',
                notes='⚠ Same lead details detected in another branch within 10 days.',
                source=source,
                data_payload=clean_payload
            )

            # Register branch in secondary_branches if distinct
            if incoming_branch and incoming_branch != existing_lead.branch:
                existing_lead.secondary_branches.add(incoming_branch)

            branch_label = incoming_branch.name if incoming_branch else 'N/A'
            log_activity(
                user=user,
                action="Duplicate Lead Detected",
                description=f"Duplicate submission for '{existing_lead.name}' ({existing_lead.phone}) in branch '{branch_label}' recorded as duplicate within 10 days of original lead #{existing_lead.id}.",
                object_type="Lead",
                object_id=existing_lead.id
            )
            return (existing_lead, True, dup_rec)

        else:
            # ─────────────────────────────────────────────────────────
            # AFTER 10 DAYS -> VALID NEW LEAD!
            # ─────────────────────────────────────────────────────────
            # Treat submission as a valid new lead and assign Telecaller
            channel = (
                Channel.objects.filter(name__icontains='Google Form').first() or
                Channel.objects.filter(name__icontains='Form').first() or
                Channel.objects.first()
            )

            new_lead = Lead.objects.create(
                name=name or existing_lead.name,
                phone=phone or existing_lead.phone,
                email=email or existing_lead.email,
                alternate_phone=lead_data.get('alternate_phone', ''),
                channel=channel,
                status=LeadStatus.NEW,
                branch=incoming_branch,
                source=source,
                is_offline=True,
                notes=f"New submission from {incoming_branch.name if incoming_branch else 'branch'} (submitted 10+ days after original lead #{existing_lead.id})."
            )

            assign_lead_to_branch_telecaller(new_lead, branch=incoming_branch, source=source, triggered_by=user)

            log_activity(
                user=user,
                action="Lead Created (10+ Days Renewal)",
                description=f"Lead '{new_lead.name}' ({new_lead.phone}) submitted 10+ days after original lead #{existing_lead.id}. Processed as valid new lead in branch '{incoming_branch.name if incoming_branch else 'N/A'}'.",
                object_type="Lead",
                object_id=new_lead.id
            )
            return (new_lead, False, None)

    else:
        # ─────────────────────────────────────────────────────────
        # NO EXISTING LEAD -> BRAND NEW LEAD!
        # ─────────────────────────────────────────────────────────
        channel = (
            Channel.objects.filter(name__icontains='Google Form').first() or
            Channel.objects.filter(name__icontains='Form').first() or
            Channel.objects.first()
        )

        new_lead = Lead.objects.create(
            name=name or 'Google Form Lead',
            phone=phone or '9876543210',
            email=email,
            alternate_phone=lead_data.get('alternate_phone', ''),
            channel=channel,
            status=LeadStatus.NEW,
            branch=incoming_branch,
            source=source,
            is_offline=True,
            notes=lead_data.get('notes', 'Imported via Google Form')
        )

        assign_lead_to_branch_telecaller(new_lead, branch=incoming_branch, source=source, triggered_by=user)

        log_activity(
            user=user,
            action="Lead Created",
            description=f"New lead '{new_lead.name}' ({new_lead.phone}) imported via {source} for branch '{incoming_branch.name if incoming_branch else 'N/A'}'.",
            object_type="Lead",
            object_id=new_lead.id
        )
        return (new_lead, False, None)


def mask_phone(phone):
    """
    Formats 10-digit phone numbers as: 98765xxxxx (first 5 digits + xxxxx).
    Preserves non-standard or already masked phones.
    """
    if not phone:
        return ''
    raw = str(phone).strip()
    if raw.endswith('xxxxx') and len(raw) == 10:
        return raw
    clean = normalize_phone(raw)
    if len(clean) == 10 and clean.isdigit():
        return clean[:5] + 'xxxxx'
    elif len(raw) == 10 and raw.isdigit():
        return raw[:5] + 'xxxxx'
    return raw


def process_spreadsheet_row_duplicate_rules(row_data, headers=None, connection=None, user=None):
    """
    Implements Duplicate Flow (Sections 8, 9, 10, 11) for rows detected in a connected Google Spreadsheet:
    Row found in spreadsheet
           │
           ▼
    Check lead details (phone, email, name)
           │
           ├── Lead does NOT exist ──► Normal Lead
           │
           └── Lead exists
                 │
                 ├── Same Branch ──► Duplicate
                 │
                 └── Different Branch
                       │
                       ├── Within 10 Days ──► Duplicate (warning banner, status DUPLICATE)
                       │
                       └── After 10 Days ──► New / Normal Lead
    
    Returns:
        tuple (lead_or_existing, is_duplicate, duplicate_record)
    """
    from .models import DuplicateLeadRecord, LeadStatus, GoogleSheetRowMapping
    from .assignment import assign_lead_to_branch_telecaller
    from channels.models import Channel

    # Convert row_data to dict if needed
    row_dict = {}
    if isinstance(row_data, dict):
        row_dict = dict(row_data)
    elif isinstance(row_data, (list, tuple)) and headers:
        for idx, h in enumerate(headers):
            if idx < len(row_data):
                row_dict[h] = row_data[idx]

    # Helper to find values case-insensitively
    def get_val(*keywords):
        for k, v in row_dict.items():
            if str(k).startswith('_'):
                continue
            k_lower = str(k).strip().lower()
            if any(kw in k_lower for kw in keywords):
                if v is not None and str(v).strip():
                    return str(v).strip()
        return ''

    name = get_val('name', 'student', 'applicant')
    phone = get_val('phone', 'mobile', 'contact')
    email = get_val('email')
    branch_str = get_val('branch', 'location', 'center', 'city')
    notes_str = get_val('notes', 'remarks', 'query', 'course', 'product')

    row_idx = row_dict.get('_row_index', 0)
    row_id = ''
    if connection:
        row_id = f"{connection.spreadsheet_id}_{connection.worksheet_name or 'Sheet1'}_row_{row_idx}"

    # Check if already processed
    if connection and row_id:
        existing_mapping = GoogleSheetRowMapping.objects.filter(
            connection=connection,
            row_identifier=row_id
        ).select_related('lead').first()
        if existing_mapping:
            return (existing_mapping.lead, False, None)

        existing_dup = DuplicateLeadRecord.objects.filter(
            original_lead__sheet_mappings__connection=connection,
            name=name,
            phone=phone
        ).first() if (name and phone) else None
        if existing_dup:
            return (existing_dup.original_lead, True, existing_dup)

    # Resolve incoming branch
    incoming_branch = None
    if branch_str:
        incoming_branch = Branch.objects.filter(Q(name__iexact=branch_str) | Q(name__icontains=branch_str)).first()

    if not incoming_branch and connection:
        if connection.branch:
            incoming_branch = connection.branch
        elif connection.name:
            for b in Branch.objects.filter(status='Active'):
                if b.name.lower() in connection.name.lower():
                    incoming_branch = b
                    break

    if not incoming_branch and user and hasattr(user, 'branch') and user.branch:
        incoming_branch = user.branch

    clean_payload = {}
    for k, v in row_dict.items():
        if not str(k).startswith('_'):
            clean_payload[str(k)] = str(v) if v is not None else ''

    source_label = connection.name if connection else 'Google Sheets'

    # Check for existing lead by details
    existing_lead = find_duplicate_lead(phone=phone, email=email, name=name)

    if existing_lead:
        now = timezone.now()
        time_diff = now - existing_lead.created_at
        days_diff = time_diff.total_seconds() / 86400.0

        is_same_branch = (
            (existing_lead.branch and incoming_branch and existing_lead.branch == incoming_branch) or
            (not existing_lead.branch and not incoming_branch)
        )

        if is_same_branch:
            # ─────────────────────────────────────────────────────────
            # SAME BRANCH -> DUPLICATE!
            # ─────────────────────────────────────────────────────────
            dup_rec = DuplicateLeadRecord.objects.create(
                original_lead=existing_lead,
                name=name or existing_lead.name,
                phone=phone or existing_lead.phone,
                email=email or existing_lead.email,
                branch=incoming_branch,
                branch_name=incoming_branch.name if incoming_branch else (existing_lead.branch.name if existing_lead.branch else 'Same Branch'),
                status='DUPLICATE',
                notes=notes_str or 'Same lead details detected in same branch.',
                source=source_label,
                data_payload=clean_payload
            )
            return (existing_lead, True, dup_rec)

        elif days_diff <= 10.0:
            # ─────────────────────────────────────────────────────────
            # DIFFERENT BRANCH WITHIN 10 DAYS -> DUPLICATE!
            # ─────────────────────────────────────────────────────────
            dup_rec = DuplicateLeadRecord.objects.create(
                original_lead=existing_lead,
                name=name or existing_lead.name,
                phone=phone or existing_lead.phone,
                email=email or existing_lead.email,
                branch=incoming_branch,
                branch_name=incoming_branch.name if incoming_branch else 'Different Branch',
                status='DUPLICATE',
                notes='⚠ Same lead details detected in another branch within 10 days.',
                source=source_label,
                data_payload=clean_payload
            )

            if incoming_branch and incoming_branch != existing_lead.branch:
                existing_lead.secondary_branches.add(incoming_branch)

            return (existing_lead, True, dup_rec)

        else:
            # ─────────────────────────────────────────────────────────
            # DIFFERENT BRANCH AFTER 10 DAYS -> VALID NEW LEAD!
            # ─────────────────────────────────────────────────────────
            # Channel/Source attribution: use the connection's selected Channel/Source
            # (the admin-selected marketing attribution), not a hardcoded "Google Sheets".
            channel = (connection.channel if connection else None) or (
                Channel.objects.filter(name__icontains='Google Sheets').first() or
                Channel.objects.first()
            )

            new_lead = Lead.objects.create(
                name=name or existing_lead.name,
                phone=phone or existing_lead.phone,
                email=email or existing_lead.email,
                branch=incoming_branch,
                channel=channel,
                source=source_label,
                is_offline=True,
                status=LeadStatus.NEW,
                notes=f"New submission from {incoming_branch.name if incoming_branch else 'branch'} (submitted 10+ days after original lead #{existing_lead.id})."
            )

            assign_lead_to_branch_telecaller(new_lead, branch=incoming_branch, source=source_label, triggered_by=user)

            if connection and row_id:
                GoogleSheetRowMapping.objects.get_or_create(
                    connection=connection,
                    row_identifier=row_id,
                    defaults={'lead': new_lead, 'row_index': row_idx, 'source_status': 'Active'}
                )

            return (new_lead, False, None)

    else:
        # ─────────────────────────────────────────────────────────
        # NO EXISTING LEAD -> BRAND NEW LEAD!
        # ─────────────────────────────────────────────────────────
        # Channel/Source attribution: use the connection's selected Channel/Source
        # (the admin-selected marketing attribution), not a hardcoded "Google Sheets".
        channel = (connection.channel if connection else None) or (
            Channel.objects.filter(name__icontains='Google Sheets').first() or
            Channel.objects.first()
        )

        new_lead = Lead.objects.create(
            name=name or 'Spreadsheet Lead',
            phone=phone or '',
            email=email or '',
            branch=incoming_branch,
            channel=channel,
            source=source_label,
            is_offline=True,
            status=LeadStatus.NEW,
            notes=notes_str or f"Imported from {source_label}"
        )

        assign_lead_to_branch_telecaller(new_lead, branch=incoming_branch, source=source_label, triggered_by=user)

        if connection and row_id:
            GoogleSheetRowMapping.objects.get_or_create(
                connection=connection,
                row_identifier=row_id,
                defaults={'lead': new_lead, 'row_index': row_idx, 'source_status': 'Active'}
            )

        return (new_lead, False, None)


