---
name: "solution-designer"
description: "Builds exactly two evidence-grounded diagrams through editable Draw.io, validated Mermaid, and presentation-ready SVG/PNG stages, with ranked composition candidates, offline preview, and hash-bound browser inspection."
---

# Solution Designer: Draw.io to Presentation

Produce exactly two self-contained SVG diagrams, their PNG renders, and `preview.html`:

1. `SA_<ScenarioSlug>.svg` - requirements-driven Solution Architecture
2. `SD_<ScenarioSlug>.svg` - Sequence Diagram derived from the architecture

Begin with an editable `Design_<ScenarioSlug>.drawio` containing exactly two pages (Solution
Architecture and Sequence Diagram), validate it, then generate and validate
`SA_<ScenarioSlug>.mmd` and `SD_<ScenarioSlug>.mmd`, then compose the presentation SVG/PNG pair.
These are representations of the same two diagrams, not additional semantic diagrams.
Draw.io must contain editable nodes, lifelines, and anchored edges, not screenshots.

The HTML preview displays the two diagrams as separate images; it is not a third diagram or a
combined canvas. Complete model construction, Draw.io review, Mermaid review, candidate
composition, validation, rendering, preview generation, inspection, and publication in one
invocation. This is a staged design workflow, not lossy Draw.io-to-Mermaid-to-SVG parsing:
the validated canonical model remains authoritative at every stage.

When invoked by `cad-orchestrator`, follow `..\workflow-checkpointing.md`. Start the `design`
stage after `prepare` returns its run ID; checkpoint prepare, source generation, candidate generation, inspection, and
finalize. Commit `current-design.json` only after its hashes and validation status pass.

The packaged `resources\artifact-contract.json` is validated against the shared `artifact-contract.schema.json` before execution and is the authority for the lowercase `design` output root and artifact naming.

## 1. Offline determinism rules

- Do not browse the web, download icon packs, install dependencies, or search for product assets during a run.
- Use `resources/reference-manifest.json` for cached Microsoft guidance and exact source URLs.
- Use `resources/icon-manifest.json` and `resources/icons/` for packaged official icons.
- If an evidenced product has no cached verified icon, use `generic-component` and label it as generic. Never substitute another product icon.
- Resolve products through the packaged canonical alias registry, not broad substring guesses. In particular, Microsoft 365 Copilot is not Agent 365. Show the registered product caption when a custom canonical component name does not already identify its product.
- Read only the latest direct child `<basePath>\output\classification\complexity-classification_<timestamp>.json`, resolved through `lisa-config.json`. Do not reread the full requirements corpus.
- Use the packaged `scripts/layout_engine.py` with the installed NetworkX dependency for obstacle-aware rectilinear routing and collision-free label placement. Do not substitute model-generated coordinates or download an executable. Missing dependencies block the run and must be installed during setup.
- Use the packaged `@resvg/resvg-js` renderer and bundled Inter font for deterministic, browser-free PNG generation.
- Generate editable sources locally with `scripts/source_artifacts.py`. No Draw.io cloud service,
  Mermaid CDN, online editor, or added renderer dependency is required. Do not send customer
  topology to an external rendering service.

Reference and icon refreshes are maintenance operations performed outside a run.

## 2. Evidence and complexity

Use only evidenced goals, actors, channels, knowledge, data, tools, integrations, security controls, agent behavior, and human handoffs. Show the complete required solution, including components outside the team's allowed-tool boundary. Do not invent products, protocols, stores, connectors, or actions. Show unresolved choices as `TBD`.

Preserve the classifier's capability coverage, implementation status, build owner, PoC scope, production status, simulation disclosure, and production-readiness gaps. Never reduce the customer solution to only the buildable subset or depict simulated, manual, deferred, blocked, or unknown behavior as live implementation.

- Low: retrieval and informational behavior only.
- Medium: evidenced standard tools, agent flows, actions, or connected agents.
- High: evidenced custom integration, pro-code services, gateways, or multi-agent behavior.

