from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.forms import SetPasswordForm
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.utils import timezone

from accounts.models import User, UserRole
from accounts.permissions import admin_required, counselor_required
from branches.models import Branch
from leads.models import Lead, LeadStatus
from leads.handoff_service import reassign_lead, unassign_lead
from followups.models import FollowUp, FollowUpStatus
from calls.models import CallHistory
from activities.models import Activity
from activities.utils import log_activity
from branch_heads.views import _counselor_context
from .forms import AdminCounselorCreateForm


# ==========================================
# COUNSELOR: OWN PORTAL
# ==========================================

@counselor_required
def counselor_dashboard(request):
    counselor = request.user

    my_leads = Lead.objects.filter(assigned_counselor=counselor)
    my_leads_count = my_leads.count()
    visits_count = my_leads.filter(status=LeadStatus.VISITED).count()
    counseling_count = my_leads.filter(status=LeadStatus.COUNSELING).count()
    joined_count = my_leads.filter(status=LeadStatus.JOINED).count()

    pending_followups_count = FollowUp.objects.filter(
        lead__assigned_counselor=counselor, status=FollowUpStatus.PENDING
    ).count()

    status_counts = my_leads.values('status').annotate(total=Count('id'))
    status_dict = {item['status']: item['total'] for item in status_counts}

    telecallers = User.objects.filter(role=UserRole.TELECALLER, counselor=counselor)

    recent_activities = Activity.objects.filter(user=counselor).select_related('user')[:8]
    recent_leads = my_leads.select_related('channel', 'product', 'branch').order_by('-updated_at')[:8]

    return render(request, 'counselor_dashboard/dashboard.html', {
        'my_leads_count': my_leads_count,
        'visits_count': visits_count,
        'counseling_count': counseling_count,
        'joined_count': joined_count,
        'pending_followups_count': pending_followups_count,
        'status_dict': status_dict,
        'telecallers_count': telecallers.count(),
        'recent_activities': recent_activities,
        'recent_leads': recent_leads,
    })


@counselor_required
def counselor_telecallers_list(request):
    counselor = request.user
    telecallers = User.objects.filter(role=UserRole.TELECALLER, counselor=counselor).annotate(
        lead_count=Count('telecaller_leads', distinct=True),
        call_count=Count('telecaller_calls', distinct=True),
        followup_count=Count('telecaller_followups', distinct=True)
    ).order_by('-date_joined')

    return render(request, 'counselor/telecallers_list.html', {
        'telecallers': telecallers
    })


@counselor_required
def counselor_telecaller_leads(request, pk):
    """
    Leads assigned to one of the logged-in Counselor's own Telecallers (hierarchy level 5).
    Scoped server-side to telecaller.counselor == request.user - a Counselor cannot reach
    another Counselor's Telecaller by editing the URL's pk.
    """
    counselor = request.user
    telecaller = get_object_or_404(User, pk=pk, role=UserRole.TELECALLER, counselor=counselor)

    leads = Lead.objects.filter(assigned_telecaller=telecaller).select_related(
        'channel', 'product', 'branch'
    ).order_by('-updated_at')

    other_telecallers = User.objects.filter(
        role=UserRole.TELECALLER, counselor=counselor, is_active=True
    ).exclude(pk=telecaller.pk)

    return render(request, 'counselor/telecaller_leads.html', {
        'telecaller': telecaller,
        'leads': leads,
        'other_telecallers': other_telecallers,
    })


@counselor_required
def counselor_lead_reassign(request, lead_pk):
    """
    Reassigns a lead from one of the Counselor's own Telecallers to another. The target
    Telecaller must exist, be active, and belong to this same Counselor - validated here
    server-side (not just filtered out of the dropdown) before delegating to the shared
    reassign_lead service, so the business rule can't be bypassed by posting an arbitrary id.
    """
    counselor = request.user
    lead = get_object_or_404(Lead, pk=lead_pk)

    if not lead.assigned_telecaller_id or lead.assigned_telecaller.counselor_id != counselor.id:
        raise PermissionDenied("This lead is not under one of your Telecallers.")

    current_telecaller_pk = lead.assigned_telecaller_id

    if request.method == 'POST':
        target_id = request.POST.get('telecaller_id', '').strip()
        target = User.objects.filter(
            pk=target_id, role=UserRole.TELECALLER, counselor=counselor, is_active=True
        ).first() if target_id.isdigit() else None

        if not target:
            messages.error(request, "Select a valid, active Telecaller under your supervision.")
            return redirect('counselor_telecaller_leads', pk=current_telecaller_pk)

        reassign_lead(
            lead, to_user=target, to_role='TELECALLER',
            reason='Reassigned by Counselor', assigned_by=counselor
        )
        log_activity(
            user=counselor,
            action="Lead Reassigned",
            description=f"Counselor reassigned lead '{lead.name}' from Telecaller to '{target.get_full_name() or target.username}'.",
            object_type="Lead",
            object_id=lead.pk,
            request=request
        )
        messages.success(request, f"Lead '{lead.name}' reassigned to '{target.get_full_name() or target.username}'.")
        return redirect('counselor_telecaller_leads', pk=target.pk)

    return redirect('counselor_telecaller_leads', pk=current_telecaller_pk)


