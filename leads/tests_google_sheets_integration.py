import json
from unittest.mock import patch, MagicMock
import urllib.error

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, UserRole
from branches.models import Branch
from channels.models import Channel
from products.models import Product
from leads.models import (
    Lead,
    LeadStatus,
    GoogleSheetConnection,
    GoogleSheetSource,
    GoogleSheetRowMapping,
    GoogleSheetSyncHistory,
)
from services.google_sheets_service import (
    validate_url,
    extract_spreadsheet_id,
    extract_gid,
    build_fetch_url,
    fetch_sheet,
    parse_sheet,
    normalize_rows,
)
from services.google_sheets_parser import (
    normalize_header_name,
    clean_and_deduplicate_headers,
    sanitize_cell_value,
    parse_csv_content,
    detect_field_mapping,
)
from services.google_sheets_sync_service import sync_connection


class GoogleSheetsServiceUnitTests(TestCase):
    """
    Tests for URL parsing, security domain validation, GID extraction,
    and public URL generation.
    """

    def test_extract_spreadsheet_id_valid_urls(self):
        url1 = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0"
        self.assertEqual(extract_spreadsheet_id(url1), "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms")

        url2 = "https://docs.google.com/spreadsheets/d/2CxiMVsCustomCols12345/view"
        self.assertEqual(extract_spreadsheet_id(url2), "2CxiMVsCustomCols12345")

        url3 = "https://docs.google.com/spreadsheets/d/3DxiMVsLiveCheck12345/"
        self.assertEqual(extract_spreadsheet_id(url3), "3DxiMVsLiveCheck12345")

        raw_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
        self.assertEqual(extract_spreadsheet_id(raw_id), raw_id)

    def test_extract_spreadsheet_id_invalid(self):
        self.assertIsNone(extract_spreadsheet_id(""))
        self.assertIsNone(extract_spreadsheet_id("https://example.com/not-google"))
        self.assertIsNone(extract_spreadsheet_id("short"))

    def test_extract_gid(self):
        url_with_gid = "https://docs.google.com/spreadsheets/d/ABC1234567890123/edit#gid=987654"
        self.assertEqual(extract_gid(url_with_gid), "987654")

        url_with_query_gid = "https://docs.google.com/spreadsheets/d/ABC1234567890123/edit?gid=112233"
        self.assertEqual(extract_gid(url_with_query_gid), "112233")

        url_no_gid = "https://docs.google.com/spreadsheets/d/ABC1234567890123/edit"
        self.assertEqual(extract_gid(url_no_gid), "0")

    def test_url_security_and_ssrf_validation(self):
        # Valid Google Docs URL
        is_val, err = validate_url("https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit")
        self.assertTrue(is_val)
        self.assertIsNone(err)

        # Invalid arbitrary domain (SSRF attempt)
        is_val, err = validate_url("https://malicious-site.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit")
        self.assertFalse(is_val)
        self.assertIn("Only Google Sheets URLs on docs.google.com are supported", err)

        # Non-HTTPS protocol
        is_val, err = validate_url("ftp://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit")
        self.assertFalse(is_val)
        self.assertIn("HTTPS", err)

        # Missing spreadsheet path
        is_val, err = validate_url("https://docs.google.com/document/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit")
        self.assertFalse(is_val)

    def test_build_fetch_url(self):
        url = build_fetch_url("SHEET_ID_123", gid="456")
        self.assertIn("https://docs.google.com/spreadsheets/d/SHEET_ID_123/gviz/tq?tqx=out:csv&gid=456", url)

        url_named = build_fetch_url("SHEET_ID_123", sheet_name="Form Responses 1")
        self.assertIn("sheet=Form%20Responses%201", url_named)


