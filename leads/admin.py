from django.contrib import admin
from .models import Lead, LeadImportHistory, LeadAssignmentHistory, LeadStatusHistory

@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'email', 'channel', 'status', 'current_owner_type', 'assigned_sales_head', 'assigned_telecaller', 'assigned_counselor', 'created_at')
    list_filter = ('status', 'current_owner_type', 'channel', 'assigned_sales_head', 'assigned_telecaller', 'assigned_counselor', 'created_at')
    search_fields = ('name', 'phone', 'email', 'notes')
    ordering = ('-created_at',)

@admin.register(LeadImportHistory)
class LeadImportHistoryAdmin(admin.ModelAdmin):
    list_display = ('file_name', 'uploaded_by', 'uploaded_on', 'records', 'successful', 'failed', 'status')
    list_filter = ('status', 'uploaded_on')
    search_fields = ('file_name',)
    ordering = ('-uploaded_on',)

@admin.register(LeadAssignmentHistory)
class LeadAssignmentHistoryAdmin(admin.ModelAdmin):
    list_display = ('lead', 'from_role', 'to_role', 'from_user', 'to_user', 'branch', 'assigned_by', 'created_at')
    list_filter = ('from_role', 'to_role', 'branch', 'created_at')
    search_fields = ('lead__name', 'lead__phone', 'reason')
    ordering = ('-created_at',)

@admin.register(LeadStatusHistory)
class LeadStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('lead', 'old_status', 'new_status', 'changed_by', 'created_at')
    list_filter = ('old_status', 'new_status', 'created_at')
    search_fields = ('lead__name', 'lead__phone', 'remarks')
    ordering = ('-created_at',)
