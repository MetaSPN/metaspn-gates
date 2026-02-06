from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from metaspn_gates.learning import (
    classify_failure_reason,
    evaluate_attempt_outcomes,
    generate_calibration_proposals,
)


class LearningTests(unittest.TestCase):
    def test_moved_too_early_detection(self) -> None:
        now = datetime(2026, 2, 6, 12, 0, tzinfo=timezone.utc)
        attempts = [{"attempt_id": "a1", "gate_id": "g1", "attempted_at": now, "passed": True}]
        outcomes = [{"timestamp": now + timedelta(minutes=20), "success": True}]

        rows = evaluate_attempt_outcomes(
            attempts,
            outcomes,
            outcome_window_seconds=300,
            failure_taxonomy_map={"moved_too_early": "window_miss"},
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].label, "moved_too_early")
        self.assertEqual(rows[0].failure_reason, "window_miss")

    def test_false_negative_and_false_positive_behavior(self) -> None:
        now = datetime(2026, 2, 6, 12, 0, tzinfo=timezone.utc)
        attempts = [
            {"attempt_id": "a1", "gate_id": "g1", "attempted_at": now, "passed": True},
            {"attempt_id": "a2", "gate_id": "g1", "attempted_at": now + timedelta(minutes=1), "passed": False},
        ]
        outcomes = [
            {"timestamp": now + timedelta(seconds=20), "success": False},
            {"timestamp": now + timedelta(minutes=1, seconds=15), "success": True},
        ]

        rows = evaluate_attempt_outcomes(attempts, outcomes, outcome_window_seconds=30)
        self.assertEqual(rows[0].label, "moved_too_early")
        self.assertEqual(rows[1].label, "false_negative")

    def test_calibration_recommendation_determinism(self) -> None:
        now = datetime(2026, 2, 6, 12, 0, tzinfo=timezone.utc)
        attempts = [
            {"attempt_id": "a1", "gate_id": "g1", "attempted_at": now, "passed": True},
            {"attempt_id": "a2", "gate_id": "g1", "attempted_at": now + timedelta(minutes=1), "passed": True},
            {"attempt_id": "a3", "gate_id": "g1", "attempted_at": now + timedelta(minutes=2), "passed": False},
            {"attempt_id": "a4", "gate_id": "g1", "attempted_at": now + timedelta(minutes=3), "passed": False},
        ]
        outcomes = [
            {"timestamp": now + timedelta(minutes=5), "success": True},
            {"timestamp": now + timedelta(minutes=6), "success": True},
        ]

        rows = evaluate_attempt_outcomes(attempts, outcomes, outcome_window_seconds=120)
        p1 = generate_calibration_proposals(rows, min_samples=3)
        p2 = generate_calibration_proposals(rows, min_samples=3)

        self.assertEqual([(x.gate_id, x.recommendation_type, x.direction, x.confidence) for x in p1], [(x.gate_id, x.recommendation_type, x.direction, x.confidence) for x in p2])
        self.assertTrue(all(not p.auto_apply for p in p1))

    def test_classify_failure_reason_defaults(self) -> None:
        self.assertIsNone(classify_failure_reason(label="true_positive", taxonomy_map={}))
        self.assertEqual(classify_failure_reason(label="false_negative", taxonomy_map={}), "unknown_failure")


if __name__ == "__main__":
    unittest.main()
