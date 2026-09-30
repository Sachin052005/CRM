from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError

class LeadStatus(models.TextChoices):
    NEW = 'New', 'New'
    CONTACTED = 'Contacted', 'Contacted'
    INTERESTED = 'Interested', 'Interested'
    FOLLOW_UP = 'Follow-up', 'Follow-up'
    DEMO_SCHEDULED = 'Demo Scheduled', 'Demo Scheduled'
    INSTITUTE_VISIT = 'Institute Visit', 'Institute Visit'
    CONVERTED = 'Converted', 'Converted'
    LOST = 'Lost', 'Lost'
    LATER = 'Later', 'Later'
    DISCUSSION = 'Discussion', 'Discussion'
    VISIT_SCHEDULED = 'Visit Scheduled', 'Visit Scheduled'
    VISITED = 'Visited', 'Visited'
    COUNSELING = 'Counseling', 'Counseling'
    JOINED = 'Joined', 'Joined'
    NOT_INTERESTED = 'Not Interested', 'Not Interested'
    NO_ANSWER = 'No Answer', 'No Answer'
    BUSY = 'Busy', 'Busy'
    NOT_JOINED = 'Not Joined', 'Not Joined'

class LeadOwnerType(models.TextChoices):
    UNASSIGNED = 'UNASSIGNED', 'Unassigned'
    TELECALLER = 'TELECALLER', 'Telecaller'
    COUNSELOR = 'COUNSELOR', 'Counselor'
    BRANCH_HEAD = 'BRANCH_HEAD', 'Branch Head'
    SALES_HEAD = 'SALES_HEAD', 'Sales Head'
    ADMIN = 'ADMIN', 'Admin'

class Lead(models.Model):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, default='')
    alternate_phone = models.CharField(max_length=20, blank=True, default='')
    channel = models.ForeignKey(
        'channels.Channel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leads'
    )
    status = models.CharField(
        max_length=30,
        choices=LeadStatus.choices,
        default=LeadStatus.NEW
    )
    assigned_sales_head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_leads'
    )
    assigned_telecaller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='telecaller_leads'
    )
    assigned_branch_head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='branch_head_leads',
        limit_choices_to={'role': 'BRANCH_HEAD'}
    )
    assigned_counselor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='counselor_leads',
        limit_choices_to={'role': 'COUNSELOR'}
    )
    current_owner_type = models.CharField(
        max_length=20,
        choices=LeadOwnerType.choices,
        default=LeadOwnerType.UNASSIGNED,
        db_index=True
    )
    product = models.ForeignKey(
        'products.Product',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leads'
    )
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='leads'
    )
    secondary_branches = models.ManyToManyField(
        'branches.Branch',
        blank=True,
        related_name='multi_branch_leads',
        help_text="Additional branches where this lead has appeared"
    )
    notes = models.TextField(blank=True, default='')
    source = models.CharField(max_length=50, default='Manual', blank=True, db_index=True)
    is_offline = models.BooleanField(default=False, db_index=True)
    assignment_status = models.CharField(
        max_length=50,
        default='Assigned',
        blank=True,
        db_index=True,
        help_text="Status of assignment: Assigned, Pending Assignment, or Unassigned"
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    pending_assignment_reason = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.phone} ({self.status})"

    @property
    def assigned_manager(self):
        """Backward-compat read-only alias for templates not yet updated to assigned_sales_head."""
        return self.assigned_sales_head

    @property
    def masked_phone(self):
        if not self.phone:
            return ''
        digits = str(self.phone).strip()
        if len(digits) >= 5:
            return f"{digits[:5]}xxxxx"
        return digits

    def get_all_branches(self):
        branches_list = []
        if self.branch:
            branches_list.append(self.branch)
        for b in self.secondary_branches.all():
            if b not in branches_list:
                branches_list.append(b)
        return branches_list

    def get_all_branch_names(self):
        return [b.name for b in self.get_all_branches()]

    def get_source_spreadsheets(self):
        from .models import GoogleSheetConnection
        conns = list(GoogleSheetConnection.objects.filter(row_mappings__lead=self).distinct())
        if not conns and self.source:
            conn_by_name = GoogleSheetConnection.objects.filter(name__iexact=self.source).first()
            if conn_by_name:
                conns.append(conn_by_name)
        return conns

    @property
    def source_spreadsheet_names(self):
        conns = self.get_source_spreadsheets()
        if conns:
            return [c.name for c in conns]
        if self.source and self.source != 'Manual':
            return [self.source]
        return []

    def clean(self):
        super().clean()
        if self.assigned_telecaller and self.branch_id and self.assigned_telecaller.branch_id and self.assigned_telecaller.branch_id != self.branch_id:
            raise ValidationError({
                'assigned_telecaller': f"Telecaller '{self.assigned_telecaller.username}' belongs to a different branch."
            })
        if self.assigned_counselor_id and self.branch_id and self.assigned_counselor.branch_id and self.assigned_counselor.branch_id != self.branch_id:
            raise ValidationError({
                'assigned_counselor': f"Counselor '{self.assigned_counselor.username}' belongs to a different branch."
            })
        if self.assigned_branch_head_id and self.branch_id and self.assigned_branch_head.branch_id and self.assigned_branch_head.branch_id != self.branch_id:
            raise ValidationError({
                'assigned_branch_head': f"Branch Head '{self.assigned_branch_head.username}' belongs to a different branch."
            })


