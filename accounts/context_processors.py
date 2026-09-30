from followups.models import FollowUp, FollowUpStatus
from django.db.models import Q
from django.utils import timezone

def crm_context(request):
    context = {
        'APP_NAME': 'TECHPANDA CRM',
        'is_admin': False,
        'is_manager': False,
        'is_branch_head': False,
        'is_counselor': False,
        'is_telecaller': False,
        'user_role': '',
        'pending_followups_count': 0,
        'overdue_followups_count': 0,
        'unread_notifications_count': 0,
    }
    if request.user.is_authenticated:
        context['is_admin'] = request.user.is_admin_user
        context['is_manager'] = request.user.is_sales_head_user
        context['is_branch_head'] = request.user.is_branch_head_user
        context['is_counselor'] = request.user.is_counselor_user
        context['is_telecaller'] = request.user.is_telecaller_user
        context['user_role'] = request.user.display_role

        if request.user.is_admin_user:
            from branches.models import Branch
            from branches.utils import get_admin_selected_branch
            context['admin_branches'] = Branch.objects.filter(status=Branch.Status.ACTIVE).order_by('name')
            context['selected_branch'] = get_admin_selected_branch(request)

        # Scoped notification counters
        today = timezone.now().date()
        qs = FollowUp.objects.filter(status=FollowUpStatus.PENDING)
        if request.user.is_telecaller_user:
            qs = qs.filter(telecaller=request.user)
        elif request.user.is_sales_head_user:
            from accounts.permissions import get_accessible_branch_ids
            qs = qs.filter(
                Q(manager=request.user) | Q(telecaller__branch_id__in=get_accessible_branch_ids(request.user))
            )
        
        context['pending_followups_count'] = qs.count()
        context['overdue_followups_count'] = qs.filter(follow_up_date__lt=today).count()
        
        from activities.models import Notification
        context['unread_notifications_count'] = Notification.objects.filter(recipient=request.user, is_read=False).count()
        
    return context
