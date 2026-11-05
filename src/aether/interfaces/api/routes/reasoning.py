from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from aether.interfaces.api.dependencies.auth import require_operator, require_session
from aether.interfaces.api.schemas.models import ExplanationCreate, QueryCreate

router = APIRouter(tags=["reasoning"])


@router.post("/queries")
def query(request: Request, payload: QueryCreate):
    require_session(request)
    state = request.app.state.studio
    try:
        return state.query(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/inference")
def inference(request: Request):
    require_operator(request)
    return request.app.state.studio.recompute()


@router.post("/explanations")
def explanation(request: Request, payload: ExplanationCreate):
    require_session(request)
    return request.app.state.studio.explain(payload)
