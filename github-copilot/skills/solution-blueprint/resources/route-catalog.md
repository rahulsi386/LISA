# Route Catalog — the 7 routes

Used in `solution-derivation.md` Step G. Defines what each route is, when it fits, when it does not,
its typical complexity and where it is governed. Use the signals to set the **Fit** score and gate
notes; never use this file to assert licensing, SKU, pricing, region or GA status. Anything marked
**verify in tenant** is unconfirmed availability — record it as a `TBD` gate result and an open
issue unless the source material confirms it.

## Quick view

| Route | One-line definition | Typical complexity | Governance plane |
|---|---|---|---|
| **DA + skills** | M365 Copilot declarative agent in the Copilot chat harness with reusable skills/instructions, knowledge and bounded actions | Low–Medium | M365 admin (agent management) + tenant data/compliance controls |
| **Pro-code DA with MCP** | Code-built declarative / custom engine agent calling MCP servers for live external systems | High | Team-owned code + hosting, Entra app registrations, M365 admin for publishing, MCP servers as owned security boundaries |
| **Pro-code DA without MCP** | Code-built agent using direct APIs / connectors, no MCP layer | Medium–High | Team-owned code + hosting, Entra app registrations, M365 admin for publishing |
| **Standard harness** | Copilot Studio standard harness — rule-based, predictable, structured conversations, agent flows, knowledge, tools | Low–Medium | Power Platform / Copilot Studio admin (environments, DLP, ALM) |
| **GHCP harness** | Copilot Studio GitHub Copilot harness — reasoning-heavy, multi-step, autonomous orchestration | Medium–High | Power Platform / Copilot Studio admin + Copilot Credits consumption monitoring |
| **Cowork plugins** | Microsoft Cowork — delegated personal work owned and consumed by one employee | Low–Medium | User-scoped; tenant controls for Cowork — verify in tenant |
| **Scout** | Microsoft Scout desktop — local skills/automations/MCP on an individual power user's workstation | Low (personal) | Individual workstation; no shared enterprise channel — verify in tenant |

## 1. DA + skills

- **What it is:** A Microsoft 365 Copilot **declarative agent** running in the Copilot chat harness,
  configured with instructions and reusable skills, grounded on M365 knowledge (SharePoint, OneDrive,
  Graph connectors) and limited to bounded actions. Audience: internal M365 users.
- **Best-fit work types / signals:** Knowledge retrieval with citations; Q&A over tenant content;
  light, bounded actions (one form/flow, one record write); users already working in M365 Copilot
  Chat or Teams; reusable methods expressed as skills/instructions.
- **Not-fit signals:** External/anonymous users; high-volume deterministic multi-stage processes;
  dynamic multi-system investigation needing tool choice across custom APIs; custom UI or
  protocols; strict per-step orchestration control.
- **Typical complexity:** Low (retrieval only) to Medium (with actions).
- **Governance plane:** M365 admin agent management plus the tenant's existing compliance controls
  for M365 data. Per-user Copilot availability and licensing: **verify in tenant**.

## 2. Pro-code DA with MCP

- **What it is:** A declarative agent or custom engine agent **built in code** (M365 Agents SDK /
  Teams Toolkit) that calls **MCP servers** to reach live external systems.
- **Best-fit work types / signals:** Adaptive reasoning across several line-of-business systems;
  custom or unsupported APIs that benefit from a reusable, tool-described MCP layer; need for
  custom state, orchestration or protocols; same tools to be reused by other agents.
- **Not-fit signals:** Retrieval-only or single-action scenarios (over-engineered); no team to own
  code, hosting and MCP servers; very short timelines that need configuration-led delivery.
- **Typical complexity:** High (pro-code + custom integration).
- **Governance plane:** Team-owned code, hosting and release pipeline; Entra app registrations and
  permissions; M365 admin for publishing the agent; **each MCP server is a security boundary**
  (identity, authZ, data flow, failure behaviour must be stated). MCP support in the chosen SDK /
  hosting surface: **verify in tenant**.

## 3. Pro-code DA without MCP

- **What it is:** A **code-built** agent (same tooling family as route 2) that calls systems
  through **direct APIs or connectors**, with no MCP layer.
- **Best-fit work types / signals:** Custom agent software with a small, stable set of integrations;
  custom UI or state; organisations not ready to operate MCP servers.
- **Not-fit signals:** Many or changing tools to reuse across agents (MCP is cheaper to extend);
  simple retrieval or flow scenarios that configuration-led routes cover.
- **Typical complexity:** Medium–High.
- **Governance plane:** Team-owned code and hosting; Entra app registrations; M365 admin for
  publishing; each API/connector is a security boundary.

