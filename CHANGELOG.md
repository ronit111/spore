# Changelog

All notable changes to Spore will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-03-10

### Added

- **Earned significance**: Findings accumulate significance through adoption. When agents build on a finding, its earned significance grows logarithmically (`min(1.0, self_reported + 0.1 * log2(1 + adoption_count))`). New findings fall back to self-reported significance. Discovery results now sort by earned significance.
- `compute_earned_significance()` function exported from SDK
- `SporeIndex.get_adoption_count()` and `SporeIndex.get_earned_significance()` methods
- `SporeRepo.get_finding_significance()` convenience method returning self-reported, adoption count, and earned significance
- CLI `discover` shows earned significance and adoption count columns
- CLI `finding show` displays earned significance with adoption breakdown
- Prior art display shows earned significance

### Changed

- 30 new earned significance tests (354 total)
- Version bumped from 0.3.0 to 0.4.0
- Discovery results (`search()`, `discover()`) now include `earned_significance` and `adoption_count` fields
- Results sorted by earned significance instead of raw self-reported significance
- VISION.md updated: earned significance moved from roadmap to documented feature, MCP server removed from roadmap (CLI is already agent-friendly)

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
