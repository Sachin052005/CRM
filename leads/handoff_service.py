from django.core.exceptions import PermissionDenied
from django.db import transaction
from .models import LeadStatus, LeadOwnerType, LeadAssignmentHistory, LeadStatusHistory


def change_lead_status(lead, new_status, user, remarks=''):
    """Centralized status transition: validates permission, records history, updates the lead.
    May trigger an automatic telecaller->counselor handoff (see below)."""
    from accounts.permissions import can_change_lead_status
    if not can_change_lead_status(user, lead, new_status):
        raise PermissionDenied("You do not have permission to change this lead's status.")

    old_status = lead.status
    if old_status == new_status:
        return lead

    lead.status = new_status
    lead.save(update_fields=['status', 'updated_at'])

    LeadStatusHistory.objects.create(
        lead=lead,
        old_status=old_status,
        new_status=new_status,
        changed_by=user if getattr(user, 'is_authenticated', False) else None,
        remarks=remarks,
    )

    if new_status == LeadStatus.VISIT_SCHEDULED and not lead.assigned_counselor_id:
        auto_handoff_lead_to_counselor(lead, triggered_by=user)

    return lead


def reassign_lead(lead, *, to_user, to_role, reason='', assigned_by, _skip_permission_check=False):
    """Generic reassignment across any of the four assignable roles.
    to_role must be one of: 'TELECALLER', 'COUNSELOR', 'BRANCH_HEAD', 'SALES_HEAD'.
    Enforces branch scope via can_reassign_lead (Admin may override across branches).
    _skip_permission_check is for internal automated transitions only (see
    auto_handoff_lead_to_counselor) - the caller there was already permission-checked
    for the status change that triggered this side effect."""
    from accounts.permissions import can_reassign_lead

    if not _skip_permission_check and not can_reassign_lead(assigned_by, lead, to_user):
        raise PermissionDenied("You do not have permission to reassign this lead to that user.")

    field_map = {
        'TELECALLER': 'assigned_telecaller',
        'COUNSELOR': 'assigned_counselor',
        'BRANCH_HEAD': 'assigned_branch_head',
        'SALES_HEAD': 'assigned_sales_head',
    }
    owner_type_map = {
        'TELECALLER': LeadOwnerType.TELECALLER,
        'COUNSELOR': LeadOwnerType.COUNSELOR,
        'BRANCH_HEAD': LeadOwnerType.BRANCH_HEAD,
        'SALES_HEAD': LeadOwnerType.SALES_HEAD,
    }
    field_name = field_map[to_role]
    # "from" reflects the lead's actual current owner (by current_owner_type), not merely
    # the prior value of the target field - which may never have been set before (e.g. a
    # first telecaller->counselor handoff finds assigned_counselor empty even though the
    # telecaller was the real previous owner).
    current_owner_field = field_map.get(lead.current_owner_type)
    from_user = getattr(lead, current_owner_field) if current_owner_field else None
    from_role = lead.current_owner_type if from_user else ''

    with transaction.atomic():
        setattr(lead, field_name, to_user)
        lead.current_owner_type = owner_type_map[to_role]
        lead.save(update_fields=[field_name, 'current_owner_type', 'updated_at'])

        LeadAssignmentHistory.objects.create(
            lead=lead,
            from_user=from_user,
            to_user=to_user,
            from_role=from_role,
            to_role=to_role,
            branch=lead.branch,
            reason=reason,
            assigned_by=assigned_by if getattr(assigned_by, 'is_authenticated', False) else None,
        )

    return lead


def unassign_lead(lead, *, unassigned_by, reason='Unassigned'):
    """Removes the current Telecaller assignment from a lead without deleting it.
    The lead, its branch, channel/source and duplicate history are all preserved - only the
    assignment is cleared and the lead returns to a Pending Assignment state so it can be
    picked up again. Mirrors reassign_lead's permission check and audit trail so unassignment
    and reassignment stay consistent (one shared service, not duplicated per-view logic)."""
    from accounts.permissions import can_assign_lead

    if not can_assign_lead(unassigned_by, lead):
        raise PermissionDenied("You do not have permission to unassign this lead.")

    from_user = lead.assigned_telecaller
    from_role = lead.current_owner_type if from_user else ''

    with transaction.atomic():
        lead.assigned_telecaller = None
        lead.assignment_status = 'Pending Assignment'
        lead.pending_assignment_reason = reason
        lead.current_owner_type = LeadOwnerType.UNASSIGNED
        lead.save(update_fields=[
            'assigned_telecaller', 'assignment_status', 'pending_assignment_reason',
            'current_owner_type', 'updated_at',
        ])

        LeadAssignmentHistory.objects.create(
            lead=lead,
            from_user=from_user,
            to_user=None,
            from_role=from_role,
            to_role='',
            branch=lead.branch,
            reason=reason,
            assigned_by=unassigned_by if getattr(unassigned_by, 'is_authenticated', False) else None,
        )

    return lead


def handoff_to_counselor(lead, counselor, assigned_by, reason='Telecaller handoff'):
    """Explicit telecaller -> counselor handoff. Keeps assigned_telecaller intact for traceability."""
    return reassign_lead(lead, to_user=counselor, to_role='COUNSELOR', reason=reason, assigned_by=assigned_by)


def auto_handoff_lead_to_counselor(lead, triggered_by=None):
    """Round-robin auto-select the least-loaded active Counselor in the lead's branch and hand off.
    No-op (returns None) if there's no branch or no active counselor available - does NOT raise,
    since this is called automatically from a status change and must never block that transition."""
    from django.db.models import Count
    from accounts.models import User, UserRole

    if not lead.branch_id:
        return None
    candidate = (
        User.objects.filter(role=UserRole.COUNSELOR, branch_id=lead.branch_id, is_active=True)
        .annotate(cnt=Count('counselor_leads'))
        .order_by('cnt', 'id')
        .first()
    )
    if not candidate:
        return None
    return reassign_lead(
        lead,
        to_user=candidate,
        to_role='COUNSELOR',
        reason='Automatic handoff on Visit Scheduled',
        assigned_by=triggered_by or candidate,
        _skip_permission_check=True,
    )
