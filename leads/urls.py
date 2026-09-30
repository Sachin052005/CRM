from django.urls import path
from . import views

urlpatterns = [
    # Admin Lead routes
    path('admin/leads/', views.admin_leads_list, name='admin_leads_list'),
    path('admin/leads/create/', views.admin_lead_create, name='admin_lead_create'),
    path('admin/leads/<int:pk>/', views.admin_lead_detail, name='admin_lead_detail'),
    path('admin/leads/<int:pk>/edit/', views.admin_lead_edit, name='admin_lead_edit'),
    path('admin/leads/<int:pk>/delete/', views.admin_lead_delete, name='admin_lead_delete'),
    path('admin/leads/import/', views.admin_leads_import, name='admin_leads_import'),
    path('admin/leads/<int:pk>/status/', views.admin_lead_update_status, name='admin_lead_update_status'),
    path('admin/duplicate-leads/', views.admin_duplicate_leads_view, name='admin_duplicate_leads'),
    path('admin/duplicate-leads/keep-single/', views.admin_duplicate_leads_keep_single, name='admin_duplicate_leads_keep_single'),
    path('admin/leads/interested/', views.admin_interested_leads, name='admin_interested_leads'),
    path('admin/leads/demo-scheduled/', views.admin_demo_scheduled_leads, name='admin_demo_scheduled_leads'),
    path('admin/leads/converted/', views.admin_converted_leads, name='admin_converted_leads'),
    path('admin/leads/lost/', views.admin_lost_leads, name='admin_lost_leads'),
    path('admin/leads/later/', views.admin_later_leads, name='admin_later_leads'),
    path('admin/leads/discussion/', views.admin_discussion_leads, name='admin_discussion_leads'),

    path('admin/leads/<int:pk>/duplicate-info/', views.admin_lead_duplicate_info, name='admin_lead_duplicate_info'),
    path('admin/leads/retry-pending/', views.admin_retry_pending_assignments, name='admin_retry_pending_assignments'),
    path('admin/settings/lead-setup/', views.admin_lead_setup, name='admin_lead_setup'),

    # Admin Offline Leads & Google Sheets / Google Form
    path('admin/offline-leads/', views.admin_offline_leads_list, name='admin_offline_leads'),
    path('admin/offline-leads/list/', views.admin_offline_leads_list, name='admin_offline_leads_list'),
    path('admin/offline-leads/google-form/connect/', views.admin_google_form_connect, name='admin_google_form_connect'),
    path('admin/offline-leads/google-form/disconnect/', views.admin_google_form_disconnect, name='admin_google_form_disconnect'),
    path('admin/offline-leads/google-form/submit-lead/', views.admin_google_form_submit_lead, name='admin_google_form_submit_lead'),
    path('admin/offline-leads/oauth/connect/', views.admin_google_oauth_connect, name='admin_google_oauth_connect'),
    path('admin/offline-leads/connect/', views.admin_google_sheet_connect, name='admin_google_sheet_connect'),
    path('admin/offline-leads/disconnect/', views.admin_google_sheet_disconnect, name='admin_offline_leads_disconnect'),
    path('admin/offline-leads/google-sheet/connect/', views.admin_google_sheet_connect, name='admin_google_sheet_connect_direct'),
    path('admin/offline-leads/google-sheet/<int:connection_id>/disconnect/', views.admin_google_sheet_disconnect, name='admin_google_sheet_disconnect'),
    path('admin/offline-leads/map/<int:connection_id>/', views.admin_google_sheet_save_mapping, name='admin_google_sheet_save_mapping'),
    path('admin/offline-leads/sync/<str:connection_id>/', views.admin_google_sheet_sync_now, name='admin_google_sheet_sync_now'),
    path('admin/offline-leads/toggle/<int:connection_id>/', views.admin_google_sheet_toggle, name='admin_google_sheet_toggle'),
    path('admin/offline-leads/delete/<int:connection_id>/', views.admin_google_sheet_delete, name='admin_google_sheet_delete'),
    path('admin/offline-leads/history/<int:connection_id>/', views.admin_google_sheet_history, name='admin_google_sheet_history'),
    path('admin/offline-leads/test/', views.admin_google_sheet_test, name='admin_google_sheet_test_new'),
    path('admin/offline-leads/test/<int:connection_id>/', views.admin_google_sheet_test, name='admin_google_sheet_test'),
    path('admin/offline-leads/edit/<int:connection_id>/', views.admin_google_sheet_edit, name='admin_google_sheet_edit'),
    path('admin/offline-leads/upload/', views.admin_offline_leads_upload, name='admin_offline_leads_upload'),
    path('admin/offline-leads/api/leads/', views.admin_offline_leads_data_api, name='admin_offline_leads_data_api'),
    path('admin/offline-leads/api/status/', views.admin_offline_leads_status_api, name='admin_offline_leads_status_api'),


    # Manager Lead routes
    path('manager/leads/', views.manager_leads_list, name='manager_leads_list'),
    path('manager/leads/create/', views.manager_lead_create, name='manager_lead_create'),
    path('manager/leads/import/', views.manager_lead_import, name='manager_lead_import'),
    path('manager/leads/<int:pk>/', views.manager_lead_detail, name='manager_lead_detail'),
    path('manager/leads/<int:pk>/edit/', views.manager_lead_edit, name='manager_lead_edit'),

    # Telecaller Lead routes
    path('telecaller/leads/', views.telecaller_leads_list, name='telecaller_leads_list'),
    path('telecaller/leads/create/', views.telecaller_lead_create, name='telecaller_lead_create'),
    path('telecaller/leads/import/', views.telecaller_lead_import, name='telecaller_lead_import'),
    path('telecaller/leads/<int:pk>/', views.telecaller_lead_detail, name='telecaller_lead_detail'),
    path('telecaller/leads/<int:pk>/edit/', views.telecaller_lead_edit, name='telecaller_lead_edit'),
]
