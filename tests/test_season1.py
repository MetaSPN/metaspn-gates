from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from metaspn_gates import (
    apply_decisions,
    evaluate_gates,
    evaluate_season1_policy,
    format_admin_decision_trace,
    load_state_machine_config,
)


class Season1GateTests(unittest.TestCase):
    def setUp(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "season1_state_machine_config.json"
        self.config = load_state_machine_config(fixture)
        self.now = datetime(2026, 2, 7, 12, 0, tzinfo=timezone.utc)

    def test_lifecycle_progression_valid_path(self) -> None:
        s0 = {"entity_id": "season-1", "state": "NOT_STARTED", "track": "SEASON1"}

        d1 = evaluate_gates(self.config, s0, {"founder": {"stake": 1000}}, self.now)
        self.assertEqual(d1[0].gate_id, "season1.not_started_to_active")
        self.assertTrue(d1[0].passed)
        s1, e1 = apply_decisions(s0, d1, caused_by="sig-s1")
        self.assertEqual(s1["state"], "ACTIVE")
        self.assertEqual(e1[0]["task_id"], "season.activate")

        d2 = evaluate_gates(self.config, s1, {"season": {"end_reached": True}}, self.now)
        self.assertTrue(d2[0].passed)
        s2, e2 = apply_decisions(s1, d2, caused_by="sig-s1")
        self.assertEqual(s2["state"], "ENDED")
        self.assertEqual(e2[0]["task_id"], "season.settle")

        d3 = evaluate_gates(self.config, s2, {"season": {"claim_window_open": True}}, self.now)
        self.assertTrue(d3[0].passed)
        s3, e3 = apply_decisions(s2, d3, caused_by="sig-s1")
        self.assertEqual(s3["state"], "CLAIMABLE")
        self.assertEqual(e3[0]["task_id"], "season.open_claims")

        d4 = evaluate_gates(self.config, s3, {"season": {"close_ready": True}}, self.now)
        self.assertTrue(d4[0].passed)
        s4, e4 = apply_decisions(s3, d4, caused_by="sig-s1")
        self.assertEqual(s4["state"], "CLOSED")
        self.assertEqual(e4[0]["task_id"], "season.close")

    def test_founder_heartbeat_required_for_activation(self) -> None:
        state = {"entity_id": "season-2", "state": "NOT_STARTED", "track": "SEASON1"}
        decisions = evaluate_gates(self.config, state, {"founder": {"stake": 0}}, self.now)

        self.assertEqual(len(decisions), 1)
        self.assertFalse(decisions[0].passed)
        self.assertEqual(decisions[0].reason, "founder_heartbeat_missing")

    def test_activation_cooldown_applies_on_attempt(self) -> None:
        state = {
            "entity_id": "season-3",
            "state": "NOT_STARTED",
            "track": "SEASON1",
            "gate_cooldowns": {"season1.not_started_to_active": (self.now - timedelta(seconds=60)).isoformat()},
        }
        decisions = evaluate_gates(self.config, state, {"founder": {"stake": 500}}, self.now)

        self.assertFalse(decisions[0].passed)
        self.assertEqual(decisions[0].reason, "cooldown_active")

    def test_deterministic_decisions_and_emissions(self) -> None:
        state = {"entity_id": "season-4", "state": "NOT_STARTED", "track": "SEASON1"}
        features = {"founder": {"stake": 1500}}

        d1 = evaluate_gates(self.config, state, features, self.now)
        d2 = evaluate_gates(self.config, state, features, self.now)
        self.assertEqual([(d.gate_id, d.passed, d.reason) for d in d1], [(d.gate_id, d.passed, d.reason) for d in d2])

        _, e1 = apply_decisions(state, d1, caused_by="sig-repeat")
        _, e2 = apply_decisions(state, d1, caused_by="sig-repeat")
        self.assertEqual(e1, e2)

    def test_admin_trace_contains_audit_fields(self) -> None:
        state = {"entity_id": "season-5", "state": "NOT_STARTED", "track": "SEASON1"}
        decisions = evaluate_gates(self.config, state, {"founder": {"stake": 0}}, self.now)

        trace = format_admin_decision_trace(decisions)
        self.assertEqual(len(trace), 1)
        row = trace[0]
        for key in (
            "gate_id",
            "gate_version",
            "track",
            "passed",
            "reason",
            "failed_requirement_id",
            "cooldown_active",
            "cooldown_scope",
            "cooldown_scope_key",
            "snapshot_config_version",
            "snapshot_gate_version",
            "timestamp",
        ):
            self.assertIn(key, row)


class Season1PolicyTests(unittest.TestCase):
    def test_policy_windows(self) -> None:
        self.assertTrue(evaluate_season1_policy({"state": "ACTIVE"}, "stake").allowed)
        self.assertFalse(evaluate_season1_policy({"state": "ENDED"}, "stake").allowed)

        self.assertTrue(evaluate_season1_policy({"state": "CLAIMABLE"}, "unstake").allowed)
        self.assertFalse(evaluate_season1_policy({"state": "ACTIVE"}, "unstake").allowed)

        self.assertTrue(evaluate_season1_policy({"state": "CLAIMABLE"}, "claim").allowed)
        self.assertFalse(evaluate_season1_policy({"state": "NOT_STARTED"}, "claim").allowed)

    def test_unsupported_action(self) -> None:
        decision = evaluate_season1_policy({"state": "ACTIVE"}, "slash")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "unsupported_action")


if __name__ == "__main__":
    unittest.main()
