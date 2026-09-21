# Microsoft Agentic Development Platform Decision Framework
## Copilot Studio Harnesses, Microsoft Cowork, Microsoft Foundry, and Microsoft Agent Framework

Version: August 2026
Audience: Solution Architects, CAD, FDE, CAF, Solution Designers, Architecture Review Agents

---

# Purpose

Use this framework to select and compose Microsoft technologies for an agentic solution across industries, verticals, and organization sizes.

This is not a single-product ranking. The options operate at different architecture layers and can be combined:

- **Copilot Studio harnesses** provide managed low-code agent and workflow runtimes.
- **Microsoft Cowork** is an end-user delegated-work experience, subject to tenant availability and verified product constraints.
- **Microsoft Foundry** (formerly Azure AI Foundry) provides managed agent, model, tool, evaluation, hosting, and Azure control-plane capabilities.
- **Microsoft Agent Framework** is a pro-code SDK and orchestration framework that can run in Foundry Hosted Agents or on infrastructure selected by the engineering team.

Make decisions per solution component, not only once for the entire solution.

---

# Team PoC/MVP Delivery Profile

When this framework is used by the local `complexity-classifier`, `solution-designer`, and `agent-builder` pipeline, apply this implementation boundary:

- **Allowed build tools:** Microsoft Copilot Studio, Microsoft 365 Copilot Chat, Microsoft Cowork, and Microsoft Teams.
- **Architecture scope:** Design the complete solution required by the customer, including dependencies outside the allowed build tools.
- **Build-credit rule:** Only functionality genuinely implementable with an allowed tool contributes to native build coverage.
- **Demonstration rule:** Explicitly disclosed simulations, static sample data, and manual PoC steps may contribute only to PoC demonstration coverage.
- **Out-of-bound technologies:** Microsoft Foundry, Microsoft Agent Framework, custom services, and other technologies can describe a complete-solution dependency or future implementation path, but the local builder must not implement them or count them as native coverage.
- **Honesty rule:** Never represent a mock, manual step, deferred dependency, or unsupported integration as a completed external action.

For this profile, platform selection has two outputs:

1. The correct complete logical architecture.
2. A capability-by-capability allowed-tool delivery plan with native, configurable, partial, demonstrable-only, unsupported, or unknown feasibility.

Keep production hardening requirements in a separate backlog unless they are necessary for a safe and credible PoC. Minimum PoC gates remain product availability, allowed-tool compliance, authentication, least privilege, approved test data, action control, simulation disclosure, auditability, and a viable builder path.

---

# Executive Summary

Choose in the following order:

1. **Determine whether AI is necessary.** If a function, rule, search index, or conventional workflow can reliably solve the problem, prefer that simpler mechanism.
2. **Apply mandatory architecture gates.** Eliminate options that cannot satisfy required availability, security, privacy, data location, identity, networking, audit, lifecycle, reliability, or maturity constraints.
3. **Decompose the solution.** Classify each component as conventional software, knowledge retrieval, deterministic execution, adaptive reasoning, delegated personal work, or custom agent software.
4. **Choose the lowest-complexity viable option.** Do not select greater autonomy or custom code without a measurable need.
5. **Compose platforms for mixed processes.** Use deterministic workflows for transactions and controls, and bounded agents for interpretation, investigation, and planning.
6. **Score viable candidates and run a proof of concept.** A weighted score cannot override a failed mandatory gate.

---

# Decision Principles

1. **Decide per component.** A solution can use more than one harness, platform, or framework.
2. **Separate reasoning from control.** Use AI for ambiguity; use deterministic code and workflows for enforceable rules and critical state transitions.
3. **Bound autonomy by impact.** Higher-impact actions require stronger authorization, validation, approval, rollback, and audit controls.
4. **Keep durable state outside conversational memory.** Systems of record, process state, evidence, and approvals belong in governed data stores.
5. **Treat tools as security boundaries.** Every connector, API, MCP server, plugin, and delegated agent needs explicit identity, authorization, data-flow, and failure behavior.
6. **Prefer evidence over feature labels.** Record the documentation, feature status, region, license, test result, and date supporting every material decision.
7. **Design for change.** Isolate dependencies and define reassessment triggers for models, features, limits, and obligations.

