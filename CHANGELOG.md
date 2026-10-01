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

- **Breaking:** Agent Builder is now programmatic first. The new
  `resources/automation-precedence.md` defines the rules, and every build path follows them:
  - Every Copilot Studio operation starts with the latest PAC CLI:
    - `init --environment` bootstrap, including `--authoring-mode cli-copilot`;
    - `clone`, `push`, `pull`, `publish`, `status`;
    - `pac solution`, `pac connector`, and `pac copilot-studio download-agent-channel-manifest`.
  - Knowledge files, flows, connection references, topics, tools, triggers, skills, workflows, and
    connected agents are pushed from the sync workspace instead of being added in the browser.
  - The browser is a per-operation last resort. Each use needs a recorded PAC attempt, a
    justification, and `pac copilot pull` reconciliation.
  - Cowork skills and plugins are generated as Microsoft 365 app packages (`manifest.json` v1.28)
    and packaged and installed with `atk`. Preferences, sharing, and admin-center distribution
    may use the browser directly.
  - `agent-build-handoff.json` now requires `automationToolchain` and `automationLedger`.
    It also accepts `artifacts.coworkPackages`.
  - The validator rejects:
    - a PAC CLI older than the recorded latest version;
    - browser or programmatic Copilot Studio steps with no PAC attempt;
    - fallbacks with no justification;
    - built components with no ledger entry;
    - Cowork packages whose hash doesn't match.
  - Both builder CLI entry points now run the builder-local checks.
- **Breaking:** Solution Designer 5.0 publishes three diagrams:
  - `BA_<slug>`: business architecture. This is a leadership operating model derived from the classified capabilities, their PoC treatments, human decisions, information, platform and controls.
  - `SA_<slug>`: engineering architecture.
  - `SD_<slug>`: sequence diagram.

  They are delivered through a three-page Draw.io file, three Mermaid sources, and an offline `<Title> | Architecture Review` page.

  The review page follows the SDM Intelligent Operations review style. It has a decision brief, delivery path, Business/Engineering view toggle, sequence narrative, readiness gates, a platform decision and comparison, and component/capability reference tables.

  The design model now requires `businessArchitecture` and carries the classifier `decision`. Inspection binds the business PNG and a `business_view` check. Customer artifacts include `solution-business-architecture.png`.

  All three diagrams share one visual system, `renderer/style.js`, benchmarked against the SDM Intelligent Operations Architecture Review instead of the procurement reference:
  - tinted responsibility cards with accent bars, `C01` codes and treatment tags;
  - dashed deployment-boundary zones, preferred whenever a design spans two or more boundaries;
  - meaning-coloured links (evidence, request/response, governed action, identity/access, control/audit) with `R01` codes and a relationship index on the review page;
  - a numbered sequence rail with compact lane headers and green/red/amber branch bands;
  - a full-width cross-cutting control band.

  A new `style-conformance` gate, a zone-containment check in `Test-Diagrams.ps1`, and a `reference_style` inspection check enforce it. The editable Draw.io and Mermaid sources use the same palette.

  The designer `SKILL.md` is reduced from about 28 KB to about 11 KB. The full diagram specification and the repair/publication detail moved verbatim to `resources/design-rules.md` and `resources/repair-and-publication.md`, which are read only when needed. Runtime behavior, outputs, and cache keys are unchanged.
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