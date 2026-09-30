import logging
from django.db import transaction
from django.db.models import F, Count, Q
from django.utils import timezone
from accounts.models import User, UserRole
from branches.models import Branch
from activities.utils import log_activity

logger = logging.getLogger('crm')


def assign_new_lead(lead, branch=None, source="Google Sheet", triggered_by=None) -> bool:
    """
    Single Centralized Lead Assignment Engine across all sources:
    - Google Sheets (Offline, Instagram, Facebook, future spreadsheets)
    - Google Form
    - Manual Import / Creation

    Rules:
    1. Identify the target branch.
    2. Load the latest valid saved allocation configuration (TelecallerLeadSetup).
    3. Select ONLY checked, active telecallers (is_active=True).
    4. Confirm that selected percentages total exactly 100%.
    5. If no valid 100% configuration exists, mark lead as 'Pending Assignment' and record reason.
    6. Calculate target share using weighted cumulative distribution (largest positive allocation gap).
    7. Atomically assign lead to selected telecaller and their manager.
    8. Update telecaller's current_leads_assigned counter.
    9. Record assignment in CRM Activity logs.
    """
    from .models import LeadSetupConfig, TelecallerLeadSetup, AssignmentMethod, LeadOwnerType, LeadAssignmentHistory

    target_branch = branch or getattr(lead, 'branch', None)
    if not target_branch:
        lead.assignment_status = 'Pending Assignment'
        lead.pending_assignment_reason = 'Lead does not have an assigned branch.'
        lead.assigned_telecaller = None
        if lead.pk:
            lead.save(update_fields=['assignment_status', 'pending_assignment_reason', 'assigned_telecaller', 'updated_at'])
        else:
            lead.save()
        log_activity(
            user=triggered_by,
            action="Lead Assignment Pending",
            description=f"Lead '{lead.name}' marked Pending Assignment: Missing branch.",
            object_type="Lead",
            object_id=getattr(lead, 'pk', None)
        )
        return False

    with transaction.atomic():
        # Query active telecallers belonging to this branch with is_active=True in setup
        setups = list(
            TelecallerLeadSetup.objects.select_for_update()
            .filter(
                branch=target_branch,
                is_active=True,
                telecaller__is_active=True,
                telecaller__role=UserRole.TELECALLER
            )
            .select_related('telecaller', 'telecaller__branch')
        )

        method = LeadSetupConfig.get_current_method()

        # Check percentage-based distribution
        if method == AssignmentMethod.PERCENTAGE:
            valid_setups = [s for s in setups if s.assignment_percentage > 0]
            total_pct = sum(s.assignment_percentage for s in valid_setups)

            # Strict 100% check
            if not valid_setups:
                lead.branch = target_branch
                lead.assignment_status = 'Pending Assignment'
                lead.pending_assignment_reason = f"No active telecallers or allocation configured for branch '{target_branch.name}'."
                lead.assigned_telecaller = None
                if lead.pk:
                    lead.save(update_fields=['branch', 'assignment_status', 'pending_assignment_reason', 'assigned_telecaller', 'updated_at'])
                else:
                    lead.save()
                log_activity(
                    user=triggered_by,
                    action="Lead Assignment Pending",
                    description=f"Lead '{lead.name}' marked Pending Assignment: No active telecallers or allocation configured for branch '{target_branch.name}'.",
                    object_type="Lead",
                    object_id=getattr(lead, 'pk', None)
                )
                return False

            if total_pct != 100:
                lead.branch = target_branch
                lead.assignment_status = 'Pending Assignment'
                lead.pending_assignment_reason = f"Branch '{target_branch.name}' telecaller allocation total is {total_pct}% (must equal exactly 100%)."
                lead.assigned_telecaller = None
                if lead.pk:
                    lead.save(update_fields=['branch', 'assignment_status', 'pending_assignment_reason', 'assigned_telecaller', 'updated_at'])
                else:
                    lead.save()
                log_activity(
                    user=triggered_by,
                    action="Lead Assignment Pending",
                    description=f"Lead '{lead.name}' marked Pending Assignment: Branch '{target_branch.name}' allocation total is {total_pct}% (must equal 100%).",
                    object_type="Lead",
                    object_id=getattr(lead, 'pk', None)
                )
                return False

            # Strict Weighted Distribution Algorithm (Largest Positive Allocation Gap)
            # Cumulative total assigned to the active allocation group
            total_assigned = sum(s.current_leads_assigned for s in valid_setups)
            next_total = total_assigned + 1

            def allocation_score(s):
                target_count = next_total * (s.assignment_percentage / 100.0)
                actual_count = s.current_leads_assigned
                gap = target_count - actual_count
                # Tie breakers: larger gap, higher percentage, lower current count, lower id
                return (gap, s.assignment_percentage, -s.current_leads_assigned, -s.id)

            best_setup = max(valid_setups, key=allocation_score)
            selected_telecaller = best_setup.telecaller

        elif method == AssignmentMethod.COUNT:
            # Number of leads based
            valid_setups = [s for s in setups if s.lead_count > 0]
            if not valid_setups:
                lead.branch = target_branch
                lead.assignment_status = 'Pending Assignment'
                lead.pending_assignment_reason = f"No active telecallers with lead quota in branch '{target_branch.name}'."
                lead.assigned_telecaller = None
                if lead.pk:
                    lead.save(update_fields=['branch', 'assignment_status', 'pending_assignment_reason', 'assigned_telecaller', 'updated_at'])
                else:
                    lead.save()
                return False

            # Pick telecaller below quota with lowest assigned count
            below_quota = [s for s in valid_setups if s.current_leads_assigned < s.lead_count]
            if below_quota:
                below_quota.sort(key=lambda s: (s.current_leads_assigned, -s.lead_count, s.id))
                best_setup = below_quota[0]
            else:
                valid_setups.sort(key=lambda s: (s.current_leads_assigned, s.id))
                best_setup = valid_setups[0]
            selected_telecaller = best_setup.telecaller
        else:
            best_setup = setups[0] if setups else None
            selected_telecaller = best_setup.telecaller if best_setup else None

        if not selected_telecaller:
            lead.branch = target_branch
            lead.assignment_status = 'Pending Assignment'
            lead.pending_assignment_reason = f"Could not determine eligible telecaller for branch '{target_branch.name}'."
            lead.assigned_telecaller = None
            if lead.pk:
                lead.save(update_fields=['branch', 'assignment_status', 'pending_assignment_reason', 'assigned_telecaller', 'updated_at'])
            else:
                lead.save()
            return False

        # Identify assigned manager (Sales Head with access to this branch)
        selected_manager = User.objects.filter(
            role=UserRole.SALES_HEAD,
            branch_access__branch=target_branch,
            is_active=True
        ).annotate(cnt=Count('manager_leads')).order_by('cnt', 'id').first()
        if not selected_manager:
            selected_manager = User.objects.filter(role=UserRole.SALES_HEAD, is_active=True).first()

        # Update Lead atomically
        previous_telecaller = lead.assigned_telecaller if lead.pk else None
        lead.branch = target_branch
        lead.assigned_telecaller = selected_telecaller
        lead.assigned_sales_head = selected_manager
        lead.current_owner_type = LeadOwnerType.TELECALLER
        lead.assignment_status = 'Assigned'
        lead.pending_assignment_reason = ''
        lead.assigned_at = timezone.now()
        if lead.pk:
            lead.save(update_fields=[
                'branch',
                'assigned_telecaller',
                'assigned_sales_head',
                'current_owner_type',
                'assignment_status',
                'pending_assignment_reason',
                'assigned_at',
                'updated_at'
            ])
        else:
            lead.save()

        LeadAssignmentHistory.objects.create(
            lead=lead,
            from_user=previous_telecaller,
            to_user=selected_telecaller,
            from_role=UserRole.TELECALLER if previous_telecaller else '',
            to_role=UserRole.TELECALLER,
            branch=target_branch,
            reason=source,
            assigned_by=triggered_by if getattr(triggered_by, 'is_authenticated', False) else None,
        )

        # Atomically increment telecaller's assignment counter
        TelecallerLeadSetup.objects.filter(pk=best_setup.pk).update(
            current_leads_assigned=F('current_leads_assigned') + 1,
            updated_at=timezone.now()
        )

        tc_name = selected_telecaller.get_full_name() or selected_telecaller.username
        mgr_name = selected_manager.get_full_name() or selected_manager.username if selected_manager else "Unassigned"

        log_activity(
            user=triggered_by or selected_manager,
            action="Lead Auto-Assigned",
            description=f"Lead '{lead.name}' auto-assigned to Branch '{target_branch.name}' Telecaller '{tc_name}' (Manager: {mgr_name}) via {source}.",
            object_type="Lead",
            object_id=lead.pk
        )
        return True


