---
name: "complexity-classifier"
description: "Researches with Microsoft MCP servers and official vendor sources, decides agentic versus deterministic suitability, selects the platform by Cowork, Copilot Studio, Foundry, Agent Framework precedence, designs the solution and scores complexity and allowed-tool coverage."
---

# Complexity Classifier

Act as a senior Microsoft AI agent architect: design the complete customer solution, including
unsupported dependencies, then distinguish intrinsic complexity from business-weighted build and
demonstration coverage. Never hide a missing capability to make the allowed tools appear sufficient.

## Mandatory boundaries

- Allowed implementation tools: Microsoft Copilot Studio, Microsoft 365 Copilot Chat, Microsoft
  Cowork, and Microsoft Teams. Other required products/services remain explicit architecture
  dependencies, never team-buildable coverage. Prefer the missing capability over prescribing an
  out-of-bound product when several implementations could satisfy it.
- Read `..\Platform-Decision.md` by section, not in full: its gates, work types, action impact,
  state distinctions, hybrid patterns, evidence rules, category scoring and PoC acceptance rules
  are mandatory.

  | When | Sections |
  |---|---|
  | Every run | Team PoC/MVP Delivery Profile through Phase 5 (including the Evidence Register); Hybrid Architecture Patterns; Control Requirements for Agentic Actions; State, Memory, and Evidence; Evaluation and Operational Readiness; Final Golden Rules; and the Copilot Chat, Standard, GitHub Copilot, and Microsoft Cowork platform guidance |
  | Stage 2 or 3 research only | Microsoft Foundry Prompt Agents, Microsoft Foundry Hosted Agents, Microsoft Agent Framework |
  | Only when a decision needs it | Common Anti-Patterns, Architecture Decision Record Template, Authoritative References |
- Classify every in-scope finding: Required, Confirmed, Current, Preferred and Near-term. Do not
  inflate required scope with Future, Potential, Optional, Explicitly excluded, Not evidenced,
  analyst gaps or prohibited classic Copilot Studio Topics.
- Preserve exact external-system/source names, product/service boundaries, implementation
  methods, owners and evidence IDs. Recommendations require consulted official evidence, not
  fabricated requirement IDs. Keep production-hardening gaps distinct from minimum PoC blockers.
- Require current tenant availability, authentication, least privilege, approved test data, safe
  actions/approvals, honest simulation, auditable demo actions and a viable builder path. Never
  fabricate success, approvals, identifiers or state changes.

Use the packaged runner for preparation, staged refresh, validation, deterministic scoring,
rendering and publication. The model designs the solution; it does not author coverage percentages,
counts or final complexity. Do not reparse source documents or treat prior classification prose as
evidence.

## Prepare and trusted input

```powershell
& "<skill-dir>\scripts\Invoke-ComplexityClassifier.ps1" prepare `
  --config "<path-to>\lisa-config.json" `
  --local-time "<authoritative-current-datetime-with-offset>"
```

There is no `--input` or `--output` override. Configuration determines `<basePath>\output\analysis`
and `<basePath>\output\classification`. The runner selects the newest matching timestamped ledger
and requires its matching `-manifest.json` validated publication marker. It checks source-root
binding, canonical source inventory, exact run/sibling paths, and ledger/Markdown hashes without
rereading requirement documents. An unvalidated newest analysis fails; never silently use an older
one. The handoff is fingerprinted in the run/cache and rechecked before run use and publication.

When invoked by `cad-orchestrator`, follow `..\workflow-checkpointing.md`. Start `classification`
after preparation returns its run ID; checkpoint refresh, each research assessment, model completion
and publication. Commit the classification manifest only after Markdown and JSON validate.

## Model-facing read and completion plan

Preparation returns `model_context`, `evidence_overview`, `evidence_index`, `reference_index`,
`completion_contract`, authoritative `evidence_summary`, `references` and `model_draft` paths.
Paths inside `model-context.json` are run-directory-relative unless absolute.

