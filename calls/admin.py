from django.contrib import admin
from .models import CallHistory

@admin.register(CallHistory)
class CallHistoryAdmin(admin.ModelAdmin):
    list_display = ('lead', 'caller', 'manager', 'telecaller', 'duration', 'call_status', 'call_outcome', 'call_started_at')
    list_filter = ('call_status', 'call_outcome', 'manager', 'telecaller', 'call_started_at')
    search_fields = ('lead__name', 'lead__phone', 'caller__username', 'notes')
    ordering = ('-call_started_at',)