---

# Architecture Layers

Do not compare unlike choices as if they were substitutes.

| Layer | Decision | Candidate Options |
|---|---|---|
| Experience | Where and for whom does work occur? | Microsoft 365 Copilot, Teams, web, mobile, API, line-of-business application, Cowork |
| Process | Is execution deterministic, adaptive, or mixed? | Conventional code, workflow, Copilot Studio workflow or agent flow, agent |
| Managed agent runtime | How much runtime behavior should the platform manage? | Copilot chat harness, standard harness, GitHub Copilot harness, Foundry Prompt Agent |
| Custom agent runtime | Is custom orchestration or code required? | Foundry Hosted Agent, self-hosted application |
| Development framework | Which pro-code abstractions are required? | Microsoft Agent Framework or another approved framework |
| Model and tools | Which models, knowledge, APIs, connectors, and protocols are approved? | Foundry models and tools, Copilot Studio connectors, MCP, custom APIs |
| Control plane | How is the solution secured, deployed, observed, evaluated, and governed? | Power Platform controls, Microsoft Foundry and Azure controls, custom platform controls |

---

# Phase 1: Mandatory Gates

Evaluate these requirements before functional scoring. Mark each candidate **Pass**, **Fail**, or **Exception Required**. A failed candidate is not viable unless the accountable authority approves a documented exception.

| Gate | Questions to Answer | Required Evidence |
|---|---|---|
| Product availability | Is every required feature available in each target tenant, cloud, region, language, and channel? | Availability documentation and tenant validation |
| Feature maturity | Are production dependencies generally available? If preview is allowed, who accepts the risk and exit plan? | Feature status, owner, expiration date, fallback |
| Contractual coverage | Do service terms, licenses, support commitments, and data protection terms cover the intended use? | Product terms and legal/procurement approval |
| Data location and movement | Where are prompts, files, state, embeddings, model inputs, outputs, traces, evaluations, telemetry, and support data stored and processed? | End-to-end data-flow diagram and service evidence |
| Identity | Can users, workloads, agents, and tools use approved identities with least privilege and separation of duties? | Identity design and access review |
| Authorization | Can permissions be scoped by user, agent, tool, resource, environment, and operation? | RBAC/ABAC and delegated-access design |
| Network isolation | Are private ingress, controlled egress, endpoint restrictions, firewall, and private connectivity requirements supported? | Network architecture and connectivity test |
| Encryption and keys | Are encryption, customer-managed keys, secret storage, and rotation requirements supported? | Key and secret management design |
| Data-loss prevention | Can knowledge, connectors, tools, endpoints, channels, and data combinations be allowed or blocked? | Policy configuration and enforcement test |
| Audit and traceability | Are model, tool, identity, approval, configuration, deployment, and admin events captured with sufficient retention and export? | Audit-event inventory and sample records |
| Safety and action control | Can tools be constrained, inputs and outputs validated, approvals required, attacks mitigated, and actions stopped or reversed? | Threat model, control tests, rollback procedure |
| Records and data lifecycle | Can retention, deletion, legal hold, data-subject handling, backup, restore, and evidence preservation requirements be met? | Lifecycle and recovery design |
| Reliability | Can availability, latency, throughput, retry, idempotency, recovery, and continuity targets be met? | SLO design and failure test |
| Operational ownership | Is a team accountable for monitoring, incidents, access, cost, quality, and model or prompt changes? | RACI and operating model |
| Portability and exit | Can data, prompts, tools, evaluations, and business logic be exported or replaced in time? | Exit plan and dependency inventory |

## Gate Rules

- Evaluate the **exact feature combination**, not only the parent product.
- Include every external connector, model, plugin, MCP server, agent, and telemetry destination.
- A platform certification or contractual commitment does not automatically make an implementation compliant.
- Re-run gates when regions, models, tools, hosting modes, or feature maturity change.

---

# Phase 2: Component Classification

Break the scenario into independently deployable or governable components. Assign each component one primary work type.

