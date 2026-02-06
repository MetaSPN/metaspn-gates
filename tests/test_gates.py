from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from metaspn_gates import apply_decisions, evaluate_gates, parse_state_machine_config
from metaspn_gates.config import (
    ConfigError,
    load_state_machine_config,
    schemas_backend_available,
    schemas_contract_available,
)


BASE_CONFIG = {
    "config_version": "sm.v1",
    "gates": [
        {
            "gate_id": "g.qualify.a",
            "version": "1",
            "track": "A",
            "from": "candidate",
            "to": "qualified",
            "hard_requirements": [
                {
                    "requirement_id": "hr.followers",
                    "field": "social.followers",
                    "op": "gte",
                    "value": 1000,
                }
            ],
            "soft_thresholds": [
                {
                    "threshold_id": "st.quality",
                    "field": "quality.score",
                    "op": "gte",
                    "value": 0.7,
                }
            ],
            "min_soft_passed": 1,
            "cooldown_seconds": 3600,
            "cooldown_on": "attempt",
            "enqueue_tasks_on_pass": ["task.review"],
            "failure_taxonomy": {"hr.followers": "insufficient_reach"},
        },
        {
            "gate_id": "g.qualify.b",
            "version": "1",
            "track": "B",
            "from": "candidate",
            "to": "qualified",
            "hard_requirements": [],
        },
    ],
}


