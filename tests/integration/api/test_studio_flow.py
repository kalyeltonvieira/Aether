import tempfile
import unittest

try:
    from fastapi.testclient import TestClient
    from aether.interfaces.api.app import create_app
except ImportError:
    TestClient = None
    create_app = None


@unittest.skipIf(TestClient is None, "API dependencies are not installed")
class StudioFlowTests(unittest.TestCase):
    def test_real_flow_restart_and_websocket(self):
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(app) as client:
                login = client.post("/api/v1/auth/login", json={"token": "operator-token"})
                csrf = login.json()["csrf_token"]
                headers = {"X-CSRF-Token": csrf}
                for entity_id in ("alice", "bob", "carol"):
                    self.assertEqual(client.post("/api/v1/entities", json={"entity_id": entity_id, "properties": {}}, headers=headers).status_code, 201)
                first = client.post("/api/v1/facts", json={"subject": "alice", "predicate": "sent_email_to", "object": "bob", "provenance": {"source": "mail-a"}}, headers=headers).json()
                second = client.post("/api/v1/facts", json={"subject": "alice", "predicate": "works_with", "object": "bob", "provenance": {"source": "hr"}}, headers=headers).json()
                self.assertNotEqual(first["fact_id"], second["fact_id"])
                for rule_id, predicate in (("email-contact", "sent_email_to"), ("work-contact", "works_with")):
                    response = client.post("/api/v1/rules", json={"rule_id": rule_id, "antecedents": [{"subject": "?x", "predicate": predicate, "object": "?y"}], "consequent": {"subject": "?x", "predicate": "contacted", "object": "?y"}}, headers=headers)
                    self.assertEqual(response.status_code, 201)
                query_payload = {"subject": "?x", "predicate": "contacted", "object": "?y", "strategy": "forward", "limit": 100}
                query = client.post("/api/v1/queries", json=query_payload)
                self.assertEqual(query.status_code, 200)
                self.assertTrue(query.json()["proven"])
                self.assertEqual(len(query.json()["solutions"]), 1)
                self.assertEqual(len(query.json()["solutions"][0]["proofs"]), 2)
                cached = client.post("/api/v1/queries", json=query_payload).json()
                self.assertTrue(cached["cache_hit"])
                explanation = client.post("/api/v1/explanations", json={"subject": "alice", "predicate": "contacted", "object": "bob"})
                self.assertEqual(explanation.status_code, 200)
                self.assertEqual(len(explanation.json()["explanation"][0]["proofs"]), 2)
                removed = client.delete(f"/api/v1/facts/{first['fact_id']}", headers=headers)
                self.assertEqual(removed.status_code, 200)
                after = client.post("/api/v1/queries", json={"subject": "alice", "predicate": "contacted", "object": "bob", "strategy": "forward"})
                self.assertTrue(after.json()["proven"])
                self.assertEqual(len(after.json()["solutions"][0]["proofs"]), 1)
                self.assertGreater(client.get("/api/v1/history").json()["total"], 0)
                event = client.post("/api/v1/events", json={"event_type": "fact.add", "source": "studio", "payload": {"subject": "bob", "predicate": "sent_email_to", "object": "carol"}}, headers=headers)
                self.assertEqual(event.status_code, 202)
                batch = client.post("/api/v1/events/process", json={"limit": 100}, headers=headers)
                self.assertEqual(batch.status_code, 200)
                self.assertEqual(batch.json()["processed"], 1)
                self.assertEqual(client.get("/api/v1/memory").json()["hits"] >= 1, True)
                with client.websocket_connect("/ws", headers={"origin": "http://localhost:3000"}) as socket:
                    snapshot = socket.receive_json()
                    self.assertEqual(snapshot["type"], "snapshot")
                    socket.send_text("ping")
                    self.assertEqual(socket.receive_json()["type"], "metrics")
            app2 = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(app2) as restarted:
                restarted.post("/api/v1/auth/login", json={"token": "operator-token"})
                self.assertEqual(restarted.get("/api/v1/entities").json()["total"], 3)
                self.assertGreaterEqual(restarted.get("/api/v1/facts").json()["total"], 2)

    def test_open_backward_is_rejected_and_ws_origin_is_required(self):
        with tempfile.TemporaryDirectory() as data_dir:
            app = create_app(data_dir=data_dir, auth_mode="token", token="operator-token")
            with TestClient(app) as client:
                client.post("/api/v1/auth/login", json={"token": "operator-token"})
                response = client.post("/api/v1/queries", json={"subject": "?x", "predicate": "p", "object": "?y", "strategy": "backward"})
                self.assertEqual(response.status_code, 422)
                with self.assertRaises(Exception):
                    with client.websocket_connect("/ws") as socket:
                        socket.receive_json()
