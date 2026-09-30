from django.db import migrations


def migrate_manager_to_sales_head(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(role='MANAGER').update(role='SALES_HEAD')


def reverse_migrate(apps, schema_editor):
    User = apps.get_model('accounts', 'User')
    User.objects.filter(role='SALES_HEAD').update(role='MANAGER')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_remove_user_manager_user_counselor_alter_user_role'),
    ]

    operations = [
        migrations.RunPython(migrate_manager_to_sales_head, reverse_migrate),
    ]
