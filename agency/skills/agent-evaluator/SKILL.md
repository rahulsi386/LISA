---
name: "agent-evaluator"
description: "Harness-aware agent evaluation gate. Generates a source-grounded test set, selects the correct test surface from the agent's harness (Standard → the /overview 'Test your agent' pane, with classic canvas / Demo website / Teams fallback; GitHub Copilot → the /agents preview canvas; Copilot chat → M365 Copilot channel), executes every test through Playwright (waiting out slow multi-minute retrieval, dismissing feedback surveys, ignoring interim reasoning steps), records observations/evidence, and e"
---

# Agent Evaluation Gate

## Purpose

Generate a source-grounded evaluation test set from project requirements, transcripts, and configured knowledge sources; select the correct test surface from the agent's **harness**; execute every runnable test against the deployed agent through Playwright; record the actual responses and browser observations; and enforce four mandatory evaluation gates:

1. LLM-as-Judge
2. Tool Use
3. Groundedness
4. Regression Testing

Do not mark the evaluation complete from dataset generation alone. Completion requires dataset generation, harness-correct Playwright execution, recorded observations, scoring, and a deployment-gate decision.

This skill evaluates only. It must never change agent instructions, knowledge, tools, routing, configuration, deployment, or permissions. It produces an evidence-backed `optimizerHandoff`; `agent-optimizer` owns all evaluation-driven changes and invokes this evaluator again for retesting.

When invoked by `cad-orchestrator`, follow `..\workflow-checkpointing.md`. Start the `evaluation`
stage as soon as the `EVAL-*` ID is assigned. Persist the exact next test ID and attempt after every
captured response, evidence write, and score. Resume from that cursor without rerunning completed
tests whose observation and evidence hashes still validate. Commit `evaluation-manifest.json` only
after the deployment-gate decision and packaged validator complete.

## Inputs

Read `lisa-config.json` first, resolve its configured `basePath`, and use only:

1. The latest direct child `<basePath>\output\classification\complexity-classification_<timestamp>.json`.
2. `<basePath>\output\build\agent-build-handoff.json`.
3. Every evaluation source beneath `<basePath>\evalData`.
4. Environment, agent target, thresholds, and other necessary values from `lisa-config.json`.

Reject absolute paths, caller-selected input/output/baseline/handoff paths, traversal outside `basePath`, and classification files outside the canonical stage folder.

Resolve and validate these inputs with `resolve_skill_inputs.py --skill agent-evaluator --config <lisa-config.json>`.

The evaluator output is fixed at `<basePath>\output\evaluation`. `evalData` contains the source-grounded test material, transcripts, and evaluation knowledge files; configured remote URLs remain configuration values rather than filesystem paths.

Required for Playwright execution, unless an equivalent resolvable target is supplied:

- `agentUrl`: published agent or demo website URL

The target may instead be resolved from configured deployment identifiers when supported by the current environment:

- `environmentId`
- `botId`
- `agentName`

Optional configuration:

- `harness`: the agent's harness — `GitHub Copilot`, `Standard`, or `Copilot chat` (for example, from the complexity-classifier JSON `harness` field or the agent-developer record). When absent, detect it (see "Resolve the test surface from the agent's harness").
- `maxConcurrency`: number of concurrent test workers for parallel execution (default 1 = sequential). See "Optional parallel execution".
- `testSetId`
- `mcsConnectionId`
- `evaluationThresholds`
- `playwrightTimeoutMs`
- `expectedCitationMode`
- Builder handoff is mandatory at `<basePath>\output\build\agent-build-handoff.json`; use its harness, IDs, target, knowledge/component inventory, quality targets, risks, and recommendations, but verify deployed state independently.

If required config-relative input is missing, do not invent paths or sources. Write the blocker to `<basePath>\output\evaluation\deployment-gate-summary.md`. If the browser target cannot be resolved, still generate the dataset and rubric, mark every execution as `BLOCKED`, and fail the deployment gate rather than claiming a successful evaluation.

## Resolve the test surface from the agent's harness (MANDATORY)

The agent's harness determines which test surface — and therefore which URL and controls — Playwright must use. **Using the wrong surface produces false failures.** Choose the surface as follows:

- **Standard harness** (classic authoring: a Custom GPT component, classic Topics, `GenerativeAIRecognizer`, `GPTSettings`) → the agent-workspace **"Test your agent" pane on the `/overview` page** (preview host, `/bots/` route):
  `https://copilotstudio.preview.microsoft.com/environments/<environmentId>/bots/<botId>/overview`
  This docked test pane is the reliable surface for a Standard-harness agent. **Do not** use the new-experience `/agents/<botId>/preview` tab for a Standard-harness agent — it commonly returns `BotDefinitionOverride contains invalid YAML and could not be parsed` for classic agents (a surface mismatch, not an agent defect). If the `/overview` test pane is unavailable, fall back in order to: (a) the classic maker-portal canvas `https://copilotstudio.microsoft.com/environments/<environmentId>/bots/<botId>/canvas` — note this canvas can intermittently fail with a client-side `Unable to connect.` / `Cannot read properties of undefined` portal error; (b) a published **Demo website** channel URL; (c) **Test in Teams**.
- **GitHub Copilot harness** (new agent experience: the `/agents/<id>` UI, skills, memory) → the **new preview canvas / Preview tab**:
  `https://copilotstudio.preview.microsoft.com/environments/<environmentId>/agents/<botId>/preview`
- **Copilot chat harness** (extends Microsoft 365 Copilot Chat) → test in the published **Microsoft 365 Copilot** channel, or a fallback surface above.

Rules:
- Prefer an explicit `agentUrl` (a published demo website or channel) when one is supplied; otherwise build the harness-matched URL above from `environmentId` and `botId`.
- If `harness` is not provided, **detect it before opening any surface**: inspect the deployed agent definition — a `GenerativeAIRecognizer` with a Custom GPT / classic Topics / `GPTSettings` is a **Standard-harness** agent; a new-experience agent that uses skills, memory, or the `/agents/<id>` surface is a **GitHub Copilot harness** agent.
- A surface that returns a **definition/parse error** (`BotDefinitionOverride contains invalid YAML`) or a **client-side portal error** (`Unable to connect.`, a `subscribe`/undefined JavaScript error) is a **surface/tooling failure, not proof the agent is broken**. Move to the next surface in the harness-appropriate fallback order and record which surface finally worked. Only conclude an agent-definition defect after **every** appropriate surface fails; never attribute a single surface's error to a defective agent.
- Record the surface finally used (for example `overview-test-pane`, `preview-canvas`, `classic-canvas`, `m365-copilot`, or `published-url`).

## Evaluation artifact contract (MANDATORY)

`resources\artifact-contract.json` must validate against the shared local-skills `artifact-contract.schema.json` before any evaluation artifact is published.

Store every evaluator-owned artifact under exactly:

```text
<basePath>\output\evaluation\
```

Write nothing evaluation-related to the output root, `build`, `optimization`, requirements/input folders, or external temporary folders. All evidence and temporary worker files remain beneath `evaluation`; delete token-bearing `storage-state.json` before completion.

### Standard run and names

- Run ID: `EVAL-YYYYMMDD-HHMMSS-XXXXXXXX`, where `XXXXXXXX` is uppercase hexadecimal.
- Required files:
  1. `evaluation-manifest.json`
  2. `evaluation-dataset.json`
  3. `evaluation-dataset.csv`
  4. `evaluation-rubric.json`
  5. `evaluation-observations.json`
  6. `regression-baseline.json`
  7. `evaluation-run-report.md`
  8. `deployment-gate-summary.md`
