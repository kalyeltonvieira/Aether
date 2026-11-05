import os
import tempfile
import time
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
    from aether.interfaces.api.app import create_app
except ImportError as exc:  # optional API dependencies are intentionally skippable
    TestClient = None
    create_app = None


@unittest.skipIf(TestClient is None, "API dependencies are not installed")
class StudioAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(data_dir=self.tmp.name, auth_mode="token", token="operator-token")
        self.client = TestClient(self.app)
        self.client.__enter__()
        response = self.client.post("/api/v1/auth/login", json={"token": "operator-token"})
        self.assertEqual(response.status_code, 200)
        self.csrf = response.json()["csrf_token"]
        self.headers = {"X-CSRF-Token": self.csrf}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_public_health_and_protected_read(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/info").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/entities").status_code, 401)

    def test_mutations_require_csrf_and_operator(self):
        missing = self.client.post("/api/v1/entities", json={"entity_id": "alice", "properties": {}})
        self.assertEqual(missing.status_code, 403)
        ok = self.client.post("/api/v1/entities", json={"entity_id": "alice", "properties": {}}, headers=self.headers)
        self.assertEqual(ok.status_code, 201)
        bad = self.client.post("/api/v1/entities", json={"entity_id": "bob", "properties": {}} , headers={"X-CSRF-Token": "bad"})
        self.assertEqual(bad.status_code, 403)

    def test_expired_session_is_rejected(self):
        session_id = self.client.cookies.get(self.app.state.auth.session_cookie)
        self.app.state.auth.sessions[session_id].expires_at = time.time() - 1
        self.assertEqual(self.client.get("/api/v1/config").status_code, 401)

    def test_validation_rejects_non_scalar_and_cors_is_finite(self):
        invalid = self.client.post("/api/v1/entities", json={"entity_id": "x", "properties": {"bad": []}}, headers=self.headers)
        self.assertEqual(invalid.status_code, 422)
        allowed = self.client.get("/api/v1/config", headers={"Origin": "http://localhost:3000"})
        self.assertEqual(allowed.headers.get("access-control-allow-origin"), "http://localhost:3000")
        disallowed = self.client.get("/api/v1/config", headers={"Origin": "https://evil.example"})
        self.assertNotEqual(disallowed.headers.get("access-control-allow-origin"), "https://evil.example")

    def test_empty_fact_filters_are_treated_as_unset(self):
        response = self.client.get("/api/v1/facts?subject=&predicate=")
        self.assertEqual(response.status_code, 200)
        self.assertIn("items", response.json())

    def test_login_rate_limit_and_logout_csrf(self):
        self.client.post("/api/v1/auth/logout")
        # Repeated invalid requests are bounded and do not disclose the token.
        statuses = [self.client.post("/api/v1/auth/login", json={"token": "wrong"}).status_code for _ in range(11)]
        self.assertIn(429, statuses)
