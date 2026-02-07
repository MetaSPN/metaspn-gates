from __future__ import annotations

from typing import Any, Iterable

from .models import GateDecision


def format_decision_trace(decisions: Iterable[GateDecision]) -> list[dict[str, Any]]:
    """Returns digest-ready gate trace rows.

    Each row includes passed/blocked flags and reason text so downstream digest
    renderers can explain "why this entity" without duplicating gate logic.
    """

    rows: list[dict[str, Any]] = []
    for decision in decisions:
        reason = decision.reason if decision.reason else ("passed" if decision.passed else "blocked")
        rows.append(
            {
                "gate_id": decision.gate_id,
                "from_state": decision.from_state,
                "to_state": decision.to_state,
                "passed": decision.passed,
                "blocked": not decision.passed,
                "reason": reason,
                "failed_requirement_id": decision.failed_requirement_id,
                "cooldown_active": decision.cooldown_active,
                "timestamp": decision.transition_attempted.timestamp.isoformat(),
            }
        )

    rows.sort(key=lambda r: (r["gate_id"], r["timestamp"]))
    return rows


def format_admin_decision_trace(decisions: Iterable[GateDecision]) -> list[dict[str, Any]]:
    """Returns admin audit rows with lifecycle and policy debugging context."""

    rows: list[dict[str, Any]] = []
    for decision in decisions:
        attempted = decision.transition_attempted
        snapshot = attempted.snapshot
        rows.append(
            {
                "gate_id": decision.gate_id,
                "gate_version": decision.gate_version,
                "track": decision.track,
                "from_state": decision.from_state,
                "to_state": decision.to_state,
                "passed": decision.passed,
                "reason": decision.reason if decision.reason else ("passed" if decision.passed else "blocked"),
                "failed_requirement_id": decision.failed_requirement_id,
                "cooldown_active": decision.cooldown_active,
                "cooldown_scope": decision.cooldown_scope,
                "cooldown_scope_key": decision.cooldown_scope_key,
                "snapshot_config_version": snapshot.get("config_version"),
                "snapshot_gate_version": snapshot.get("gate_version"),
                "timestamp": attempted.timestamp.isoformat(),
            }
        )

    rows.sort(key=lambda r: (r["gate_id"], r["timestamp"]))
    return rows
