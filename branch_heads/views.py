from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.forms import SetPasswordForm
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, Q

from accounts.models import User, UserRole
from accounts.permissions import (
    admin_required, sales_head_required, branch_head_required, get_accessible_branch_ids,
    can_create_user, can_manage_user,
)
from branches.models import Branch
from leads.models import Lead, LeadStatus
from calls.models import CallHistory
from followups.models import FollowUp, FollowUpStatus
from activities.models import Activity
from activities.utils import log_activity
from .forms import (
    BranchHeadCreateForm, BranchHeadEditForm,
    BranchHeadCounselorCreateForm, BranchHeadCounselorEditForm,
)


def _branch_head_context(branch_head):
    counselors = User.objects.filter(role=UserRole.COUNSELOR, branch_id=branch_head.branch_id)
    telecallers = User.objects.filter(role=UserRole.TELECALLER, branch_id=branch_head.branch_id)
    total_leads = Lead.objects.filter(branch_id=branch_head.branch_id).count()
    total_calls = CallHistory.objects.filter(telecaller__branch_id=branch_head.branch_id).count()
    pending_followups = FollowUp.objects.filter(
        telecaller__branch_id=branch_head.branch_id, status=FollowUpStatus.PENDING
    ).count()
    recent_activities = Activity.objects.filter(user=branch_head)[:10]
    recent_calls = CallHistory.objects.filter(
        telecaller__branch_id=branch_head.branch_id
    ).select_related('lead', 'caller')[:10]
    return {
        'branch_head': branch_head,
        'counselors': counselors,
        'telecallers': telecallers,
        'total_leads': total_leads,
        'total_calls': total_calls,
        'pending_followups': pending_followups,
        'recent_activities': recent_activities,
        'recent_calls': recent_calls,
    }


def _list_queryset(branch_ids, search_query, status_filter, branch_filter):
    qs = User.objects.filter(role=UserRole.BRANCH_HEAD, branch_id__in=branch_ids).select_related('branch')

    if search_query:
        qs = qs.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    if status_filter == 'active':
        qs = qs.filter(is_active=True)
    elif status_filter == 'inactive':
        qs = qs.filter(is_active=False)
    if branch_filter:
        qs = qs.filter(branch_id=branch_filter)

    qs = qs.annotate(
        counselor_count=Count(
            'branch__users', filter=Q(branch__users__role=UserRole.COUNSELOR), distinct=True
        ),
        telecaller_count=Count(
            'branch__users', filter=Q(branch__users__role=UserRole.TELECALLER), distinct=True
        ),
        lead_count=Count('branch_head_leads', distinct=True),
    ).order_by('-date_joined')
    return qs


# ==========================================
# ADMIN: BRANCH HEAD MANAGEMENT (ALL BRANCHES)
# ==========================================

@admin_required
def admin_branch_heads_list(request):
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    branch_filter = request.GET.get('branch', '').strip()

    all_branch_ids = Branch.objects.values_list('id', flat=True)
    branch_heads_qs = _list_queryset(all_branch_ids, search_query, status_filter, branch_filter)

    paginator = Paginator(branch_heads_qs, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'admin/branch_heads_list.html', {
        'page_obj': page_obj,
        'branches': Branch.objects.filter(status='Active'),
        'search_query': search_query,
        'status_filter': status_filter,
        'branch_filter': branch_filter,
    })


@admin_required
def admin_branch_head_create(request):
    allowed_branches = Branch.objects.filter(status='Active')
    if request.method == 'POST':
        form = BranchHeadCreateForm(request.POST, allowed_branches=allowed_branches)
        if form.is_valid():
            if not can_create_user(request.user, UserRole.BRANCH_HEAD, form.cleaned_data['branch']):
                raise PermissionDenied("You do not have permission to create a Branch Head for this branch.")
            branch_head = form.save()
            log_activity(
                user=request.user,
                action="Branch Head Created",
                description=f"Admin created Branch Head account '{branch_head.username}' for branch '{branch_head.branch.name}'.",
                object_type="User",
                object_id=branch_head.pk,
                request=request
            )
            messages.success(request, f"Branch Head '{branch_head.username}' was successfully created.")
            return redirect('admin_branch_heads_list')
    else:
        form = BranchHeadCreateForm(allowed_branches=allowed_branches)

    return render(request, 'admin/branch_head_create.html', {'form': form})


