from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from django.utils import timezone
from accounts.models import User, UserRole
from accounts.permissions import admin_required, sales_head_required, telecaller_required, can_access_lead, get_accessible_branch_ids
from branches.models import Branch
from branches.utils import get_admin_selected_branch
from leads.models import Lead, LeadStatus
from leads.handoff_service import change_lead_status
from followups.models import FollowUp, FollowUpStatus
from activities.utils import log_activity
from .models import CallHistory, CallStatus, CallOutcome
from .forms import AdminCallRecordForm

from django.http import JsonResponse

def _branch_sales_head(branch):
    if not branch:
        return None
    access = branch.sales_head_access.select_related('sales_head').first()
    return access.sales_head if access else None

@login_required
@transaction.atomic
def start_call_record(request):
    """
    Mandatory endpoint to initiate a call for a lead.
    Enforces the Call-Notes Lock:
    If the caller has an unfinished call where notes are pending (notes_completed=False),
    starting another call is strictly BLOCKED both at backend and frontend.
    """
    caller = request.user
    lead_id = request.POST.get('lead_id') or request.GET.get('lead_id')
    if not lead_id:
        return JsonResponse({'success': False, 'error': 'Missing lead_id parameter.'}, status=400)

    lead = get_object_or_404(Lead, pk=lead_id)

    # Scoped verification: Enforce access control
    if not can_access_lead(caller, lead):
        raise PermissionDenied("Permission denied: You are not authorized to call this lead.")

    # Check for pending call notes lock across ALL leads for this telecaller
    pending_call = CallHistory.objects.filter(
        caller=caller,
        notes_completed=False
    ).select_related('lead').order_by('-call_started_at').first()

    if pending_call:
        return JsonResponse({
            'success': False,
            'blocked': True,
            'error': 'call_notes_required',
            'message': 'You have a completed call that still requires notes.',
            'pending_call': {
                'id': pending_call.id,
                'lead_id': pending_call.lead.id,
                'lead_name': pending_call.lead.name,
                'lead_phone': pending_call.lead.phone,
                'duration': pending_call.duration,
                'formatted_duration': pending_call.formatted_duration,
                'call_status': pending_call.call_status,
                'started_at': pending_call.call_started_at.strftime('%Y-%m-%d %H:%M:%S')
            }
        }, status=400)

    # No pending lock: create active call record
    now = timezone.now()
    manager = lead.assigned_sales_head or (_branch_sales_head(caller.branch) if caller.is_telecaller_user else None)
    telecaller = caller if caller.is_telecaller_user else lead.assigned_telecaller

    new_call = CallHistory.objects.create(
        lead=lead,
        caller=caller,
        manager=manager,
        telecaller=telecaller,
        call_started_at=now,
        duration=0,
        call_status=CallStatus.INITIATED,
        call_outcome=CallOutcome.FOLLOW_UP_REQUIRED,
        notes='',
        notes_completed=False
    )

    return JsonResponse({
        'success': True,
        'call_id': new_call.id,
        'lead_id': lead.id,
        'lead_name': lead.name,
        'lead_phone': lead.phone,
        'started_at': new_call.call_started_at.strftime('%Y-%m-%d %H:%M:%S')
    })


@login_required
def check_call_lock(request):
    """
    Checks if the authenticated telecaller has a call waiting for mandatory notes.
    """
    pending_call = CallHistory.objects.filter(
        caller=request.user,
        notes_completed=False
    ).select_related('lead').order_by('-call_started_at').first()

    if pending_call:
        return JsonResponse({
            'has_lock': True,
            'pending_call': {
                'id': pending_call.id,
                'lead_id': pending_call.lead.id,
                'lead_name': pending_call.lead.name,
                'lead_phone': pending_call.lead.phone,
                'duration': pending_call.duration,
                'formatted_duration': pending_call.formatted_duration,
                'started_at': pending_call.call_started_at.strftime('%Y-%m-%d %H:%M:%S')
            }
        })
    return JsonResponse({'has_lock': False})