| Work Type | Characteristics | Default Direction |
|---|---|---|
| Conventional software | Fully specified logic, exact calculations, strict validation, or no need for language reasoning | Function, service, rules engine, or application code |
| Knowledge retrieval | Answers grounded in enterprise content; limited action requirements | Copilot chat harness or standard harness |
| Deterministic execution | Known stages, branches, approvals, deadlines, retries, and system updates | Copilot Studio workflow, agent flow, standard harness, or conventional workflow platform |
| Adaptive reasoning | Must investigate, plan, choose tools, interpret varied evidence, or recover dynamically | GitHub Copilot harness, Foundry Prompt Agent, or Foundry Hosted Agent |
| Delegated personal work | A person delegates work, owns the context, and directly consumes the result | Cowork, subject to mandatory gates and verified availability |
| Custom agent software | Custom protocols, models, state, middleware, algorithms, UI, hosting, or orchestration | Microsoft Agent Framework with Foundry Hosted Agents or approved self-hosting |

When a component contains multiple work types, split it or use a hybrid pattern. Do not make a probabilistic agent the sole authority for a rule that can be implemented deterministically.

---

# Phase 3: Platform Comparison

Ratings are directional starting points, not evidence. Validate exact capabilities, limits, maturity, region, and licensing during architecture review.

Legend: **High** = native strength, **Medium** = supported with configuration or constraints, **Low** = not a focus, **Owner-built** = engineering must implement and operate it.

| Dimension | Copilot Chat Harness | Standard Harness | GitHub Copilot Harness | Microsoft Cowork | Foundry Prompt Agent | Foundry Hosted Agent | Microsoft Agent Framework |
|---|---|---|---|---|---|---|---|
| Primary purpose | Grounded M365 Copilot extension | Structured agents and repeatable processes | Managed deep-reasoning agents and workflows | Delegated work for an individual | Managed configurable agent API | Managed hosting for custom agent code | Pro-code agent and workflow development |
| Primary audience | Internal M365 users | Internal or external users | Internal or external users | Individual employee | Custom application users or services | Custom application users or services | Determined by the application |
| Development model | Declarative | Low-code | Natural-language-first managed authoring | End-user configuration | Portal, SDK, or REST | Source code or container | .NET, Python, or Go |
| Deterministic workflows | Low | High | Medium | Low to Medium | Medium | High with custom code | High with graph workflows or code |
| Adaptive reasoning | Low | Medium with generative orchestration | High | High for delegated work | High | High | High |
| Multi-step planning | Low | Medium | High | High | High | High | High |
| Multi-agent support | Low | Medium to High | High | Verify current capability | Medium; validate pattern | High | High with explicit workflows |
| Human approval | Low | High through workflows and agent flows | High when designed into tools or workflows | Verify current capability | Application-dependent | Owner-built or integrated | Owner-built with workflow support |
| Event-driven operation | Low | High with triggers and flows | High | Verify current capability | Application-dependent | Owner-built or integrated | Owner-built or integrated |
| Long-running work | Low | Medium; validate limits | High for supported task patterns | Verify limits | Validate runtime limits | High with custom state | High; durability depends on host and stores |
| Tools and APIs | Limited extension scope | Connectors, flows, HTTP, MCP | Connectors, knowledge, MCP, tools | Plugins; verify catalog | Built-ins, functions, OpenAPI, MCP, toolboxes | Foundry tools plus custom code | Functions, MCP, middleware, integrations |
| Memory | Low | Session context; externalize durable state | Native capability; verify status and policy | Verify status and policy | Built-in options; verify status | Custom plus platform/session state | Context providers and selected stores |
| Model choice | Platform-managed | Platform-configured | Selectable supported models | Platform-managed | Broad Foundry model catalog | Broad catalog plus code control | Multiple providers and local models |
| File creation/editing | Low | Low to Medium | High for supported Office/PDF work | High for personal work | Tool-dependent | Customizable | Owner-built or tool-dependent |
| Custom orchestration | Low | Medium | Medium | Low | Low to Medium | High | Very High |
| Custom UI/protocols | Low | Supported channels | Supported channels | Product experience | High through application integration | Very High | Very High |
| Private networking | Platform configuration | Platform configuration | Platform configuration | Verify service boundary | High with supported setup | High; validate hosting limitations | Owner-built; depends on host |
| Customer-owned stores | Limited | Dataverse and connected stores | Connected stores; validate internal state | Verify | High with standard setup | High | Owner-built |
| Observability/evaluation | Platform analytics | Analytics and evaluations | Evaluate and Monitor surfaces | Verify | Foundry tracing, evaluation, monitoring | Foundry plus custom telemetry | Telemetry hooks; solution is owner-built |
| ALM and CI/CD control | Low to Medium | High through Power Platform ALM | Validate required automation | Low | High through SDK/REST and Azure tools | High through source and Azure tools | Very High |
| Runtime ownership | Microsoft | Microsoft | Microsoft | Microsoft | Microsoft | Foundry-managed containers | Team-selected unless hosted in Foundry |
| Portability | Low | Medium | Medium | Low | Medium | High at code layer | High at code layer; dependencies remain |
| Operational burden | Low | Low to Medium | Low to Medium | Low | Medium | Medium to High | High |
| Best fit | M365-grounded knowledge | Controlled conversations and processes | Complex managed knowledge work | Personal delegation | Managed agents for custom apps | Custom agents with managed Azure hosting | Maximum code and orchestration control |