@admin_required
def admin_branch_head_detail(request, pk):
    branch_head = get_object_or_404(User.objects.select_related('branch'), pk=pk, role=UserRole.BRANCH_HEAD)
    return render(request, 'admin/branch_head_detail.html', _branch_head_context(branch_head))


@admin_required
def admin_branch_head_edit(request, pk):
    branch_head = get_object_or_404(User, pk=pk, role=UserRole.BRANCH_HEAD)
    allowed_branches = Branch.objects.filter(status='Active')
    if request.method == 'POST':
        form = BranchHeadEditForm(request.POST, instance=branch_head, allowed_branches=allowed_branches)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Branch Head Updated",
                description=f"Admin updated Branch Head profile for '{branch_head.username}'.",
                object_type="User",
                object_id=branch_head.pk,
                request=request
            )
            messages.success(request, f"Branch Head '{branch_head.username}' profile updated.")
            return redirect('admin_branch_head_detail', pk=branch_head.pk)
    else:
        form = BranchHeadEditForm(instance=branch_head, allowed_branches=allowed_branches)

    return render(request, 'admin/branch_head_edit.html', {'form': form, 'branch_head': branch_head})


@admin_required
def admin_branch_head_toggle_status(request, pk):
    branch_head = get_object_or_404(User, pk=pk, role=UserRole.BRANCH_HEAD)
    branch_head.is_active = not branch_head.is_active
    branch_head.save()
    status_str = "activated" if branch_head.is_active else "deactivated"
    log_activity(
        user=request.user,
        action="Branch Head Status Changed",
        description=f"Admin {status_str} Branch Head '{branch_head.username}'.",
        object_type="User",
        object_id=branch_head.pk,
        request=request
    )
    messages.success(request, f"Branch Head '{branch_head.username}' has been {status_str}.")
    return redirect('admin_branch_heads_list')


@admin_required
def admin_branch_head_change_password(request, pk):
    branch_head = get_object_or_404(User, pk=pk, role=UserRole.BRANCH_HEAD)
    if request.method == 'POST':
        form = SetPasswordForm(branch_head, request.POST)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Password Reset by Admin",
                description=f"Admin reset password for Branch Head '{branch_head.username}'.",
                object_type="User",
                object_id=branch_head.pk,
                request=request
            )
            messages.success(request, f"Password for Branch Head '{branch_head.username}' has been successfully changed.")
            from activities.services import create_notification
            create_notification(
                recipient=branch_head,
                title="Password Changed",
                message="Your account password was updated by the Administrator.",
                notification_type="password_changed"
            )
            return redirect('admin_branch_head_detail', pk=branch_head.pk)
    else:
        form = SetPasswordForm(branch_head)

    return render(request, 'admin/branch_head_change_password.html', {
        'form': form,
        'branch_head': branch_head,
    })


# ==========================================
# SALES HEAD: BRANCH HEAD MANAGEMENT (ACCESSIBLE BRANCHES ONLY)
# ==========================================

@sales_head_required
def sales_head_branch_heads_list(request):
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    branch_filter = request.GET.get('branch', '').strip()

    branch_ids = get_accessible_branch_ids(request.user)
    branch_heads_qs = _list_queryset(branch_ids, search_query, status_filter, branch_filter)

    paginator = Paginator(branch_heads_qs, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'manager/branch_heads_list.html', {
        'page_obj': page_obj,
        'branches': Branch.objects.filter(id__in=branch_ids),
        'search_query': search_query,
        'status_filter': status_filter,
        'branch_filter': branch_filter,
    })