class LeadAssignmentHistory(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='assignment_history')
    from_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    from_role = models.CharField(max_length=20, blank=True, default='')
    to_role = models.CharField(max_length=20, blank=True, default='')
    branch = models.ForeignKey('branches.Branch', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reason = models.CharField(max_length=255, blank=True, default='')
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Lead assignment histories'

    def __str__(self):
        return f"{self.lead_id}: {self.from_role or '-'} -> {self.to_role or '-'} ({self.created_at:%Y-%m-%d %H:%M})"


class LeadStatusHistory(models.Model):
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='status_history')
    old_status = models.CharField(max_length=30, blank=True, default='')
    new_status = models.CharField(max_length=30)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    remarks = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Lead status histories'

    def __str__(self):
        return f"{self.lead_id}: {self.old_status or '-'} -> {self.new_status} ({self.created_at:%Y-%m-%d %H:%M})"


class LeadImportHistory(models.Model):
    file_name = models.CharField(max_length=255)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lead_imports'
    )
    uploaded_on = models.DateTimeField(auto_now_add=True)
    records = models.IntegerField(default=0)
    successful = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    status = models.CharField(max_length=30, default='Completed')
    error_log = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-uploaded_on']
        verbose_name_plural = 'Lead import histories'

    def __str__(self):
        return f"{self.file_name} ({self.uploaded_on.strftime('%Y-%m-%d %H:%M')})"

class GoogleSheetConnection(models.Model):
    name = models.CharField(max_length=200)
    spreadsheet_url = models.URLField(max_length=500)
    spreadsheet_id = models.CharField(max_length=150, db_index=True)
    worksheet_name = models.CharField(max_length=150, default='Sheet1')
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='google_sheet_connections'
    )
    channel = models.ForeignKey(
        'channels.Channel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='google_sheet_connections'
    )
    assignment_method = models.CharField(
        max_length=20,
        choices=[('Automatic', 'Automatic'), ('Manual', 'Manual')],
        default='Automatic'
    )
    field_mapping = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    sync_interval_seconds = models.IntegerField(default=60)
    last_sync_time = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=50, default='Connected')
    last_sync_error = models.TextField(blank=True, default='')
    total_leads_imported = models.IntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='google_sheet_connections'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.worksheet_name})"

    @property
    def default_branch(self):
        return self.branch

    @default_branch.setter
    def default_branch(self, value):
        self.branch = value

    @property
    def default_branch_id(self):
        return self.branch_id

    @default_branch_id.setter
    def default_branch_id(self, value):
        self.branch_id = value

