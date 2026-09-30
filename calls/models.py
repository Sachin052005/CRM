from django.db import models
from django.conf import settings
from django.utils import timezone

class CallStatus(models.TextChoices):
    INITIATED = 'Initiated', 'Initiated'
    CONNECTED = 'Connected', 'Connected'
    COMPLETED = 'Completed', 'Completed'
    FAILED = 'Failed', 'Failed'
    MISSED = 'Missed', 'Missed'
    CANCELLED = 'Cancelled', 'Cancelled'

class CallOutcome(models.TextChoices):
    INTERESTED = 'Interested', 'Interested'
    NOT_INTERESTED = 'Not Interested', 'Not Interested'
    FOLLOW_UP_REQUIRED = 'Follow-up Required', 'Follow-up Required'
    CALLBACK_REQUESTED = 'Callback Requested', 'Callback Requested'
    CONVERTED = 'Converted', 'Converted'
    NO_ANSWER = 'No Answer', 'No Answer'
    BUSY = 'Busy', 'Busy'

class CallHistory(models.Model):
    lead = models.ForeignKey(
        'leads.Lead',
        on_delete=models.CASCADE,
        related_name='calls'
    )
    caller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conducted_calls'
    )
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manager_calls'
    )
    telecaller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='telecaller_calls'
    )
    call_started_at = models.DateTimeField(default=timezone.now)
    call_ended_at = models.DateTimeField(null=True, blank=True)
    duration = models.IntegerField(default=0, help_text="Duration in seconds")
    call_status = models.CharField(
        max_length=20,
        choices=CallStatus.choices,
        default=CallStatus.COMPLETED
    )
    call_outcome = models.CharField(
        max_length=30,
        choices=CallOutcome.choices,
        default=CallOutcome.FOLLOW_UP_REQUIRED
    )
    notes = models.TextField(blank=True, default='')
    notes_completed = models.BooleanField(
        default=True,
        db_index=True,
        help_text="True if call notes have been submitted and call record is finalized"
    )
    recording_url = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Call histories'

    def __str__(self):
        caller_name = self.caller.username if self.caller else 'Unknown'
        lead_name = self.lead.name if self.lead else 'Unknown Lead'
        return f"Call with {lead_name} by {caller_name} ({self.duration}s)"


    @property
    def formatted_duration(self):
        minutes, seconds = divmod(self.duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
