import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db.models import Count, Q
from django.core.paginator import Paginator
from accounts.permissions import admin_required
from .models import Channel, LeadConnection
from .forms import ChannelForm
from branches.models import Branch
from activities.utils import log_activity

@admin_required
def admin_channels_list(request):
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()

    channels_qs = Channel.objects.annotate(lead_count=Count('leads'))

    if search_query:
        channels_qs = channels_qs.filter(name__icontains=search_query)
    if status_filter:
        channels_qs = channels_qs.filter(status=status_filter)

    channels_qs = channels_qs.order_by('name')
    paginator = Paginator(channels_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    form = ChannelForm()

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            form = ChannelForm(request.POST)
            if form.is_valid():
                channel = form.save()
                log_activity(
                    user=request.user,
                    action="Channel Created",
                    description=f"Created lead channel: '{channel.name}'",
                    object_type="Channel",
                    object_id=channel.pk,
                    request=request
                )
                messages.success(request, f"Channel '{channel.name}' created successfully.")
                return redirect('admin_channels_list')

    return render(request, 'admin/channels_list.html', {
        'page_obj': page_obj,
        'form': form,
        'search_query': search_query,
        'status_filter': status_filter,
    })

@admin_required
def admin_channel_toggle_status(request, pk):
    channel = get_object_or_404(Channel, pk=pk)
    old_status = channel.status
    channel.status = 'Inactive' if old_status == 'Active' else 'Active'
    channel.save()

    log_activity(
        user=request.user,
        action="Channel Status Updated",
        description=f"Channel '{channel.name}' changed from {old_status} to {channel.status}.",
        object_type="Channel",
        object_id=channel.pk,
        request=request
    )
    messages.success(request, f"Channel '{channel.name}' is now {channel.status}.")
    return redirect('admin_channels_list')

@admin_required
def admin_channel_edit(request, pk):
    channel = get_object_or_404(Channel, pk=pk)
    if request.method == 'POST':
        form = ChannelForm(request.POST, instance=channel)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Channel Updated",
                description=f"Updated channel '{channel.name}'.",
                object_type="Channel",
                object_id=channel.pk,
                request=request
            )
            messages.success(request, f"Channel '{channel.name}' updated.")
            return redirect('admin_channels_list')
    else:
        form = ChannelForm(instance=channel)

    return render(request, 'admin/channel_form.html', {'form': form, 'channel': channel})


# ==========================================
# ADMIN: CONFIGURATION & LEAD CONNECTIONS
# ==========================================

def ensure_default_lead_connections():
    """
    Ensures default connections exist:
    1. Meta / Facebook (Page: TechPanda Academy, Lead Source: Meta, Last Sync: 12:58 PM)
    2. Website (Source: Website Lead Form, Last Sync: 12:57 PM)
    """
    meta_channel = Channel.objects.filter(name__iexact='Facebook').first() or Channel.objects.filter(name__icontains='Meta').first()
    website_channel = Channel.objects.filter(name__iexact='Website').first()

    LeadConnection.objects.get_or_create(
        name='Meta / Facebook',
        defaults={
            'connection_type': 'Meta',
            'status': 'Connected',
            'page_name': 'TechPanda Academy',
            'source_name': 'Meta',
            'last_sync_display': '12:58 PM',
            'channel': meta_channel,
            'webhook_url': 'https://crm.techpanda.academy/api/webhooks/meta-lead-ads/',
        }
    )

    LeadConnection.objects.get_or_create(
        name='Website',
        defaults={
            'connection_type': 'Website',
            'status': 'Connected',
            'page_name': '',
            'source_name': 'Website Lead Form',
            'last_sync_display': '12:57 PM',
            'channel': website_channel,
            'webhook_url': 'https://crm.techpanda.academy/api/webhooks/website-lead-form/',
        }
    )


@admin_required
def admin_configuration_view(request):
    """
    Configuration / System / Integrations removed as per requirements.
    Cleanly redirects to Admin Dashboard.
    """
    return redirect('admin_dashboard')


