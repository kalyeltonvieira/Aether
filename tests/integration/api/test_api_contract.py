import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import jwt
    from fastapi.testclient import TestClient
    from aether.interfaces.api.app import create_app
    from aether.interfaces.api.services.state import _atomic_json
except ImportError:  # optional API dependencies are intentionally skippable
    jwt = None
    TestClient = None
    create_app = None
    _atomic_json = None


@unittest.skipIf(TestClient is None or jwt is None, "API dependencies are not installed")
class ManagedPreviewAuthTests(unittest.TestCase):
    def _environment(self, *, open_ids: str = "owner-1"):
        return patch.dict(
            os.environ,
            {
                "MANUS_JWT_SECRET": "test-preview-secret-0123456789abcdef",
                "MANUS_PROJECT_ID": "project-123",
                "AETHER_OPERATOR_OPEN_IDS": open_ids,
                "AETHER_OWNER_OPEN_IDS": "",
                "AETHER_OWNER_OPEN_ID": "",
                "MANUS_OWNER_OPEN_ID": "",
            },
            clear=False,
        )

    @staticmethod
    def _jwt(*, open_id: str = "owner-1", app_id: str = "project-123", expires_at: int | None = None) -> str:
        return jwt.encode(
            {
                "openId": open_id,
                "appId": app_id,
                "exp": int(time.time()) + 60 if expires_at is None else expires_at,
            },
            "test-preview-secret-0123456789abcdef",
            algorithm="HS256",
        )

    def test_preview_cookie_and_role_resolution(self):
        with self._environment():
            with tempfile.TemporaryDirectory() as data_dir:
                app = create_app(data_dir=data_dir, auth_mode="manus", public_origin="https://preview.example")
                with TestClient(app) as client:
                    token = self._jwt()
                    client.cookies.set("webdev_app_session", token)
                    session = client.get("/api/v1/auth/session")
                    self.assertEqual(session.status_code, 200)
                    self.assertEqual(session.json()["role"], "operator")
                    self.assertEqual(session.json()["auth_mode"], "manus")
                    self.assertIn("webdev_app_session", session.headers.get("set-cookie", ""))
                    set_cookie = session.headers["set-cookie"].lower()
                    self.assertIn("secure", set_cookie)
                    self.assertIn("samesite=none", set_cookie)
                    self.assertEqual(app.state.auth.session_cookie, "webdev_app_session")
                    info = client.get("/api/v1/auth/info")
                    self.assertEqual(set(info.json()), {"mode", "login_available"})

    def test_preview_defaults_to_reader_and_rejects_expired_or_wrong_project(self):
        with self._environment(open_ids=""):
            with tempfile.TemporaryDirectory() as data_dir:
                app = create_app(data_dir=data_dir, auth_mode="manus")
                with TestClient(app) as client:
                    client.cookies.set("webdev_app_session", self._jwt(open_id="reader-1"))
                    session = client.get("/api/v1/auth/session")
                    self.assertEqual(session.status_code, 200)
                    self.assertEqual(session.json()["role"], "reader")
                    csrf = session.json()["csrf_token"]
                    denied = client.post(
                        "/api/v1/entities",
                        json={"entity_id": "blocked", "properties": {}},
                        headers={"X-CSRF-Token": csrf},
                    )
                    self.assertEqual(denied.status_code, 403)

            with tempfile.TemporaryDirectory() as expired_dir:
                expired_app = create_app(data_dir=expired_dir, auth_mode="manus")
                with TestClient(expired_app) as client:
                    client.cookies.set("webdev_app_session", self._jwt(expires_at=int(time.time()) - 1))
                    self.assertEqual(client.get("/api/v1/auth/session").status_code, 401)

            with tempfile.TemporaryDirectory() as wrong_project_dir:
                wrong_app = create_app(data_dir=wrong_project_dir, auth_mode="manus")
                with TestClient(wrong_app) as client:
                    client.cookies.set("webdev_app_session", self._jwt(app_id="other-project"))
                    self.assertEqual(client.get("/api/v1/auth/session").status_code, 401)

    def test_preview_session_expires_at_validated_jwt_expiry(self):
        with self._environment():
            with tempfile.TemporaryDirectory() as data_dir:
                app = create_app(data_dir=data_dir, auth_mode="manus")
                with TestClient(app) as client:
                    expires_at = int(time.time()) + 120
                    client.cookies.set("webdev_app_session", self._jwt(expires_at=expires_at))
                    with patch("aether.interfaces.api.services.auth.time.time", return_value=expires_at - 10):
                        created = client.get("/api/v1/auth/session")
                        self.assertEqual(created.status_code, 200)
                        session_id = next(iter(app.state.auth.sessions))
                        self.assertEqual(app.state.auth.sessions[session_id].expires_at, expires_at)
                    with patch("aether.interfaces.api.services.auth.time.time", return_value=expires_at + 1):
                        self.assertEqual(client.get("/api/v1/auth/session").status_code, 401)