When `solution_topology` is present in the classification, consume its canonical component IDs, exact names, deployment boundaries, relationships, and ordered sequence flows directly. Do not regroup, rename, shorten, or infer replacements for topology components.

Keep deployment state, build ownership, sample-data use, and interaction execution mode
distinct. A built runtime using sample records is not automatically a simulated runtime.
Resolve each sequence interaction to its directed architecture relationship and preserve its
execution mode. Contradictions are blocking errors, not opportunities to default to `real`.
Do not treat a self-step as an external tool call or persistent-store write.

Consume optional `presentation` hints and trust boundaries when supplied. Hints influence
reading order and composition only; they cannot authorize omission, renaming, or invented
connections. Missing approval outcomes, timeouts, or simulated-execution disclosures required
by a capability must be returned to the classifier for an explicit sequence contract. Never
manufacture approval or production success to complete a diagram.

Prefer grouping over omission only for legacy classifications that do not contain `solution_topology`:

- Maximum 30 architecture nodes.
- Maximum 60 architecture relationships.
- Maximum 8 sequence lifelines.
- Maximum 30 sequence messages.
- Group equivalent knowledge sources or external systems only into accurately named cards that visibly list every member; do not turn semantic layers into mandatory enclosing panels.

## 3. Normalize once

Resolve the output root only from `lisa-config.json`. Create and use:

```text
<basePath>\output\
  design\
```

Every artifact generated by this skill must remain beneath `<basePath>\output\design`. This includes `design-model.json`, SVGs, PNGs, `preview.html`, diagram/validation/render/run reports, inspection notes, browser profiles, repair artifacts, and diagnostics. Nothing except the `design` directory itself may be created directly under `<basePath>\output`.

The packaged `prepare` command creates a design model directly from the validated classification JSON and validates it against `resources/design-model.schema.json`. For current classifications it projects `solution_topology` without architectural inference. Do not manually reconstruct classification evidence.

The model is the single source for both diagrams:

- Canonical component IDs, labels, status, layers, and icon keys.
- Architecture relationships.
- Sequence participants and messages.
- Applicable cached reference keys.
- Deployment/trust boundaries, exact inventory mappings, and presentation hints when present.

Every sequence participant must map to an architecture component. Use identical names and icon keys in both diagrams.

The source stage validates visible Draw.io labels and connections, Mermaid statements, exact
directed multi-edge/message coverage, and content hashes. Editing an intermediate source does
not silently override `design-model.json`; reconcile the canonical input and regenerate all
representations. `source-report.json` records Draw.io validation before Mermaid validation.

## 4. Cached grounding

Select only relevant entries from `resources/reference-manifest.json`:

- Always select architecture diagramming guidance.
- Select Copilot Studio core and harness guidance only for Copilot Studio solutions.
- Select knowledge, tools, flows, connected-agent, authentication, analytics, and ALM guidance only when evidenced.
- Select Microsoft 365 Copilot declarative-agent guidance only for that channel or harness.
- Select Microsoft Foundry Agent Service guidance only for pro-code or Azure-hosted solutions.
- Select Purview, Power Platform data policy, and managed-environment guidance only when those controls are evidenced.

Copy the selected manifest URLs into `reference_sources`. A stale cache is reported as `packaged-stale`; it does not trigger network access during the run.

## 5. Diagram content

### Solution Architecture

Classify components using these semantic layers. Layers describe responsibility; they do **not** prescribe visible containers, columns, or a fixed number of stages:

1. Users and requesters.
2. Conversation channels.
3. Agent platform, instructions, orchestration, knowledge, tools, connected agents, and human review.
4. Data, automation, connectors, and external systems.
5. Identity, security, and governance.
6. Monitoring and lifecycle.

Preserve distinct user and channel components and the evidenced `User → Channel → Agent` connections. Do not collapse them into a generic access box. Do not invent a conversational channel for an autonomous or integration-only scenario.

