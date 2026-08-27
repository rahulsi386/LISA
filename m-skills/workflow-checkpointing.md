# LISA Workflow Checkpoint Contract

Use this contract whenever a stage runs under `cad-orchestrator`. Standalone skill execution may
omit workflow checkpointing, but its normal terminal artifact validation remains mandatory.

## Commands

After a stage obtains its run ID:

```powershell
python "<local-skills-root>\workflow_checkpoint.py" --config "<CONFIG>" start-stage --stage "<STAGE>" --stage-run-id "<RUN-ID>" --phase "<PHASE>" --unit-id "<UNIT>"
```

At every durable phase or work-unit boundary:

```powershell
python "<local-skills-root>\workflow_checkpoint.py" --config "<CONFIG>" checkpoint --phase "<PHASE>" --unit-id "<NEXT-UNIT>" --status RUNNING
```

Before a remote write, checkpoint `RECONCILING` with `--pending-operation-json`. Include a stable
operation ID, idempotency key, canonical remote target, expected content hash, and read-back method.
After verified read-back, checkpoint with `--receipt-json`. If interrupted between those writes,
query and reconcile the remote target; never blindly replay the operation.

After terminal validation, calculate the completion marker SHA-256 and run `complete-stage` with a
basePath-relative marker. Use `BLOCKED` only for a deliberate validated gate outcome.

## Phase and unit boundaries

| Stage | Durable phases | Unit cursor |
|---|---|---|
| analysis | prepare, extract, visual-review, ledger, publish | source or review-target ID |
| classification | prepare, reference-refresh, copilot-assessment, foundry-assessment, framework-assessment, publish | reference or finding ID |
| design | prepare, generate, inspect, finalize | candidate or inspection ID |
| build | verify-environment, specify, construct, publish, verify-live, package, manifest | component or remote operation ID |
| evaluation | prepare, dataset, rubric, execute-test, score-test, aggregate, manifest | exact test and attempt ID |
| optimization | audit, plan, before-snapshot, apply, verify, retest, accept-or-rollback, manifest | round and operation ID |
| artifacts | snapshot-inputs, render, validate, publish-set, manifest | artifact name |
| publication | preflight, build-manifest, publish-zip, propagate-metadata, publish-artifact, verify-remote, record | manifest artifact key |
| cleanup | inventory, delete-entry, verify-empty | inventory index and relative path |

## Recovery rules

1. Read `recover`; do not recursively scan stage output.
2. Verify that config and input marker hashes still match.
3. Resume the exact phase and unit when no operation is pending.
4. Reconcile a pending remote operation by canonical identity before deciding to skip, complete, or retry it.
5. Treat committed manifests and pointers as completion evidence, not as mid-stage checkpoints.
6. Never advance to a later stage from folder existence, timestamps, or an unvalidated report.
7. Keep credentials, cookies, and tokens out of checkpoints and operation receipts.