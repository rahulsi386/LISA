# Agency GEPA candidate mode

Read this file only when `agent-optimizer` sends a GEPA candidate or final-retest request.

For a GEPA request from `agent-optimizer`, follow `agent-optimizer\resources\gepa-execution.md`
in the plugin skills root. Candidate mode is a subordinate operation
within optimization, not a normal evaluation stage. Do not regenerate tests, change thresholds,
write canonical evaluation files, create a deployment gate, or call `start-stage evaluation`.
Use `scripts\gepa_candidate.py freeze --config <CONFIG>` once to preserve the validated initial
dataset, rubric, observations and baseline. Write candidate responses and evidence only beneath
`output\evaluation\gepa\<OPT-ID>\<request-ID>\`; seal with `scripts\gepa_candidate.py seal`.
These nested runs have their own hash-bound receipts and are excluded from the canonical
evaluation inventory. Only the exact pinned shadow identity is allowed; do not suppress generic
target identity checks. Return normalized scores from the fixed rubric, observed evidence and
redacted actionable feedback. Authentication/tooling/source blockers are BLOCKED, not low scores.
Do not run `render_evaluation.py` for candidate runs.

For the final target retest after GEPA promotion, use normal evaluation mode on the original
target with the full frozen dataset and rubric unchanged. Include `instructionSha256` from live
read-back in observations. Candidate-mode scores can never authorize deployment.

For Agency GHCP GEPA runs, use the optimizer's `policy.gepa.githubCopilot.memoryMode` consistently from the
initial evaluation through candidate tests and final target retest. Require the live CliCopilot
signature and the pinned `/environments/<envId>/agents/<agentId>/preview` URL; no Standard test-pane
fallback is allowed. On initial and final observations, include `gepaExecution` with
`authoringPath` (`pac-cli-copilot` or `new-agent-ui`) and `harnessSignature` as specified by the GEPA
protocol. For every test, record `playwrightObservations.surfaceUsed: preview-canvas`, `surfaceUrl`,
`conversationReset: true`, and `memoryState` (`disabled` or `reset`). Candidate results use the same
per-test fields and record the signature/authoring path in `persistenceReceipt`. A fresh chat alone
does not reset persistent memory. Missing reset or signature evidence is a blocker, not a low score.