- Required directory: `evidence\`
- Evidence names: `EVAL-NNN-attempt-NN.png` (or `.jpg`, `.jpeg`, `.json` for equivalent browser evidence). Retests increment `attempt-NN`; never overwrite earlier evidence.

Use UTF-8. JSON must be valid and machine-readable. CSV must quote fields containing commas, quotes, arrays, or line breaks.

The JSON files must validate against their packaged schemas: `evaluation-dataset.schema.json`, `evaluation-rubric.schema.json`, `evaluation-observations.schema.json`, and `regression-baseline.schema.json`. Generate `evaluation-manifest.json` last and inventory every evaluator artifact other than the manifest itself by relative path, hash, size, kind, required status, and schema.

Packaged naming contract: `resources\artifact-contract.json`.

Before completion run the packaged atomic publisher:

```powershell
python "<skill-dir>\scripts\generate_manifest.py" --root "<basePath>\output\evaluation" --status "<pass|fail|blocked>" --source-run "<BLD run ID>" --summary "<concise evaluation outcome>"
```

The evaluator cannot issue a gate decision until this returns `passed`. The publisher excludes the manifest from its own inventory, rejects unlisted/extra artifacts, and restores the prior manifest if validation fails.

## Workflow

### Step 1: Load and validate project configuration

1. Load `lisa-config.json` and resolve its configured `basePath`.
2. Resolve only the canonical classification, build handoff, `evalData`, and evaluation output paths.
3. Create `<basePath>\output\evaluation\` and its `evidence\` subfolder.
4. Validate that `evalData` and every required canonical input exist and are readable.
5. Treat configured `knowledgeSources` as authoritative. Treat additional sources mentioned in requirements or transcripts as supplemental and label them accordingly; do not silently promote them to authoritative sources.
6. Resolve the published agent target from `agentUrl` or supported deployment identifiers.
7. Resolve the agent's **harness** (from `harness`, or detect it from the agent definition) and record it; it selects the test surface in Step 5.
8. Record missing, inaccessible, or ambiguous inputs as blockers. Do not guess.

### Step 2: Ingest and trace source material

Read and analyze:

- Evaluation documents beneath `<basePath>\evalData`
- Meeting and chat transcripts beneath `<basePath>\evalData`
- Every configured knowledge source that is accessible

Extract and retain source traceability for:

- Business goals
- Personas and access roles
- User intents and representative phrasing
- Factual questions and source-grounded answers
- Expected agent responses and required response elements
- Required tools, actions, parameters, and side effects
- Citation or attribution expectations
- Out-of-scope requests
- Safety, privacy, and compliance constraints
- Clarification and disambiguation behavior
- Success criteria and known failure modes
- Critical scenarios that must not regress

For each extracted fact or expected answer, retain the source name plus the most precise available locator, such as heading, page, paragraph, row, or URL fragment. Do not create expected facts that are absent from the sources.

### Step 3: Generate the evaluation test set

Create representative test cases automatically from requirements and knowledge sources. Include direct factual questions, realistic user prompts, paraphrases, multi-intent requests where required, tool/action scenarios, clarification cases, unsupported or out-of-scope requests, safety cases, and critical regression scenarios. Every critical or high-priority requirement must be covered by at least one test case.

Each test case must contain a concrete `userPrompt` and a concrete canonical `expectedResponse`. `expectedResponse` must state the answer the agent should return, including required facts, caveats, citations, confirmations, or refusal language. Do not use phrases such as "respond appropriately" or copy `expectedBehavior` into `expectedResponse`. When wording can vary, provide a canonical response and use `responseAssertions` to identify the required semantic elements.

Use this schema for `evaluation-dataset.json`:

```json
{
  "schemaVersion": "1.0",
  "generatedAt": "ISO-8601 timestamp",
  "testSetId": "Stable test-set identifier",
  "sources": [
    {
      "name": "Source name",
      "type": "requirement | meeting-transcript | chat-transcript | knowledge-source",
      "location": "Configured path or URL",
      "authority": "authoritative | supplemental"
    }
  ],
  "testCases": [
    {
      "id": "EVAL-001",
      "scenario": "Short scenario name",
      "sourceType": "requirement | meeting-transcript | chat-transcript | knowledge-source",
      "sourceReferences": [
        {
          "source": "File or source name",
          "locator": "Heading, page, paragraph, row, or URL fragment"
        }
      ],
      "userPrompt": "Exact prompt to submit to the agent",
      "expectedResponse": "Concrete canonical answer expected from the agent",
      "expectedBehavior": "Observable behavior, action, or interaction requirements",
      "responseAssertions": [
        "Required fact, caveat, citation, confirmation, or refusal"
      ],
      "expectedKnowledgeSources": ["Configured source name"],
      "requiredTools": ["Expected tool or action name"],
      "prohibitedBehavior": ["Behavior, claim, or action that must not occur"],
      "evaluationTypes": ["LLM_AS_JUDGE", "TOOL_USE", "GROUNDEDNESS", "REGRESSION"],
      "severity": "critical | high | medium | low",
      "passCriteria": "Unambiguous pass condition",
      "failCriteria": "Unambiguous fail condition"
    }
  ]
}
```

Rules:

- `expectedResponse` is mandatory and must never be empty.
- `sourceReferences` is mandatory and must substantiate the expected response.
- Use an empty array for `requiredTools` only when no tool or action is expected.
- Include `REGRESSION` for critical scenarios and for cases mapped to a baseline; do not add it mechanically when no regression comparison is possible.
- Do not require exact wording unless the source mandates exact legal, safety, compliance, or confirmation text.
- Keep prompts executable as written; do not leave placeholders unresolved.

Create `evaluation-dataset.csv` with these columns in this order:

`id,scenario,sourceType,sourceReferences,userPrompt,expectedResponse,expectedBehavior,responseAssertions,expectedKnowledgeSources,requiredTools,prohibitedBehavior,evaluationTypes,severity,passCriteria,failCriteria`

Serialize array and object fields as compact JSON strings inside the CSV cells.

### Step 4: Build the evaluation rubric

Create `evaluation-rubric.json` with explicit scoring criteria for each applicable evaluation type. Use a 0-4 scale unless `evaluationThresholds` specifies another scale:

- `4`: fully satisfies the criterion with no material issue
- `3`: satisfies the criterion with a minor non-blocking issue
- `2`: partially satisfies the criterion with a material omission or ambiguity
- `1`: minimally satisfies the criterion or contains a major error
- `0`: fails, contradicts sources, performs a prohibited action, or has no usable response

The rubric must define:

- LLM-as-Judge: correctness, completeness, relevance, instruction adherence, and handling of prohibited behavior
- Tool Use: correct tool selection, required invocation, parameter correctness, execution result, and absence of unintended side effects. Mark `NOT_APPLICABLE` when the agent has no tools, agent flows, or connected agents.
- Groundedness: factual support, expected source use, citation quality when required, and absence of unsupported claims. **If the agent reports it could not retrieve a configured knowledge source (for example "only the filename was returned" / "the codeset content was not returned") and answers from model/general knowledge instead, treat that as a groundedness failure or material deduction even when the answer looks correct — it means the agent is not grounded in the configured authoritative source and may violate a "use only configured sources" rule.**
- Regression: comparison with the configured baseline for response quality, tool behavior, grounding, and previously passing critical behavior

Define per-gate thresholds and the overall deployment threshold. A critical prohibited behavior, safety violation, unsupported high-impact claim, wrong side effect, or unexecuted critical test is an automatic gate failure regardless of average score.

### Step 5: Execute every test through Playwright

Use Playwright browser tools to test the deployed agent through its user interface. Do not substitute an API, direct service call, synthetic answer, or manually authored actual response for the browser run.

1. Open the **harness-matched test surface URL** resolved in "Resolve the test surface from the agent's harness". For a **Standard-harness** agent this is the `/overview` **Test-your-agent** pane; for a **GitHub Copilot harness** agent the `/agents/<id>/preview` canvas; for **Copilot chat** the Microsoft 365 Copilot channel. Do not default to whichever portal was most recently used for other agents. If the surface errors, move through the harness-appropriate fallback order before treating it as an agent blocker.
2. If authentication or consent requires user interaction, stop and record the exact blocker; mark affected tests `BLOCKED` with `eligibleForOptimization=false`. Never request, enter, log, or persist credentials.
3. Confirm the surface loaded a working chat control before running tests. Discover controls from the current accessibility snapshot; prefer accessible roles/names and stable test ids. On the `/overview` Test-your-agent pane the controls are typically: reset = `chat-restart-button`, input = `send box text area` (placeholder "Ask a question or describe what you need"), send = `send box send button`.
4. Before each test, start a new conversation with the reset control (`chat-restart-button` on the overview pane) and verify prior messages are absent. If isolation cannot be established, mark the case `BLOCKED` rather than contaminating results.
5. Submit the test case's `userPrompt` exactly as stored in the dataset.
6. **Wait for the full final response, allowing for slow generation.** Knowledge-grounded agents can take **two to three minutes** to answer (multiple retrieval rounds). Use `playwrightTimeoutMs` when configured; otherwise poll with a generous bounded timeout (up to about 180 seconds per turn). The answer is complete only when the transcript is **stable** and contains the expected final structure. **Do not treat intermediate reasoning/status steps as the final response** — for example "Searching through knowledge sources…", "Thinking…", "Refining knowledge query…", "Crafting the final response…", or "Connectivity Status: Connected".
7. **Dismiss interrupting dialogs** that can block the transcript, such as the Copilot Studio feedback / NPS survey ("How likely are you to recommend Copilot Studio…") — click its `Cancel` (or `Close`) button and continue. Never submit such surveys.
8. Capture the complete visible **final** response, citations or source links, tool/action status, confirmations, errors, and elapsed time. Note that the test pane may also render maker-only **reasoning/chain-of-thought** steps; evaluate the final user-facing message, and remember these internal reasoning traces are usually not shown to end users in production channels (do not fail an agent solely because an internal reasoning step is visible in the maker test pane, but do record any sensitive disclosure in the final response).
9. Save a screenshot under `<basePath>\output\evaluation\evidence\` when supported. Record its relative path. If screenshot storage is unavailable, record the accessible browser evidence used instead.
10. Retry once only for a demonstrably transient browser or page-loading failure, or a one-time surface/harness-mismatch switch. Never retry merely because the agent gave a poor answer. Record both attempts and the reason.
11. Do not perform destructive or externally visible actions unless the test environment and source requirements explicitly authorize them. For such tests, require a sandbox/test target or stop at the confirmation step and evaluate that behavior.

A Playwright run is evidence, not a verdict. Record what was visibly observed without inferring hidden tool calls, hidden grounding, or successful side effects. If required tool use cannot be observed or verified, record `NOT_OBSERVABLE` and fail or block that criterion according to the rubric.

#### Optional parallel execution

When `maxConcurrency` > 1, tests may run concurrently to shorten slow Standard-harness runs, subject to these constraints:

- Use a **local Playwright worker pool**: one browser, one **isolated browser context per test** (each context = a separate, isolated conversation). Seed each context from a shared authenticated `storageState.json` so workers do not re-authenticate. Never use the raw Direct Line API — execution must stay on the real UI surface.
- Keep concurrency modest (typically 3–5). Treat throttling (`429`, timeout, `Unable to connect`) as **retryable**, not an agent failure; requeue with backoff and staggered starts.
- Keep every **multi-turn** test on a single worker/context, run sequentially within it. Only independent single-turn tests are distributed.
- Store all parallel helpers (`storageState.json`, `prompts.json`, `responses.json`, worker scripts) inside `<basePath>\output\evaluation\`, and delete `storageState.json` when finished.
- Scoring (Step 7) is deterministic and can always run in parallel/offline after responses are captured, regardless of `maxConcurrency`.

### Step 6: Record observations

Write `evaluation-observations.json` using this schema:

```json
{
  "schemaVersion": "1.1",
  "runId": "EVAL-YYYYMMDD-HHMMSS-XXXXXXXX",
  "testSetId": "Configured or generated test-set identifier",
  "agent": {
    "name": "Configured agent name",
    "url": "Resolved harness-matched browser target",
    "harness": "GitHub Copilot | Standard | Copilot chat",
    "surface": "overview-test-pane | preview-canvas | classic-canvas | m365-copilot | published-url",
    "environmentId": "Configured environment identifier",
    "agentId": "Configured agent or bot identifier"
  },
  "startedAt": "ISO-8601 timestamp",
  "completedAt": "ISO-8601 timestamp",
  "summary": {
    "total": 0,
    "passed": 0,
    "failed": 0,
    "blocked": 0,
    "notRun": 0
  },
  "results": [
    {
      "testCaseId": "EVAL-001",
      "scenario": "Scenario name",
      "userPrompt": "Exact submitted prompt",
      "expectedResponse": "Canonical expected response",
      "actualResponse": "Complete final response captured from the agent",
      "status": "PASS | FAIL | BLOCKED | NOT_RUN",
      "startedAt": "ISO-8601 timestamp",
      "completedAt": "ISO-8601 timestamp",
      "durationMs": 0,
      "attempts": 1,
      "playwrightObservations": {
        "conversationReset": true,
        "responseCompleted": true,
        "surfaceUsed": "overview-test-pane | preview-canvas | classic-canvas | m365-copilot | published-url",
        "citationsObserved": ["Visible citation text or URL"],
        "toolActivityObserved": ["Visible tool or action evidence"],
        "uiErrors": ["Visible error text"],
        "sideEffectsObserved": ["Verified visible side effect"],
        "evidence": ["evidence/EVAL-001-attempt-01.png"],
        "notes": "Objective UI observations only"
      },
      "gateResults": {
        "llmAsJudge": {
          "status": "PASS | FAIL | NOT_APPLICABLE | NOT_OBSERVABLE",
          "score": 0,
          "rationale": "Comparison with expected response and assertions"
        },
        "toolUse": {
          "status": "PASS | FAIL | NOT_APPLICABLE | NOT_OBSERVABLE",
          "score": 0,
          "rationale": "Observed tool behavior and result"
        },
        "groundedness": {
          "status": "PASS | FAIL | NOT_APPLICABLE | NOT_OBSERVABLE",
          "score": 0,
          "rationale": "Claim-level comparison with source references; note any configured-source retrieval failure"
        },
        "regression": {
          "status": "PASS | FAIL | NOT_APPLICABLE | NOT_OBSERVABLE",
          "score": 0,
          "rationale": "Comparison with baseline"
        }
      },
      "assertionResults": [
        {
          "assertion": "Required semantic element",
          "status": "PASS | FAIL | NOT_OBSERVABLE",
          "evidence": "Quoted response text or browser observation"
        }
      ],
      "prohibitedBehaviorObserved": [],
      "failureReasons": [],
      "blocker": null
    }
  ],
  "gateSummary": {
    "llmAsJudge": {},
    "toolUse": {},
    "groundedness": {},
    "regression": {}
  },
  "optimizerHandoff": {
    "evaluationDecision": "PASS | FAIL | BLOCKED | NOT_RUN",
    "eligibleForOptimization": false,
    "findings": [
      {
        "id": "OPT-FINDING-001",
        "testCaseIds": ["EVAL-001"],
        "severity": "critical | high | medium | low",
        "failedGates": ["LLM_AS_JUDGE | TOOL_USE | GROUNDEDNESS | REGRESSION"],
        "observedSymptom": "Evidence-based description only",
        "evidence": ["Quoted response, observation, or relative evidence path"],
        "suspectedChangeSurface": "instructions | tool-description | tool-schema | knowledge | orchestration | connected-agent-routing | permissions | implementation | performance | platform-or-surface",
        "requiredRetestScope": ["EVAL-001"],
        "doNotOptimizeReason": null
      }
    ]
  }
}
```

Do not leave a case as `PASS` when an applicable mandatory gate failed or was not observable. Do not omit failed, blocked, timed-out, or not-run cases.

### Step 7: Evaluate the mandatory gates

For each test case:

1. Compare `actualResponse` semantically with `expectedResponse`, `responseAssertions`, `expectedBehavior`, `passCriteria`, and `failCriteria`.
2. Score only the evaluation types listed for that test case.
3. Verify factual claims against `sourceReferences`; source presence alone is not proof of groundedness. If the agent states it could not retrieve a configured knowledge source and used model/general knowledge instead, deduct or fail groundedness accordingly and note the retrieval failure.
4. For tool cases, distinguish requested intent, visible invocation evidence, completion, and verified side effect. A plausible answer is not proof that a tool ran.
5. For regression cases, compare only against `<basePath>\output\evaluation\regression-baseline.json` when it exists. If no valid baseline exists, mark regression `NOT_APPLICABLE`, create the current `regression-baseline.json` (inside the `evaluation` folder), and state that regression was not enforced for this initial run.
6. Apply automatic-failure rules before aggregate thresholds.
7. Determine the test status from the applicable gate results and rubric.

Populate `regression-baseline.json` only from completed, reviewed run data. Include test-case ID, prompt, expected response, actual response, gate scores, overall status, agent identifiers, and timestamp. Never overwrite an approved baseline silently; preserve or version it according to the configured path and project conventions.

### Step 8: Produce the run report

Create `evaluation-run-report.md` (in the `evaluation` folder) with these sections in this order:

1. `# Agent Evaluation Run Report`
2. `## Run Metadata` (include the agent's harness and the harness-matched surface actually used)
3. `## Source and Requirement Coverage`
4. `## Execution Summary`
5. `## Gate Summary`
6. `## Test Case Observations`
7. `## Failures and Blockers`
8. `## Optimizer Handoff`
9. `## Regression Comparison`
10. `## Overall Decision`

In `## Test Case Observations`, use this exact format for every test case:

```markdown
### EVAL-001: Scenario name

**User prompt:** Exact submitted prompt

**Expected response:** Canonical expected response

**Actual response:** Complete captured final response, or `Not available` when blocked/not run

**Playwright observations:** Objective notes about the surface used, reset state, response completion, citations, tool activity, errors, side effects, timing, retries, and evidence.

| Gate | Status | Score | Rationale |
|---|---|---:|---|
| LLM-as-Judge | PASS/FAIL/NOT_APPLICABLE/NOT_OBSERVABLE | 0-4 | Evidence-based rationale |
| Tool Use | PASS/FAIL/NOT_APPLICABLE/NOT_OBSERVABLE | 0-4 | Evidence-based rationale |
| Groundedness | PASS/FAIL/NOT_APPLICABLE/NOT_OBSERVABLE | 0-4 | Evidence-based rationale |
| Regression | PASS/FAIL/NOT_APPLICABLE/NOT_OBSERVABLE | 0-4 | Evidence-based rationale |

**Overall result:** PASS/FAIL/BLOCKED/NOT_RUN

**Failure reasons or blocker:** None, or a specific evidence-based explanation.
```

Quote actual agent text accurately. Clearly distinguish observed evidence from evaluator judgment. Do not rewrite a failed response to make it appear correct.

In `## Optimizer Handoff`, list only evidence-backed findings from `optimizerHandoff`. Do not modify the agent, draft replacement instructions, or claim a root cause that was not observed. Set `eligibleForOptimization=false` for authentication/consent blockers, wrong test surfaces, portal failures, inaccessible sources, or other platform/tooling blockers that must be fixed before agent optimization.

### Step 9: Enforce the deployment gate

Create `deployment-gate-summary.md` (in the `evaluation` folder) containing:

- Overall decision: `PASS` or `FAIL`
- Agent harness and the harness-matched test surface actually used
- Counts of passed, failed, blocked, and not-run tests
- Result of each mandatory gate
- Critical and high-severity failures
- Blockers and unobservable criteria (distinguish a surface/tooling failure from a genuine agent defect)
- Regression status and baseline used
- Artifact paths (all under `<basePath>\output\evaluation\`)
- Required remediation and retest scope
- Optimizer-handoff eligibility and finding IDs

The deployment gate passes only when:

- The agent was exercised on the harness-matched surface
- Every critical test was executed and passed
- No automatic-failure condition occurred
- All applicable mandatory gates meet their configured thresholds
- No required test is blocked or not run
- The generated dataset has complete source traceability, prompts, and expected responses
- Playwright evidence and observations exist for every executed case
- The packaged artifact validator returns `passed`

If any condition is unmet, set the overall decision to `FAIL`. Never describe a dataset-only run, a partially executed run, a run on the wrong harness surface, or a run with missing evidence as passed.

## Quality and Integrity Rules

- **Write every artifact under the single `<basePath>\output\evaluation\` folder; never write evaluation output elsewhere.** Every final path must satisfy `resources\artifact-contract.json`; `evaluation-manifest.json` must verify all relative paths, hashes, and sizes.
- Select the test surface from the agent's harness; never let a previously used portal decide it. For a Standard-harness agent, prefer the `/overview` Test-your-agent pane and fall back only through the documented order.
- Generate both the questions or user prompts and their expected responses from the supplied evidence.
- Keep expected answers source-grounded and independently derived before testing the agent; never derive an expected answer from the agent's actual response.
- Use Playwright for execution and capture the agent's final response exactly as shown; wait out slow multi-minute generations and ignore interim reasoning/status steps.
- Start each single-turn test in an isolated conversation using the reset control; when running in parallel, use one isolated browser context per test.
- Record every outcome, including errors, timeouts, blockers, and unobservable behavior.
- Do not fabricate citations, tool invocations, side effects, scores, browser evidence, or baseline comparisons.
- Do not attribute a surface/tooling error (invalid-YAML parse error, `Unable to connect`, portal JavaScript error) to a broken agent; verify on the harness-appropriate surfaces first.
- Treat a reported failure to retrieve a configured knowledge source (model-knowledge fallback) as a groundedness problem even when answers look correct.
- Redact secrets and authentication data, but do not redact ordinary response content needed to explain a failure. Keep any `storageState.json` inside the `evaluation` folder and delete it when done.
- Preserve test IDs across runs so regression comparisons remain stable.
- If a source changes materially, version the affected test and explain the baseline impact.
- A deployment-gate pass must be supported by the artifacts, not by narrative judgment alone.
