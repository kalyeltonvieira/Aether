"""Authentication and authorization for the Studio API.

Managed deployments use Manus OAuth/Preview identity by default. Independent
installations may opt into token exchange explicitly with ``auth_mode=token``.
No bearer token is ever returned as a frontend session credential.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hmac
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt


@dataclass
class Session:
    session_id: str
    open_id: str | None
    role: str
    csrf_token: str
    created_at: float
    expires_at: float
    auth_source: str = "oauth"


class AuthService:
    managed_session_cookie = "webdev_app_session"
    token_session_cookie = "aether_studio_session"
    oauth_state_cookie = "aether_oauth_state"
    session_ttl_seconds = 8 * 60 * 60
    oauth_ttl_seconds = 10 * 60

    def __init__(
        self,
        *,
        mode: str | None = None,
        public_origin: str | None = None,
        admin_token: str | None = None,
        admin_token_file: str | os.PathLike | None = None,
        data_dir: str | os.PathLike | None = None,
    ):
        self.mode = mode or os.environ.get("AETHER_AUTH_MODE", "manus").strip().lower()
        if self.mode not in {"manus", "token"}:
            raise ValueError("auth mode must be manus or token")
        self.session_cookie = self.managed_session_cookie if self.mode == "manus" else self.token_session_cookie
        self.public_origin = (public_origin or os.environ.get("AETHER_PUBLIC_ORIGIN") or "").rstrip("/") or None
        self.secure_cookie = bool(self.public_origin and self.public_origin.startswith("https://"))
        self.allowed_origins = self._allowed_origins()
        self.operator_open_ids = {
            value.strip()
            for value in os.environ.get("AETHER_OPERATOR_OPEN_IDS", "").split(",")
            if value.strip()
        }
        self.sessions: dict[str, Session] = {}
        self.oauth_states: dict[str, dict[str, Any]] = {}
        self.login_attempts: dict[str, list[float]] = {}
        default_token_file = Path(data_dir or ".aether-data").expanduser() / "operator-token"
        self.admin_token_file = Path(admin_token_file or os.environ.get("AETHER_ADMIN_TOKEN_FILE", default_token_file)).expanduser()
        self.admin_token = admin_token or os.environ.get("AETHER_OPERATOR_TOKEN")
        if self.mode == "token" and not self.admin_token:
            self.admin_token = self._load_or_create_local_token()

    def _allowed_origins(self) -> set[str]:
        values = {
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        }
        raw = os.environ.get("AETHER_ALLOWED_ORIGINS", "")
        values.update(value.strip().rstrip("/") for value in raw.split(",") if value.strip())
        if self.public_origin:
            values.add(self.public_origin)
        return values

    def _load_or_create_local_token(self) -> str | None:
        try:
            if self.admin_token_file.exists():
                value = self.admin_token_file.read_text(encoding="utf-8").strip()
                if value:
                    return value
            self.admin_token_file.parent.mkdir(parents=True, exist_ok=True)
            token = secrets.token_urlsafe(32)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            descriptor = os.open(self.admin_token_file, flags, 0o600)
            try:
                os.write(descriptor, token.encode("utf-8"))
            finally:
                os.close(descriptor)
            try:
                os.chmod(self.admin_token_file, 0o600)
            except OSError:
                pass
            return token
        except OSError:
            return None

    def info(self) -> dict[str, Any]:
        available = self.mode == "token" and bool(self.admin_token)
        if self.mode == "manus":
            available = bool(
                os.environ.get("MANUS_OAUTH_PORTAL_URL")
                and os.environ.get("MANUS_OAUTH_API_URL")
                and os.environ.get("MANUS_PROJECT_ID")
            )
        return {"mode": self.mode, "login_available": available}

    def _cleanup(self) -> None:
        now = time.time()
        self.sessions = {key: value for key, value in self.sessions.items() if value.expires_at > now}
        self.oauth_states = {key: value for key, value in self.oauth_states.items() if value["expires_at"] > now and not value.get("used")}
        self.login_attempts = {key: values[-20:] for key, values in self.login_attempts.items() if values and values[-1] > now - 300}

    def _rate_limit(self, address: str) -> None:
        self._cleanup()
        now = time.time()
        attempts = [stamp for stamp in self.login_attempts.get(address, []) if stamp > now - 60]
        if len(attempts) >= 10:
            raise PermissionError("too many login attempts; retry later")
        attempts.append(now)
        self.login_attempts[address] = attempts

    def _role_for(self, open_id: str | None, *, token_login: bool = False) -> str:
        if token_login:
            return "operator"
        if open_id and open_id in self.operator_open_ids:
            return "operator"
        return "reader"

    def create_session(
        self,
        *,
        open_id: str | None,
        token_login: bool = False,
        auth_source: str | None = None,
        expires_at: float | None = None,
    ) -> Session:
        self._cleanup()
        now = time.time()
        source = auth_source or ("token" if token_login else "oauth")
        session = Session(
            secrets.token_urlsafe(32),
            open_id,
            self._role_for(open_id, token_login=token_login),
            secrets.token_urlsafe(32),
            now,
            min(now + self.session_ttl_seconds, expires_at) if expires_at is not None else now + self.session_ttl_seconds,
            source,
        )
        self.sessions[session.session_id] = session
        return session

    def get_session(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        self._cleanup()
        session = self.sessions.get(session_id)
        if session is None or session.expires_at <= time.time():
            if session is not None:
                self.sessions.pop(session_id, None)
            return None
        return session

    def resolve_request_session(
        self,
        session_id: str | None,
        preview_token: str | None = None,
    ) -> tuple[Session | None, bool]:
        """Resolve a request session, optionally binding it to Preview JWT identity.

        The returned boolean is true only when a new cookie session was created.
        A Preview session is never authorized from an unverified or expired JWT;
        its expiry is bounded by the JWT expiry and maximum session TTL. JWTs are
        not introspected again, so later revocation cannot be detected.
        """
        # In managed mode the same cookie name is used for both the platform's
        # injected JWT and our short-lived opaque session. Recognize an issued
        # opaque session first; only an unknown value is treated as a JWT.
        session = self.get_session(session_id)
        if session is not None:
            return session, False
        if self.mode != "manus" or not preview_token:
            return None, False
        verified = self._preview_claims(preview_token)
        if verified is None:
            return None, False
        identity, token_expiry = verified
        return self.create_session(open_id=identity, auth_source="preview", expires_at=token_expiry), True

    def revoke(self, session_id: str | None) -> None:
        if session_id:
            self.sessions.pop(session_id, None)

    def session_payload(self, session: Session) -> dict[str, Any]:
        return {"authenticated": True, "role": session.role, "csrf_token": session.csrf_token, "auth_mode": self.mode, "open_id": session.open_id}

    def verify_csrf(self, session: Session, token: str | None) -> bool:
        return bool(token) and hmac.compare_digest(session.csrf_token, token)

    def login_token(self, token: str, *, address: str) -> Session:
        if self.mode != "token":
            raise PermissionError("token login is disabled in managed Manus mode")
        self._rate_limit(address)
        if not self.admin_token or not hmac.compare_digest(token, self.admin_token):
            raise PermissionError("invalid administrator token")
        return self.create_session(open_id="token-administrator", token_login=True, auth_source="token")

    def login_url(self) -> tuple[str, str]:
        if self.mode != "manus":
            raise PermissionError("OAuth login URL is disabled in token mode")
        portal_url = os.environ.get("MANUS_OAUTH_PORTAL_URL")
        api_url = os.environ.get("MANUS_OAUTH_API_URL")
        project_id = os.environ.get("MANUS_PROJECT_ID")
        if not portal_url or not api_url or not project_id:
            raise RuntimeError("Manus OAuth portal, API and project ID are required")
        redirect_uri = os.environ.get("MANUS_OAUTH_REDIRECT_URI") or (
            f"{self.public_origin}/api/v1/auth/callback" if self.public_origin else None
        )
        if not redirect_uri:
            raise RuntimeError("public origin or explicit Manus OAuth redirect URI is required")
        nonce = secrets.token_urlsafe(32)
        state_data = {"redirectUri": redirect_uri, "nonce": nonce}
        state_json = json.dumps(state_data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        state = base64.b64encode(state_json).decode("ascii")
        self._cleanup()
        self.oauth_states[state] = {
            "nonce": nonce,
            "redirect_uri": redirect_uri,
            "created_at": time.time(),
            "expires_at": time.time() + self.oauth_ttl_seconds,
            "used": False,
        }
        params = {
            "appId": project_id,
            "redirectUri": redirect_uri,
            "state": state,
            "responseType": "code",
        }
        authorize_url = portal_url.rstrip("/") + "/app-auth"
        separator = "&" if "?" in authorize_url else "?"
        return authorize_url + separator + urlencode(params), state

    async def callback(self, code: str, state: str, state_cookie: str | None) -> Session:
        if self.mode != "manus":
            raise PermissionError("OAuth callback is disabled in token mode")
        if state_cookie and len(state_cookie) >= 2 and state_cookie[0] == state_cookie[-1] == '"':
            state_cookie = state_cookie[1:-1]
        if not state_cookie or not hmac.compare_digest(state, state_cookie):
            raise PermissionError("OAuth state cookie mismatch")
        record = self.oauth_states.get(state)
        if not record or record.get("used") or record["expires_at"] <= time.time():
            raise PermissionError("OAuth state is invalid or expired")
        try:
            state_data = json.loads(base64.b64decode(state, validate=True))
        except (ValueError, TypeError, json.JSONDecodeError):
            raise PermissionError("OAuth state is invalid") from None
        if (
            not isinstance(state_data, dict)
            or state_data.get("nonce") != record["nonce"]
            or state_data.get("redirectUri") != record["redirect_uri"]
        ):
            raise PermissionError("OAuth state binding is invalid")
        # Reserve synchronously before the first await. Provider errors leave it
        # consumed; starting a fresh OAuth flow is safer than permitting replay.
        record["used"] = True
        api_url = os.environ.get("MANUS_OAUTH_API_URL")
        project_id = os.environ.get("MANUS_PROJECT_ID")
        redirect_uri = record["redirect_uri"]
        if not api_url or not project_id:
            raise RuntimeError("Manus OAuth API URL and project ID are required")
        token_url = api_url.rstrip("/") + "/webdev.v1.WebDevAuthPublicService/ExchangeToken"
        userinfo_url = api_url.rstrip("/") + "/webdev.v1.WebDevAuthPublicService/GetUserInfo"
        data = {
            "clientId": project_id,
            "grantType": "authorization_code",
            "code": code,
            "redirectUri": redirect_uri,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(token_url, json=data)
                response.raise_for_status()
                token_payload = response.json()
                access_token = token_payload.get("accessToken")
                if not isinstance(access_token, str) or not access_token:
                    raise RuntimeError("Manus OAuth exchange did not return accessToken")
                user_response = await client.post(userinfo_url, json={"accessToken": access_token})
                user_response.raise_for_status()
                identity = user_response.json()
            except httpx.HTTPError:
                raise RuntimeError("Manus OAuth provider request failed") from None
        if not isinstance(identity, dict):
            raise RuntimeError("Manus OAuth identity response was invalid")
        open_id = identity.get("openId")
        if not isinstance(open_id, str) or not open_id:
            raise RuntimeError("Manus OAuth identity response did not contain openId")
        return self.create_session(open_id=open_id, auth_source="oauth")

    def preview_identity(self, token: str | None) -> str | None:
        verified = self._preview_claims(token)
        return verified[0] if verified is not None else None

    def _preview_claims(self, token: str | None) -> tuple[str, float] | None:
        if self.mode != "manus" or not token:
            return None
        secret = os.environ.get("MANUS_JWT_SECRET")
        project_id = os.environ.get("MANUS_PROJECT_ID") or os.environ.get("MANUS_APP_ID")
        if not secret or not project_id:
            return None
        try:
            payload = jwt.decode(token, secret, algorithms=["HS256"], options={"require": ["exp"]})
        except Exception:
            return None
        token_project = payload.get("appId") or payload.get("app_id") or payload.get("projectId") or payload.get("project_id")
        if token_project is None or str(token_project) != str(project_id):
            return None
        open_id = payload.get("openId") or payload.get("open_id") or payload.get("sub")
        if not isinstance(open_id, str) or not open_id:
            return None
        try:
            expiry = float(payload["exp"])
        except (KeyError, TypeError, ValueError):
            return None
        return open_id, expiry
