# Solution Derivation Method

Self-contained standalone method — needs nothing beyond this skill's bundled files. Follow
Steps A–I **in order** for every new blueprint and every "re-derive". Do not invent product facts beyond what is stated here or in the
user's source material; when a fact is unknown, write `TBD` and raise an open issue.

---

## Step A — Requirement ledger (traceable)

Extract every requirement into a ledger row:

| Field | Rule |
|-------|------|
| `id` | Prefix by type + sequence: `FR-01` functional, `NFR-01` non-functional, `GR-01` guardrail, `INT-01` integration, `DATA-01` data/grounding, `SEC-01` security/identity, `UX-01` channel/experience, `OPS-01` operations/ALM. **If the source already has IDs, keep them verbatim. Never fabricate a source ID** — generated IDs are marked `"idOrigin": "derived"`. |
| `text` | One-sentence requirement. |
| `source` | Exact short quote + locator (section/heading/page/line). No quote → `Not evidenced`. |
| `classification` | See table below. |
| `systems` | Exact external system names as written in the source (e.g. "SharePoint list 'HR Requests'"). |

Classification:

| In scope (drives design) | Out of scope (never drives route choice) |
|---|---|
| Required, Confirmed, Current, Preferred, Near-term | Future, Potential, Optional, Explicitly excluded, Not evidenced |

Do not inflate scope with out-of-scope rows — list them, but exclude them from gates, scoring and
complexity. Keep ledger IDs stable across updates.

## Step B — Is AI needed at all?

For each in-scope requirement ask: would a function, business rule, search index, form or
conventional workflow solve it reliably? If yes, assign it **Conventional software** and do not
route it through an LLM. Record the decision in the component table (`aiNeeded: false`).

## Step C — Mandatory gates (before any scoring)

Evaluate each candidate route against every gate with **Pass / Fail / Exception / TBD**.
`Exception` requires a named owner and rationale. **A weighted score can never override a Fail.**
A route with any Fail is "Not viable as primary"; `TBD` lowers confidence and becomes an open issue.

1. Product availability — tenant, region, language, channel
2. Feature maturity — GA vs preview (preview needs a named risk owner)
3. Contractual / licensing
4. Data location & movement (residency, does data leave the tenant)
5. Identity — least privilege
6. Authorization scoping (user-delegated vs app, per-record trimming)
7. Network isolation
8. Encryption / key management
9. DLP
10. Audit & traceability
11. Safety & action control — approvals, confirmation, rollback
12. Records lifecycle — retention, deletion
13. Reliability — SLOs, failure behaviour
14. Operational ownership — who runs, monitors, patches it
15. Portability / exit

## Step D — Components and work types

Decompose the solution into components (e.g. "Policy Q&A", "Raise request action", "Escalation").
Assign **one** work type per component; split mixed components or use a hybrid pattern.

| Work type | Signal | Default direction |
|---|---|---|
| Conventional software | Deterministic rule, calculation, lookup | Function / service / rules |
| Knowledge retrieval | Answer from documents with citations | Copilot chat harness (Declarative Agent) or Copilot Studio standard harness |
| Deterministic execution | Known stages, approvals, system updates | Copilot Studio workflow / agent flow / Power Automate / standard harness |
| Adaptive reasoning | Investigate, plan, choose tools dynamically | GitHub Copilot (GHCP) harness, Foundry Prompt Agent or Foundry Hosted Agent |
| Delegated personal work | A person delegates a task and consumes the result | Cowork (plugins/skills), subject to gates |
| Custom agent software | Custom protocols, state, UI, orchestration | Microsoft Agent Framework on Foundry Hosted Agents / self-hosted |

Design principles (apply to every component):

- **Separate reasoning from control** — a probabilistic agent is never the sole authority for a
  deterministic rule (eligibility, approval, write-back validation).
- **Bound autonomy by action impact** — read-only < reversible write < irreversible/external action;
  higher impact needs confirmation/approval and rollback.
- **Durable state in governed stores** (SharePoint list, Dataverse, system of record), never in
  conversational memory.
- **Every connector / API / MCP server / plugin is a security boundary** — state its identity,
  authZ, data flow and failure behaviour.

## Step E — Lowest-complexity viable option (staged escalation)

1. **Stage 1 (always evaluate):** Copilot Studio harnesses, M365 Copilot Chat / Declarative Agents,
   Teams, Cowork.
2. **Stage 2:** escalate to **Foundry** only for requirement IDs Stage 1 cannot meet — list them.
3. **Stage 3:** escalate to **Agent Framework** only for gaps Stage 2 still cannot meet — list them.

Reusable delegated methods → explicit **skills**; live external access → **plugins / MCP**.
Custom connectors or MCP may raise complexity while **Copilot Studio stays the agent platform**.
Record for each stage: `considered`, `meets` (IDs), `gaps` (IDs), `escalate: yes/no`.

## Step F — Complexity rating

