from django.contrib import admin
from .models import Lead, LeadImportHistory

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'email', 'channel', 'status', 'assigned_manager', 'assigned_telecaller', 'created_at')
    list_filter = ('status', 'channel', 'assigned_manager', 'assigned_telecaller', 'created_at')
    search_fields = ('name', 'phone', 'email', 'notes')
    ordering = ('-created_at',)

@admin.register(LeadImportHistory)
class LeadImportHistoryAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'uploaded_by', 'uploaded_on', 'records', 'successful', 'failed', 'status')
    list_filter = ('status', 'uploaded_on')
    search_fields = ('file_name',)
    ordering = ('-uploaded_on',)
