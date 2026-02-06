from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class AttemptOutcomeEvaluation:
    attempt_id: str
    gate_id: str
    label: str
    success_observed: bool
    outcomes_count: int
    failure_reason: str | None
    attempted_at: datetime


@dataclass(frozen=True)
class CalibrationProposal:
    gate_id: str
    recommendation_type: str
    direction: str
    rationale: str
    confidence: float
    auto_apply: bool = False


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def classify_failure_reason(
    *,
    label: str,
    taxonomy_map: Mapping[str, str] | None = None,
    default_reason: str = "unknown_failure",
) -> str | None:
    if label in {"true_positive", "true_negative"}:
        return None
    if taxonomy_map and label in taxonomy_map:
        return taxonomy_map[label]
    return default_reason


def evaluate_attempt_outcomes(
    attempts: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    *,
    outcome_window_seconds: int,
    failure_taxonomy_map: Mapping[str, str] | None = None,
) -> list[AttemptOutcomeEvaluation]:
    if outcome_window_seconds < 0:
        raise ValueError("outcome_window_seconds must be non-negative")

    normalized_outcomes: list[tuple[datetime, bool]] = []
    for outcome in outcomes:
        ts = outcome.get("timestamp")
        if not isinstance(ts, datetime):
            continue
        normalized_outcomes.append((_as_utc(ts), bool(outcome.get("success"))))

    normalized_outcomes.sort(key=lambda row: row[0])

    rows: list[AttemptOutcomeEvaluation] = []
    for attempt in attempts:
        attempted_at = attempt.get("attempted_at")
        if not isinstance(attempted_at, datetime):
            continue
        attempt_ts = _as_utc(attempted_at)
        window_end = attempt_ts + timedelta(seconds=outcome_window_seconds)

        in_window = [success for ts, success in normalized_outcomes if attempt_ts <= ts <= window_end]
        success_observed = any(in_window)
        passed = bool(attempt.get("passed"))

        if passed and success_observed:
            label = "true_positive"
        elif passed and not success_observed:
            label = "moved_too_early"
        elif not passed and success_observed:
            label = "false_negative"
        else:
            label = "true_negative"

        rows.append(
            AttemptOutcomeEvaluation(
                attempt_id=str(attempt.get("attempt_id", "")),
                gate_id=str(attempt.get("gate_id", "")),
                label=label,
                success_observed=success_observed,
                outcomes_count=len(in_window),
                failure_reason=classify_failure_reason(label=label, taxonomy_map=failure_taxonomy_map),
                attempted_at=attempt_ts,
            )
        )

    rows.sort(key=lambda r: (r.gate_id, r.attempted_at, r.attempt_id))
    return rows


def generate_calibration_proposals(
    evaluations: Sequence[AttemptOutcomeEvaluation],
    *,
    min_samples: int = 3,
) -> list[CalibrationProposal]:
    if min_samples < 1:
        raise ValueError("min_samples must be >= 1")

    by_gate: dict[str, list[AttemptOutcomeEvaluation]] = defaultdict(list)
    for ev in evaluations:
        by_gate[ev.gate_id].append(ev)

    proposals: list[CalibrationProposal] = []
    for gate_id in sorted(by_gate):
        samples = by_gate[gate_id]
        if len(samples) < min_samples:
            continue

        false_positive = sum(1 for s in samples if s.label == "moved_too_early")
        false_negative = sum(1 for s in samples if s.label == "false_negative")
        total = len(samples)

        fp_rate = false_positive / total
        fn_rate = false_negative / total

        if fp_rate >= 0.30:
            proposals.append(
                CalibrationProposal(
                    gate_id=gate_id,
                    recommendation_type="threshold_adjustment",
                    direction="increase",
                    rationale="high moved_too_early rate",
                    confidence=round(fp_rate, 4),
                    auto_apply=False,
                )
            )
            proposals.append(
                CalibrationProposal(
                    gate_id=gate_id,
                    recommendation_type="cooldown_adjustment",
                    direction="increase",
                    rationale="repeated early transitions in window",
                    confidence=round(fp_rate, 4),
                    auto_apply=False,
                )
            )

        if fn_rate >= 0.30:
            proposals.append(
                CalibrationProposal(
                    gate_id=gate_id,
                    recommendation_type="threshold_adjustment",
                    direction="decrease",
                    rationale="high false_negative rate",
                    confidence=round(fn_rate, 4),
                    auto_apply=False,
                )
            )

    proposals.sort(key=lambda p: (p.gate_id, p.recommendation_type, p.direction, p.rationale))
    return proposals
