from django import forms
from .models import Channel

class ChannelForm(forms.ModelForm):
    class Meta:
        model = Channel
        fields = ['name', 'status']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g. Website, Facebook, Referral'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
        }
