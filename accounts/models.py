from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.exceptions import ValidationError

class UserRole(models.TextChoices):
    ADMIN = 'ADMIN', 'Admin'
    MANAGER = 'MANAGER', 'Manager / Counsellor'
    TELECALLER = 'TELECALLER', 'Telecaller'

class User(AbstractUser):
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.TELECALLER,
        help_text="Application access role"
    )
    phone = models.CharField(max_length=20, blank=True, default='')
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users'
    )
    manager = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_telecallers',
        limit_choices_to={'role': UserRole.MANAGER}
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['username']

    def __str__(self):
        full = self.get_full_name()
        return f"{full} ({self.username})" if full else self.username

    @property
    def is_admin_user(self):
        return self.role == UserRole.ADMIN or self.is_superuser

    @property
    def is_manager_user(self):
        return self.role == UserRole.MANAGER

    @property
    def is_telecaller_user(self):
        return self.role == UserRole.TELECALLER

    @property
    def display_role(self):
        return dict(UserRole.choices).get(self.role, self.role)

    def clean(self):
        super().clean()
        if self.manager:
            if self.manager == self:
                raise ValidationError({'manager': "A user cannot be their own manager."})
            if self.manager.role != UserRole.MANAGER:
                raise ValidationError({'manager': "Assigned manager must have the MANAGER role."})
            if self.role != UserRole.TELECALLER:
                raise ValidationError({'manager': "Only Telecallers can have an assigned manager."})
