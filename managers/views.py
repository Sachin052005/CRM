from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.utils import timezone
from accounts.models import User, UserRole
from accounts.permissions import admin_required, sales_head_required, get_accessible_branch_ids
from branches.models import Branch
from leads.models import Lead, LeadStatus
from calls.models import CallHistory
from followups.models import FollowUp, FollowUpStatus
from activities.models import Activity
from activities.utils import log_activity
from branches.utils import get_admin_selected_branch
from django.contrib.auth.forms import SetPasswordForm
from .forms import AdminManagerCreateForm, AdminManagerEditForm

# ==========================================
# ADMIN: MANAGER (SALES HEAD) MANAGEMENT
# ==========================================

@admin_required
def admin_managers_list(request):
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    branch_filter = request.GET.get('branch', '').strip()

    managers_qs = User.objects.filter(role=UserRole.SALES_HEAD).select_related('branch')

    if search_query:
        managers_qs = managers_qs.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    if status_filter == 'active':
        managers_qs = managers_qs.filter(is_active=True)
    elif status_filter == 'inactive':
        managers_qs = managers_qs.filter(is_active=False)

    selected_branch = get_admin_selected_branch(request)
    if selected_branch:
        managers_qs = managers_qs.filter(branch_access__branch=selected_branch)
    elif branch_filter:
        managers_qs = managers_qs.filter(branch_access__branch_id=branch_filter)

    managers_qs = managers_qs.annotate(
        telecaller_count=Count(
            'branch_access__branch__users',
            filter=Q(branch_access__branch__users__role=UserRole.TELECALLER),
            distinct=True
        ),
        lead_count=Count('manager_leads', distinct=True)
    ).order_by('-date_joined').distinct()

    paginator = Paginator(managers_qs, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    branches = Branch.objects.filter(status='Active')

    return render(request, 'admin/managers_list.html', {
        'page_obj': page_obj,
        'branches': branches,
        'search_query': search_query,
        'status_filter': status_filter,
        'branch_filter': branch_filter,
    })

@admin_required
def admin_manager_create(request):
    if request.method == 'POST':
        form = AdminManagerCreateForm(request.POST)
        if form.is_valid():
            manager = form.save(created_by=request.user)
            log_activity(
                user=request.user,
                action="Manager Created",
                description=f"Admin created Manager account '{manager.username}' ({manager.email}).",
                object_type="User",
                object_id=manager.pk,
                request=request
            )
            messages.success(request, f"Manager '{manager.username}' was successfully created.")
            return redirect('admin_managers_list')
    else:
        form = AdminManagerCreateForm()

    return render(request, 'admin/manager_create.html', {'form': form})

@admin_required
def admin_manager_detail(request, pk):
    manager = get_object_or_404(User.objects.select_related('branch'), pk=pk, role=UserRole.SALES_HEAD)
    branch_ids = get_accessible_branch_ids(manager)

    telecallers = User.objects.filter(role=UserRole.TELECALLER, branch_id__in=branch_ids).annotate(
        lead_count=Count('telecaller_leads', distinct=True),
        call_count=Count('telecaller_calls', distinct=True),
        followup_count=Count('telecaller_followups', distinct=True)
    )

    total_leads = Lead.objects.filter(Q(assigned_sales_head=manager) | Q(assigned_telecaller__branch_id__in=branch_ids)).count()
    total_calls = CallHistory.objects.filter(Q(manager=manager) | Q(telecaller__branch_id__in=branch_ids)).count()
    pending_followups = FollowUp.objects.filter(
        Q(manager=manager) | Q(telecaller__branch_id__in=branch_ids),
        status=FollowUpStatus.PENDING
    ).count()
    completed_followups = FollowUp.objects.filter(
        Q(manager=manager) | Q(telecaller__branch_id__in=branch_ids),
        status=FollowUpStatus.COMPLETED
    ).count()

    recent_activities = Activity.objects.filter(user=manager)[:10]
    recent_calls = CallHistory.objects.filter(
        Q(manager=manager) | Q(telecaller__branch_id__in=branch_ids)
    ).select_related('lead', 'caller')[:10]

    return render(request, 'admin/manager_detail.html', {
        'manager': manager,
        'telecallers': telecallers,
        'total_leads': total_leads,
        'total_calls': total_calls,
        'pending_followups': pending_followups,
        'completed_followups': completed_followups,
        'recent_activities': recent_activities,
        'recent_calls': recent_calls,
    })

@admin_required
def admin_manager_edit(request, pk):
    manager = get_object_or_404(User, pk=pk, role=UserRole.SALES_HEAD)
    if request.method == 'POST':
        form = AdminManagerEditForm(request.POST, instance=manager)
        if form.is_valid():
            form.save(created_by=request.user)
            log_activity(
                user=request.user,
                action="Manager Updated",
                description=f"Admin updated Manager profile for '{manager.username}'.",
                object_type="User",
                object_id=manager.pk,
                request=request
            )
            messages.success(request, f"Manager '{manager.username}' profile updated.")
            return redirect('admin_manager_detail', pk=manager.pk)
    else:
        form = AdminManagerEditForm(instance=manager)
        form.initial['branches'] = list(manager.branch_access.values_list('branch_id', flat=True))

    return render(request, 'admin/manager_edit.html', {'form': form, 'manager': manager})

@admin_required
def admin_manager_toggle_status(request, pk):
    manager = get_object_or_404(User, pk=pk, role=UserRole.SALES_HEAD)
    old_status = manager.is_active
    manager.is_active = not old_status
    manager.save()

    status_str = "activated" if manager.is_active else "deactivated"
    log_activity(
        user=request.user,
        action="Manager Status Changed",
        description=f"Admin {status_str} Manager '{manager.username}'.",
        object_type="User",
        object_id=manager.pk,
        request=request
    )
    messages.success(request, f"Manager '{manager.username}' has been {status_str}.")
    return redirect('admin_managers_list')

@admin_required
def admin_manager_change_password(request, pk):
    manager = get_object_or_404(User, pk=pk, role=UserRole.SALES_HEAD)
    if request.method == 'POST':
        form = SetPasswordForm(manager, request.POST)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Password Reset by Admin",
                description=f"Admin reset password for Manager '{manager.username}'.",
                object_type="User",
                object_id=manager.pk,
                request=request
            )
            messages.success(request, f"Password for Manager '{manager.username}' has been successfully changed.")
            from activities.services import create_notification
            create_notification(
                recipient=manager,
                title="Password Changed",
                message="Your account password was updated by the Administrator.",
                notification_type="password_changed"
            )
            return redirect('admin_manager_detail', pk=manager.pk)
    else:
        form = SetPasswordForm(manager)

    return render(request, 'admin/manager_change_password.html', {
        'form': form,
        'manager': manager
    })


