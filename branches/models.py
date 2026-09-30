from django.conf import settings
from django.db import models

class Branch(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'Active', 'Active'
        INACTIVE = 'Inactive', 'Inactive'

    name = models.CharField(max_length=100, unique=True)
    address = models.TextField(blank=True, default='')
    phone = models.CharField(max_length=20, blank=True, default='')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Branches'

    def __str__(self):
        return self.name


class SalesHeadBranchAccess(models.Model):
    sales_head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='branch_access',
        limit_choices_to={'role': 'SALES_HEAD'}
    )
    branch = models.ForeignKey(
        'branches.Branch',
        on_delete=models.CASCADE,
        related_name='sales_head_access'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('sales_head', 'branch')
        verbose_name_plural = 'Sales head branch access'

    def __str__(self):
        return f"{self.sales_head} -> {self.branch}"
