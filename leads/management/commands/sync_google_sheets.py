import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from leads.models import GoogleSheetConnection
from leads.google_sheets import sync_google_sheet

class Command(BaseCommand):
    help = "Synchronizes active Google Sheet connections into CRM Offline Leads."

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=0,
            help="Continuous execution interval in seconds (0 for single execution)."
        )

    def handle(self, *args, **options):
        interval = options.get('interval', 0)
        self.stdout.write(self.style.SUCCESS("Starting Google Sheets Lead Synchronizer..."))

        while True:
            active_connections = GoogleSheetConnection.objects.filter(is_active=True)
            count = active_connections.count()
            self.stdout.write(f"[{timezone.now().strftime('%Y-%m-%d %H:%M:%S')}] Found {count} active connection(s).")

            for conn in active_connections:
                self.stdout.write(f"Syncing connection '{conn.name}' ({conn.spreadsheet_id})...")
                result = sync_google_sheet(conn)
                self.stdout.write(
                    f"Result: {result['status']} | Rows: {result['rows_checked']} | New: {result['new_leads']} | Updated: {result['updated_leads']} | Failed: {result['failed']}"
                )

            if interval <= 0:
                break

            time.sleep(interval)
