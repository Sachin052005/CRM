from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.utils import timezone
from accounts.models import User, UserRole
from accounts.permissions import admin_required, telecaller_required
from branches.models import Branch
from leads.models import Lead, TelecallerLeadSetup
from calls.models import CallHistory, CallStatus, CallOutcome
from followups.models import FollowUp, FollowUpStatus
from activities.models import Activity
from activities.utils import log_activity
from branches.utils import get_admin_selected_branch
from django.contrib.auth.forms import SetPasswordForm
from .forms import AdminTelecallerCreateForm, AdminTelecallerEditForm, TelecallerAssignForm

# ==========================================
# ADMIN: TELECALLER MANAGEMENT
# ==========================================

@admin_required
def admin_telecallers_list(request):
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    manager_filter = request.GET.get('manager', '').strip()
    branch_filter = request.GET.get('branch', '').strip()

    telecallers_qs = User.objects.filter(role=UserRole.TELECALLER).select_related('manager', 'branch')

    if search_query:
        telecallers_qs = telecallers_qs.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    if status_filter == 'active':
        telecallers_qs = telecallers_qs.filter(is_active=True)
    elif status_filter == 'inactive':
        telecallers_qs = telecallers_qs.filter(is_active=False)

    if manager_filter:
        telecallers_qs = telecallers_qs.filter(manager_id=manager_filter)
    
    selected_branch = get_admin_selected_branch(request)
    if selected_branch:
        telecallers_qs = telecallers_qs.filter(branch=selected_branch)
    elif branch_filter:
        telecallers_qs = telecallers_qs.filter(branch_id=branch_filter)

    telecallers_qs = telecallers_qs.annotate(
        lead_count=Count('telecaller_leads', distinct=True),
        call_count=Count('telecaller_calls', distinct=True),
        followup_count=Count('telecaller_followups', distinct=True)
    ).order_by('-date_joined')

    paginator = Paginator(telecallers_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    managers = User.objects.filter(role=UserRole.MANAGER, is_active=True)
    branches = Branch.objects.filter(status='Active')

    return render(request, 'admin/telecallers_list.html', {
        'page_obj': page_obj,
        'managers': managers,
        'branches': branches,
        'search_query': search_query,
        'status_filter': status_filter,
        'manager_filter': manager_filter,
        'branch_filter': branch_filter,
    })

@admin_required
def admin_telecaller_create(request):
    if request.method == 'POST':
        form = AdminTelecallerCreateForm(request.POST)
        if form.is_valid():
            telecaller = form.save()
            if telecaller.branch:
                from leads.models import TelecallerLeadSetup
                TelecallerLeadSetup.objects.get_or_create(
                    telecaller=telecaller,
                    branch=telecaller.branch,
                    defaults={'assignment_percentage': 0, 'lead_count': 0, 'is_active': False}
                )
            mgr_str = f" under Manager '{telecaller.manager.username}'" if telecaller.manager else " (unassigned manager)"
            log_activity(
                user=request.user,
                action="Telecaller Created",
                description=f"Admin created Telecaller '{telecaller.username}' ({telecaller.email}){mgr_str}.",
                object_type="User",
                object_id=telecaller.pk,
                request=request
            )
            messages.success(request, f"Telecaller '{telecaller.username}' created successfully.")
            return redirect('admin_telecallers_list')
    else:
        form = AdminTelecallerCreateForm()

    return render(request, 'admin/telecaller_create.html', {'form': form})

@admin_required
def admin_telecaller_detail(request, pk):
    telecaller = get_object_or_404(User.objects.select_related('manager', 'branch'), pk=pk, role=UserRole.TELECALLER)

    leads = Lead.objects.filter(assigned_telecaller=telecaller).select_related('channel', 'product')[:10]
    calls = CallHistory.objects.filter(caller=telecaller).select_related('lead')[:10]
    followups = FollowUp.objects.filter(telecaller=telecaller).select_related('lead')[:10]
    activities = Activity.objects.filter(user=telecaller)[:10]

    total_leads = Lead.objects.filter(assigned_telecaller=telecaller).count()
    total_calls = CallHistory.objects.filter(caller=telecaller).count()
    completed_calls = CallHistory.objects.filter(caller=telecaller, call_status='Completed').count()
    pending_followups = FollowUp.objects.filter(telecaller=telecaller, status=FollowUpStatus.PENDING).count()

    return render(request, 'admin/telecaller_detail.html', {
        'telecaller': telecaller,
        'leads': leads,
        'calls': calls,
        'followups': followups,
        'activities': activities,
        'total_leads': total_leads,
        'total_calls': total_calls,
        'completed_calls': completed_calls,
        'pending_followups': pending_followups,
    })

@admin_required
def admin_telecaller_edit(request, pk):
    telecaller = get_object_or_404(User, pk=pk, role=UserRole.TELECALLER)
    if request.method == 'POST':
        form = AdminTelecallerEditForm(request.POST, instance=telecaller)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Telecaller Updated",
                description=f"Admin updated Telecaller profile for '{telecaller.username}'.",
                object_type="User",
                object_id=telecaller.pk,
                request=request
            )
            messages.success(request, f"Telecaller '{telecaller.username}' updated.")
            return redirect('admin_telecaller_detail', pk=telecaller.pk)
    else:
        form = AdminTelecallerEditForm(instance=telecaller)

    return render(request, 'admin/telecaller_edit.html', {'form': form, 'telecaller': telecaller})