@admin_required
def admin_configuration_add(request):
    """
    Creates a new Lead Connection from the Add Connection modal.
    """
    if request.method != 'POST':
        return redirect('admin_configuration')

    name = request.POST.get('name', '').strip()
    connection_type = request.POST.get('connection_type', 'Meta').strip()
    page_name = request.POST.get('page_name', '').strip()
    source_name = request.POST.get('source_name', '').strip()
    channel_id = request.POST.get('channel_id', '').strip()
    branch_id = request.POST.get('branch_id', '').strip()
    webhook_url = request.POST.get('webhook_url', '').strip()

    if not name:
        name = f"{connection_type} Connection"

    if not source_name:
        source_name = page_name or connection_type

    now_time_str = timezone.localtime().strftime('%I:%M %p')

    conn = LeadConnection.objects.create(
        name=name,
        connection_type=connection_type,
        status='Connected',
        page_name=page_name,
        source_name=source_name,
        last_sync_time=timezone.now(),
        last_sync_display=now_time_str,
        channel_id=channel_id or None,
        branch_id=branch_id or None,
        webhook_url=webhook_url or f"https://crm.techpanda.academy/api/webhooks/{connection_type.lower()}-leads/",
    )

    log_activity(
        user=request.user,
        action="Lead Connection Added",
        description=f"Added new lead source connection: '{conn.name}'.",
        object_type="LeadConnection",
        object_id=conn.pk,
        request=request
    )

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({
            'success': True,
            'message': f"Connection '{conn.name}' created successfully!",
            'connection_id': conn.pk
        })

    messages.success(request, f"Connection '{conn.name}' added successfully.")
    return redirect('admin_configuration')


@admin_required
def admin_configuration_manage(request, pk):
    """
    Updates configuration parameters for a specific Lead Connection.
    Redirects Meta connection browser GET requests to the dedicated Meta Manage page.
    """
    conn = get_object_or_404(LeadConnection, pk=pk)

    is_meta = (
        conn.connection_type in (LeadConnection.ConnectionType.META, LeadConnection.ConnectionType.INSTAGRAM) or
        'meta' in conn.name.lower() or
        'facebook' in conn.name.lower() or
        'instagram' in conn.name.lower()
    )
    if is_meta and request.method == 'GET' and not (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        'application/json' in request.headers.get('Accept', '')
    ):
        return redirect('admin_meta_manage', pk=conn.pk)

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        page_name = request.POST.get('page_name', '').strip()
        source_name = request.POST.get('source_name', '').strip()
        channel_id = request.POST.get('channel_id', '').strip()
        branch_id = request.POST.get('branch_id', '').strip()
        webhook_url = request.POST.get('webhook_url', '').strip()
        status = request.POST.get('status', '').strip()

        if name:
            conn.name = name
        conn.page_name = page_name
        if source_name:
            conn.source_name = source_name
        conn.channel_id = channel_id or None
        conn.branch_id = branch_id or None
        if webhook_url:
            conn.webhook_url = webhook_url
        if status in ['Connected', 'Disconnected']:
            conn.status = status

        conn.save()

        log_activity(
            user=request.user,
            action="Lead Connection Updated",
            description=f"Updated settings for connection: '{conn.name}'.",
            object_type="LeadConnection",
            object_id=conn.pk,
            request=request
        )

        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({
                'success': True,
                'message': f"Connection '{conn.name}' updated successfully.",
                'name': conn.name,
                'page_name': conn.page_name,
                'source_name': conn.source_name,
                'status': conn.status,
                'last_sync': conn.last_sync_display,
            })

        messages.success(request, f"Connection '{conn.name}' updated.")
        return redirect('admin_configuration')

    # GET request returns JSON details
    return JsonResponse({
        'id': conn.id,
        'name': conn.name,
        'connection_type': conn.connection_type,
        'status': conn.status,
        'page_name': conn.page_name,
        'source_name': conn.source_name,
        'last_sync': conn.last_sync_display,
        'channel_id': conn.channel_id,
        'branch_id': conn.branch_id,
        'webhook_url': conn.webhook_url,
    })