def assign_lead_to_branch_telecaller(lead, branch=None, source="Google Form", triggered_by=None):
    """
    Backwards-compatible wrapper delegating to the unified assign_new_lead engine.
    """
    target_branch = branch or getattr(lead, 'branch', None)
    if target_branch and getattr(lead, 'branch', None) != target_branch:
        lead.branch = target_branch
        lead.save(update_fields=['branch'])
    return assign_new_lead(lead, branch=target_branch, source=source, triggered_by=triggered_by)


def assign_lead_automatically(lead, branch=None, source="Import", triggered_by=None):
    """
    Backwards-compatible wrapper delegating to the unified assign_new_lead engine.
    """
    target_branch = branch or getattr(lead, 'branch', None)
    if target_branch and getattr(lead, 'branch', None) != target_branch:
        lead.branch = target_branch
        lead.save(update_fields=['branch'])
    return assign_new_lead(lead, branch=target_branch, source=source, triggered_by=triggered_by)


def retry_pending_assignments(branch=None, user=None) -> tuple[int, int]:
    """
    Retries assignment for all leads currently marked 'Pending Assignment' or unassigned.
    Returns: (newly_assigned_count, still_pending_count)
    """
    from .models import Lead

    pending_qs = Lead.objects.filter(
        Q(assignment_status='Pending Assignment') |
        Q(assigned_telecaller__isnull=True, assignment_status__in=['Pending Assignment', 'Unassigned'])
    )
    if branch:
        pending_qs = pending_qs.filter(Q(branch=branch) | Q(branch__isnull=True))

    assigned_count = 0
    still_pending_count = 0

    for lead in pending_qs:
        target_b = lead.branch or branch
        success = assign_new_lead(lead, branch=target_b, source="Retry Assignment", triggered_by=user)
        if success:
            assigned_count += 1
        else:
            still_pending_count += 1

    return assigned_count, still_pending_count


