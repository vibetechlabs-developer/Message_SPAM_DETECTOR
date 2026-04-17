from django.test import TestCase
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from unittest.mock import patch
from .utils import compute_lead_score, generate_mock_audit, generate_site_audit


class UtilsTests(TestCase):
    def test_compute_lead_score_caps_at_hundred(self):
        score, intent = compute_lead_score(
            email="owner@business.com",
            phone="+911234567890",
            source_url="https://example.com",
            keyword="best agency near me"
        )
        self.assertEqual(score, 100)
        self.assertEqual(intent, "high_intent")

    def test_generate_mock_audit_has_required_fields(self):
        result = generate_mock_audit("https://client-site.com")
        self.assertTrue(result["is_mock"])
        self.assertIn("disclaimer", result)
        self.assertIn("critical_issues_found", result)
        self.assertEqual(len(result["critical_issues_found"]), 3)

    @patch("core.utils._run_browser_audit")
    def test_generate_site_audit_uses_browser_results(self, mock_browser_audit):
        mock_browser_audit.return_value = {
            "status": 200,
            "finalUrl": "https://client-site.com",
            "title": "Client Landing Page For Services",
            "titleLength": 32,
            "metaDescriptionLength": 140,
            "hasMetaDescription": True,
            "hasViewport": True,
            "hasCanonical": True,
            "hasNoindex": False,
            "htmlLang": "en",
            "h1Count": 1,
            "formsCount": 1,
            "inputsCount": 2,
            "unlabeledInputsCount": 0,
            "buttonsCount": 2,
            "emptyButtonsCount": 0,
            "imageCount": 3,
            "missingAltCount": 0,
            "oversizedImages": 0,
            "internalLinkCount": 8,
            "externalLinkCount": 2,
            "insecureRequests": 0,
            "thirdPartyDomains": 2,
            "domContentLoadedMs": 900,
            "loadEventMs": 1500,
            "totalRequests": 12,
            "scriptRequests": 4,
            "imageRequests": 3,
            "stylesheetRequests": 2,
            "totalTransferSize": 350000,
            "failedRequestCount": 0,
            "badResponseCount": 0,
            "consoleErrorCount": 0,
            "blocked": False,
            "pagesAudited": 3,
            "pageSummaries": [
                {"url": "https://client-site.com", "status": 200, "title": "Home", "loadEventMs": 1200},
                {"url": "https://client-site.com/services", "status": 200, "title": "Services", "loadEventMs": 1600},
                {"url": "https://client-site.com/contact", "status": 200, "title": "Contact", "loadEventMs": 1100},
            ],
        }
        result = generate_site_audit("client-site.com")
        self.assertFalse(result["is_mock"])
        self.assertEqual(result["url"], "https://client-site.com")
        self.assertEqual(result["status"], "Good")
        self.assertIn("No high-confidence", result["critical_issues_found"][0])
        self.assertIn("what_we_can_improve", result)
        self.assertIn("competitor_benchmark", result)
        self.assertIn("delivery_plan", result)
        self.assertIn("outreach_summary", result)
        self.assertIn("technical_observations", result)
        self.assertEqual(result["pages_audited"], 3)
        self.assertEqual(len(result["audited_pages"]), 3)

    @patch("core.utils._run_browser_audit")
    def test_generate_site_audit_avoids_false_positives_on_challenge_page(self, mock_browser_audit):
        mock_browser_audit.return_value = {
            "status": 200,
            "finalUrl": "https://www.amazon.in/errors/validatecaptcha",
            "title": "Captcha",
            "titleLength": 7,
            "metaDescriptionLength": 0,
            "hasMetaDescription": False,
            "hasViewport": False,
            "hasCanonical": False,
            "hasNoindex": False,
            "htmlLang": "",
            "h1Count": 0,
            "formsCount": 0,
            "inputsCount": 0,
            "unlabeledInputsCount": 0,
            "buttonsCount": 0,
            "emptyButtonsCount": 0,
            "imageCount": 0,
            "missingAltCount": 0,
            "oversizedImages": 0,
            "internalLinkCount": 0,
            "externalLinkCount": 0,
            "insecureRequests": 0,
            "thirdPartyDomains": 0,
            "domContentLoadedMs": 1200,
            "loadEventMs": 1400,
            "totalRequests": 3,
            "scriptRequests": 1,
            "imageRequests": 0,
            "stylesheetRequests": 0,
            "totalTransferSize": 15000,
            "failedRequestCount": 0,
            "badResponseCount": 0,
            "consoleErrorCount": 0,
            "blocked": True,
            "pagesAudited": 1,
            "pageSummaries": [
                {"url": "https://www.amazon.in/errors/validatecaptcha", "status": 200, "title": "Captcha", "loadEventMs": 1400},
            ],
        }
        result = generate_site_audit("https://www.amazon.in")
        self.assertFalse(result["is_mock"])
        self.assertEqual(result["performance_score"], "N/A")
        self.assertEqual(result["status"], "Review Required")
        self.assertIn("fake issues", result["disclaimer"].lower())

    @patch("core.utils._run_browser_audit")
    def test_generate_site_audit_detects_multiple_real_issues(self, mock_browser_audit):
        mock_browser_audit.return_value = {
            "status": 200,
            "finalUrl": "https://slow-site.com",
            "title": "Slow Site",
            "titleLength": 9,
            "metaDescriptionLength": 0,
            "hasMetaDescription": False,
            "hasViewport": True,
            "hasCanonical": False,
            "hasNoindex": False,
            "htmlLang": "en",
            "h1Count": 0,
            "formsCount": 1,
            "inputsCount": 4,
            "unlabeledInputsCount": 2,
            "buttonsCount": 2,
            "emptyButtonsCount": 1,
            "imageCount": 10,
            "missingAltCount": 6,
            "oversizedImages": 4,
            "internalLinkCount": 10,
            "externalLinkCount": 8,
            "insecureRequests": 1,
            "thirdPartyDomains": 14,
            "domContentLoadedMs": 3400,
            "loadEventMs": 6200,
            "totalRequests": 140,
            "scriptRequests": 40,
            "imageRequests": 20,
            "stylesheetRequests": 14,
            "totalTransferSize": 8200000,
            "failedRequestCount": 3,
            "badResponseCount": 5,
            "consoleErrorCount": 2,
            "blocked": False,
            "pagesAudited": 3,
            "pageSummaries": [
                {"url": "https://slow-site.com", "status": 200, "title": "Home", "loadEventMs": 6200},
                {"url": "https://slow-site.com/services", "status": 200, "title": "Services", "loadEventMs": 5900},
                {"url": "https://slow-site.com/contact", "status": 200, "title": "Contact", "loadEventMs": 3400},
            ],
        }
        result = generate_site_audit("https://slow-site.com")
        joined_issues = " ".join(result["critical_issues_found"]).lower()
        self.assertIn("slow", joined_issues)
        self.assertTrue(result["technical_observations"])
        self.assertNotEqual(result["estimated_cost_to_fix"], "$0")
        self.assertEqual(result["pages_audited"], 3)


class KeywordSearchViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="tester", password="secret123")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    @patch("core.views.scrape_leads")
    @patch("core.views.search_keyword_urls")
    def test_keyword_search_returns_preview_data(self, mock_search_keyword_urls, mock_scrape_leads):
        mock_search_keyword_urls.return_value = ["https://example.com"]
        mock_scrape_leads.return_value = {
            "status": "success",
            "leads": [
                {
                    "source": "https://example.com",
                    "contact_name": "Example Rep",
                    "email": "hello@example.com",
                    "phone": "+911234567890",
                }
            ],
        }

        response = self.client.post("/api/keyword-search", {"keyword": "example services"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["new_leads_found"], 1)
        self.assertIn("existing_leads_found", response.data)
        self.assertEqual(len(response.data["searched_urls"]), 1)
        self.assertEqual(len(response.data["new_leads"]), 1)
        self.assertEqual(response.data["new_leads"][0]["contact_name"], "Example Rep")


class LeadsCsvImportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="csv-user", password="secret123")
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_import_csv_creates_rows_and_skips_duplicates(self):
        content = (
            "name,email,phone,website,keyword,status\n"
            "Alice,alice@example.com,+911111111111,example.com,plumber,new\n"
            "Alice2,alice@example.com,+922222222222,example2.com,plumber,new\n"
            "Bob,not_found,not_found,agency.com,agency,contacted\n"
        ).encode("utf-8")
        upload = SimpleUploadedFile("leads.csv", content, content_type="text/csv")

        response = self.client.post("/api/leads/import-csv", {"file": upload}, format="multipart")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["created"], 2)
        self.assertEqual(response.data["skipped"], 1)
