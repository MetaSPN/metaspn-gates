from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Iterable, Mapping

from .models import GateDecision, TransitionApplied
from .schemas import build_task_and_emission, schemas_available


def apply_decisions(
    entity_state: Mapping[str, Any],
    decisions: Iterable[GateDecision],
    caused_by: str | None = None,
    use_schema_envelopes: bool = False,
    default_task_priority: int = 50,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    new_state: dict[str, Any] = deepcopy(dict(entity_state))
    emissions: list[dict[str, Any]] = []

    attempts = new_state.setdefault("gate_attempts", [])
    applied = new_state.setdefault("transitions_applied", [])
    cooldowns = new_state.setdefault("gate_cooldowns", {})

    if not isinstance(attempts, list):
        raise ValueError("entity_state.gate_attempts must be a list when present")
    if not isinstance(applied, list):
        raise ValueError("entity_state.transitions_applied must be a list when present")
    if not isinstance(cooldowns, dict):
        raise ValueError("entity_state.gate_cooldowns must be an object when present")

    for decision in decisions:
        attempted = decision.transition_attempted
        attempts.append(
            {
                "gate_id": attempted.gate_id,
                "from": attempted.from_state,
                "to": attempted.to_state,
                "passed": attempted.passed,
                "reason": attempted.reason,
                "failed_requirement_id": attempted.failed_requirement_id,
                "timestamp": attempted.timestamp.isoformat(),
                "snapshot": deepcopy(dict(attempted.snapshot)),
            }
        )

        if decision.passed:
            new_state["state"] = decision.to_state

            record = TransitionApplied(
                gate_id=decision.gate_id,
                from_state=decision.from_state,
                to_state=decision.to_state,
                caused_by=caused_by,
                timestamp=attempted.timestamp,
                snapshot=deepcopy(dict(attempted.snapshot)),
            )
            applied.append(
                {
                    "gate_id": record.gate_id,
                    "from": record.from_state,
                    "to": record.to_state,
                    "caused_by": record.caused_by,
                    "timestamp": record.timestamp.isoformat(),
                    "snapshot": record.snapshot,
                }
            )

            for task in decision.enqueue_tasks_on_pass:
                base_emission: dict[str, Any] = {
                    "kind": "task_enqueued",
                    "task_id": task,
                    "gate_id": decision.gate_id,
                    "gate_version": decision.gate_version,
                    "entity_id": new_state.get("entity_id"),
                    "from_state": decision.from_state,
                    "to_state": decision.to_state,
                    "caused_by": caused_by,
                    "timestamp": attempted.timestamp.isoformat(),
                }
                if use_schema_envelopes and schemas_available():
                    entity_id = new_state.get("entity_id")
                    if not isinstance(entity_id, str) or not entity_id:
                        raise ValueError("entity_state.entity_id is required when use_schema_envelopes=True")
                    schema_payload = build_task_and_emission(
                        task_id=task,
                        created_at=attempted.timestamp,
                        caused_by=caused_by or "unknown",
                        entity_id=entity_id,
                        gate_id=decision.gate_id,
                        emission_id=f"{decision.gate_id}:{task}:{int(attempted.timestamp.timestamp())}",
                        priority=default_task_priority,
                    )
                    if schema_payload is not None:
                        base_emission["schema"] = schema_payload
                emissions.append(base_emission)

        if decision.cooldown_on == "attempt" or (decision.cooldown_on == "pass" and decision.passed):
            cooldowns[decision.gate_id] = decision.transition_attempted.timestamp.isoformat()

    return new_state, emissions