@sales_head_required
def sales_head_branch_head_create(request):
    allowed_branches = Branch.objects.filter(id__in=get_accessible_branch_ids(request.user), status='Active')
    if request.method == 'POST':
        form = BranchHeadCreateForm(request.POST, allowed_branches=allowed_branches)
        if form.is_valid():
            if not can_create_user(request.user, UserRole.BRANCH_HEAD, form.cleaned_data['branch']):
                raise PermissionDenied("You do not have permission to create a Branch Head for this branch.")
            branch_head = form.save()
            log_activity(
                user=request.user,
                action="Branch Head Created",
                description=f"Sales Head created Branch Head account '{branch_head.username}' for branch '{branch_head.branch.name}'.",
                object_type="User",
                object_id=branch_head.pk,
                request=request
            )
            messages.success(request, f"Branch Head '{branch_head.username}' was successfully created.")
            return redirect('sales_head_branch_heads_list')
    else:
        form = BranchHeadCreateForm(allowed_branches=allowed_branches)

    return render(request, 'manager/branch_head_create.html', {'form': form})


@sales_head_required
def sales_head_branch_head_detail(request, pk):
    branch_head = get_object_or_404(
        User.objects.select_related('branch'),
        pk=pk, role=UserRole.BRANCH_HEAD, branch_id__in=get_accessible_branch_ids(request.user)
    )
    if not can_manage_user(request.user, branch_head):
        raise PermissionDenied("You do not have permission to view this Branch Head.")
    return render(request, 'manager/branch_head_detail.html', _branch_head_context(branch_head))


@sales_head_required
def sales_head_branch_head_edit(request, pk):
    branch_ids = get_accessible_branch_ids(request.user)
    branch_head = get_object_or_404(User, pk=pk, role=UserRole.BRANCH_HEAD, branch_id__in=branch_ids)
    if not can_manage_user(request.user, branch_head):
        raise PermissionDenied("You do not have permission to edit this Branch Head.")

    allowed_branches = Branch.objects.filter(id__in=branch_ids, status='Active')
    if request.method == 'POST':
        form = BranchHeadEditForm(request.POST, instance=branch_head, allowed_branches=allowed_branches)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Branch Head Updated",
                description=f"Sales Head updated Branch Head profile for '{branch_head.username}'.",
                object_type="User",
                object_id=branch_head.pk,
                request=request
            )
            messages.success(request, f"Branch Head '{branch_head.username}' profile updated.")
            return redirect('sales_head_branch_head_detail', pk=branch_head.pk)
    else:
        form = BranchHeadEditForm(instance=branch_head, allowed_branches=allowed_branches)

    return render(request, 'manager/branch_head_edit.html', {'form': form, 'branch_head': branch_head})


@sales_head_required
def sales_head_branch_head_toggle_status(request, pk):
    branch_ids = get_accessible_branch_ids(request.user)
    branch_head = get_object_or_404(User, pk=pk, role=UserRole.BRANCH_HEAD, branch_id__in=branch_ids)
    if not can_manage_user(request.user, branch_head):
        raise PermissionDenied("You do not have permission to manage this Branch Head.")

    branch_head.is_active = not branch_head.is_active
    branch_head.save()
    status_str = "activated" if branch_head.is_active else "deactivated"
    log_activity(
        user=request.user,
        action="Branch Head Status Changed",
        description=f"Sales Head {status_str} Branch Head '{branch_head.username}'.",
        object_type="User",
        object_id=branch_head.pk,
        request=request
    )
    messages.success(request, f"Branch Head '{branch_head.username}' has been {status_str}.")
    return redirect('sales_head_branch_heads_list')


@sales_head_required
def sales_head_branch_head_change_password(request, pk):
    branch_ids = get_accessible_branch_ids(request.user)
    branch_head = get_object_or_404(User, pk=pk, role=UserRole.BRANCH_HEAD, branch_id__in=branch_ids)
    if not can_manage_user(request.user, branch_head):
        raise PermissionDenied("You do not have permission to manage this Branch Head.")

    if request.method == 'POST':
        form = SetPasswordForm(branch_head, request.POST)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Password Reset by Sales Head",
                description=f"Sales Head reset password for Branch Head '{branch_head.username}'.",
                object_type="User",
                object_id=branch_head.pk,
                request=request
            )
            messages.success(request, f"Password for Branch Head '{branch_head.username}' has been successfully changed.")
            from activities.services import create_notification
            create_notification(
                recipient=branch_head,
                title="Password Changed",
                message="Your account password was updated by your Sales Head.",
                notification_type="password_changed"
            )
            return redirect('sales_head_branch_head_detail', pk=branch_head.pk)
    else:
        form = SetPasswordForm(branch_head)

    return render(request, 'manager/branch_head_change_password.html', {
        'form': form,
        'branch_head': branch_head,
    })


