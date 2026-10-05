import logging
from django.db import models
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, Http404, JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from accounts.models import UserRole
from accounts.permissions import can_access_lead, get_accessible_branch_ids
from activities.utils import log_activity
from .models import DriveConnection, CallRecording
from .services import (
    validate_and_connect_drive_folder,
    sync_drive_connection,
    retry_matching_unmatched_recordings,
    get_user_recordings_queryset,
    STANDARD_SILENT_MP3,
)

logger = logging.getLogger('crm')


@login_required
def drive_dashboard(request):
    """
    Main unified Drive page view accessible across Admin, Manager, and Telecaller roles.
    Presents connected folders, recording statistics, search/filter controls,
    and role-scoped call recordings.
    Telecallers see only their own folder connections and recordings.
    """
    if request.user.is_telecaller_user:
        connections = DriveConnection.objects.filter(created_by=request.user).order_by('-created_at')
    elif request.user.is_sales_head_user:
        branch_ids = get_accessible_branch_ids(request.user)
        connections = DriveConnection.objects.filter(
            models_q = None
        ) if False else DriveConnection.objects.filter(
            models.Q(created_by=request.user) | models.Q(created_by__branch_id__in=branch_ids)
        ).order_by('-created_at').distinct()
    else:
        connections = DriveConnection.objects.all().order_by('-created_at')

    latest_connection = connections.filter(is_active=True).first() or connections.first()

    # Base recordings scoped to user's permissions
    recordings_qs = get_user_recordings_queryset(request.user)

    # Search & Filters (Section 19)
    search_mobile = request.GET.get('search_mobile', '').strip()
    search_file = request.GET.get('search_file', '').strip()
    status_filter = request.GET.get('status', 'All').strip()

    if search_mobile:
        recordings_qs = recordings_qs.filter(
            models.Q(mobile_number__icontains=search_mobile) |
            models.Q(normalized_mobile_number__icontains=search_mobile)
        )

    if search_file:
        recordings_qs = recordings_qs.filter(file_name__icontains=search_file)

    if status_filter == 'Matched':
        recordings_qs = recordings_qs.filter(match_status='MATCHED')
    elif status_filter == 'Unmatched':
        recordings_qs = recordings_qs.filter(match_status='UNMATCHED')

    # Metrics (Section 18)
    connected_folders_count = connections.filter(is_active=True).count()
    user_recordings = get_user_recordings_queryset(request.user)
    total_recordings_count = user_recordings.count()
    matched_recordings_count = user_recordings.filter(match_status='MATCHED').count()
    
    if (request.user.is_admin_user or request.user.is_sales_head_user) and status_filter != 'Matched':
        unmatched_recordings_count = CallRecording.objects.filter(match_status='UNMATCHED').count()
        unmatched_recordings = CallRecording.objects.filter(match_status='UNMATCHED').select_related('drive_connection').order_by('-created_at')
    else:
        unmatched_recordings_count = CallRecording.objects.filter(match_status='UNMATCHED').count() if (request.user.is_admin_user or request.user.is_sales_head_user) else 0
        unmatched_recordings = []

    last_sync = latest_connection.last_sync_at if latest_connection else None
    is_connected = latest_connection is not None and latest_connection.is_active and latest_connection.connection_status == 'Connected'
    sync_status = 'Active' if is_connected else 'Inactive'

    context = {
        'connections': connections,
        'latest_connection': latest_connection,
        'is_connected': is_connected,
        'recordings': recordings_qs,
        'unmatched_recordings': unmatched_recordings,
        'connected_folders_count': connected_folders_count,
        'total_recordings_count': total_recordings_count,
        'matched_recordings_count': matched_recordings_count,
        'unmatched_recordings_count': unmatched_recordings_count,
        'last_sync': last_sync,
        'sync_status': sync_status,
        'search_mobile': search_mobile,
        'search_file': search_file,
        'status_filter': status_filter,
        'is_admin': request.user.is_admin_user,
        'is_manager': request.user.is_sales_head_user,
        'is_telecaller': request.user.is_telecaller_user,
    }

    return render(request, 'drive/drive_dashboard.html', context)


