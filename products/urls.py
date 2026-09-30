from django.urls import path
from . import views

urlpatterns = [
    path('admin/products/', views.admin_products_list, name='admin_products_list'),
    path('admin/products/<int:pk>/edit/', views.admin_product_edit, name='admin_product_edit'),
    path('admin/products/<int:pk>/toggle/', views.admin_product_toggle_status, name='admin_product_toggle_status'),
]
