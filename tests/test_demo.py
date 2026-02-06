from __future__ import annotations

import importlib
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from metaspn_gates import apply_decisions, evaluate_gates, format_decision_trace, load_state_machine_config


class DemoTests(unittest.TestCase):
    def _base_features(self, draft_enabled: bool) -> dict:
        return {
            "ingestion": {"resolved_entity_id": "ent-demo-1"},
            "profile": {"handle": "demo_user", "confidence": 0.91},
            "scores": {"quality_score": 0.88, "readiness_score": 0.9},
            "demo": {"draft_enabled": draft_enabled},
        }

    def test_demo_progression_without_optional_draft(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "demo_state_machine_config.json"
        config = load_state_machine_config(fixture)
        now = datetime(2026, 2, 6, 15, 0, tzinfo=timezone.utc)

        s0 = {"entity_id": "ent-demo-1", "state": "SEEN", "track": "DEMO"}
        features = self._base_features(draft_enabled=False)

        d1 = evaluate_gates(config, s0, features, now)
        s1, e1 = apply_decisions(s0, d1, caused_by="sig-demo")
        self.assertEqual(s1["state"], "OBSERVED")
        self.assertEqual(e1[0]["task_id"], "enrich_profile")

        d2 = evaluate_gates(config, s1, features, now)
        s2, e2 = apply_decisions(s1, d2, caused_by="sig-demo")
        self.assertEqual(s2["state"], "SHORTLISTED")
        self.assertEqual(e2[0]["task_id"], "score_entity")

        d3 = evaluate_gates(config, s2, features, now)
        self.assertEqual(len(d3), 2)
        passed = [x for x in d3 if x.passed]
        self.assertEqual(len(passed), 1)
        self.assertEqual(passed[0].gate_id, "demo.shortlisted_to_ready")
        s3, e3 = apply_decisions(s2, d3, caused_by="sig-demo")
        self.assertEqual(s3["state"], "READY")
        self.assertEqual(e3, [])

    def test_demo_progression_with_optional_draft(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "demo_state_machine_config.json"
        config = load_state_machine_config(fixture)
        now = datetime(2026, 2, 6, 15, 0, tzinfo=timezone.utc)

        s0 = {"entity_id": "ent-demo-2", "state": "SHORTLISTED", "track": "DEMO"}
        features = self._base_features(draft_enabled=True)

        decisions = evaluate_gates(config, s0, features, now)
        passed = [x for x in decisions if x.passed]
        self.assertEqual(len(passed), 1)
        self.assertEqual(passed[0].gate_id, "demo.shortlisted_to_ready_with_draft")
        _, emissions = apply_decisions(s0, decisions, caused_by="sig-demo")
        self.assertEqual(len(emissions), 1)
        self.assertEqual(emissions[0]["task_id"], "draft_message")

    def test_demo_digest_trace_helper(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "demo_state_machine_config.json"
        config = load_state_machine_config(fixture)
        now = datetime(2026, 2, 6, 15, 0, tzinfo=timezone.utc)
        state = {"entity_id": "ent-demo-3", "state": "SHORTLISTED", "track": "DEMO"}
        features = self._base_features(draft_enabled=False)

        decisions = evaluate_gates(config, state, features, now)
        trace = format_decision_trace(decisions)

        self.assertEqual(len(trace), 2)
        for row in trace:
            for key in ("gate_id", "passed", "blocked", "reason", "from_state", "to_state", "timestamp"):
                self.assertIn(key, row)

    def test_demo_loader_stable_with_backend_active(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "demo_state_machine_config.json"
        spec = importlib.util.find_spec("metaspn_schemas")
        if spec is None:
            self.skipTest("metaspn_schemas is not installed")

        backend = importlib.import_module("metaspn_schemas")
        parse_hook = getattr(backend, "parse_state_machine_config", None)
        if callable(parse_hook):
            with mock.patch.object(backend, "parse_state_machine_config", side_effect=TypeError("expects other shape")):
                config = load_state_machine_config(fixture)
        else:
            config = load_state_machine_config(fixture)

        self.assertEqual(config.config_version, "demo.v1")
        self.assertEqual({g.to_state for g in config.gates}, {"OBSERVED", "SHORTLISTED", "READY"})


if __name__ == "__main__":
    unittest.main()