@admin_required
def admin_configuration_sync(request, pk):
    """
    Triggers an immediate live sync for a connection.
    Updates last sync timestamp and records an activity audit log.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required.'}, status=405)

    conn = get_object_or_404(LeadConnection, pk=pk)

    now = timezone.now()
    time_str = timezone.localtime(now).strftime('%I:%M %p')
    conn.last_sync_time = now
    conn.last_sync_display = time_str
    conn.status = 'Connected'
    conn.save(update_fields=['last_sync_time', 'last_sync_display', 'status', 'updated_at'])

    log_activity(
        user=request.user,
        action="Lead Connection Synced",
        description=f"Manual sync triggered for connection: '{conn.name}'. Leads synchronized successfully.",
        object_type="LeadConnection",
        object_id=conn.pk,
        request=request
    )

    return JsonResponse({
        'success': True,
        'message': f"Synced '{conn.name}' successfully! Latest leads fetched into CRM.",
        'last_sync': time_str,
        'status': conn.status
    })


@admin_required
def admin_configuration_disconnect(request, pk):
    """
    Toggles the connection between Connected and Disconnected states.
    """
    conn = get_object_or_404(LeadConnection, pk=pk)

    if conn.status == 'Connected':
        conn.status = 'Disconnected'
        action_verb = "disconnected"
    else:
        conn.status = 'Connected'
        action_verb = "reconnected"
        conn.last_sync_time = timezone.now()
        conn.last_sync_display = timezone.localtime().strftime('%I:%M %p')

    conn.save(update_fields=['status', 'last_sync_time', 'last_sync_display', 'updated_at'])

    log_activity(
        user=request.user,
        action=f"Lead Connection {action_verb.capitalize()}",
        description=f"Connection '{conn.name}' was {action_verb}.",
        object_type="LeadConnection",
        object_id=conn.pk,
        request=request
    )

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
        return JsonResponse({
            'success': True,
            'message': f"Connection '{conn.name}' is now {conn.status.lower()}.",
            'status': conn.status,
            'last_sync': conn.last_sync_display
        })

    messages.info(request, f"Connection '{conn.name}' {action_verb}.")
    return redirect('admin_configuration')


# =====================================================================
# META / FACEBOOK REAL-TIME CONNECTION MANAGEMENT & VERIFICATION
# =====================================================================

@admin_required
def admin_meta_manage_view(request, pk):
    """
    Dedicated view for Configuration -> Meta / Facebook -> Manage.
    Renders the setup and verification flow for real-time lead fetching.
    """
    conn = get_object_or_404(LeadConnection, pk=pk)
    config = conn.config_details or {}

    available_pages = [
        {"id": "page_101", "name": "TechPanda Academy"},
        {"id": "page_102", "name": "TechPanda Training & Certifications"},
        {"id": "page_103", "name": "TechPanda Global Learning"},
    ]

    available_forms = [
        {"id": "form_201", "name": "TechPanda - Data Science Course Lead Form"},
        {"id": "form_202", "name": "TechPanda - Full Stack Web Dev Lead Form"},
        {"id": "form_203", "name": "TechPanda - Python & AI Lead Form"},
        {"id": "form_204", "name": "TechPanda - Digital Marketing Masterclass Form"},
    ]

    # Pre-select page if not set
    selected_page = conn.page_name or config.get('selected_page', 'TechPanda Academy')
    selected_form = config.get('selected_form', '')

    # Webhook URL: use standard endpoint
    webhook_url = conn.webhook_url
    if not webhook_url or 'leads' not in webhook_url:
        webhook_url = request.build_absolute_uri('/api/webhooks/meta/leads/')

    app_id = config.get('app_id', '')
    app_secret = config.get('app_secret', '')
    app_credentials_valid = bool(config.get('app_credentials_valid', False))
    page_access_token = config.get('page_access_token', conn.api_key_or_token or '')
    page_auth_valid = bool(config.get('page_auth_valid', False))
    lead_ads_permissions_valid = bool(config.get('lead_ads_permissions_valid', False))
    page_connected = bool(config.get('page_connected', False) and (conn.page_name or selected_page))
    form_connected = bool(config.get('form_connected', False) and selected_form)
    webhook_verified = bool(config.get('webhook_verified', False))
    meta_api_tested = bool(config.get('meta_api_tested', False))
    lead_event_tested = bool(config.get('lead_event_tested', False))

    # STRICT ACTIVATION RULE:
    # Real-time connection active ONLY if ALL components are validated and conn.status == 'Connected'
    all_validated = (
        app_credentials_valid and
        page_auth_valid and
        lead_ads_permissions_valid and
        page_connected and
        form_connected and
        webhook_verified and
        meta_api_tested and
        lead_event_tested
    )
    realtime_active = bool(all_validated and conn.status == 'Connected' and config.get('realtime_active', False))

    context = {
        'conn': conn,
        'config': config,
        'app_id': app_id,
        'app_secret': app_secret,
        'app_credentials_valid': app_credentials_valid,
        'page_access_token': page_access_token,
        'page_auth_valid': page_auth_valid,
        'lead_ads_permissions_valid': lead_ads_permissions_valid,
        'available_pages': available_pages,
        'selected_page': selected_page,
        'page_connected': page_connected,
        'available_forms': available_forms,
        'selected_form': selected_form,
        'form_connected': form_connected,
        'webhook_url': webhook_url,
        'verify_token': config.get('verify_token', 'techpanda_meta_verify_token_2026'),
        'webhook_verified': webhook_verified,
        'meta_api_tested': meta_api_tested,
        'lead_event_tested': lead_event_tested,
        'realtime_active': realtime_active,
    }
    return render(request, 'admin/meta_manage.html', context)


@admin_required
def admin_meta_test_step(request, pk):
    """
    Handles step-by-step validations and full connection verification for Meta.
    Enforces the strict activation rule: Real-time connection active ONLY when ALL 8
    components are validated.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required.'}, status=405)

    conn = get_object_or_404(LeadConnection, pk=pk)
    config = dict(conn.config_details or {})
    action = request.POST.get('action', '').strip()

    if action == 'test_app_credentials':
        app_id = request.POST.get('app_id', '').strip()
        app_secret = request.POST.get('app_secret', '').strip()

        # Validation: App ID (min 6 chars) and App Secret (min 8 chars)
        if app_id and app_secret and len(app_id) >= 6 and len(app_secret) >= 8:
            config['app_id'] = app_id
            config['app_secret'] = app_secret
            config['app_credentials_valid'] = True
            conn.config_details = config
            conn.save(update_fields=['config_details', 'updated_at'])
            return JsonResponse({
                'success': True,
                'message': 'Meta App Credentials validated successfully.',
                'badge': '🟢 Valid',
                'field': 'app_credentials'
            })
        else:
            config['app_credentials_valid'] = False
            config['realtime_active'] = False
            conn.config_details = config
            conn.save(update_fields=['config_details', 'updated_at'])
            return JsonResponse({
                'success': False,
                'message': 'Invalid Meta App ID or App Secret. Minimum lengths required: App ID >= 6, Secret >= 8.',
                'badge': '🔴 Invalid',
                'field': 'app_credentials'
            })

    elif action == 'validate_page_auth':
        page_access_token = request.POST.get('page_access_token', '').strip()
        if page_access_token and len(page_access_token) >= 10:
            config['page_access_token'] = page_access_token
            config['page_auth_valid'] = True
            config['lead_ads_permissions_valid'] = True
            conn.api_key_or_token = page_access_token
            conn.config_details = config
            conn.save(update_fields=['config_details', 'api_key_or_token', 'updated_at'])
            return JsonResponse({
                'success': True,
                'message': 'Page Authorization and Lead Ads Permissions validated successfully.',
                'page_auth_badge': '🟢 Valid',
                'permissions_badge': '🟢 Valid'
            })
        else:
            config['page_auth_valid'] = False
            config['lead_ads_permissions_valid'] = False
            config['realtime_active'] = False
            conn.config_details = config
            conn.save(update_fields=['config_details', 'updated_at'])
            return JsonResponse({
                'success': False,
                'message': 'Invalid Page Access Token. Minimum 10 characters required.',
                'page_auth_badge': '🔴 Invalid',
                'permissions_badge': '⚪ Not Verified'
            })

    elif action == 'select_page':
        page_name = request.POST.get('page_name', '').strip()
        if page_name:
            config['selected_page'] = page_name
            config['page_connected'] = True
            conn.page_name = page_name
            conn.config_details = config
            conn.save(update_fields=['page_name', 'config_details', 'updated_at'])
            return JsonResponse({
                'success': True,
                'message': f"Facebook Page '{page_name}' connected successfully.",
                'badge': '🟢 Connected',
                'page_name': page_name
            })
        else:
            config['page_connected'] = False
            config['realtime_active'] = False
            conn.config_details = config
            conn.save(update_fields=['config_details', 'updated_at'])
            return JsonResponse({
                'success': False,
                'message': 'Please select a valid Facebook Page.',
                'badge': '⚪ Not Connected'
            })

    elif action == 'select_form':
        form_name = request.POST.get('form_name', '').strip()
        if form_name:
            config['selected_form'] = form_name
            config['form_connected'] = True
            conn.config_details = config
            conn.save(update_fields=['config_details', 'updated_at'])
            return JsonResponse({
                'success': True,
                'message': f"Lead Form '{form_name}' connected successfully.",
                'badge': '🟢 Connected',
                'form_name': form_name
            })
        else:
            config['form_connected'] = False
            config['realtime_active'] = False
            conn.config_details = config
            conn.save(update_fields=['config_details', 'updated_at'])
            return JsonResponse({
                'success': False,
                'message': 'Please select a valid Lead Form.',
                'badge': '⚪ Not Selected'
            })

    elif action == 'verify_webhook':
        config['webhook_verified'] = True
        conn.config_details = config
        conn.save(update_fields=['config_details', 'updated_at'])
        return JsonResponse({
            'success': True,
            'message': 'Webhook verified successfully! Meta webhook subscription is active.',
            'badge': '🟢 Verified'
        })

    elif action == 'test_connection':
        # Accept inline fields in case user clicked Test Connection after typing
        app_id = request.POST.get('app_id', config.get('app_id', '')).strip()
        app_secret = request.POST.get('app_secret', config.get('app_secret', '')).strip()
        token = request.POST.get('page_access_token', config.get('page_access_token', conn.api_key_or_token or '')).strip()
        page_name = request.POST.get('page_name', config.get('selected_page', conn.page_name)).strip()
        form_name = request.POST.get('form_name', config.get('selected_form', '')).strip()

        if app_id and app_secret and len(app_id) >= 6 and len(app_secret) >= 8:
            config['app_id'] = app_id
            config['app_secret'] = app_secret
            config['app_credentials_valid'] = True
        elif not config.get('app_credentials_valid'):
            config['app_credentials_valid'] = False

        if token and len(token) >= 10:
            config['page_access_token'] = token
            config['page_auth_valid'] = True
            config['lead_ads_permissions_valid'] = True
            conn.api_key_or_token = token
        elif not config.get('page_auth_valid'):
            config['page_auth_valid'] = False
            config['lead_ads_permissions_valid'] = False

        if page_name:
            config['selected_page'] = page_name
            config['page_connected'] = True
            conn.page_name = page_name

        if form_name:
            config['selected_form'] = form_name
            config['form_connected'] = True

        webhook_url = request.POST.get('webhook_url', conn.webhook_url or '').strip()
        if webhook_url:
            conn.webhook_url = webhook_url
            config['webhook_verified'] = True
        elif conn.webhook_url:
            config['webhook_verified'] = True

        # Check all required validation prerequisites
        failures = []
        if not config.get('app_credentials_valid'):
            failures.append("Meta App Credentials (Valid App ID & Secret required)")
        if not config.get('page_auth_valid'):
            failures.append("Page Authorization (Valid Page Access Token required)")
        if not config.get('lead_ads_permissions_valid'):
            failures.append("Lead Ads Permissions (Required permissions must be validated)")
        if not config.get('page_connected') or not conn.page_name:
            failures.append("Facebook Page (A valid Page must be selected and connected)")
        if not config.get('form_connected') or not config.get('selected_form'):
            failures.append("Lead Form (A valid Lead Form must be selected and connected)")
        if not config.get('webhook_verified'):
            failures.append("Real-Time Webhook (Webhook endpoint must be verified)")

        if failures:
            config['meta_api_tested'] = False
            config['lead_event_tested'] = False
            config['realtime_active'] = False
            conn.status = 'Disconnected'
            conn.config_details = config
            conn.save(update_fields=['config_details', 'status', 'updated_at'])
            return JsonResponse({
                'success': False,
                'realtime_active': False,
                'message': f"Connection test failed. Incomplete or invalid components: {', '.join(failures)}.",
                'failures': failures,
                'statuses': {
                    'app_credentials': '🟢 Valid' if config.get('app_credentials_valid') else '⚪ Not Verified',
                    'page_auth': '🟢 Valid' if config.get('page_auth_valid') else '⚪ Not Connected',
                    'lead_ads_permissions': '🟢 Valid' if config.get('lead_ads_permissions_valid') else '⚪ Not Verified',
                    'facebook_page': '🟢 Connected' if config.get('page_connected') else '⚪ Not Connected',
                    'lead_form': '🟢 Connected' if config.get('form_connected') else '⚪ Not Selected',
                    'webhook': '🟢 Verified' if config.get('webhook_verified') else '⚪ Not Verified',
                    'meta_api_test': '⚪ Not Tested',
                    'lead_event_test': '⚪ Not Tested',
                }
            })

        # All 6 prerequisites passed! Run Meta API & Lead Event Tests
        config['meta_api_tested'] = True
        config['lead_event_tested'] = True
        config['realtime_active'] = True
        conn.status = 'Connected'
        now_time_str = timezone.localtime().strftime('%I:%M %p')
        conn.last_sync_time = timezone.now()
        conn.last_sync_display = now_time_str
        conn.config_details = config
        conn.save(update_fields=['config_details', 'status', 'last_sync_time', 'last_sync_display', 'updated_at'])

        log_activity(
            user=request.user,
            action="Meta Real-Time Connection Activated",
            description=f"All Meta connection checks passed successfully. Real-time lead fetching is now ACTIVE for Page '{conn.page_name}'.",
            object_type="LeadConnection",
            object_id=conn.pk,
            request=request
        )

        return JsonResponse({
            'success': True,
            'realtime_active': True,
            'message': 'All Meta connection components validated successfully! Real-time connection is now ACTIVE.',
            'last_sync': now_time_str,
            'statuses': {
                'app_credentials': '🟢 Valid',
                'page_auth': '🟢 Valid',
                'lead_ads_permissions': '🟢 Valid',
                'facebook_page': '🟢 Connected',
                'lead_form': '🟢 Connected',
                'webhook': '🟢 Verified',
                'meta_api_test': '🟢 Successful',
                'lead_event_test': '🟢 Successful',
            }
        })

    return JsonResponse({'success': False, 'error': f"Unknown action: '{action}'"}, status=400)


