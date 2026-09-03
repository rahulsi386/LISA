---
name: "cad-orchestrator"
description: "Runs the LISA Copilot Agent Delivery (CAD) pipeline end to end: reads lisa-config.json, then invokes requirement-analyzer, complexity-classifier, solution-designer, agent-builder, agent-evaluator, agent-optimizer, artifact-generator and artifact-publisher in order, and finally offers consented post-publish cleanup. Use when asked to run the LISA pipeline, build and publish a Copilot Studio agent from a requirements folder, or orchestrate the CAD lifecycle."
---

# CAD Orchestrator

Run the LISA Copilot Agent Delivery pipeline in order, one stage at a time.

This skill is a **router**. It decides *what* runs and *in what order*. Each stage skill owns
*how* its own work is done — never restate, override, or second-guess a stage skill's internal
rules from here. If this file and a stage skill ever disagree, the stage skill wins.

## 1. Read the configuration first

Resolve the configuration file in this order:

1. A path supplied by the caller.
2. Otherwise the Agency repository default: `<agency-repo-dir>\lisa-config.json`, where
  `<agency-repo-dir>` is `AGENCY_REPO_DIR`.

Resolve `<plugin-skills-root>` from `AGENCY_PLUGIN_DIR\skills`. When Agency is running through
Claude Code and only `CLAUDE_PLUGIN_ROOT` is available, use `CLAUDE_PLUGIN_ROOT\skills` instead.

Read it before any stage runs, and use these fields wherever a later stage needs them:

| Field | Meaning |
|---|---|
| `basePath` | Base path every relative path in the pipeline resolves against |
| `custName` | Customer the agent is being built for |
| `knowledgeSources` | Verified knowledge sources to attach to the agent |
| `copilotStudio.envUrl` | Environment URL the agent is deployed to |
| `copilotStudio.envId` | Environment ID that must match the authenticated environment |
| `agentRegistry.sharepoint.deployableAgentLibraryName` | Library for the deployable agent ZIP |
| `agentRegistry.sharepoint.agentArtifactLibraryName` | Library for all other generated artifacts |

Resolve and sanity-check paths with:

```powershell
python "<plugin-skills-root>\lisa_path_resolver.py" --config "<CONFIG>"
```

Require `<basePath>\requirements` to contain at least one file. Stop and report if the config is
missing required fields or the requirements folder is empty. Do not invent values.

## 1.1 Initialize or recover the workflow

The shared checkpoint engine is the only authority for workflow position. At the start of every
invocation run:

```powershell
python "<plugin-skills-root>\workflow_checkpoint.py" --config "<CONFIG>" init
python "<plugin-skills-root>\workflow_checkpoint.py" --config "<CONFIG>" recover
```

`recover` reads a fixed root pointer, two workflow snapshots, and one active-stage checkpoint. Do
not scan stage trees or choose a continuation point from timestamps. If it returns
`reconcile-remote-operation`, reconcile the recorded remote identity before issuing another write.
If it returns `continue-phase`, resume the exact recorded phase and unit. A `BLOCKED` workflow is a
deliberate terminal gate and requires an explicit new run or approved remediation; it is not an
interrupted stage.

## 2. Execution policy (applies to every stage below)

- Invoke each stage skill **directly in this session**. Do not delegate a whole skill to a nested
  task or subagent.
- Invoke the sibling skill registered by this plugin and follow its instructions. If the host does
  not expose direct skill invocation, read `<plugin-skills-root>\<skill-name>\SKILL.md` and execute
  it in the current session.
- Execute in **bounded phases**. No phase may run silently for more than 90 seconds.
- After each phase: return a concise progress update, persist intermediate state under that
  skill's own output folder, and begin the next phase with a new tool call.
- Always emit a final textual response after the last tool call of a stage.
- Invoke each stage **once per stage run**. Do not add automatic retry loops around a skill; each
  skill owns its own retry, caching and validation behaviour. A user-selected **Revise** decision
  may start a new run of the same stage with a new stage run ID and the supplied feedback.