Compose the architecture from the actual relationship graph. Find an evidenced requester or trigger path into the primary agent, then follow the main action path toward its business outcome. Alternate channels with identical dependencies may sit together without a surrounding frame; every channel remains an individually named node. Place connected supporting services near the components they serve, keep supporting chains in dependency order, and retain disconnected requirements without inventing connections. Cycles, return paths, parallel services, additional agents, and cross-cutting controls must remain visible where evidenced.

The procurement reference is a **visual-quality benchmark, not a topology template**. A retrieval assistant, approval workflow, autonomous integration, and multi-agent solution should have different compositions. The renderer derives stage count, row count, card positions, and canvas dimensions from the requirements and measured content. Do not mandate four stages, a central platform panel, a right-hand data panel, or empty placeholder regions.

Use one node per deployable, configurable, or externally owned component. Keep orchestration and instructions as text inside the agent node rather than separate product nodes. Label directional dependencies with their evidenced purpose.

Do not group canonical `solution_topology` components. When a legacy classification forces grouping, visibly list every exact component name inside the grouped card. A count-only label such as “3 tools,” “data sources,” or “integration endpoints” is invalid unless all member names are also rendered.

The architecture must visibly name:

- Every supported channel.
- Every tool and its service/workflow/API/MCP implementation name.
- Every data source and storage component.
- Every automation and autonomous trigger.
- Every integration endpoint.
- AuthN and AuthZ platform/tool names.
- Security and governance tool names.
- Every ALM component.
- The team-buildable PoC boundary, allowed-tool boundary, customer or external dependency boundary, and deferred production capability where applicable.
- Each component's build, configure, simulate, manual, deferred, or blocked status through the packaged visual treatment and legend.

### Sequence Diagram

Use architecture component IDs as lifelines. Show only evidenced interactions:

- Authentication and authorization.
- Generative orchestration as an agent self-step.
- Knowledge grounding, tool calls, flows, AI Builder, or connected-agent delegation.
- Human approval for binding or regulated decisions.
- Final response.

The primary sequence must preserve each interaction's real, simulated, manual, deferred, or blocked mode. Visibly prefix simulated actions with `Simulated:` and state when data was not transmitted to an external system. Include applicable failure, insufficient-grounding, rejection, timeout, and simulation branches only when they exist in the classifier sequence contract.

Time flows top-to-bottom. Solid arrows are calls/actions; dashed arrows are responses. Use numbered messages and activation bars. Use fragments only when represented in the normalized model.

## 6. Visual and icon rules

- Use the packaged professional-light presentation system: pale neutral canvas, white cards, restrained blue/teal accents, subtle shadows, and consistent spacing. Do not add decorative gradients or large background illustrations.
- Use a 36 px page title, 19-23 px architecture component names, 16 px sequence participant names, 14 px body text, and at least 11 px metadata. Never shrink text to force content into a fixed box.
- Measure wrapping and placement with the bundled Inter font through resvg. Derive descriptions, badges, metadata, and card height from actual preceding text bounds, not character-count estimates or fixed multiline offsets.
- Keep SVGs self-contained with embedded icons and the bundled font; PNG rendering must use that same font without system-font substitution.
- Blue for normal flow, green for approval/success, cyan dashed for simulation, amber dashed for manual work, gray dashed for deferred scope, and red for blocked or evidenced failure.
- Visual quality is not negotiable for speed. A diagram that is structurally valid but visually generic, sparse, crowded, or difficult to follow fails.
- Use an open canvas with a clearly emphasized primary agent, a numbered main flow, nearby supporting services, compact controls, and a concise architectural statement. Numbered headings identify reading order, not mandatory product/layer slots. Keep each dependency direction and implementation mode unchanged.
- Separate semantic classification from visual geometry. The packaged renderer uses nonvisual `semantic-layer` metadata to retain layer identity and bounds without painting layer panels. Ownership, PoC scope, production gaps, and boundary descriptions remain visible on the relevant components; a semantic layer is not a deployment or trust boundary.
- Size cards to their content. Never stretch a single component across an entire layer merely to fill the canvas.
- Render governance and lifecycle as compact cross-cutting cards with a shared heading, not boxed layer panels or ordinary process steps. Cap individual card widths; a single control must never become a full-canvas card.
- Keep status, ownership, PoC scope, and readiness in a quiet, measured footer within each card rather than letting implementation badges dominate the architecture. Preserve every exact name and grouped member.
- Prefer one concise responsibility per card; remove redundant repetition of a product/runtime
  rather than truncating names or hiding required scope. Preserve full evidence in the model and
  accessible descriptions. Deployment, ownership, and execution-mode disclosures remain visible.
