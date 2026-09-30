from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.paginator import Paginator
from django.utils import timezone
from accounts.models import User, UserRole
from accounts.permissions import admin_required, sales_head_required, telecaller_required, get_accessible_branch_ids
from branches.models import Branch
from branches.utils import get_admin_selected_branch
from channels.models import Channel
from products.models import Product
from leads.models import Lead
from django.core.exceptions import PermissionDenied
from activities.utils import log_activity
from .models import FollowUp, FollowUpStatus
from .forms import AdminFollowUpForm, FollowUpRescheduleForm

@login_required
def update_followup_status(request, pk, new_status):
    followup = get_object_or_404(FollowUp, pk=pk)
    user = request.user

    # Security check: telecaller can only update their own follow-ups
    if user.is_telecaller_user and followup.telecaller != user and followup.assigned_user != user:
        raise PermissionDenied("Permission denied: You cannot modify this follow-up.")
    if user.is_sales_head_user:
        branch_ids = get_accessible_branch_ids(user)
        if followup.manager != user and followup.assigned_user != user and not (followup.telecaller and followup.telecaller.branch_id in branch_ids):
            raise PermissionDenied("Permission denied: You cannot modify this follow-up.")

    old_status = followup.status
    if new_status in [FollowUpStatus.COMPLETED, FollowUpStatus.CANCELLED, FollowUpStatus.PENDING]:
        followup.status = new_status
        followup.save()

        action_name = f"Follow-up {new_status}" if new_status in [FollowUpStatus.COMPLETED, FollowUpStatus.CANCELLED] else f"Follow-up Marked {new_status}"

        log_activity(
            user=user,
            action=action_name,
            description=f"Follow-up for '{followup.lead.name}' updated from {old_status} to {new_status}.",
            object_type="FollowUp",
            object_id=followup.pk,
            request=request
        )
        messages.success(request, f"Follow-up marked as {new_status}.")

    # Redirect appropriately
    if user.is_admin_user:
        return redirect('admin_followups_list')
    elif user.is_sales_head_user:
        return redirect('manager_followups_list')
    elif user.is_telecaller_user:
        return redirect('telecaller_followups_list')
    return redirect('admin_followups_list')



# ==========================================
# ADMIN: FOLLOW-UPS
# ==========================================

