# Detailed classification and design guidance

Supporting reference, not an additional mandatory full-document read. Follow the execution/read plan
in `..\SKILL.md`; read the applicable sections below in full. The model schema remains authoritative
for field shapes. Current product claims require consultation of the staged official references.

## Required delivery assessment

Decompose findings into atomic capabilities and design the complete logical solution first. Apply
current evidence and minimum PoC gates to the allowed tools, assign an explicit treatment to every
capability, then let the publisher calculate coverage. Produce the complete topology, typed build
contracts, gaps and production-readiness backlog rather than hiding unsupported dependencies.

Create atomic capabilities that collectively cover every in-scope finding. Each capability must declare its business priority and deterministic weight, work type, action impact, topology component IDs, dependencies, allowed-product feasibility, PoC treatment, owner, typed build contract, verification method, and confidence.

Use these status rules:

- `native` and `configurable`: native and demonstration factors are both 1.
- `partial`: native factor is strictly between 0 and 1 and is justified by named supported and unsupported portions; demonstration factor cannot be lower.
- `demonstrable-only`: native factor is 0 and demonstration factor is 0.25.
- `unsupported` and `unknown`: both factors are 0.

The publisher calculates, and the model must never author, these percentages:

- Native build coverage: business-weighted functionality genuinely implemented with allowed tools.
- PoC demonstration coverage: business-weighted journey represented by real implementation or an explicitly disclosed simulation.
- Unsupported coverage: known functionality not natively implementable by the team.
- Unknown coverage: functionality without enough evidence for a feasibility decision.

For each allowed product selected by a capability, score all eight fixed categories from `..\..\Platform-Decision.md` on the 0-5 scale and cite consulted evidence. The publisher derives the weighted score. Category scores rank products only after mandatory gates pass; they do not affect business-weighted capability coverage and cannot override a failed gate.

Every capability receives exactly one PoC treatment: `build`, `configure`, `simulate`, `static-sample-data`, `manual-handoff`, `defer`, or `block`. Simulations require a user-visible disclosure and replacement path. High-impact and irreversible actions require explicit approval. Never fabricate external success, identifiers, approvals, or state changes.

Keep production hardening gaps separate from PoC blockers. The minimum PoC gates are allowed-tool compliance, current tenant availability, authentication, least privilege, approved test data, safe action control, honest simulation, auditable demo actions, and a viable builder path.

## In-scope evidence

Classify findings with status:

- Required
- Confirmed
- Current
- Preferred
- Near-term

Do not count Future, Potential, Optional, Explicitly excluded, Not evidenced, or unresolved gaps as required implementation.

A component can be:

- `evidenced`: directly supported by in-scope finding IDs.
- `configured`: specified in `lisa-config.json`.
- `recommended`: selected from researched Microsoft capabilities.
- `default`: applied by the channel fallback rule.
- `mandatory-baseline`: required for robust identity, security, governance, or ALM.

Every component requires evidence IDs, consulted reference IDs, or a configuration source reference.

## AI agent architect responsibility

Do not merely repeat requirement nouns or report an inventory. Produce a buildable architecture that follows current Microsoft guidance and can be consumed directly by the solution-designer without architectural inference.

For every run:

1. Select an explicit, purpose-specific name for every architecture component.
2. Name the exact Microsoft product or service used to implement it, such as Microsoft Entra ID, Microsoft Purview, SharePoint Online, Microsoft Dataverse, Power Automate, Azure Functions, Azure API Management, Azure Key Vault, or Application Insights when research supports that choice.
3. Recommend architecture components that are not explicitly named in the requirements when they are needed for a robust, reusable, modular, secure, reliable, scalable, governable, or operable solution.
4. Mark recommendations as `recommended` or `mandatory-baseline` and ground them in consulted Microsoft documentation. Do not fabricate requirement evidence for recommendations.
5. Avoid generic component names such as “API,” “database,” “storage,” “integration layer,” “workflow,” or “security.” Name the actual service and its solution-specific responsibility.
6. Preserve requirement-named external systems and data sources exactly, then select the Microsoft integration, storage, identity, and governance services needed to use them safely.
7. Separate human actors, channels, agent runtime, tools, automation, integrations, sources, stores, identity, security, governance, monitoring, and ALM into their correct deployable or configurable boundaries.
8. Design for explicit failure behavior, throttling, retry/idempotency, least privilege, trust boundaries, environment isolation, telemetry, deployment promotion, and human escalation where applicable.

