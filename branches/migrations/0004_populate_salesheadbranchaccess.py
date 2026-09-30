from django.db import migrations


def populate_sales_head_branch_access(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    SalesHeadBranchAccess = apps.get_model('branches', 'SalesHeadBranchAccess')

    for user in User.objects.filter(role='SALES_HEAD', branch__isnull=False):
        SalesHeadBranchAccess.objects.get_or_create(sales_head_id=user.id, branch_id=user.branch_id)


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('branches', '0003_salesheadbranchaccess'),
        ('accounts', '0003_migrate_manager_role_to_sales_head'),
    ]

    operations = [
        migrations.RunPython(populate_sales_head_branch_access, reverse_noop),
    ]
