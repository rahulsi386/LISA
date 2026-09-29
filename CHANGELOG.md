# Changelog

User-visible changes are recorded here. Unreleased entries are not a published release.

## Unreleased

### Added

- MIT license for original LISA code, with Rahul Prashant Singh as copyright holder.
- Repository ownership, contribution, security-reporting, support, and release policies.
- Documented existing code ownership and administrator guidance for protected branches and private reporting.
- Windows CI and a matching local runner for plugin tests, Scout shared-infrastructure checks,
  and the synthetic GEPA engine test. CI performs no tenant operations.

### Changed

- **Breaking:** Complexity Classifier 3.0 uses classification model schema 4.0. Models now need four new sections:
  - a research plan seeded from the analysis;
  - a register of every consulted source, which records all four MCP servers (`ms-learn-mcp`, `azure-mcp`, `ms-eng-hub-mcp`, `ms-icm-mcp`) and requires official vendor sources for non-Microsoft products;
  - an agentic-suitability decision (agentic, hybrid, or deterministic);
  - a five-row platform comparison.

  Platform selection follows Microsoft Cowork, then Copilot Studio, then Azure AI Foundry, then Microsoft Agent Framework. Cowork must always be assessed. A `Deterministic (no agent)` result ends the lifecycle after classification. Microsoft-internal sources are kept out of customer-facing text. Customer documents now include the suitability section and the comparison table.
- The plugin distribution now lives in `github-copilot/`. Installation commands, CI, test runners,
  and documentation use the new folder and GitHub subdirectory source `rahulsi386/LISA:github-copilot`.
  Existing installations referencing the previous location must be reinstalled from the new source.

### Fixed

- Plugin artifact test fixtures now include a validated analysis handoff and the standalone video contract.
- Offline classifier tests use a test-only reference clock instead of expiring with the wall clock;
  fresh and expired reference behavior is covered explicitly.

### Unchanged

- Runtime checkpoint enforcement, cloud permissions, executable dependency versions, and draft
  certification are unchanged. Live agent behavior and publication still require authorized manual validation.