from django import forms
from accounts.models import User, UserRole
from leads.models import Lead
from .models import FollowUp, FollowUpStatus

class AdminFollowUpForm(forms.ModelForm):
    lead = forms.ModelChoiceField(
        queryset=Lead.objects.all().order_by('name'),
        widget=forms.Select(attrs={'class': 'form-select'}),
        help_text="Select lead for this follow-up"
    )
    assigned_user = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by('username'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    manager = forms.ModelChoiceField(
        queryset=User.objects.filter(role=UserRole.MANAGER, is_active=True).order_by('username'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    telecaller = forms.ModelChoiceField(
        queryset=User.objects.filter(role=UserRole.TELECALLER, is_active=True).order_by('username'),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    follow_up_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    follow_up_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'})
    )
    status = forms.ChoiceField(
        choices=FollowUpStatus.choices,
        initial=FollowUpStatus.PENDING,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Discussion notes or callback reason...'})
    )

    class Meta:
        model = FollowUp
        fields = [
            'lead',
            'assigned_user',
            'manager',
            'telecaller',
            'follow_up_date',
            'follow_up_time',
            'status',
            'notes',
        ]

    def clean(self):
        cleaned_data = super().clean()
        manager = cleaned_data.get('manager')
        telecaller = cleaned_data.get('telecaller')

        if telecaller and manager:
            if telecaller.manager and telecaller.manager != manager:
                raise forms.ValidationError(
                    f"Invalid assignment: Telecaller '{telecaller.username}' reports to '{telecaller.manager.username}', not '{manager.username}'."
                )

        return cleaned_data

class FollowUpRescheduleForm(forms.Form):
    follow_up_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        help_text="Select new follow-up date"
    )
    follow_up_time = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={'type': 'time', 'class': 'form-control'}),
        help_text="Optional time"
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Reason for rescheduling or additional notes...'}),
        help_text="Reschedule context or reason"
    )
