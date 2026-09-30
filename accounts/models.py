from django.contrib.auth.models import AbstractUser
from django.db import models
from django.core.exceptions import ValidationError

class UserRole(models.TextChoices):
    ADMIN = 'ADMIN', 'Admin'
    SALES_HEAD = 'SALES_HEAD', 'Sales Head'
    BRANCH_HEAD = 'BRANCH_HEAD', 'Branch Head'
    COUNSELOR = 'COUNSELOR', 'Counselor'
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
    counselor = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_telecallers',
        limit_choices_to={'role': UserRole.COUNSELOR}
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
    def is_sales_head_user(self):
        return self.role == UserRole.SALES_HEAD

    @property
    def is_branch_head_user(self):
        return self.role == UserRole.BRANCH_HEAD

    @property
    def is_counselor_user(self):
        return self.role == UserRole.COUNSELOR

    @property
    def is_telecaller_user(self):
        return self.role == UserRole.TELECALLER

    @property
    def display_role(self):
        return dict(UserRole.choices).get(self.role, self.role)

    def clean(self):
        super().clean()
        if self.counselor_id:
            if self.role != UserRole.TELECALLER:
                raise ValidationError({'counselor': "Only Telecallers can have an assigned counselor."})
            if self.counselor_id == self.id:
                raise ValidationError({'counselor': "A user cannot be their own counselor."})
            if self.counselor.role != UserRole.COUNSELOR:
                raise ValidationError({'counselor': "Assigned counselor must have the COUNSELOR role."})
            if self.branch_id and self.counselor.branch_id and self.branch_id != self.counselor.branch_id:
                raise ValidationError({'counselor': "Assigned counselor must belong to the same branch as the telecaller."})
