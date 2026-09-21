---
name: "postpublish-cleanup"
description: "Safely removes all contents from the config-resolved LISA output folder only after showing an inventory and receiving explicit user consent."
---

# Post-Publish Cleanup

Clean a LISA output folder only after explicit, run-scoped user consent. This operation is irreversible.

Validate `resources\artifact-contract.json` against the shared local-skills `artifact-contract.schema.json` before inventory or deletion. Its `producesArtifacts: false` declaration is mandatory: cleanup must leave no receipt inside the output root.

When invoked by `cad-orchestrator`, follow `..\workflow-checkpointing.md`. Keep the cleanup
checkpoint beneath `<basePath>\.lisa`, outside the deletion target. Persist the consented inventory
and next relative path. After interruption, continue only when the remaining tree is an unchanged
subset of that inventory; otherwise inventory again and request new consent.

## Non-negotiable safety rules

1. Read `lisa-config.json` first and resolve its configured `basePath`. Never accept or hardcode a direct output directory.
2. Resolve only `<basePath>\output`; reject caller-selected output paths and alternate roots.
3. Delete the contents beneath the resolved output root, including hidden files and directories, but preserve the output root directory itself.
4. Never follow or delete through symbolic links, junctions, mount points, or other reparse points. Stop if any are found.
5. Never delete anything before consent. Inventory is read-only.
6. Consent is scoped to the exact resolved path and inventory fingerprint. If content changes, inventory again and request new consent.
7. Never infer consent from “yes”, prior consent, or another operation. Require the exact phrase `DELETE OUTPUT` through `m_ask_user` free-text input and stop while waiting.
8. A response other than the exact phrase cancels cleanup without side effects.

## Workflow

1. Run the packaged script in inventory mode:

```powershell
python "<skill-dir>\scripts\cleanup_output.py" --config "<project-root>\config\lisa-config.json" --inventory
```

2. Show the user the customer, exact resolved output path, file count, directory count, total size, inventory fingerprint, and a concise sample. Warn that all contents will be permanently deleted and the root folder will remain.
3. Ask the user to type `DELETE OUTPUT` using `m_ask_user` free-text mode. Stop and wait.
4. Only after an exact match, execute with the inventory fingerprint:

```powershell
python "<skill-dir>\scripts\cleanup_output.py" --config "<project-root>\config\lisa-config.json" --execute --expected-fingerprint "<fingerprint>" --confirm "DELETE OUTPUT"
```

5. If the fingerprint changed, do not delete. Re-inventory, show the new scope, and request consent again.
6. Report the deleted file/directory counts and bytes. Never report success unless the root exists and is empty.

Do not create cleanup receipts inside the output root, because the operation must leave it empty.


## Advisory execution budget

Guideline for a standard workload: **seconds; inventory is read-only and deletion is bounded by the consented fingerprint**.

If execution exceeds the guideline after the required deletion consent is granted, record the phase,
elapsed time, target, estimated remaining time, and likely cause, then continue automatically. Do not
request additional approval because of elapsed time. This does not remove or weaken the explicit
`DELETE OUTPUT` consent requirement.
