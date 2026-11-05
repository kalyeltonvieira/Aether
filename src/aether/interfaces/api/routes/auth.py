from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from aether.interfaces.api.schemas.models import AuthLogin
from aether.interfaces.api.services.auth import AuthService
from aether.interfaces.api.dependencies.auth import require_session


router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie_kwargs(auth: AuthService) -> dict:
    return {
        "key": auth.session_cookie,
        "httponly": True,
        "secure": auth.secure_cookie,
        "samesite": "none" if auth.secure_cookie else "strict",
        "max_age": auth.session_ttl_seconds,
        "path": "/",
    }


@router.get("/info")
def auth_info(request: Request):
    return request.app.state.auth.info()


@router.get("/login-url")
def login_url(request: Request, response: Response):
    auth: AuthService = request.app.state.auth
    try:
        url, state = auth.login_url()
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response.set_cookie(
        key=auth.oauth_state_cookie,
        value=state,
        httponly=True,
        secure=auth.secure_cookie,
        samesite="none" if auth.secure_cookie else "strict",
        max_age=auth.oauth_ttl_seconds,
        path="/api/v1/auth",
    )
    return {"url": url}


@router.get("/callback")
async def oauth_callback(
    request: Request,
    response: Response,
    code: str = Query(min_length=1),
    state: str = Query(min_length=1),
):
    auth: AuthService = request.app.state.auth
    try:
        session = await auth.callback(code, state, request.cookies.get(auth.oauth_state_cookie))
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    redirect = RedirectResponse(url="/", status_code=303)
    redirect.set_cookie(**_cookie_kwargs(auth), value=session.session_id)
    redirect.delete_cookie(auth.oauth_state_cookie, path="/api/v1/auth")
    return redirect


@router.post("/login")
def login(request: Request, response: Response, payload: AuthLogin):
    auth: AuthService = request.app.state.auth
    if auth.mode != "token":
        raise HTTPException(status_code=400, detail="token login is disabled; use Manus OAuth")
    address = request.client.host if request.client else "unknown"
    try:
        session = auth.login_token(payload.token, address=address)
    except PermissionError as exc:
        message = str(exc)
        code = 429 if "too many" in message else 401
        raise HTTPException(status_code=code, detail=message) from exc
    response.set_cookie(**_cookie_kwargs(auth), value=session.session_id)
    return auth.session_payload(session)


@router.get("/session")
def session_info(request: Request):
    session = require_session(request)
    return request.app.state.auth.session_payload(session)


@router.post("/logout")
def logout(request: Request, response: Response):
    auth: AuthService = request.app.state.auth
    session = require_session(request)
    if not auth.verify_csrf(session, request.headers.get("X-CSRF-Token")):
        raise HTTPException(status_code=403, detail="valid X-CSRF-Token required")
    auth.revoke(session.session_id)
    response.delete_cookie(auth.session_cookie, path="/")
    return {"authenticated": False}
