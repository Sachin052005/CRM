from django.shortcuts import render
from django.db.models import Count, Q, Avg, Sum
from django.utils import timezone
from datetime import datetime, time
from accounts.models import User, UserRole
from accounts.permissions import admin_required, sales_head_required, get_accessible_branch_ids
from branches.models import Branch
from channels.models import Channel
from products.models import Product
from leads.models import Lead, LeadStatus
from followups.models import FollowUp, FollowUpStatus
from calls.models import CallHistory, CallStatus
from activities.models import Activity
from branches.utils import get_admin_selected_branch

# ==========================================
# ADMIN DASHBOARD (Section 15)
# ==========================================

@admin_required
def admin_dashboard(request):
    today = timezone.now().date()

    # Filter parameters
    manager_filter = request.GET.get('manager', '').strip()
    telecaller_filter = request.GET.get('telecaller', '').strip()
    branch_filter = request.GET.get('branch', '').strip()
    channel_filter = request.GET.get('channel', '').strip()
    product_filter = request.GET.get('product', '').strip()
    status_filter = request.GET.get('status', '').strip()
    from_date = request.GET.get('from_date', '').strip()
    to_date = request.GET.get('to_date', '').strip()

    # Base QuerySets
    leads_qs = Lead.objects.all()
    calls_qs = CallHistory.objects.all()
    followups_qs = FollowUp.objects.all()

    # Apply filters dynamically
    selected_branch = get_admin_selected_branch(request)
    if selected_branch:
        leads_qs = leads_qs.filter(branch=selected_branch)
        calls_qs = calls_qs.filter(lead__branch=selected_branch)
        followups_qs = followups_qs.filter(lead__branch=selected_branch)
    elif branch_filter:
        leads_qs = leads_qs.filter(branch_id=branch_filter)
        calls_qs = calls_qs.filter(lead__branch_id=branch_filter)
        followups_qs = followups_qs.filter(lead__branch_id=branch_filter)

    if manager_filter:
        leads_qs = leads_qs.filter(assigned_manager_id=manager_filter)
        calls_qs = calls_qs.filter(manager_id=manager_filter)
        followups_qs = followups_qs.filter(manager_id=manager_filter)
    if telecaller_filter:
        leads_qs = leads_qs.filter(assigned_telecaller_id=telecaller_filter)
        calls_qs = calls_qs.filter(telecaller_id=telecaller_filter)
        followups_qs = followups_qs.filter(telecaller_id=telecaller_filter)
    if channel_filter:
        leads_qs = leads_qs.filter(channel_id=channel_filter)
    if product_filter:
        leads_qs = leads_qs.filter(product_id=product_filter)
    if status_filter:
        leads_qs = leads_qs.filter(status=status_filter)
    if from_date:
        try:
            fd = datetime.strptime(from_date, "%Y-%m-%d").date()
            leads_qs = leads_qs.filter(created_at__date__gte=fd)
            calls_qs = calls_qs.filter(call_started_at__date__gte=fd)
            followups_qs = followups_qs.filter(follow_up_date__gte=fd)
        except ValueError:
            pass
    if to_date:
        try:
            td = datetime.strptime(to_date, "%Y-%m-%d").date()
            leads_qs = leads_qs.filter(created_at__date__lte=td)
            calls_qs = calls_qs.filter(call_started_at__date__lte=td)
            followups_qs = followups_qs.filter(follow_up_date__lte=td)
        except ValueError:
            pass

    # Real DB Metrics (Section 15 KPI cards)
    total_leads = leads_qs.count()
    new_leads = leads_qs.filter(status=LeadStatus.NEW).count()
    active_leads = leads_qs.exclude(status__in=[LeadStatus.LOST, LeadStatus.CONVERTED]).count()

    manager_performance = User.objects.filter(role=UserRole.SALES_HEAD)
    telecaller_performance = User.objects.filter(role=UserRole.TELECALLER).select_related('counselor')
    activities_qs = Activity.objects.select_related('user')

    if selected_branch:
        total_managers = User.objects.filter(role=UserRole.SALES_HEAD, branch_access__branch=selected_branch).count()
        total_telecallers = User.objects.filter(role=UserRole.TELECALLER, branch=selected_branch).count()
        manager_performance = manager_performance.filter(branch_access__branch=selected_branch).distinct()
        telecaller_performance = telecaller_performance.filter(branch=selected_branch)
        activities_qs = activities_qs.filter(user__branch=selected_branch)
    else:
        total_managers = User.objects.filter(role=UserRole.SALES_HEAD).count()
        total_telecallers = User.objects.filter(role=UserRole.TELECALLER).count()

    pending_followups = followups_qs.filter(status=FollowUpStatus.PENDING, follow_up_date__gte=today).count()
    overdue_followups = followups_qs.filter(
        Q(status=FollowUpStatus.OVERDUE) | Q(status=FollowUpStatus.PENDING, follow_up_date__lt=today)
    ).count()

    total_calls = calls_qs.count()
    completed_calls = calls_qs.filter(call_status='Completed').count()

    total_products = Product.objects.count()
    total_channels = Channel.objects.count()
    total_branches = Branch.objects.count()

    # Manager Performance Table
    manager_performance = manager_performance.annotate(
        lead_count=Count('manager_leads', distinct=True),
        call_count=Count('manager_calls', distinct=True),
        followup_count=Count('manager_followups', distinct=True),
        converted_count=Count('manager_leads', filter=Q(manager_leads__status=LeadStatus.CONVERTED), distinct=True)
    )

    # Telecaller Performance Table
    telecaller_performance = telecaller_performance.annotate(
        lead_count=Count('telecaller_leads', distinct=True),
        call_count=Count('telecaller_calls', distinct=True),
        followup_count=Count('telecaller_followups', distinct=True)
    )

    # Recent Records
    recent_leads = leads_qs.select_related('channel', 'assigned_manager', 'assigned_telecaller').order_by('-created_at')[:6]
    recent_activities = activities_qs.order_by('-timestamp')[:6]
    recent_calls = calls_qs.select_related('lead', 'caller', 'manager', 'telecaller').order_by('-call_started_at')[:6]

    # Dropdown collections for filter form
    managers = User.objects.filter(role=UserRole.SALES_HEAD, is_active=True)
    telecallers = User.objects.filter(role=UserRole.TELECALLER, is_active=True)
    branches = Branch.objects.filter(status='Active')
    channels = Channel.objects.filter(status='Active')
    products = Product.objects.filter(status='Active')

    return render(request, 'admin_dashboard/dashboard.html', {
        'total_leads': total_leads,
        'new_leads': new_leads,
        'active_leads': active_leads,
        'total_managers': total_managers,
        'total_telecallers': total_telecallers,
        'pending_followups': pending_followups,
        'overdue_followups': overdue_followups,
        'total_calls': total_calls,
        'completed_calls': completed_calls,
        'total_products': total_products,
        'total_channels': total_channels,
        'total_branches': total_branches,
        'manager_performance': manager_performance,
        'telecaller_performance': telecaller_performance,
        'recent_leads': recent_leads,
        'recent_activities': recent_activities,
        'recent_calls': recent_calls,
        'managers': managers,
        'telecallers': telecallers,
        'branches': branches,
        'channels': channels,
        'products': products,
        'statuses': LeadStatus.choices,
        'manager_filter': manager_filter,
        'telecaller_filter': telecaller_filter,
        'branch_filter': branch_filter,
        'channel_filter': channel_filter,
        'product_filter': product_filter,
        'status_filter': status_filter,
        'from_date': from_date,
        'to_date': to_date,
    })


