from __future__ import annotations

import importlib
from typing import Any, Mapping


def _load_backend() -> Any | None:
    try:
        return importlib.import_module("metaspn_schemas")
    except ImportError:
        return None


def schemas_available() -> bool:
    return _load_backend() is not None


def _to_dict(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        out = to_dict()
        if isinstance(out, Mapping):
            return out
    raise TypeError("schema object is not serializable to mapping")


def build_task_and_emission(
    *,
    task_id: str,
    created_at,
    caused_by: str,
    entity_id: str,
    gate_id: str,
    emission_id: str,
    priority: int = 50,
) -> dict[str, Any] | None:
    backend = _load_backend()
    if backend is None:
        return None

    entity_ref = backend.EntityRef(ref_type="entity_id", value=entity_id)
    task = backend.Task(
        task_id=task_id,
        task_type=task_id,
        created_at=created_at,
        priority=priority,
        entity_ref=entity_ref,
        context={"gate_id": gate_id, "caused_by": caused_by},
    )
    envelope = backend.EmissionEnvelope(
        emission_id=emission_id,
        timestamp=created_at,
        emission_type="task_enqueued",
        payload=task,
        caused_by=caused_by,
        entity_refs=(entity_ref,),
    )

    return {
        "task": dict(_to_dict(task)),
        "emission_envelope": dict(_to_dict(envelope)),
    }