# ==========================================
# BRANCH HEAD: OWN PORTAL (SCOPED TO OWN BRANCH)
# ==========================================

@branch_head_required
def branch_head_dashboard(request):
    branch_head = request.user
    branch_id = branch_head.branch_id

    counselors = User.objects.filter(role=UserRole.COUNSELOR, branch_id=branch_id)
    telecallers = User.objects.filter(role=UserRole.TELECALLER, branch_id=branch_id)

    leads_qs = Lead.objects.filter(branch_id=branch_id)
    branch_leads_count = leads_qs.count()
    visits_count = leads_qs.filter(status__in=[LeadStatus.VISIT_SCHEDULED, LeadStatus.VISITED]).count()
    joined_count = leads_qs.filter(status=LeadStatus.JOINED).count()

    pending_followups_count = FollowUp.objects.filter(
        telecaller__branch_id=branch_id, status=FollowUpStatus.PENDING
    ).count()

    counselor_perf = counselors.annotate(
        lead_count=Count('counselor_leads', distinct=True),
        joined_count=Count('counselor_leads', filter=Q(counselor_leads__status=LeadStatus.JOINED), distinct=True),
    )
    telecaller_perf = telecallers.annotate(
        lead_count=Count('telecaller_leads', distinct=True),
        call_count=Count('telecaller_calls', distinct=True),
        followup_count=Count('telecaller_followups', distinct=True),
    )

    status_counts = leads_qs.values('status').annotate(total=Count('id'))
    status_dict = {item['status']: item['total'] for item in status_counts}

    recent_activities = Activity.objects.filter(
        Q(user=branch_head) | Q(user__branch_id=branch_id)
    ).select_related('user')[:8]

    return render(request, 'branch_head_dashboard/dashboard.html', {
        'branch_leads_count': branch_leads_count,
        'counselors_count': counselors.count(),
        'telecallers_count': telecallers.count(),
        'pending_followups_count': pending_followups_count,
        'visits_count': visits_count,
        'joined_count': joined_count,
        'counselor_perf': counselor_perf,
        'telecaller_perf': telecaller_perf,
        'status_dict': status_dict,
        'recent_activities': recent_activities,
    })


def _counselor_context(counselor):
    telecallers = User.objects.filter(role=UserRole.TELECALLER, counselor=counselor)
    leads = Lead.objects.filter(assigned_counselor=counselor)
    return {
        'counselor': counselor,
        'telecallers': telecallers,
        'total_leads': leads.count(),
        'joined_count': leads.filter(status=LeadStatus.JOINED).count(),
        'recent_activities': Activity.objects.filter(user=counselor)[:10],
    }


def _counselor_list_queryset(branch_id, search_query, status_filter):
    qs = User.objects.filter(role=UserRole.COUNSELOR, branch_id=branch_id)
    if search_query:
        qs = qs.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    if status_filter == 'active':
        qs = qs.filter(is_active=True)
    elif status_filter == 'inactive':
        qs = qs.filter(is_active=False)
    return qs.annotate(
        telecaller_count=Count('assigned_telecallers', distinct=True),
        lead_count=Count('counselor_leads', distinct=True),
    ).order_by('-date_joined')


@branch_head_required
def branch_head_counselors_list(request):
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()

    counselors_qs = _counselor_list_queryset(request.user.branch_id, search_query, status_filter)
    paginator = Paginator(counselors_qs, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'branch_head/counselors_list.html', {
        'page_obj': page_obj,
        'search_query': search_query,
        'status_filter': status_filter,
    })


@branch_head_required
def branch_head_counselor_create(request):
    branch_head = request.user
    if request.method == 'POST':
        form = BranchHeadCounselorCreateForm(request.POST)
        if form.is_valid():
            if not can_create_user(branch_head, UserRole.COUNSELOR, branch_head.branch):
                raise PermissionDenied("You do not have permission to create a Counselor for this branch.")
            counselor = form.save(branch=branch_head.branch)
            log_activity(
                user=branch_head,
                action="Counselor Created",
                description=f"Branch Head created Counselor account '{counselor.username}' for branch '{branch_head.branch.name}'.",
                object_type="User",
                object_id=counselor.pk,
                request=request
            )
            messages.success(request, f"Counselor '{counselor.username}' was successfully created.")
            return redirect('branch_head_counselors_list')
    else:
        form = BranchHeadCounselorCreateForm()

    return render(request, 'branch_head/counselor_create.html', {'form': form})


