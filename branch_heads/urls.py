from django.urls import path
from . import views

urlpatterns = [
    # Admin branch head management
    path('admin/branch-heads/', views.admin_branch_heads_list, name='admin_branch_heads_list'),
    path('admin/branch-heads/create/', views.admin_branch_head_create, name='admin_branch_head_create'),
    path('admin/branch-heads/<int:pk>/', views.admin_branch_head_detail, name='admin_branch_head_detail'),
    path('admin/branch-heads/<int:pk>/edit/', views.admin_branch_head_edit, name='admin_branch_head_edit'),
    path('admin/branch-heads/<int:pk>/toggle/', views.admin_branch_head_toggle_status, name='admin_branch_head_toggle_status'),
    path('admin/branch-heads/<int:pk>/password/', views.admin_branch_head_change_password, name='admin_branch_head_change_password'),

    # Sales Head branch head management (scoped to accessible branches)
    path('manager/branch-heads/', views.sales_head_branch_heads_list, name='sales_head_branch_heads_list'),
    path('manager/branch-heads/create/', views.sales_head_branch_head_create, name='sales_head_branch_head_create'),
    path('manager/branch-heads/<int:pk>/', views.sales_head_branch_head_detail, name='sales_head_branch_head_detail'),
    path('manager/branch-heads/<int:pk>/edit/', views.sales_head_branch_head_edit, name='sales_head_branch_head_edit'),
    path('manager/branch-heads/<int:pk>/toggle/', views.sales_head_branch_head_toggle_status, name='sales_head_branch_head_toggle_status'),
    path('manager/branch-heads/<int:pk>/password/', views.sales_head_branch_head_change_password, name='sales_head_branch_head_change_password'),

    # Branch Head's own portal
    path('manager/branch-head/dashboard/', views.branch_head_dashboard, name='branch_head_dashboard'),
    path('manager/branch-head/counselors/', views.branch_head_counselors_list, name='branch_head_counselors_list'),
    path('manager/branch-head/counselors/create/', views.branch_head_counselor_create, name='branch_head_counselor_create'),
    path('manager/branch-head/counselors/<int:pk>/', views.branch_head_counselor_detail, name='branch_head_counselor_detail'),
    path('manager/branch-head/counselors/<int:pk>/edit/', views.branch_head_counselor_edit, name='branch_head_counselor_edit'),
    path('manager/branch-head/counselors/<int:pk>/toggle/', views.branch_head_counselor_toggle_status, name='branch_head_counselor_toggle_status'),
    path('manager/branch-head/counselors/<int:pk>/password/', views.branch_head_counselor_change_password, name='branch_head_counselor_change_password'),
    path('manager/branch-head/telecallers/', views.branch_head_telecallers_list, name='branch_head_telecallers_list'),
]