@admin_required
def admin_telecaller_assign(request, pk):
    telecaller = get_object_or_404(User.objects.select_related('manager'), pk=pk, role=UserRole.TELECALLER)
    old_manager = telecaller.manager

    if request.method == 'POST':
        form = TelecallerAssignForm(request.POST)
        if form.is_valid():
            new_manager = form.cleaned_data['manager']
            telecaller.manager = new_manager
            telecaller.save()

            old_name = old_manager.get_full_name() or old_manager.username if old_manager else "None"
            new_name = new_manager.get_full_name() or new_manager.username

            log_activity(
                user=request.user,
                action="Telecaller Reassigned",
                description=f"Admin reassigned Telecaller '{telecaller.username}' from Manager '{old_name}' to Manager '{new_name}'.",
                object_type="User",
                object_id=telecaller.pk,
                request=request
            )
            messages.success(request, f"Telecaller '{telecaller.username}' successfully assigned to Manager '{new_name}'.")
            return redirect('admin_telecallers_list')
    else:
        initial_data = {'manager': old_manager.pk if old_manager else None}
        form = TelecallerAssignForm(initial=initial_data)

    return render(request, 'admin/telecaller_assign.html', {
        'form': form,
        'telecaller': telecaller,
        'old_manager': old_manager
    })

@admin_required
def admin_telecaller_toggle_status(request, pk):
    telecaller = get_object_or_404(User, pk=pk, role=UserRole.TELECALLER)
    old_status = telecaller.is_active
    telecaller.is_active = not old_status
    telecaller.save()

    status_str = "activated" if telecaller.is_active else "deactivated"
    log_activity(
        user=request.user,
        action="Telecaller Status Changed",
        description=f"Admin {status_str} Telecaller '{telecaller.username}'.",
        object_type="User",
        object_id=telecaller.pk,
        request=request
    )
    messages.success(request, f"Telecaller '{telecaller.username}' has been {status_str}.")
    return redirect('admin_telecallers_list')

@admin_required
def admin_telecaller_change_password(request, pk):
    telecaller = get_object_or_404(User, pk=pk, role=UserRole.TELECALLER)
    if request.method == 'POST':
        form = SetPasswordForm(telecaller, request.POST)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Password Reset by Admin",
                description=f"Admin reset password for Telecaller '{telecaller.username}'.",
                object_type="User",
                object_id=telecaller.pk,
                request=request
            )
            messages.success(request, f"Password for Telecaller '{telecaller.username}' has been successfully changed.")
            from activities.services import create_notification
            create_notification(
                recipient=telecaller,
                title="Password Changed",
                message="Your account password was updated by the Administrator.",
                notification_type="password_changed"
            )
            return redirect('admin_telecaller_detail', pk=telecaller.pk)
    else:
        form = SetPasswordForm(telecaller)

    return render(request, 'admin/telecaller_change_password.html', {
        'form': form,
        'telecaller': telecaller
    })

