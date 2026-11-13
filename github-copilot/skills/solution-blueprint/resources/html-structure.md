# Blueprint HTML Structure

Shell = `resources/blueprint-template.html`. Keep its `<head>`, entire `<style>` block and the final
`<script>` IIFE unchanged (only add CSS for new derivation elements, using the same `--cp-*`
variables). Replace content only. Everything inline — no external CSS, JS, fonts or images.

## Fixed element IDs (the template script depends on them)

| ID | Element |
|----|---------|
| `document-status` | `<span class="value">` showing current status |
| `status-select` | `<select>` with exactly: Draft, In review, Approved, Blocked, Archived |
| `update-status` | button — sets status and appends a changelog entry |
| `last-updated` | `<span class="value">` (display format e.g. `Oct 6, 2026`) |
| `open-issues` + `issue-input` + `add-issue` | Open Issues list + add box |
| `technical-decisions` + `decision-input` + `add-decision` | Decisions list + add box |
| `change-log` + `change-input` + `add-change` | append-only Change Log + add box |
| `download-updated` (class `secondary-button`) | "Download updated HTML" — serialises DOM + JSON |
| `blueprint-data` | `<script type="application/json">` — the source of truth |

List items in those three lists use `<div class="change-item"><strong>label</strong><span>text</span></div>`.

## Section order (template order + derivation sections marked ★)

All sections sit inside `<div class="grid">` as `<section class="section [span-4|span-6|span-8]">`.

1. **Hero** (`section.hero` > `.hero-content`): eyebrow "Solution Blueprint Draft", `<h1>` solution
   name, one-line `.summary`, `.pill-row` tags; `aside.meta-panel` rows: Document status (+ status
   editor), Recommended route, ★ Complexity, Confidence (with reason), Last updated.
2. **Blueprint Snapshot** — `.kpi-grid` of 4 `.card` tiles (e.g. in-scope requirements, routes
   evaluated = 7, open questions, complexity / recommended path).
3. **Executive Summary**
4. **First-Draft Recommendation** (`span-8 recommendation`) — primary route, hybrid composition,
   why (cite requirement IDs), MCP-readiness note when relevant.
5. **Questions to Confirm** (`span-4`)
6. **Scenario Overview** — Primary actor / Trigger / Expected outcome (3 `.card`s or meta rows)
7. **Key JTBDs Covered**
8. **Personas / Primary Users** — table (persona, need, volume, channel)
9. **Business Problem and Opportunity**
10. **In-Scope and Out-of-Scope Capabilities**
11. **Requirement Summary**
12. ★ **Requirement Ledger** — table: ID · requirement · classification · source quote/locator ·
    systems. Out-of-scope rows greyed (`.muted`).
13. **Current State / Trigger Context**
14. **Target Experience / Future State**
15. **Core User Journeys** (`.timeline` / `.timeline-item` / `.step`)
16. **Data Sources and Grounding Sources**
17. **Integrations and Dependencies**
18. **Security, Privacy, Compliance, and Governance**
19. ★ **Component Work Types** — table: component · work type · AI needed? · default direction ·
    autonomy/impact level · state store · requirement IDs.
20. **Architecture / Implementation Approach** — ★ layered diagram (Users → Channels → Agent platform
    → Data/automation/connectors/external systems, side rails Identity/security/governance and
    Monitoring/ALM) as inline SVG or CSS boxes; ★ primary-journey sequence (≤8 lifelines, ≤30 steps);
    ★ staged-escalation summary (Stage 1/2/3: meets, gaps, escalate?).
21. **Risks and Mitigations**
22. ★ **Mandatory Gate Results** — table: gate × 7 routes, cells Pass / Fail / Exception / TBD
    (colour with `--cp-success` / `--cp-danger` / `--cp-warning`).
23. **Solution Route Analysis** — `.route-grid` of 7 `.route-card`s: `<h3>` name, `.score`
    "`x/35`" (and "Primary" / "Not viable" / "Over-engineered" label), `.bar` width = total/35 %,
    rationale, Covers: IDs, Cannot cover: IDs.
