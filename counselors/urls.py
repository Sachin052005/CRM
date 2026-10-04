from django.urls import path
from . import views

urlpatterns = [
    # Admin counselor oversight
    path('admin/counselors/', views.admin_counselors_list, name='admin_counselors_list'),
    path('admin/counselors/create/', views.admin_counselor_create, name='admin_counselor_create'),
    path('admin/counselors/<int:pk>/', views.admin_counselor_detail, name='admin_counselor_detail'),
    path('admin/counselors/<int:pk>/password/', views.admin_counselor_change_password, name='admin_counselor_change_password'),

    # Counselor portal
    path('counselor/dashboard/', views.counselor_dashboard, name='counselor_dashboard'),
    path('counselor/telecallers/', views.counselor_telecallers_list, name='counselor_telecallers_list'),
    path('counselor/telecallers/<int:pk>/leads/', views.counselor_telecaller_leads, name='counselor_telecaller_leads'),
    path('counselor/leads/<int:lead_pk>/reassign/', views.counselor_lead_reassign, name='counselor_lead_reassign'),
    path('counselor/leads/<int:lead_pk>/unassign/', views.counselor_lead_unassign, name='counselor_lead_unassign'),
]