- Keep alternate channels beside the main experience where their dependencies permit, and keep
  autonomous triggers distinct from conversational entry. Supporting services must not become
  an arbitrary bottom-row inventory simply because they are not on the selected main path.
- Represent every governance/lifecycle relationship visibly, using routed edges or compact
  named scope annotations with exact endpoint coverage. A cross-cutting card alone is not proof
  that all its relationships have been drawn.
- `Balanced`, `Spacious`, and `Wide` adjust available space and route clearance, not the solution topology. Nominal width may grow by up to 25% to accommodate measured connector labels before a main path wraps into numbered continuation rows. Canvas sizing also considers supporting-service density and control count, so a short main path cannot force a large hub into a narrow poster. Report the selected spine and composition in `diagram-manifest.json` for inspection.
- Keep connector labels horizontal, close to the edge they describe, and clear of every route, heading, card, and other label. Reserve separate lanes for parallel and returning flows. Arrow tips must meet their intended node boundaries, not section borders or nearby icons.
- Compare genuinely different compositions within bounded candidates, not only spacing changes.
  Rank candidates by measured presentation quality after structural gates. Routing quality must
  account for crossings, shared lanes, direction ambiguity, bends, and detours across the whole
  graph. Document numerical scores and blocking reasons in candidate diagnostics; no all-true
  subjective assertion can override a failed machine gate.
- Use fixed-size arrowheads independent of line stroke width. Match arrowhead color to the actual interaction mode.
- Preserve bidirectional relationships with two correctly oriented arrowheads, or an explicit
  two-way scope annotation for controls, consistently across Draw.io, Mermaid, SVG, and PNG.
- Sequence diagrams must use participant-type color accents and named phase bands such as authentication, analysis, human decision, monitoring, and response when the evidence supports them.
- Reserve dedicated vertical space for phase and fragment headings. Size message rows from measured multiline labels and self-call loops. Contiguous messages explicitly sharing a fragment belong inside the same fragment boundary.
- Fragment borders, phase labels, activation bars, messages, and lifelines must remain visually distinct. A self-call on the rightmost participant must turn inward rather than leave the canvas.
- Do not crop, rotate, recolor, distort, or reshape official Microsoft icons.
- Place product names beside icons.
- Both diagrams require a legend distinguishing verified Microsoft icons from generic style and explaining line semantics.

## 7. Execute the packaged path

Run:

```powershell
& "<resourceDir>\scripts\Invoke-SolutionDesigner.ps1" prepare `
  --config "<path-to>\lisa-config.json" `
  --local-time "<authoritative-current-datetime-with-offset>"`