# ==========================================
# MANAGER (SALES HEAD) PORTAL (SCOPED TO LOGGED-IN SALES HEAD)
# ==========================================

@sales_head_required
def manager_dashboard(request):
    manager = request.user
    today = timezone.now().date()
    branch_ids = get_accessible_branch_ids(manager)
    my_branches = Branch.objects.filter(id__in=branch_ids)

    # Telecallers within this Sales Head's accessible branches
    telecallers = User.objects.filter(role=UserRole.TELECALLER, branch_id__in=branch_ids)
    telecaller_ids = list(telecallers.values_list('id', flat=True))

    # Real database metrics scoped to Sales Head
    my_leads_count = Lead.objects.filter(
        Q(assigned_sales_head=manager) | Q(assigned_telecaller_id__in=telecaller_ids)
    ).count()
    my_telecallers_count = telecallers.count()

    todays_calls_count = CallHistory.objects.filter(
        Q(manager=manager) | Q(telecaller_id__in=telecaller_ids),
        call_started_at__date=today
    ).count()

    completed_calls_count = CallHistory.objects.filter(
        Q(manager=manager) | Q(telecaller_id__in=telecaller_ids),
        call_status='Completed'
    ).count()

    pending_followups_count = FollowUp.objects.filter(
        Q(manager=manager) | Q(telecaller_id__in=telecaller_ids),
        status=FollowUpStatus.PENDING
    ).count()

    overdue_followups_count = FollowUp.objects.filter(
        Q(manager=manager) | Q(telecaller_id__in=telecaller_ids),
        status=FollowUpStatus.PENDING,
        follow_up_date__lt=today
    ).count()

    # Telecaller performance table
    telecaller_perf = telecallers.annotate(
        lead_count=Count('telecaller_leads', distinct=True),
        call_count=Count('telecaller_calls', distinct=True),
        followup_count=Count('telecaller_followups', distinct=True),
        completed_calls=Count('telecaller_calls', filter=Q(telecaller_calls__call_status='Completed'), distinct=True)
    )

    # Lead status distribution for chart
    status_counts = Lead.objects.filter(
        Q(assigned_sales_head=manager) | Q(assigned_telecaller_id__in=telecaller_ids)
    ).values('status').annotate(total=Count('id'))

    status_dict = {item['status']: item['total'] for item in status_counts}

    recent_calls = CallHistory.objects.filter(
        Q(manager=manager) | Q(telecaller_id__in=telecaller_ids)
    ).select_related('lead', 'caller', 'telecaller')[:8]

    recent_activities = Activity.objects.filter(
        Q(user=manager) | Q(user_id__in=telecaller_ids)
    ).select_related('user')[:8]

    return render(request, 'manager_dashboard/dashboard.html', {
        'my_branches': my_branches,
        'my_leads_count': my_leads_count,
        'my_telecallers_count': my_telecallers_count,
        'todays_calls_count': todays_calls_count,
        'completed_calls_count': completed_calls_count,
        'pending_followups_count': pending_followups_count,
        'overdue_followups_count': overdue_followups_count,
        'telecaller_perf': telecaller_perf,
        'status_dict': status_dict,
        'recent_calls': recent_calls,
        'recent_activities': recent_activities,
    })