@admin_required
def admin_followups_list(request):
    today = timezone.now().date()
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()
    manager_filter = request.GET.get('manager', '').strip()
    telecaller_filter = request.GET.get('telecaller', '').strip()
    branch_filter = request.GET.get('branch', '').strip()
    product_filter = request.GET.get('product', '').strip()
    channel_filter = request.GET.get('channel', '').strip()
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    base_qs = FollowUp.objects.all()

    selected_branch = get_admin_selected_branch(request)
    if selected_branch:
        base_qs = base_qs.filter(lead__branch=selected_branch)
    elif branch_filter:
        base_qs = base_qs.filter(lead__branch_id=branch_filter)

    # Scoped real database metrics with consistent overdue logic
    today_count = base_qs.filter(follow_up_date=today, status=FollowUpStatus.PENDING).count()
    pending_count = base_qs.filter(status=FollowUpStatus.PENDING, follow_up_date__gte=today).count()
    overdue_count = base_qs.filter(
        Q(status=FollowUpStatus.OVERDUE) | Q(status=FollowUpStatus.PENDING, follow_up_date__lt=today)
    ).count()
    completed_count = base_qs.filter(status=FollowUpStatus.COMPLETED).count()

    followups_qs = base_qs.select_related(
        'lead', 'assigned_user', 'manager', 'telecaller', 'lead__branch', 'lead__product', 'lead__channel'
    )

    if search_query:
        followups_qs = followups_qs.filter(
            Q(lead__name__icontains=search_query) |
            Q(lead__phone__icontains=search_query) |
            Q(notes__icontains=search_query)
        )
    if status_filter == 'overdue':
        followups_qs = followups_qs.filter(
            Q(status=FollowUpStatus.OVERDUE) | Q(status=FollowUpStatus.PENDING, follow_up_date__lt=today)
        )
    elif status_filter == 'today':
        followups_qs = followups_qs.filter(follow_up_date=today, status=FollowUpStatus.PENDING)
    elif status_filter:
        followups_qs = followups_qs.filter(status=status_filter)

    if manager_filter:
        followups_qs = followups_qs.filter(manager_id=manager_filter)
    if telecaller_filter:
        followups_qs = followups_qs.filter(telecaller_id=telecaller_filter)
    if product_filter:
        followups_qs = followups_qs.filter(lead__product_id=product_filter)
    if channel_filter:
        followups_qs = followups_qs.filter(lead__channel_id=channel_filter)
    if date_from:
        try:
            df = datetime.strptime(date_from, "%Y-%m-%d").date()
            followups_qs = followups_qs.filter(follow_up_date__gte=df)
        except ValueError:
            pass
    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d").date()
            followups_qs = followups_qs.filter(follow_up_date__lte=dt)
        except ValueError:
            pass

    followups_qs = followups_qs.order_by('follow_up_date', 'follow_up_time')
    paginator = Paginator(followups_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    # Build extra_params for preserving filters across pagination links
    query_dict = request.GET.copy()
    query_dict.pop('page', None)
    extra_params = query_dict.urlencode()

    managers = User.objects.filter(role=UserRole.SALES_HEAD, is_active=True)
    telecallers = User.objects.filter(role=UserRole.TELECALLER, is_active=True)
    branches = Branch.objects.filter(status='Active')
    products = Product.objects.all()
    channels = Channel.objects.all()

    return render(request, 'admin/followups_list.html', {
        'page_obj': page_obj,
        'today_count': today_count,
        'pending_count': pending_count,
        'overdue_count': overdue_count,
        'completed_count': completed_count,
        'managers': managers,
        'telecallers': telecallers,
        'branches': branches,
        'products': products,
        'channels': channels,
        'search_query': search_query,
        'status_filter': status_filter,
        'manager_filter': manager_filter,
        'telecaller_filter': telecaller_filter,
        'branch_filter': branch_filter,
        'product_filter': product_filter,
        'channel_filter': channel_filter,
        'date_from': date_from,
        'date_to': date_to,
        'extra_params': extra_params,
    })


@admin_required
def admin_followup_create(request):
    initial = {'follow_up_date': timezone.now().date(), 'status': FollowUpStatus.PENDING}
    lead_id = request.GET.get('lead')
    if lead_id:
        lead = Lead.objects.filter(pk=lead_id).first()
        if lead:
            initial['lead'] = lead
            initial['manager'] = lead.assigned_manager
            initial['telecaller'] = lead.assigned_telecaller

    if request.method == 'POST':
        form = AdminFollowUpForm(request.POST)
        if form.is_valid():
            followup = form.save()
            log_activity(
                user=request.user,
                action="Follow-up Created",
                description=f"Created follow-up for lead '{followup.lead.name}' scheduled on {followup.follow_up_date}.",
                object_type="FollowUp",
                object_id=followup.pk,
                request=request
            )
            messages.success(request, f"Follow-up for '{followup.lead.name}' scheduled successfully.")
            return redirect('admin_followups_list')
    else:
        form = AdminFollowUpForm(initial=initial)

    return render(request, 'admin/followup_form.html', {
        'form': form,
        'is_create': True,
        'page_title': 'Schedule Follow-up'
    })


@admin_required
def admin_followup_edit(request, pk):
    followup = get_object_or_404(FollowUp, pk=pk)

    if request.method == 'POST':
        form = AdminFollowUpForm(request.POST, instance=followup)
        if form.is_valid():
            followup = form.save()
            log_activity(
                user=request.user,
                action="Follow-up Edited",
                description=f"Updated follow-up for lead '{followup.lead.name}' on {followup.follow_up_date}.",
                object_type="FollowUp",
                object_id=followup.pk,
                request=request
            )
            messages.success(request, f"Follow-up for '{followup.lead.name}' updated successfully.")
            return redirect('admin_followups_list')
    else:
        form = AdminFollowUpForm(instance=followup)

    return render(request, 'admin/followup_form.html', {
        'form': form,
        'followup': followup,
        'is_create': False,
        'page_title': f"Edit Follow-up: {followup.lead.name}"
    })


@admin_required
def admin_followup_reschedule(request, pk):
    followup = get_object_or_404(FollowUp, pk=pk)

    if request.method == 'POST':
        form = FollowUpRescheduleForm(request.POST)
        if form.is_valid():
            old_date = followup.follow_up_date
            followup.follow_up_date = form.cleaned_data['follow_up_date']
            followup.follow_up_time = form.cleaned_data['follow_up_time']
            reschedule_notes = form.cleaned_data.get('notes', '').strip()
            if reschedule_notes:
                stamp = timezone.now().strftime('%Y-%m-%d %H:%M')
                followup.notes = f"[{stamp}] Rescheduled from {old_date}: {reschedule_notes}\n" + (followup.notes or '')
            followup.status = FollowUpStatus.PENDING
            followup.save()

            log_activity(
                user=request.user,
                action="Follow-up Rescheduled",
                description=f"Rescheduled follow-up for '{followup.lead.name}' from {old_date} to {followup.follow_up_date}.",
                object_type="FollowUp",
                object_id=followup.pk,
                request=request
            )
            messages.success(request, f"Follow-up rescheduled to {followup.follow_up_date}.")
            return redirect('admin_followups_list')
    else:
        form = FollowUpRescheduleForm(initial={
            'follow_up_date': followup.follow_up_date,
            'follow_up_time': followup.follow_up_time,
        })

    return render(request, 'admin/followup_reschedule.html', {
        'form': form,
        'followup': followup,
    })


# ==========================================
# SALES HEAD: FOLLOW-UPS
# ==========================================

@sales_head_required
def manager_followups_list(request):
    manager = request.user
    today = timezone.now().date()
    telecallers = User.objects.filter(role=UserRole.TELECALLER, branch_id__in=get_accessible_branch_ids(manager))
    telecaller_ids = list(telecallers.values_list('id', flat=True))

    scope_filter = Q(manager=manager) | Q(telecaller_id__in=telecaller_ids) | Q(assigned_user=manager)

    today_count = FollowUp.objects.filter(scope_filter, follow_up_date=today, status=FollowUpStatus.PENDING).count()
    pending_count = FollowUp.objects.filter(scope_filter, status=FollowUpStatus.PENDING, follow_up_date__gte=today).count()
    overdue_count = FollowUp.objects.filter(
        scope_filter,
        Q(status=FollowUpStatus.OVERDUE) | Q(status=FollowUpStatus.PENDING, follow_up_date__lt=today)
    ).count()
    completed_count = FollowUp.objects.filter(scope_filter, status=FollowUpStatus.COMPLETED).count()

    followups_qs = FollowUp.objects.filter(scope_filter).select_related('lead', 'telecaller', 'manager', 'assigned_user')

    status_filter = request.GET.get('status', '').strip()
    telecaller_filter = request.GET.get('telecaller', '').strip()

    if status_filter == 'overdue':
        followups_qs = followups_qs.filter(
            Q(status=FollowUpStatus.OVERDUE) | Q(status=FollowUpStatus.PENDING, follow_up_date__lt=today)
        )
    elif status_filter == 'today':
        followups_qs = followups_qs.filter(follow_up_date=today, status=FollowUpStatus.PENDING)
    elif status_filter:
        followups_qs = followups_qs.filter(status=status_filter)

    if telecaller_filter:
        followups_qs = followups_qs.filter(telecaller_id=telecaller_filter)

    followups_qs = followups_qs.order_by('follow_up_date', 'follow_up_time')
    paginator = Paginator(followups_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'manager/followups_list.html', {
        'page_obj': page_obj,
        'today_count': today_count,
        'pending_count': pending_count,
        'overdue_count': overdue_count,
        'completed_count': completed_count,
        'telecallers': telecallers,
        'status_filter': status_filter,
        'telecaller_filter': telecaller_filter,
    })


# ==========================================
# TELECALLER: FOLLOW-UPS
# ==========================================

@telecaller_required
def telecaller_followups_list(request):
    telecaller = request.user
    today = timezone.now().date()

    scope_filter = Q(telecaller=telecaller) | Q(assigned_user=telecaller)

    today_count = FollowUp.objects.filter(scope_filter, follow_up_date=today, status=FollowUpStatus.PENDING).count()
    pending_count = FollowUp.objects.filter(scope_filter, status=FollowUpStatus.PENDING, follow_up_date__gte=today).count()
    overdue_count = FollowUp.objects.filter(
        scope_filter,
        Q(status=FollowUpStatus.OVERDUE) | Q(status=FollowUpStatus.PENDING, follow_up_date__lt=today)
    ).count()
    completed_count = FollowUp.objects.filter(scope_filter, status=FollowUpStatus.COMPLETED).count()

    followups_qs = FollowUp.objects.filter(scope_filter).select_related('lead', 'telecaller', 'assigned_user')

    status_filter = request.GET.get('status', '').strip() or request.GET.get('filter', '').strip()
    if status_filter == 'overdue':
        followups_qs = followups_qs.filter(
            Q(status=FollowUpStatus.OVERDUE) | Q(status=FollowUpStatus.PENDING, follow_up_date__lt=today)
        )
    elif status_filter == 'today':
        followups_qs = followups_qs.filter(follow_up_date=today, status=FollowUpStatus.PENDING)
    elif status_filter:
        followups_qs = followups_qs.filter(status=status_filter)

    followups_qs = followups_qs.order_by('follow_up_date', 'follow_up_time')
    paginator = Paginator(followups_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'telecaller/followups_list.html', {
        'page_obj': page_obj,
        'today_count': today_count,
        'pending_count': pending_count,
        'overdue_count': overdue_count,
        'completed_count': completed_count,
        'status_filter': status_filter,
    })