```

Do not accept caller-selected classification or output paths.

Preparation returns a validated `design-model.json`, run path, and cache status.

### Validated cache hit

When `cache_hit` is true:

```powershell
& "<resourceDir>\scripts\Invoke-SolutionDesigner.ps1" reuse --run "<run.json>"
```

The cache key includes the classification, normalized model, artifact contract, schemas,
manifests, every packaged icon, source exporter, renderer/preview/generator/validator scripts,
inspection collector, and orchestrator. Only a previously inspected, validated source, diagram,
preview, and evidence set can be reused. Missing or changed sources, preview bytes, or inspection
evidence invalidate the cache just like changed diagram bytes.

### Cache miss

Generate staged artifacts:

```powershell
& "<resourceDir>\scripts\Invoke-SolutionDesigner.ps1" generate --run "<run.json>"
```

The command:

1. Validates the shared model and generates an editable two-page Draw.io design.
2. Validates Draw.io semantic fidelity, then creates and validates the two Mermaid sources.
3. Uses packaged Inter font metrics to compute content-sized presentation cards without ellipsis or clipping.
4. Evaluates composition candidates under deterministic Balanced, Spacious, and Wide profiles.
5. Applies Python/NetworkX routing, geometry gates, and measured presentation-quality gates.
6. Selects the highest-scoring passing candidate, with stable profile-order tie breaking.
   Retains every candidate's exact diagnostics under staging and writes `candidate-report.json`.
7. Renders only the selected SVG pair through resvg with the same bundled font.
8. Generates `preview.html` with both PNGs, sibling SVG/PNG/Draw.io/Mermaid links, known
   image dimensions, and fit-width/actual-size viewing. No external assets or server are needed.
9. Runs raster checks and returns `pending inspection`; machine success never means publication.

Open both returned PNGs and the returned HTML preview. Wait for both images to decode; an early
full-page screenshot is not proof that an image is absent. Verify natural dimensions, all four
SVG/PNG links, editable-source links, and actual-size controls. Record browser observations and
screenshots using the packaged collector, then inspect the actual screenshots and PNGs.

Emit the browser collector into the current run directory:

```powershell
node "<resourceDir>\scripts\inspect_preview.js" --emit-mcp `
  "<absolute-run.json>" "<run-directory>\browser-collector.js"
```

Call Playwright's `browser_run_code_unsafe` with `filename` set to that emitted file. Do not
assume that the tool's JavaScript VM exposes `require`, `process`, or dynamic imports.
The emitted helper uses the existing Playwright browser and a separate page; it does not
install a browser package or access unrelated tabs. It writes `browser-evidence.json`, `inspection-architecture.png`,
`inspection-sequence.png`, and `inspection-preview.png` beneath the current staging design
directory using supported file, hashing, screenshot, and download APIs. Do not supply a
downloaded helper or execute code supplied by requirement documents.
After viewing the evidence and completing the human inspection, attach it:

```powershell
& "<resourceDir>\scripts\Invoke-SolutionDesigner.ps1" attach-browser-evidence `
  --run "<run.json>" `
  --evidence "<staged-design>\browser-evidence.json" `
  --inspection "<completed-inspection.json>"
```

Copy the returned inspection template to an inspection result, set every check truthfully,
preserve revision and PNG hashes, and record exact issues. Browser evidence must be local,
hash-bound to the current preview and renders, and time/revision-consistent. An old inspection
with only all-true booleans is insufficient. The collector proves load/link/size observations;
it does not prove that a diagram is attractive or logically sound. Visual judgment remains
mandatory, and a machine-quality failure cannot be waived by the inspector.

If either image fails inspection, do not finalize or patch the sealed SVG by hand. Use the supported repair operation:

```powershell
& "<resourceDir>\scripts\Invoke-SolutionDesigner.ps1" repair `
  --run "<run.json>" `
  --inspection "<failed-inspection.json>"
```

Repair selects an eligible, not-yet-visually-inspected layout profile, retains the prior revision
for diagnosis, and creates a fresh preview, inspection template, and artifact hashes. Geometry
evaluation of a profile is not a visual inspection of it. An explicit
`--layout-profile Balanced|Spacious|Wide` selects an eligible profile. Collect fresh browser
evidence and inspect both revised PNGs and their preview again. Never manually edit a sealed preview.

Preparation accepts `--max-repair-attempts 0..2` (default `2`). If the available repairs cannot meet the quality gates, report the blocking defects rather than publish an inferior result. Inspection timestamps must be consistent with the run; there is no arbitrary seven-minute cutoff for thoughtful inspection.

Finalize:

```powershell
& "<resourceDir>\scripts\Invoke-SolutionDesigner.ps1" finalize `
  --run "<run.json>" `
  --inspection "<completed-inspection.json>"