@sales_head_required
def manager_telecallers_list(request):
    manager = request.user
    branch_ids = get_accessible_branch_ids(manager)
    telecallers = User.objects.filter(role=UserRole.TELECALLER, branch_id__in=branch_ids).annotate(
        lead_count=Count('telecaller_leads', distinct=True),
        call_count=Count('telecaller_calls', distinct=True),
        followup_count=Count('telecaller_followups', distinct=True)
    ).order_by('-date_joined')

    return render(request, 'manager/telecallers_list.html', {
        'telecallers': telecallers
    })

@sales_head_required
def manager_telecaller_detail(request, pk):
    manager = request.user
    branch_ids = get_accessible_branch_ids(manager)
    # Ensure telecaller strictly belongs to an accessible branch
    telecaller = get_object_or_404(User, pk=pk, role=UserRole.TELECALLER, branch_id__in=branch_ids)

    leads = Lead.objects.filter(assigned_telecaller=telecaller).select_related('channel', 'product')[:15]
    calls = CallHistory.objects.filter(caller=telecaller).select_related('lead')[:15]
    followups = FollowUp.objects.filter(telecaller=telecaller).select_related('lead')[:15]
    activities = Activity.objects.filter(user=telecaller)[:15]

    total_leads = Lead.objects.filter(assigned_telecaller=telecaller).count()
    total_calls = CallHistory.objects.filter(caller=telecaller).count()
    completed_calls = CallHistory.objects.filter(caller=telecaller, call_status='Completed').count()
    pending_followups = FollowUp.objects.filter(telecaller=telecaller, status=FollowUpStatus.PENDING).count()
    completed_followups = FollowUp.objects.filter(telecaller=telecaller, status=FollowUpStatus.COMPLETED).count()

    return render(request, 'manager/telecaller_detail.html', {
        'telecaller': telecaller,
        'leads': leads,
        'calls': calls,
        'followups': followups,
        'activities': activities,
        'total_leads': total_leads,
        'total_calls': total_calls,
        'completed_calls': completed_calls,
        'pending_followups': pending_followups,
        'completed_followups': completed_followups,
    })
