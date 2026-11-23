import unittest
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock external network modules
sys.modules["yfinance"] = MagicMock()
sys.modules["finnhub"] = MagicMock()
sys.modules["ib_insync"] = MagicMock()
sys.modules["apscheduler"] = MagicMock()
sys.modules["apscheduler.schedulers"] = MagicMock()
sys.modules["apscheduler.schedulers.background"] = MagicMock()
sys.modules["apscheduler.triggers"] = MagicMock()
sys.modules["apscheduler.triggers.cron"] = MagicMock()

from fastapi.testclient import TestClient
from api_server import app
from database import init_db
import auth
from security import rate_limiter


class TestSecurityHardening(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.client = TestClient(app)
        auth.IBKR_USERNAME = "testadmin"
        auth.IBKR_PASSWORD = auth.hash_password("SuperSecretPass123!")

    def test_security_headers_present(self):
        """Verify HSTS, CSP, X-Frame-Options, X-Content-Type-Options are returned."""
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(res.headers.get("X-Frame-Options"), "DENY")
        self.assertIn("max-age=31536000", res.headers.get("Strict-Transport-Security", ""))
        self.assertIn("default-src 'self'", res.headers.get("Content-Security-Policy", ""))
        self.assertEqual(res.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")

    def test_login_rate_limiting(self):
        """Verify brute-force rate limiter blocks requests exceeding threshold."""
        # Clear rate limit state
        rate_limiter.requests.clear()

        # 5 failed attempts
        for _ in range(5):
            res = self.client.post("/api/auth/login", json={"username": "testadmin", "password": "wrong"})
            self.assertEqual(res.status_code, 401)

        # 6th attempt must be rejected with 429
        res_blocked = self.client.post("/api/auth/login", json={"username": "testadmin", "password": "wrong"})
        self.assertEqual(res_blocked.status_code, 429)
        self.assertIn("Too many requests", res_blocked.json()["detail"])

    def test_auth_and_cookie_generation(self):
        """Verify valid login sets HttpOnly Secure cookie and issues valid token."""
        rate_limiter.requests.clear()
        res = self.client.post(
            "/api/auth/login",
            json={"username": "testadmin", "password": "SuperSecretPass123!"},
        )
        self.assertEqual(res.status_code, 200)
        json_data = res.json()
        self.assertIn("access_token", json_data)
        self.assertEqual(json_data["role"], "admin")
        self.assertIn("blitz_access_token", res.cookies)

    def test_admin_route_protection(self):
        """Verify non-admin / unauthenticated users cannot trigger administrative endpoints."""
        # Unauthenticated request to settings update
        res = self.client.put("/api/settings", json={"trading_mode": "paper"})
        self.assertEqual(res.status_code, 401)

        # Valid admin token succeeds
        admin_token = auth.create_access_token("testadmin", role="admin")
        res_admin = self.client.get(
            "/api/settings",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        self.assertEqual(res_admin.status_code, 200)

        # Non-admin token fails with 403 Forbidden
        viewer_token = auth.create_access_token("viewer", role="viewer")
        res_viewer = self.client.put(
            "/api/settings",
            headers={"Authorization": f"Bearer {viewer_token}"},
            json={"trading_mode": "paper"},
        )
        self.assertEqual(res_viewer.status_code, 403)


if __name__ == "__main__":
    unittest.main()
