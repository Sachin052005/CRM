from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'counselor', 'branch', 'is_active')
    list_filter = ('role', 'is_active', 'branch', 'date_joined')
    search_fields = ('username', 'email', 'first_name', 'last_name', 'phone')
    ordering = ('username',)

    fieldsets = BaseUserAdmin.fieldsets + (
        ('CRM Attributes', {'fields': ('role', 'phone', 'counselor', 'branch')}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ('CRM Attributes', {'fields': ('role', 'phone', 'counselor', 'branch')}),
    )