# ==========================================
# ADMIN REPORTS (Section 52)
# ==========================================

@admin_required
def admin_reports(request):
    selected_branch = get_admin_selected_branch(request)
    leads_base = Lead.objects.all()
    calls_base = CallHistory.objects.all()

    if selected_branch:
        leads_base = leads_base.filter(branch=selected_branch)
        calls_base = calls_base.filter(lead__branch=selected_branch)

    # Real ORM Aggregations
    status_distribution = list(leads_base.values('status').annotate(count=Count('id')).order_by('-count'))
    channel_distribution = list(Channel.objects.filter(leads__in=leads_base).annotate(count=Count('leads')).values('name', 'count').order_by('-count'))
    product_distribution = list(Product.objects.filter(leads__in=leads_base).annotate(count=Count('leads')).values('name', 'count').order_by('-count'))
    if selected_branch:
        branch_distribution = list(Branch.objects.filter(id=selected_branch.id).annotate(count=Count('leads')).values('name', 'count').order_by('-count'))
    else:
        branch_distribution = list(Branch.objects.annotate(count=Count('leads')).values('name', 'count').order_by('-count'))
    call_outcome_distribution = list(calls_base.values('call_outcome').annotate(count=Count('id')).order_by('-count'))

    total_leads = leads_base.count()
    converted_leads = leads_base.filter(status=LeadStatus.CONVERTED).count()
    conversion_rate = round((converted_leads / total_leads * 100), 1) if total_leads > 0 else 0

    total_calls = calls_base.count()
    avg_call_duration = round(calls_base.aggregate(avg=Avg('duration'))['avg'] or 0, 1)

    return render(request, 'reports/admin_reports.html', {
        'status_distribution': status_distribution,
        'channel_distribution': channel_distribution,
        'product_distribution': product_distribution,
        'branch_distribution': branch_distribution,
        'call_outcome_distribution': call_outcome_distribution,
        'total_leads': total_leads,
        'converted_leads': converted_leads,
        'conversion_rate': conversion_rate,
        'total_calls': total_calls,
        'avg_call_duration': avg_call_duration,
    })


