from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Count
from django.core.paginator import Paginator
from accounts.permissions import admin_required
from django.views.decorators.http import require_POST
from .models import Branch
from .forms import BranchForm
from .utils import set_admin_selected_branch
from activities.utils import log_activity

@admin_required
def admin_branches_list(request):
    search_query = request.GET.get('search', '').strip()
    status_filter = request.GET.get('status', '').strip()

    branches_qs = Branch.objects.annotate(lead_count=Count('leads'))

    if search_query:
        branches_qs = branches_qs.filter(name__icontains=search_query)
    if status_filter:
        branches_qs = branches_qs.filter(status=status_filter)

    branches_qs = branches_qs.order_by('name')
    paginator = Paginator(branches_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))

    form = BranchForm()
    if request.method == 'POST' and request.POST.get('action') == 'create':
        form = BranchForm(request.POST)
        if form.is_valid():
            branch = form.save()
            log_activity(
                user=request.user,
                action="Branch Created",
                description=f"Created branch office: '{branch.name}'",
                object_type="Branch",
                object_id=branch.pk,
                request=request
            )
            messages.success(request, f"Branch '{branch.name}' created successfully.")
            return redirect('admin_branches_list')

    return render(request, 'admin/branches_list.html', {
        'page_obj': page_obj,
        'form': form,
        'search_query': search_query,
        'status_filter': status_filter,
    })

@admin_required
def admin_branch_edit(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    if request.method == 'POST':
        form = BranchForm(request.POST, instance=branch)
        if form.is_valid():
            form.save()
            log_activity(
                user=request.user,
                action="Branch Updated",
                description=f"Updated branch '{branch.name}'.",
                object_type="Branch",
                object_id=branch.pk,
                request=request
            )
            messages.success(request, f"Branch '{branch.name}' updated.")
            return redirect('admin_branches_list')
    else:
        form = BranchForm(instance=branch)

    return render(request, 'admin/branch_form.html', {'form': form, 'branch': branch})

@admin_required
def admin_branch_toggle_status(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    old_status = branch.status
    branch.status = 'Inactive' if old_status == 'Active' else 'Active'
    branch.save()

    log_activity(
        user=request.user,
        action="Branch Status Changed",
        description=f"Branch '{branch.name}' changed from {old_status} to {branch.status}.",
        object_type="Branch",
        object_id=branch.pk,
        request=request
    )
    messages.success(request, f"Branch '{branch.name}' status is now {branch.status}.")
    return redirect('admin_branches_list')

@admin_required
@require_POST
def set_active_branch(request):
    branch_id = request.POST.get('branch_id')
    set_admin_selected_branch(request, branch_id)
    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'admin_dashboard'
    return redirect(next_url)