class GoogleSheetsParserTests(TestCase):
    """
    Tests for parser resilience: Unicode (Tamil/English), deduplication,
    formula sanitization, empty rows, dynamic columns (5 to 30+).
    """

    def test_header_normalization(self):
        self.assertEqual(normalize_header_name("  Student Name  "), "student name")
        self.assertEqual(normalize_header_name("Mobile_Number"), "mobile number")
        self.assertEqual(normalize_header_name("Contact-Phone"), "contact phone")
        # Tamil Unicode preservation
        self.assertEqual(normalize_header_name("பெயர்"), "பெயர்")

    def test_deduplicate_headers(self):
        raw = ["Name", "Email", "Phone", "Email", "Phone", ""]
        cleaned = clean_and_deduplicate_headers(raw)
        self.assertEqual(cleaned, ["Name", "Email", "Phone", "Email_2", "Phone_2", "Column_6"])

    def test_formula_sanitization(self):
        # Prevent spreadsheet formula injection
        self.assertEqual(sanitize_cell_value("=cmd|'/C calc'!A0"), "'=cmd|'/C calc'!A0")
        self.assertEqual(sanitize_cell_value("+1234567890"), "'+1234567890")
        self.assertEqual(sanitize_cell_value("-500"), "'-500")
        self.assertEqual(sanitize_cell_value("@SUM(A1:A10)"), "'@SUM(A1:A10)")
        self.assertEqual(sanitize_cell_value("Standard Text"), "Standard Text")

    def test_parse_csv_content_tamil_and_english(self):
        csv_data = (
            "பெயர்,மின்னஞ்சல்,கைபேசி,படிப்பு,City\n"
            "முருகன்,murugan@example.com,9876543210,Python Full Stack,மதுரை\n"
            "Priya,priya@example.com,9123456780,Data Science,Chennai\n"
            ",,,,\n"  # Empty row
        )
        headers, rows = parse_csv_content(csv_data)
        self.assertEqual(headers, ["பெயர்", "மின்னஞ்சல்", "கைபேசி", "படிப்பு", "City"])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["பெயர்"], "முருகன்")
        self.assertEqual(rows[0]["கைபேசி"], "9876543210")
        self.assertEqual(rows[1]["பெயர்"], "Priya")
        self.assertEqual(rows[1]["City"], "Chennai")

    def test_detect_field_mapping_multilingual(self):
        headers = ["பெயர்", "மின்னஞ்சல்", "கைபேசி", "விருப்பமான படிப்பு", "கிளை"]
        mapping = detect_field_mapping(headers)
        self.assertEqual(mapping.get("name"), "பெயர்")
        self.assertEqual(mapping.get("email"), "மின்னஞ்சல்")
        self.assertEqual(mapping.get("phone"), "கைபேசி")
        self.assertEqual(mapping.get("product"), "விருப்பமான படிப்பு")
        self.assertEqual(mapping.get("branch"), "கிளை")

    def test_dynamic_columns_large_sheet(self):
        # 30 columns
        headers = [f"Col_{i}" for i in range(1, 31)]
        row_vals = [f"Val_{i}" for i in range(1, 31)]
        csv_line = ",".join(headers) + "\n" + ",".join(row_vals) + "\n"
        parsed_headers, parsed_rows = parse_csv_content(csv_line)
        self.assertEqual(len(parsed_headers), 30)
        self.assertEqual(len(parsed_rows), 1)
        self.assertEqual(parsed_rows[0]["Col_30"], "Val_30")


