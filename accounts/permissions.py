from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.contrib import messages
from .models import UserRole

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
            # Redirect to their appropriate dashboard
            if request.user.role == UserRole.ADMIN or request.user.is_superuser:
                return redirect('admin_dashboard')
            elif request.user.role == UserRole.MANAGER:
                return redirect('manager_dashboard')
            elif request.user.role == UserRole.TELECALLER:
                return redirect('telecaller_dashboard')
            return redirect('login')
        return _wrapped_view
    return decorator

def admin_required(view_func):
    return role_required(UserRole.ADMIN)(view_func)

def manager_required(view_func):
    return role_required(UserRole.MANAGER)(view_func)

def telecaller_required(view_func):
    return role_required(UserRole.TELECALLER)(view_func)

def can_access_lead(user, lead):
    """Enforce object-level visibility for leads."""
    if not user.is_authenticated:
        return False
    if user.is_admin_user:
        return True
    if user.is_manager_user:
        # Manager can view their own leads or leads assigned to their telecallers
        if lead.assigned_manager == user:
            return True
        if lead.assigned_telecaller and lead.assigned_telecaller.manager == user:
            return True
        return False
    if user.is_telecaller_user:
        return lead.assigned_telecaller == user
    return False

def can_access_telecaller(user, telecaller_user):
    """Check if manager can access telecaller data."""
    if not user.is_authenticated:
        return False
    if user.is_admin_user:
        return True
    if user.is_manager_user:
        return telecaller_user.manager == user
    return False