1. Read the compact `model_context` and `resources\completion-contract.json`.
2. Read the evidence overview and its first index page. Follow every `next_page` link through the
   empty terminator, reading **every** listed batch. `evidence_index` is the complete machine audit
   index; its full contents need not be loaded when using the bounded navigation pages.
3. Reassemble fragments with the same `record_id` in `part` order until `final_part=true`, then parse
   their concatenated text as JSON. Complete findings include all original attributes and long
   statements/provenance; no truncation or first-N sampling. `in_scope` in wrapper provenance
   distinguishes required implementation from contextual exclusions/gaps. Configuration and
   evidenced-channel records also use bounded batches so a large source configuration does not
   inflate the context header.
4. Read the relevant detailed sections listed below and the staged official documentation. The
   reference index contains IDs, URLs, stage, availability and on-demand local excerpt paths.
   Titles and stripped/truncated excerpts are **locators, never capability evidence**. Consult
   applicable complete official sections and record consulted reference IDs in requirement
   assessments, gates, product scores, components and topology. Retrieval is not permission to
   infer capability from a title. Do not skip required or applicable staged research.
5. Load the generated draft programmatically and edit targeted fields. Use schema slices or an
   empty example of a field shape rather than printing the populated draft into context.
   Preserve deterministic metadata and unaffected structures; provisional product choices,
   defaults and unknown capabilities still require assessment. Do not read the full authoritative
   ledger **plus** its duplicated summary **plus** the populated draft. Retrieve specific JSON
   pointers from those on-disk artifacts only when needed.
6. Complete exactly one researched assessment per in-scope finding and atomic capabilities
   covering every finding. Reconcile **all** scope, conflicts, dependencies, business weights,
   gates/products, channels/triggers, ownership/build boundaries, inventory/topology/sequences and
   readiness gaps—even if only one finding changed. Delta-only publication is prohibited.

Each serialized evidence batch is at most 16,384 UTF-8 bytes, including metadata. Oversized content
splits losslessly with provenance. Small inputs may remain one batch. Full authoritative artifacts
remain on disk; batch/index/context hashes and complete per-ID coverage are machine-validated.

### Applicable detailed references

Read sections of `resources\design-guidance.md` as follows; do not load the entire document merely
because it is available:

| When | Required sections |
|---|---|
| Every non-cache architecture | Research plan, sources, suitability, and precedence; Required delivery assessment; In-scope evidence; AI agent architect responsibility; Required component inventory; Architecture-ready solution topology; Mandatory baseline components |
| Every run's active research | Staged research (Stage 1 always; later stages only after the persisted gap gate) |
| Conversational channels | Channels; Harness selection and solution design |
| Autonomous work | Autonomous triggers |
| Personal delegated work | Cowork selection and solution design, plus the Cowork rules in Staged research and Mandatory baseline components |
| Explaining publisher results | Deterministic complexity |

Use `resources\classification-model.schema.json` for exact field shapes. The completion contract is
a focused checklist, not a replacement for applicable safety, product or architecture guidance.

## Research, suitability and precedence

Resolve every `research-plan-seed.json` topic, adding topics until each in-scope finding maps to
one, with cited `research_register` sources (tool, query, locator, retrieval time, finding). Use all
MCP servers and record each in `mcp_usage`; a failing server is `unavailable` with its detail:

| Server | Use for |
|---|---|
| `ms-learn-mcp` (mandatory) | Microsoft and allied product documentation, limits, best practices, known issues |
| `azure-mcp` | Azure and Power Platform best practices, architecture references, deployment tooling |
| `ms-eng-hub-mcp` | Microsoft-internal deep engineering guidance |
| `ms-icm-mcp` | Microsoft-internal open incidents and bugs affecting the design |

Non-Microsoft products cite only the vendor's official documentation (`vendor-official`, trust
basis, version/date). Internal sources never appear in customer-facing text.

