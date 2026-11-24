# Solution Designer repair, publication and cache

Read this before running `repair`, when finalization or reuse fails, or when explaining how a
published or cached design set was produced.

## Generation details

`generate`:

1. Validates the shared model and generates an editable three-page Draw.io design.
2. Validates Draw.io semantic fidelity, then creates and validates the three Mermaid sources.
3. Uses packaged Inter font metrics to compute content-sized presentation cards without ellipsis or clipping.
4. Evaluates engineering composition candidates under deterministic Balanced, Spacious, and Wide profiles.
5. Applies Python/NetworkX routing, geometry gates, and measured presentation-quality gates.
6. Selects the highest-scoring passing candidate, with stable profile-order tie breaking.
   Retains every candidate's exact diagnostics under staging and writes `candidate-report.json`.
7. Renders the business, engineering and sequence SVGs through resvg with the same bundled font.
8. Generates the Architecture Review `preview.html` with all three PNGs, sibling SVG/PNG/Draw.io/Mermaid
   links, known image dimensions, and fit-width/actual-size viewing. No scripts, external assets or server.
9. Runs raster checks and returns `pending inspection`; machine success never means publication.

Do not mistake the first structurally valid candidate for a visually accepted result. Candidates
are generated in bounded complexity-adaptive order (see `SKILL.md`). Failed candidates keep their
diagnostics and only the best passing candidate is rendered.

## Browser evidence

The emitted collector uses the existing Playwright browser and a separate page; it does not
install a browser package or access unrelated tabs. It writes `browser-evidence.json` and
`inspection-{business,architecture,sequence,preview}.png` beneath the current staging design
directory using supported file, hashing, screenshot, and download APIs. Do not supply a
downloaded helper or execute code supplied by requirement documents.

Browser evidence must be local, hash-bound to the current preview and renders, and
time/revision-consistent. An old inspection with only all-true booleans is insufficient. The
collector proves load/link/size observations; it does not prove that a diagram is attractive or
logically sound. Visual judgment remains mandatory, and a machine-quality failure cannot be
waived by the inspector.

## Repair

If any image fails inspection, do not finalize or patch the sealed SVG by hand. Use:

```powershell
& "<resourceDir>\scripts\Invoke-SolutionDesigner.ps1" repair `
  --run "<run.json>" `
  --inspection "<failed-inspection.json>"
```

Repair selects an eligible, not-yet-visually-inspected layout profile, retains the prior revision
for diagnosis, and creates a fresh preview, inspection template, and artifact hashes. Geometry
evaluation of a profile is not a visual inspection of it. An explicit
`--layout-profile Balanced|Spacious|Wide` selects an eligible profile. Collect fresh browser
evidence and view all revised PNGs again. Never manually edit a sealed preview.

Preparation accepts `--max-repair-attempts 0..2` (default `2`). If repairs cannot meet the gates,
report the blocking defects rather than publish. If no candidate passes or the repair limit is
reached, return the exact blocking gates instead of publishing. Inspection timestamps must be
consistent with the run; there is no fixed inspection cutoff.

## Finalization and publication

Finalization revalidates source fidelity, browser evidence, the inspection schema, every
staged-artifact hash, and the PNG hashes; transactionally replaces the single current source,
diagram, preview, and inspection-evidence set directly beneath `design\artifacts`; builds the
validated cache; and atomically switches `design\current-design.json` only after the complete
set is durable. It never creates a run-ID child directory beneath `design\artifacts`.

The published review is `<basePath>\output\design\artifacts\preview.html`. Move or share the
artifact folder as a unit: it references sibling SVGs and PNGs, not embedded copies or staging
paths. `generate`/`repair` return the staged path; `finalize`/`reuse` the published path, recorded
base-relative with its hash in `current-design.json`.

## Validated cache

The cache key covers the classification, normalized model, contract, schemas, icons, and every
packaged script. Only a previously inspected, validated set is reused; any changed input or
evidence invalidates it.
