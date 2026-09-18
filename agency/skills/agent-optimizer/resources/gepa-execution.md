# Agency GEPA Execution Protocol

GEPA 0.1.4 supplies actual reflective evolution and per-validation-example Pareto selection.
The host supplies proposals and Evaluator supplies measurements. No provider SDK, remote
endpoint, credential file, synthetic runtime score, or hidden reasoning is used by the driver.
The pilot optimizes only existing instructions, not tools, code, requirements, rubrics or agent
architecture. It is disabled by default. Missing prerequisites when enabled are blockers.
Supported harness values are `Standard` and `GitHub Copilot` (GHCP means the Copilot Studio
harness, not a separate model provider). The target and shadow must use the same canonical value.

## Prepare

1. Install `requirements-gepa.txt` in the Agency execution interpreter (Python 3.11-3.14).
2. Validate the canonical build and evaluation. Builder must emit `instructionOptimization`
   in its handoff. Pull live instructions, confirm they match the builder seed, and complete
   the mandatory audit. Eligible evaluator findings must identify the `instructions` surface.
3. Create `optimization-plan.json` normally. Add `policy.gepa` matching `gepa-policy.schema.json`.
   Copy configured `optimization.gepa` values exactly. Choose disjoint `trainIds`,
   `validationIds`, `holdoutIds`, and `protectedTestIds` covering the frozen dataset; put every
   critical case in the protected set. Split by scenario/source family, not just random
   paraphrases. Freeze the metric before search: arithmetic mean of applicable mandatory gate
   scores divided by their rubric maximum, in [0,1]. Never tune normalization between candidates.
4. Add exact `shadowAgent` identity, `reflectionProvider`, `reflectionModel`, `reflectionApproved`,
  `isolationVerified`, and `isolationEvidence`. Confirm shadow and target are different agents of
  the same supported harness in the exact configured test environment. A shadow is a remote resource, not an offline
   simulation. Obtain scope approval before creating it. Disable triggers, restrict to test users,
   and verify read-only tools and isolated connections/data. No binding or state-changing tools
   are supported. Verify comparable knowledge readiness, authentication, model configuration and
   component inventory; record mapping differences. Do not share with production users.
5. Evaluator runs `gepa_candidate.py freeze --config <CONFIG>`. This freezes its own input files
   beneath `output/evaluation/gepa/<OPT-ID>/baseline/` without modifying the canonical files.
6. Optimizer runs `gepa_optimize.py init --config <CONFIG>`. The driver pins the config, build,
   frozen evaluation, seed, contract, budget and policy in a hash-bound session.

Example plan policy (replace verified values and use actual dataset IDs):

```json
{
  "enabled": true,
  "seed": 7,
  "searchMetricCalls": 24,
  "maxMetricCalls": 60,
  "maxReflectionCalls": 6,
  "maxElapsedSeconds": 7200,
  "minimumImprovement": 0.05,
  "maxReflectionCostUsd": null,
  "trainIds": ["EVAL-001"],
  "validationIds": ["EVAL-002"],
  "holdoutIds": ["EVAL-003"],
  "protectedTestIds": ["EVAL-004"],
  "shadowAgent": {"agentId": "verified-shadow-id", "environmentId": "verified-env-id", "harness": "Standard"},
  "isolationVerified": true,
  "isolationEvidence": "Reference the verified trigger, connection, identity and component inventory evidence.",
  "reflectionApproved": true,
  "reflectionProvider": "approved-provider",
  "reflectionModel": "approved-model"
}
```

For GHCP, change `shadowAgent.harness` to `GitHub Copilot` and add this to `policy.gepa` and the
configured `optimization.gepa` before the initial build/evaluation:

```json
"githubCopilot": {
  "memoryMode": "disabled",
  "creditsVerified": true
}
```

Set `creditsVerified` only after verifying environment allocation and approved capacity. Use
`reset-between-tests` when memory is required and a reproducible reset exists; use `disabled`
only when memory is disabled on both target and shadow. Otherwise block. Preserve fixed skills,
knowledge, tools, workflow definitions and capability flags across candidates. Ensure uploaded
skills do not add unapproved side effects. Reset ephemeral sandbox/native-file state as well as
conversation state; never disable required capabilities or silently remove connected agents.
The pilot still excludes multi-agent optimization and binding/state-changing tool scenarios.

### Harness Authoring and Test Surfaces

