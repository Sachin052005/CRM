from django.db import migrations

def seed_branches(apps, schema_editor):
    Branch = apps.get_model('branches', 'Branch')
    branches = [
        'T. Nagar',
        'Velachery',
        'Sholinganallur',
        'Anna Nagar',
        'Tambaram',
        'Porur'
    ]
    for name in branches:
        Branch.objects.get_or_create(name=name, defaults={'status': 'Active'})

def reverse_branches(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('branches', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_branches, reverse_branches),
    ]
