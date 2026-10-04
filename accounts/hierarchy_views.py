from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, Count
from accounts.models import User, UserRole
from accounts.permissions import get_accessible_branch_ids
from branches.models import Branch, SalesHeadBranchAccess
from leads.models import Lead, LeadStatus
from calls.models import CallHistory
from followups.models import FollowUp, FollowUpStatus

# ==============================================================================
# HIERARCHY LEVEL 1: SALES HEADS PAGE
# Displays ONLY Sales Heads. Clicking a Sales Head navigates to Level 2 (Branch Heads).
# ==============================================================================

@login_required
def hierarchy_sales_heads_list(request):
    user = request.user
    if user.role == UserRole.SALES_HEAD:
        return redirect('sales_head_branch_heads', sales_head_id=user.id)
    elif user.role == UserRole.BRANCH_HEAD:
        return redirect('branch_head_counselors', branch_head_id=user.id)
    elif user.role == UserRole.COUNSELOR:
        return redirect('counselor_telecallers', counselor_id=user.id)
    elif user.role == UserRole.TELECALLER:
        return redirect('telecaller_leads', telecaller_id=user.id)
    elif not user.is_admin_user:
        raise PermissionDenied("You do not have permission to view Sales Heads.")

    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    branch_filter = request.GET.get('branch', '').strip()

    qs = User.objects.filter(role=UserRole.SALES_HEAD).prefetch_related('branch_access__branch')

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
        qs = qs.filter(branch_access__branch_id=branch_filter)

    qs = qs.order_by('-date_joined').distinct()

    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))
    branches = Branch.objects.filter(status='Active')

    return render(request, 'hierarchy/sales_heads.html', {
        'page_obj': page_obj,
        'branches': branches,
        'search_query': search_query,
        'status_filter': status_filter,
        'branch_filter': branch_filter,
    })


# ==============================================================================
# HIERARCHY LEVEL 2: BRANCH HEADS PAGE
# Displays ONLY Branch Heads belonging to branches accessible to the selected Sales Head.
# Clicking a Branch Head navigates to Level 3 (Counselors).
# ==============================================================================

