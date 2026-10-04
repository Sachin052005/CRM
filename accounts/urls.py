from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from . import hierarchy_views

urlpatterns = [
    path('login/', views.general_login, name='login'),
    path('login/redirect/', views.login_redirect, name='login_redirect'),
    path('logout/', views.logout_view, name='logout'),
    
    # Password Reset
    path('password-reset/', auth_views.PasswordResetView.as_view(
        template_name='registration/password_reset_form.html',
        email_template_name='registration/password_reset_email.html',
        subject_template_name='registration/password_reset_subject.txt',
    ), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='registration/password_reset_done.html'
    ), name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', auth_views.PasswordResetConfirmView.as_view(
        template_name='registration/password_reset_confirm.html'
    ), name='password_reset_confirm'),
    path('password-reset-complete/', auth_views.PasswordResetCompleteView.as_view(
        template_name='registration/password_reset_complete.html'
    ), name='password_reset_complete'),
    
    # Role-specific authentication routes
    path('admin/login/', views.admin_login, name='admin_login'),
    path('admin/logout/', views.logout_view, name='admin_logout'),
    
    path('manager/login/', views.manager_login, name='manager_login'),
    path('manager/register/', views.manager_register, name='manager_register'),
    path('manager/logout/', views.logout_view, name='manager_logout'),
    
    path('telecaller/login/', views.telecaller_login, name='telecaller_login'),
    path('telecaller/register/', views.telecaller_register, name='telecaller_register'),
    path('telecaller/logout/', views.logout_view, name='telecaller_logout'),

    # Progressive Hierarchy Routes (Levels 1 - 5)
    path('sales-heads/', hierarchy_views.hierarchy_sales_heads_list, name='hierarchy_sales_heads_list'),
    path('sales-heads/<int:sales_head_id>/branch-heads/', hierarchy_views.hierarchy_branch_heads_list, name='sales_head_branch_heads'),
    path('sales-heads/<int:sales_head_id>/branch-heads/view/', hierarchy_views.hierarchy_branch_heads_list, name='hierarchy_sales_head_branch_heads'),
    
    path('branch-heads/', hierarchy_views.hierarchy_branch_heads_list, name='hierarchy_branch_heads_list'),
    path('branch-heads/<int:branch_head_id>/counselors/', hierarchy_views.hierarchy_counselors_list, name='branch_head_counselors'),
    path('branch-heads/<int:branch_head_id>/counselors/view/', hierarchy_views.hierarchy_counselors_list, name='hierarchy_branch_head_counselors'),
    
    path('counselors/', hierarchy_views.hierarchy_counselors_list, name='hierarchy_counselors_list'),
    path('counselors/<int:counselor_id>/telecallers/', hierarchy_views.hierarchy_telecallers_list, name='counselor_telecallers'),
    path('counselors/<int:counselor_id>/telecallers/view/', hierarchy_views.hierarchy_telecallers_list, name='hierarchy_counselor_telecallers'),
    
    path('telecallers/', hierarchy_views.hierarchy_telecallers_list, name='hierarchy_telecallers_list'),
    path('telecallers/<int:telecaller_id>/leads/', hierarchy_views.hierarchy_telecaller_leads, name='telecaller_leads'),
    path('telecallers/<int:telecaller_id>/leads/view/', hierarchy_views.hierarchy_telecaller_leads, name='hierarchy_telecaller_leads'),
]