# ==========================================
# SALES HEAD REPORTS (Section 41, 52)
# ==========================================

@sales_head_required
def manager_reports(request):
    manager = request.user
    telecallers = User.objects.filter(role=UserRole.TELECALLER, branch_id__in=get_accessible_branch_ids(manager))
    telecaller_ids = list(telecallers.values_list('id', flat=True))

    team_lead_filter = Q(assigned_manager=manager) | Q(assigned_telecaller_id__in=telecaller_ids)
    team_call_filter = Q(manager=manager) | Q(caller=manager) | Q(caller_id__in=telecaller_ids)

    # Scoped aggregations
    status_distribution = list(Lead.objects.filter(team_lead_filter).values('status').annotate(count=Count('id')).order_by('-count'))
    channel_distribution = list(Channel.objects.filter(leads__in=Lead.objects.filter(team_lead_filter)).annotate(count=Count('leads')).values('name', 'count').order_by('-count'))
    product_distribution = list(Product.objects.filter(leads__in=Lead.objects.filter(team_lead_filter)).annotate(count=Count('leads')).values('name', 'count').order_by('-count'))
    call_outcome_distribution = list(CallHistory.objects.filter(team_call_filter).values('call_outcome').annotate(count=Count('id')).order_by('-count'))

    total_leads = Lead.objects.filter(team_lead_filter).count()
    converted_leads = Lead.objects.filter(team_lead_filter, status=LeadStatus.CONVERTED).count()
    conversion_rate = round((converted_leads / total_leads * 100), 1) if total_leads > 0 else 0

    total_calls = CallHistory.objects.filter(team_call_filter).count()

    telecaller_performance = telecallers.annotate(
        lead_count=Count('telecaller_leads', distinct=True),
        call_count=Count('telecaller_calls', distinct=True),
        completed_calls=Count('telecaller_calls', filter=Q(telecaller_calls__call_status='Completed'), distinct=True),
        converted_leads=Count('telecaller_leads', filter=Q(telecaller_leads__status=LeadStatus.CONVERTED), distinct=True)
    )

    return render(request, 'reports/manager_reports.html', {
        'status_distribution': status_distribution,
        'channel_distribution': channel_distribution,
        'product_distribution': product_distribution,
        'call_outcome_distribution': call_outcome_distribution,
        'total_leads': total_leads,
        'converted_leads': converted_leads,
        'conversion_rate': conversion_rate,
        'total_calls': total_calls,
        'telecaller_performance': telecaller_performance,
    })