@counselor_required
def counselor_lead_unassign(request, lead_pk):
    """
    Unassigns a lead from one of the Counselor's own Telecallers. The lead itself, its branch,
    channel/source and duplicate history are preserved - only the Telecaller assignment is
    cleared via the shared unassign_lead service.
    """
    counselor = request.user
    lead = get_object_or_404(Lead, pk=lead_pk)

    if not lead.assigned_telecaller_id or lead.assigned_telecaller.counselor_id != counselor.id:
        raise PermissionDenied("This lead is not under one of your Telecallers.")

    current_telecaller_pk = lead.assigned_telecaller_id

    if request.method == 'POST':
        unassign_lead(lead, unassigned_by=counselor, reason='Unassigned by Counselor')
        log_activity(
            user=counselor,
            action="Lead Unassigned",
            description=f"Counselor unassigned lead '{lead.name}' from its Telecaller.",
            object_type="Lead",
            object_id=lead.pk,
            request=request
        )
        messages.success(request, f"Lead '{lead.name}' has been unassigned and is pending reassignment.")
        return redirect('counselor_telecaller_leads', pk=current_telecaller_pk)

    return redirect('counselor_telecaller_leads', pk=current_telecaller_pk)


# ==========================================
# ADMIN: COUNSELOR OVERSIGHT (ALL BRANCHES)
# ==========================================

@admin_required
def admin_counselors_list(request):
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    branch_filter = request.GET.get('branch', '').strip()

    counselors_qs = User.objects.filter(role=UserRole.COUNSELOR).select_related('branch')

    if search_query:
        counselors_qs = counselors_qs.filter(
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(phone__icontains=search_query)
        )
    if status_filter == 'active':
        counselors_qs = counselors_qs.filter(is_active=True)
    elif status_filter == 'inactive':
        counselors_qs = counselors_qs.filter(is_active=False)
    if branch_filter:
        counselors_qs = counselors_qs.filter(branch_id=branch_filter)

    counselors_qs = counselors_qs.annotate(
        telecaller_count=Count('assigned_telecallers', distinct=True),
        lead_count=Count('counselor_leads', distinct=True),
    ).order_by('-date_joined')

    paginator = Paginator(counselors_qs, 12)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'admin/counselors_list.html', {
        'page_obj': page_obj,
        'branches': Branch.objects.filter(status='Active'),
        'search_query': search_query,
        'status_filter': status_filter,
        'branch_filter': branch_filter,
    })


@admin_required
def admin_counselor_create(request):
    allowed_branches = Branch.objects.filter(status='Active')
    if request.method == 'POST':
        form = AdminCounselorCreateForm(request.POST, allowed_branches=allowed_branches)
        if form.is_valid():
            counselor = form.save()
            log_activity(
                user=request.user,
                action="Counselor Created",
                description=f"Admin created Counselor account '{counselor.username}' for branch '{counselor.branch.name}'.",
                object_type="User",
                object_id=counselor.pk,
                request=request
            )
            messages.success(request, f"Counselor '{counselor.username}' was successfully created.")
            return redirect('admin_counselors_list')
    else:
        form = AdminCounselorCreateForm(allowed_branches=allowed_branches)

    return render(request, 'admin/counselor_create.html', {'form': form})


@admin_required
def admin_counselor_detail(request, pk):
    counselor = get_object_or_404(User.objects.select_related('branch'), pk=pk, role=UserRole.COUNSELOR)
    branch_head = User.objects.filter(role=UserRole.BRANCH_HEAD, branch_id=counselor.branch_id).first()
    context = _counselor_context(counselor)
    context['branch_head'] = branch_head
    return render(request, 'admin/counselor_detail.html', context)


@admin_required
def admin_counselor_change_password(request, pk):
    counselor = get_object_or_404(User, pk=pk, role=UserRole.COUNSELOR)
    if request.method == 'POST':
        form = SetPasswordForm(counselor, request.POST)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Password Reset by Admin",
                description=f"Admin reset password for Counselor '{counselor.username}'.",
                object_type="User",
                object_id=counselor.pk,
                request=request
            )
            messages.success(request, f"Password for Counselor '{counselor.username}' has been successfully changed.")
            from activities.services import create_notification
            create_notification(
                recipient=counselor,
                title="Password Changed",
                message="Your account password was updated by the Administrator.",
                notification_type="password_changed"
            )
            return redirect('admin_counselor_detail', pk=counselor.pk)
    else:
        form = SetPasswordForm(counselor)

    return render(request, 'admin/counselor_change_password.html', {
        'form': form,
        'counselor': counselor,
    })
