---
name: "artifact-publisher"
description: "Publishes a dynamically categorized manifest through an authenticated SharePoint REST fast path: ZIP first, then Agent-ID-linked files under a root-level agent-name folder."
---

# Artifact Publisher

## Purpose

Publish a completed LISA run to the configured SharePoint registry. Use the authenticated SharePoint REST fast path by default: verify the deployable ZIP first at the Agent Library root, then publish manifest-selected Agent Artifact files concurrently under a root-level folder named exactly after the agent. Propagate Agent ID metadata from the Agent Library ZIP read-back to the Agent Artifact folder and every file.

Treat “Agent Factory library” as the configured Agent Artifact library.

When invoked by `cad-orchestrator`, follow `..\workflow-checkpointing.md`. Start the `publication`
stage before preflight. Checkpoint the ZIP, metadata propagation, and every manifest artifact key.
Every upload or metadata mutation requires a remote operation intent before execution and a receipt
after fresh read-back. Resume by querying exact SharePoint paths and hashes. Commit
`publication-record.json` only after fresh remote verification determines the terminal status.

## 1. Authoritative inputs

Default config:

`<path-to>\lisa-config.json`

Require configured `basePath`, `custName`, and the configured SharePoint site and library names. Resolve the current lifecycle only from canonical files beneath `<basePath>\output`:

- `build\build-manifest.json` and `build\agent-build-handoff.json`
- `design\current-design.json`
- `evaluation\evaluation-manifest.json`
- `optimization\optimization-manifest.json`
- the current direct-child Analysis and Classification outputs
- `artifacts\`

Select the deployable ZIP from `agent-build-handoff.json.artifacts.packages`; require exactly one package, or exactly one package explicitly marked `primary`/`deployable`. Verify its path, size, SHA-256, ZIP format, and non-empty contents before publication. Use the agent identity from the build handoff and the description from the handoff or build specification. Preserve only manifest-listed files plus validated current design and final artifact files. Exclude hidden working folders, caches, publication metadata, browser storage, credentials, tokens, and secrets.

## 2. Dynamic categorized manifest

Validate `resources\artifact-contract.json` against the shared local-skills `artifact-contract.schema.json` before building the publication manifest. The contract is the authority for the lowercase `publication` folder and publication metadata names.

Run:

`<skill-dir>\scripts\publication-guard.ps1 -Mode BuildManifest`

The manifest—not a hardcoded number—defines publication and benchmark scope. Require schema `3.0`, exactly one Agent Library entry, and `deployableAgent` first with `uploadSequence: 1`.

Every entry must have an `artifactCategory`:

- `deployablePackage`: the single ZIP
- `declaredArtifact`: a file selected by a current lifecycle manifest, current design pointer, or final artifact output
- `evaluationArtifact`: an additional non-evidence evaluation output
- `evaluationEvidence`: a file under `evaluation/evidence`
- `additionalRunFile`: another eligible file selected by policy

Report `expected.categoryCounts` separately. Never call every non-ZIP file a “supporting artifact.” In particular, evaluation evidence remains evidence, not a supporting deliverable.

The total benchmark count is always `manifest.expected.totalCount`. Agent Artifact count is `manifest.expected.artifactLibraryCount`. Do not hardcode “35 files,” “34 supporting artifacts,” or any other fixed count.

The Agent Artifact destination is:

`<agentArtifactLibraryName>/<authoritative agentName>`

Use the agent name unchanged and directly under the library root.

`publication-record.json` is history only and must never suppress live remote reads or uploads.

## 3. Mandatory fast transport

Fast runner:

`<skill-dir>\scripts\fast-sharepoint-publisher.js`

Default transport is `authenticated-sharepoint-rest`. Do not use UI navigation, drag/drop, staging copies, fixed sleeps, or one-tool-call-per-file in the default path.

Create `artifactPublisherFastJob` from the validated manifest and store it in SharePoint-origin session storage. Invoke the runner with `playwright-browser_run_code_unsafe` using its filename. Defaults:

```json
{
  "dryRun": false,
  "uploadConcurrency": 6,
  "metadataConcurrency": 12,
  "maxDurationMs": 240000,
  "allowSlowFallback": false
}
```

The runner uses temporary browser file inputs only to expose local bytes; all remote operations use authenticated SharePoint REST. It stores `artifactPublisherFastResult` with transport, duration, actions, and fresh inventory.

## 4. Transport fallback

Publication is idempotent, so an interrupted run resumes safely and skips already-published files. Never enter slow UI mode automatically; Playwright UI fallback requires an explicit `allowSlowFallback: true`.

## 5. Cached preflight

Validate authentication, configured site, both document libraries, permissions, and metadata columns.

Resolve Agent Library Agent ID, Agent Name, Agent Description, and Customer/Cx Name fields. Resolve a writable Agent ID text field in Agent Artifact.

Cache validated library IDs and internal field names in SharePoint-origin session storage for 15 minutes. Reuse only when site path and both library names match. Record `schemaCacheHit`. Missing or incompatible metadata fields are hard failures.

## 6. Strict two-phase order

### Phase 1: ZIP first

The ZIP is the first item processed and first file uploaded/replaced. Store it directly at:

`<deployableAgentLibraryName>/<ZIP filename>`

Use no Agent Library subfolder. Populate and read back Agent ID, Agent Name, Agent Description, and Customer Name. Capture `verifiedAgentLibraryAgentId` from the read-back. Do not create or write to Agent Artifact before this phase succeeds.

### Phase 2: manifest-selected Agent Artifact files

Create or resolve:

`<agentArtifactLibraryName>/<agentName>`

Preserve required relative subdirectories beneath the root agent-name folder. Upload only missing/changed manifest entries with bounded concurrency. Reconcile unchanged files by live path and size/comparable hash.

Set Agent ID metadata on the root agent folder and every manifest-selected Agent Artifact file. Every value must equal `verifiedAgentLibraryAgentId` from Agent Library.

Exclude the ZIP, publication record, temporary files, credentials, cookies, tokens, secrets, and browser storage from Agent Artifact.

## 7. Fresh verification

Discard pre-write observations and build a new live inventory. Write only its `inventory` portion to session-temporary JSON and run `publication-guard.ps1 -Mode VerifyRemote`.

`PUBLISHED` requires guard exit `0`, `passed: true`, and proof that:

- ZIP was first and is at Agent Library root
- Agent Library metadata matches
- agent-name folder is directly at Agent Artifact root
- every manifest entry exists with matching content metadata
- no manifest entry is missing and no unexpected file exists in the agent folder
- folder and every Agent Artifact file use the Agent Library Agent ID

Verification counts must be compared to the dynamic manifest counts and category counts, never fixed constants.

## 8. Idempotency and legacy layouts

Query exact live paths. Upload missing files, skip matching files, and replace differing files only at their intended paths using versioning. Never silently rename conflicts.

Do not publish to run-ID folders. Remove a legacy folder only after the new layout passes verification and only when all content is an identical duplicate with no unrelated files.

## 9. Publication record and state

Generate `<basePath>\output\publication\publication-record.json` atomically from the current manifest, fast result, and verified live inventory only. Never merge old entries. `BuildManifest` persists its validated input manifest at `<basePath>\output\publication\publication-manifest.json`. Publication metadata is never included in the remotely published artifact inventory.

Include:

- dynamic total, library counts, and `categoryCounts`
- ordered actions with each entry’s `artifactCategory`
- paths, hashes, sizes, IDs, URLs, and metadata verification
- transport, fast-path/fallback state, schema cache state
- start/completion time, duration, and concurrency
- guard result and mismatches

Update only the publication stage checkpoint; preserve upstream completion-marker records.

Status:

- `PUBLISHED`: guard passed
- `PARTIAL`: at least one item succeeded but fresh remote verification did not complete
- `FAILED`: preflight/fast path failed before success
- `SKIPPED`: explicitly disabled or no eligible entries

## 10. Cleanup

Delete temporary manifest, job, result, inventory, and browser file inputs. Clear clipboard and fast-job/result session keys. Preserve the 15-minute schema cache.

## 11. Performance release gate

Any fast-runner change requires:

1. Run `python -m unittest discover -s "<skill-dir>\tests" -p "test*.py"`.
2. Require all manifest, verification, metadata, concurrency, and rerun regressions to pass.
3. Run a read-only dry-run preflight.
4. Run a controlled fresh benchmark using exactly the current manifest entries.
5. Report manifest category counts separately.
6. Record the measured duration as a performance observation.

The automated suite uses local fixtures and an in-memory SharePoint REST model. It must never access a live tenant or perform a remote write.

Name the benchmark dynamically, for example: “manifest benchmark: N total files,” where `N = manifest.expected.totalCount`. Never describe all Agent Artifact entries as supporting artifacts.

## 12. Output contract

Return exactly one JSON object:

```json
{
  "publication_record": "",
  "publication_status": "PUBLISHED | PARTIAL | FAILED | SKIPPED",
  "evaluation_decision": "PASS | FAIL",
  "transport": "authenticated-sharepoint-rest | playwright-ui",
  "fast_path_used": true,
  "fallback_reason": null,
  "schema_cache_hit": false,
  "duration_seconds": 0,
  "first_processed_item": "deployableAgent",
  "artifact_agent_folder": "",
  "verified_agent_library_agent_id": "",
  "manifest_expected_count": 0,
  "manifest_category_counts": {},
  "remote_verified_count": 0,
  "uploaded_count": 0,
  "already_published_count": 0,
  "failed_count": 0,
  "agent_library_metadata_verified": false,
  "artifact_folder_agent_id_verified": false,
  "artifact_items_agent_id_verified": false,
  "verified_urls": []
}
```

Do not claim `PUBLISHED` unless the fresh remote guard passes.
