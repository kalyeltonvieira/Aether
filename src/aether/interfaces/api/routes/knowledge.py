from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from aether.interfaces.api.dependencies.auth import require_operator, require_session
from aether.interfaces.api.schemas.models import EntityCreate, EntityPatch, FactCreate, FactPatch, RuleCreate
from aether.interfaces.api.services.state import _change_dict, _entity_dict, _fact_dict, _rule_dict

router = APIRouter(tags=["knowledge"])


def _page(items, offset: int, limit: int):
    selected = list(items[offset:offset + limit])
    next_offset = offset + limit if offset + limit < len(items) else None
    return {"items": selected, "total": len(items), "offset": offset, "limit": limit, "next_offset": next_offset}


@router.get("/entities")
def list_entities(request: Request, search: str = "", offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    require_session(request)
    state = request.app.state.studio
    with state.lock:
        entities = [_entity_dict(item) for item in state.store.entities() if not search or search.lower() in item.entity_id.lower()]
    return _page(entities, offset, limit)


@router.post("/entities", status_code=201)
async def create_entity(request: Request, payload: EntityCreate):
    require_operator(request)
    state = request.app.state.studio
    entity = state.add_entity(payload.entity_id, payload.properties)
    result = _entity_dict(entity)
    await state.notify("knowledge.changed", {"operation": "entity.add", "entity": result})
    return result


@router.get("/entities/{entity_id}")
def get_entity(request: Request, entity_id: str):
    require_session(request)
    state = request.app.state.studio
    try:
        with state.lock:
            return _entity_dict(state.store.get_entity(entity_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"entity not found: {entity_id}") from exc


@router.patch("/entities/{entity_id}")
async def patch_entity(request: Request, entity_id: str, payload: EntityPatch):
    require_operator(request)
    state = request.app.state.studio
    try:
        result = _entity_dict(state.update_entity(entity_id, payload.properties))
        await state.notify("knowledge.changed", {"operation": "entity.update", "entity": result})
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"entity not found: {entity_id}") from exc


@router.get("/facts")
def list_facts(
    request: Request,
    subject: str | None = None,
    predicate: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
):
    require_session(request)
    state = request.app.state.studio
    subject = subject or None
    predicate = predicate or None
    with state.lock:
        facts = [_fact_dict(item) for item in state.store.query(subject=subject, predicate=predicate)]
    return _page(facts, offset, limit)


@router.post("/facts", status_code=201)
async def create_fact(request: Request, payload: FactCreate):
    require_operator(request)
    state = request.app.state.studio
    try:
        fact = state.add_fact(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = _fact_dict(fact)
    await state.notify("knowledge.changed", {"operation": "fact.add", "fact": result})
    return result


@router.get("/facts/{fact_id}")
def get_fact(request: Request, fact_id: int):
    require_session(request)
    state = request.app.state.studio
    try:
        with state.lock:
            return _fact_dict(state.store.get_fact(fact_id))
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=404, detail=f"fact not found: {fact_id}") from exc


@router.patch("/facts/{fact_id}")
async def patch_fact(request: Request, fact_id: int, payload: FactPatch):
    require_operator(request)
    state = request.app.state.studio
    try:
        result = state.replace_fact(fact_id, payload)
        await state.notify("knowledge.changed", {"operation": "fact.replace", "fact": result})
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"fact not found: {fact_id}") from exc


@router.delete("/facts/{fact_id}")
async def delete_fact(request: Request, fact_id: int):
    require_operator(request)
    state = request.app.state.studio
    try:
        fact = state.remove_fact(fact_id)
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=404, detail=f"fact not found: {fact_id}") from exc
    result = {"deleted": True, "fact": _fact_dict(fact)}
    await state.notify("knowledge.changed", {"operation": "fact.remove", "fact": result["fact"]})
    return result


@router.get("/history")
def history(request: Request, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    require_session(request)
    state = request.app.state.studio
    with state.lock:
        changes = [_change_dict(item) for item in state.store.history_changes(offset=offset, limit=limit)]
        stats = state.store.history_stats()
    return {"items": changes, "total": stats["retained_changes"], "offset": offset, "limit": limit, "next_offset": offset + len(changes) if offset + len(changes) < stats["retained_changes"] else None}


@router.get("/graph")
def graph(
    request: Request,
    predicate: str | None = None,
    center: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(250, ge=1, le=5000),
):
    require_session(request)
    state = request.app.state.studio
    predicate = predicate or None
    center = center or None
    with state.lock:
        entity_ids = {item.entity_id for item in state.store.entities()}
        facts = list(state.store.query(predicate=predicate))
        eligible = [item for item in facts if isinstance(item.object, str) and item.object in entity_ids]
        if center is not None:
            neighborhood = {center}
            for fact in eligible:
                if fact.subject == center:
                    neighborhood.add(fact.object)
                if fact.object == center:
                    neighborhood.add(fact.subject)
            eligible = [fact for fact in eligible if fact.subject in neighborhood and fact.object in neighborhood]
        eligible.sort(key=lambda item: item.fact_id)
        total = len(eligible)
        page = eligible[offset:offset + limit]
        next_offset = offset + len(page) if offset + len(page) < total else None
        truncated = next_offset is not None
        node_ids = {fact.subject for fact in page} | {fact.object for fact in page}
        if center is not None:
            node_ids.add(center)
        nodes = [{"id": item.entity_id, "label": item.entity_id, "properties": item.property_map()} for item in state.store.entities() if item.entity_id in node_ids]
        edges = [{"id": f"fact:{item.fact_id}", "source": item.subject, "target": item.object, "predicate": item.predicate, "fact_id": item.fact_id} for item in page]
    return {
        "nodes": nodes,
        "edges": edges,
        "truncated": truncated,
        "total": total,
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
    }


@router.get("/rules")
def list_rules(request: Request):
    require_session(request)
    state = request.app.state.studio
    with state.lock:
        return {"items": [_rule_dict(item) for item in state.rules]}


@router.post("/rules", status_code=201)
async def create_rule(request: Request, payload: RuleCreate):
    require_operator(request)
    state = request.app.state.studio
    result = _rule_dict(state.add_rule(payload))
    await state.notify("knowledge.changed", {"operation": "rule.add", "rule": result})
    return result


@router.delete("/rules/{rule_id}")
async def delete_rule(request: Request, rule_id: str):
    require_operator(request)
    state = request.app.state.studio
    try:
        result = {"deleted": True, "rule": _rule_dict(state.remove_rule(rule_id))}
        await state.notify("knowledge.changed", {"operation": "rule.remove", "rule_id": rule_id})
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"rule not found: {rule_id}") from exc
