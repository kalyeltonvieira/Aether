"""FastAPI dependencies used by all protected routes."""
from __future__ import annotations

import hmac
from fastapi import HTTPException, Request

from aether.interfaces.api.services.auth import AuthService, Session
from aether.interfaces.api.services.state import StudioState


def get_state(request: Request) -> StudioState:
    return request.app.state.studio


def get_auth(request: Request) -> AuthService:
    return request.app.state.auth


def _request_session(request: Request) -> Session | None:
    service: AuthService = request.app.state.auth
    session = getattr(request.state, "resolved_session", None)
    if session is not None:
        return service.get_session(session.session_id)
    return service.resolve_request_session(
        request.cookies.get(service.session_cookie),
        request.cookies.get("webdev_app_session"),
    )[0]


def require_session(
    request: Request,
) -> Session:
    session = _request_session(request)
    if session is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return session


def current_session(request: Request) -> Session | None:
    return _request_session(request)


def require_operator(request: Request) -> Session:
    session = require_session(request)
    if session.role != "operator":
        raise HTTPException(status_code=403, detail="operator role required")
    token = request.headers.get("X-CSRF-Token")
    if not token or not hmac.compare_digest(session.csrf_token, token):
        raise HTTPException(status_code=403, detail="valid X-CSRF-Token required")
    return session


def require_reader(request: Request) -> Session:
    return require_session(request)
