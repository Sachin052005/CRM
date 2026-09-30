from django.contrib import admin
from .models import DriveConnection, CallRecording


@admin.register(DriveConnection)
class DriveConnectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'folder_id', 'connection_status', 'last_sync_at', 'created_by', 'created_at')
    search_fields = ('name', 'folder_id', 'folder_url')
    list_filter = ('connection_status', 'created_at')


@admin.register(CallRecording)
class CallRecordingAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'mobile_number', 'normalized_mobile_number', 'match_status', 'lead', 'drive_connection', 'created_at')
    search_fields = ('file_name', 'mobile_number', 'normalized_mobile_number', 'drive_file_id')
    list_filter = ('match_status', 'drive_connection', 'created_at')
