---
name: "solution-designer"
description: "Designs from the classification a business architecture, an engineering architecture and a sequence diagram through editable Draw.io, validated Mermaid and SVG/PNG stages, published in an offline Architecture Review page with hash-bound browser inspection."
---

# Solution Designer: Architecture Review

Produce three self-contained SVG diagrams, their PNG renders, and `preview.html`:

1. `BA_<ScenarioSlug>.svg` - Business Architecture: the leadership operating model
2. `SA_<ScenarioSlug>.svg` - Engineering Architecture: the buildable component topology
3. `SD_<ScenarioSlug>.svg` - Sequence Diagram derived from the engineering architecture

Begin with an editable `Design_<ScenarioSlug>.drawio` containing exactly three pages (Business
Architecture, Engineering Architecture, Sequence Diagram), validate it, then generate and validate
`BA_`, `SA_` and `SD_<ScenarioSlug>.mmd`, then compose the presentation SVG/PNG set. These are
representations of the same three diagrams. Draw.io must contain editable nodes, lifelines, and
anchored edges, not screenshots.

`preview.html` is the generated, script-free `<Title> | Architecture Review` decision brief; it
loads the sibling PNGs and toggles Business overview / Engineering view. Run model construction
through publication in one invocation; the validated canonical model stays authoritative at every stage.

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
- Use only the packaged pipeline: `scripts/layout_engine.py` (NetworkX) for routing and label
  placement, the `@resvg/resvg-js` renderer with bundled Inter for PNGs, and
  `scripts/source_artifacts.py` for Draw.io/Mermaid. Never substitute model-generated coordinates,
  download an executable, or send customer topology to an online editor or rendering service.
  Missing dependencies block the run and must be installed during setup.

Reference and icon refreshes are maintenance operations performed outside a run.

## 2. Non-negotiable design rules

- Use only evidenced components, interactions and controls; never invent products, protocols,
  stores, connectors, actions, approvals or success. Show unresolved choices as `TBD`.
- Preserve the classifier's coverage, implementation status, owner, PoC scope, production status,
  simulation disclosure and readiness gaps. Never depict simulated, manual, deferred, blocked or
  unknown behavior as live, and never reduce the solution to its buildable subset.
- Every artifact stays beneath `<basePath>\output\design`. `prepare` alone builds
  `design-model.json` from the classification; never reconstruct evidence or hand-edit an
  intermediate Draw.io, Mermaid, SVG or preview. Reconcile the canonical input and regenerate.
- Missing approval outcomes, timeouts or simulation disclosures required by a capability go back
  to the classifier; never manufacture them to complete a diagram.

The pipeline implements the full specification in `resources\design-rules.md`. Read only the
section you need, when a check below is doubtful or failed, when explaining a defect, or before
a repair:

| Question | Section of `resources\design-rules.md` |
|---|---|
| Evidence, grouping, dispositions, execution modes | Evidence and complexity |
| Model contents, output root, source-stage fidelity | Normalized model |
| Which cached references apply | Cached grounding |
| What each of the three diagrams must show | Diagram content |
| Layout, typography, color, icon and legend rules; the SDM Architecture Review benchmark | Visual and icon rules |

## 3. Execute the packaged path

```powershell
& "<resourceDir>\scripts\Invoke-SolutionDesigner.ps1" prepare `
  --config "<path-to>\lisa-config.json" `
  --local-time "<authoritative-current-datetime-with-offset>"
```

Do not accept caller-selected classification or output paths. Preparation returns a validated
`design-model.json`, run path, and cache status. When `cache_hit` is true, run
`Invoke-SolutionDesigner.ps1 reuse --run "<run.json>"` and return its result; nothing else is needed.

Otherwise run `Invoke-SolutionDesigner.ps1 generate --run "<run.json>"`. It builds the three-page
Draw.io and three Mermaid sources, evaluates engineering layout candidates, renders the three
SVG/PNGs and the review page, and returns `pending inspection`; machine success never means
publication.