| Harness | Instruction persistence | Candidate and target tests |
|---|---|---|
| Standard | Existing PAC pull/change/push/publish/pull path | Existing harness-correct evaluator routing, normally `/bots/<agentId>/overview` |
| GitHub Copilot | Builder Section B's `cli-copilot` workspace; verify PAC support and live signature before push/publish/pull. If unsupported, new-agent UI keyboard insertion, Save/reload and Dataverse read-back | Pinned `/environments/<environmentId>/agents/<agentId>/preview` on `copilotstudio.preview.microsoft.com`; `surfaceUsed: preview-canvas` |

Before provisioning a GHCP shadow, verify `pac copilot init help` exposes `--authoring-mode`
and `cli-copilot`. Use `--authoring-mode cli-copilot` when creating through PAC, not the Standard
template. If PAC cannot author this surface, use Builder's new-agent UI fallback. Keep the shadow
workspace and construction evidence under `output/optimization/gepa/`; do not write to the
committed build directory. For rich-text edits use real keyboard insertion, not Playwright
`fill()`. Always read back exact instructions and the live configuration signature:

```json
{"authoringModel": "CliCopilot", "recognizer": "CLICopilotRecognizer", "template": "cliagent-1.0.0"}
```

Record `authoringPath` as `pac-cli-copilot` or `new-agent-ui`. A label in an artifact is not proof
of the live signature. Persist evidence of the pull/read-back. Do not use the Standard overview
pane or convert the agent's harness when a GHCP preview is unavailable; report a surface blocker.
Use the same authoring/read-back path for promotion and rollback, and verify the original target
identity before either operation. Changing harness or memory policy requires a new GEPA session.

## Service One Request

Run `gepa_optimize.py advance --config <CONFIG>`. Exit 3 means `awaiting-host`, not failure.
Read only `output/optimization/gepa/pending.json` and its referenced request, not a recursive
latest-file search. Requests, candidates and sealed results are immutable. Run one writer at a
time. Never remove or replace prior requests to force replay to follow a different path.

For `evaluation`, Optimizer applies the exact candidate from `gepa/candidates/<candidateId>.json`
to the verified shadow through its harness-specific path above. Persist remote intent before each write and receipt after
read-back. Evaluator tests exactly `testIds` through the harness-correct UI, resetting conversation
state between cases. Store evidence and `response.json` under
`output/evaluation/gepa/<OPT-ID>/<requestId>/`. Do not advance the top-level evaluation stage.

Required response shape:

```json
{
  "requestSha256": "canonical request hash from pending.json",
  "candidateId": "exact request candidateId",
  "instructionSha256": "exact request instructionSha256",
  "agent": {"agentId": "verified-shadow-id", "environmentId": "verified-env-id", "harness": "Standard"},
  "partition": "train",
  "owner": "agent-evaluator",
  "deploymentGate": false,
  "evaluatorRunId": "EVAL-20260917-120000-ABCDEF12",
  "policyPassed": true,
  "policyEvidence": "Review immutable clauses, unsupported references, instruction conflicts and approved component names.",
  "persistenceReceipt": {"verified": true, "operationId": "checkpoint-operation-id", "instructionSha256": "exact hash", "agent": {"agentId": "verified-shadow-id", "environmentId": "verified-env-id", "harness": "Standard"}},
  "results": [{
    "testCaseId": "EVAL-001",
    "status": "PASS",
    "score": 0.9,
    "actualResponse": "Exact observed response, retained only in evaluator evidence.",
    "feedback": "Redacted actionable observations. State general failure mechanisms without embedding test answers.",
    "approvedForReflection": true,
    "safetyViolation": false,
    "evidence": [{"path": "evidence/EVAL-001-attempt-01.json", "sha256": "actual file hash"}]
  }]
}
```

GHCP requests additionally contain `payload.execution` with a derived preview URL, memory mode,
and expected `harnessSignature`. Retain the exact requested GHCP `agent` identity in the response.
Add the live `harnessSignature` and `authoringPath` to `persistenceReceipt`, and these fields to
each test result (the URL must identify the requested shadow, not the original target):

```json
"playwrightObservations": {
  "surfaceUsed": "preview-canvas",
  "surfaceUrl": "https://copilotstudio.preview.microsoft.com/environments/verified-env-id/agents/verified-shadow-id/preview",
  "conversationReset": true,
  "memoryState": "disabled"
}
```

For `reset-between-tests`, record `memoryState: reset` only after verifying the reset for that
case, including protected cases. Use the ordinary evidence files to substantiate these fields.
Both initial and final target evaluations require these per-test observations with the target
preview URL and a top-level `gepaExecution` object containing the live `harnessSignature` and
`authoringPath`. They do not use the candidate `persistenceReceipt` wrapper. If an earlier GHCP
baseline lacks this evidence, rerun initial evaluation under the fixed memory policy before
freezing it. Do not manufacture execution metadata for an old run.

