from django import forms
from django.utils import timezone
from accounts.models import User, UserRole
from leads.models import Lead
from .models import CallHistory, CallStatus, CallOutcome

class AdminCallRecordForm(forms.ModelForm):
    lead = forms.ModelChoiceField(
        queryset=Lead.objects.all().order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Select lead called"
    )
    caller = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('username'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="User who initiated/conducted the call"
    )
    manager = forms.ModelChoiceField(
        queryset=User.objects.filter(role=UserRole.SALES_HEAD, is_active=True).order_by('username'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Supervising manager"
    )
    telecaller = forms.ModelChoiceField(
        queryset=User.objects.filter(role=UserRole.TELECALLER, is_active=True).order_by('username'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Assigned telecaller"
    )
    call_status = forms.ChoiceField(
        choices=CallStatus.choices,
        initial=CallStatus.COMPLETED,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    call_outcome = forms.ChoiceField(
        choices=CallOutcome.choices,
        initial=CallOutcome.FOLLOW_UP_REQUIRED,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    call_started_at = forms.DateTimeField(
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'}),
        initial=timezone.now
    )
    call_ended_at = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'})
    )
    duration = forms.IntegerField(
        initial=0,
        min_value=0,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Duration in seconds'}),
        help_text="Call duration in seconds"
    )
    recording_url = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional recording file URL or path'})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Discussion summary...'})
    )

    class Meta:
        model = CallHistory
        fields = [
            'lead',
            'caller',
            'manager',
            'telecaller',
            'call_status',
            'call_outcome',
            'call_started_at',
            'call_ended_at',
            'duration',
            'recording_url',
            'notes',
        ]

    def clean(self):
        cleaned_data = super().clean()
        manager = cleaned_data.get('manager')
        telecaller = cleaned_data.get('telecaller')
        started_at = cleaned_data.get('call_started_at')
        ended_at = cleaned_data.get('call_ended_at')
        duration = cleaned_data.get('duration') or 0

        if telecaller and manager:
            from accounts.permissions import get_accessible_branch_ids
            if telecaller.branch_id and telecaller.branch_id not in get_accessible_branch_ids(manager):
                raise forms.ValidationError(
                    f"Invalid assignment: Telecaller '{telecaller.username}' belongs to a branch not managed by '{manager.username}'."
                )

        if started_at and ended_at and ended_at < started_at:
            raise forms.ValidationError("Call ended time cannot be earlier than call started time.")

        return cleaned_data