@login_required
@require_POST
def drive_connect(request):
    """
    Connects a new or existing Google Drive folder link.
    Validates folder URL, checks access, loads call recordings, and matches leads.
    """
    folder_url = request.POST.get('folder_url', '').strip()
    folder_name = request.POST.get('folder_name', '').strip()

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json'

    if not folder_url:
        err_msg = "🔴 Unable to connect to Drive\n\nThe Drive folder link is invalid.\n\nPlease enter a valid Google Drive folder link. Invalid Drive folder link."
        if is_ajax:
            return HttpResponse(err_msg, status=400)
        messages.error(request, err_msg)
        return redirect('drive_dashboard')

    success, message, conn = validate_and_connect_drive_folder(
        folder_url=folder_url,
        custom_name=folder_name,
        user=request.user
    )

    if success and conn:
        messages.success(request, message)
        log_activity(
            user=request.user,
            action="Drive Connected",
            description=f"Connected Google Drive folder '{conn.name}'.",
            object_type="DriveConnection",
            object_id=str(conn.pk),
            request=request
        )
    else:
        messages.error(request, message)

    return redirect('drive_dashboard')


@login_required
@require_POST
def drive_sync(request, connection_id):
    """
    Manually triggers synchronization for a connected Drive folder.
    """
    connection = get_object_or_404(DriveConnection, pk=connection_id)

    # Ownership check: Telecaller can only sync their own connections
    if request.user.is_telecaller_user and connection.created_by != request.user:
        raise PermissionDenied("Access denied: You do not own this Drive connection.")

    success, message, created, matched = sync_drive_connection(connection, triggered_by=request.user)

    if success:
        messages.success(request, message)
        log_activity(
            user=request.user,
            action="Drive Synced",
            description=f"Synchronized Drive folder '{connection.name}' ({created} new, {matched} matched).",
            object_type="DriveConnection",
            object_id=str(connection.pk),
            request=request
        )
    else:
        messages.error(request, message)

    return redirect('drive_dashboard')


@login_required
@require_POST
def drive_disconnect(request, connection_id):
    """
    Disconnects a Google Drive folder source.
    Stops future synchronization while preserving all archived audio in MySQL.
    """
    connection = get_object_or_404(DriveConnection, pk=connection_id)

    # Permission verification
    if request.user.is_telecaller_user and connection.created_by != request.user:
        raise PermissionDenied("Access denied: You cannot disconnect another user's Drive folder.")

    if not (request.user.is_telecaller_user or request.user.is_admin_user or request.user.is_sales_head_user):
        raise PermissionDenied("Access denied.")

    name = connection.name
    # Mark disconnected and inactive to stop future synchronization
    connection.connection_status = 'Disconnected'
    connection.is_active = False
    connection.save(update_fields=['connection_status', 'is_active', 'updated_at'])

    log_activity(
        user=request.user,
        action="Drive Disconnected",
        description=f"Disconnected Drive folder '{name}'. Archived audio preserved in MySQL.",
        object_type="DriveConnection",
        object_id=str(connection.pk),
        request=request
    )
    messages.success(request, f"Drive folder '{name}' disconnected successfully. Archived audio remains preserved in MySQL.")
    return redirect('drive_dashboard')


@login_required
@require_POST
def drive_retry_matching(request):
    """
    Retries matching all UNMATCHED recordings against current CRM leads.
    """
    matched_count = retry_matching_unmatched_recordings(user=request.user)

    if matched_count > 0:
        messages.success(request, f"🟢 Re-matching completed: {matched_count} call recording(s) newly matched to CRM leads!")
        log_activity(
            user=request.user,
            action="Drive Re-matching",
            description=f"Re-matching attached {matched_count} call recording(s) to CRM leads.",
            object_type="CallRecording",
            object_id="",
            request=request
        )
    else:
        messages.info(request, "Re-matching completed: No new matching CRM leads found for unmatched recordings.")

    return redirect('drive_dashboard')


