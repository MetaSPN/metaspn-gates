from __future__ import annotations

import importlib
import json
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
    def test_m0_fixture_progression_seen_observed_profiled(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "m0_state_machine_config.json"
        config = load_state_machine_config(fixture_path)
        now = datetime(2026, 2, 6, 0, 0, tzinfo=timezone.utc)

        entity_state = {"entity_id": "ent-42", "state": "SEEN", "track": "M0"}
        features = {
            "ingestion": {"resolved_entity_id": "ent-42"},
            "profile": {"handle": "neo", "confidence": 0.9},
        }

        first_decisions = evaluate_gates(config, entity_state, features, now)
        self.assertEqual(len(first_decisions), 1)
        self.assertEqual(first_decisions[0].gate_id, "m0.seen_to_observed")
        self.assertTrue(first_decisions[0].passed)

        state_after_first, first_emissions = apply_decisions(entity_state, first_decisions, caused_by="sig-m0")
        self.assertEqual(state_after_first["state"], "OBSERVED")
        self.assertEqual(first_emissions[0]["task_id"], "task.capture_observation")

        second_decisions = evaluate_gates(config, state_after_first, features, now)
        self.assertEqual(len(second_decisions), 1)
        self.assertEqual(second_decisions[0].gate_id, "m0.observed_to_profiled")
        self.assertTrue(second_decisions[0].passed)

        state_after_second, second_emissions = apply_decisions(state_after_first, second_decisions, caused_by="sig-m0")
        self.assertEqual(state_after_second["state"], "PROFILED")
        self.assertEqual(second_emissions[0]["task_id"], "task.build_profile")

    def test_decision_and_emission_contract_fields_for_workers(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "m0_state_machine_config.json"
        config = load_state_machine_config(fixture_path)
        now = datetime(2026, 2, 6, 0, 0, tzinfo=timezone.utc)
        entity_state = {"entity_id": "ent-55", "state": "SEEN", "track": "M0"}
        features = {"ingestion": {"resolved_entity_id": "ent-55"}, "profile": {"handle": "p55", "confidence": 0.8}}

        decisions = evaluate_gates(config, entity_state, features, now)
        self.assertEqual(len(decisions), 1)
        decision = decisions[0]
        for attr in (
            "gate_id",
            "gate_version",
            "from_state",
            "to_state",
            "passed",
            "cooldown_active",
            "cooldown_on",
            "enqueue_tasks_on_pass",
            "transition_attempted",
        ):
            self.assertTrue(hasattr(decision, attr))

        attempted = decision.transition_attempted
        self.assertEqual(attempted.gate_id, decision.gate_id)
        self.assertIn("feature_snapshot", attempted.snapshot)
        self.assertIn("entity_snapshot", attempted.snapshot)
        self.assertIn("config_version", attempted.snapshot)
        self.assertIn("gate_version", attempted.snapshot)
        self.assertIn("timestamp", attempted.snapshot)

        _, emissions = apply_decisions(entity_state, decisions, caused_by="sig-contract")
        self.assertEqual(len(emissions), 1)
        for key in ("kind", "task_id", "gate_id", "caused_by", "timestamp"):
            self.assertIn(key, emissions[0])
        self.assertEqual(emissions[0]["kind"], "task_enqueued")
        self.assertEqual(emissions[0]["gate_id"], decision.gate_id)

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
            seen_payload_type = None

            @staticmethod
            def parse_state_machine_config(payload: dict) -> dict:
                FakeSchemas.seen_payload_type = type(payload)
                if payload.get("config_version") != "sm.v2":
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
                path = Path(tmp) / "config.json"
                path.write_text(
                    '{"config_version":"sm.v2","gates":[{"gate_id":"g1","version":"2","from":"start","to":"next"}]}',
                    encoding="utf-8",
                )
                config = load_state_machine_config(path)
                self.assertEqual(config.config_version, "sm.v2.validated")
                self.assertEqual(config.gates[0].version, "2")
                self.assertEqual(FakeSchemas.seen_payload_type, dict)

    def test_schemas_backend_available_helper(self) -> None:
        with mock.patch("metaspn_gates.config.importlib.import_module", return_value=object()):
            self.assertTrue(schemas_backend_available())
        with mock.patch("metaspn_gates.config.importlib.import_module", side_effect=ImportError):
            self.assertFalse(schemas_backend_available())

    def test_schemas_contract_available_helper(self) -> None:
        class FakeSchemas:
            @staticmethod
            def parse_state_machine_config(raw: str) -> dict:
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

    def test_load_state_machine_config_schema_parser_receives_mapping_not_raw(self) -> None:
        class FakeSchemas:
            @staticmethod
            def parse_state_machine_config(payload: dict) -> dict:
                if not isinstance(payload, dict):
                    raise TypeError("payload must be mapping")
                return payload

            @staticmethod
            def validate_state_machine_config(payload: dict) -> dict:
                return payload

        with mock.patch("metaspn_gates.config.importlib.import_module", return_value=FakeSchemas):
            with TemporaryDirectory() as tmp:
                path = Path(tmp) / "config.json"
                path.write_text(
                    '{"config_version":"sm.v1","gates":[{"gate_id":"g1","version":"1","from":"a","to":"b"}]}',
                    encoding="utf-8",
                )
                config = load_state_machine_config(path)
                self.assertEqual(config.gates[0].gate_id, "g1")

    def test_real_schemas_backend_present_path_stays_stable(self) -> None:
        spec = importlib.util.find_spec("metaspn_schemas")
        if spec is None:
            self.skipTest("metaspn_schemas is not installed in this environment")

        backend = importlib.import_module("metaspn_schemas")
        fixture_path = Path(__file__).parent / "fixtures" / "m0_state_machine_config.json"
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))

        parse_hook = getattr(backend, "parse_state_machine_config", None)
        if callable(parse_hook):
            with mock.patch.object(backend, "parse_state_machine_config", side_effect=TypeError("expects mapping")):
                config = load_state_machine_config(fixture_path)
        else:
            # Older schemas builds may not expose the parse hook at package root.
            config = load_state_machine_config(fixture_path)

        self.assertEqual(config.config_version, payload["config_version"])
        self.assertEqual(
            {g.gate_id for g in config.gates},
            {g["gate_id"] for g in payload["gates"]},
        )


if __name__ == "__main__":
    unittest.main()