- Pass no input or output paths. Every stage skill resolves its own paths from `lisa-config.json`.
- Follow `<plugin-skills-root>\workflow-checkpointing.md` at every phase boundary. A stage starts
  checkpointing immediately after it obtains its stage run ID and commits only after its terminal
  completion marker validates.

## 3. Stage sequence

Run these in order. After each stage, validate its completion marker and commit that marker through
`workflow_checkpoint.py complete-stage` before starting the next. Classification and build are
exceptions only in timing: validate their terminal markers, run the human-review gates below, and
commit the marker only after **Accept**.

| # | Skill | Produces under `<basePath>\output\` |
|---|---|---|
| 1 | `/requirement-analyzer` | `analysis\requirement-analysis_<timestamp>-manifest.json` |
| 2 | `/complexity-classifier` | `classification\classification-manifest.json` |
| 3 | `/solution-designer` | `design\current-design.json` |
| 4 | `/agent-builder` | `build\build-manifest.json` |
| 5 | `/agent-evaluator` | `evaluation\evaluation-manifest.json` |
| 6 | `/agent-optimizer` | `optimization\optimization-manifest.json` |
| 7 | `/artifact-generator` | `artifacts\artifact-generation-manifest.json` |
| 8 | `/artifact-publisher` | `publication\publication-record.json` + SharePoint |

Notes that affect routing only:

- **Never infer completion from a non-empty folder.** Skip a stage only when the workflow snapshot
  records it as `COMMITTED`, its completion marker exists, its SHA-256 matches, and that marker
  validates against the stage contract. If the marker is valid but the workflow snapshot was not
  advanced before interruption, repair the checkpoint transition without rerunning the stage.
- **agent-builder performs remote writes.** Before it runs, verify the authenticated Power
  Platform environment matches `copilotStudio.envUrl` and `envId`. On any mismatch, missing or
  expired authentication, stop and report before anything is created remotely.
- **A failing evaluation is data, not an error.** `agent-evaluator` returning a FAIL deployment
  gate is a valid outcome and the evidence `agent-optimizer` consumes. Only missing or invalid
  evaluator output is an execution failure.
- **agent-optimizer decides its own scope** from evaluator evidence, and declines findings that
  are platform or authentication blockers. Let it make that call.
- **Only fresh remote verification may report PUBLISHED** in the publication stage.

If a stage fails, stop the pipeline, report the exact failing stage and reason, and leave every
artifact already produced in place. Do not continue to later stages on a failure.

## 4. Human-review gates

Human review is mandatory after classification and build. These are single-select decisions; never
infer approval from silence, earlier instructions, or unrelated consent. At each prompt, use the
host's user-question interaction with the choices shown below and stop immediately after the tool
call. If no structured question tool is available, ask the same question in chat and end the turn.
Resume only from the user's next turn.
Use `--status RUNNING` for **Accept**, `--status WAITING` while collecting **Revise** feedback, and
`--status CANCELLED` for **Cancel**.

### 4.1 Classification review

After the classification Markdown, JSON, and `classification-manifest.json` validate, but before
committing the classification stage:

1. Present a concise review containing the selected agentic platform, any Copilot Studio harness,
   complexity, code tier, native-build and PoC-demonstration coverage, PoC treatments, simulations,
   blocked or deferred capabilities, and production-readiness gaps.
2. Persist the pause:

   ```powershell
  python "<plugin-skills-root>\workflow_checkpoint.py" --config "<CONFIG>" checkpoint --phase "human-review" --unit-id "classification-decision" --status WAITING
   ```

3. Ask the user with this structured question when supported:

   ```json
   {
     "question": "How should the classification stage proceed?",
     "answers": [
       {"title": "Accept", "description": "Approve the classification and continue to solution design."},
       {"title": "Revise", "description": "Provide changes and rerun classification before continuing."},
       {"title": "Cancel", "description": "Stop the CAD pipeline and preserve generated artifacts."}
     ],
     "recommendedIndex": 0
   }
   ```

4. Stop immediately after the call.
5. On **Accept**, checkpoint `RUNNING` with unit `classification-accepted`, commit the validated
   classification marker as `COMMITTED`, and continue to solution design.
