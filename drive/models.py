from django.db import models
from django.conf import settings
from django.utils import timezone


class DriveConnection(models.Model):
    name = models.CharField(max_length=200, default='Call Recordings')
    folder_url = models.URLField(max_length=500)
    folder_id = models.CharField(max_length=150, db_index=True)
    connection_status = models.CharField(max_length=50, default='Connected')
    is_active = models.BooleanField(default=True, db_index=True)
    is_syncing = models.BooleanField(default=False)
    last_sync_status = models.CharField(max_length=50, default='Success')
    last_error_message = models.TextField(blank=True, default='')
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='drive_connections'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.folder_id})"

    @property
    def folder_name(self):
        return self.name

    @folder_name.setter
    def folder_name(self, value):
        self.name = value

    @property
    def total_recordings_count(self):
        return self.recordings.count()

    @property
    def matched_recordings_count(self):
        return self.recordings.filter(match_status='MATCHED').count()

    @property
    def unmatched_recordings_count(self):
        return self.recordings.filter(match_status='UNMATCHED').count()


class CallRecording(models.Model):
    MATCH_STATUS_CHOICES = [
        ('MATCHED', 'Matched'),
        ('UNMATCHED', 'Unmatched'),
    ]

    lead = models.ForeignKey(
        'leads.Lead',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='drive_recordings'
    )
    drive_connection = models.ForeignKey(
        DriveConnection,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recordings'
    )
    telecaller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='archived_call_recordings'
    )
    source_folder_id = models.CharField(max_length=150, blank=True, default='', db_index=True)
    drive_file_id = models.CharField(max_length=150, unique=True, db_index=True)
    file_name = models.CharField(max_length=255)
    mobile_number = models.CharField(max_length=30, blank=True, default='')
    normalized_mobile_number = models.CharField(max_length=20, blank=True, default='', db_index=True)
    drive_url = models.URLField(max_length=500, blank=True, default='')
    mime_type = models.CharField(max_length=50, default='audio/mpeg')
    duration = models.CharField(max_length=20, default='04:32')
    file_size = models.BigIntegerField(default=0)
    audio_data = models.BinaryField(null=True, blank=True)
    recording_date = models.DateTimeField(null=True, blank=True)
    match_status = models.CharField(
        max_length=20,
        choices=MATCH_STATUS_CHOICES,
        default='UNMATCHED',
        db_index=True
    )
    unmatched_reason = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-recording_date', '-created_at']
        indexes = [
            models.Index(fields=['drive_file_id']),
            models.Index(fields=['normalized_mobile_number']),
            models.Index(fields=['match_status']),
        ]

    def __str__(self):
        return f"{self.file_name} ({self.match_status})"
