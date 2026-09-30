from django.urls import path
from . import views

urlpatterns = [
    # Global atomic call completion & lock endpoints (Section 48, 49)
    path('calls/start/', views.start_call_record, name='start_call_record'),
    path('calls/lock-check/', views.check_call_lock, name='check_call_lock'),
    path('calls/<int:pk>/end/', views.end_call_record, name='end_call_record'),
    path('calls/complete/', views.complete_call_record, name='complete_call_record'),

    # Admin routes
    path('admin/calls/', views.admin_calls_list, name='admin_calls_list'),
    path('admin/calls/create/', views.admin_call_create, name='admin_call_create'),
    path('admin/calls/<int:pk>/', views.admin_call_detail, name='admin_call_detail'),

    # Manager routes
    path('manager/calls/', views.manager_calls_list, name='manager_calls_list'),

    # Telecaller routes
    path('telecaller/calls/', views.telecaller_calls_list, name='telecaller_calls_list'),
]
