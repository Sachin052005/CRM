from django.contrib import admin
from .models import Activity

@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'object_type', 'object_id', 'ip_address')
    list_filter = ('action', 'object_type', 'timestamp')
    search_fields = ('user__username', 'description', 'ip_address')
    ordering = ('-timestamp',)
