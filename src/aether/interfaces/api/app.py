"""FastAPI application factory for AETHER Studio."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
import time
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aether.temporal.engine import BackpressureError
from aether.interfaces.api.routes import auth, knowledge, reasoning, system
from aether.interfaces.api.services.auth import AuthService
from aether.interfaces.api.services.state import StudioState
from aether.interfaces.api.websocket.manager import WebSocketManager


def _cookie_kwargs(auth_service: AuthService) -> dict[str, Any]:
    return {
        "key": auth_service.session_cookie,
        "httponly": True,
        "secure": auth_service.secure_cookie,
        "samesite": "none" if auth_service.secure_cookie else "strict",
        "max_age": auth_service.session_ttl_seconds,
        "path": "/",
    }


def create_app(
    data_dir: str | os.PathLike | None = None,
    *,
    auth_mode: str | None = None,
    public_origin: str | None = None,
    token: str | None = None,
    admin_token_file: str | os.PathLike | None = None,
    state: StudioState | None = None,
) -> FastAPI:
    studio = state or StudioState(data_dir)
    auth_service = AuthService(
        mode=auth_mode,
        public_origin=public_origin,
        admin_token=token,
        admin_token_file=admin_token_file,
        data_dir=studio.data_dir,
    )
    manager = WebSocketManager()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        studio.close()

    app = FastAPI(title="AETHER Studio API", version="v1", lifespan=lifespan)
    app.state.studio = studio
    app.state.auth = auth_service
    app.state.websocket_manager = manager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(auth_service.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    @app.middleware("http")
    async def preview_session_middleware(request: Request, call_next):
        session, created = auth_service.resolve_request_session(
            request.cookies.get(auth_service.session_cookie),
            request.cookies.get("webdev_app_session"),
        )
        if session is not None:
            request.state.resolved_session = session
        response = await call_next(request)
        if created and session is not None:
            response.set_cookie(**_cookie_kwargs(auth_service), value=session.session_id)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        def json_safe(value: Any) -> Any:
            if isinstance(value, BaseException):
                return str(value)
            if isinstance(value, dict):
                return {str(key): json_safe(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [json_safe(item) for item in value]
            return value

        return JSONResponse(status_code=422, content={"detail": json_safe(exc.errors())})

    @app.exception_handler(KeyError)
    async def key_error(request: Request, exc: KeyError):
        return JSONResponse(status_code=404, content={"detail": f"not found: {exc.args[0] if exc.args else 'resource'}"})

    @app.exception_handler(BackpressureError)
    async def backpressure_error(request: Request, exc: BackpressureError):
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(knowledge.router, prefix="/api/v1")
    app.include_router(reasoning.router, prefix="/api/v1")
    app.include_router(system.router, prefix="/api/v1")

    async def state_listener(message: dict[str, Any]):
        await manager.broadcast(message)

    studio.register_listener(state_listener)

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        origin = websocket.headers.get("origin")
        if not origin or origin not in auth_service.allowed_origins:
            await websocket.close(code=1008, reason="origin is not allowed")
            return
        session, _ = auth_service.resolve_request_session(
            websocket.cookies.get(auth_service.session_cookie),
            websocket.cookies.get("webdev_app_session"),
        )
        if session is None:
            await websocket.close(code=1008, reason="authentication required")
            return
        await websocket.accept()
        await manager.add(websocket)
        try:
            with studio.lock:
                snapshot = studio.status()
            await websocket.send_json({"type": "snapshot", "timestamp_ns": time.time_ns(), "data": snapshot})
            while True:
                try:
                    message = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
                except asyncio.TimeoutError:
                    # Do not keep an authorized socket alive after logout, session
                    # expiry, or Preview JWT expiry. The timeout also avoids an
                    # unbounded receive wait while the manager is broadcasting.
                    session, _ = auth_service.resolve_request_session(
                        websocket.cookies.get(auth_service.session_cookie),
                        websocket.cookies.get("webdev_app_session"),
                    )
                    if session is None:
                        await websocket.close(code=1008, reason="session is no longer authorized")
                        return
                    continue
                session, _ = auth_service.resolve_request_session(
                    websocket.cookies.get(auth_service.session_cookie),
                    websocket.cookies.get("webdev_app_session"),
                )
                if session is None:
                    await websocket.close(code=1008, reason="session is no longer authorized")
                    return
                if message == "ping":
                    with studio.lock:
                        metrics = studio.sample_metrics()
                    await websocket.send_json({"type": "metrics", "timestamp_ns": time.time_ns(), "data": metrics})
                else:
                    await websocket.send_json({"type": "error", "timestamp_ns": time.time_ns(), "data": {"detail": "WebSocket only accepts ping"}})
        except WebSocketDisconnect:
            pass
        finally:
            await manager.remove(websocket)

    return app
