from django.db import models

class Channel(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    name = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class LeadConnection(models.Model):
    class ConnectionType(models.TextChoices):
        META = 'Meta', 'Meta / Facebook'
        WEBSITE = 'Website', 'Website'
        GOOGLE_SHEETS = 'Google Sheets', 'Google Sheets'
        WHATSAPP = 'WhatsApp', 'WhatsApp'
        WEBHOOK = 'Webhook', 'Custom Webhook'
        OTHER = 'Other', 'Other'

    class ConnectionStatus(models.TextChoices):
        CONNECTED = 'Connected', 'Connected'
        DISCONNECTED = 'Disconnected', 'Disconnected'
        ERROR = 'Error', 'Error'

    name = models.CharField(max_length=150)
    connection_type = models.CharField(
        max_length=50,
        choices=ConnectionType.choices,
        default=ConnectionType.META
    )
    status = models.CharField(
        max_length=30,
        choices=ConnectionStatus.choices,
        default=ConnectionStatus.CONNECTED
    )
    page_name = models.CharField(max_length=200, blank=True, default='')
    source_name = models.CharField(max_length=150, default='Meta')
    last_sync_time = models.DateTimeField(null=True, blank=True)
    last_sync_display = models.CharField(max_length=50, blank=True, default='12:58 PM')

    channel = models.ForeignKey(
        Channel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='connections'
    )
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lead_connections'
    )

    webhook_url = models.CharField(max_length=500, blank=True, default='')
    api_key_or_token = models.CharField(max_length=255, blank=True, default='')
    config_details = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.name} ({self.status})"

