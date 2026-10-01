# Build path A — Standard harness (PAC CLI workspace)

Read this file only when the validated platform is Microsoft Copilot Studio and the harness is
`Standard`. The shared gates in `SKILL.md` Sections 1–8 and `resources\automation-precedence.md`
apply. Record every remote write in `automationLedger`.

Use for rule-based and predictable Standard-harness agents. Every step below is PAC-first; the
browser is used only for an operation that `automation-precedence.md` Section 3 justifies, after
a recorded PAC attempt.

## A1. Create after confirmation

Pass the toolchain gate, then bootstrap a live, sync-ready workspace in one step:

```powershell
pac copilot init `
  --name "<display name>" `
  --publisher-prefix "<prefix>" `
  --schema-name "<prefix_schemaName>" `
  --instructions "Short initial instruction; full instructions follow after scaffold." `
  --project-dir "<basePath>\output\build\project\<schemaName>" `
  --template minimal `
  --environment "<confirmed environment URL>"
```

`--project-dir` must be empty. Use a short one-line initial instruction (multiline CLI arguments
can fail). Successful `init --environment` imports a solution and creates the agent: record the
agent ID and schema name. If the schema name already exists, stop and use `pac copilot clone`
instead of creating a duplicate. If the environment is new and reports that async operations are
disabled, wait and retry.

If the bootstrap is rejected, record the attempt. Then scaffold without `--environment`, run
`pac copilot pack`, then `pac solution import`, then `pac copilot clone` into an empty folder.
Before going further, confirm the agent is solution-aware under the approved custom publisher.

Replace the bootstrap instruction in `agent.mcs.yml` with the Section 5 instruction contract.
Align `settings.mcs.yml` with the approved design instead of accepting scaffold defaults. This
covers model knowledge, file analysis, semantic search, authentication, access, connectability,
and orchestration mode.

Prefer generative orchestration for new Standard-harness agents. Do not introduce classic
orchestration or classic topics unless the approved design explicitly requires
migration/compatibility behavior and the rationale is recorded.

Disable capabilities unless required:

```yaml
gptCapabilities:
  webBrowsing: false
  codeInterpreter: false
```

## A2. Add only approved components through the workspace

Author each definition from a scaffold, pulled reference, or extracted template (never invented),
then push and pull:

| Component | Workspace location |
|---|---|
| Topics, entities, variables, Adaptive Cards | `topics\*.mcs.yml` |
| Knowledge (SharePoint, public site, Dataverse, Graph connector) | knowledge definition YAML |
| Uploaded knowledge files (PDF, DOCX, and similar) | `knowledge\files\` |
| Agent flows / cloud flows | `workflows\<name>\workflow.json` + `metadata.yaml` |
| Connection references | `connectionreferences.mcs.yml` |
| Prompts, connectors, REST API, MCP, computer-use tools | `actions\*.mcs.yml` |
| Event and schedule triggers | `trigger\*.mcs.yml` |

Knowledge patterns:

```yaml
# SharePoint
kind: KnowledgeSourceConfiguration
source: { kind: SharePointSearchSource, site: <verified URL> }
```
```yaml
# Public website (Bing grounding — affects compliance boundary)
kind: KnowledgeSourceConfiguration
source: { kind: PublicSiteSearchSource, site: <verified URL> }
```

Do not use `PublicWebsiteSearchSource`. For Dataverse, verify Dataverse Search, table permissions,
search config, and Quick Find columns. For uploaded files, wait for indexing and confirm the files
return on the next `pac copilot pull`.

Create custom connectors with `pac connector init` and
`pac connector create --solution-unique-name "<solution>"`. Bind connection references and
environment variables with `pac solution create-settings` and `--settings-file` on import. Only the
interactive OAuth consent that creates a user-delegated connection is `manual`.

For every action/connector/flow, apply Section 5.3 descriptions and Section 4 resilience controls.
Use environment variables and connection references. Configure end-user credentials unless an
approved service identity is required. Keep secrets in Key Vault-backed environment variables.
Configure Application Insights/correlation telemetry when required or approved; otherwise add it
to the recommendation backlog. Add nothing the approved design does not require.

## A3. Push, publish, verify

```powershell
pac copilot push --project-dir "<project-dir>"
pac copilot pull --project-dir "<project-dir>"
pac copilot publish --bot "<schema name or agent ID>" --environment "<confirmed environment URL>"
pac copilot status --bot-id "<agent ID>" --environment "<confirmed environment URL>"
pac copilot list --environment "<confirmed environment URL>"
```

If push reports a conflict, pull, re-apply, and push again. Never overwrite a server-side change
you haven't seen.

Before publishing the build for evaluation:

- Run `pac solution check` on the exported solution.
- Resolve build-breaking findings and record non-blocking ones as recommendations.
- Confirm Published/Active/Provisioned. Don't rely only on exit codes.

Behavioral scoring remains out of scope for this skill.

## A4. Exhausted-ladder browser exception

Use the browser only for an operation where a PAC attempt (and any rung-2 route) was recorded as
`unsupported`, `rejected`, or `failed`, and `automation-precedence.md` Section 3 justifies rung 3.
Typical remaining cases:

- the agent Details-page description, when the pulled workspace exposes no field for it;
- enabling non-Microsoft 365 channels;
- a definition the service rejects despite being derived from a pulled reference.

Procedure:

1. Isolate: remove only the failing local definition so everything else publishes.
2. Complete that one operation in Copilot Studio for the confirmed environment.
3. `pac copilot pull`, confirm the change persisted, and record `reconciliation`.
4. Return to the workspace for every later change, then re-publish and re-verify.

## A5. Channels and package

For the Teams and Microsoft 365 Copilot channel, run
`pac copilot-studio download-agent-channel-manifest --agent-id "<agent ID>" --channel-name M365 --out-file "<basePath>\output\build\project\<schemaName>\m365-channel.zip"`.
Use `atk install --file-path <zip> --scope Personal` for maker testing. Organizational
availability requires admin approval, which is `manual`.

```powershell
pac copilot pack --publisher-prefix "<prefix>" --project-dir "<basePath>\output\build\project\<schemaName>" --solution-name "<solution name>" --output-path "<basePath>\output\build\packages"
```

If `pack` rejects the workspace, fall back to
`pac solution export --name "<solution unique name>" --path "<output folder>" --overwrite`.

- Keep the unpacked source project and produce exactly one deployable ZIP, using the managed
  state required by deployment policy.
- Confirm the `.zip` exists, inspect its contents and missing dependencies, and record its
  absolute path.
