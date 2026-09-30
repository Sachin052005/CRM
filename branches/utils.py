from .models import Branch

SESSION_BRANCH_KEY = 'selected_branch_id'

def get_admin_selected_branch(request):
    """
    Returns the Branch instance if a specific branch is selected in admin session,
    or None if 'All Branches' is selected or no valid branch selected.
    """
    if not request.user.is_authenticated or not getattr(request.user, 'is_admin_user', False):
        return None

    branch_id = request.session.get(SESSION_BRANCH_KEY)
    if not branch_id or str(branch_id).lower() == 'all':
        return None

    try:
        return Branch.objects.filter(pk=int(branch_id), status=Branch.Status.ACTIVE).first()
    except (ValueError, TypeError):
        return None

def set_admin_selected_branch(request, branch_id):
    """
    Stores selected branch in the session.
    'all' or empty string clears the selection.
    """
    if not branch_id or str(branch_id).lower() == 'all':
        request.session[SESSION_BRANCH_KEY] = 'all'
    else:
        try:
            branch = Branch.objects.filter(pk=int(branch_id)).first()
            if branch:
                request.session[SESSION_BRANCH_KEY] = branch.pk
            else:
                request.session[SESSION_BRANCH_KEY] = 'all'
        except (ValueError, TypeError):
            request.session[SESSION_BRANCH_KEY] = 'all'