@login_required
def hierarchy_branch_heads_list(request, sales_head_id=None):
    user = request.user
    sales_head = None

    if sales_head_id:
        sales_head = get_object_or_404(User, pk=sales_head_id, role=UserRole.SALES_HEAD)
        # Server-side validation of permission scope
        if user.role == UserRole.SALES_HEAD and user.id != sales_head_id:
            raise PermissionDenied("You do not have access to another Sales Head's branch heads.")
        elif user.role == UserRole.BRANCH_HEAD:
            if user.branch_id not in get_accessible_branch_ids(sales_head):
                raise PermissionDenied("You do not have access to this Sales Head.")
        elif not (user.is_admin_user or (user.role == UserRole.SALES_HEAD and user.id == sales_head_id)):
            raise PermissionDenied("Access denied.")
        accessible_branch_ids = get_accessible_branch_ids(sales_head)
    else:
        # Generic / Direct access
        if user.role == UserRole.SALES_HEAD:
            sales_head = user
            accessible_branch_ids = get_accessible_branch_ids(user)
        elif user.is_admin_user:
            accessible_branch_ids = list(Branch.objects.values_list('id', flat=True))
        elif user.role == UserRole.BRANCH_HEAD:
            return redirect('branch_head_counselors', branch_head_id=user.id)
        else:
            raise PermissionDenied("Access denied.")

    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    branch_filter = request.GET.get('branch', '').strip()

    qs = User.objects.filter(role=UserRole.BRANCH_HEAD, branch_id__in=accessible_branch_ids).select_related('branch')

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
    if branch_filter and int(branch_filter) in accessible_branch_ids:
        qs = qs.filter(branch_id=branch_filter)

    qs = qs.order_by('-date_joined')
    paginator = Paginator(qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    branches = Branch.objects.filter(id__in=accessible_branch_ids, status='Active')

    return render(request, 'hierarchy/branch_heads.html', {
        'page_obj': page_obj,
        'sales_head': sales_head,
        'branches': branches,
        'search_query': search_query,
        'status_filter': status_filter,
        'branch_filter': branch_filter,
    })


# ==============================================================================
# HIERARCHY LEVEL 3: COUNSELORS PAGE
# Displays ONLY Counselors under the selected Branch Head's branch.
# Clicking a Counselor navigates to Level 4 (Telecallers).
# ==============================================================================

@login_required
def hierarchy_counselors_list(request, branch_head_id=None):
    user = request.user
    branch_head = None
    sales_head = None

    if branch_head_id:
        branch_head = get_object_or_404(User, pk=branch_head_id, role=UserRole.BRANCH_HEAD)
        # Server-side validation of permission scope
        if user.is_admin_user:
            pass
        elif user.role == UserRole.SALES_HEAD:
            if branch_head.branch_id not in get_accessible_branch_ids(user):
                raise PermissionDenied("This Branch Head is not in your assigned branch access.")
        elif user.role == UserRole.BRANCH_HEAD:
            if user.id != branch_head_id and user.branch_id != branch_head.branch_id:
                raise PermissionDenied("You can only access Counselors in your own branch.")
        else:
            raise PermissionDenied("Access denied.")

        counselors_qs = User.objects.filter(role=UserRole.COUNSELOR, branch_id=branch_head.branch_id).select_related('branch')

        # Find sales head associated with this branch for breadcrumbs
        sh_access = SalesHeadBranchAccess.objects.filter(branch_id=branch_head.branch_id).select_related('sales_head').first()
        sales_head = sh_access.sales_head if sh_access else None
    else:
        # Standalone list
        if user.role == UserRole.BRANCH_HEAD:
            return redirect('branch_head_counselors', branch_head_id=user.id)
        elif user.is_admin_user:
            counselors_qs = User.objects.filter(role=UserRole.COUNSELOR).select_related('branch')
        elif user.role == UserRole.SALES_HEAD:
            accessible = get_accessible_branch_ids(user)
            counselors_qs = User.objects.filter(role=UserRole.COUNSELOR, branch_id__in=accessible).select_related('branch')
        elif user.role == UserRole.COUNSELOR:
            return redirect('counselor_telecallers', counselor_id=user.id)
        else:
            raise PermissionDenied("Access denied.")

    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()

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

    counselors_qs = counselors_qs.order_by('-date_joined')
    paginator = Paginator(counselors_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'hierarchy/counselors.html', {
        'page_obj': page_obj,
        'branch_head': branch_head,
        'sales_head': sales_head,
        'search_query': search_query,
        'status_filter': status_filter,
    })


# ==============================================================================
# HIERARCHY LEVEL 4: TELECALLERS PAGE
# Displays ONLY Telecallers assigned to the selected Counselor.
# Clicking a Telecaller navigates to Level 5 (Assigned Leads & Calls).
# ==============================================================================

@login_required
def hierarchy_telecallers_list(request, counselor_id=None):
    user = request.user
    counselor = None
    branch_head = None
    sales_head = None

    if counselor_id:
        counselor = get_object_or_404(User, pk=counselor_id, role=UserRole.COUNSELOR)
        # Server-side validation of permission scope
        if user.is_admin_user:
            pass
        elif user.role == UserRole.SALES_HEAD:
            if counselor.branch_id not in get_accessible_branch_ids(user):
                raise PermissionDenied("This Counselor is not in your assigned branch access.")
        elif user.role == UserRole.BRANCH_HEAD:
            if counselor.branch_id != user.branch_id:
                raise PermissionDenied("This Counselor is not in your branch.")
        elif user.role == UserRole.COUNSELOR:
            if user.id != counselor_id:
                raise PermissionDenied("You can only view your own assigned telecallers.")
        else:
            raise PermissionDenied("Access denied.")

        telecallers_qs = User.objects.filter(role=UserRole.TELECALLER, counselor_id=counselor.id).select_related('branch', 'counselor')

        # Find ancestors for breadcrumb trail
        if counselor.branch_id:
            branch_head = User.objects.filter(role=UserRole.BRANCH_HEAD, branch_id=counselor.branch_id).first()
            sh_access = SalesHeadBranchAccess.objects.filter(branch_id=counselor.branch_id).select_related('sales_head').first()
            sales_head = sh_access.sales_head if sh_access else None
    else:
        # Standalone list
        if user.role == UserRole.COUNSELOR:
            return redirect('counselor_telecallers', counselor_id=user.id)
        elif user.is_admin_user:
            telecallers_qs = User.objects.filter(role=UserRole.TELECALLER).select_related('branch', 'counselor')
        elif user.role == UserRole.BRANCH_HEAD:
            telecallers_qs = User.objects.filter(role=UserRole.TELECALLER, branch_id=user.branch_id).select_related('branch', 'counselor')
            branch_head = user
        elif user.role == UserRole.SALES_HEAD:
            accessible = get_accessible_branch_ids(user)
            telecallers_qs = User.objects.filter(role=UserRole.TELECALLER, branch_id__in=accessible).select_related('branch', 'counselor')
            sales_head = user
        elif user.role == UserRole.TELECALLER:
            return redirect('telecaller_leads', telecaller_id=user.id)
        else:
            raise PermissionDenied("Access denied.")

    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()

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

    telecallers_qs = telecallers_qs.order_by('-date_joined')
    paginator = Paginator(telecallers_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'hierarchy/telecallers.html', {
        'page_obj': page_obj,
        'counselor': counselor,
        'branch_head': branch_head,
        'sales_head': sales_head,
        'search_query': search_query,
        'status_filter': status_filter,
    })


# ==============================================================================
# HIERARCHY LEVEL 5: ASSIGNED LEADS & CALLS PAGE
# Displays Assigned Leads and Calls for the clicked Telecaller.
# ==============================================================================

@login_required
def hierarchy_telecaller_leads(request, telecaller_id):
    user = request.user
    telecaller = get_object_or_404(User.objects.select_related('counselor', 'branch'), pk=telecaller_id, role=UserRole.TELECALLER)

    # Server-side validation of permission scope
    if user.is_admin_user:
        pass
    elif user.role == UserRole.SALES_HEAD:
        if telecaller.branch_id not in get_accessible_branch_ids(user):
            raise PermissionDenied("This Telecaller is outside your accessible branch scope.")
    elif user.role == UserRole.BRANCH_HEAD:
        if telecaller.branch_id != user.branch_id:
            raise PermissionDenied("This Telecaller belongs to another branch.")
    elif user.role == UserRole.COUNSELOR:
        if telecaller.counselor_id != user.id:
            raise PermissionDenied("This Telecaller is not assigned to you.")
    elif user.role == UserRole.TELECALLER:
        if user.id != telecaller_id:
            raise PermissionDenied("You can only view your own assigned leads.")
    else:
        raise PermissionDenied("Access denied.")

    # Hierarchy ancestor chain for breadcrumbs
    counselor = telecaller.counselor
    branch_head = None
    sales_head = None
    if telecaller.branch_id:
        branch_head = User.objects.filter(role=UserRole.BRANCH_HEAD, branch_id=telecaller.branch_id).first()
        sh_access = SalesHeadBranchAccess.objects.filter(branch_id=telecaller.branch_id).select_related('sales_head').first()
        sales_head = sh_access.sales_head if sh_access else None

    # Assigned Leads & Calls
    leads = Lead.objects.filter(assigned_telecaller=telecaller).select_related(
        'channel', 'product', 'branch'
    ).order_by('-created_at')

    calls = CallHistory.objects.filter(caller=telecaller).select_related('lead').order_by('-call_started_at')[:20]

    # KPIs
    total_leads = leads.count()
    converted_leads = leads.filter(status__in=[LeadStatus.CONVERTED, LeadStatus.JOINED]).count()
    total_calls = CallHistory.objects.filter(caller=telecaller).count()
    pending_followups = FollowUp.objects.filter(telecaller=telecaller, status=FollowUpStatus.PENDING).count()

    paginator = Paginator(leads, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'hierarchy/telecaller_leads.html', {
        'telecaller': telecaller,
        'counselor': counselor,
        'branch_head': branch_head,
        'sales_head': sales_head,
        'page_obj': page_obj,
        'calls': calls,
        'total_leads': total_leads,
        'converted_leads': converted_leads,
        'total_calls': total_calls,
        'pending_followups': pending_followups,
    })
