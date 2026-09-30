from django import forms
from django.core.exceptions import ValidationError
from accounts.models import User, UserRole
from accounts.permissions import get_accessible_branch_ids
from branches.models import Branch
from channels.models import Channel
from products.models import Product
from .models import Lead, LeadStatus

def infer_lead_branch(user=None, manager=None, telecaller=None, request=None, current_branch=None):
    """
    Infers lead branch following hierarchy:
    1. Explicit / Current branch on lead
    2. Assigned Telecaller's branch
    3. Assigned Manager's branch
    4. Current user's branch (if Manager or Telecaller)
    5. Active branch in Admin session if available
    6. Primary active Branch in database
    """
    if current_branch:
        return current_branch
    if telecaller and getattr(telecaller, 'branch', None):
        return telecaller.branch
    if manager and getattr(manager, 'branch', None):
        return manager.branch
    if user and getattr(user, 'branch', None):
        return user.branch
    if request and hasattr(request, 'session'):
        active_branch_id = request.session.get('active_branch_id')
        if active_branch_id:
            b = Branch.objects.filter(pk=active_branch_id, status='Active').first()
            if b:
                return b
    return Branch.objects.filter(status='Active').first()

class AdminLeadForm(forms.ModelForm):
    assigned_manager = forms.ModelChoiceField(
        queryset=User.objects.filter(role=UserRole.SALES_HEAD, is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    assigned_telecaller = forms.ModelChoiceField(
        queryset=User.objects.filter(role=UserRole.TELECALLER, is_active=True),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    channel = forms.ModelChoiceField(queryset=Channel.objects.filter(status='Active'), required=False, widget=forms.Select(attrs={'class': 'form-select'}))
    product = forms.ModelChoiceField(queryset=Product.objects.filter(status='Active'), required=False, widget=forms.Select(attrs={'class': 'form-select'}))
    branch = forms.ModelChoiceField(queryset=Branch.objects.filter(status='Active'), required=False, widget=forms.Select(attrs={'class': 'form-select'}))

    class Meta:
        model = Lead
        fields = [
            'name', 'phone', 'email', 'alternate_phone', 'channel', 'status',
            'assigned_manager', 'assigned_telecaller', 'product', 'branch', 'notes'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full name'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91 XXXXX XXXXX'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@domain.com'}),
            'alternate_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional alternate phone'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Inquiry details, background, course interest...'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        mgr = cleaned_data.get('assigned_manager')
        tc = cleaned_data.get('assigned_telecaller')
        if mgr and tc:
            if tc.branch_id and tc.branch_id not in get_accessible_branch_ids(mgr):
                raise ValidationError({
                    'assigned_telecaller': f"Telecaller '{tc.username}' belongs to a branch not managed by '{mgr.username}'."
                })
        if not cleaned_data.get('branch'):
            current_b = getattr(self.instance, 'branch', None) if self.instance else None
            cleaned_data['branch'] = infer_lead_branch(
                manager=mgr,
                telecaller=tc,
                current_branch=current_b
            )
        return cleaned_data

    def save(self, commit=True):
        lead = super().save(commit=False)
        lead.assigned_sales_head = self.cleaned_data.get('assigned_manager')
        if not lead.branch:
            lead.branch = infer_lead_branch(
                manager=lead.assigned_manager,
                telecaller=lead.assigned_telecaller,
                current_branch=getattr(lead, 'branch', None)
            )
        if commit:
            lead.save()
        return lead

class ManagerLeadForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        manager = kwargs.pop('manager', None)
        self.manager = manager
        super().__init__(*args, **kwargs)
        if manager:
            self.fields['assigned_telecaller'].queryset = User.objects.filter(
                role=UserRole.TELECALLER,
                branch_id__in=get_accessible_branch_ids(manager),
                is_active=True
            )

    assigned_telecaller = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    product = forms.ModelChoiceField(queryset=Product.objects.filter(status='Active'), required=False, widget=forms.Select(attrs={'class': 'form-select'}))
    branch = forms.ModelChoiceField(queryset=Branch.objects.filter(status='Active'), required=False, widget=forms.Select(attrs={'class': 'form-select'}))

    class Meta:
        model = Lead
        fields = ['status', 'assigned_telecaller', 'product', 'branch', 'alternate_phone', 'notes']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'alternate_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean(self):
        cleaned_data = super().clean()
        tc = cleaned_data.get('assigned_telecaller')
        if not cleaned_data.get('branch'):
            current_b = getattr(self.instance, 'branch', None) if self.instance else None
            cleaned_data['branch'] = infer_lead_branch(
                user=self.manager,
                manager=self.manager,
                telecaller=tc,
                current_branch=current_b
            )
        return cleaned_data

    def save(self, commit=True):
        lead = super().save(commit=False)
        if not lead.branch:
            lead.branch = infer_lead_branch(
                user=self.manager,
                manager=self.manager,
                telecaller=lead.assigned_telecaller,
                current_branch=getattr(lead, 'branch', None)
            )
        if commit:
            lead.save()
        return lead

class TelecallerLeadForm(forms.ModelForm):
    class Meta:
        model = Lead
        fields = ['status', 'alternate_phone', 'email', 'notes']
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'alternate_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

class ManagerLeadCreateForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        manager = kwargs.pop('manager', None)
        self.manager = manager
        super().__init__(*args, **kwargs)
        if manager:
            self.fields['assigned_telecaller'].queryset = User.objects.filter(
                role=UserRole.TELECALLER,
                branch_id__in=get_accessible_branch_ids(manager),
                is_active=True
            )

    assigned_telecaller = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    channel = forms.ModelChoiceField(queryset=Channel.objects.filter(status='Active'), required=False, widget=forms.Select(attrs={'class': 'form-select'}))
    product = forms.ModelChoiceField(queryset=Product.objects.filter(status='Active'), required=False, widget=forms.Select(attrs={'class': 'form-select'}))
    branch = forms.ModelChoiceField(queryset=Branch.objects.filter(status='Active'), required=False, widget=forms.Select(attrs={'class': 'form-select'}))

    class Meta:
        model = Lead
        fields = [
            'name', 'phone', 'email', 'alternate_phone', 'channel', 'status',
            'assigned_telecaller', 'product', 'branch', 'notes'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full name'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91 XXXXX XXXXX'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@domain.com'}),
            'alternate_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional alternate phone'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Inquiry details, background...'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        tc = cleaned_data.get('assigned_telecaller')
        if not cleaned_data.get('branch'):
            cleaned_data['branch'] = infer_lead_branch(
                user=self.manager,
                manager=self.manager,
                telecaller=tc
            )
        return cleaned_data

    def save(self, commit=True):
        lead = super().save(commit=False)
        if not lead.branch:
            lead.branch = infer_lead_branch(
                user=self.manager,
                manager=self.manager,
                telecaller=lead.assigned_telecaller
            )
        if commit:
            lead.save()
        return lead

class TelecallerLeadCreateForm(forms.ModelForm):
    channel = forms.ModelChoiceField(queryset=Channel.objects.filter(status='Active'), required=False, widget=forms.Select(attrs={'class': 'form-select'}))
    product = forms.ModelChoiceField(queryset=Product.objects.filter(status='Active'), required=False, widget=forms.Select(attrs={'class': 'form-select'}))

    class Meta:
        model = Lead
        fields = [
            'name', 'phone', 'email', 'alternate_phone', 'channel', 'product', 'notes'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Full name'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+91 XXXXX XXXXX'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@domain.com'}),
            'alternate_phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Optional alternate phone'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Inquiry details, notes...'}),
        }

class LeadImportForm(forms.Form):
    file = forms.FileField(
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': '.csv, .xlsx'}),
        help_text="Upload .csv or .xlsx with headers: Name, Phone, Email, Channel, Product, Notes"
    )
