from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, Request

from aether.interfaces.api.dependencies.auth import require_operator, require_session
from aether.interfaces.api.schemas.models import ConfigUpdate, EventCreate, EventProcess, MemoryBudgetUpdate
from aether.interfaces.api.services.state import _event_dict

router = APIRouter(tags=["system"])


@router.get("/status")
def status(request: Request):
    require_session(request)
    state = request.app.state.studio
    with state.lock:
        return state.status()


@router.get("/memory")
def memory(request: Request):
    require_session(request)
    state = request.app.state.studio
    with state.lock:
        return state.memory_stats()


@router.put("/memory/budget")
def memory_budget(request: Request, payload: MemoryBudgetUpdate):
    require_operator(request)
    state = request.app.state.studio
    try:
        config = state.configure({"memory_max_bytes": payload.max_bytes})
    except (ValueError, MemoryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return state.memory_stats()


@router.get("/metrics")
def metrics(request: Request, period: int = Query(60, ge=1, le=86400)):
    require_session(request)
    state = request.app.state.studio
    with state.lock:
        state.sample_metrics()
        return state.metrics(period)


@router.get("/config")
def config(request: Request):
    require_session(request)
    state = request.app.state.studio
    with state.lock:
        return dict(state.config)


@router.put("/config")
def update_config(request: Request, payload: ConfigUpdate):
    require_operator(request)
    state = request.app.state.studio
    try:
        return state.configure(payload.model_dump(exclude_none=True))
    except (ValueError, MemoryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/events")
def events(
    request: Request,
    event_type: str | None = None,
    status: str | None = None,
    after: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=10000),
):
    require_session(request)
    state = request.app.state.studio
    event_type = event_type or None
    status = status or None
    try:
        with state.lock:
            page = state.events.events(after_sequence=after, limit=limit, event_type=event_type, status=status)
            queue = state.events.queue_stats()
        return {"items": [_event_dict(item) for item in page.events], "next_after": page.next_after, "complete": page.complete, "queue": queue}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/events", status_code=202)
async def enqueue_event(request: Request, payload: EventCreate):
    require_operator(request)
    state = request.app.state.studio
    try:
        with state.lock:
            receipt = state.events.enqueue(payload.event_type, payload.payload, source=payload.source, event_id=payload.event_id, provenance=payload.provenance)
            state.record_activity("event.enqueue", event_id=receipt.event.event_id, inserted=receipt.inserted)
        await state.notify("events.changed", {"event": _event_dict(receipt.event), "inserted": receipt.inserted})
        return {"event": _event_dict(receipt.event), "inserted": receipt.inserted}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/events/process")
async def process_events(request: Request, payload: EventProcess):
    require_operator(request)
    state = request.app.state.studio
    with state.lock:
        before_version = state.store.version
        limit = payload.limit if payload.limit is not None else state.config["event_batch_size"]
        batch = state.events.process_batch(state.processor, limit=limit)
        state.events_processed += batch.processed
        knowledge_changed = state.store.version != before_version
        if knowledge_changed:
            # Event handlers mutate the same reasoner/store as REST mutations.
            # Cached query explanations must not survive an event-driven write.
            state.query_cache.clear()
            knowledge_payload = {
                "operation": "event.process",
                "processed": batch.processed,
                "store_version": state.store.version,
                "facts": state.store.stats()["facts"],
                "entities": state.store.stats()["entities"],
            }
        else:
            knowledge_payload = None
        state.sample_metrics()
        state.record_activity("event.process", processed=batch.processed, failed=batch.failed)
        result = {
            "attempted": batch.attempted,
            "processed": batch.processed,
            "retried": batch.retried,
            "failed": batch.failed,
            "lost_claims": batch.lost_claims,
            "failures": [asdict(item) for item in batch.failures],
            "queue_depth": batch.queue_depth,
        }
    await state.notify("events.changed", result)
    if knowledge_changed:
        await state.notify("knowledge.changed", knowledge_payload)
    return result


@router.post("/events/{event_id}/retry")
async def retry_event(request: Request, event_id: str):
    require_operator(request)
    state = request.app.state.studio
    with state.lock:
        changed = state.events.requeue(event_id)
        if not changed:
            raise HTTPException(status_code=404, detail=f"failed event not found: {event_id}")
        state.record_activity("event.retry", event_id=event_id)
    await state.notify("events.changed", {"event_id": event_id, "requeued": True})
    return {"event_id": event_id, "requeued": True}