## Interpretation Notes

- The **standard harness** is not purely deterministic. Generative orchestration can select and chain topics, tools, knowledge, and agents, and respond to events. Evaluate whether its bounded flexibility is sufficient.
- The **GitHub Copilot harness** is strongest when long adaptive work, file handling, skills, memory, and automatic recovery matter more than low-level orchestration.
- **Foundry Prompt Agents** fit API-addressable managed agents needing model choice and Azure controls without custom orchestration code.
- **Foundry Hosted Agents** run custom code with managed endpoints, scaling, identity, session state, and observability. They can host Agent Framework applications.
- **Agent Framework** is not a managed cloud service by itself. Security, durability, scaling, deployment, and compliance depend on its providers, stores, tools, and host.
- **Cowork** must not be selected solely because one employee starts a task. Validate its current availability, service boundaries, governance, integrations, and action controls first.

---

# Phase 4: Selection Questions

Use these questions only after mandatory gates pass.

## Question 1: Can conventional software solve the component?

Use a function, rules engine, search implementation, or deterministic workflow when requirements are fully specified and language-model reasoning adds no measurable value.

## Question 2: Is it primarily grounded knowledge in Microsoft 365 Copilot?

Choose the **Copilot chat harness** when the main value is grounded enterprise answers inside Microsoft 365 Copilot and complex workflows or external channels are not required.

## Question 3: Is it a controlled conversation or known process?

Choose the **standard harness** or a **Copilot Studio workflow/agent flow** when paths, approvals, events, exceptions, and outcomes should be explicit. Generative orchestration can provide bounded interpretation and tool selection.

## Question 4: Is work delegated by and primarily consumed by one employee?

Consider **Microsoft Cowork** when the employee owns the work context and output, no shared application runtime is required, and all mandatory gates and product-evidence requirements pass.

## Question 5: Is a managed low-code agent sufficient for adaptive work?

Choose the **GitHub Copilot harness** when the system must investigate, plan, work across tools and files, adapt, and recover while a managed Copilot Studio experience meets the requirements.

## Question 6: Can the agent be expressed as instructions, a model, and supported tools?

Choose a **Microsoft Foundry Prompt Agent** for an API-addressable managed agent with broad model choice, Azure controls, and no custom orchestration code.

## Question 7: Is custom code required while managed hosting is preferred?

Choose a **Microsoft Foundry Hosted Agent** for custom logic, frameworks, protocols, or multi-agent orchestration with managed endpoints, scaling, identity, and observability.

Use **Microsoft Agent Framework** inside it when agent abstractions, middleware, sessions, tools, telemetry, or graph workflows fit.

## Question 8: Must the team control the hosting runtime?

Use **Microsoft Agent Framework on approved self-managed infrastructure** when deployment topology, runtime, scaling, networking, portability, or infrastructure integration cannot be met by a managed service.

The team then owns production hardening, state, security, evaluation, observability, scaling, patching, and support.

---

# Phase 5: Weighted Scoring

