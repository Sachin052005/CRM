from django.urls import path
from . import views

urlpatterns = [
    # Admin telecaller management
    path('admin/telecallers/', views.admin_telecallers_list, name='admin_telecallers_list'),
    path('admin/telecallers/create/', views.admin_telecaller_create, name='admin_telecaller_create'),
    path('admin/telecallers/<int:pk>/', views.admin_telecaller_detail, name='admin_telecaller_detail'),
    path('admin/telecallers/<int:pk>/edit/', views.admin_telecaller_edit, name='admin_telecaller_edit'),
    path('admin/telecallers/<int:pk>/assign/', views.admin_telecaller_assign, name='admin_telecaller_assign'),
    path('admin/telecallers/<int:pk>/toggle/', views.admin_telecaller_toggle_status, name='admin_telecaller_toggle_status'),
    path('admin/telecallers/<int:pk>/password/', views.admin_telecaller_change_password, name='admin_telecaller_change_password'),
    path('admin/telecallers/<int:pk>/delete/', views.admin_telecaller_delete, name='admin_telecaller_delete'),

    # Branch Head telecaller creation (own branch)
    path('manager/branch-head/telecallers/create/', views.branch_head_telecaller_create, name='branch_head_telecaller_create'),

    # Telecaller workspace portal
    path('telecaller/dashboard/', views.telecaller_dashboard, name='telecaller_dashboard'),
]
