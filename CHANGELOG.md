# Changelog

All notable changes to Spore will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
