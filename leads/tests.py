from django.test import TestCase, Client
from django.urls import reverse
from django.core.exceptions import ValidationError
from accounts.models import User, UserRole
from accounts.permissions import get_accessible_branch_ids
from branches.models import Branch, SalesHeadBranchAccess
from channels.models import Channel
from products.models import Product
from leads.models import Lead, LeadStatus

class LeadManagementTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.branch = Branch.objects.create(name="South Campus")
        self.branch_b = Branch.objects.create(name="North Campus")
        self.channel = Channel.objects.create(name="Website")
        self.product = Product.objects.create(name="Python FullStack", price=25000)

        self.manager_a = User.objects.create_user(username="m_alpha", password="pwd", role=UserRole.SALES_HEAD, branch=self.branch)
        self.manager_b = User.objects.create_user(username="m_beta", password="pwd", role=UserRole.SALES_HEAD, branch=self.branch_b)
        SalesHeadBranchAccess.objects.create(sales_head=self.manager_a, branch=self.branch)
        SalesHeadBranchAccess.objects.create(sales_head=self.manager_b, branch=self.branch_b)

        self.telecaller_a = User.objects.create_user(
            username="tc_alpha", password="pwd", role=UserRole.TELECALLER, branch=self.branch
        )
        self.telecaller_b = User.objects.create_user(
            username="tc_beta", password="pwd", role=UserRole.TELECALLER, branch=self.branch_b
        )

        self.lead_a = Lead.objects.create(
            name="Rahul Kumar",
            phone="9876543210",
            email="rahul@example.com",
            channel=self.channel,
            product=self.product,
            branch=self.branch,
            assigned_sales_head=self.manager_a,
            assigned_telecaller=self.telecaller_a,
            status=LeadStatus.NEW
        )

        self.lead_b = Lead.objects.create(
            name="Sneha Sharma",
            phone="9876543211",
            email="sneha@example.com",
            channel=self.channel,
            product=self.product,
            branch=self.branch_b,
            assigned_sales_head=self.manager_b,
            assigned_telecaller=self.telecaller_b,
            status=LeadStatus.CONTACTED
        )

    def test_invalid_telecaller_branch_assignment_clean(self):
        """Telecaller must belong to the lead's branch."""
        invalid_lead = Lead(
            name="Invalid Pairing",
            phone="9999900000",
            branch=self.branch,
            assigned_telecaller=self.telecaller_b  # telecaller_b belongs to a different branch!
        )
        with self.assertRaises(ValidationError):
            invalid_lead.clean()

    def test_manager_lead_scoping(self):
        """Manager A should only see lead_a, not lead_b."""
        self.client.login(username='m_alpha', password='pwd')
        response = self.client.get(reverse('manager_leads_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rahul Kumar")
        self.assertNotContains(response, "Sneha Sharma")

    def test_manager_forbidden_from_other_lead_detail(self):
        """Manager A accessing Lead B details must be blocked."""
        self.client.login(username='m_alpha', password='pwd')
        response = self.client.get(reverse('manager_lead_detail', args=[self.lead_b.pk]))
        self.assertRedirects(response, reverse('manager_leads_list'))

    def test_telecaller_lead_scoping(self):
        """Telecaller A should only access lead_a, not lead_b."""
        self.client.login(username='tc_alpha', password='pwd')
        response = self.client.get(reverse('telecaller_leads_list'))
        self.assertContains(response, "Rahul Kumar")
        self.assertNotContains(response, "Sneha Sharma")

        forbidden_response = self.client.get(reverse('telecaller_lead_detail', args=[self.lead_b.pk]))
        self.assertRedirects(forbidden_response, reverse('telecaller_leads_list'))

    def test_manager_lead_create(self):
        self.client.login(username='m_alpha', password='pwd')
        response = self.client.post(reverse('manager_lead_create'), {
            'name': 'Manager Created Lead',
            'phone': '9123456780',
            'email': 'mgrlead@example.com',
            'status': LeadStatus.NEW,
            'assigned_telecaller': self.telecaller_a.pk,
            'channel': self.channel.pk,
            'product': self.product.pk,
            'branch': self.branch.pk,
            'notes': 'Test notes'
        })
        new_lead = Lead.objects.filter(phone='9123456780').first()
        self.assertIsNotNone(new_lead)
        self.assertEqual(new_lead.assigned_sales_head, self.manager_a)
        self.assertEqual(new_lead.assigned_telecaller, self.telecaller_a)

    def test_telecaller_lead_create(self):
        self.client.login(username='tc_alpha', password='pwd')
        response = self.client.post(reverse('telecaller_lead_create'), {
            'name': 'Telecaller Created Lead',
            'phone': '9123456781',
            'email': 'tclead@example.com',
            'channel': self.channel.pk,
            'product': self.product.pk,
            'notes': 'Added by telecaller'
        })
        new_lead = Lead.objects.filter(phone='9123456781').first()
        self.assertIsNotNone(new_lead)
        self.assertEqual(new_lead.assigned_telecaller, self.telecaller_a)
        self.assertEqual(new_lead.assigned_sales_head, self.manager_a)

    def test_csv_upload_service(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from leads.services import import_leads_file

        csv_content = b"name,phone,email,channel,product,notes\nUpload Lead 1,9811111111,u1@test.com,Website,Python FullStack,Good lead\nUpload Lead 2,9822222222,u2@test.com,Website,Python FullStack,Another lead"
        file = SimpleUploadedFile("leads.csv", csv_content, content_type="text/csv")

        successful, failed, errors = import_leads_file(file, self.manager_a)
        self.assertEqual(successful, 2)
        self.assertEqual(failed, 0)
        self.assertTrue(Lead.objects.filter(phone='9811111111').exists())

    def test_assign_lead_automatically_balanced(self):
        from leads.assignment import assign_lead_automatically

        lead1 = Lead.objects.create(name="Auto 1", phone="9900000001", status=LeadStatus.NEW)
        lead2 = Lead.objects.create(name="Auto 2", phone="9900000002", status=LeadStatus.NEW)

        assign_lead_automatically(lead1)
        lead1.save()
        assign_lead_automatically(lead2)
        lead2.save()

        # Both leads should have valid assigned manager and telecaller
        self.assertIsNotNone(lead1.assigned_sales_head)
        self.assertIsNotNone(lead1.assigned_telecaller)
        self.assertEqual(lead1.assigned_telecaller.branch, lead1.branch)

        self.assertIsNotNone(lead2.assigned_sales_head)
        self.assertIsNotNone(lead2.assigned_telecaller)
        self.assertEqual(lead2.assigned_telecaller.branch, lead2.branch)

    def test_assign_lead_inactive_users_excluded(self):
        from leads.assignment import assign_lead_automatically

        # Deactivate manager_a
        self.manager_a.is_active = False
        self.manager_a.save()

        lead = Lead.objects.create(name="Active Only Lead", phone="9900000003", status=LeadStatus.NEW)
        assign_lead_automatically(lead)
        lead.save()

        # Must be assigned to active manager_b, NOT manager_a
        self.assertEqual(lead.assigned_sales_head, self.manager_b)
        self.assertEqual(lead.assigned_telecaller, self.telecaller_b)

        # Restore
        self.manager_a.is_active = True
        self.manager_a.save()

    def test_duplicate_detection_and_update_in_import(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from leads.services import import_leads_file

        # Existing lead_a has manager_a and telecaller_a, phone="9876543210"
        csv_dup = b"name,phone,email,channel,product,notes\nRahul Updated,9876543210,rahul_new@test.com,Website,Python FullStack,New notes added"
        file = SimpleUploadedFile("dup.csv", csv_dup, content_type="text/csv")

        successful, failed, errors = import_leads_file(file, self.manager_b)
        self.assertEqual(successful, 1)
        self.assertEqual(failed, 0)

        self.lead_a.refresh_from_db()
        self.assertEqual(self.lead_a.name, "Rahul Updated")
        self.assertIn("New notes added", self.lead_a.notes)
        # Assignment MUST remain preserved as manager_a, NOT overwritten
        self.assertEqual(self.lead_a.assigned_sales_head, self.manager_a)
        self.assertEqual(self.lead_a.assigned_telecaller, self.telecaller_a)

    def test_branch_auto_inference_when_omitted(self):
        from leads.forms import AdminLeadForm

        # Admin user
        admin = User.objects.create_superuser(username="admin_lead_tester", password="pwd")

        # Telecaller a has branch
        self.telecaller_a.branch = self.branch
        self.telecaller_a.save()

        form_data = {
            'name': 'Branch Inferred Lead',
            'phone': '9900000099',
            'assigned_manager': self.manager_a.pk,
            'assigned_telecaller': self.telecaller_a.pk,
            'status': LeadStatus.NEW,
            # 'branch' is omitted
        }
        form = AdminLeadForm(data=form_data)
        self.assertTrue(form.is_valid(), form.errors)
        saved_lead = form.save()
        self.assertIsNotNone(saved_lead.branch)
        self.assertEqual(saved_lead.branch, self.branch)

    def test_offline_leads_polling_api(self):
        admin = User.objects.create_superuser(username="admin_poll_test", password="pwd")
        self.client.login(username="admin_poll_test", password="pwd")

        response = self.client.get(reverse('admin_offline_leads_data_api'))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('html', data)
        self.assertIn('timestamp', data)
        self.assertIn('total_count', data)


class DuplicateLeadsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username="admin_dup_tester",
            email="admin@dup.test",
            password="TestPassword123!@#",
            role=UserRole.ADMIN
        )
        self.branch_chennai = Branch.objects.create(name="Chennai Branch", status="Active")
        self.branch_madurai = Branch.objects.create(name="Madurai Branch", status="Active")
        self.branch_coimbatore = Branch.objects.create(name="Coimbatore Branch", status="Active")
        self.client.force_login(self.admin)

    def test_phone_normalization(self):
        from leads.duplicates import normalize_phone
        self.assertEqual(normalize_phone("+91 98765 43210"), "9876543210")
        self.assertEqual(normalize_phone("09876543210"), "9876543210")
        self.assertEqual(normalize_phone("98765-43210"), "9876543210")
        self.assertEqual(normalize_phone("(987) 654-3210"), "9876543210")

    def test_find_duplicate_lead(self):
        from leads.duplicates import find_duplicate_lead
        lead = Lead.objects.create(
            name="Arun Kumar",
            phone="9876543210",
            email="arun@example.com",
            branch=self.branch_chennai
        )

        # Match by phone with country code
        found_phone = find_duplicate_lead(phone="+91 9876543210")
        self.assertEqual(found_phone, lead)

        # Match by email
        found_email = find_duplicate_lead(email="ARUN@EXAMPLE.COM")
        self.assertEqual(found_email, lead)

        # Non-matching
        self.assertIsNone(find_duplicate_lead(phone="9123456789"))

    def test_multiple_branch_duplicate_import(self):
        """
        When Arun Kumar appears in Chennai and then Madurai,
        the system must maintain ONE unique lead record with both branches.
        """
        import io
        from leads.services import import_leads_file

        csv_content = (
            "name,phone,branch\n"
            "Arun Kumar,9876543210,Chennai Branch\n"
            "Arun Kumar,9876543210,Madurai Branch\n"
            "Arun Kumar,9876543210,Coimbatore Branch\n"
        )
        file_obj = io.BytesIO(csv_content.encode('utf-8'))
        file_obj.name = "leads_multi_branch.csv"

        successful, failed, errors = import_leads_file(file_obj, self.admin)
        self.assertEqual(successful, 3)

        # EXACTLY ONE lead record in DB for Arun Kumar
        leads_count = Lead.objects.filter(phone="9876543210").count()
        self.assertEqual(leads_count, 1)

        lead = Lead.objects.get(phone="9876543210")
        self.assertEqual(lead.name, "Arun Kumar")
        # Primary branch is Chennai
        self.assertEqual(lead.branch, self.branch_chennai)
        # Secondary branches contain Madurai and Coimbatore
        branch_names = lead.get_all_branch_names()
        self.assertIn("Chennai Branch", branch_names)
        self.assertIn("Madurai Branch", branch_names)
        self.assertIn("Coimbatore Branch", branch_names)

    def test_detect_all_duplicate_groups(self):
        from leads.duplicates import detect_all_duplicate_groups

        # Create two distinct DB records with the same phone (e.g. historical unmerged duplicates)
        lead1 = Lead.objects.create(name="Arun Kumar", phone="9876543210", branch=self.branch_chennai)
        lead2 = Lead.objects.create(name="Arun Kumar", phone="9876543210", branch=self.branch_madurai)

        groups, count = detect_all_duplicate_groups()
        self.assertGreaterEqual(count, 1)

        group = next((g for g in groups if "9876543210" in g['phone']), None)
        self.assertIsNotNone(group)
        self.assertEqual(group['name'], "Arun Kumar")
        self.assertIn("Chennai Branch", group['branches'])
        self.assertIn("Madurai Branch", group['branches'])
        self.assertEqual(group['lead_count'], 2)

    def test_keep_single_lead_consolidation(self):
        from leads.duplicates import keep_single_lead_for_group
        from followups.models import FollowUp, FollowUpStatus
        from django.utils import timezone

        lead1 = Lead.objects.create(name="Arun Kumar", phone="9876543210", branch=self.branch_chennai, notes="Note 1")
        lead2 = Lead.objects.create(name="Arun Kumar", phone="9876543210", branch=self.branch_madurai, email="arun@madurai.com")

        # Create follow-up attached to lead2
        FollowUp.objects.create(
            lead=lead2,
            follow_up_date=timezone.now().date(),
            notes="Followup from Madurai branch",
            status=FollowUpStatus.PENDING
        )

        primary_lead = keep_single_lead_for_group([lead1.id, lead2.id], user=self.admin)

        # Only 1 lead remains in the database
        self.assertEqual(Lead.objects.filter(phone="9876543210").count(), 1)
        self.assertEqual(primary_lead.id, lead1.id)
        self.assertEqual(primary_lead.email, "arun@madurai.com")

        # Branch from lead2 transferred to secondary_branches
        branch_names = primary_lead.get_all_branch_names()
        self.assertIn("Chennai Branch", branch_names)
        self.assertIn("Madurai Branch", branch_names)

        # Followup re-pointed to primary_lead
        self.assertEqual(FollowUp.objects.filter(lead=primary_lead).count(), 1)

    def test_duplicate_leads_view_and_keep_single_ajax(self):
        lead1 = Lead.objects.create(name="Arun Kumar", phone="9876543210", branch=self.branch_chennai)
        lead2 = Lead.objects.create(name="Arun Kumar", phone="9876543210", branch=self.branch_madurai)

        # View review page
        res = self.client.get(reverse('admin_duplicate_leads'))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn("DUPLICATE LEADS", content)
        self.assertIn("Arun Kumar", content)
        self.assertIn("Chennai Branch", content)
        self.assertIn("Madurai Branch", content)
        self.assertIn("[ Keep Single Lead ]", content)

        # Action: Keep Single Lead via AJAX
        merge_url = reverse('admin_duplicate_leads_keep_single')
        post_res = self.client.post(
            merge_url,
            {'lead_ids': f"{lead1.id},{lead2.id}"},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(post_res.status_code, 200)
        data = post_res.json()
        self.assertTrue(data['success'])
        self.assertEqual(Lead.objects.filter(phone="9876543210").count(), 1)

    def test_sidebar_structure_no_pipeline_stages(self):
        res = self.client.get(reverse('admin_leads_list'))
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')

        # Sidebar must not contain Pipeline Stages
        self.assertNotIn("Pipeline Stages", content)

        # Must contain required navigation links
        self.assertIn("Follow-ups", content)
        self.assertIn("Calls", content)
        self.assertIn("Integrations", content)
        self.assertIn("Configuration", content)
        self.assertIn("Settings", content)