Azure supporting services do not by themselves require selecting Azure AI Foundry. A Copilot Studio solution can use a researched Azure Function, API Management instance, Key Vault, Application Insights resource, custom connector, or custom API while retaining Copilot Studio as the agent platform.

## Staged research

### Stage 1: Allowed Microsoft tools

Every run starts here. Compare Microsoft Copilot Studio, Microsoft 365 Copilot Chat, Microsoft Cowork, and Microsoft Teams after mandatory gates. Consult all relevant current official documentation for:

- Copilot Studio fundamentals and platform capabilities.
- Harness selection.
- Generative orchestration and instructions.
- Knowledge sources.
- Tools and actions.
- Agent flows and Power Automate.
- Autonomous agents and triggers.
- Connected agents.
- Authentication and authorization.
- Supported channels.
- Dataverse and connectors.
- Power Platform data policies, Managed Environments, and ALM.
- Microsoft Purview.
- Microsoft Teams and Microsoft 365 Copilot agent channels.
- Cowork delegated task execution, work-account availability, prerequisites, built-in skills, custom skills, plugins, Microsoft 365 access, approvals, task history, scheduled prompts, data handling, and limitations.
- Copilot Studio guidance and Power Platform Well-Architected best practices.

After reviewing those references, assess every in-scope requirement:

```json
{
  "copilot_studio_fit": "full | partial | not-fit",
  "cowork_fit": "not-assessed | full | partial | not-fit",
  "unmet_requirements": []
}
```

Also populate `requirement_assessments` with exactly one entry for every in-scope finding. Each entry must identify the Microsoft capability and consulted reference IDs that satisfy it. A final classification cannot leave any entry unmet.

If an allowed Stage 1 platform fully fits, stop platform research and select the best-fit allowed platform. Do not consult or cite Foundry or Agent Framework.

For explicit personal delegated work, Cowork must be assessed even when Copilot Studio could technically reproduce the functions. When Cowork is fully viable, select Microsoft Cowork. If Cowork fails a blocking gate, block or defer the personal-worker capability instead of silently replacing the requested experience with a shared Copilot Studio application.

Infer Cowork extension requirements from customer language:

- A consistent, reusable method, structure, or procedure across users or runs requires an explicit Cowork skill component.
- Live access to an external or third-party system without manual export/upload requires an explicit Cowork plugin component.
- Built-in document, email, calendar, meeting, briefing, enterprise-search, and scheduled-prompt capabilities should use Cowork built-in skills when current documentation supports them.

Copilot Studio may remain the selected agentic platform even when a custom connector, MCP server, workflow, or custom API is required. Those components can raise code tier or complexity without forcing a different agentic platform.

### Stage 2: Azure AI Foundry

Only when Copilot Studio fit is partial or not-fit, record each unmet requirement with evidence IDs and run:

```powershell
& "<skill-dir>\scripts\Invoke-ComplexityClassifier.ps1" expand-research `
  --run "<run.json>" `
  --stage foundry `
  --assessment "<copilot-stage-assessment.json>"
```

The assessment must mark Copilot Studio `partial` or `not-fit` and cite every unmet requirement. Assess whether Foundry satisfies only those persisted gaps. Publish at this stage only when Foundry fit is `full` and the selected platform is Azure AI Foundry or Hybrid.

### Stage 3: Microsoft Agent Framework

Only when Foundry still leaves an evidence-linked gap, run:

```powershell
& "<skill-dir>\scripts\Invoke-ComplexityClassifier.ps1" expand-research `
  --run "<run.json>" `
  --stage agent-framework `
  --assessment "<foundry-stage-assessment.json>"
```

The Foundry assessment can carry forward only gaps already identified at the Copilot stage. Select Microsoft Agent Framework or Hybrid only when Agent Framework fully closes the remaining gaps.

Research must expand sequentially. The publisher rejects skipped stages, unsupported escalation, incomplete per-requirement coverage, unconsulted reference IDs, and later-platform references in a Copilot-only solution.

## Channels

For every conversational agent:

1. Use channels specified in `lisa-config.json`.
2. Otherwise use channels explicitly evidenced in the requirement analysis.
3. Otherwise default to both:
   - Microsoft Teams
   - Microsoft 365 Copilot