class GateTests(unittest.TestCase):
    def test_deterministic_gate_evaluation(self) -> None:
        config = parse_state_machine_config(BASE_CONFIG)
        entity_state = {"state": "candidate", "track": "A"}
        features = {"social": {"followers": 1500}, "quality": {"score": 0.8}}

        now = datetime(2026, 2, 5, 0, 0, tzinfo=timezone.utc)
        d1 = evaluate_gates(config, entity_state, features, now)
        d2 = evaluate_gates(config, entity_state, features, now)

        self.assertEqual([d.gate_id for d in d1], ["g.qualify.a"])
        self.assertEqual([d.passed for d in d1], [True])
        self.assertEqual([(d.gate_id, d.passed, d.reason) for d in d1], [(d.gate_id, d.passed, d.reason) for d in d2])

    def test_cooldown_correctness(self) -> None:
        config = parse_state_machine_config(BASE_CONFIG)
        now = datetime(2026, 2, 5, 0, 0, tzinfo=timezone.utc)
        recent = now - timedelta(minutes=5)

        entity_state = {
            "state": "candidate",
            "track": "A",
            "gate_cooldowns": {"g.qualify.a": recent.isoformat()},
        }
        features = {"social": {"followers": 1500}, "quality": {"score": 0.9}}

        decisions = evaluate_gates(config, entity_state, features, now)
        self.assertEqual(len(decisions), 1)
        self.assertFalse(decisions[0].passed)
        self.assertTrue(decisions[0].cooldown_active)
        self.assertEqual(decisions[0].reason, "cooldown_active")

    def test_config_parsing_validation(self) -> None:
        bad = {
            "config_version": "x",
            "gates": [
                {
                    "gate_id": "a",
                    "version": "1",
                    "from": "s1",
                    "to": "s2",
                    "cooldown_seconds": -1,
                }
            ],
        }
        with self.assertRaises(ConfigError):
            parse_state_machine_config(bad)

    def test_snapshot_completeness(self) -> None:
        config = parse_state_machine_config(BASE_CONFIG)
        now = datetime(2026, 2, 5, 0, 0, tzinfo=timezone.utc)
        entity_state = {"state": "candidate", "track": "A"}
        features = {"social": {"followers": 1500}, "quality": {"score": 0.9}}

        decisions = evaluate_gates(config, entity_state, features, now)
        self.assertEqual(len(decisions), 1)
        snapshot = decisions[0].transition_attempted.snapshot
        self.assertIn("feature_snapshot", snapshot)
        self.assertIn("entity_snapshot", snapshot)
        self.assertIn("config_version", snapshot)
        self.assertIn("gate_version", snapshot)
        self.assertIn("timestamp", snapshot)

    def test_apply_decisions_emits_and_transitions(self) -> None:
        config = parse_state_machine_config(BASE_CONFIG)
        now = datetime(2026, 2, 5, 0, 0, tzinfo=timezone.utc)
        entity_state = {"state": "candidate", "track": "A"}
        features = {"social": {"followers": 1500}, "quality": {"score": 0.9}}

        decisions = evaluate_gates(config, entity_state, features, now)
        new_state, emissions = apply_decisions(entity_state, decisions, caused_by="sig-123")

        self.assertEqual(new_state["state"], "qualified")
        self.assertEqual(len(new_state["gate_attempts"]), 1)
        self.assertEqual(len(new_state["transitions_applied"]), 1)
        self.assertEqual(len(emissions), 1)
        self.assertEqual(emissions[0]["task_id"], "task.review")

    def test_apply_decisions_schema_emissions(self) -> None:
        config = parse_state_machine_config(BASE_CONFIG)
        now = datetime(2026, 2, 5, 0, 0, tzinfo=timezone.utc)
        entity_state = {"entity_id": "ent-1", "state": "candidate", "track": "A"}
        features = {"social": {"followers": 1500}, "quality": {"score": 0.9}}

        decisions = evaluate_gates(config, entity_state, features, now)
        with mock.patch("metaspn_gates.applier.schemas_available", return_value=True):
            with mock.patch(
                "metaspn_gates.applier.build_task_and_emission",
                return_value={"task": {"task_id": "task.review"}, "emission_envelope": {"emission_type": "task_enqueued"}},
            ):
                _, emissions = apply_decisions(entity_state, decisions, caused_by="sig-123", use_schema_envelopes=True)
        self.assertIn("schema", emissions[0])
        self.assertEqual(emissions[0]["schema"]["task"]["task_id"], "task.review")

    def test_apply_decisions_schema_emissions_require_entity_id(self) -> None:
        config = parse_state_machine_config(BASE_CONFIG)
        now = datetime(2026, 2, 5, 0, 0, tzinfo=timezone.utc)
        entity_state = {"state": "candidate", "track": "A"}
        features = {"social": {"followers": 1500}, "quality": {"score": 0.9}}

        decisions = evaluate_gates(config, entity_state, features, now)
        with mock.patch("metaspn_gates.applier.schemas_available", return_value=True):
            with self.assertRaises(ValueError):
                apply_decisions(entity_state, decisions, caused_by="sig-123", use_schema_envelopes=True)

    def test_failure_override_hook(self) -> None:
        config = parse_state_machine_config(BASE_CONFIG)
        now = datetime(2026, 2, 5, 0, 0, tzinfo=timezone.utc)
        entity_state = {
            "state": "candidate",
            "track": "A",
            "failure_overrides": {"g.qualify.a": "manual_override_reason"},
        }
        features = {"social": {"followers": 10}, "quality": {"score": 0.1}}

        decisions = evaluate_gates(config, entity_state, features, now)
        self.assertEqual(decisions[0].reason, "manual_override_reason")

    def test_load_state_machine_config_json_fallback(self) -> None:
        with mock.patch("metaspn_gates.config.importlib.import_module", side_effect=ImportError):
            with TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.yaml"
                path.write_text(
                    '{"config_version":"sm.v1","gates":[{"gate_id":"g1","version":"1","from":"a","to":"b"}]}',
                    encoding="utf-8",
                )
                config = load_state_machine_config(path)
                self.assertEqual(config.config_version, "sm.v1")
                self.assertEqual(config.gates[0].gate_id, "g1")

    def test_load_state_machine_config_uses_schemas_backend(self) -> None:
        class FakeSchemas:
            @staticmethod
            def parse_state_machine_config_yaml(raw: str) -> dict:
                if "config_version: sm.v2" not in raw:
                    raise ValueError("unexpected input")
                return {
                    "config_version": "sm.v2",
                    "gates": [
                        {
                            "gate_id": "g1",
                            "version": "2",
                            "from": "start",
                            "to": "next",
                        }
                    ],
                }

            @staticmethod
            def validate_state_machine_config(payload: dict) -> dict:
                out = dict(payload)
                out["config_version"] = "sm.v2.validated"
                return out

        with mock.patch("metaspn_gates.config.importlib.import_module", return_value=FakeSchemas):
            with TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.yaml"
                path.write_text(
                    "config_version: sm.v2\n"
                    "gates:\n"
                    "  - gate_id: g1\n"
                    "    version: '2'\n"
                    "    from: start\n"
                    "    to: next\n",
                    encoding="utf-8",
                )
                config = load_state_machine_config(path)
                self.assertEqual(config.config_version, "sm.v2.validated")
                self.assertEqual(config.gates[0].version, "2")

    def test_schemas_backend_available_helper(self) -> None:
        with mock.patch("metaspn_gates.config.importlib.import_module", return_value=object()):
            self.assertTrue(schemas_backend_available())
        with mock.patch("metaspn_gates.config.importlib.import_module", side_effect=ImportError):
            self.assertFalse(schemas_backend_available())

    def test_schemas_contract_available_helper(self) -> None:
        class FakeSchemas:
            @staticmethod
            def parse_state_machine_config_yaml(raw: str) -> dict:
                return {}

            @staticmethod
            def validate_state_machine_config(payload: dict) -> dict:
                return payload

        with mock.patch("metaspn_gates.config.importlib.import_module", return_value=FakeSchemas):
            self.assertTrue(schemas_contract_available())

        with mock.patch("metaspn_gates.config.importlib.import_module", return_value=object()):
            self.assertFalse(schemas_contract_available())

    def test_parse_state_machine_config_runs_backend_validation(self) -> None:
        class FakeSchemas:
            called = False

            @staticmethod
            def validate_state_machine_config(payload: dict) -> dict:
                FakeSchemas.called = True
                out = dict(payload)
                out["config_version"] = "validated"
                return out

        with mock.patch("metaspn_gates.config.importlib.import_module", return_value=FakeSchemas):
            config = parse_state_machine_config(
                {"config_version": "raw", "gates": [{"gate_id": "g1", "version": "1", "from": "a", "to": "b"}]}
            )
            self.assertTrue(FakeSchemas.called)
            self.assertEqual(config.config_version, "validated")


if __name__ == "__main__":
    unittest.main()
