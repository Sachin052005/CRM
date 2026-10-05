from django.urls import path
from . import views

urlpatterns = [
    path('', views.drive_dashboard, name='drive_dashboard'),
    path('connect/', views.drive_connect, name='drive_connect'),
    path('sync/<int:connection_id>/', views.drive_sync, name='drive_sync'),
    path('disconnect/<int:connection_id>/', views.drive_disconnect, name='drive_disconnect'),
    path('retry-matching/', views.drive_retry_matching, name='drive_retry_matching'),
    path('stream/<int:recording_id>/', views.drive_stream_recording, name='drive_stream_recording'),
    path('api/sync/<int:connection_id>/', views.drive_api_sync, name='drive_api_sync'),
    path('api/status/', views.drive_api_status, name='drive_api_status'),
]