Use actual scores, IDs, hashes and evidence, never the illustrative values above. Return every
requested test in order. In the evidence JSON include the ordinary evaluator gate results,
assertions, scoring derivation, duration, citations and visible tool activity. `FAIL` is a valid
noncritical search result. `BLOCKED`/`NOT_RUN`, safety violations and protected failures cannot
become search scores: sealing rejects them and the host reports a blocker. Stop the run, preserve
evidence and reconcile shadow state rather than rewriting a sealed result. Static clause checks
do not prove semantic safety; the policy review and behavioral safety cases are mandatory.

After a host/platform blocker, run `gepa_optimize.py abort --config <CONFIG> --reason "<non-secret reason>"`
to seal a blocked search outcome, then publish the optimizer's blocked result. Abort does not
restore or delete remote resources: reconcile and document their state first. Terminal results
are sealed; another `advance` returns the same result and cannot reopen the held-out search.

Evaluator seals with `gepa_candidate.py seal --config <CONFIG>`.

For `reflection`, review the exact request for data/provider approval. Use the approved host
model to return complete instruction text, preserving section headings, protected text and
mandatory clauses. Do not include held-out feedback, raw screenshots, hidden reasoning, secrets
or test answers. Store `response.json` beside the request with `requestSha256`, `text`, `provider`,
`model`, `approvedForReflection: true` and `costUsd` (actual nonnegative cost, or null if unknown).
Optimizer seals with `gepa_optimize.py seal-reflection --config <CONFIG>`.

Run `advance` again after each seal. It deterministically replays the pinned GEPA engine from
the seed using receipts; no completed external call is repeated. Upstream pickle state is never
loaded. GEPA's internal exception retries cannot swallow the host pause signal.

## Budgets and Selection

`searchMetricCalls` stops search at iteration boundaries. `maxMetricCalls` is the hard total
request limit, including appended protected tests and the two held-out comparisons; reserve
enough headroom for a full iteration plus holdout. `maxReflectionCalls` and elapsed time bound
host work. Count spent evaluations even when a candidate is rejected. A USD limit stops further
work after reported costs reach it, or when costs are unknown; it is not a preauthorized provider
billing cap and can overshoot by the last call. Use provider-side caps for hard currency limits.
No runtime latency or Copilot Credits savings are inferred from instruction size.

Selection uses GEPA's per-example Pareto frontier, not a claimed globally optimal multi-objective
front. A selected validation gain must meet `minimumImprovement`, then the seed and selected
candidate are independently evaluated on the held-out partition. Held-out feedback never enters
reflection. Do not retry search against the same holdout after rejection; prepare a new approved
experiment if needed. This single-run comparison is not statistical proof; release acceptance
still requires repetitions and a comparable-budget evidence-guided baseline.

`ready-for-promotion` authorizes only a planned target experiment. `no-improvement`,
`holdout-rejected`, `budget-exhausted`, and `blocked` retain the original target. Never treat them
as demonstrated improvement. Restore the shadow to its seed or preserve it for approved review;
cleanup/deletion requires separate explicit consent and must not delete target resources.

## Outcome Files

- `gepa-run.json`: engine/version, seed, status, candidate lineage, Pareto membership, selected hash,
  search and held-out deltas, instruction bytes, evaluator runs and measured/unknown cost.
  Execution records identify the harness and shadow ID; GHCP adds preview surface and memory mode.
- `gepa/`: immutable session, candidate texts, host requests and reflection receipts; pending cursor.
- `optimization-outcome.json`: computed strategy, execution summary, search impact and independently
  verified final target impact. `not-measured` means no comparable target result, not zero gain.
- `optimization-impact.md`: generated human-readable impact summary.
  Includes harness and, for GHCP, the candidate test surface and memory isolation policy.
- `optimization-run-report.md`: original narrative plus generated GEPA execution/impact section.
- `optimization-plan.json` and `optimization-change-log.json`: add `gepaCandidateId` and
  `gepaRunSha256` to the promoted round; preserve all ordinary round/snapshot/rollback records.
- `optimization-manifest.json`: final hash inventory, including the GEPA outcome files.

Publish through the existing optimizer `generate_manifest.py`. It computes the outcome and
refuses `complete` until the accepted target round matches selected instructions and a fresh
Evaluator PASS on the frozen dataset/rubric. Blocked runs still publish an honest outcome.
Do not create a new skill or alter Scout files for this Agency pilot.