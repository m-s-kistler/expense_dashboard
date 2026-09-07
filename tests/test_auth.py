import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from expense_dashboard.auth import authorized_user


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.claims = dict(is_logged_in=True, iss="https://accounts.google.com", email="owner@example.com", email_verified=True, exp=2000)

    def test_verified_owner_allowed(self):
        self.assertTrue(authorized_user(self.claims, "OWNER@example.com", now=1000))

    def test_rejects_other_users_unverified_and_expired_sessions(self):
        for override in [
            {"is_logged_in": False}, {"email": "other@example.com"},
            {"email_verified": False}, {"email_verified": "true"},
            {"iss": "https://other.example.com"}, {"exp": 1000},
            {"exp": None}, {"exp": "invalid"},
        ]:
            with self.subTest(override=override):
                self.assertFalse(authorized_user(self.claims | override, "owner@example.com", now=1000))

    def test_missing_identity_or_allowlist_denied(self):
        self.assertFalse(authorized_user({}, "owner@example.com", now=1000))
        self.assertFalse(authorized_user(self.claims, "", now=1000))

    def test_unconfigured_app_stops_before_database_access(self):
        with patch("expense_dashboard.auth.st.secrets", {}), patch("expense_dashboard.db.connect") as connect:
            app = AppTest.from_file("app.py").run()
        self.assertFalse(app.exception)
        self.assertIn("Sign-in setup is not complete", app.info[0].value)
        connect.assert_not_called()

    def test_configured_app_requires_login_before_database_access(self):
        config = {
            "auth": {
                "client_id": "test-client", "client_secret": "test-secret",
                "cookie_secret": "test-cookie", "redirect_uri": "https://test.example.ts.net/oauth2callback",
                "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
            },
            "access": {"allowed_email": "owner@example.com"},
        }
        with patch("expense_dashboard.auth.st.secrets", config), patch("expense_dashboard.auth.st.user", {}), patch("expense_dashboard.db.connect") as connect:
            app = AppTest.from_file("app.py").run()
        self.assertFalse(app.exception)
        self.assertEqual(app.button[0].label, "Sign in with Google")
        connect.assert_not_called()
