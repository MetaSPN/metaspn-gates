from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .models import GateConfig, HardRequirement, SoftThreshold, StateMachineConfig


class ConfigError(ValueError):
    pass


SCHEMAS_PARSE_HOOK = "parse_state_machine_config"
SCHEMAS_VALIDATE_HOOK = "validate_state_machine_config"


def _mapping_from_object(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value

    for attr in ("model_dump", "dict", "to_dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            candidate = fn()
            if isinstance(candidate, Mapping):
                return candidate
    return None


def _load_schemas_backend() -> Any | None:
    try:
        return importlib.import_module("metaspn_schemas")
    except ImportError:
        return None


def schemas_backend_available() -> bool:
    return _load_schemas_backend() is not None


def schemas_contract_available() -> bool:
    backend = _load_schemas_backend()
    if backend is None:
        return False
    return callable(getattr(backend, SCHEMAS_PARSE_HOOK, None)) and callable(
        getattr(backend, SCHEMAS_VALIDATE_HOOK, None)
    )


def _call_parser(fn: Callable[..., Any], payload: Mapping[str, Any], path: Path) -> Any | None:
    last_exc: Exception | None = None
    for args in ((payload,), (payload, str(path))):
        try:
            return fn(*args)
        except Exception as exc:  # pragma: no cover - backend-defined exception types
            last_exc = exc
    # Degrade gracefully to caller fallback path when parser hook isn't compatible
    # with gate config payload shape.
    return None


def _parse_with_schemas_backend(payload: Mapping[str, Any] | None, path: Path, backend: Any) -> Mapping[str, Any] | None:
    parse_fn = getattr(backend, SCHEMAS_PARSE_HOOK, None)
    if not callable(parse_fn) or payload is None:
        return None
    parsed = _call_parser(parse_fn, payload, path)
    mapping = _mapping_from_object(parsed)
    if mapping is None:
        return None

    # Keep gate parsing stable: only accept backend parse results that look like
    # the expected gate config shape.
    if "config_version" in mapping and "gates" in mapping:
        return mapping
    return None


def _validate_with_schemas_backend(payload: Mapping[str, Any], backend: Any) -> Mapping[str, Any]:
    validate_fn = getattr(backend, SCHEMAS_VALIDATE_HOOK, None)
    if not callable(validate_fn):
        return payload
    try:
        validated = validate_fn(payload)
    except Exception as exc:  # pragma: no cover - backend-defined exception types
        raise ConfigError(f"metaspn_schemas validation failed: {exc}") from exc

    mapping = _mapping_from_object(validated)
    if mapping is not None:
        return mapping
    return payload


def _require_str(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{key} must be a non-empty string")
    return value


def _parse_hard_requirements(raw: Any) -> tuple[HardRequirement, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("hard_requirements must be a list")

    parsed: list[HardRequirement] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ConfigError("hard requirement entries must be objects")
        parsed.append(
            HardRequirement(
                requirement_id=_require_str(item, "requirement_id"),
                field=_require_str(item, "field"),
                op=_require_str(item, "op"),
                value=item.get("value"),
                source=item.get("source", "features"),
            )
        )
    return tuple(parsed)


def _parse_soft_thresholds(raw: Any) -> tuple[SoftThreshold, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("soft_thresholds must be a list")

    parsed: list[SoftThreshold] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ConfigError("soft threshold entries must be objects")
        if "value" not in item:
            raise ConfigError("soft threshold value is required")
        parsed.append(
            SoftThreshold(
                threshold_id=_require_str(item, "threshold_id"),
                field=_require_str(item, "field"),
                op=_require_str(item, "op"),
                value=item["value"],
                source=item.get("source", "features"),
            )
        )
    return tuple(parsed)


def parse_state_machine_config(payload: Mapping[str, Any]) -> StateMachineConfig:
    backend = _load_schemas_backend()
    if backend is not None:
        payload = _validate_with_schemas_backend(payload, backend)

    config_version = _require_str(payload, "config_version")

    raw_gates = payload.get("gates")
    if not isinstance(raw_gates, list) or not raw_gates:
        raise ConfigError("gates must be a non-empty list")

    gates: list[GateConfig] = []
    gate_ids: set[str] = set()

    for gate in raw_gates:
        if not isinstance(gate, Mapping):
            raise ConfigError("gate entries must be objects")

        gate_id = _require_str(gate, "gate_id")
        if gate_id in gate_ids:
            raise ConfigError(f"duplicate gate_id: {gate_id}")
        gate_ids.add(gate_id)

        raw_tasks = gate.get("enqueue_tasks_on_pass") or []
        if not isinstance(raw_tasks, list) or not all(isinstance(t, str) and t for t in raw_tasks):
            raise ConfigError("enqueue_tasks_on_pass must be a list of non-empty strings")

        raw_taxonomy = gate.get("failure_taxonomy") or {}
        if not isinstance(raw_taxonomy, Mapping):
            raise ConfigError("failure_taxonomy must be an object")

        cooldown_seconds = gate.get("cooldown_seconds", 0)
        if not isinstance(cooldown_seconds, int) or cooldown_seconds < 0:
            raise ConfigError("cooldown_seconds must be a non-negative integer")

        cooldown_on = gate.get("cooldown_on", "pass")
        if cooldown_on not in {"pass", "attempt"}:
            raise ConfigError("cooldown_on must be either 'pass' or 'attempt'")

        min_soft_passed = gate.get("min_soft_passed")
        if min_soft_passed is not None and (not isinstance(min_soft_passed, int) or min_soft_passed < 0):
            raise ConfigError("min_soft_passed must be a non-negative integer when provided")

        parsed = GateConfig(
            gate_id=gate_id,
            version=_require_str(gate, "version"),
            track=gate.get("track"),
            from_state=_require_str(gate, "from"),
            to_state=_require_str(gate, "to"),
            hard_requirements=_parse_hard_requirements(gate.get("hard_requirements")),
            soft_thresholds=_parse_soft_thresholds(gate.get("soft_thresholds")),
            min_soft_passed=min_soft_passed,
            cooldown_seconds=cooldown_seconds,
            cooldown_on=cooldown_on,
            enqueue_tasks_on_pass=tuple(raw_tasks),
            failure_taxonomy={str(k): str(v) for k, v in raw_taxonomy.items()},
        )

        if parsed.min_soft_passed is not None and parsed.min_soft_passed > len(parsed.soft_thresholds):
            raise ConfigError("min_soft_passed cannot exceed number of soft_thresholds")

        gates.append(parsed)

    # Stable deterministic order.
    gates.sort(key=lambda g: (g.track or "", g.from_state, g.gate_id))

    return StateMachineConfig(config_version=config_version, gates=tuple(gates))


def load_state_machine_config(path: str | Path) -> StateMachineConfig:
    """Loads config using metaspn_schemas contract hooks when available, otherwise JSON fallback."""

    path = Path(path)
    raw = path.read_text(encoding="utf-8")
    decoded_payload: Mapping[str, Any] | None = None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if parsed is not None:
        decoded_payload = _mapping_from_object(parsed)

    backend = _load_schemas_backend()
    payload: Mapping[str, Any] | None = None
    if backend is not None:
        payload = _parse_with_schemas_backend(decoded_payload, path, backend)

    if payload is None:
        if decoded_payload is None:
            raise ConfigError(
                "Config parsing failed. Install metaspn-schemas for YAML parsing, or provide JSON content."
            )
        payload = decoded_payload

    if payload is None or not isinstance(payload, Mapping):
        raise ConfigError("top-level config must be an object")

    return parse_state_machine_config(payload)