@branch_head_required
def branch_head_counselor_detail(request, pk):
    counselor = get_object_or_404(User, pk=pk, role=UserRole.COUNSELOR, branch_id=request.user.branch_id)
    if not can_manage_user(request.user, counselor):
        raise PermissionDenied("You do not have permission to view this Counselor.")
    return render(request, 'branch_head/counselor_detail.html', _counselor_context(counselor))


@branch_head_required
def branch_head_counselor_edit(request, pk):
    counselor = get_object_or_404(User, pk=pk, role=UserRole.COUNSELOR, branch_id=request.user.branch_id)
    if not can_manage_user(request.user, counselor):
        raise PermissionDenied("You do not have permission to edit this Counselor.")

    if request.method == 'POST':
        form = BranchHeadCounselorEditForm(request.POST, instance=counselor)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Counselor Updated",
                description=f"Branch Head updated Counselor profile for '{counselor.username}'.",
                object_type="User",
                object_id=counselor.pk,
                request=request
            )
            messages.success(request, f"Counselor '{counselor.username}' profile updated.")
            return redirect('branch_head_counselor_detail', pk=counselor.pk)
    else:
        form = BranchHeadCounselorEditForm(instance=counselor)

    return render(request, 'branch_head/counselor_edit.html', {'form': form, 'counselor': counselor})


@branch_head_required
def branch_head_counselor_toggle_status(request, pk):
    counselor = get_object_or_404(User, pk=pk, role=UserRole.COUNSELOR, branch_id=request.user.branch_id)
    if not can_manage_user(request.user, counselor):
        raise PermissionDenied("You do not have permission to manage this Counselor.")

    counselor.is_active = not counselor.is_active
    counselor.save()
    status_str = "activated" if counselor.is_active else "deactivated"
    log_activity(
        user=request.user,
        action="Counselor Status Changed",
        description=f"Branch Head {status_str} Counselor '{counselor.username}'.",
        object_type="User",
        object_id=counselor.pk,
        request=request
    )
    messages.success(request, f"Counselor '{counselor.username}' has been {status_str}.")
    return redirect('branch_head_counselors_list')


@branch_head_required
def branch_head_counselor_change_password(request, pk):
    counselor = get_object_or_404(User, pk=pk, role=UserRole.COUNSELOR, branch_id=request.user.branch_id)
    if not can_manage_user(request.user, counselor):
        raise PermissionDenied("You do not have permission to manage this Counselor.")

    if request.method == 'POST':
        form = SetPasswordForm(counselor, request.POST)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Password Reset by Branch Head",
                description=f"Branch Head reset password for Counselor '{counselor.username}'.",
                object_type="User",
                object_id=counselor.pk,
                request=request
            )
            messages.success(request, f"Password for Counselor '{counselor.username}' has been successfully changed.")
            from activities.services import create_notification
            create_notification(
                recipient=counselor,
                title="Password Changed",
                message="Your account password was updated by your Branch Head.",
                notification_type="password_changed"
            )
            return redirect('branch_head_counselor_detail', pk=counselor.pk)
    else:
        form = SetPasswordForm(counselor)

    return render(request, 'branch_head/counselor_change_password.html', {
        'form': form,
        'counselor': counselor,
    })


@branch_head_required
def branch_head_telecallers_list(request):
    branch_id = request.user.branch_id
    telecallers = User.objects.filter(role=UserRole.TELECALLER, branch_id=branch_id).select_related('counselor').annotate(
        lead_count=Count('telecaller_leads', distinct=True),
        call_count=Count('telecaller_calls', distinct=True),
        followup_count=Count('telecaller_followups', distinct=True),
    ).order_by('-date_joined')

    return render(request, 'branch_head/telecallers_list.html', {
        'telecallers': telecallers
    })