@login_required
def drive_stream_recording(request, recording_id):
    """
    Serves recording audio with strict role-based access validation.
    Streams actual binary audio saved in MySQL.
    """
    recording = get_object_or_404(CallRecording, pk=recording_id)

    # Permission verification: Telecaller can only stream their own recordings
    if request.user.is_telecaller_user:
        is_owner = (
            recording.telecaller == request.user or
            (recording.drive_connection and recording.drive_connection.created_by == request.user) or
            (recording.lead and recording.lead.assigned_telecaller == request.user)
        )
        if not is_owner:
            raise PermissionDenied("Access denied: You do not have permission to access this recording.")
    elif request.user.is_sales_head_user:
        branch_ids = get_accessible_branch_ids(request.user)
        allowed = (
            (recording.lead and (recording.lead.assigned_sales_head == request.user or recording.lead.branch_id in branch_ids)) or
            (recording.telecaller and recording.telecaller.branch_id in branch_ids) or
            (recording.drive_connection and recording.drive_connection.created_by and recording.drive_connection.created_by.branch_id in branch_ids)
        )
        if not allowed:
            raise PermissionDenied("Access denied: You do not have permission to access this recording.")

    # Return audio stream from MySQL binary storage
    content_type = recording.mime_type or 'audio/mpeg'
    if recording.audio_data:
        audio_content = bytes(recording.audio_data)
    else:
        audio_content = STANDARD_SILENT_MP3

    response = HttpResponse(audio_content, content_type=content_type)
    response['Content-Disposition'] = f'inline; filename="{recording.file_name}"'
    response['Content-Length'] = str(len(audio_content))
    response['Accept-Ranges'] = 'bytes'
    return response


@login_required
def drive_api_sync(request, connection_id):
    """
    Endpoint for 10-second automatic polling synchronization.
    Runs incremental sync, downloads any new audio files into MySQL,
    and returns JSON status with updated counts.
    """
    connection = get_object_or_404(DriveConnection, pk=connection_id)

    # Permission verification
    if request.user.is_telecaller_user and connection.created_by != request.user:
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)

    if not connection.is_active or connection.connection_status == 'Disconnected':
        return JsonResponse({
            'success': True,
            'is_connected': False,
            'connection_id': connection.pk,
            'connection_status': 'Disconnected',
            'total_archived': connection.recordings.count(),
            'new_files': 0,
            'message': 'Folder is disconnected.',
        })

    success, message, created, matched = sync_drive_connection(connection, triggered_by=request.user)
    connection.refresh_from_db()

    # Get recent recordings for this connection
    recordings = connection.recordings.select_related('lead')[:10]
    rec_list = [
        {
            'id': r.pk,
            'file_name': r.file_name,
            'mobile_number': r.normalized_mobile_number or r.mobile_number,
            'duration': r.duration,
            'match_status': r.match_status,
            'lead_name': r.lead.name if r.lead else None,
            'lead_id': r.lead.pk if r.lead else None,
            'drive_url': r.drive_url,
        }
        for r in recordings
    ]

    return JsonResponse({
        'success': True,
        'is_connected': connection.is_active and connection.connection_status == 'Connected',
        'connection_id': connection.pk,
        'folder_name': connection.name,
        'connection_status': connection.connection_status,
        'last_sync_status': connection.last_sync_status,
        'last_sync_at': connection.last_sync_at.isoformat() if connection.last_sync_at else None,
        'total_archived': connection.recordings.count(),
        'matched_count': connection.matched_recordings_count,
        'unmatched_count': connection.unmatched_recordings_count,
        'new_files': created,
        'newly_matched': matched,
        'message': message,
        'recordings': rec_list,
    })


@login_required
def drive_api_status(request):
    """
    Returns latest connection status and metrics for the logged-in user.
    """
    if request.user.is_telecaller_user:
        connection = DriveConnection.objects.filter(created_by=request.user, is_active=True).first()
        recordings_count = CallRecording.objects.filter(
            models.Q(telecaller=request.user) |
            models.Q(drive_connection__created_by=request.user) |
            models.Q(lead__assigned_telecaller=request.user)
        ).distinct().count()
    else:
        connection = DriveConnection.objects.filter(is_active=True).first()
        recordings_count = CallRecording.objects.count()

    if not connection:
        return JsonResponse({
            'success': True,
            'is_connected': False,
            'total_archived': recordings_count,
        })

    return JsonResponse({
        'success': True,
        'is_connected': connection.is_active and connection.connection_status == 'Connected',
        'connection_id': connection.pk,
        'folder_name': connection.name,
        'connection_status': connection.connection_status,
        'last_sync_at': connection.last_sync_at.isoformat() if connection.last_sync_at else None,
        'total_archived': recordings_count,
        'matched_count': connection.matched_recordings_count,
        'unmatched_count': connection.unmatched_recordings_count,
    })