class GoogleSheetRowMapping(models.Model):
    connection = models.ForeignKey(
        GoogleSheetConnection,
        on_delete=models.CASCADE,
        related_name='row_mappings'
    )
    lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name='sheet_mappings'
    )
    row_identifier = models.CharField(max_length=255, db_index=True)
    row_index = models.IntegerField()
    row_data_hash = models.CharField(max_length=64, blank=True)
    source_status = models.CharField(max_length=50, default='Active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('connection', 'row_identifier')
        ordering = ['row_index']

    def __str__(self):
        return f"{self.connection.name} - Row {self.row_index} -> {self.lead.name}"

class GoogleSheetSyncHistory(models.Model):
    connection = models.ForeignKey(
        GoogleSheetConnection,
        on_delete=models.CASCADE,
        related_name='sync_histories'
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    rows_checked = models.IntegerField(default=0)
    new_leads = models.IntegerField(default=0)
    updated_leads = models.IntegerField(default=0)
    skipped = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    assigned_leads = models.IntegerField(default=0)
    status = models.CharField(max_length=50, default='Completed')
    error_summary = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"Sync {self.connection.name} at {self.timestamp.strftime('%Y-%m-%d %H:%M')} ({self.status})"


# =====================================================================
# GOOGLE FORM CONNECTION MODEL
# =====================================================================
class GoogleFormConnection(models.Model):
    name = models.CharField(max_length=200, default='Google Form Leads')
    form_url = models.CharField(max_length=500)
    form_id = models.CharField(max_length=150, blank=True, default='', db_index=True)
    is_active = models.BooleanField(default=True)
    last_sync_time = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=50, default='Connected')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='google_form_connections'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.form_url})"


# =====================================================================
# SETTINGS -> LEAD SETUP MODELS
# =====================================================================
class AssignmentMethod(models.TextChoices):
    PERCENTAGE = 'PERCENTAGE', 'Percentage Based'
    COUNT = 'COUNT', 'Number Of Leads Based'


class LeadSetupConfig(models.Model):
    """
    Global configuration for Lead Setup assignment method.
    """
    assignment_method = models.CharField(
        max_length=20,
        choices=AssignmentMethod.choices,
        default=AssignmentMethod.PERCENTAGE
    )
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get_current_method(cls):
        cfg = cls.objects.first()
        if not cfg:
            cfg = cls.objects.create(assignment_method=AssignmentMethod.PERCENTAGE)
        return cfg.assignment_method


class TelecallerLeadSetup(models.Model):
    """
    Branch-based Telecaller assignment rules:
    - Percentage or Lead Count
    """
    telecaller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='lead_setup_rules'
    )
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.CASCADE,
        related_name='telecaller_lead_setups'
    )
    assignment_percentage = models.IntegerField(default=0, help_text="e.g. 40 for 40%")
    lead_count = models.IntegerField(default=0, help_text="Target / Limit lead count")
    current_leads_assigned = models.IntegerField(default=0, help_text="Count of leads assigned under this rule")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('telecaller', 'branch')
        ordering = ['branch__name', 'telecaller__username']

    def __str__(self):
        name = self.telecaller.get_full_name() or self.telecaller.username
        return f"{name} - {self.branch.name} ({self.assignment_percentage}%, {self.lead_count} leads)"


# =====================================================================
# DUPLICATE LEAD RECORD MODEL (10-Day Rule)
# =====================================================================
class DuplicateLeadRecord(models.Model):
    """
    Stores duplicate submission details for a lead when submitted within 10 days.
    Keeps the original lead on the main Leads page and references this duplicate record.
    """
    original_lead = models.ForeignKey(
        Lead,
        on_delete=models.CASCADE,
        related_name='duplicate_records'
    )
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True, default='')
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='duplicate_lead_records'
    )
    branch_name = models.CharField(max_length=150, blank=True, default='')
    status = models.CharField(max_length=50, blank=True, default='New')
    notes = models.TextField(blank=True, default='Same lead details detected within 10 days.')
    source = models.CharField(max_length=100, default='Google Form')
    data_payload = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f"Duplicate: {self.name} ({self.phone}) in {self.branch_name or 'N/A'}"