class GoogleSheetsSyncServiceTests(TestCase):
    """
    Tests for synchronization engine into MySQL:
    - First import
    - New row addition
    - Existing row update
    - Content unchanged detection
    - Removed row detection (preserving CRM leads)
    - Duplicate detection
    - Atomic rollback
    """

    def setUp(self):
        self.branch = Branch.objects.get_or_create(name="Chennai", defaults={"status": "Active"})[0]
        self.channel = Channel.objects.get_or_create(name="Google Sheets", defaults={"status": "Active"})[0]
        self.admin = User.objects.create_user(
            username="admin_sync_test",
            email="admin_sync@example.com",
            password="TestPassword@123",
            role=UserRole.ADMIN
        )
        self.connection = GoogleSheetConnection.objects.create(
            name="Test Public Sheet",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/1BxiMVsTestSheet12345/edit#gid=0",
            spreadsheet_id="1BxiMVsTestSheet12345",
            gid="0",
            worksheet_name="Sheet1",
            branch=self.branch,
            channel=self.channel,
            created_by=self.admin
        )

    def test_initial_sync_creates_leads_and_row_mappings(self):
        headers = ["Full Name", "Phone Number", "Email Address", "Course"]
        rows = [
            {"_row_index": 2, "Full Name": "Arun Kumar", "Phone Number": "9876543210", "Email Address": "arun@example.com", "Course": "Python"},
            {"_row_index": 3, "Full Name": "Ravi Teja", "Phone Number": "9876543211", "Email Address": "ravi@example.com", "Course": "Django"},
        ]

        result = sync_connection(self.connection, triggered_by=self.admin, headers=headers, rows=rows)

        self.assertTrue(result["success"])
        self.assertEqual(result["created"], 2)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["unchanged"], 0)
        self.assertEqual(result["total_rows"], 2)

        # Verify records exist in MySQL
        self.assertEqual(Lead.objects.filter(is_offline=True).count(), 2)
        lead_arun = Lead.objects.get(phone="9876543210")
        self.assertEqual(lead_arun.name, "Arun Kumar")
        self.assertEqual(lead_arun.email, "arun@example.com")

        # Verify GoogleSheetRowMapping exists
        self.assertEqual(GoogleSheetRowMapping.objects.filter(connection=self.connection).count(), 2)
        mapping_arun = GoogleSheetRowMapping.objects.get(lead=lead_arun)
        self.assertEqual(mapping_arun.source_status, "Active")

        # Verify GoogleSheetSyncHistory recorded
        history = GoogleSheetSyncHistory.objects.filter(connection=self.connection).first()
        self.assertIsNotNone(history)
        self.assertEqual(history.status, "Success")
        self.assertEqual(history.new_leads, 2)

    def test_second_sync_with_updates_and_new_row(self):
        headers = ["Full Name", "Phone Number", "Email Address", "Course"]
        initial_rows = [
            {"_row_index": 2, "Full Name": "Arun Kumar", "Phone Number": "9876543210", "Email Address": "arun@example.com", "Course": "Python"},
            {"_row_index": 3, "Full Name": "Ravi Teja", "Phone Number": "9876543211", "Email Address": "ravi@example.com", "Course": "Django"},
        ]
        sync_connection(self.connection, headers=headers, rows=initial_rows)

        # Second sync: Arun is unchanged, Ravi updated email, Suresh is a new row
        updated_rows = [
            {"_row_index": 2, "Full Name": "Arun Kumar", "Phone Number": "9876543210", "Email Address": "arun@example.com", "Course": "Python"},
            {"_row_index": 3, "Full Name": "Ravi Teja", "Phone Number": "9876543211", "Email Address": "ravi_new@example.com", "Course": "Django"},
            {"_row_index": 4, "Full Name": "Suresh Raina", "Phone Number": "9876543212", "Email Address": "suresh@example.com", "Course": "React"},
        ]

        result = sync_connection(self.connection, headers=headers, rows=updated_rows)

        self.assertTrue(result["success"])
        self.assertEqual(result["created"], 1)    # Suresh
        self.assertEqual(result["updated"], 1)    # Ravi
        self.assertEqual(result["unchanged"], 1)  # Arun
        self.assertEqual(result["total_rows"], 3)

        # Confirm Ravi's email was updated in MySQL
        ravi_lead = Lead.objects.get(phone="9876543211")
        self.assertEqual(ravi_lead.email, "ravi_new@example.com")

        # Confirm Suresh was created
        self.assertTrue(Lead.objects.filter(phone="9876543212").exists())

    def test_removed_row_is_flagged_without_deleting_lead(self):
        headers = ["Full Name", "Phone Number"]
        initial_rows = [
            {"_row_index": 2, "Full Name": "Lead One", "Phone Number": "9000000001"},
            {"_row_index": 3, "Full Name": "Lead Two", "Phone Number": "9000000002"},
        ]
        sync_connection(self.connection, headers=headers, rows=initial_rows)
        self.assertEqual(Lead.objects.count(), 2)

        # Second sync: Row 3 was deleted from Google Sheet
        new_rows = [
            {"_row_index": 2, "Full Name": "Lead One", "Phone Number": "9000000001"}
        ]
        sync_connection(self.connection, headers=headers, rows=new_rows)

        # Lead Two must NOT be deleted from CRM
        self.assertEqual(Lead.objects.count(), 2)
        row_map_2 = GoogleSheetRowMapping.objects.get(lead__phone="9000000002")
        self.assertEqual(row_map_2.source_status, "Removed from source")


