from django.contrib import admin
from .models import FollowUp

@admin.register(FollowUp)
class FollowUpAdmin(admin.ModelAdmin):
    list_display = ('lead', 'manager', 'telecaller', 'follow_up_date', 'follow_up_time', 'status')
    list_filter = ('status', 'follow_up_date', 'manager', 'telecaller')
    search_fields = ('lead__name', 'lead__phone', 'notes')
    ordering = ('follow_up_date', 'follow_up_time')