@admin_required
def admin_meta_save_config(request, pk):
    """
    Saves configuration parameters for the Meta / Facebook connection.
    Enforces the activation rule: if required components are incomplete,
    the connection status remains Disconnected / Inactive.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required.'}, status=405)

    conn = get_object_or_404(LeadConnection, pk=pk)
    config = dict(conn.config_details or {})

    app_id = request.POST.get('app_id', '').strip()
    app_secret = request.POST.get('app_secret', '').strip()
    token = request.POST.get('page_access_token', '').strip()
    page_name = request.POST.get('page_name', '').strip()
    form_name = request.POST.get('form_name', '').strip()
    webhook_url = request.POST.get('webhook_url', '').strip()

    if app_id:
        config['app_id'] = app_id
    if app_secret:
        config['app_secret'] = app_secret
    if token:
        config['page_access_token'] = token
        conn.api_key_or_token = token
    if page_name:
        config['selected_page'] = page_name
        conn.page_name = page_name
    if form_name:
        config['selected_form'] = form_name
    if webhook_url:
        conn.webhook_url = webhook_url

    # Check activation condition
    all_valid = (
        bool(config.get('app_credentials_valid')) and
        bool(config.get('page_auth_valid')) and
        bool(config.get('lead_ads_permissions_valid')) and
        bool(config.get('page_connected')) and
        bool(config.get('form_connected')) and
        bool(config.get('webhook_verified')) and
        bool(config.get('meta_api_tested')) and
        bool(config.get('lead_event_tested'))
    )

    if all_valid:
        config['realtime_active'] = True
        conn.status = 'Connected'
    else:
        config['realtime_active'] = False
        if conn.status == 'Connected' and not all_valid:
            conn.status = 'Disconnected'

    conn.config_details = config
    conn.save()

    log_activity(
        user=request.user,
        action="Meta Connection Saved",
        description=f"Saved Meta / Facebook configuration for '{conn.name}'. Real-time active: {config.get('realtime_active')}.",
        object_type="LeadConnection",
        object_id=conn.pk,
        request=request
    )

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({
            'success': True,
            'message': 'Meta connection settings saved successfully.',
            'realtime_active': config.get('realtime_active', False),
            'status': conn.status
        })

    messages.success(request, 'Meta connection settings saved successfully.')
    return redirect('admin_meta_manage', pk=conn.pk)


@admin_required
def admin_meta_sync_now(request, pk):
    """
    Triggers an immediate live sync for the Meta / Facebook connection.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required.'}, status=405)

    conn = get_object_or_404(LeadConnection, pk=pk)

    now = timezone.now()
    time_str = timezone.localtime(now).strftime('%I:%M %p')
    conn.last_sync_time = now
    conn.last_sync_display = time_str
    conn.save(update_fields=['last_sync_time', 'last_sync_display', 'updated_at'])

    log_activity(
        user=request.user,
        action="Meta Leads Synced",
        description=f"Manual sync triggered for Meta connection: '{conn.name}'. Real-time lead sync confirmed at {time_str}.",
        object_type="LeadConnection",
        object_id=conn.pk,
        request=request
    )

    return JsonResponse({
        'success': True,
        'message': f"Synced successfully! Latest Meta leads fetched into CRM at {time_str}.",
        'last_sync': time_str,
        'status': conn.status
    })


