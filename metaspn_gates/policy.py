from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


_ALLOWED_POLICY_WINDOWS: dict[str, str] = {
    "stake": "ACTIVE",
    "unstake": "CLAIMABLE",
    "claim": "CLAIMABLE",
}


@dataclass(frozen=True)
class PolicyDecision:
    action: str
    allowed: bool
    state: str | None
    required_state: str | None
    reason: str


def evaluate_season1_policy(entity_state: Mapping[str, object], action: str) -> PolicyDecision:
    current_state = entity_state.get("state")
    state = current_state if isinstance(current_state, str) else None
    required_state = _ALLOWED_POLICY_WINDOWS.get(action)

    if required_state is None:
        return PolicyDecision(
            action=action,
            allowed=False,
            state=state,
            required_state=None,
            reason="unsupported_action",
        )

    if state == required_state:
        return PolicyDecision(
            action=action,
            allowed=True,
            state=state,
            required_state=required_state,
            reason="allowed",
        )

    return PolicyDecision(
        action=action,
        allowed=False,
        state=state,
        required_state=required_state,
        reason="outside_policy_window",
    )
