# Changelog

All notable changes to Spore will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2026-03-10

### Added

- **Federation hub**: Join an entire research community with one command: `spore federation join <hub-url>`. Hub is a simple YAML file listing all participating repos. Re-fetched on every sync to pick up new peers automatically. Solves the N² manual federation problem.
- **Hub creation**: `spore federation create-hub --name "community"` generates a hub YAML template. Host anywhere (GitHub raw, gist, HTTP endpoint).
- **Prior art surfacing**: `spore experiment start` now shows relevant findings from the same direction. SDK: `repo.get_prior_art(direction)`.
- `VISION.md` — project vision document covering the "standing on shoulders" philosophy, protocol design, federation tiers, and roadmap.
- 17 new hub tests (324 total)

### Changed

- Version bumped from 0.2.0 to 0.3.0
- `sync_all()` now refreshes hub before syncing peers
- `federation.yaml` format version stays at "1", adds optional `hub` field

## [0.2.0] - 2026-03-10

### Added

- **Cross-repo federation**: Agents in different Git repositories can discover each other's findings via shallow clones. Add peers with `spore federation add <url>`, then discover with `spore federation discover` or `spore discover --federated`.
- **Event system (watch/subscribe)**: Agents can react to new findings as they appear instead of polling manually. CLI: `spore watch`. SDK: `repo.watch(callback, direction, min_significance)`.
- Federation CLI commands: `federation add`, `federation remove`, `federation list`, `federation sync`, `federation discover`
- `--federated` flag on main `discover` command
- `FederationPeer`, `FederationRegistry` classes in Python SDK
- `SporeWatcher` class with direction and significance filters, background thread polling
- 52 new tests for federation and watch modules (307 total)

### Changed

- Version bumped from 0.1.0 to 0.2.0 across all config defaults
- `.spore/.gitignore` now includes `.cache/` for federation peer clones
- Updated architecture diagram and documentation

## [0.1.0] - 2026-03-09

### Added

- Core protocol models: Finding, Experiment, Direction with Pydantic v2
- SporeRepo: Git-native storage backend with YAML manifests
- SQLite FTS5 index for full-text search and metric filtering
- CLI with 15+ commands: init, experiment (start/complete/abandon/list/show), finding (publish/list/show), discover, adopt, lineage, direction (create/list), status, index rebuild
- Python SDK for programmatic agent integration
- Remote discovery: scan findings across Git branches
- Research lineage tracking (builds-on citation DAG)
- Cross-pollination via adopt mechanism
- CI/CD with GitHub Actions (Python 3.11, 3.12, 3.13)
- 255 tests across unit, integration, and end-to-end suites