6. On **Revise**, checkpoint `WAITING` with unit `classification-revision-feedback`, then call
  the host's free-text user-question interaction without `answers`:

   ```json
   {
     "question": "What should be revised in the classification?",
     "inputHint": "Describe required platform, scope, capability, coverage, or disposition changes"
   }
   ```

   Stop after the call. On the next turn, preserve the prior artifacts, rerun the classification
   stage with a new stage run ID and the user's feedback, validate the replacement marker, and
   present this classification gate again. Do not advance to design before acceptance.
7. On **Cancel**, checkpoint `CANCELLED` with unit `classification-cancelled`, preserve all existing
   artifacts, report that the user cancelled at classification review, and run no later stage.

### 4.2 Build review

After `build-manifest.json` and all builder artifacts validate, but before committing the build
stage:

1. Present a concise review containing the agentic platform, any Copilot Studio harness, agent and
   component identities, actual dispositions, planned-versus-actual coverage, live construction
   verification, simulations, blocked or deferred components, package or Cowork configuration
   evidence, and evaluator handoff risks.
2. Persist the pause:

   ```powershell
  python "<plugin-skills-root>\workflow_checkpoint.py" --config "<CONFIG>" checkpoint --phase "human-review" --unit-id "build-decision" --status WAITING
   ```

3. Ask the user with this structured question when supported:

   ```json
   {
     "question": "How should the build stage proceed?",
     "answers": [
       {"title": "Accept", "description": "Approve the build and continue to evaluation."},
       {"title": "Revise", "description": "Provide changes and rerun the build before evaluation."},
       {"title": "Cancel", "description": "Stop the CAD pipeline and preserve generated artifacts."}
     ],
     "recommendedIndex": 0
   }
   ```

4. Stop immediately after the call.
5. On **Accept**, checkpoint `RUNNING` with unit `build-accepted`, commit the validated build marker
   using its validated terminal status (`COMMITTED` or `BLOCKED`). Continue to evaluation only for
   `COMMITTED`; a `BLOCKED` build remains a terminal workflow gate.
6. On **Revise**, checkpoint `WAITING` with unit `build-revision-feedback`, then use the host's
  free-text user-question interaction without `answers`:

   ```json
   {
     "question": "What should be revised in the build?",
     "inputHint": "Describe required agent, skill, plugin, tool, configuration, or disposition changes"
   }
   ```

   Stop after the call. On the next turn, preserve the prior build evidence, rerun the build stage
   with a new stage run ID and the user's feedback, validate the replacement marker, and present
   this build gate again. Do not advance to evaluation before acceptance.
7. On **Cancel**, checkpoint `CANCELLED` with unit `build-cancelled`, preserve all existing
   artifacts and remote resources, report that the user cancelled at build review, and run no
   later stage. Cancellation does not delete or roll back remote resources.

## 5. Post-publish cleanup (consented, irreversible)

Cleanup is **not** automatic and runs only after a successful publication.

1. Confirm the publication stage reported a verified PUBLISHED result. If it did not, do not offer
   cleanup: the local output is still the only copy of the run.
2. Ask the user exactly:
   `Artifacts published remotely. Do you want to delete local copies? (Delete/Cancel)`
3. On **Cancel**, finish the run and leave every file untouched.
4. On **Delete**, invoke `/postpublish-cleanup` directly in this session. That skill enforces its
   own `DELETE OUTPUT` consent phrase — never bypass, pre-answer, or infer it from this prompt.

Keep the workflow `RUNNING` after publication while this decision is pending. On Cancel, finish it
as `COMPLETED`. On Delete, start and checkpoint the `cleanup` stage, perform the fingerprint-bound
cleanup, commit its external active-stage checkpoint as the completion marker, then finish the
workflow as `COMPLETED`:

```powershell
python "<plugin-skills-root>\workflow_checkpoint.py" --config "<CONFIG>" finish --status COMPLETED
```

Cleanup empties everything beneath `<basePath>\output`. If the user wants a local record, copy the
customer artifacts elsewhere before invoking it.

## 6. Final report

Close the run with: customer, the stages completed, the agent name and ID, the selected harness,
the evaluation gate decision, the publication status and SharePoint location, the local
solution-document path, and whether cleanup ran.