## 4. Standard harness (Copilot Studio)

- **What it is:** The Copilot Studio **standard harness** — rule-based, predictable and potentially
  high-volume structured conversations with topics, **agent flows**, knowledge and tools/connectors.
  Audience: internal **or external** users across channels.
- **Best-fit work types / signals:** Deterministic execution (known stages, approvals, system
  updates); knowledge retrieval plus actions; predictable behaviour and auditability; high volume;
  Power Platform connectors already cover the systems; external-facing channels.
- **Not-fit signals:** Open-ended investigation where the agent must decide which checks/tools to run;
  heavy document create/edit; deep multi-step reasoning.
- **Typical complexity:** Low–Medium (Medium with flows/actions; custom connectors may raise it while
  Copilot Studio stays the platform).
- **Governance plane:** Power Platform admin center / Copilot Studio — environments, DLP policies,
  solution-based ALM, analytics.

## 5. GHCP harness (Copilot Studio GitHub Copilot harness)

- **What it is:** The Copilot Studio **GitHub Copilot harness** — reasoning-heavy, multi-step agents
  with goal decomposition, native Word/Excel/PowerPoint/PDF create-edit, skills, memory, MCP and
  autonomous orchestration. **Consumes Copilot Credits from build time.**
- **Best-fit work types / signals:** Adaptive reasoning; plan-and-execute over many steps; agent
  chooses tools dynamically; document generation/editing as a core output; MCP tools.
- **Not-fit signals:** Simple retrieval or a single predictable flow (cost and non-determinism not
  justified); a deterministic rule where the agent would be the sole authority; scenarios where
  credit consumption during build is unacceptable.
- **Typical complexity:** Medium–High.
- **Governance plane:** Power Platform / Copilot Studio admin plus monitoring of Copilot Credits
  consumption. Availability, maturity (GA vs preview) and region: **verify in tenant**.

## 6. Cowork plugins

- **What it is:** **Microsoft Cowork** — delegated personal work owned and consumed by **one
  employee**. **Skills** capture reusable methods; **plugins** provide live external access. No
  Copilot Studio harness is involved.
- **Best-fit work types / signals:** Delegated personal work ("my", "for me", "for my review");
  the person who asks is the person who consumes the result; reads the user's own mail, meetings,
  files; drafts for human review; schedule-driven personal routines.
- **Not-fit signals:** Shared team or customer-facing service; many users; external users;
  enterprise SLOs; processes that must run independently of one person.
- **Typical complexity:** Low–Medium.
- **Governance plane:** User-scoped delegated permissions under tenant controls. Tenant enablement,
  admin controls and availability: **verify in tenant**.

## 7. Scout

- **What it is:** **Microsoft Scout** desktop — local skills, automations and MCP for an
  **individual power user's workstation** workflows. Prototype / personal productivity; **not a
  shared enterprise channel**.
- **Best-fit work types / signals:** One power user automating their own desktop workflows; rapid
  prototyping of skills or MCP tools before productising; local files and tools.
- **Not-fit signals:** Any shared, team, customer or production service; centrally governed audit or
  SLO requirements; non-technical end users.
- **Typical complexity:** Low (personal) — production use is out of scope for this route.
- **Governance plane:** The individual's managed workstation; no shared enterprise governance plane.
  Availability and enterprise controls: **verify in tenant**. If recommending Scout + DA skills,
  state whether the design should be MCP-ready.

## Disambiguation cues

| If the requirement says… | Lean toward | Rather than |
|---|---|---|
| "answer from our handbook / policies, with citations" | DA + skills or Standard harness | GHCP harness, pro-code |
| "external customers", "high volume", "predictable script" | Standard harness | DA + skills, Cowork, Scout |
| "investigate", "decide which checks to run", several custom APIs | Pro-code DA with MCP or GHCP harness (+ deterministic flow for approvals) | DA + skills |
| "create/edit Word, Excel, PowerPoint, PDF" as core output | GHCP harness | Standard harness |
| "only I use it", "for my review", "my mail/meetings/files" | Cowork plugins (Scout for desktop power users) | Standard harness, pro-code |
| custom UI, custom protocol, few stable APIs | Pro-code DA without MCP | GHCP harness |

## How to use in scoring

1. Pick the dominant in-scope component(s) from Step D.
2. A route whose **not-fit signals** match the dominant component gets **Fit ≤ 2**.
3. A route above the derived complexity is labelled **"Over-engineered for current scope"**.
4. Items marked *verify in tenant* become `TBD` in the gate table (never `Pass`) unless the source
   material confirms them.
