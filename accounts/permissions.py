from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.contrib import messages
from .models import UserRole

_ROLE_DASHBOARD_URL_NAMES = {
    UserRole.ADMIN: 'admin_dashboard',
    UserRole.SALES_HEAD: 'manager_dashboard',
    UserRole.TELECALLER: 'telecaller_dashboard',
}

def role_required(*allowed_roles):
    """Decorator ensuring logged in user has one of the allowed roles."""
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_active:
                messages.error(request, "Your account has been deactivated. Please contact support.")
                return redirect('login')

            if request.user.is_superuser or request.user.role in allowed_roles:
                return view_func(request, *args, **kwargs)

            messages.error(request, "Access denied: You do not have permission to access this resource.")
            if request.user.is_superuser or request.user.role == UserRole.ADMIN:
                return redirect('admin_dashboard')
            return redirect(_ROLE_DASHBOARD_URL_NAMES.get(request.user.role, 'login'))
        return _wrapped_view
    return decorator

def admin_required(view_func):
    return role_required(UserRole.ADMIN)(view_func)

def sales_head_required(view_func):
    return role_required(UserRole.SALES_HEAD)(view_func)

def branch_head_required(view_func):
    return role_required(UserRole.BRANCH_HEAD)(view_func)

def counselor_required(view_func):
    return role_required(UserRole.COUNSELOR)(view_func)

def telecaller_required(view_func):
    return role_required(UserRole.TELECALLER)(view_func)

def get_accessible_branch_ids(user):
    """Branch ids this user can see/operate within, under the hierarchy."""
    if not user.is_authenticated:
        return []
    if user.is_admin_user:
        from branches.models import Branch
        return list(Branch.objects.values_list('id', flat=True))
    if user.role == UserRole.SALES_HEAD:
        return list(user.branch_access.values_list('branch_id', flat=True))
    if user.branch_id:
        return [user.branch_id]
    return []

def can_access_lead(user, lead):
    """Enforce object-level visibility for leads."""
    if not user.is_authenticated:
        return False
    if user.is_admin_user:
        return True
    if user.role == UserRole.SALES_HEAD:
        return lead.branch_id in get_accessible_branch_ids(user)
    if user.role in (UserRole.BRANCH_HEAD, UserRole.COUNSELOR):
        return lead.branch_id == user.branch_id
    if user.is_telecaller_user:
        return lead.assigned_telecaller_id == user.id
    return False

def can_access_telecaller(user, telecaller_user):
    """Check if a manager-level user can access telecaller data."""
    if not user.is_authenticated:
        return False
    if user.is_admin_user:
        return True
    if user.role == UserRole.SALES_HEAD:
        return telecaller_user.branch_id in get_accessible_branch_ids(user)
    if user.role in (UserRole.BRANCH_HEAD, UserRole.COUNSELOR):
        return telecaller_user.branch_id == user.branch_id
    return False
