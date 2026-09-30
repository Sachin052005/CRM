import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from leads.models import GoogleSheetConnection
from leads.google_sheets import sync_all_active_spreadsheets, sync_google_sheet

class Command(BaseCommand):
    help = "Synchronizes all active connected Google Spreadsheets into CRM Leads with strict assignment."

    def add_arguments(self, parser):
        parser.add_argument(
            '--interval',
            type=int,
            default=0,
            help="Continuous execution interval in seconds (0 for single execution)."
        )

    def handle(self, *args, **options):
        interval = options.get('interval', 0)
        self.stdout.write(self.style.SUCCESS("Starting Multi-Spreadsheet Lead Synchronizer..."))

        while True:
            now_str = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
            active_connections = GoogleSheetConnection.objects.filter(is_active=True)
            count = active_connections.count()
            self.stdout.write(f"[{now_str}] Found {count} active connected spreadsheet(s).")

            results = sync_all_active_spreadsheets()
            for r in results:
                self.stdout.write(
                    f"Sheet '{r['connection_name']}': {r['status']} | "
                    f"Checked: {r['rows_checked']} | New: {r['new_leads']} | "
                    f"Updated/Consolidated: {r['updated_leads']} | "
                    f"Assigned: {r.get('assigned_leads', 0)} | Failed: {r['failed']}"
                )

            if interval <= 0:
                break

            time.sleep(interval)