24. **Route Scoring Rubric** — the 1–5 rubric table + a scores table (route × 7 criteria + total).
25. ★ **Build vs Demonstrate vs Dependency** — three columns (`span-4` each).
26. **Open Issues** (`span-6`, editable)
27. **Key Technical Decisions** (`span-6`, editable; labels Proposed / Decided / Added)
28. **EVALs** — table: eval area · what to measure · target · current status.
29. **Implementation Roadmap** — phases (`.timeline`).
30. **Change Log** — append-only + add box + "Download updated HTML" in `.action-row`.

## `blueprint-data` schema

The authoritative, machine-checkable definition is `resources/blueprint-data.schema.json`
(JSON Schema draft 2020-12). The example below is illustrative.

```json
{
  "name": "", "slug": "", "status": "Draft", "lastUpdated": "YYYY-MM-DD",
  "mode": "standalone|lisa",
  "sourceArtifacts": [{"path": "", "sha256": "", "role": "requirements|classification|ledger|design|diagram"}],
  "confidence": {"level": "Low|Medium|High", "reason": ""},
  "executiveSummary": "", "scenarioOverview": {"primaryActor": "", "trigger": "", "expectedOutcome": ""},
  "jtbd": [], "personas": [{"name": "", "need": "", "volume": "", "channel": ""}],
  "assumptions": [], "questionsToConfirm": [],
  "requirements": [{"id": "FR-01", "idOrigin": "source|derived", "text": "", "classification": "Required",
                    "source": "quote — locator", "systems": []}],
  "components": [{"name": "", "workType": "Knowledge retrieval", "aiNeeded": true, "direction": "",
                  "impact": "read-only|reversible write|irreversible", "stateStore": "", "requirementIds": []}],
  "escalation": [{"stage": 1, "considered": [], "meets": [], "gaps": [], "escalate": false}],
  "complexity": {"rating": "Low|Medium|High", "drivers": []},
  "gates": [{"gate": "Data location & movement", "results": {"Standard harness": "Pass"}, "note": "", "owner": ""}],
  "routes": [{"name": "Standard harness", "gate": "Pass|Fail|Exception|TBD",
              "scores": {"fit": 5, "implementationSpeed": 5, "governance": 5, "extensibility": 4,
                         "integrationReadiness": 5, "userExperience": 5, "operationalComplexity": 5},
              "total": 34, "covers": [], "cannotCover": [], "label": "Primary", "rationale": ""}],
  "recommendedRoute": "", "recommendation": {"primary": "", "hybrid": "", "why": "", "requirementIds": []},
  "buildDemoDependency": {"buildable": [], "demonstrable": [], "dependency": []},
  "architecture": {"users": [], "channels": [], "agentPlatform": {}, "data": [], "identityGovernance": [], "monitoringAlm": []},
  "sequence": [{"from": "", "to": "", "message": ""}],
  "evals": [{"area": "", "measure": "", "target": "", "status": "Not started"}],
  "risks": [{"risk": "", "mitigation": ""}],
  "openIssues": [], "technicalDecisions": [],
  "roadmap": [{"phase": "", "scope": "", "exit": ""}],
  "changeLog": [{"date": "YYYY-MM-DD", "entry": "Initial draft generated from <source>."}]
}
```

`mode` is `"standalone"` (default) or `"lisa"`; Update mode never changes it. `sourceArtifacts`
lists every input the blueprint was built from (file name or URL; `sha256` is optional in
standalone mode — leave `""` if the host cannot hash — and required in LISA mode). A standalone
blueprint must not contain LISA-specific sections, labels or text.

Note: the template's `syncBlueprintData()` rewrites `status`, `lastUpdated`, `changeLog`,
`openIssues` and `technicalDecisions` from the DOM on every edit — keep those as flat
string/obj arrays as shown so the in-browser editor and file-based updates agree. Escape `</` as
`<\/` inside the JSON so it cannot close the script tag.

## Update mechanics (file-based, durable)

1. Read the HTML; parse `blueprint-data` with `json.loads`.
2. Apply the command to the JSON **and** the matching DOM section (append a `.change-item`, change
   `#document-status` text and the `selected` option, set `#last-updated`).
3. Append a changelog entry `{date: today, entry: "<what changed>"}` — never remove old entries.
4. Write the file back with the same name and location (or the host's normal deliverables
   location if the original location is not writable).
Browser-side edits are not persistent until the user clicks **Download updated HTML**; say so.
