from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from aether.interfaces.api.dependencies.auth import require_operator, require_session
from aether.interfaces.api.schemas.models import (
    ConsistencyAssessmentCreate,
    ConflictResolutionCreate,
)
from aether.interfaces.api.services.state import _fact_dict, _proof_dict

router = APIRouter(tags=["consistency"])
_EVIDENCE_ID = re.compile(r"^ev_[0-9a-f]{64}$")


def _resolution_dict(resolution) -> dict[str, Any]:
    return {
        "fact_ids": list(resolution.fact_ids),
        "selected_fact_ids": list(resolution.selected_fact_ids),
        "reason": resolution.reason,
        "resolved_by": resolution.resolved_by,
        "evidence_fingerprint": resolution.evidence_fingerprint,
        "recorded_at_ns": resolution.recorded_at_ns,
        "invalidated_at_ns": resolution.invalidated_at_ns,
        "active": resolution.invalidated_at_ns is None,
    }


def _assessment_dict(assessment) -> dict[str, Any]:
    return {
        "claim": list(assessment.claim),
        "status": assessment.status.value,
        "explicit_fact_ids": list(assessment.explicit_fact_ids),
        "derived_proofs": [_proof_dict(proof) for proof in assessment.derived_proofs],
        "conflicting_fact_ids": list(assessment.conflicting_fact_ids),
        "evidence_sufficient": assessment.evidence_sufficient,
        "complete": assessment.complete,
        "resolution": None if assessment.resolution is None else _resolution_dict(assessment.resolution),
        "note": assessment.note,
    }


@router.post("/consistency/assessments")
def assess_consistency(request: Request, payload: ConsistencyAssessmentCreate):
    require_session(request)
    state = request.app.state.studio
    return _assessment_dict(state.assess_consistency(payload))


@router.get("/consistency/resolutions")
def list_resolutions(request: Request):
    require_session(request)
    state = request.app.state.studio
    with state.lock:
        items = [_resolution_dict(item) for item in state.store.conflict_resolutions]
    return {"items": items}


@router.post("/consistency/resolutions", status_code=201)
async def record_resolution(request: Request, payload: ConflictResolutionCreate):
    operator = require_operator(request)
    state = request.app.state.studio
    resolved_by = operator.open_id or f"{operator.auth_source}:operator"
    resolution = state.record_conflict_resolution(payload, resolved_by=resolved_by)
    assessment = state.assess_consistency(payload)
    result = {"resolution": _resolution_dict(resolution), "assessment": _assessment_dict(assessment)}
    await state.notify(
        "consistency.changed",
        {"operation": "conflict_resolution.recorded", "resolution": result["resolution"]},
    )
    return result


@router.delete("/facts/{fact_id}/evidence/{evidence_id}")
async def remove_evidence(request: Request, fact_id: int, evidence_id: str):
    require_operator(request)
    if not _EVIDENCE_ID.fullmatch(evidence_id):
        raise HTTPException(status_code=422, detail="invalid evidence_id")
    state = request.app.state.studio
    try:
        result = state.remove_evidence(fact_id, evidence_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="fact or evidence not found") from exc
    fact_after = result.removal.fact_after
    response = {
        "removed": True,
        "fact_id": fact_id,
        "evidence_id": evidence_id,
        "fact_deleted": fact_after is None,
        "fact": None if fact_after is None else _fact_dict(fact_after),
        "inference_complete": result.inference_complete,
        "invalidation": None if result.invalidation is None else {
            "requested_supports": result.invalidation.requested_supports,
            "conclusions_invalidated": result.invalidation.conclusions_invalidated,
            "remaining_conclusions": result.invalidation.remaining_conclusions,
            "proofs_invalidated": result.invalidation.proofs_invalidated,
            "conclusions_preserved_by_alternative": result.invalidation.conclusions_preserved_by_alternative,
        },
    }
    await state.notify("knowledge.changed", {"operation": "fact.evidence.remove", **response})
    return response
