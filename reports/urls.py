from django.urls import path
from . import views

urlpatterns = [
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/reports/', views.admin_reports, name='admin_reports'),
    path('manager/reports/', views.manager_reports, name='manager_reports'),
]