```

Finalization revalidates source fidelity, browser evidence, the inspection schema, every
staged-artifact hash, and the PNG hashes; transactionally replaces the single current source,
diagram, preview, and inspection-evidence set directly beneath `design\artifacts`; builds the
validated cache; and atomically switches `design\current-design.json` only after the complete
set is durable. It never creates a run-ID child directory beneath `design\artifacts`.

The published preview is `<basePath>\output\design\artifacts\preview.html`. Move or share the artifact folder as a unit: the preview references its sibling SVGs and PNGs rather than embedding duplicate images or absolute staging paths. `generate`/`repair` return its staged path; `finalize`/`reuse` return its published path. `current-design.json` records the base-relative path and the preview's integrity hash.

## 8. Bounded candidate repair and publication

Do not mistake the first structurally valid candidate for a visually accepted result. Use only the bounded, revision-preserving repair workflow.

Within a single invocation:

1. Generate candidates in bounded complexity-adaptive order: Balanced first for at most 18 components
   (Balanced, Spacious, Wide); Spacious first for larger topologies (Spacious, Balanced, Wide).
2. Run every structural and visual geometry gate after each candidate.
3. Discard failed candidates while preserving their exact diagnostics in the run report.
4. Rank passing candidates by measured quality; render only the selected candidate.
5. Run deterministic PNG sanity checks, inspect both renders, and finalize only when every inspection check is true.
6. If rendered inspection fails, record the exact defects and invoke repair while an eligible,
   not-yet-visually-inspected profile and repair attempt remain. Inspect the newly hashed revision.
7. If no candidate passes or the repair limit is reached, do not publish a defective set. Return the exact blocking gates.

Never weaken a gate or mark a failed check as passed. Visual quality outranks speed: withhold publication if bounded repairs cannot produce an acceptable candidate.

The design is invalid when a buildable component has no builder path, a blocked component appears implemented, a simulated interaction is not visibly disclosed, a sequence message lacks a matching architecture relationship, a high-impact write lacks its classified approval control, ownership or PoC treatment is missing, or displayed coverage differs from the classifier output.

Rendered inspection must explicitly reject:

- Equal-size card grids that obscure the primary-agent hierarchy.
- Excessive empty space caused by full-width single-node rows.
- Connector labels that collide, overlap cards, or stack on one lane.
- A sequence diagram with no visual phase grouping when distinct phases are evidenced.
- Truncated names or descriptions that could fit through wrapping or card resizing.

## 9. Output contract

Return one JSON object and no surrounding prose:

```json
{
  "solution_architecture_diagram": "<absolute SA path>",
  "sequence_diagram": "<absolute SD path>",
  "html_preview": "<absolute preview.html path>",
  "renders": {
    "solution_architecture_png": "<absolute path>",
    "sequence_png": "<absolute path>"
  },
  "editable_sources": {
    "drawio": "<absolute two-page Design_<ScenarioSlug>.drawio path>",
    "architecture_mermaid": "<absolute SA_<ScenarioSlug>.mmd path>",
    "sequence_mermaid": "<absolute SD_<ScenarioSlug>.mmd path>",
    "report": "<absolute source-report.json path>"
  },
  "browser_evidence": "<absolute browser-evidence.json path>",
  "candidate_report": "<absolute candidate-report.json path>",
  "inspection_assurance": "Hash-bound browser observations plus recorded human/vision judgment; not browser attestation.",
  "scenario_slug": "<letters, digits, and underscores only>",
  "icon_manifest": [
    {
      "component": "<canonical name>",
      "icon": "<cached file or generic-component.svg>",
      "source": "<source pack or generic>",
      "verified": true
    }
  ],
  "reference_sources": ["<cached Microsoft Learn URL>"],
  "cache_status": "packaged-fresh",
  "timings_ms": {
    "model": 0,
    "generate": 0,
    "validate": 0,
    "render": 0,
    "inspection": 0,
    "total": 0
  },
  "validation": "passed",
  "validation_issues": [],
  "summary": "<concise evidence-grounded summary>"
}
```

Set `validation` to `passed` only when both diagrams and PNGs exist, Python routing and every structural gate pass, deterministic raster checks pass, the inspection schema passes, every inspection check is true, and the inspected PNG hashes match. Never publish a defective candidate.

Every returned path must be beneath `<basePath>\output\design`.