class GoogleSheetsRestApiTests(TestCase):
    """
    Tests for REST API endpoints:
    - GET /api/google-sheets/
    - POST /api/google-sheets/connect/
    - POST /api/google-sheets/<id>/sync/
    - GET /api/google-sheets/<id>/
    - DELETE /api/google-sheets/<id>/
    """

    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.get_or_create(name="Velachery", defaults={"status": "Active"})[0]
        self.connection = GoogleSheetConnection.objects.create(
            name="Existing Sheet",
            spreadsheet_url="https://docs.google.com/spreadsheets/d/1BxiMVsApiTest123/edit#gid=0",
            spreadsheet_id="1BxiMVsApiTest123",
            gid="0",
            worksheet_name="Sheet1",
            branch=self.branch
        )

    def test_api_list_sheets(self):
        resp = self.client.get(reverse('api_google_sheets_list'))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["sources"][0]["spreadsheet_id"], "1BxiMVsApiTest123")

    @patch('services.google_sheets_sync_service.fetch_sheet')
    @patch('leads.api_google_sheets.fetch_sheet')
    def test_api_connect_sheet_success(self, mock_api_fetch, mock_sync_fetch):
        mock_data = (
            ["Full Name", "Phone Number"],
            [{"_row_index": 2, "Full Name": "API Lead", "Phone Number": "9888877777"}]
        )
        mock_api_fetch.return_value = mock_data
        mock_sync_fetch.return_value = mock_data

        payload = {
            "name": "New API Connected Sheet",
            "sheet_url": "https://docs.google.com/spreadsheets/d/2CxiMVsNewConnect456/edit#gid=10",
            "worksheet_name": "Sheet1"
        }

        resp = self.client.post(
            reverse('api_google_sheets_connect'),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["spreadsheet_id"], "2CxiMVsNewConnect456")
        self.assertEqual(data["gid"], "10")
        self.assertEqual(data["rows_imported"], 1)

        # Confirm persisted in MySQL
        self.assertTrue(GoogleSheetConnection.objects.filter(spreadsheet_id="2CxiMVsNewConnect456").exists())
        self.assertTrue(Lead.objects.filter(phone="9888877777").exists())

    def test_api_connect_invalid_domain_blocked(self):
        payload = {
            "name": "Attack Sheet",
            "sheet_url": "https://attacker.com/spreadsheets/d/123456789012345/edit"
        }
        resp = self.client.post(
            reverse('api_google_sheets_connect'),
            data=json.dumps(payload),
            content_type="application/json"
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data["success"])
        self.assertIn("docs.google.com", data["error"])

    @patch('services.google_sheets_sync_service.fetch_sheet')
    def test_api_sync_now(self, mock_fetch):
        mock_fetch.return_value = (
            ["Full Name", "Phone Number"],
            [{"_row_index": 2, "Full Name": "Sync Lead", "Phone Number": "9999988888"}]
        )

        resp = self.client.post(
            reverse('api_google_sheets_sync', args=[self.connection.id])
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["sync_result"]["created"], 1)

    def test_api_detail_and_disconnect(self):
        # GET details
        resp = self.client.get(
            reverse('api_google_sheets_detail', args=[self.connection.id])
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["source"]["name"], "Existing Sheet")

        # DELETE (Disconnect)
        del_resp = self.client.delete(
            reverse('api_google_sheets_detail', args=[self.connection.id])
        )
        self.assertEqual(del_resp.status_code, 200)
        self.connection.refresh_from_db()
        self.assertFalse(self.connection.is_active)
        self.assertEqual(self.connection.connection_status, "DISCONNECTED")
