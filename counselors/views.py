from django.shortcuts import render, get_object_or_404
from django.db.models import Count, Q
from django.core.paginator import Paginator
from django.utils import timezone

from accounts.models import User, UserRole
from accounts.permissions import admin_required, counselor_required
from branches.models import Branch
from leads.models import Lead, LeadStatus
from followups.models import FollowUp, FollowUpStatus
from calls.models import CallHistory
from activities.models import Activity


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
