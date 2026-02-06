from __future__ import annotations

import importlib
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from metaspn_gates import apply_decisions, evaluate_gates, load_state_machine_config


class TokenGateTests(unittest.TestCase):
    def _features(self) -> dict:
        return {
            "token": {
                "address": "0xabc123",
                "chain": "base",
                "symbol": "TKN",
                "holder_count": 1200,
                "creator_behavior_risk": 0.22,
            },
            "scores": {
                "credibility": 0.87,
                "organic_volume": 0.82,
                "concentration": 0.33,
            },
        }

    def test_token_fixture_loads_with_backend_present(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "token_health_state_machine_config.json"
        spec = importlib.util.find_spec("metaspn_schemas")
        if spec is None:
            self.skipTest("metaspn_schemas is not installed")

        backend = importlib.import_module("metaspn_schemas")
        parse_hook = getattr(backend, "parse_state_machine_config", None)
        if callable(parse_hook):
            with mock.patch.object(backend, "parse_state_machine_config", side_effect=TypeError("shape mismatch expected")):
                config = load_state_machine_config(fixture)
        else:
            config = load_state_machine_config(fixture)

        self.assertEqual(config.config_version, "token.v1")
        self.assertEqual({g.gate_id for g in config.gates}, {"token.candidate_to_watchlisted", "token.watchlisted_to_promising"})

    def test_token_gate_decisions_are_deterministic(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "token_health_state_machine_config.json"
        config = load_state_machine_config(fixture)
        now = datetime(2026, 2, 6, 16, 0, tzinfo=timezone.utc)
        state = {"entity_id": "tok-1", "state": "CANDIDATE", "track": "TOKEN"}
        features = self._features()

        d1 = evaluate_gates(config, state, features, now)
        d2 = evaluate_gates(config, state, features, now)
        self.assertEqual([(d.gate_id, d.passed, d.reason) for d in d1], [(d.gate_id, d.passed, d.reason) for d in d2])
        self.assertEqual(d1[0].gate_id, "token.candidate_to_watchlisted")
        self.assertTrue(d1[0].passed)

    def test_token_gate_progression_and_task_metadata(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "token_health_state_machine_config.json"
        config = load_state_machine_config(fixture)
        now = datetime(2026, 2, 6, 16, 0, tzinfo=timezone.utc)
        state = {"entity_id": "tok-2", "state": "CANDIDATE", "track": "TOKEN"}
        features = self._features()

        first = evaluate_gates(config, state, features, now)
        state1, emissions1 = apply_decisions(state, first, caused_by="sig-token")
        self.assertEqual(state1["state"], "WATCHLISTED")
        self.assertEqual(emissions1[0]["task_id"], "token.enrich_profile")
        self.assertEqual(emissions1[0]["token_address"], "0xabc123")
        self.assertEqual(emissions1[0]["chain"], "base")
        self.assertEqual(emissions1[0]["symbol"], "TKN")

        second = evaluate_gates(config, state1, features, now)
        state2, emissions2 = apply_decisions(state1, second, caused_by="sig-token")
        self.assertEqual(state2["state"], "PROMISING")
        self.assertEqual(emissions2[0]["task_id"], "token.route_review")

    def test_token_cooldown_blocks_repeat_attempts(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "token_health_state_machine_config.json"
        config = load_state_machine_config(fixture)
        now = datetime(2026, 2, 6, 16, 0, tzinfo=timezone.utc)
        state = {
            "entity_id": "tok-3",
            "state": "CANDIDATE",
            "track": "TOKEN",
            "gate_cooldowns": {"token.candidate_to_watchlisted": (now - timedelta(seconds=60)).isoformat()},
        }

        decisions = evaluate_gates(config, state, self._features(), now)
        self.assertEqual(len(decisions), 1)
        self.assertFalse(decisions[0].passed)
        self.assertEqual(decisions[0].reason, "cooldown_active")


if __name__ == "__main__":
    unittest.main()
