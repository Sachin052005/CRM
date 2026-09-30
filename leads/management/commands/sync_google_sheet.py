from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from leads.google_sheets_service import (
    check_google_auth_status,
    start_desktop_oauth_flow
)
from leads.models import GoogleSheetConnection
from leads.google_sheets import sync_google_sheet, sync_default_environment_sheet

class Command(BaseCommand):
    help = "Synchronizes Google Sheet Form responses into TECHPANDA CRM Lead records."

    def add_arguments(self, parser):
        parser.add_argument(
            '--auth',
            action='store_true',
            help="Initiate Google OAuth 2.0 Desktop authorization flow."
        )
        parser.add_argument(
            '--tab',
            type=str,
            default=None,
            help="Override Google Sheet tab name (e.g. 'Form Responses 1')."
        )
        parser.add_argument(
            '--connection',
            type=int,
            default=None,
            help="ID of specific GoogleSheetConnection to synchronize."
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Google Sheets Sync"))
        self.stdout.write(self.style.MIGRATE_HEADING("------------------"))

        auth_status = check_google_auth_status()

        # Handle explicit --auth flag or missing authentication
        if options['auth'] or not auth_status['is_authenticated']:
            if not auth_status['credentials_exist']:
                raise CommandError(
                    f"Google OAuth credentials are not configured.\n"
                    f"Please place your Desktop OAuth 'credentials.json' at:\n"
                    f"  {auth_status['credentials_path']}"
                )

            self.stdout.write(self.style.WARNING("Google authentication required. Launching Desktop OAuth flow in browser..."))
            try:
                start_desktop_oauth_flow(port=0, timeout_seconds=120)
                self.stdout.write(self.style.SUCCESS("Google Sheets authentication completed and token saved!"))
            except Exception as e:
                raise CommandError(f"OAuth authorization failed: {e}")

            if options['auth']:
                return

        # Determine target connection to sync
        connection_id = options.get('connection')
        target_tab = options.get('tab')

        if connection_id:
            try:
                conn = GoogleSheetConnection.objects.get(pk=connection_id)
            except GoogleSheetConnection.DoesNotExist:
                raise CommandError(f"GoogleSheetConnection #{connection_id} not found.")

            if target_tab:
                conn.worksheet_name = target_tab
                conn.save(update_fields=['worksheet_name'])

            result = sync_google_sheet(conn)
            self._print_result(conn.name, conn.worksheet_name, result)

        elif getattr(settings, 'GOOGLE_SHEET_ID', None):
            conn, result = sync_default_environment_sheet()
            sheet_title = conn.name if conn else settings.GOOGLE_SHEET_ID
            sheet_tab = conn.worksheet_name if conn else getattr(settings, 'GOOGLE_SHEET_TAB', 'Form Responses 1')
            self._print_result(sheet_title, sheet_tab, result)

        else:
            # Sync all active database connections
            active_conns = GoogleSheetConnection.objects.filter(is_active=True)
            if not active_conns.exists():
                self.stdout.write(self.style.WARNING("No active Google Sheet connections found and GOOGLE_SHEET_ID is not set in environment."))
                self.stdout.write("Configure GOOGLE_SHEET_ID in .env or add a connection via /admin/offline-leads/.")
                return

            for conn in active_conns:
                result = sync_google_sheet(conn)
                self._print_result(conn.name, conn.worksheet_name, result)

    def _print_result(self, title, sheet_tab, result):
        self.stdout.write(f"Spreadsheet: {title}")
        self.stdout.write(f"Sheet: {sheet_tab}\n")
        self.stdout.write(f"Rows fetched: {result.get('rows_checked', 0)}")
        self.stdout.write(self.style.SUCCESS(f"New leads: {result.get('new_leads', 0)}"))
        self.stdout.write(f"Updated leads: {result.get('updated_leads', 0)}")
        self.stdout.write(f"Duplicates skipped: {result.get('skipped', 0)}")
        if result.get('failed', 0) > 0:
            self.stdout.write(self.style.ERROR(f"Failed rows: {result.get('failed', 0)}"))
            for err in result.get('errors', []):
                self.stdout.write(self.style.ERROR(f"  - {err}"))

        self.stdout.write("")
        if result.get('status') in ['Completed', 'Completed with Errors']:
            self.stdout.write(self.style.SUCCESS("Sync completed successfully."))
        else:
            self.stdout.write(self.style.ERROR(f"Sync ended with status: {result.get('status')}"))
        self.stdout.write("------------------")
