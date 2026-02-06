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
- If `metaspn_schemas` is unavailable, it falls back to JSON parsing only.
- Current dependency target: `metaspn-schemas==0.1.0`.
- `apply_decisions(..., use_schema_envelopes=True)` attaches schema-shaped payloads when `entity_state.entity_id` is present.

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