@unittest.skipIf(TestClient is None, "API dependencies are not installed")
class ApiStateContractTests(unittest.TestCase):
    def test_typed_values_rules_config_and_restart(self):
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(app) as client:
                login = client.post("/api/v1/auth/login", json={"token": "operator-token"})
                self.assertEqual(login.status_code, 200)
                headers = {"X-CSRF-Token": login.json()["csrf_token"]}
                for entity_id in ("alice", "bob"):
                    self.assertEqual(
                        client.post("/api/v1/entities", json={"entity_id": entity_id, "properties": {}}, headers=headers).status_code,
                        201,
                    )
                typed = (
                    ("bool", True, "bool"),
                    ("int", 1, "int"),
                    ("float", 1.5, "float"),
                    ("str", "one", "str"),
                    ("null", None, "null"),
                )
                for predicate, value, object_type in typed:
                    response = client.post(
                        "/api/v1/facts",
                        json={"subject": "alice", "predicate": predicate, "object": value, "object_type": object_type},
                        headers=headers,
                    )
                    self.assertEqual(response.status_code, 201)
                    self.assertEqual(response.json()["object_type"], object_type)
                rule = client.post(
                    "/api/v1/rules",
                    json={
                        "rule_id": "contact-rule",
                        "antecedents": [{"subject": "?x", "predicate": "str", "object": "?y"}],
                        "consequent": {"subject": "?x", "predicate": "contacted", "object": "?y"},
                    },
                    headers=headers,
                )
                self.assertEqual(rule.status_code, 201)
                config = client.put(
                    "/api/v1/config",
                    json={"max_depth": 12, "max_operations": 20000, "join_planner": "input"},
                    headers=headers,
                )
                self.assertEqual(config.status_code, 200)
                toggle_off = client.put(
                    "/api/v1/config", json={"persistence_enabled": False}, headers=headers
                )
                self.assertEqual(toggle_off.status_code, 422)
                self.assertTrue(client.get("/api/v1/config").json()["persistence_enabled"])

            restarted = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(restarted) as client:
                login = client.post("/api/v1/auth/login", json={"token": "operator-token"})
                self.assertEqual(login.status_code, 200)
                self.assertEqual(client.get("/api/v1/facts").json()["total"], 5)
                self.assertEqual(client.get("/api/v1/rules").json()["items"][0]["rule_id"], "contact-rule")
                persisted_config = client.get("/api/v1/config").json()
                self.assertEqual(persisted_config["max_depth"], 12)
                self.assertEqual(persisted_config["max_operations"], 20000)
                facts = {item["predicate"]: item for item in client.get("/api/v1/facts").json()["items"]}
                self.assertIs(facts["bool"]["object"], True)
                self.assertEqual(facts["int"]["object"], 1)
                self.assertEqual(facts["null"]["object"], None)

    def test_persistence_disabled_uses_ephemeral_stores_and_requires_restart_to_toggle(self):
        with tempfile.TemporaryDirectory() as data_dir:
            root = Path(data_dir)
            legacy_files = {
                "knowledge.json": b"do-not-load-knowledge",
                "rules.json": b"do-not-load-rules",
                "events.sqlite3": b"do-not-open-events",
                "memory.sqlite3": b"do-not-open-memory",
            }
            for filename, payload in legacy_files.items():
                (root / filename).write_bytes(payload)
            _atomic_json(root / "config.json", {"persistence_enabled": False})

            app = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(app) as client:
                login = client.post("/api/v1/auth/login", json={"token": "operator-token"})
                headers = {"X-CSRF-Token": login.json()["csrf_token"]}
                state = app.state.studio
                self.assertFalse(state.config["persistence_enabled"])
                self.assertEqual(state.events.path, ":memory:")
                self.assertIsNone(state.memory.cold_store)
                self.assertEqual(state.store.stats()["facts"], 0)
                self.assertEqual(state.rules, [])

                toggle_on = client.put(
                    "/api/v1/config", json={"persistence_enabled": True}, headers=headers
                )
                self.assertEqual(toggle_on.status_code, 422)
                self.assertIn("startup-only", toggle_on.json()["detail"])
                self.assertFalse(client.get("/api/v1/config").json()["persistence_enabled"])

                created = client.post(
                    "/api/v1/entities",
                    json={"entity_id": "ephemeral", "properties": {}},
                    headers=headers,
                )
                self.assertEqual(created.status_code, 201)
                queued = client.post(
                    "/api/v1/events",
                    json={"event_type": "entity.add", "source": "test", "payload": {"entity_id": "event-only"}},
                    headers=headers,
                )
                self.assertEqual(queued.status_code, 202)
                state.memory.put("test:ephemeral", b"ephemeral")

            for filename, payload in legacy_files.items():
                self.assertEqual((root / filename).read_bytes(), payload)

    def test_default_strategy_event_batch_graph_pagination_and_status(self):
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(app) as client:
                login = client.post("/api/v1/auth/login", json={"token": "operator-token"})
                headers = {"X-CSRF-Token": login.json()["csrf_token"]}

                configured = client.put(
                    "/api/v1/config",
                    json={"default_strategy": "backward", "event_batch_size": 1},
                    headers=headers,
                )
                self.assertEqual(configured.status_code, 200)
                self.assertEqual(configured.json()["default_strategy"], "backward")
                self.assertEqual(configured.json()["event_batch_size"], 1)
                self.assertEqual(
                    client.put("/api/v1/config", json={"default_strategy": "adaptive"}, headers=headers).status_code,
                    422,
                )

                query = client.post("/api/v1/queries", json={"subject": "missing", "predicate": "p", "object": "value"})
                self.assertEqual(query.status_code, 200)
                self.assertEqual(query.json()["strategy"], "backward")

                for entity_id in ("event-a", "event-b"):
                    queued = client.post(
                        "/api/v1/events",
                        json={"event_type": "entity.add", "source": "test", "payload": {"entity_id": entity_id}},
                        headers=headers,
                    )
                    self.assertEqual(queued.status_code, 202)
                processed = client.post("/api/v1/events/process", json={}, headers=headers)
                self.assertEqual(processed.status_code, 200)
                self.assertEqual(processed.json()["attempted"], 1)
                self.assertEqual(processed.json()["processed"], 1)

                for entity_id in ("a", "b", "c"):
                    self.assertEqual(
                        client.post("/api/v1/entities", json={"entity_id": entity_id, "properties": {}}, headers=headers).status_code,
                        201,
                    )
                facts = []
                for target in ("b", "c"):
                    response = client.post(
                        "/api/v1/facts",
                        json={"subject": "a", "predicate": "link", "object": target, "object_type": "str"},
                        headers=headers,
                    )
                    self.assertEqual(response.status_code, 201)
                    facts.append(response.json()["fact_id"])
                response = client.post(
                    "/api/v1/facts",
                    json={"subject": "b", "predicate": "link", "object": "c", "object_type": "str"},
                    headers=headers,
                )
                self.assertEqual(response.status_code, 201)
                facts.append(response.json()["fact_id"])

                self.assertEqual(client.get("/api/v1/facts?subject=&predicate=").status_code, 200)
                self.assertEqual(client.get("/api/v1/events?event_type=&status=").status_code, 200)
                empty_filter_graph = client.get("/api/v1/graph?predicate=&center=")
                self.assertEqual(empty_filter_graph.status_code, 200)
                self.assertEqual(empty_filter_graph.json()["total"], 3)

                first_page = client.get("/api/v1/graph?center=a&offset=0&limit=1")
                self.assertEqual(first_page.status_code, 200)
                self.assertEqual(first_page.json()["total"], 3)
                self.assertEqual(first_page.json()["offset"], 0)
                self.assertEqual(first_page.json()["next_offset"], 1)
                self.assertTrue(first_page.json()["truncated"])
                self.assertEqual(first_page.json()["edges"][0]["fact_id"], facts[0])
                self.assertIn("a", {node["id"] for node in first_page.json()["nodes"]})

                second_page = client.get("/api/v1/graph?center=a&offset=1&limit=1")
                self.assertEqual(second_page.status_code, 200)
                self.assertEqual(second_page.json()["edges"][0]["fact_id"], facts[1])
                self.assertEqual(second_page.json()["next_offset"], 2)

                removed = client.delete(f"/api/v1/facts/{facts[0]}", headers=headers)
                self.assertEqual(removed.status_code, 200)
                status = client.get("/api/v1/status")
                self.assertEqual(status.status_code, 200)
                core = status.json()["core"]
                self.assertEqual(core["status"], "incomplete")
                self.assertFalse(core["complete"])
                self.assertIsNotNone(core["stale_reason"])
                self.assertIsNone(core["conclusions"])
                self.assertIsNone(status.json()["rust"]["operations"])
                self.assertIsNone(client.get("/api/v1/metrics").json()["samples"][-1]["rust_operations"])

    def test_query_and_explanation_preserve_scalar_types(self):
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(app) as client:
                login = client.post("/api/v1/auth/login", json={"token": "operator-token"})
                headers = {"X-CSRF-Token": login.json()["csrf_token"]}
                self.assertEqual(
                    client.post("/api/v1/entities", json={"entity_id": "alice", "properties": {}}, headers=headers).status_code,
                    201,
                )
                fact = client.post(
                    "/api/v1/facts",
                    json={"subject": "alice", "predicate": "score", "object": 1, "object_type": "int"},
                    headers=headers,
                )
                self.assertEqual(fact.status_code, 201)
                rule = client.post(
                    "/api/v1/rules",
                    json={
                        "rule_id": "score-rule",
                        "antecedents": [{"subject": "?x", "predicate": "score", "object": "?y"}],
                        "consequent": {"subject": "?x", "predicate": "scored", "object": "?y"},
                    },
                    headers=headers,
                )
                self.assertEqual(rule.status_code, 201)
                query = client.post(
                    "/api/v1/queries",
                    json={"subject": "?x", "predicate": "scored", "object": "?y", "strategy": "forward"},
                )
                self.assertEqual(query.status_code, 200)
                solution = query.json()["solutions"][0]
                self.assertEqual(solution["object_type"], "int")
                self.assertEqual(solution["explanation"][0]["key_type"], ["str", "str", "int"])
                support = solution["explanation"][0]["proofs"][0]["supports"][0]
                self.assertEqual(support["key"], ["alice", "score", 1])
                self.assertEqual(support["key_type"], ["str", "str", "int"])

    def test_event_processing_updates_query_state_and_websocket(self):
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(app) as client:
                login = client.post("/api/v1/auth/login", json={"token": "operator-token"})
                headers = {"X-CSRF-Token": login.json()["csrf_token"]}
                for entity_id in ("alice", "bob"):
                    client.post("/api/v1/entities", json={"entity_id": entity_id, "properties": {}}, headers=headers)
                query_payload = {"subject": "alice", "predicate": "sent", "object": "bob", "strategy": "forward"}
                initial = client.post("/api/v1/queries", json=query_payload)
                self.assertFalse(initial.json()["proven"])
                with client.websocket_connect("/ws", headers={"origin": "http://localhost:3000"}) as socket:
                    self.assertEqual(socket.receive_json()["type"], "snapshot")
                    queued = client.post(
                        "/api/v1/events",
                        json={
                            "event_type": "fact.add",
                            "source": "studio",
                            "payload": {"subject": "alice", "predicate": "sent", "object": "bob"},
                        },
                        headers=headers,
                    )
                    self.assertEqual(queued.status_code, 202)
                    self.assertEqual(socket.receive_json()["type"], "events.changed")
                    processed = client.post("/api/v1/events/process", json={"limit": 100}, headers=headers)
                    self.assertEqual(processed.status_code, 200)
                    self.assertEqual(socket.receive_json()["type"], "events.changed")
                    knowledge_notice = socket.receive_json()
                    self.assertEqual(knowledge_notice["type"], "knowledge.changed")
                    self.assertEqual(knowledge_notice["data"]["operation"], "event.process")
                after = client.post("/api/v1/queries", json=query_payload)
                self.assertTrue(after.json()["proven"])
                self.assertFalse(after.json()["cache_hit"])

    def test_context_filter_is_evidence_scoped_and_separates_query_cache(self):
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(app) as client:
                login = client.post("/api/v1/auth/login", json={"token": "operator-token"})
                headers = {"X-CSRF-Token": login.json()["csrf_token"]}
                client.post("/api/v1/entities", json={"entity_id": "alice", "properties": {}}, headers=headers)
                fact_ids = {}
                for role, domain in (("analyst", "hr"), ("admin", "security")):
                    response = client.post(
                        "/api/v1/facts",
                        json={
                            "subject": "alice", "predicate": "role", "object": role,
                            "object_type": "str", "context": {"domain": domain},
                        },
                        headers=headers,
                    )
                    self.assertEqual(response.status_code, 201)
                    self.assertEqual(response.json()["evidence_records"][0]["context"], {"domain": domain})
                    fact_ids[role] = response.json()["fact_id"]

                payload = {
                    "subject": "alice", "predicate": "role", "object": "?role",
                    "strategy": "forward", "context_filter": {"domain": "hr"},
                }
                hr = client.post("/api/v1/queries", json=payload)
                self.assertEqual(hr.status_code, 200)
                self.assertEqual([item["key"][2] for item in hr.json()["solutions"]], ["analyst"])
                self.assertEqual(hr.json()["context_fact_count"], 1)
                self.assertFalse(hr.json()["cache_hit"])

                security = client.post(
                    "/api/v1/queries", json={**payload, "context_filter": {"domain": "security"}}
                )
                self.assertEqual([item["key"][2] for item in security.json()["solutions"]], ["admin"])
                self.assertFalse(security.json()["cache_hit"])
                cached_hr = client.post("/api/v1/queries", json=payload)
                self.assertEqual([item["key"][2] for item in cached_hr.json()["solutions"]], ["analyst"])
                self.assertTrue(cached_hr.json()["cache_hit"])

                for strategy in ("backward", "hybrid", "adaptive"):
                    alternate = client.post(
                        "/api/v1/queries",
                        json={**payload, "object": "analyst", "object_type": "str", "strategy": strategy},
                    )
                    self.assertEqual(alternate.status_code, 200)
                    self.assertEqual([item["key"][2] for item in alternate.json()["solutions"]], ["analyst"])
                    self.assertEqual(alternate.json()["context_fact_count"], 1)

                patched = client.patch(
                    f"/api/v1/facts/{fact_ids['analyst']}",
                    json={"context": {"domain": "analytics"}},
                    headers=headers,
                )
                self.assertEqual(patched.status_code, 200, patched.text)
                self.assertEqual(
                    [item["context"] for item in patched.json()["evidence_records"]],
                    [{"domain": "analytics"}],
                )

                invalid = client.post(
                    "/api/v1/queries", json={**payload, "context_filter": {"domain": 7}}
                )
                self.assertEqual(invalid.status_code, 422)

    def test_context_filter_prevents_cross_context_rule_joins_and_applies_to_explanations(self):
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(app) as client:
                login = client.post("/api/v1/auth/login", json={"token": "operator-token"})
                headers = {"X-CSRF-Token": login.json()["csrf_token"]}
                for entity_id in ("alice", "team-1"):
                    client.post("/api/v1/entities", json={"entity_id": entity_id, "properties": {}}, headers=headers)
                for subject, predicate, obj, domain in (
                    ("alice", "member_of", "team-1", "hr"),
                    ("team-1", "classification", "restricted", "security"),
                ):
                    self.assertEqual(
                        client.post(
                            "/api/v1/facts",
                            json={"subject": subject, "predicate": predicate, "object": obj,
                                  "object_type": "str", "context": {"domain": domain}},
                            headers=headers,
                        ).status_code,
                        201,
                    )
                rule = client.post(
                    "/api/v1/rules",
                    json={
                        "rule_id": "membership-classification",
                        "antecedents": [
                            {"subject": "?person", "predicate": "member_of", "object": "?team"},
                            {"subject": "?team", "predicate": "classification", "object": "?label"},
                        ],
                        "consequent": {"subject": "?person", "predicate": "access_level", "object": "?label"},
                    },
                    headers=headers,
                )
                self.assertEqual(rule.status_code, 201)

                unscoped = client.post(
                    "/api/v1/queries",
                    json={"subject": "alice", "predicate": "access_level", "object": "restricted", "strategy": "forward"},
                )
                self.assertTrue(unscoped.json()["proven"])
                scoped_payload = {
                    "subject": "alice", "predicate": "access_level", "object": "restricted",
                    "strategy": "forward", "context_filter": {"domain": "hr"},
                }
                scoped = client.post("/api/v1/queries", json=scoped_payload)
                self.assertFalse(scoped.json()["proven"])
                self.assertEqual(scoped.json()["context_fact_count"], 1)
                explanation = client.post(
                    "/api/v1/explanations",
                    json={"subject": "alice", "predicate": "access_level", "object": "restricted",
                          "context_filter": {"domain": "hr"}},
                )
                self.assertEqual(explanation.status_code, 200)
                self.assertEqual(explanation.json()["proofs"], [])
                self.assertEqual(explanation.json()["context_fact_count"], 1)

    def test_context_filter_preserves_multistep_reasoning_without_cross_context_joins(self):
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(app) as client:
                login = client.post("/api/v1/auth/login", json={"token": "operator-token"})
                headers = {"X-CSRF-Token": login.json()["csrf_token"]}
                for entity_id in ("alice", "team-1", "project-1"):
                    client.post("/api/v1/entities", json={"entity_id": entity_id, "properties": {}}, headers=headers)
                for subject, predicate, obj, domain in (
                    ("alice", "member_of", "team-1", "hr"),
                    ("team-1", "owns_project", "project-1", "hr"),
                    ("project-1", "classification", "restricted", "hr"),
                ):
                    created = client.post(
                        "/api/v1/facts",
                        json={"subject": subject, "predicate": predicate, "object": obj,
                              "object_type": "str", "context": {"domain": domain},
                              "provenance": {"source": f"registry:{predicate}"}},
                        headers=headers,
                    )
                    self.assertEqual(created.status_code, 201, created.text)
                rules = (
                    {
                        "rule_id": "person-project",
                        "antecedents": [
                            {"subject": "?person", "predicate": "member_of", "object": "?team"},
                            {"subject": "?team", "predicate": "owns_project", "object": "?project"},
                        ],
                        "consequent": {"subject": "?person", "predicate": "member_project", "object": "?project"},
                    },
                    {
                        "rule_id": "project-access-level",
                        "antecedents": [
                            {"subject": "?person", "predicate": "member_project", "object": "?project"},
                            {"subject": "?project", "predicate": "classification", "object": "?level"},
                        ],
                        "consequent": {"subject": "?person", "predicate": "access_level", "object": "?level"},
                    },
                )
                for rule in rules:
                    self.assertEqual(client.post("/api/v1/rules", json=rule, headers=headers).status_code, 201)

                scoped = client.post(
                    "/api/v1/queries",
                    json={"subject": "alice", "predicate": "access_level", "object": "restricted",
                          "strategy": "forward", "context_filter": {"domain": "hr"}},
                )
                self.assertEqual(scoped.status_code, 200, scoped.text)
                self.assertTrue(scoped.json()["proven"])
                self.assertTrue(scoped.json()["complete"])
                self.assertGreaterEqual(len(scoped.json()["solutions"][0]["explanation"]), 1)

                isolated = client.post(
                    "/api/v1/queries",
                    json={"subject": "alice", "predicate": "access_level", "object": "restricted",
                          "strategy": "forward", "context_filter": {"domain": "finance"}},
                )
                self.assertEqual(isolated.status_code, 200)
                self.assertFalse(isolated.json()["proven"])

    def test_consistency_assessment_distinguishes_unknown_from_insufficient_evidence(self):
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(app) as client:
                login = client.post("/api/v1/auth/login", json={"token": "operator-token"})
                headers = {"X-CSRF-Token": login.json()["csrf_token"]}
                client.post("/api/v1/entities", json={"entity_id": "alice", "properties": {}}, headers=headers)
                created = client.post(
                    "/api/v1/facts",
                    json={"subject": "alice", "predicate": "membership", "object": "active",
                          "object_type": "str"},
                    headers=headers,
                )
                self.assertEqual(created.status_code, 201)

                insufficient = client.post(
                    "/api/v1/consistency/assessments",
                    json={"subject": "alice", "predicate": "membership", "object": "active", "object_type": "str"},
                )
                self.assertEqual(insufficient.status_code, 200, insufficient.text)
                self.assertEqual(insufficient.json()["status"], "insufficient_evidence")
                self.assertFalse(insufficient.json()["evidence_sufficient"])
                self.assertTrue(insufficient.json()["complete"])

                unknown = client.post(
                    "/api/v1/consistency/assessments",
                    json={"subject": "alice", "predicate": "citizenship", "object": "unknown", "object_type": "str"},
                )
                self.assertEqual(unknown.status_code, 200, unknown.text)
                self.assertEqual(unknown.json()["status"], "unknown")
                self.assertIn("absence is not falsity", unknown.json()["note"])

    def test_evidence_retraction_and_conflict_review_api_contract(self):
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(app) as client:
                login = client.post("/api/v1/auth/login", json={"token": "operator-token"})
                headers = {"X-CSRF-Token": login.json()["csrf_token"]}
                self.assertEqual(
                    client.post("/api/v1/entities", json={"entity_id": "alice", "properties": {}}, headers=headers).status_code,
                    201,
                )
                alive = client.post(
                    "/api/v1/facts",
                    json={"subject": "alice", "predicate": "alive", "object": True,
                          "object_type": "bool", "provenance": {"source": "witness-a"}},
                    headers=headers,
                )
                dead = client.post(
                    "/api/v1/facts",
                    json={"subject": "alice", "predicate": "dead", "object": True,
                          "object_type": "bool", "provenance": {"source": "witness-b"}},
                    headers=headers,
                )
                self.assertEqual(alive.status_code, 201)
                self.assertEqual(dead.status_code, 201)
                alive_id, dead_id = alive.json()["fact_id"], dead.json()["fact_id"]
                evidence_id = alive.json()["evidence_records"][0]["evidence_id"]
                self.assertRegex(evidence_id, r"^ev_[0-9a-f]{64}$")

                claim = {
                    "subject": "alice", "predicate": "alive", "object": True,
                    "object_type": "bool",
                    "incompatibilities": [{"predicate_a": "alive", "predicate_b": "dead"}],
                }
                assessment = client.post("/api/v1/consistency/assessments", json=claim)
                self.assertEqual(assessment.status_code, 200, assessment.text)
                self.assertEqual(assessment.json()["status"], "contradicted")
                self.assertTrue(assessment.json()["evidence_sufficient"])
                self.assertEqual(assessment.json()["explicit_fact_ids"], [alive_id])
                self.assertEqual(assessment.json()["conflicting_fact_ids"], [dead_id])

                review = client.post(
                    "/api/v1/consistency/resolutions",
                    json={**claim, "selected_fact_ids": [alive_id], "reason": "Reviewed source records."},
                    headers=headers,
                )
                self.assertEqual(review.status_code, 201, review.text)
                self.assertEqual(review.json()["assessment"]["status"], "contradicted")
                self.assertEqual(review.json()["assessment"]["resolution"]["selected_fact_ids"], [alive_id])
                self.assertEqual(review.json()["resolution"]["resolved_by"], "token-administrator")
                self.assertTrue(client.get("/api/v1/consistency/resolutions").json()["items"][0]["active"])

                # A new source changes the evidence fingerprint and invalidates the human review.
                added_source = client.post(
                    "/api/v1/facts",
                    json={"subject": "alice", "predicate": "alive", "object": True,
                          "object_type": "bool", "provenance": {"source": "witness-c"}},
                    headers=headers,
                )
                self.assertEqual(added_source.status_code, 201)
                self.assertEqual(added_source.json()["fact_id"], alive_id)
                self.assertEqual(len(added_source.json()["evidence_records"]), 2)
                self.assertFalse(client.get("/api/v1/consistency/resolutions").json()["items"][0]["active"])
                stale_review = client.post("/api/v1/consistency/assessments", json=claim)
                self.assertFalse(stale_review.json()["resolution"])

                missing_csrf = client.delete(f"/api/v1/facts/{alive_id}/evidence/{evidence_id}")
                self.assertEqual(missing_csrf.status_code, 403)
                reader_mutation = client.delete(
                    f"/api/v1/facts/{alive_id}/evidence/{evidence_id}", headers=headers
                )
                self.assertEqual(reader_mutation.status_code, 200)
                self.assertFalse(reader_mutation.json()["fact_deleted"])
                remaining_id = reader_mutation.json()["fact"]["evidence_records"][0]["evidence_id"]
                last_evidence = client.delete(
                    f"/api/v1/facts/{alive_id}/evidence/{remaining_id}", headers=headers
                )
                self.assertEqual(last_evidence.status_code, 200, last_evidence.text)
                self.assertTrue(last_evidence.json()["fact_deleted"])
                self.assertIsNone(last_evidence.json()["fact"])
                self.assertEqual(client.get(f"/api/v1/facts/{alive_id}").status_code, 404)
                self.assertEqual(
                    client.delete(f"/api/v1/facts/{alive_id}/evidence/not-an-id", headers=headers).status_code,
                    422,
                )
                self.assertEqual(
                    client.delete(f"/api/v1/facts/{alive_id}/evidence/{remaining_id}", headers=headers).status_code,
                    404,
                )
                history = client.get("/api/v1/history?offset=0&limit=100").json()["items"]
                self.assertTrue(any(item["operation"] == "fact_evidence_removed" for item in history))
                self.assertEqual(client.post("/api/v1/auth/logout", headers=headers).status_code, 200)
                self.assertEqual(client.get("/api/v1/consistency/resolutions").status_code, 401)
                self.assertEqual(client.post("/api/v1/consistency/assessments", json=claim).status_code, 401)

            restarted = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(restarted) as client:
                login = client.post("/api/v1/auth/login", json={"token": "operator-token"})
                self.assertEqual(login.status_code, 200)
                resolutions = client.get("/api/v1/consistency/resolutions")
                self.assertEqual(resolutions.status_code, 200)
                self.assertFalse(resolutions.json()["items"][0]["active"])


if __name__ == "__main__":
    unittest.main()