@login_required
@transaction.atomic
def end_call_record(request, pk):
    """
    Marks the live call as ended and records duration. Notes remain pending (notes_completed=False).
    """
    call = get_object_or_404(CallHistory, pk=pk, caller=request.user)
    duration = int(request.POST.get('duration', 0))
    now = timezone.now()
    call.call_ended_at = now
    if duration > 0:
        call.duration = duration
    elif not call.duration and call.call_started_at:
        call.duration = max(0, int((now - call.call_started_at).total_seconds()))
    call.call_status = CallStatus.CONNECTED
    call.save(update_fields=['call_ended_at', 'duration', 'call_status', 'updated_at'])
    return JsonResponse({
        'success': True,
        'call_id': call.id,
        'duration': call.duration,
        'formatted_duration': call.formatted_duration
    })


@login_required
@transaction.atomic
def complete_call_record(request):
    """
    Mandatory atomic backend completion for live calls (Section 48, 49).
    Authenticates user, verifies lead permission, validates mandatory notes (non-whitespace),
    records CallHistory with notes_completed=True, logs Activity, updates Lead status,
    optionally creates FollowUp, and commits atomically to the database.
    """
    if request.method != 'POST':
        return redirect('login_redirect')

    call_id = request.POST.get('call_id')
    lead_id = request.POST.get('lead_id')
    duration = int(request.POST.get('duration', 0))
    call_outcome = request.POST.get('call_outcome', CallOutcome.FOLLOW_UP_REQUIRED)
    lead_status = request.POST.get('lead_status')
    notes = request.POST.get('notes', '').strip()
    follow_up_date = request.POST.get('follow_up_date')
    follow_up_time = request.POST.get('follow_up_time')

    # Strict Validation: Call notes are required before completing this call and cannot be empty or whitespace-only
    if not notes:
        err_msg = "Call Notes are required before completing this call."
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({'success': False, 'error': err_msg}, status=400)
        messages.error(request, err_msg)
        if lead_id:
            return redirect('telecaller_lead_detail', pk=lead_id)
        return redirect('telecaller_dashboard')

    caller = request.user

    # Find existing initiated/ended call if call_id provided
    call_record = None
    if call_id:
        call_record = CallHistory.objects.filter(pk=call_id, caller=caller).first()

    if not call_record and lead_id:
        call_record = CallHistory.objects.filter(lead_id=lead_id, caller=caller, notes_completed=False).order_by('-call_started_at').first()

    if not lead_id and call_record:
        lead_id = call_record.lead_id

    lead = get_object_or_404(Lead, pk=lead_id)

    # Scoped verification: Enforce access control (returns 403 Forbidden if unauthorized)
    if not can_access_lead(caller, lead):
        raise PermissionDenied("Permission denied: You are not authorized to log calls for this lead.")

    # Calculate timestamps
    now = timezone.now()
    started_at = now - timezone.timedelta(seconds=duration) if duration > 0 else now

    # Determine supervising manager & telecaller references
    manager = lead.assigned_sales_head or (_branch_sales_head(caller.branch) if caller.is_telecaller_user else None)
    telecaller = caller if caller.is_telecaller_user else lead.assigned_telecaller

    if call_record:
        if duration > 0:
            call_record.duration = duration
        call_record.call_ended_at = now
        call_record.call_status = CallStatus.COMPLETED
        call_record.call_outcome = call_outcome
        call_record.notes = notes
        call_record.notes_completed = True
        call_record.save()
    else:
        call_record = CallHistory.objects.create(
            lead=lead,
            caller=caller,
            manager=manager,
            telecaller=telecaller,
            call_started_at=started_at,
            call_ended_at=now,
            duration=duration,
            call_status=CallStatus.COMPLETED,
            call_outcome=call_outcome,
            notes=notes,
            notes_completed=True
        )

    # Ensure no lingering unnoted calls remain for this lead/caller
    CallHistory.objects.filter(lead=lead, caller=caller, notes_completed=False).update(notes_completed=True)

    # 2. Update Lead status and append note
    if lead_status:
        change_lead_status(lead, lead_status, caller, remarks=notes or '')
    if notes:
        lead.notes = f"[{now.strftime('%Y-%m-%d %H:%M')}] Call by {caller.username} ({call_outcome}): {notes}\n" + (lead.notes or '')
    lead.save()

    # 3. Schedule next Follow-up if requested
    if follow_up_date:
        FollowUp.objects.create(
            lead=lead,
            assigned_user=caller,
            manager=manager,
            telecaller=telecaller,
            follow_up_date=follow_up_date,
            follow_up_time=follow_up_time or None,
            status=FollowUpStatus.PENDING,
            notes=f"Scheduled after call on {now.strftime('%Y-%m-%d')}: {notes}"
        )
        log_activity(
            user=caller,
            action="Follow-up Created",
            description=f"Scheduled follow-up with '{lead.name}' for {follow_up_date}.",
            object_type="FollowUp",
            request=request
        )

    # 4. Create Activity
    log_activity(
        user=caller,
        action="Call Completed",
        description=f"Completed {call_record.formatted_duration} call with lead '{lead.name}'. Outcome: {call_outcome}. Notes: {notes[:100]}",
        object_type="CallHistory",
        object_id=call_record.pk,
        request=request
    )

    # 5. Notify Supervising Manager if call made by telecaller
    if manager and caller != manager:
        from activities.services import create_notification
        create_notification(
            recipient=manager,
            title="Call Logged by Team Member",
            message=f"{caller.get_full_name() or caller.username} completed a {call_record.formatted_duration} call with '{lead.name}'. Outcome: {call_outcome}.",
            notification_type="call_logged"
        )

    success_msg = "Call notes saved successfully. You can now call another lead."
    messages.success(request, success_msg)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({
            'success': True,
            'message': success_msg,
            'call_id': call_record.pk,
            'duration': call_record.duration,
            'formatted_duration': call_record.formatted_duration
        })

    # Redirect based on user role
    if caller.is_telecaller_user:
        return redirect('telecaller_lead_detail', pk=lead.pk)
    elif caller.is_sales_head_user:
        return redirect('manager_lead_detail', pk=lead.pk)
    return redirect('admin_lead_detail', pk=lead.pk)


