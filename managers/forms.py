from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from accounts.models import User, UserRole
from branches.models import Branch

class AdminManagerCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Set password'}))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm password'}))
    branch = forms.ModelChoiceField(queryset=Branch.objects.filter(status='Active'), required=False, widget=forms.Select(attrs={'class': 'form-select'}))

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email', 'phone', 'branch', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("A user with this username already exists.")
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if not email:
            raise ValidationError("Email is required.")
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError("A user with this email address already exists.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('password')
        p2 = cleaned_data.get('confirm_password')
        if p1 and p2:
            if p1 != p2:
                self.add_error('confirm_password', "Passwords do not match.")
            else:
                user_instance = User(
                    username=cleaned_data.get('username'),
                    email=cleaned_data.get('email')
                )
                try:
                    validate_password(p1, user=user_instance)
                except ValidationError as e:
                    self.add_error('password', e)
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = UserRole.SALES_HEAD
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            if user.branch_id:
                from branches.models import SalesHeadBranchAccess
                SalesHeadBranchAccess.objects.get_or_create(sales_head=user, branch_id=user.branch_id)
        return user

class AdminManagerEditForm(forms.ModelForm):
    branch = forms.ModelChoiceField(queryset=Branch.objects.all(), required=False, widget=forms.Select(attrs={'class': 'form-select'}))

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'phone', 'branch', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