@admin_required
def admin_telecaller_delete(request, pk):
    telecaller = User.objects.filter(pk=pk, role=UserRole.TELECALLER).first()
    if not telecaller:
        messages.error(request, "Telecaller not found.")
        return redirect('admin_telecallers_list')

    if telecaller.pk == request.user.pk:
        messages.error(request, "You cannot delete your own account.")
        return redirect('admin_telecallers_list')

    if request.method == 'POST':
        with transaction.atomic():
            username = telecaller.username
            full_name = telecaller.get_full_name() or username

            # 1. Preserve existing leads: unassign telecaller, set status to Unassigned
            assigned_leads = Lead.objects.filter(assigned_telecaller=telecaller)
            affected_leads_count = assigned_leads.count()
            assigned_leads.update(
                assigned_telecaller=None,
                assignment_status='Unassigned',
                pending_assignment_reason=f"Previous telecaller '{full_name}' was deleted."
            )

            # 2. Preserve follow-ups: detach telecaller references
            FollowUp.objects.filter(telecaller=telecaller).update(telecaller=None)
            FollowUp.objects.filter(assigned_user=telecaller).update(assigned_user=None)

            # 3. Preserve calls: detach telecaller and caller references
            CallHistory.objects.filter(telecaller=telecaller).update(telecaller=None)
            CallHistory.objects.filter(caller=telecaller).update(caller=None)

            # 4. Preserve activities: detach user reference
            Activity.objects.filter(user=telecaller).update(user=None)

            # 5. Remove any LeadSetup allocation configurations
            TelecallerLeadSetup.objects.filter(telecaller=telecaller).delete()

            # 6. Audit activity log
            log_activity(
                user=request.user,
                action="Telecaller Deleted",
                description=f"Admin deleted Telecaller '{username}' ({full_name}). {affected_leads_count} lead(s) set to Unassigned.",
                object_type="User",
                object_id=str(pk),
                request=request
            )

            # 7. Delete the telecaller user account
            telecaller.delete()

        messages.success(request, "Telecaller deleted successfully.")
        return redirect('admin_telecallers_list')

    # If GET, render confirmation page fallback
    assigned_leads_count = Lead.objects.filter(assigned_telecaller=telecaller).count()
    return render(request, 'admin/telecaller_confirm_delete.html', {
        'telecaller': telecaller,
        'assigned_leads_count': assigned_leads_count
    })


# ==========================================
# TELECALLER WORKSPACE & DASHBOARD
# ==========================================

