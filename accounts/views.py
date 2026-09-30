from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .forms import LoginForm, ManagerRegistrationForm, TelecallerRegistrationForm
from .models import User, UserRole
from activities.utils import log_activity

def login_redirect(request):
    """Smart redirect to appropriate dashboard based on user role."""
    if not request.user.is_authenticated:
        return redirect('login')
    if request.user.is_admin_user:
        return redirect('admin_dashboard')
    elif request.user.is_manager_user:
        return redirect('manager_dashboard')
    elif request.user.is_telecaller_user:
        return redirect('telecaller_dashboard')
    return redirect('login')

def _process_login(request, expected_role=None, template_name='registration/login.html', portal_title='CRM Login'):
    if request.user.is_authenticated:
        return login_redirect(request)

    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        username_input = form.cleaned_data.get('username', '').strip()
        password = form.cleaned_data.get('password')
        remember_me = form.cleaned_data.get('remember_me')

        matched_user = User.objects.filter(email__iexact=username_input).first()
        if not matched_user:
            matched_user = User.objects.filter(username__iexact=username_input).first()

        auth_username = matched_user.username if matched_user else username_input
        user = authenticate(request, username=auth_username, password=password)
        if user is not None:
            if not user.is_active:
                messages.error(request, "This account is inactive. Please contact your administrator.")
                return render(request, template_name, {'form': form, 'portal_title': portal_title, 'portal_role': expected_role})

            if expected_role:
                if expected_role == UserRole.ADMIN and not user.is_admin_user:
                    messages.error(request, f"Access denied. '{username}' is not registered with Admin privileges.")
                    return render(request, template_name, {'form': form, 'portal_title': portal_title, 'portal_role': expected_role})
                elif expected_role == UserRole.MANAGER and not user.is_manager_user:
                    messages.error(request, f"Access denied. '{username}' is not a Manager/Counsellor.")
                    return render(request, template_name, {'form': form, 'portal_title': portal_title, 'portal_role': expected_role})
                elif expected_role == UserRole.TELECALLER and not user.is_telecaller_user:
                    messages.error(request, f"Access denied. '{username}' is not a Telecaller.")
                    return render(request, template_name, {'form': form, 'portal_title': portal_title, 'portal_role': expected_role})

            login(request, user)
            if not remember_me:
                request.session.set_expiry(0)  # Browser close expiration
            else:
                request.session.set_expiry(1209600)  # 2 weeks

            log_activity(
                user=user,
                action="User Logged In",
                description=f"{user.display_role} '{user.username}' logged in successfully.",
                object_type="User",
                object_id=str(user.pk),
                request=request
            )
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            return login_redirect(request)
        else:
            messages.error(request, "Invalid username or password. Please try again.")

    return render(request, template_name, {
        'form': form,
        'portal_title': portal_title,
        'portal_role': expected_role
    })

def general_login(request):
    return _process_login(
        request,
        expected_role=None,
        template_name='registration/login.html',
        portal_title='TECHPANDA CRM Login'
    )

def admin_login(request):
    return _process_login(
        request,
        expected_role=UserRole.ADMIN,
        template_name='registration/admin_login.html',
        portal_title='Admin Secure Portal'
    )

def manager_login(request):
    return _process_login(
        request,
        expected_role=UserRole.MANAGER,
        template_name='registration/manager_login.html',
        portal_title='Manager / Counsellor Portal'
    )

def telecaller_login(request):
    return _process_login(
        request,
        expected_role=UserRole.TELECALLER,
        template_name='registration/telecaller_login.html',
        portal_title='Telecaller Workspace Login'
    )

def manager_register(request):
    if request.user.is_authenticated:
        return login_redirect(request)

    if request.method == 'POST':
        form = ManagerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_activity(
                user=user,
                action="Manager Registered",
                description=f"New Manager account registered: '{user.username}' ({user.email}).",
                object_type="User",
                object_id=str(user.pk),
                request=request
            )
            messages.success(request, "Manager registration successful! You can now log in.")
            return redirect('manager_login')
    else:
        form = ManagerRegistrationForm()

    return render(request, 'registration/manager_register.html', {
        'form': form,
        'portal_title': 'Register as Manager / Counsellor'
    })

def telecaller_register(request):
    if request.user.is_authenticated:
        return login_redirect(request)

    if request.method == 'POST':
        form = TelecallerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_activity(
                user=user,
                action="Telecaller Registered",
                description=f"New Telecaller account registered: '{user.username}' ({user.email}).",
                object_type="User",
                object_id=str(user.pk),
                request=request
            )
            messages.success(request, "Telecaller registration successful! You can now log in.")
            return redirect('telecaller_login')
    else:
        form = TelecallerRegistrationForm()

    return render(request, 'registration/telecaller_register.html', {
        'form': form,
        'portal_title': 'Register as Telecaller'
    })

@login_required
def logout_view(request):
    user = request.user
    log_activity(
        user=user,
        action="User Logged Out",
        description=f"User '{user.username}' logged out.",
        object_type="User",
        object_id=str(user.pk),
        request=request
    )
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect('login')