Score only candidates that passed mandatory gates.

Use a 0-5 scale:

- **0:** Unsupported or unacceptable
- **1:** Major gaps or extensive custom work
- **2:** Partially meets the requirement
- **3:** Meets it with normal configuration
- **4:** Strong native fit
- **5:** Differentiating strength with verified evidence

| Category | Default Weight |
|---|---:|
| Security, privacy, governance, and data control | 20% |
| Safety, authorization, approvals, and reversibility | 15% |
| Functional and reasoning fit | 15% |
| Data, tools, channels, and integration fit | 15% |
| Reliability, observability, evaluation, and supportability | 12% |
| Engineering fit, ALM, extensibility, and portability | 10% |
| Cost, licensing, capacity, and operational effort | 8% |
| Availability, maturity, and roadmap risk | 5% |

Adjust weights before scoring and document why. Do not change them after seeing results without architecture-review approval.

`Weighted score = sum(category score / 5 * category weight)`

The result is out of 100. It ranks viable options; it does not prove fitness.

## Evidence Register

| Field | Description |
|---|---|
| Requirement | Specific capability or constraint |
| Score | 0-5 |
| Evidence | Documentation, contract, configuration, benchmark, or test |
| Feature status | Generally available, preview, private preview, or roadmap |
| Scope | Region, cloud, tenant, model, channel, license, and hosting mode |
| Confidence | High, medium, or low |
| Owner | Person accountable for validation |
| Verified on | Date evidence was checked |
| Recheck trigger | Date or condition requiring reassessment |

---

# Hybrid Architecture Patterns

## Pattern 1: Deterministic Shell with Reasoning Steps

Use a workflow to own state, deadlines, retries, approvals, and writes. Invoke an agent only for bounded extraction, classification, comparison, summarization, or recommendation.

## Pattern 2: Managed Agent with Guarded Tools

Use the GitHub Copilot harness or a Foundry Prompt Agent to reason and plan. Expose narrow, idempotent tools with schemas, least privilege, validation, approval thresholds, and audit events.

## Pattern 3: Custom Agent on Managed Hosting

Build orchestration with Microsoft Agent Framework and deploy it as a Foundry Hosted Agent. Use Foundry for endpoints, scaling, identity, models, tools, tracing, evaluation, and monitoring.

## Pattern 4: Self-Hosted Agent Application

Build with Microsoft Agent Framework and deploy to approved application infrastructure. Add selected models, stores, queues, identity, policy enforcement, evaluation, and telemetry.

## Pattern 5: Experience and Runtime Separation

Use Microsoft 365 Copilot, Teams, or a custom application as the experience while a Copilot Studio agent, Foundry agent, or custom service works behind an authenticated API boundary.

## Pattern 6: Multi-Agent with Explicit Ownership

Split agents only when domains, teams, identities, models, lifecycle, or reuse justify independent components. Define contracts, handoffs, timeout behavior, evidence propagation, and trace correlation.

Do not use multi-agent design merely to imitate an organization chart. Additional agents increase latency, cost, testing, and governance surface.

---

# Control Requirements for Agentic Actions

| Impact Level | Typical Effect | Minimum Control Pattern |
|---|---|---|
| Read-only | Retrieves approved information | Scoped identity, source authorization, logging, data minimization |
| Draft | Produces content without publishing or changing records | Grounding, citations where applicable, validation, user review |
| Reversible write | Creates or updates recoverable records | Idempotency, preconditions, audit, notification, rollback |
| High-impact write | Commits material changes or external communications | Explicit authorization, approval or deterministic policy gate, recovery plan |
| Irreversible or safety-critical | Cannot be reliably undone or could cause severe harm | No autonomous execution without formal risk acceptance and purpose-built safeguards |

For every write-capable tool, define:

- Caller identity and delegated identity behavior
- Allowed resources and operations
- Input and output schema validation
- Business preconditions and policy checks
- Confirmation or approval requirements
- Idempotency and duplicate suppression
- Timeout, retry, compensation, and rollback behavior
- Audit events and correlation identifiers
- Kill switch and incident procedure

---

# State, Memory, and Evidence