@telecaller_required
def telecaller_dashboard(request):
    telecaller = request.user
    today = timezone.now().date()

    # 1. Fresh Leads Today: assigned today or created today if assigned_at is null
    fresh_leads_qs = Lead.objects.filter(
        assigned_telecaller=telecaller
    ).filter(
        Q(assigned_at__date=today) | Q(assigned_at__isnull=True, created_at__date=today)
    )
    fresh_leads_today_count = fresh_leads_qs.count()

    # 2. Today's Follow-ups: scheduled for today, pending
    todays_followups_qs = FollowUp.objects.filter(
        Q(telecaller=telecaller) | Q(assigned_user=telecaller),
        follow_up_date=today,
        status=FollowUpStatus.PENDING
    ).select_related('lead')
    todays_followups_count = todays_followups_qs.count()

    # 3. Pending Calls Today: calls initiated/created today by caller that are not completed or cancelled, or notes pending
    pending_calls_qs = CallHistory.objects.filter(
        caller=telecaller
    ).filter(
        Q(call_started_at__date=today) | Q(created_at__date=today)
    ).filter(
        Q(notes_completed=False) | ~Q(call_status__in=[CallStatus.COMPLETED, CallStatus.CANCELLED])
    )
    pending_calls_today_count = pending_calls_qs.count()

    # 4. Leads Not Touched for 7 Days
    cutoff_7 = today - timezone.timedelta(days=7)
    touched_7_ids = CallHistory.objects.filter(
        call_started_at__date__gt=cutoff_7
    ).values_list('lead_id', flat=True)
    not_touched_7_count = Lead.objects.filter(
        assigned_telecaller=telecaller,
        created_at__date__lte=cutoff_7
    ).exclude(id__in=touched_7_ids).count()

    # 5. Leads Not Touched for 15 Days
    cutoff_15 = today - timezone.timedelta(days=15)
    touched_15_ids = CallHistory.objects.filter(
        call_started_at__date__gt=cutoff_15
    ).values_list('lead_id', flat=True)
    not_touched_15_count = Lead.objects.filter(
        assigned_telecaller=telecaller,
        created_at__date__lte=cutoff_15
    ).exclude(id__in=touched_15_ids).count()

    # 6. Call Not Picked: leads where call outcome in ['No Answer', 'Busy'] or status in ['Missed', 'Failed']
    not_picked_lead_ids = CallHistory.objects.filter(
        caller=telecaller
    ).filter(
        Q(call_outcome__in=[CallOutcome.NO_ANSWER, CallOutcome.BUSY]) |
        Q(call_status__in=[CallStatus.MISSED, CallStatus.FAILED])
    ).values_list('lead_id', flat=True)
    call_not_picked_count = Lead.objects.filter(
        assigned_telecaller=telecaller,
        id__in=not_picked_lead_ids
    ).distinct().count()

    # Real DB scoped metrics for leads table
    my_leads_qs = Lead.objects.filter(assigned_telecaller=telecaller).select_related('channel', 'product', 'branch')
    my_leads_count = my_leads_qs.count()

    search_query = request.GET.get('search', '').strip()
    if search_query:
        my_leads_qs = my_leads_qs.filter(
            Q(name__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(email__icontains=search_query)
        )
    my_leads = my_leads_qs.order_by('-id')

    todays_followups = todays_followups_qs

    pending_followups_count = FollowUp.objects.filter(
        Q(telecaller=telecaller) | Q(assigned_user=telecaller),
        status=FollowUpStatus.PENDING
    ).count()

    overdue_followups_count = FollowUp.objects.filter(
        Q(telecaller=telecaller) | Q(assigned_user=telecaller),
        status=FollowUpStatus.PENDING,
        follow_up_date__lt=today
    ).count()

    todays_calls_count = CallHistory.objects.filter(
        caller=telecaller,
        call_started_at__date=today
    ).count()

    completed_calls_count = CallHistory.objects.filter(
        caller=telecaller,
        call_status='Completed'
    ).count()

    recent_calls = CallHistory.objects.filter(
        caller=telecaller
    ).select_related('lead')[:8]

    # Lead status counts
    lead_status_counts = Lead.objects.filter(
        assigned_telecaller=telecaller
    ).values('status').annotate(total=Count('id'))
    status_dict = {item['status']: item['total'] for item in lead_status_counts}

    recent_activities = Activity.objects.filter(user=telecaller)[:8]

    return render(request, 'telecaller_dashboard/dashboard.html', {
        'my_leads': my_leads,
        'my_leads_count': my_leads_count,
        'search_query': search_query,
        'fresh_leads_today_count': fresh_leads_today_count,
        'todays_followups_count': todays_followups_count,
        'pending_calls_today_count': pending_calls_today_count,
        'not_touched_7_count': not_touched_7_count,
        'not_touched_15_count': not_touched_15_count,
        'call_not_picked_count': call_not_picked_count,
        'todays_followups': todays_followups,
        'pending_followups_count': pending_followups_count,
        'overdue_followups_count': overdue_followups_count,
        'todays_calls_count': todays_calls_count,
        'completed_calls_count': completed_calls_count,
        'recent_calls': recent_calls,
        'status_dict': status_dict,
        'recent_activities': recent_activities,
    })
