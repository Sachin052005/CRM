from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Count
from django.core.paginator import Paginator
from accounts.permissions import admin_required
from .models import Product
from .forms import ProductForm
from activities.utils import log_activity

@admin_required
def admin_products_list(request):
    """
    Products page removed as per requirement. Cleanly redirects to Admin Dashboard.
    Database table products_product is preserved.
    """
    return redirect('admin_dashboard')

    products_qs = Product.objects.annotate(lead_count=Count('leads'))

    if search_query:
        products_qs = products_qs.filter(name__icontains=search_query)
    if status_filter:
        products_qs = products_qs.filter(status=status_filter)

    products_qs = products_qs.order_by('name')
    paginator = Paginator(products_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    form = ProductForm()
    if request.method == 'POST' and request.POST.get('action') == 'create':
        form = ProductForm(request.POST)
        if form.is_valid():
            prod = form.save()
            log_activity(
                user=request.user,
                action="Product Created",
                description=f"Created product/course: '{prod.name}'",
                object_type="Product",
                object_id=prod.pk,
                request=request
            )
            messages.success(request, f"Product '{prod.name}' created successfully.")
            return redirect('admin_products_list')

    return render(request, 'admin/products_list.html', {
        'page_obj': page_obj,
        'form': form,
        'search_query': search_query,
        'status_filter': status_filter,
    })

@admin_required
def admin_product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Product Updated",
                description=f"Updated product '{product.name}'.",
                object_type="Product",
                object_id=product.pk,
                request=request
            )
            messages.success(request, f"Product '{product.name}' updated.")
            return redirect('admin_products_list')
    else:
        form = ProductForm(instance=product)

    return render(request, 'admin/product_form.html', {'form': form, 'product': product})

@admin_required
def admin_product_toggle_status(request, pk):
    product = get_object_or_404(Product, pk=pk)
    old_status = product.status
    product.status = 'Inactive' if old_status == 'Active' else 'Active'
    product.save()

    log_activity(
        user=request.user,
        action="Product Status Changed",
        description=f"Product '{product.name}' changed from {old_status} to {product.status}.",
        object_type="Product",
        object_id=product.pk,
        request=request
    )
    messages.success(request, f"Product '{product.name}' status is now {product.status}.")
    return redirect('admin_products_list')
