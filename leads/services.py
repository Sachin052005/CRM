import csv
import io
import openpyxl
from django.db import transaction
from django.db.models import Count
from .models import Lead, LeadStatus, LeadImportHistory
from accounts.models import User, UserRole
from channels.models import Channel
from products.models import Product
from branches.models import Branch
from activities.utils import log_activity
from .assignment import assign_lead_automatically
from .duplicates import find_duplicate_lead, handle_incoming_lead_duplicate

def import_leads_file(uploaded_file, user):
    """
    Reusable file upload service for CSV/XLSX lead import.
    Applies role-scoped assignment, automatic manager & telecaller assignment,
    duplicate detection with update, and activity logging.
    """
    filename = uploaded_file.name
    rows = []

    if filename.endswith('.csv'):
        file_data = uploaded_file.read().decode('utf-8', errors='replace')
        io_string = io.StringIO(file_data)
        reader = csv.DictReader(io_string)
        for row in reader:
            rows.append(row)
    elif filename.endswith('.xlsx'):
        wb = openpyxl.load_workbook(uploaded_file, data_only=True)
        sheet = wb.active
        header = [str(cell.value or '').strip().lower() for cell in sheet[1]]
        for row_cells in sheet.iter_rows(min_row=2, values_only=True):
            if any(row_cells):
                row_dict = {}
                for h, val in zip(header, row_cells):
                    row_dict[h] = str(val or '').strip()
                rows.append(row_dict)
    else:
        raise ValueError("Unsupported file format. Please upload a .csv or .xlsx file.")

    total_records = len(rows)
    successful = 0
    failed = 0
    errors = []

    # Scoping attributes based on user role
    assigned_sales_head = None
    assigned_telecaller = None
    default_branch = None

    if user.is_telecaller_user:
        assigned_telecaller = user
        default_branch = user.branch
        if default_branch:
            access = default_branch.sales_head_access.select_related('sales_head').first()
            assigned_sales_head = access.sales_head if access else None
    elif user.is_sales_head_user:
        assigned_sales_head = user
        default_branch = user.branch

    with transaction.atomic():
        for idx, r in enumerate(rows, start=1):
            clean_row = {str(k).strip().lower(): str(v).strip() for k, v in r.items() if k}
            name = clean_row.get('name') or clean_row.get('lead name') or clean_row.get('full name')
            phone = clean_row.get('phone') or clean_row.get('mobile') or clean_row.get('phone number')
            email = clean_row.get('email', '')
            alt_phone = clean_row.get('alternate_phone') or clean_row.get('alt_phone', '')
            notes = clean_row.get('notes') or clean_row.get('remarks', '')

            if not name or not phone:
                failed += 1
                errors.append(f"Row {idx}: Name and Phone are required.")
                continue

            channel_name = clean_row.get('channel') or 'Offline'
            channel_obj = Channel.objects.filter(name__iexact=channel_name).first() if channel_name else None

            product_name = clean_row.get('product') or clean_row.get('course')
            product_obj = Product.objects.filter(name__iexact=product_name).first() if product_name else None

            branch_name = clean_row.get('branch')
            if branch_name:
                branch_obj = Branch.objects.filter(name__iexact=branch_name).first() or default_branch
            else:
                branch_obj = default_branch

            # Check duplicate in DB (by phone, email, or normalized details)
            existing_lead = find_duplicate_lead(phone=phone, email=email, name=name)

            if existing_lead:
                # Update existing lead and register branch without creating duplicate
                handle_incoming_lead_duplicate(
                    existing_lead=existing_lead,
                    incoming_data={
                        'name': name,
                        'email': email,
                        'alternate_phone': alt_phone,
                        'product': product_obj,
                        'channel': channel_obj,
                        'notes': notes
                    },
                    branch=branch_obj,
                    user=user,
                    source_label=f"File Import '{filename}'"
                )
                successful += 1
                continue

            # New Lead creation
            new_lead = Lead(
                name=name,
                phone=phone,
                email=email,
                alternate_phone=alt_phone,
                channel=channel_obj,
                product=product_obj,
                branch=branch_obj,
                status=LeadStatus.NEW,
                notes=notes
            )

            if user.is_telecaller_user:
                new_lead.assigned_telecaller = assigned_telecaller
                new_lead.assigned_sales_head = assigned_sales_head
                new_lead.branch = branch_obj or default_branch
            elif user.is_sales_head_user:
                new_lead.assigned_sales_head = assigned_sales_head
                # Auto-assign an active telecaller within this sales head's accessible branches
                from accounts.permissions import get_accessible_branch_ids
                tc_qs = User.objects.filter(role=UserRole.TELECALLER, branch_id__in=get_accessible_branch_ids(user), is_active=True)
                if branch_obj:
                    branch_tcs = tc_qs.filter(branch=branch_obj)
                    if branch_tcs.exists():
                        tc_qs = branch_tcs
                new_lead.assigned_telecaller = tc_qs.annotate(cnt=Count('telecaller_leads')).order_by('cnt', 'id').first() if tc_qs.exists() else None
                new_lead.branch = branch_obj or default_branch
            else:
                # Admin or batch import: auto-assign manager and telecaller
                assign_lead_automatically(
                    new_lead,
                    branch=branch_obj,
                    source=f"File Import '{filename}'",
                    triggered_by=user
                )

            new_lead.save()
            successful += 1

    # Record history
    history = LeadImportHistory.objects.create(
        file_name=filename,
        uploaded_by=user,
        records=total_records,
        successful=successful,
        failed=failed,
        status="Completed" if failed == 0 else "Completed with Errors",
        error_log="\n".join(errors[:50])
    )

    log_activity(
        user=user,
        action="Leads Imported",
        description=f"Batch lead import by {user.display_role} '{user.username}' from '{filename}': {successful} created, {failed} failed.",
        object_type="LeadImportHistory",
        object_id=history.pk
    )

    return successful, failed, errors