Do not apply these fallback channels to a Cowork solution. A Cowork solution must explicitly use the Microsoft Cowork experience and may add Teams only when evidenced or configured.

The output must explicitly name every supported channel and its selection basis.

The Copilot chat harness requires an evidenced or configured Microsoft 365 Copilot Chat channel. Other Copilot Studio harnesses can still publish to supported Teams or Microsoft 365 Copilot channels when documented.

## Autonomous triggers

Every autonomous agent must have at least one explicitly named invocation trigger.

For each trigger record:

- name
- trigger type: user, scheduled, event, or other
- exact mechanism
- implementation tier
- evidence and reference IDs

Examples include a Copilot Studio autonomous scheduled trigger, event trigger, Power Automate event, or custom event source. Never output an autonomous agent without its trigger.

## Required component inventory

Regardless of complexity or selected platform, output:

1. Supported conversational channels.
2. Agent development platform name.
3. Explicit platform capabilities used.
4. Primary and connected agents.
5. Exact knowledge-source names.
6. Explicit tool names.
7. Explicit creation method for every tool:
   - Native action
   - Connector
  - Plugin
   - Agent flow
   - Power Automate workflow
   - MCP server
   - Custom connector
   - Custom API
   - Other
8. Invocation triggers.
9. Automation names.
10. Data-store and data-source names.
11. Integration names.
12. AuthN platform, tool, and configuration.
13. AuthZ platform, tool, and configuration.
14. Security controls.
15. Governance controls.
16. ALM components and practices.

When requirements do not name a data, integration, or tool component, recommend an explicit Microsoft component after research and mark it `recommended`. Do not use vague labels such as “integration layer,” “API,” or “workflow” without naming how it will be implemented.

For Copilot Studio tools, always cite the consulted Copilot Studio tool/workflow documentation and state the creation method.

For Cowork, distinguish built-in skills, custom skills, and plugins. Cite Cowork overview/setup guidance for built-in capabilities and Cowork customization guidance for every custom skill or plugin.

## Architecture-ready solution topology

The final model must populate `solution_topology`. This is the authoritative contract for the solution-designer and must not require it to infer hosting, grouping, or relationships.

### Canonical components

Create one canonical topology component for every human, channel, configurable capability, deployable service, Microsoft managed service, external system, and cross-cutting control that must appear in the architecture. Each component requires:

- stable canonical ID and exact solution-specific name
- category and component type
- exact Microsoft product/service or exact external-system name
- role and hosting/runtime
- deployment and environment boundary
- lifecycle: existing, configure, build, or recommended
- exact inventory names represented by the component
- reliability, scalability, and security design
- evidence and consulted-reference grounding

Every name in the component inventory, including AuthN/AuthZ platform and tool names, must map to exactly one topology component. A component can additionally be an architecture recommendation with no inventory mapping when grounded by Microsoft guidance.

At minimum, every solution topology must explicitly name:

- users or operational owners
- every supported channel
- selected agent platform and every agent
- tools and their implementation services
- a purpose-specific data source and a purpose-specific Microsoft data store
- Microsoft Entra ID authentication and authorization components or the researched equivalent
- security and information-protection services
- governance services
- monitoring and observability services
- ALM and deployment services

Add knowledge, automation, integration, external-system, connected-agent, and human-approval components whenever the inventory or requirements require them.

### Explicit relationships

Create source-target relationships using canonical component IDs. Every relationship must name:

- interaction purpose and direction
- integration method and protocol
- data exchanged and read/write/execute behavior
- authentication/token mechanism
- synchronous or asynchronous execution
- failure, retry, escalation, or graceful-degradation behavior

Keep the diagram interaction label at 42 characters or fewer; place protocol, data-flow, authentication, and failure detail in their dedicated fields. Use `hosts` to connect the selected agent platform/runtime to each agent.

Model `Actor -> Channel -> Agent` for every conversational channel. Model every trigger to its target agent, every tool to its service/data dependency, AuthN and AuthZ token flow, data access direction, integrations, human approvals, security protection, governance application, monitoring, and ALM deployment.

### Trust, environments, and sequence

Define:

- trust boundaries and the exact component IDs and controls within each boundary
- Development, Test, and Production environments with promotion through named Microsoft ALM services
- exactly five architecture quality decisions: reusable, modular, reliable, secure, and scalable
- an ordered sequence contract using canonical component IDs, with no more than eight lifelines and no more than 30 interactions

Keep each sequence action at 56 characters or fewer and each optional condition at 34 characters or fewer so the contract is directly renderable without truncation.

The sequence contract must cover the applicable authentication, request or autonomous trigger, orchestration, grounding, tool/data/integration calls, human decision, monitoring/error behavior, and final response. Include only interactions represented by architecture relationships.

Ordinary interaction cycles and asynchronous responses are legitimate. Do not invent blanket
acyclicity or Authentication/Response phase ordering; dependency semantics must come from evidence
and the chosen architecture, not an unspecified global rule.

## Mandatory baseline components

Every solution must include researched identity, security, governance, and ALM—not `None evidenced`.

For Copilot Studio, the default baseline is:

- AuthN: Microsoft Entra ID with Copilot Studio user authentication.
- AuthZ: Microsoft Entra ID, source-system permissions, connector connection references, least privilege, and human approval for binding actions.
- Security: Power Platform data policies and Microsoft Purview protection where applicable.
- Governance: Power Platform Managed Environments and data-policy controls.
- ALM: Power Platform solutions, environment variables, connection references, and deployment pipelines.

For Cowork, use a configuration-oriented baseline:

- AuthN: Microsoft Entra ID work-account sign-in and Cowork prerequisites.
- AuthZ: user-scoped Microsoft 365 permissions, plugin connector consent, and Conditional Access.
- Security: Cowork approval controls, Microsoft 365 data protection, prompt-injection awareness, and draft review.
- Governance: tenant enablement, plugin/skill availability, sharing scope, connector access, and task-data handling.
- Lifecycle: versioned Cowork skill/plugin configuration, controlled sharing, test evidence, and configuration verification. Do not invent a Power Platform solution package for Cowork-only work.

Adapt these when later platform research justifies a different Microsoft control, but keep the component explicit and documented.

## Harness selection and solution design

When Copilot Studio can satisfy all requirements:

1. Use the consulted harness documentation, Copilot Studio guidance, Microsoft 365 documentation, and Power Platform Well-Architected guidance.
2. Select exactly one harness:
   - GitHub Copilot
   - Standard
   - Copilot chat
3. Record the rationale and billing implication.
4. Design the complete Copilot Studio solution using the explicit components above.
5. Add robustness, security, scalability, reliability, governance, and ALM controls from the researched best-practice documents.

Harness validation:

- GitHub Copilot requires skills, memory, or autonomous multi-step planning/orchestration.
- Standard excludes those requirements and supports predictable orchestration, knowledge, tools, flows, and supported triggers.
- Copilot chat requires the matching Microsoft 365 Copilot Chat channel.

Classic Copilot Studio Topics are prohibited and never counted.

## Cowork selection and solution design

Choose Microsoft Cowork when the primary experience is personal delegated work: one authenticated user owns the context, delegates the task, reviews the progress, approves sensitive actions, and directly consumes private drafts or files. Record `harness: Cowork` as the runtime marker.

Cowork selection requires:

1. `cowork_fit: full`.
2. Current Cowork overview, setup, and customization evidence as applicable.
3. All minimum PoC gates and category scores for Microsoft Cowork.
4. An explicit Microsoft Cowork experience channel.
5. Skill and plugin components inferred from the requirements.
6. User-scoped identity, authorization, approval, source, task-history, and configuration-lifecycle components.

## Deterministic complexity

The publisher calculates:

- knowledge sources
- easily-integrable tools
- skills
- connected agents

Knowledge-source count does not raise complexity.

High applies when:

- a pro-code component is required
- a custom API, custom connector, MCP server, gateway, middleware, or custom orchestration is required
- more than 3 easily-integrable tools
- more than 5 skills
- more than 3 connected agents
- Azure AI Foundry, Microsoft Agent Framework, or Hybrid is selected

Low applies only to Copilot Studio No-code with at most 1 easily-integrable tool, at most 3 skills, no connected agents, and no low-code/custom/pro-code component.

Medium applies when no High trigger exists, Low does not fit, and the solution remains within 3 tools, 5 skills, and 3 connected agents.

Real-time or scheduled behavior alone does not force High. Its implementation mechanism decides the tier.
