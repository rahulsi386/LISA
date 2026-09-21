---
name: "agent-optimizer"
description: "Harness-aware Microsoft Copilot Studio optimizer. Runs a mandatory read-only instruction-design audit, then applies minimal evidence-backed changes through the correct harness surface, preserves requirements and rollback safety, and delegates every retest back to agent-evaluator."
---

# Agent Optimizer

## Purpose

Optimize an existing Microsoft Copilot Studio agent from completed `agent-evaluator` evidence and a mandatory read-only live-instruction audit. Diagnose failed gates, plan the smallest justified change, update the live agent through its harness-correct authoring path, preserve rollback evidence, and delegate all retesting and scoring back to `agent-evaluator`.

This skill's first pass is an instruction-design review; it does not modify the agent or score behavior. The skill does not generate evaluation datasets, execute or score tests, create regression baselines, or declare behavioral success from its own judgment.

When invoked by `cad-orchestrator`, follow `..\workflow-checkpointing.md`. Start the `optimization`
stage as soon as the `OPT-*` ID is assigned. Checkpoint the instruction audit and every exact round
phase. Every live mutation requires a persisted remote operation intent before execution and a
verified receipt afterward. On recovery, reconcile uncertain live state before choosing accept,
continue, or rollback. Commit `optimization-manifest.json` only after its validator passes.

## Required inputs

