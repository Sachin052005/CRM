from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.paginator import Paginator
from accounts.models import User, UserRole
from accounts.permissions import admin_required, sales_head_required, telecaller_required, get_accessible_branch_ids
from branches.models import Branch
from branches.utils import get_admin_selected_branch
from .models import Activity, Notification

# ==========================================
# ADMIN: AUDIT LOG PAGE (Section 51)
# ==========================================

@admin_required
def admin_activities_list(request):
    user_filter = request.GET.get('user', '').strip()
    role_filter = request.GET.get('role', '').strip()
    action_filter = request.GET.get('action', '').strip()
    search_query = request.GET.get('search', '').strip()
    branch_filter = request.GET.get('branch', '').strip()

    activities_qs = Activity.objects.select_related('user', 'user__branch').order_by('-timestamp')

    selected_branch = get_admin_selected_branch(request)
    if selected_branch:
        activities_qs = activities_qs.filter(user__branch=selected_branch)
    elif branch_filter:
        activities_qs = activities_qs.filter(user__branch_id=branch_filter)

    if search_query:
        activities_qs = activities_qs.filter(
            Q(description__icontains=search_query) |
            Q(action__icontains=search_query) |
            Q(user__username__icontains=search_query)
        )
    if user_filter:
        activities_qs = activities_qs.filter(user_id=user_filter)
    if role_filter:
        activities_qs = activities_qs.filter(user__role=role_filter)
    if action_filter:
        activities_qs = activities_qs.filter(action__icontains=action_filter)

    paginator = Paginator(activities_qs, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    users = User.objects.all().order_by('username')
    branches = Branch.objects.filter(status='Active')

    return render(request, 'admin/activities_list.html', {
        'page_obj': page_obj,
        'users': users,
        'branches': branches,
        'roles': UserRole.choices,
        'user_filter': user_filter,
        'role_filter': role_filter,
        'action_filter': action_filter,
        'search_query': search_query,
        'branch_filter': branch_filter,
    })


# ==========================================
# SALES HEAD: ACTIVITIES (Section 42)
# ==========================================

@sales_head_required
def manager_activities_list(request):
    manager = request.user
    telecallers = User.objects.filter(role=UserRole.TELECALLER, branch_id__in=get_accessible_branch_ids(manager))
    telecaller_ids = list(telecallers.values_list('id', flat=True))

    activities_qs = Activity.objects.filter(
        Q(user=manager) | Q(user_id__in=telecaller_ids)
    ).select_related('user').order_by('-timestamp')

    user_filter = request.GET.get('user', '').strip()
    if user_filter:
        activities_qs = activities_qs.filter(user_id=user_filter)

    paginator = Paginator(activities_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    team_members = [manager] + list(telecallers)

    return render(request, 'manager/activities_list.html', {
        'page_obj': page_obj,
        'team_members': team_members,
        'user_filter': user_filter,
    })


# ==========================================
# TELECALLER: ACTIVITIES
# ==========================================

@telecaller_required
def telecaller_activities_list(request):
    telecaller = request.user
    activities_qs = Activity.objects.filter(user=telecaller).order_by('-timestamp')

    paginator = Paginator(activities_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'telecaller/activities_list.html', {
        'page_obj': page_obj
    })


# ==========================================
# DATABASE-BACKED NOTIFICATIONS API
# ==========================================

@login_required
def get_notifications_api(request):
    notifications = Notification.objects.filter(recipient=request.user).order_by('-timestamp')[:15]
    unread_count = Notification.objects.filter(recipient=request.user, is_read=False).count()
    data = [
        {
            'id': n.pk,
            'title': n.title,
            'message': n.message,
            'notification_type': n.notification_type,
            'link': n.link,
            'is_read': n.is_read,
            'timestamp': n.timestamp.strftime('%b %d, %H:%M')
        }
        for n in notifications
    ]
    return JsonResponse({
        'unread_count': unread_count,
        'notifications': data
    })

@login_required
@require_POST
def mark_notification_read_api(request, pk):
    notif = get_object_or_404(Notification, pk=pk, recipient=request.user)
    notif.is_read = True
    notif.save(update_fields=['is_read'])
    return JsonResponse({'status': 'success', 'id': pk})

@login_required
@require_POST
def mark_all_notifications_read_api(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'status': 'success'})

