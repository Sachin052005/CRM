from django.contrib import admin
from .models import Branch

@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'address', 'phone')
    ordering = ('name',)
