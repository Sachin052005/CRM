from django.core.management.base import BaseCommand
from branches.models import Branch
from channels.models import Channel
from products.models import Product

class Command(BaseCommand):
    help = 'Seeds initial standard channels, branches, and courses without creating fake user or lead records.'

    def handle(self, *args, **options):
        # 1. Standard Channels (Section 27)
        channels = ['Website', 'Google Ads', 'Facebook', 'Instagram', 'Referral', 'Walk-in', 'Phone', 'WhatsApp', 'Google Sheets', 'Manual']
        for ch in channels:
            Channel.objects.get_or_create(name=ch, defaults={'status': 'Active'})

        # 2. Standard Branches (Section 29)
        branches = [
            {'name': 'Main Campus', 'phone': '+91 98765 00001', 'address': 'Plot 12, Tech Park Sector 5'},
            {'name': 'Downtown Center', 'phone': '+91 98765 00002', 'address': 'Suite 401, Central Business Hub'},
        ]
        for b in branches:
            Branch.objects.get_or_create(name=b['name'], defaults={'phone': b['phone'], 'address': b['address'], 'status': 'Active'})

        # 3. Standard Products / Programs (Section 28)
        products = [
            {'name': 'Full-Stack Python & AI', 'price': 35000, 'description': 'Comprehensive Django, React, AI agent engineering course.'},
            {'name': 'Data Science & Machine Learning', 'price': 42000, 'description': 'Deep learning, predictive modeling, and data analytics.'},
            {'name': 'Cloud & DevOps Engineering', 'price': 38000, 'description': 'AWS, Docker, Kubernetes, CI/CD pipeline mastery.'},
        ]
        for p in products:
            Product.objects.get_or_create(name=p['name'], defaults={'price': p['price'], 'description': p['description'], 'status': 'Active'})

        self.stdout.write(self.style.SUCCESS("Successfully provisioned standard master data (Channels, Branches, Products)."))