| Concept | Purpose | Design Rule |
|---|---|---|
| Conversation context | Short-term interaction continuity | Minimize and expire according to policy |
| Agent memory | Reusable learned or user-specific context | Require explicit scope, provenance, correction, retention, and deletion controls |
| Process state | Authoritative workflow position and transaction data | Store in a durable governed system, not only agent memory |
| Evidence | Material supporting a decision or action | Preserve source, version, timestamp, identity, transformation history, and integrity |
| Configuration | Instructions, model, tools, policies, and thresholds | Version, review, test, approve, deploy, and roll back through ALM |

---

# Evaluation and Operational Readiness

No platform should enter production solely from a feature comparison.

## Proof-of-Concept Test Areas

1. **Task quality:** completion, accuracy, groundedness, tool selection, and instruction adherence.
2. **Control effectiveness:** authorization, approvals, DLP, prompt-injection resistance, and unsafe-action prevention.
3. **Reliability:** latency, throughput, timeout, retry, duplicate execution, dependency failure, and recovery.
4. **Traceability:** reconstruct the user, version, model, inputs, sources, tool calls, approvals, outputs, and changes.
5. **Data handling:** verify storage, processing, telemetry, retention, deletion, and movement.
6. **Operations:** monitoring, alerting, triage, kill switch, rollback, backup, restore, and support escalation.
7. **Lifecycle:** source control, promotion, automated tests, evaluation gates, deployment approval, and rollback.
8. **Economics:** model, tool, connector, hosting, storage, observability, license, support, and engineering cost.
9. **User experience:** channel fit, accessibility, response time, transparency, escalation, and misunderstanding recovery.

## Minimum Acceptance Criteria

Set numeric thresholds before the proof of concept for:

- Task completion and critical-error rates
- Unauthorized or unapproved actions: zero
- Groundedness or evidence quality where relevant
- Latency and availability
- Recovery point and recovery time where state is durable
- Cost per successful task and projected monthly cost
- Audit reconstruction success
- Adversarial and prompt-injection test performance
- Human escalation success

Test representative, edge-case, stale, conflicting, malformed, unauthorized, and adversarial inputs. A successful demonstration is not a production-readiness test.

---

# Platform Guidance

## Copilot Chat Harness

Choose for grounded answers inside Microsoft 365 Copilot when users are internal and workflow, autonomy, and channel requirements are limited. Avoid when complex orchestration, high-impact autonomous actions, extensive custom UI, or external customer channels are central.

## Standard Harness

Choose for controlled, repeatable conversations and processes using topics, rules, flows, approvals, connectors, and triggers. It can use generative orchestration for bounded interpretation, tool selection, MCP, and connected agents; do not classify it as purely deterministic.

## GitHub Copilot Harness

Choose for reasoning-heavy, adaptive, multi-step, or file-centric work where managed skills, memory, tools, evaluation, monitoring, and supported channels fit. Avoid when a fixed workflow is sufficient or custom runtime-level control is mandatory.

## Microsoft Cowork

Consider when one employee delegates work and directly owns its context and output, and a shared application or service endpoint is unnecessary. Cowork for work or school accounts is generally available according to current Microsoft documentation, but tenant enablement, licensing, usage-based billing, identity, network access, plugins, and builder/configuration paths still require exact-environment verification.

Cowork provides built-in skills for documents, email, scheduling, calendar management, meetings, daily briefings, enterprise search, communications, and deep research. Use a custom Cowork skill when a reusable domain method or output structure must be consistently applied. Use a Cowork plugin when the delegated task requires an external data source or service. Treat unavailable plugins, unresolved connector authentication, and unverified tenant features as unknown or blocked rather than silently substituting a shared application platform.

## Microsoft Foundry Prompt Agents

Choose when a custom application needs an API-addressable managed agent, instructions plus supported models and tools are sufficient, and Azure identity, networking, data controls, tracing, evaluation, and monitoring matter without runtime-code ownership.

## Microsoft Foundry Hosted Agents

Choose for custom code, orchestration, protocols, middleware, or frameworks with managed hosting, scaling, agent identity, endpoints, state capabilities, and Foundry observability. Validate the chosen hosting mode's network, region, maturity, and runtime limits.