# ==========================================
# ADMIN: CALLS VIEWS
# ==========================================

@admin_required
def admin_calls_list(request):
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    outcome_filter = request.GET.get('outcome', '').strip()
    manager_filter = request.GET.get('manager', '').strip()
    telecaller_filter = request.GET.get('telecaller', '').strip()
    branch_filter = request.GET.get('branch', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    calls_qs = CallHistory.objects.select_related(
        'lead', 'caller', 'manager', 'telecaller', 'lead__branch', 'lead__product', 'lead__channel'
    )

    selected_branch = get_admin_selected_branch(request)
    if selected_branch:
        calls_qs = calls_qs.filter(lead__branch=selected_branch)
    elif branch_filter:
        calls_qs = calls_qs.filter(lead__branch_id=branch_filter)

    if search_query:
        calls_qs = calls_qs.filter(
            Q(lead__name__icontains=search_query) |
            Q(lead__phone__icontains=search_query) |
            Q(caller__username__icontains=search_query) |
            Q(notes__icontains=search_query)
        )
    if status_filter:
        calls_qs = calls_qs.filter(call_status=status_filter)
    if outcome_filter:
        calls_qs = calls_qs.filter(call_outcome=outcome_filter)
    if manager_filter:
        calls_qs = calls_qs.filter(manager_id=manager_filter)
    if telecaller_filter:
        calls_qs = calls_qs.filter(telecaller_id=telecaller_filter)
    if date_from:
        try:
            df = datetime.strptime(date_from, "%Y-%m-%d").date()
            calls_qs = calls_qs.filter(call_started_at__date__gte=df)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d").date()
            calls_qs = calls_qs.filter(call_started_at__date__lte=dt)
        except ValueError:
            pass

    calls_qs = calls_qs.order_by('-call_started_at')
    paginator = Paginator(calls_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Build extra_params for preserving filters across pagination links
    query_dict = request.GET.copy()
    query_dict.pop('page', None)
    extra_params = query_dict.urlencode()

    managers = User.objects.filter(role=UserRole.SALES_HEAD, is_active=True)
    telecallers = User.objects.filter(role=UserRole.TELECALLER, is_active=True)
    branches = Branch.objects.filter(status='Active')

    return render(request, 'admin/calls_list.html', {
        'page_obj': page_obj,
        'managers': managers,
        'telecallers': telecallers,
        'branches': branches,
        'statuses': CallStatus.choices,
        'outcomes': CallOutcome.choices,
        'search_query': search_query,
        'status_filter': status_filter,
        'outcome_filter': outcome_filter,
        'manager_filter': manager_filter,
        'telecaller_filter': telecaller_filter,
        'branch_filter': branch_filter,
        'date_from': date_from,
        'date_to': date_to,
        'extra_params': extra_params,
    })

@admin_required
def admin_call_create(request):
    initial = {'call_started_at': timezone.now()}
    lead_id = request.GET.get('lead')
    if lead_id:
        lead = Lead.objects.filter(pk=lead_id).first()
        if lead:
            initial['lead'] = lead
            initial['manager'] = lead.assigned_sales_head
            initial['telecaller'] = lead.assigned_telecaller

    if request.method == 'POST':
        form = AdminCallRecordForm(request.POST)
        if form.is_valid():
            call = form.save()
            log_activity(
                user=request.user,
                action="Call Created",
                description=f"Logged call record for '{call.lead.name}' ({call.call_outcome}, {call.formatted_duration}).",
                object_type="CallHistory",
                object_id=call.pk,
                request=request
            )
            messages.success(request, f"Call record for '{call.lead.name}' created successfully.")
            return redirect('admin_calls_list')
    else:
        form = AdminCallRecordForm(initial=initial)

    return render(request, 'admin/call_form.html', {
        'form': form,
        'page_title': 'Log Call Record'
    })

@admin_required
def admin_call_detail(request, pk):
    call = get_object_or_404(CallHistory.objects.select_related('lead', 'caller', 'manager', 'telecaller'), pk=pk)
    return render(request, 'admin/call_detail.html', {'call': call})



# ==========================================
# SALES HEAD: CALLS VIEWS
# ==========================================

@sales_head_required
def manager_calls_list(request):
    manager = request.user
    telecallers = User.objects.filter(role=UserRole.TELECALLER, branch_id__in=get_accessible_branch_ids(manager))
    telecaller_ids = list(telecallers.values_list('id', flat=True))

    calls_qs = CallHistory.objects.filter(
        Q(manager=manager) | Q(caller=manager) | Q(caller_id__in=telecaller_ids) | Q(telecaller_id__in=telecaller_ids)
    ).select_related('lead', 'caller', 'telecaller').order_by('-call_started_at')

    outcome_filter = request.GET.get('outcome', '').strip()
    telecaller_filter = request.GET.get('telecaller', '').strip()

    if outcome_filter:
        calls_qs = calls_qs.filter(call_outcome=outcome_filter)
    if telecaller_filter:
        calls_qs = calls_qs.filter(caller_id=telecaller_filter)

    paginator = Paginator(calls_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'manager/calls_list.html', {
        'page_obj': page_obj,
        'telecallers': telecallers,
        'outcomes': CallOutcome.choices,
        'outcome_filter': outcome_filter,
        'telecaller_filter': telecaller_filter,
    })


# ==========================================
# TELECALLER: CALLS VIEWS
# ==========================================

@telecaller_required
def telecaller_calls_list(request):
    telecaller = request.user
    today = timezone.now().date()
    calls_qs = CallHistory.objects.filter(caller=telecaller).select_related('lead').order_by('-call_started_at')

    outcome_filter = request.GET.get('outcome', '').strip()
    status_filter = request.GET.get('status', '').strip() or request.GET.get('filter', '').strip()

    if outcome_filter:
        calls_qs = calls_qs.filter(call_outcome=outcome_filter)

    if status_filter == 'pending':
        calls_qs = calls_qs.filter(
            Q(call_started_at__date=today) | Q(created_at__date=today)
        ).filter(
            Q(notes_completed=False) | ~Q(call_status__in=[CallStatus.COMPLETED, CallStatus.CANCELLED])
        )
    elif status_filter:
        calls_qs = calls_qs.filter(call_status=status_filter)

    paginator = Paginator(calls_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'telecaller/calls_list.html', {
        'page_obj': page_obj,
        'outcomes': CallOutcome.choices,
        'outcome_filter': outcome_filter,
        'status_filter': status_filter,
    })
