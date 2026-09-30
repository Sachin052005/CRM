from django.db import migrations


def backfill_owner_type(apps, schema_editor):
    Lead = apps.get_model('leads', 'Lead')
    Lead.objects.filter(assigned_telecaller__isnull=False).update(current_owner_type='TELECALLER')
    Lead.objects.filter(assigned_telecaller__isnull=True, assigned_sales_head__isnull=False).update(current_owner_type='SALES_HEAD')


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0007_rename_assigned_manager_lead_assigned_sales_head_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_owner_type, reverse_noop),
    ]