## Microsoft Agent Framework

Choose when developers need pro-code agents, tools, middleware, session state, telemetry, provider integrations, or explicit graph workflows. It can run in Foundry or on team-selected infrastructure. The team owns all controls not supplied by the host and providers. Validate language-specific feature maturity before commitment.

---

# Common Anti-Patterns

- Selecting from persona before applying mandatory gates
- Making one platform decision for an entire mixed-mode process
- Using an LLM for exact rules or calculations that conventional code can implement
- Treating platform compliance claims as proof that an implementation is compliant
- Storing authoritative state or evidence only in conversation history or memory
- Giving an agent broad user credentials or unrestricted tools
- Allowing high-impact writes without validation, approval, idempotency, and rollback
- Selecting multi-agent architecture without a clear ownership, reuse, lifecycle, or isolation need
- Using preview capabilities without an owner, exception, fallback, and exit date
- Comparing low-code services, managed hosting, and SDKs as if they carry the same responsibilities
- Scoring a candidate that failed a mandatory gate
- Relying on a matrix without representative and adversarial evaluations

---

# Architecture Decision Record Template

## Decision Summary

- Scenario and business outcome:
- Decision unit or component:
- Selected experience:
- Selected process mechanism:
- Selected managed or custom runtime:
- Selected development framework, if any:
- Selected models, tools, stores, and channels:

## Constraints and Gates

- Mandatory gates passed:
- Exceptions and accountable approvers:
- Preview dependencies and exit plans:
- Data-flow diagram:
- Threat model:

## Evaluation

- Candidates considered:
- Final weighted scores:
- Key evidence:
- Proof-of-concept results:
- Cost model:
- Residual risks:

## Operations

- Product owner:
- Engineering owner:
- Security and governance owner:
- SLOs and alerts:
- Incident and kill-switch procedure:
- Rollback and recovery procedure:

## Lifecycle

- Decision date:
- Reassessment date:
- Reassessment triggers:
- Replacement or exit strategy:

---

# Final Golden Rules

1. **Use conventional software when the answer can be specified exactly.**
2. **Use workflows to own process state and enforce known controls.**
3. **Use agents for ambiguity, interpretation, investigation, planning, and adaptive tool use.**
4. **Use the least autonomous and least custom option that meets the measured need.**
5. **Compose platforms when components have different requirements.**
6. **Never let a weighted score override a failed mandatory gate.**
7. **Prove quality, control, reliability, traceability, and cost before production.**

---

# Authoritative References

Validate capabilities against current documentation because product names, feature status, limits, and regional availability change.

- [Choose a Copilot Studio harness](https://learn.microsoft.com/en-us/microsoft-copilot-studio/harnesses-overview)
- [Microsoft Copilot Studio overview](https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-fundamentals)
- [Copilot Studio generative orchestration](https://learn.microsoft.com/en-us/microsoft-copilot-studio/advanced-generative-actions)
- [Copilot Studio child and connected agents](https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-add-other-agents)
- [Copilot Studio security and governance](https://learn.microsoft.com/en-us/microsoft-copilot-studio/security-and-governance)
- [Copilot Studio geographic data residency](https://learn.microsoft.com/en-us/microsoft-copilot-studio/geo-data-residency)
- [Microsoft Foundry overview](https://learn.microsoft.com/en-us/azure/foundry/what-is-foundry)
- [Microsoft Foundry Agent Service overview](https://learn.microsoft.com/en-us/azure/foundry/agents/overview)
- [Microsoft Foundry Agent Service private networking](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/virtual-networks)
- [Microsoft Foundry observability](https://learn.microsoft.com/en-us/azure/foundry/concepts/observability)
- [Microsoft Agent Framework overview](https://learn.microsoft.com/en-us/agent-framework/overview/)
- [Microsoft Copilot Cowork overview](https://learn.microsoft.com/en-us/microsoft-365/copilot/cowork/)
- [Get started with Microsoft Copilot Cowork](https://learn.microsoft.com/en-us/microsoft-365/copilot/cowork/get-started)
- [Customize Cowork skills and plugins](https://learn.microsoft.com/en-us/microsoft-365/copilot/cowork/cowork-customize)