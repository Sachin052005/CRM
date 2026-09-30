from django.urls import path
from . import views

urlpatterns = [
    # Admin counselor oversight
    path('admin/counselors/', views.admin_counselors_list, name='admin_counselors_list'),

    # Counselor portal
    path('counselor/dashboard/', views.counselor_dashboard, name='counselor_dashboard'),
    path('counselor/telecallers/', views.counselor_telecallers_list, name='counselor_telecallers_list'),
]
