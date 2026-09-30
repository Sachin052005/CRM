from django.contrib import admin
from .models import Product

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('name', 'description')
    ordering = ('name',)