Decide `agentic_suitability` first (agentic, hybrid or deterministic) across all seven criteria,
with the deterministic alternative and why the other approach was rejected. Deterministic selects
`Deterministic (no agent)`: no agents, no harness. Otherwise apply precedence Microsoft Cowork ->
Copilot Studio -> Azure AI Foundry -> Microsoft Agent Framework: always assess Cowork and select
the first full fit. `platform_comparison` justifies the choice against all five options with fit,
pros, cons, rationale and public sources.

## Staged research

Stage 1 always evaluates the allowed tools and relevant current Copilot Studio, Microsoft 365,
Teams, Cowork, identity, security, governance and ALM documentation. Apply minimum gates before
category ranking. A fully viable requested personal-worker experience selects Cowork; a failed
Cowork blocking gate means block/defer, not silently substitute a shared Copilot Studio application.
Reusable delegated methods require explicit skills; live external access requires plugins.

If Stage 1 fully fits, stop: no Foundry or Agent Framework citations. Custom connectors/MCP/services
can raise complexity while Copilot Studio remains the agent platform.

Only for persisted evidence-linked unmet requirements, expand sequentially:

```powershell
& "<skill-dir>\scripts\Invoke-ComplexityClassifier.ps1" expand-research `
  --run "<run.json>" --stage foundry --assessment "<copilot-stage-assessment.json>"

& "<skill-dir>\scripts\Invoke-ComplexityClassifier.ps1" expand-research `
  --run "<run.json>" --stage agent-framework --assessment "<foundry-stage-assessment.json>"
```

Assessments must be in the run directory and match its run ID/stage. Foundry can carry forward only
Copilot-stage gaps; Agent Framework requires remaining Foundry gaps. Read the refreshed model
context/reference index and applicable new documentation after expansion. Preserve global
reconciliation; the publisher rejects skipped stages and incomplete per-requirement coverage.

## Architecture and publication

Build a complete, grounded canonical topology with exact products, inventory mapping, hosting,
deployable/configurable/external boundaries, roles/owners, reliability/scalability/security,
typed relationships, trust controls, Development/Test/Production promotion, and five quality
decisions. Include users/channels/agents, tools/services/data, identity, governance, monitoring and
ALM plus applicable triggers, integrations, human approvals and external systems.

Sequences must derive from relationships and cover applicable auth, request/trigger, orchestration,
grounding, calls, decisions, errors and responses. Maximum eight lifelines and 30 interactions;
relationship labels <=42 characters, actions <=56, conditions <=34. Ordinary loops and asynchronous
responses are legitimate: do not invent blanket acyclicity or Authentication/Response phase ordering.

```powershell
& "<skill-dir>\scripts\Invoke-ComplexityClassifier.ps1" publish `
  --run "<run.json>" --model "<completed-model-in-run-directory.json>"
```

Publication validates upstream/resource/context integrity, every in-scope ID, staged research,
gates, weighted capabilities, exact products, topology/inventory/sequence integrity, schemas,
Markdown/JSON consistency and output containment. It emits:

- `complexity-classification_<timestamp>.md`
- `complexity-classification_<timestamp>.json`
- `classification-manifest.json`

## Verified reuse and measurements

Only `classification_cache_hit: true` permits publishing the returned reused model without repeating
model completion; candidates are re-scored against current evidence and architecture checks.
Semantic reuse ignores **only the ledger's top-level `run_id`**. The key also covers the configured
root, source identity, configuration, references, schemas, contracts, helpers, instructions, rules
and templates; each run still binds exact current ledger, Markdown and manifest hashes.

`classification_cache_decision` explains reuse or refusal. Models naming old upstream artifacts,
analyzer run IDs or changed hashes are not rewritten: complete the current model. Output paths and
hashes always come from the current run. `input_size_counters` reports measured UTF-8 bytes, not
token estimates or promised savings.

Return concise suitability, complexity/platform/stage, tier/harness, counts, channels/triggers, topology counts,
published paths, cache status and duration.