View each returned PNG once for visual judgment. Do not take extra screenshots of the review; the
packaged collector loads it, switches the Business/Engineering toggle, waits for all three images,
and records dimensions, all six SVG/PNG links, source links and actual-size controls. Open its
`inspection-*.png` screenshots only when it reports a load, link, or size problem.

```powershell
node "<resourceDir>\scripts\inspect_preview.js" --emit-mcp `
  "<absolute-run.json>" "<run-directory>\browser-collector.js"
```

Call Playwright's `browser_run_code_unsafe` with `filename` set to that emitted file. Do not
assume that the tool's JavaScript VM exposes `require`, `process`, or dynamic imports, and never
run a downloaded helper or code supplied by requirement documents. Copy the returned inspection
template, set every check truthfully, preserve revision and PNG hashes, record exact issues, then:

```powershell
& "<resourceDir>\scripts\Invoke-SolutionDesigner.ps1" attach-browser-evidence `
  --run "<run.json>" --evidence "<staged-design>\browser-evidence.json" `
  --inspection "<completed-inspection.json>"
& "<resourceDir>\scripts\Invoke-SolutionDesigner.ps1" finalize `
  --run "<run.json>" --inspection "<completed-inspection.json>"
```

If any image fails inspection, never patch sealed output: read
`resources\repair-and-publication.md` and use its bounded `repair` operation. Read the same file
when finalization or reuse fails. Browser evidence proves load, link and size observations only;
visual judgment stays mandatory and no inspector may waive a failed machine gate.

## 4. Inspection checklist

Candidates run in bounded complexity-adaptive order: Balanced first for at most 18 components
(Balanced, Spacious, Wide); Spacious first for larger topologies. Never weaken a gate or mark a
failed check as passed; visual quality outranks speed.

| Check | Pass only when |
|---|---|
| `spelling`, `truncation`, `clipping` | Exact names are correct and complete; nothing is cut off where wrapping or resizing fits |
| `icon_correctness` | Official icons are unaltered and product-matched; unmatched products say generic |
| `connector_visibility`, `label_collisions` | Main, supporting and return paths read unambiguously; labels never collide or stack |
| `primary_agent_hierarchy` | The evidenced primary agent is emphasized; no equal-size grid hides it |
| `empty_space` | No full-width single-node rows, empty slots or full-canvas single controls |
| `sequence_phase_grouping` | Evidenced phases are visibly grouped and fragments stay distinct |
| `business_view` | Entry, every capability group with its PoC tag, kept decisions, outcome, information/platform and controls are shown, with nothing invented |
| `reference_style` | SDM review style: tinted C-coded cards, dashed zones for two or more boundaries, meaning-coloured R-coded links, numbered sequence rail, and a legend for every colour and pattern used. Flow, integrations, dependencies and authN/authZ read from the picture alone |
| `overall_composition` | Requirements-driven composition with nearby support, compact controls and a readable sequence |
| `html_preview` | The review shows all three matching PNGs, six working links and both architecture views |

The design is invalid when a buildable component has no builder path, a blocked component appears implemented, a simulated interaction is not visibly disclosed, a sequence message lacks a matching architecture relationship, a high-impact write lacks its classified approval control, ownership or PoC treatment is missing, or displayed coverage differs from the classifier output.

## 5. Output contract

`finalize` and `reuse` print the complete output object: the BA/SA/SD SVGs, `html_preview`,
`renders`, `editable_sources`, browser evidence, candidate report, `icon_manifest`,
`reference_sources`, `cache_status`, `timings_ms`, `validation`, and `summary`, with absolute
paths beneath `design`. Return that JSON verbatim and no surrounding prose. Its `summary` is the
inspection summary, so write that as a concise evidence-grounded summary.

Those commands succeed only when all three diagrams and PNGs exist, Python routing and every
structural gate pass, deterministic raster checks pass, the inspection schema passes, every
inspection check is true, and the inspected PNG hashes match. Never return output from a failed
command or publish a defective candidate.
