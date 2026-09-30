from django.urls import path
from . import views

urlpatterns = [
    # Status toggle
    path('followups/<int:pk>/<str:new_status>/', views.update_followup_status, name='update_followup_status'),

    # Admin routes
    path('admin/followups/', views.admin_followups_list, name='admin_followups_list'),
    path('admin/followups/create/', views.admin_followup_create, name='admin_followup_create'),
    path('admin/followups/<int:pk>/edit/', views.admin_followup_edit, name='admin_followup_edit'),
    path('admin/followups/<int:pk>/reschedule/', views.admin_followup_reschedule, name='admin_followup_reschedule'),

    # Manager routes
    path('manager/followups/', views.manager_followups_list, name='manager_followups_list'),

    # Telecaller routes
    path('telecaller/followups/', views.telecaller_followups_list, name='telecaller_followups_list'),
]
