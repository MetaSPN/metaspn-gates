from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(frozen=True)
class HardRequirement:
    requirement_id: str
    field: str
    op: str
    value: Any = None
    source: str = "features"


@dataclass(frozen=True)
class SoftThreshold:
    threshold_id: str
    field: str
    op: str
    value: Any
    source: str = "features"


@dataclass(frozen=True)
class GateConfig:
    gate_id: str
    version: str
    track: str | None
    from_state: str
    to_state: str
    hard_requirements: tuple[HardRequirement, ...] = field(default_factory=tuple)
    soft_thresholds: tuple[SoftThreshold, ...] = field(default_factory=tuple)
    min_soft_passed: int | None = None
    cooldown_seconds: int = 0
    cooldown_on: str = "pass"  # pass | attempt
    cooldown_scope: str = "entity"  # entity | channel | playbook | channel_playbook
    cooldown_channel_field: str = "context.channel"
    cooldown_playbook_field: str = "context.playbook"
    suppression_field: str | None = None
    enqueue_tasks_on_pass: tuple[str, ...] = field(default_factory=tuple)
    failure_taxonomy: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class StateMachineConfig:
    config_version: str
    gates: tuple[GateConfig, ...]


@dataclass(frozen=True)
class TransitionAttempted:
    gate_id: str
    from_state: str
    to_state: str
    passed: bool
    timestamp: datetime
    reason: str | None
    failed_requirement_id: str | None
    snapshot: Mapping[str, Any]


@dataclass(frozen=True)
class GateDecision:
    gate_id: str
    gate_version: str
    track: str | None
    from_state: str
    to_state: str
    passed: bool
    reason: str | None
    failed_requirement_id: str | None
    cooldown_active: bool
    cooldown_on: str
    cooldown_scope: str
    cooldown_scope_key: str | None
    enqueue_tasks_on_pass: tuple[str, ...]
    transition_attempted: TransitionAttempted


@dataclass(frozen=True)
class TransitionApplied:
    gate_id: str
    from_state: str
    to_state: str
    caused_by: str | None
    timestamp: datetime
    snapshot: Mapping[str, Any]