| Rating | Definition |
|---|---|
| **Low** | Retrieval / informational only |
| **Medium** | Standard tools, agent flows, actions, or connected agents |
| **High** | Custom integration, pro-code services, gateways, or multi-agent |

Rate by the **highest** in-scope component. State the driver requirement IDs.

## Step G — Map to the 7 routes and score

Always score all seven: **DA + skills**, **Pro-code DA with MCP**, **Pro-code DA without MCP**,
**Standard harness** (Copilot Studio), **GHCP harness**, **Cowork plugins**, **Scout**.

**Read `route-catalog.md` first.** It defines each route (what it is, best-fit and not-fit
signals, typical complexity, governance plane). Use it to set Fit, the over-engineered label and
gate notes: a route whose not-fit signals match the dominant component gets Fit ≤ 2; catalog items
marked *verify in tenant* are `TBD` in the gate table (never `Pass`) unless the source confirms them.
Do not add licensing, SKU or availability facts that are not in the catalog or the source.

Per route record: gate result (from Step C), 1–5 scores on the 7 criteria, `covers` (requirement
IDs), `cannotCover` (IDs + reason), one-line rationale.

### Scoring rubric (1–5, higher is always better)

| Criterion | 1 | 3 | 5 |
|---|---|---|---|
| Fit | Misaligned with dominant work type | Partial; needs workarounds | Native match to dominant work type(s) |
| Implementation speed | Months of pro-code | Weeks; some custom pieces | Days; configuration-led |
| Governance | Ad-hoc; custom audit/DLP | Partial platform controls | Admin-managed, DLP, audit, ALM built in |
| Extensibility | Hard to add tools/sources | Possible with effort | Plug-in tools/connectors/skills easily |
| Integration readiness | Required systems unsupported | Needs custom connector/API | Required systems supported out of the box |
| User experience | Wrong channel / friction | Acceptable | Native in the required channel(s) |
| Operational complexity (inverted) | Heavy infra & ops ownership | Moderate | Minimal; platform-run |

Total = sum (max 35). Show as `x/35` and fit bar width = total/35 %. Ties break toward the lower
complexity route (Step E). A route that is not in a Stage reached by escalation is capped: it can
score but must be labelled "over-engineered for current scope" if it exceeds the derived complexity.

### Recommendation

- One **primary route**, tied to the requirement IDs it satisfies and the gates it passes.
- **Hybrid composition** when components differ (e.g. "Standard harness for FR-01..04 + Power
  Automate flow for FR-05").
- If recommending Scout + DA skills, state whether the design should be MCP-ready.
- **Build vs Demonstrate vs Dependency** view for each component:
  - *Buildable natively* — supported by the chosen platform now.
  - *Demonstrable only* — disclosed simulation/sample data; label it as such.
  - *External dependency* — needs another team/system/licence; name the owner or `TBD`.
- **Honesty rule:** never present mocks, manual steps or unsupported integrations as live.

## Step H — Architecture (in the HTML)

Render inline SVG or HTML/CSS boxes using these semantic layers, top to bottom:

1. **Users** (personas, counts)
2. **Channels** (Teams, M365 Copilot Chat, web, etc. — exactly as required)
3. **Agent platform** — instructions, orchestration, knowledge, tools/actions, connected agents,
   human review
4. **Data / automation / connectors / external systems**
5. Side rails: **Identity, security & governance** and **Monitoring & ALM**

Name every channel, tool, data source, integration, auth component and ALM element explicitly.
Unresolved choices show `TBD`. Do not invent products.

Add a **sequence** of the primary journey: ≤8 lifelines, ≤30 steps, as an ordered list
(`Actor → Target: message`) or a simple SVG.

## Step I — Embed in `blueprint-data`

Store `requirements`, `gates`, `components`, `escalation`, `complexity`, `routes` (with numeric
scores, covers/cannotCover, gate result), `recommendation`, `buildDemoDependency`, `architecture`
and `sequence` in the JSON (schema in `html-structure.md`) so updates preserve them.

---

## Worked calibration example (do not copy content; use to sanity-check)

*Requirement:* an "invoice exception investigator" that, for each flagged invoice, must pull data
from three line-of-business systems via custom APIs, decide which checks to run, draft a resolution
and post it for a finance approver, with full audit.

*Derivation:* components = Adaptive reasoning (investigation, tool choice) + Deterministic execution
(approval + posting) + Conventional software (tolerance rules → function, `aiNeeded: false`).
Stage 1 meets the approval flow and channel but cannot meet the adaptive multi-system investigation
IDs → escalate those to Stage 2 (Foundry agent) with Copilot Studio / Power Automate kept for the
approval → **High** complexity (custom integration + pro-code). Pro-code DA with MCP ranks top for
the investigation component; a pure retrieval route (DA + skills) cannot cover the INT IDs and is
not viable as primary. Contrast: a retrieval-plus-one-action scenario would stay in Stage 1 at
Medium and must not escalate.
