import json
import logging
from django.http import JsonResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from accounts.permissions import admin_required

from services.google_sheets_service import (
    validate_url,
    extract_spreadsheet_id,
    extract_gid,
    fetch_sheet,
)
from services.google_sheets_sync_service import sync_connection
from .models import GoogleSheetConnection, GoogleSheetRowMapping, Lead

logger = logging.getLogger('crm')


def _parse_request_body(request) -> dict:
    """Helper to parse JSON payload or POST form parameters."""
    if request.body:
        try:
            return json.loads(request.body.decode('utf-8'))
        except Exception:
            pass
    return request.POST.dict()


@csrf_exempt
def api_google_sheets_list(request):
    """
    GET /api/google-sheets/
    Returns list of all connected Google Sheet sources stored in MySQL.
    """
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    sheets = GoogleSheetConnection.objects.all().order_by('-created_at')
    data = []
    for s in sheets:
        sync_iso = s.last_sync_time.isoformat() if s.last_sync_time else None
        data.append({
            'id': s.id,
            'name': s.name,
            'sheet_url': s.spreadsheet_url,
            'spreadsheet_id': s.spreadsheet_id,
            'gid': s.gid or '0',
            'worksheet_name': s.worksheet_name,
            'is_active': s.is_active,
            'connection_status': s.connection_status,
            'last_sync_status': s.last_sync_status,
            'last_synced_at': sync_iso,
            'last_sync_error': s.last_sync_error,
            'total_leads_imported': s.total_leads_imported or s.row_mappings.count(),
            'created_at': s.created_at.isoformat(),
        })

    return JsonResponse({
        'success': True,
        'count': len(data),
        'sources': data
    })


@csrf_exempt
def api_google_sheets_connect(request):
    """
    POST /api/google-sheets/connect/
    Connects a new publicly accessible Google Sheet URL into MySQL.
    
    Payload:
    {
        "name": "Student Enquiries",
        "sheet_url": "https://docs.google.com/spreadsheets/d/1ABC.../edit#gid=0",
        "worksheet_name": "Sheet1",  (optional)
        "branch_id": 1               (optional)
    }
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    payload = _parse_request_body(request)
    sheet_url = (
        payload.get('sheet_url') or
        payload.get('url') or
        payload.get('spreadsheet_url') or ''
    ).strip()

    name = (payload.get('name') or payload.get('spreadsheet_name') or 'Google Sheet Leads').strip()
    worksheet_name = (payload.get('worksheet_name') or 'Sheet1').strip()
    branch_id = payload.get('branch_id')

    # 1. Validate Google Sheet URL (Strict domain & format validation, SSRF protection)
    is_valid, val_err = validate_url(sheet_url)
    if not is_valid:
        return JsonResponse({
            'success': False,
            'error': val_err or 'Invalid Google Spreadsheet URL.'
        }, status=400)

    # 2. Extract Spreadsheet ID & GID
    spreadsheet_id = extract_spreadsheet_id(sheet_url)
    gid = extract_gid(sheet_url) or '0'

    # 3. Test public access and fetch initial data
    try:
        headers, rows = fetch_sheet(
            spreadsheet_id=spreadsheet_id,
            gid=gid,
            sheet_name=worksheet_name
        )
    except PermissionError as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=403)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': f"Failed to access Google Sheet: {e}"
        }, status=502)

    if not headers or not any(headers):
        return JsonResponse({
            'success': False,
            'error': 'The Google Sheet contains no data or could not be read. Please ensure it contains header columns and is shared as "Anyone with the link can view".'
        }, status=400)

    # 4. Save or retrieve GoogleSheetConnection in MySQL
    conn, created = GoogleSheetConnection.objects.get_or_create(
        spreadsheet_id=spreadsheet_id,
        worksheet_name=worksheet_name,
        defaults={
            'name': name,
            'spreadsheet_url': sheet_url,
            'gid': gid,
            'is_active': True,
            'last_sync_status': 'Connected',
            'created_by': request.user if request.user.is_authenticated else None,
            'branch_id': int(branch_id) if (branch_id and str(branch_id).isdigit()) else None,
        }
    )

    if not created:
        conn.name = name
        conn.spreadsheet_url = sheet_url
        conn.gid = gid
        conn.is_active = True
        conn.last_sync_status = 'Connected'
        if branch_id and str(branch_id).isdigit():
            conn.branch_id = int(branch_id)
        conn.save()

    # 5. Perform initial synchronization into MySQL
    sync_result = sync_connection(
        connection=conn,
        triggered_by=request.user if request.user.is_authenticated else None,
        headers=headers,
        rows=rows
    )

    rows_imported = sync_result.get('created', 0) + sync_result.get('updated', 0)

    return JsonResponse({
        'success': True,
        'source_id': conn.id,
        'spreadsheet_id': conn.spreadsheet_id,
        'gid': conn.gid or '0',
        'worksheet_name': conn.worksheet_name,
        'rows_imported': rows_imported,
        'sync_result': sync_result,
        'message': f"Connected and synced {rows_imported} rows into MySQL successfully."
    }, status=201 if created else 200)


@csrf_exempt
def api_google_sheets_sync(request, connection_id):
    """
    POST /api/google-sheets/<int:connection_id>/sync/
    Triggers live manual 'Sync Now' for a specific connected sheet.
    Fetches latest rows from Google Sheets public export endpoint and updates MySQL.
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    conn = get_object_or_404(GoogleSheetConnection, pk=connection_id)
    user = request.user if request.user.is_authenticated else None

    result = sync_connection(conn, triggered_by=user)

    return JsonResponse({
        'success': result.get('success', True),
        'connection_id': conn.id,
        'name': conn.name,
        'sync_result': result
    })


