from django.db import models
from django.conf import settings
from django.utils import timezone

class FollowUpStatus(models.TextChoices):
    PENDING = 'Pending', 'Pending'
    COMPLETED = 'Completed', 'Completed'
    CANCELLED = 'Cancelled', 'Cancelled'
    OVERDUE = 'Overdue', 'Overdue'

class FollowUp(models.Model):
    lead = models.ForeignKey(
        'leads.Lead',
        on_delete=models.CASCADE,
        related_name='followups'
    )
    assigned_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_followups'
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_followups'
    )
    telecaller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='telecaller_followups'
    )
    follow_up_date = models.DateField()
    follow_up_time = models.TimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=FollowUpStatus.choices,
        default=FollowUpStatus.PENDING
    )
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['follow_up_date', 'follow_up_time']

    def __str__(self):
        lead_name = self.lead.name if self.lead else "Unknown Lead"
        return f"Follow-up with {lead_name} on {self.follow_up_date} ({self.status})"

    @property
    def is_overdue(self):
        if self.status == FollowUpStatus.OVERDUE:
            return True
        if self.status == FollowUpStatus.PENDING:
            now = timezone.now()
            today = now.date()
            if self.follow_up_date < today:
                return True
            if self.follow_up_date == today and self.follow_up_time:
                return now.time() > self.follow_up_time
        return False

    @property
    def display_status(self):
        if self.is_overdue:
            return 'Overdue'
        return self.status

