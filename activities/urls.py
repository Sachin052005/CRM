from django.urls import path
from . import views

urlpatterns = [
    path('admin/activities/', views.admin_activities_list, name='admin_activities_list'),
    path('manager/activities/', views.manager_activities_list, name='manager_activities_list'),
    path('telecaller/activities/', views.telecaller_activities_list, name='telecaller_activities_list'),
    
    # Notification API
    path('notifications/latest/', views.get_notifications_api, name='get_notifications_api'),
    path('notifications/<int:pk>/mark-read/', views.mark_notification_read_api, name='mark_notification_read_api'),
    path('notifications/mark-all-read/', views.mark_all_notifications_read_api, name='mark_all_notifications_read_api'),
]
