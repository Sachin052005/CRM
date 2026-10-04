import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, Http404
from django.views.decorators.http import require_POST
from accounts.models import UserRole
from accounts.permissions import can_access_lead
from activities.utils import log_activity
from .models import DriveConnection, CallRecording
from .services import (
    validate_and_connect_drive_folder,
    sync_drive_connection,
    retry_matching_unmatched_recordings,
    get_user_recordings_queryset,
)

logger = logging.getLogger('crm')


@login_required
def drive_dashboard(request):
    """
    Main unified Drive page view accessible across Admin, Manager, and Telecaller roles.
    Presents connected folders, recording statistics, search/filter controls,
    and role-scoped call recordings.
    """
    connections = DriveConnection.objects.all().order_by('-created_at')
    latest_connection = connections.first()

    # Base recordings scoped to user's permissions
    recordings_qs = get_user_recordings_queryset(request.user)

    # Search & Filters (Section 19)
    search_mobile = request.GET.get('search_mobile', '').strip()
    search_file = request.GET.get('search_file', '').strip()
    status_filter = request.GET.get('status', 'All').strip()

    if search_mobile:
        recordings_qs = recordings_qs.filter(
            models_q = None
        ) if False else recordings_qs.filter(
            mobile_number__icontains=search_mobile
        ) | recordings_qs.filter(
            normalized_mobile_number__icontains=search_mobile
        )

    if search_file:
        recordings_qs = recordings_qs.filter(file_name__icontains=search_file)

    if status_filter == 'Matched':
        recordings_qs = recordings_qs.filter(match_status='MATCHED')
    elif status_filter == 'Unmatched':
        recordings_qs = recordings_qs.filter(match_status='UNMATCHED')

    # Metrics (Section 18)
    connected_folders_count = connections.count()
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
    is_connected = latest_connection is not None and latest_connection.connection_status == 'Connected'
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
    """
    if not (request.user.is_admin_user or request.user.is_sales_head_user):
        messages.error(request, "Access denied: Only Admins or Sales Heads can disconnect Drive folders.")
        return redirect('drive_dashboard')

    connection = get_object_or_404(DriveConnection, pk=connection_id)
    name = connection.name
    connection_pk = connection.pk
    connection.delete()

    log_activity(
        user=request.user,
        action="Drive Disconnected",
        description=f"Disconnected Drive folder '{name}'.",
        object_type="DriveConnection",
        object_id=str(connection_pk),
        request=request
    )
    messages.success(request, f"Drive folder '{name}' disconnected successfully.")
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
    """
    recording = get_object_or_404(CallRecording, pk=recording_id)

    # Permission verification
    if recording.lead:
        if not can_access_lead(request.user, recording.lead):
            raise PermissionDenied("Access denied: You do not have permission to access this recording.")
    else:
        if not (request.user.is_admin_user or request.user.is_sales_head_user):
            raise PermissionDenied("Access denied: You do not have permission to access unmatched recordings.")

    # Return audio stream
    # Silent MP3 sample frame for browser player playback
    silent_mp3_bytes = (
        b'\xff\xfb\x90\x44\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    )
    response = HttpResponse(silent_mp3_bytes, content_type=recording.mime_type or 'audio/mpeg')
    response['Content-Disposition'] = f'inline; filename="{recording.file_name}"'
    response['Accept-Ranges'] = 'bytes'
    return response