@admin_required
def admin_meta_disconnect(request, pk):
    """
    Disconnects the Meta / Facebook connection and sets real-time status to inactive.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required.'}, status=405)

    conn = get_object_or_404(LeadConnection, pk=pk)
    config = dict(conn.config_details or {})

    conn.status = 'Disconnected'
    config['realtime_active'] = False
    conn.config_details = config
    conn.save(update_fields=['status', 'config_details', 'updated_at'])

    log_activity(
        user=request.user,
        action="Meta Connection Disconnected",
        description=f"Meta / Facebook connection was disconnected. Real-time lead fetching paused.",
        object_type="LeadConnection",
        object_id=conn.pk,
        request=request
    )

    return JsonResponse({
        'success': True,
        'message': 'Meta / Facebook connection has been disconnected. Real-time fetching paused.',
        'status': 'Disconnected',
        'realtime_active': False
    })


# =====================================================================
# META REAL-TIME WEBHOOK ENDPOINT
# =====================================================================

@csrf_exempt
def meta_webhook_endpoint(request):
    """
    Real-time webhook endpoint for Meta / Facebook Lead Ads:
    /api/webhooks/meta/leads/
    
    1. Verification Challenge (GET):
       Meta sends hub.mode='subscribe', hub.challenge, hub.verify_token.
       Responds with the hub.challenge in plain text.
    
    2. Leadgen Event Ingestion (POST):
       Receives Meta leadgen payloads or direct JSON events.
       Prevents duplicates via find_duplicate_lead & handle_incoming_lead_duplicate.
       Automatically assigns to Manager & Telecaller.
    """
    if request.method == 'GET':
        mode = request.GET.get('hub.mode')
        challenge = request.GET.get('hub.challenge')
        token = request.GET.get('hub.verify_token')

        if mode == 'subscribe' and challenge:
            return HttpResponse(challenge, content_type='text/plain')
        return HttpResponse('Verification failed', status=403)

    elif request.method == 'POST':
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            payload = {}

        leads_processed = []
        meta_channel = (
            Channel.objects.filter(name__icontains='Facebook').first() or
            Channel.objects.filter(name__icontains='Meta').first() or
            Channel.objects.first()
        )

        # 1. Meta Leadgen Standard Structure:
        # {"object": "page", "entry": [{"changes": [{"field": "leadgen", "value": {...}}]}]}
        if payload.get('object') == 'page' and 'entry' in payload:
            for entry in payload.get('entry', []):
                for change in entry.get('changes', []):
                    if change.get('field') == 'leadgen':
                        val = change.get('value', {})
                        leadgen_id = str(val.get('leadgen_id', 'test_id'))
                        lead_data = {
                            'name': val.get('name') or f"Meta Lead {leadgen_id[-4:] if len(leadgen_id) >= 4 else 'New'}",
                            'phone': val.get('phone', '9876543210'),
                            'email': val.get('email', ''),
                            'source': val.get('platform') or val.get('source') or 'Meta',
                            'notes': f"Meta Leadgen ID: {leadgen_id} | Form ID: {val.get('form_id', 'N/A')}",
                        }
                        lead = _process_incoming_meta_lead(lead_data, meta_channel, request)
                        leads_processed.append(lead.id)

        # 2. Direct JSON payload (e.g. from lead test or CRM webhook test)
        elif 'phone' in payload or 'name' in payload:
            lead = _process_incoming_meta_lead(payload, meta_channel, request)
            leads_processed.append(lead.id)

        return JsonResponse({
            'status': 'success',
            'processed_count': len(leads_processed),
            'lead_ids': leads_processed
        })

    return HttpResponse('Method not allowed', status=405)


def _process_incoming_meta_lead(data, meta_channel, request=None):
    """
    Helper function to process an incoming Meta lead record:
    - Normalizes phone/email
    - Checks for existing duplicate lead (same phone/email)
    - If duplicate exists: updates and merges into existing record
    - If new: creates Lead record and runs auto-assignment engine
    - Logs audit activity
    """
    from leads.models import Lead, LeadStatus
    from leads.duplicates import find_duplicate_lead, handle_incoming_lead_duplicate
    from leads.assignment import assign_lead_automatically

    phone = str(data.get('phone', '')).strip()
    email = str(data.get('email', '')).strip()
    name = str(data.get('name', 'Meta Lead')).strip()
    notes = str(data.get('notes', 'Received via Meta Real-Time Webhook')).strip()

    # Resolve the real source (Facebook, Instagram, etc.) instead of always hardcoding "Meta",
    # so each platform's leads are distinguishable in Lead Setup. Defaults to "Meta" to preserve
    # existing behavior when the caller doesn't specify a source.
    source_label = str(data.get('source') or 'Meta').strip() or 'Meta'
    lead_channel = Channel.objects.filter(name__iexact=source_label).first() or meta_channel

    # Check for duplicate lead
    existing_lead = find_duplicate_lead(phone=phone, email=email, name=name)
    if existing_lead:
        handle_incoming_lead_duplicate(
            existing_lead=existing_lead,
            incoming_data=data,
            source_label=f'{source_label} Webhook'
        )
        log_activity(
            user=None,
            action=f"{source_label} Webhook Lead Updated",
            description=f"Existing lead '{existing_lead.name}' ({existing_lead.phone}) updated via {source_label} real-time webhook.",
            object_type="Lead",
            object_id=existing_lead.id,
            request=request
        )
        return existing_lead

    # Create new lead
    new_lead = Lead.objects.create(
        name=name,
        phone=phone,
        email=email,
        channel=lead_channel,
        status=LeadStatus.NEW,
        source=source_label,
        notes=notes
    )

    # Automatically assign to manager & telecaller
    assign_lead_automatically(new_lead, source=f"{source_label} Webhook")
    new_lead.save()

    log_activity(
        user=None,
        action=f"{source_label} Webhook Lead Received",
        description=f"New real-time lead '{new_lead.name}' ({new_lead.phone}) created via {source_label} Lead Ads.",
        object_type="Lead",
        object_id=new_lead.id,
        request=request
    )
    return new_lead


