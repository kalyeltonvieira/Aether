from __future__ import annotations

import argparse
import logging
import os
import socket

import uvicorn

from aether.interfaces.api.app import create_app


def _is_loopback(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"}


def _seed_fixture(application) -> None:
    state = application.state.studio
    with state.lock:
        if state.store.entities() or state.store.query():
            return
    state.add_entity("alice", {"name": "Alice"})
    state.add_entity("bob", {"name": "Bob"})
    state.add_fact({"subject": "alice", "predicate": "sent_email_to", "object": "bob", "properties": {}, "confidence": 1.0, "provenance": {"source": "aether-fixture", "evidence_type": "fixture"}})
    state.add_rule({"rule_id": "email-implies-contact", "antecedents": [{"subject": "?x", "predicate": "sent_email_to", "object": "?y"}], "consequent": {"subject": "?x", "predicate": "contacted", "object": "?y"}, "enabled": True})
    state.recompute()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AETHER Studio FastAPI backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", default=".aether-data")
    parser.add_argument("--auth-mode", choices=("token", "manus"), default=None)
    parser.add_argument("--public-origin", default=None)
    parser.add_argument("--seed-fixture", action="store_true", help="seed test-only data only when the store is empty")
    args = parser.parse_args()
    mode = args.auth_mode or os.environ.get("AETHER_AUTH_MODE", "manus")
    if mode == "token" and not _is_loopback(args.host):
        if not os.environ.get("AETHER_OPERATOR_TOKEN"):
            raise SystemExit("refusing network token mode without AETHER_OPERATOR_TOKEN")
    application = create_app(data_dir=args.data_dir, auth_mode=mode, public_origin=args.public_origin)
    if args.seed_fixture:
        _seed_fixture(application)
    if mode == "token" and not os.environ.get("AETHER_OPERATOR_TOKEN"):
        token_path = application.state.auth.admin_token_file
        logging.getLogger("aether.api").warning("generated administrator token stored in private file %s; token value is not printed", token_path)
    uvicorn.run(application, host=args.host, port=args.port, workers=1, reload=False)


if __name__ == "__main__":
    main()
