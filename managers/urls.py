from django.urls import path
from . import views

urlpatterns = [
    # Admin manager management
    path('admin/managers/', views.admin_managers_list, name='admin_managers_list'),
    path('admin/managers/create/', views.admin_manager_create, name='admin_manager_create'),
    path('admin/managers/<int:pk>/', views.admin_manager_detail, name='admin_manager_detail'),
    path('admin/managers/<int:pk>/edit/', views.admin_manager_edit, name='admin_manager_edit'),
    path('admin/managers/<int:pk>/toggle/', views.admin_manager_toggle_status, name='admin_manager_toggle_status'),
    path('admin/managers/<int:pk>/password/', views.admin_manager_change_password, name='admin_manager_change_password'),
    path('admin/managers/<int:pk>/delete/', views.admin_manager_delete, name='admin_manager_delete'),

    # Manager portal
    path('manager/dashboard/', views.manager_dashboard, name='manager_dashboard'),
    path('manager/telecallers/', views.manager_telecallers_list, name='manager_telecallers_list'),
    path('manager/telecallers/<int:pk>/', views.manager_telecaller_detail, name='manager_telecaller_detail'),
]
