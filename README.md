# metaspn-gates

`metaspn-gates` is a config-driven gate + state-machine evaluator for MetaSPN entity pipelines.

## Current implementation (v0.1 seed)

- Deterministic gate evaluation from config
- Hard requirements and soft thresholds
- Per-gate per-entity cooldown checks
- Transition attempt snapshots
- Transition application + task emissions
- Config parsing and validation from mapping
- `metaspn-schemas` integration hooks (currently used for typed emission shaping)
- Optional `metaspn-schemas` emission shaping (`Task` + `EmissionEnvelope`)

## Public API

- `evaluate_gates(config, entity_state, features, now)`
- `apply_decisions(entity_state, decisions, caused_by=None)`
- `parse_state_machine_config(payload)`
- `load_state_machine_config(path)`

## Notes

- `load_state_machine_config` can use `metaspn_schemas` parsing/validation hooks when exposed by that package version.
- Canonical schema hooks:
  - parser: `parse_state_machine_config` (mapping payload)
  - validator: `validate_state_machine_config`
- If `metaspn_schemas` is unavailable, it falls back to JSON parsing only.
- Current dependency target: `metaspn-schemas>=0.1.0,<0.2.0`.
- `apply_decisions(..., use_schema_envelopes=True)` attaches schema-shaped payloads when `entity_state.entity_id` is present.

## M0 Minimum Keys

For the sample M0 progression (`SEEN -> OBSERVED -> PROFILED`) the minimum keys are:

- `entity_state.state`: `SEEN` or `OBSERVED`
- `entity_state.track`: `M0`
- `features.ingestion.resolved_entity_id`: required for `SEEN -> OBSERVED`
- `features.profile.handle`: required for `OBSERVED -> PROFILED`
- `features.profile.confidence`: numeric threshold for `OBSERVED -> PROFILED` (sample gate uses `>= 0.7`)

Reference fixture:

- `/Users/leoguinan/MetaSPN/metaspn-gates/tests/fixtures/m0_state_machine_config.json`

## M1 Required Keys

For the M1 routing progression (`SEEN -> OBSERVED -> PROFILED -> QUALIFIED -> ROUTED`) the minimum keys are:

- `entity_state.state`: one of `SEEN`, `OBSERVED`, `PROFILED`, `QUALIFIED`
- `entity_state.track`: `M1`
- `entity_state.entity_id`: required for emitted task metadata
- `features.ingestion.resolved_entity_id`: required for `SEEN -> OBSERVED`
- `features.profile.handle`: required for `OBSERVED -> PROFILED`
- `features.profile.confidence`: thresholded for `OBSERVED -> PROFILED`
- `features.social.followers`: required floor for `PROFILED -> QUALIFIED`
- `features.scores.routing_readiness`: required for `PROFILED -> QUALIFIED` and `QUALIFIED -> ROUTED`
- `features.scores.profile_quality`: thresholded for `PROFILED -> QUALIFIED`

M1 reference fixture:

- `/Users/leoguinan/MetaSPN/metaspn-gates/tests/fixtures/m1_routing_state_machine_config.json`

## Release

- GitHub Actions workflow: `/Users/leoguinan/MetaSPN/metaspn-gates/.github/workflows/publish.yml`
- Publish trigger: GitHub Release published (or manual `workflow_dispatch`)
- Publishing method: PyPI Trusted Publishing via `pypa/gh-action-pypi-publish`

### One-time setup

1. In PyPI, create project `metaspn-gates` and configure Trusted Publisher for this GitHub repo/workflow.
2. In GitHub, create environment `pypi` (optional protection rules supported).

### Release flow

1. Bump `/Users/leoguinan/MetaSPN/metaspn-gates/pyproject.toml` version.
2. Tag and push a release commit.
3. Publish a GitHub Release for that tag.
4. `publish.yml` builds and uploads to PyPI.
