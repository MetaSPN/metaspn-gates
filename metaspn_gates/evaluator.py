from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .models import GateDecision, GateConfig, StateMachineConfig, TransitionAttempted


def _get_path(mapping: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = mapping
    for key in path.split("."):
        if not isinstance(current, Mapping) or key not in current:
            return False, None
        current = current[key]
    return True, current


def _compare(op: str, actual: Any, expected: Any) -> bool:
    if op == "eq":
        return actual == expected
    if op == "ne":
        return actual != expected
    if op == "gt":
        return actual > expected
    if op == "gte":
        return actual >= expected
    if op == "lt":
        return actual < expected
    if op == "lte":
        return actual <= expected
    if op == "in":
        return actual in expected
    if op == "not_in":
        return actual not in expected
    raise ValueError(f"unsupported operator: {op}")


def _requirement_passed(source: Mapping[str, Any], field: str, op: str, value: Any) -> bool:
    if op == "exists":
        exists, _ = _get_path(source, field)
        return exists
    if op == "not_exists":
        exists, _ = _get_path(source, field)
        return not exists

    exists, actual = _get_path(source, field)
    if not exists:
        return False
    return _compare(op, actual, value)


def _check_cooldown(gate: GateConfig, entity_state: Mapping[str, Any], now: datetime) -> bool:
    if gate.cooldown_seconds <= 0:
        return False

    cooldowns = entity_state.get("gate_cooldowns")
    if not isinstance(cooldowns, Mapping):
        return False

    raw_last = cooldowns.get(gate.gate_id)
    if raw_last is None:
        return False

    if isinstance(raw_last, str):
        last_attempt = datetime.fromisoformat(raw_last)
    elif isinstance(raw_last, datetime):
        last_attempt = raw_last
    else:
        return False

    if last_attempt.tzinfo is None:
        last_attempt = last_attempt.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    return now < (last_attempt + timedelta(seconds=gate.cooldown_seconds))


def _matches_state(gate: GateConfig, entity_state: Mapping[str, Any]) -> bool:
    if entity_state.get("state") != gate.from_state:
        return False

    if gate.track is None:
        return True
    return entity_state.get("track") == gate.track


class Evaluator:
    def evaluate_gates(
        self,
        config: StateMachineConfig,
        entity_state: Mapping[str, Any],
        features: Mapping[str, Any],
        now: datetime,
    ) -> list[GateDecision]:
        return evaluate_gates(config, entity_state, features, now)


def evaluate_gates(
    config: StateMachineConfig,
    entity_state: Mapping[str, Any],
    features: Mapping[str, Any],
    now: datetime,
) -> list[GateDecision]:
    decisions: list[GateDecision] = []

    failure_overrides = entity_state.get("failure_overrides")
    if not isinstance(failure_overrides, Mapping):
        failure_overrides = {}

    for gate in config.gates:
        if not _matches_state(gate, entity_state):
            continue

        cooldown_active = _check_cooldown(gate, entity_state, now)
        passed = not cooldown_active
        reason: str | None = "cooldown_active" if cooldown_active else None
        failed_requirement_id: str | None = None

        feature_source = features
        entity_source = entity_state

        # Hard requirements short-circuit on first failure.
        if passed:
            for requirement in gate.hard_requirements:
                source = entity_source if requirement.source == "entity" else feature_source
                if not _requirement_passed(source, requirement.field, requirement.op, requirement.value):
                    passed = False
                    failed_requirement_id = requirement.requirement_id
                    reason = gate.failure_taxonomy.get(requirement.requirement_id, "hard_requirement_failed")
                    break

        if passed and gate.soft_thresholds:
            soft_passes = 0
            for threshold in gate.soft_thresholds:
                source = entity_source if threshold.source == "entity" else feature_source
                if _requirement_passed(source, threshold.field, threshold.op, threshold.value):
                    soft_passes += 1

            needed = gate.min_soft_passed if gate.min_soft_passed is not None else len(gate.soft_thresholds)
            if soft_passes < needed:
                passed = False
                reason = "soft_threshold_failed"

        override_reason = failure_overrides.get(gate.gate_id)
        if not passed and isinstance(override_reason, str) and override_reason:
            reason = override_reason

        snapshot = {
            "feature_snapshot": deepcopy(dict(features)),
            "entity_snapshot": deepcopy(dict(entity_state)),
            "config_version": config.config_version,
            "gate_version": gate.version,
            "timestamp": now.isoformat(),
            "cooldown_active": cooldown_active,
        }

        transition_attempted = TransitionAttempted(
            gate_id=gate.gate_id,
            from_state=gate.from_state,
            to_state=gate.to_state,
            passed=passed,
            timestamp=now,
            reason=reason,
            failed_requirement_id=failed_requirement_id,
            snapshot=snapshot,
        )

        decisions.append(
            GateDecision(
                gate_id=gate.gate_id,
                gate_version=gate.version,
                track=gate.track,
                from_state=gate.from_state,
                to_state=gate.to_state,
                passed=passed,
                reason=reason,
                failed_requirement_id=failed_requirement_id,
                cooldown_active=cooldown_active,
                cooldown_on=gate.cooldown_on,
                enqueue_tasks_on_pass=gate.enqueue_tasks_on_pass,
                transition_attempted=transition_attempted,
            )
        )

    return decisions