def apply_branch_lead_distribution(branch, user=None) -> tuple[int, int, str]:
    """
    Applies strict percentage-based distribution to all available leads in the specified branch.
    Available leads include:
    - Leads in the branch (or unassigned branch leads)
    - Excluding protected leads (leads in progress, follow-up, demo scheduled, converted, lost, or having existing calls/followups)
    - Unassigned leads, pending assignment leads, or fresh/new leads
    
    Guarantees:
    - Exactly reflects the configured percentages across all available leads in the database.
    - Saves assignments directly to Lead.assigned_telecaller, Lead.assigned_sales_head, Lead.assignment_status='Assigned'.
    - Updates telecaller current_leads_assigned counters.
    - Preserves all protected leads.
    """
    from .models import Lead, LeadStatus, TelecallerLeadSetup, AssignmentMethod, LeadSetupConfig, LeadOwnerType, LeadAssignmentHistory

    if not branch:
        return 0, 0, "No branch provided."

    with transaction.atomic():
        valid_setups = list(
            TelecallerLeadSetup.objects.select_for_update()
            .filter(
                branch=branch,
                is_active=True,
                assignment_percentage__gt=0,
                telecaller__is_active=True,
                telecaller__role=UserRole.TELECALLER
            )
            .select_related('telecaller', 'telecaller__branch')
            .order_by('id')
        )

        if not valid_setups:
            unassigned_qs = Lead.objects.filter(
                Q(branch=branch) | Q(branch__isnull=True)
            ).filter(
                Q(assigned_telecaller__isnull=True) | Q(assignment_status='Pending Assignment')
            )
            count = unassigned_qs.count()
            unassigned_qs.update(
                branch=branch,
                assignment_status='Pending Assignment',
                pending_assignment_reason=f"No active telecallers or allocation configured for branch '{branch.name}'."
            )
            return 0, count, f"No active telecallers or allocation configured for branch '{branch.name}'."

        total_pct = sum(s.assignment_percentage for s in valid_setups)
        if total_pct != 100:
            unassigned_qs = Lead.objects.filter(
                Q(branch=branch) | Q(branch__isnull=True)
            ).filter(
                Q(assigned_telecaller__isnull=True) | Q(assignment_status='Pending Assignment')
            )
            count = unassigned_qs.count()
            unassigned_qs.update(
                branch=branch,
                assignment_status='Pending Assignment',
                pending_assignment_reason=f"Branch '{branch.name}' telecaller allocation total is {total_pct}% (must equal exactly 100%)."
            )
            return 0, count, f"Total percentage allocation for branch '{branch.name}' is {total_pct}% (must equal 100%)."

        # Protected statuses that MUST NOT be reassigned
        protected_statuses = [
            LeadStatus.CONTACTED,
            LeadStatus.INTERESTED,
            LeadStatus.FOLLOW_UP,
            LeadStatus.DEMO_SCHEDULED,
            LeadStatus.INSTITUTE_VISIT,
            LeadStatus.CONVERTED,
            LeadStatus.LOST,
            LeadStatus.LATER,
            LeadStatus.DISCUSSION
        ]

        # Query eligible leads for this branch
        available_leads = list(
            Lead.objects.select_for_update()
            .filter(
                Q(branch=branch) | Q(branch__isnull=True)
            )
            .exclude(status__in=protected_statuses)
            .exclude(calls__isnull=False)
            .exclude(followups__isnull=False)
            .filter(
                Q(assigned_telecaller__isnull=True) |
                Q(assignment_status__in=['Pending Assignment', 'Unassigned']) |
                Q(status=LeadStatus.NEW)
            )
            .distinct()
            .order_by('id')
        )

        if not available_leads:
            return 0, 0, f"No available leads to distribute for branch '{branch.name}'."

        # Reset current_leads_assigned counters so this batch distribution precisely allocates by percentage
        for s in valid_setups:
            s.current_leads_assigned = 0
        TelecallerLeadSetup.objects.filter(id__in=[s.id for s in valid_setups]).update(current_leads_assigned=0)

        now = timezone.now()
        assigned_count = 0

        for lead in available_leads:
            next_total = sum(s.current_leads_assigned for s in valid_setups) + 1
            best_setup = max(valid_setups, key=lambda s: (
                next_total * (s.assignment_percentage / 100.0) - s.current_leads_assigned,
                s.assignment_percentage,
                -s.current_leads_assigned,
                -s.id
            ))
            selected_tc = best_setup.telecaller
            selected_mgr = User.objects.filter(
                role=UserRole.SALES_HEAD, branch_access__branch=branch, is_active=True
            ).first()

            previous_telecaller = lead.assigned_telecaller
            lead.branch = branch
            lead.assigned_telecaller = selected_tc
            lead.assigned_sales_head = selected_mgr
            lead.current_owner_type = LeadOwnerType.TELECALLER
            lead.assignment_status = 'Assigned'
            lead.pending_assignment_reason = ''
            lead.assigned_at = now
            lead.save(update_fields=[
                'branch',
                'assigned_telecaller',
                'assigned_sales_head',
                'current_owner_type',
                'assignment_status',
                'pending_assignment_reason',
                'assigned_at',
                'updated_at'
            ])

            LeadAssignmentHistory.objects.create(
                lead=lead,
                from_user=previous_telecaller,
                to_user=selected_tc,
                from_role=UserRole.TELECALLER if previous_telecaller else '',
                to_role=UserRole.TELECALLER,
                branch=branch,
                reason='Batch Lead Distribution',
                assigned_by=user if getattr(user, 'is_authenticated', False) else None,
            )

            best_setup.current_leads_assigned += 1
            assigned_count += 1

        for s in valid_setups:
            s.save(update_fields=['current_leads_assigned', 'updated_at'])

        log_activity(
            user=user,
            action="Batch Lead Distribution",
            description=f"Admin applied lead assignment for branch '{branch.name}': {assigned_count} leads distributed across {len(valid_setups)} telecallers.",
            object_type="Branch",
            object_id=branch.pk
        )

        return assigned_count, 0, f"Successfully distributed {assigned_count} leads for branch '{branch.name}'."
