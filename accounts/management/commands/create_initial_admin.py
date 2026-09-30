import os
from django.core.management.base import BaseCommand
from accounts.models import User, UserRole
from activities.utils import log_activity

class Command(BaseCommand):
    help = 'Safely creates or verifies the initial Admin account from environment variables or arguments.'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, default=None, help='Admin username')
        parser.add_argument('--email', type=str, default=None, help='Admin email')
        parser.add_argument('--password', type=str, default=None, help='Admin password')

    def handle(self, *args, **options):
        username = options['username'] or os.getenv('INITIAL_ADMIN_USERNAME', 'priya')
        email = options['email'] or os.getenv('INITIAL_ADMIN_EMAIL', 'edppriya@gmail.com')
        password = options['password'] or os.getenv('INITIAL_ADMIN_PASSWORD')

        if not password:
            self.stdout.write(self.style.ERROR("Error: Admin password must be provided via argument or INITIAL_ADMIN_PASSWORD env variable."))
            return

        if User.objects.filter(username=username).exists():
            admin_user = User.objects.get(username=username)
            # Ensure proper roles & privileges
            if admin_user.role != UserRole.ADMIN or not admin_user.is_superuser:
                admin_user.role = UserRole.ADMIN
                admin_user.is_staff = True
                admin_user.is_superuser = True
                admin_user.save()
                self.stdout.write(self.style.WARNING(f"Updated existing user '{username}' with ADMIN role and superuser rights."))
            else:
                self.stdout.write(self.style.SUCCESS(f"Admin user '{username}' already exists. Skipping duplicate creation."))
            return

        admin_user = User(
            username=username,
            email=email,
            first_name='Priya',
            last_name='Admin',
            role=UserRole.ADMIN,
            is_staff=True,
            is_superuser=True,
            is_active=True
        )
        admin_user.set_password(password)
        admin_user.save()

        log_activity(
            user=admin_user,
            action="Admin Account Initialized",
            description=f"System initial admin account '{username}' was initialized.",
            object_type="User",
            object_id=str(admin_user.pk)
        )

        self.stdout.write(self.style.SUCCESS(f"Successfully created initial Admin account: '{username}' ({email})"))