@csrf_exempt
def api_google_sheets_detail(request, connection_id):
    """
    GET /api/google-sheets/<int:connection_id>/ -> Details & latest MySQL imported records.
    DELETE /api/google-sheets/<int:connection_id>/ -> Removes / disconnects connection.
    """
    conn = get_object_or_404(GoogleSheetConnection, pk=connection_id)

    if request.method == 'GET':
        # Retrieve imported leads from MySQL
        row_mappings = GoogleSheetRowMapping.objects.filter(connection=conn).select_related('lead')
        imported_records = []
        for m in row_mappings[:100]:
            imported_records.append({
                'row_index': m.row_index,
                'row_identifier': m.row_identifier,
                'lead_id': m.lead_id,
                'name': m.lead.name,
                'phone': m.lead.phone,
                'email': m.lead.email,
                'source_status': m.source_status,
                'status': m.lead.status,
            })

        return JsonResponse({
            'success': True,
            'source': {
                'id': conn.id,
                'name': conn.name,
                'sheet_url': conn.spreadsheet_url,
                'spreadsheet_id': conn.spreadsheet_id,
                'gid': conn.gid or '0',
                'worksheet_name': conn.worksheet_name,
                'is_active': conn.is_active,
                'connection_status': conn.connection_status,
                'last_sync_status': conn.last_sync_status,
                'last_synced_at': conn.last_sync_time.isoformat() if conn.last_sync_time else None,
                'last_sync_error': conn.last_sync_error,
                'total_leads_imported': conn.row_mappings.count(),
            },
            'records_count': len(imported_records),
            'records': imported_records
        })

    elif request.method == 'DELETE':
        conn.is_active = False
        conn.connection_status = 'DISCONNECTED'
        conn.last_sync_status = 'Disconnected'
        conn.save(update_fields=['is_active', 'connection_status', 'last_sync_status', 'updated_at'])

        return JsonResponse({
            'success': True,
            'connection_id': conn.id,
            'message': f"Google Sheet '{conn.name}' disconnected successfully."
        })

    return HttpResponseNotAllowed(['GET', 'DELETE'])