Read `lisa-config.json`, resolve its configured `basePath`, and read these artifacts only from `<basePath>\output\evaluation\`:

1. `evaluation-manifest.json`
2. `evaluation-dataset.json`
3. `evaluation-rubric.json`
4. `evaluation-observations.json` with `optimizerHandoff`
5. `regression-baseline.json`
6. `evaluation-run-report.md`
7. `deployment-gate-summary.md`

Also read `<basePath>\output\build\build-manifest.json` and `<basePath>\output\build\agent-build-handoff.json` when available. Reject absolute paths, caller-selected evaluation/build locations, and traversal outside `basePath`. Reject artifacts whose manifest paths, hashes, sizes, stage, schema, or run ID are invalid. Resolve the exact agent name/ID, harness, environment ID/URL, published target, component inventory, instruction version/hash, quality targets, build risks, packages, and recommendation backlog. Verify the deployed state independently; never assume the handoff is current.

Resolve and validate these inputs with `resolve_skill_inputs.py --skill agent-optimizer --config <lisa-config.json>`. Reject artifacts whose manifest paths, hashes, sizes, stage, schema, or run ID are invalid. Resolve the exact agent name/ID, harness, environment ID/URL, published target, component inventory, instruction version/hash, quality targets, build risks, packages, and recommendation backlog. Verify the deployed state independently; never assume the handoff is current.

Optional policy inputs:

- `maxOptimizationRounds` (default 3)
- `minimumImprovement`
- protected/critical test IDs
- controls or components that must not change
- orchestrator-supplied optimization scope

If evaluator artifacts are incomplete, inconsistent, blocked, or from a different agent/version/environment, stop and report the mismatch. Do not optimize cases whose `doNotOptimizeReason` identifies authentication, wrong surface, inaccessible source, portal/tooling, or other platform blockers.

## Non-negotiables

1. `agent-evaluator` is the only behavioral evaluator and deployment-gate authority.
2. `agent-builder` owns initial construction; this skill owns only post-evaluation optimization.
3. Never change requirements, expected answers, rubrics, thresholds, or baselines to make a failing agent pass.
4. Preserve the selected harness. If evaluation proves a harness-capability mismatch, stop optimization and return a redesign handoff to the orchestrator containing scope, billing impact, and rebuild requirements.
5. Modify only knowledge, tools, connectors, agents, channels, owners, and data sources listed in the orchestrator-supplied optimization scope.
6. After every component change, realign the description and instructions with the exact live knowledge, tools, skills, flows, connected agents, authentication, authority, failures, and response contract.
7. Application Insights, Microsoft Purview, and Managed Environments are not universal optimization blockers. Implement them when policy, risk, architecture, or evaluator evidence requires them; otherwise preserve them as prioritized recommendations.
8. Never request hidden chain-of-thought or use evaluator-visible maker reasoning as a user-facing optimization target.
9. Run the mandatory read-only instruction-design review before proposing or applying any optimization change. It is not a behavioral evaluation and never replaces `agent-evaluator`.
10. Do not enumerate every attached knowledge source in agent instructions. Copilot Studio makes configured knowledge available to the agent by default. Name a source only when evidence requires source-specific priority, conflict resolution, scope, access behavior, citation, freshness, or a missing-evidence boundary.

## Remote-write verification

Before any live change:

1. Inspect `pac auth list`, `pac env list`, `pac env who`, and `pac org who`.
2. Verify the browser identity/tenant for UI-authored harnesses matches the PAC-verified identity/tenant.
3. Record the authenticated identity, exact environment name/URL/ID, agent ID, harness, current instruction hash, evaluation run ID, and proposed change set.
4. The environment must match the configured target exactly. On any mismatch, missing authentication, or expired authentication, stop and report the exact discrepancy before changing anything remotely. When it matches, proceed without pausing.

## Workflow

### 0. Mandatory instruction-design review

After validating inputs and the target environment, but before planning any change:

1. Pull, download, or otherwise read the exact live persisted instruction text and record its SHA-256. Do not rely solely on a build artifact.
2. Perform this read-only review before `round-001`; it must not edit instructions, tools, knowledge, connections, channels, or the harness.
3. Assess the instructions against:
   - Microsoft Copilot Studio guidance for instructions, generative orchestration, knowledge, tools, authentication, and security across every harness.
   - OpenAI guidance for clear task contracts, prioritized instructions, concise output requirements, focused examples only when needed, and evaluation-driven iteration.
   - Anthropic guidance for explicit role and boundaries, structured sections, ambiguity handling, untrusted-content handling, and concise reusable instructions.
4. Identify each finding as one of: `clarity`, `scope`, `duplication`, `conflict`, `unsupported-reference`, `security`, `grounding`, `tool-policy`, `response-contract`, `overengineering`, or `knowledge-enumeration`.
5. Verify that every named live tool, connected agent, channel, or other runtime component matches the deployed inventory. Treat a source name as a runtime component only when the instruction needs the source-specific behavior described in non-negotiable 10.
6. Reject or flag instructions that:
   - enumerate all configured knowledge sources without an evidence-backed source-specific reason;
   - describe default Copilot Studio knowledge retrieval mechanics as if they were mandatory prompt rules;
   - omit required grounding, ambiguity, safe-failure, authority, or response behavior;
   - duplicate or conflict with another instruction;
   - reference a component that is absent from the live agent;
   - add speculative edge cases, hidden-reasoning requests, secrets, environment-specific values, or unnecessary platform internals.
7. Write these root-level artifacts before any mutable round:
   - `instruction-audit.json` containing the instruction hash, consulted guidance, findings, pass/fail checks, and minimal proposed rewrites.
   - `instruction-audit.md` containing a concise human-readable decision record.

The audit passes when the instructions are clear, concise, internally consistent, grounded, safe, and use knowledge behavior only where a source-specific rule is needed. A passing audit does not imply a behavioral or deployment-gate pass.

If the audit proposes an instruction change, include its exact diff, evidence, risk, rollback, and required evaluator retest scope in the optimization plan. Apply it only within the orchestrator-supplied optimization scope. A source-specific instruction rule may name only the relevant source or source class; never list every configured source merely because it is attached.

### 1. Validate and classify findings

Read `optimizerHandoff.findings`, failed gate rationales, assertion evidence, actual responses, tool observations, citations, durations, blockers, baseline, and required retest scope. Map each evidence-backed finding to one primary change surface:

- instructions
- description/discoverability
- tool description
- tool input/output schema
- flow/tool implementation
- knowledge scope/priority/freshness/permissions
- orchestration or connected-agent routing
- authentication/authorization
- reliability/error behavior
- performance/context/tool fan-out
- harness/platform mismatch

Distinguish symptoms from root causes. Do not claim an unobserved root cause. When two causes are plausible, choose the lowest-risk reversible experiment and state the uncertainty.

### 2. Create a minimal optimization plan

Prioritize critical/high failures, then repeated gate failures, then performance/cost opportunities. Group only tightly coupled changes. For each proposed change record:

- finding and test IDs
- evidence
- current live value/hash
- exact proposed value/change
- expected mechanism
- affected components
- risk and rollback
- evaluator retest IDs
- full critical regression scope

Prefer configuration and instruction fixes before new components or custom code. Keep instructions lean: state each rule once, use exact component names, remove contradictions/obsolete text, preserve established boundaries, and add examples only when evaluator evidence shows routing ambiguity that rules/tool descriptions cannot solve. Do not list attached knowledge sources unless a source-specific rule is required by the instruction-design review.

### 3. Snapshot and rollback

Before editing, create the next immutable `rounds\round-NNN\` directory. Pull/download the live definition, export the current solution/package, and store them under that round's `snapshots\before\` directory. Write `before-state-manifest.json` with hashes plus live-state inventory. Record the current instruction version/hash, component IDs, connections, harness, channels, and published state. A reversible before-state snapshot is mandatory.

### 4. Apply through the harness-correct path

- **Standard harness:** pull the PAC workspace, make the minimal supported YAML/component change, validate, push, publish to the validated test target, and pull again to verify persistence. Use the Copilot Studio UI only for components PAC cannot manage.
- **GitHub Copilot harness:** use the new agent UI; for rich-text instructions use real keyboard insertion, Save, reload, and verify the Dataverse configuration. Update skills/tools/knowledge/connected agents only when the plan requires it.
- **Copilot chat harness:** edit the agent from the Microsoft 365 Copilot agent page, not by changing a Standard-harness channel. Save/reload, publish internally, and verify the correct M365 Copilot agent resource.

Never combine unrelated changes in one batch. After persistence verification, store the verified state under the same round and write `after-state-manifest.json`. If the batch is rejected, restore the before-state, verify it remotely, and write `rollback-state-manifest.json`. Resolve build errors, live-state drift, and missing dependencies before retesting.

### 5. Construction verification

Verify only that the optimized configuration persisted and is published/provisioned: exact instructions/description, components, schemas, connections, permissions, capability flags, solution membership, and package contents. Do not submit evaluation prompts or score responses.

### 6. Delegate retesting to agent-evaluator

Invoke `agent-evaluator` against the optimized deployed version, using:

- the prior dataset/rubric
- the pinned regression baseline
- the required retest IDs from every finding
- all protected critical tests
- the same harness-correct surface and thresholds
- the new agent/instruction/configuration hashes

Do not rewrite evaluator output. Read the new `evaluation-observations.json` and `deployment-gate-summary.md` only after evaluator completion.

### 7. Accept, iterate, or rollback

Accept a batch only when `agent-evaluator` reports the required improvement, affected gates pass, and no protected/critical regression occurs. If results regress or fail the minimum improvement, rollback or apply the next explicitly planned reversible experiment. Run at most `maxOptimizationRounds`; when that limit is reached, stop and report the remaining findings and any architecture or harness redesign they would require.

A deployment-gate PASS ends optimization. A remaining FAIL produces an evidence-backed next-round plan or blocker; never claim success from configuration persistence alone.

## Optimization guidance

### Instructions and routing

- Clarify role, priorities, scope, grounding, exact tool/delegation triggers, authority, ambiguity, untrusted content, failures, and response contract.
- Remove repetition and speculative edge cases; do not request hidden reasoning.
- Keep stable instructions lean and exact; do not embed environment-specific values or secrets.

### Tools and flows

- Improve names/descriptions, when/when-not rules, typed inputs, enums, return/error contracts, timeouts, retry/idempotency, and fallback.
- Combine operations always called sequentially; allow independent read-only calls in parallel within quotas.
- Never hide a broken implementation behind instruction wording.

### Knowledge and groundedness

- Correct source attachment, priority, permissions, scope, indexing, freshness, retrieval configuration, and missing-evidence behavior.
- Do not add a source inventory to the instructions merely because knowledge is attached. In Copilot Studio, configured knowledge is available to the agent by default.
- Use a concise source-agnostic grounding rule by default, for example: "Ground policy claims in configured knowledge; when the available evidence is insufficient, say so and route to the appropriate review path."
- Add a source name only for evidence-backed priority, conflict, scope, access, citation, freshness, or missing-evidence rules. Name only the source necessary for that rule.
- Do not weaken authoritative-source requirements because general model knowledge produced a plausible answer.

### Performance, scalability, and reliability

- Reduce irrelevant context and exposed tools, remove duplicate retrieval, compact tool results, bound tool fan-out/concurrency, and use parallel independent reads.
- Address observed latency/throttling with quotas, capacity, caching/reuse, timeouts, backoff, jitter, idempotency, and graceful degradation.
- Preserve SLOs and pass performance/load retests through `agent-evaluator`.

## Optimization artifact contract

`resources\artifact-contract.json` must validate against the shared local-skills `artifact-contract.schema.json` before any optimization artifact is published.

Store every optimizer-owned artifact under exactly:

```text
<basePath>\output\optimization\
```

Never write optimizer artifacts to the output root, `build`, `evaluation`, requirements/input folders, or external temporary folders. Do not copy or rewrite evaluator artifacts. Never store credentials, tokens, cookies, or secrets.

### Standard run, files, and rounds

- Run ID: `OPT-YYYYMMDD-HHMMSS-XXXXXXXX`, where `XXXXXXXX` is uppercase hexadecimal.
- Required root files:
  1. `optimization-manifest.json`
  2. `optimization-plan.json`
  3. `optimization-change-log.json`
  4. `optimization-run-report.md`
  5. `instruction-audit.json`
  6. `instruction-audit.md`
- Required root directory: `rounds\`
- Round names: `round-001`, `round-002`, and so on, with no gaps or reuse.
- Every attempted round contains:
  1. `before-state-manifest.json`
  2. `after-state-manifest.json`
  3. `round-report.md`
  4. `snapshots\before\`
  5. `snapshots\after\`
- A rejected and rolled-back round also contains:
  1. `rollback-state-manifest.json`
  2. `snapshots\rollback\`

`optimization-plan.json` and `optimization-change-log.json` must validate against their packaged schemas. Every state manifest must validate against `resources\optimization-state-manifest.schema.json`. Never overwrite an earlier round or snapshot; append the next numbered round.

Generate `optimization-manifest.json` last using `resources\lifecycle-artifact-manifest.schema.json`. It must list every optimizer artifact other than the manifest itself by relative path, SHA-256, byte size, kind, required status, and schema. All paths must remain beneath `optimization`.

Packaged naming contract: `resources\artifact-contract.json`.

Before completion run the packaged atomic publisher:

```powershell
python "<skill-dir>\scripts\generate_manifest.py" --root "<basePath>\output\optimization" --status "<complete|blocked|rolled-back>" --summary "<concise optimization outcome>"
```

The optimizer cannot complete or hand off its result until this returns `passed`. The publisher infers the source evaluation run, excludes the manifest from its own inventory, rejects unlisted/extra artifacts, and restores the prior manifest if validation fails.

## Completion

Report:

- agent/harness/environment and verified identity
- evaluation baseline/run IDs consumed
- findings addressed and deferred
- exact changes and hashes
- construction verification
- evaluator retest run IDs and gate decision
- regressions, rollbacks, rounds, and remaining blockers
- optimization artifact paths

Optimization is complete only when the latest `agent-evaluator` deployment gate is PASS and `optimization-manifest.json` passes the packaged validator. Otherwise publish a `blocked` or `rolled-back` result and return it to the orchestrator. Configuration changes alone are not proof of improvement.
