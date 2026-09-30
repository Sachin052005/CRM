from django.urls import path
from . import views

urlpatterns = [
    path('admin/branches/', views.admin_branches_list, name='admin_branches_list'),
    path('admin/branches/<int:pk>/edit/', views.admin_branch_edit, name='admin_branch_edit'),
    path('admin/branches/<int:pk>/toggle/', views.admin_branch_toggle_status, name='admin_branch_toggle_status'),
    path('admin/branches/set-active/', views.set_active_branch, name='set_active_branch'),
]
