# Build path B — GitHub Copilot harness

Read this file only when the validated platform is Microsoft Copilot Studio and the harness is
`GitHub Copilot`. The shared gates in `SKILL.md` Sections 1–8 and
`resources\automation-precedence.md` still apply. Every component below is authored in the PAC
sync workspace first; the Build UI is a recorded, per-operation exception only.

Use this path for every currently supported GitHub Copilot-harness composition. Component types are composable, not mutually exclusive: build an instructions-only agent, or any required combination of knowledge, tools, workflows, skills, memory, file capabilities, and connected agents. Build exactly the non-empty component set defined by the validated classification and design; never force unnecessary components and never omit a required component because another component is present.

## B0. Resolve the component matrix and dependency graph

Before creation, build one inventory row for every deployable agent:

| Component | Supported composition |
|---|---|
| Instructions | Required for every agent |
| Knowledge | None, one source, or multiple public website, SharePoint, OneDrive, Dataverse, uploaded-file, or supported connector sources |
| Tools | None, or any supported combination of modern Workflow, connector, MCP, REST API, computer use, prompt, and other GitHub-harness tools |
| Skills | None, one, or multiple focused uploaded/generated skills |
| Memory | Off by default; enable only when required |
| Connected agents | None for a single agent; one or more separately authored GitHub-harness agents that are packaged into the same scenario solution |

For a multi-agent solution:

1. Create a directed dependency graph with the user-facing parent as the root.
2. Give every child one domain responsibility, its own functional name, instructions, knowledge, skills, tools, source workspace, and lifecycle boundary. All scenario agents still belong to the same final Power Platform solution.
3. Build and publish leaves before parents. Never connect an unpublished child.
4. Require every connected child to pass the same GitHub-harness signature checks as the parent; never connect a classic/Standard agent by mistake.
5. Define a distinct ≤50-word routing description for every connection. The parent must be the only agent that responds to the user; every delegated task tells the child to return findings only.

## B1. Verify PAC support and create with `cli-copilot`

The PAC `cli-copilot` path is mandatory because it creates a governed, sync-ready workspace that can be pulled, diffed, packaged, and deployed. After the toolchain gate updates PAC to the latest version, and before the first remote write:

```powershell
pac copilot init help
```

Require the help output to expose `--authoring-mode` and `cli-copilot`. Create a local disposable scaffold beneath the build run, inspect it, then delete or retain it as evidence:

```powershell
pac copilot init `
  --name "<functional display name>" `
  --publisher-prefix "<prefix>" `
  --authoring-mode cli-copilot `
  --project-dir "<basePath>\output\build\evidence\cli-scaffold-check"
```

The scaffold must contain:

```yaml
configuration:
  authoringModel: CliCopilot
  recognizer:
    kind: CLICopilotRecognizer
template: cliagent-1.0.0
```

For every parent or child, create a separate remote workspace:

```powershell
pac copilot init `
  --name "<functional display name>" `
  --publisher-prefix "<prefix>" `
  --schema-name "<prefix_functionalSchemaName>" `
  --instructions "<short one-line bootstrap instruction>" `
  --authoring-mode cli-copilot `
  --project-dir "<basePath>\output\build\project\<schemaName>" `
  --environment "<verified environment URL>"
```

Record the agent ID and schema name returned by PAC. Immediately inspect the live-synced `settings.mcs.yml`; stop if `authoringModel`, recognizer, or template does not match the GitHub-harness signature. Replace the bootstrap instruction with the Section 5 contract, then use `pac copilot push` and `pac copilot pull` to verify persistence.

If the bootstrap is rejected, record the attempt. Then scaffold locally (no `--environment`), run `pac copilot pack`, then `pac solution import`, then `pac copilot clone` into an empty folder, and re-check the signature.

Only when the **updated** PAC still lacks `cli-copilot` (a recorded `unsupported` attempt), create the agent at `https://copilotstudio.preview.microsoft.com/environments/<environment-id>/agents/new` after verifying browser identity and environment. Then immediately `pac copilot clone` it into the governed project directory, record `reconciliation`, and add every component through the workspace.

## B2. Implement every required component type

Author each definition in the workspace from the scaffold, a pulled reference agent, or an extracted template; never invent YAML. After each change, `pac copilot push`, then `pac copilot pull` and diff. A push the service rejects is a recorded `rejected` attempt. Only then may that single operation use the Build UI, followed by `pac copilot pull` reconciliation (see `automation-precedence.md` Section 3).

### Knowledge

- Add each exact validated source as a knowledge definition under `capabilities\knowledge\`, and place uploaded files under `knowledge\files\`; `pac copilot push` uploads them.
- Public website URLs must satisfy the current picker depth rules; never broaden to general web search to work around a rejected URL.
- For SharePoint, OneDrive, and Dataverse, verify tenant/site/table scope, runtime identity, source permissions, indexing/readiness, Dataverse Search and Quick Find configuration where applicable.
- For uploaded files, wait for upload and indexing to complete.
- Keep `Search all websites` off unless the design explicitly requires general web search.
- Configured knowledge is available to Copilot Studio orchestration by default. Do not enumerate every source in instructions. Add instruction text only for evidence-backed priority, conflict resolution, scope, freshness, citation, access, or missing-evidence behavior.

### Skills

- Create a focused `SKILL.md` with YAML frontmatter (`name`, `description`), one responsibility, typed tool expectations, explicit failure behavior, and no duplicated parent instructions.
- Author `behaviors\<name>.mcs.yml` with `kind: InlineAgentSkill`, modeled on a pulled reference skill, and push. Only if the push is rejected, upload the file or a ZIP whose root contains `SKILL.md` in the UI, then pull.
- Verify the pulled workspace contains `behaviors\<name>*.mcs.yml` with `kind: InlineAgentSkill`.

### Workflow tools

1. Author the modern GitHub-harness Workflow as `workflows\<name>-<id>\workflow.json` plus metadata, modeled on a pulled reference workflow, and push it. Use the Workflows surface only after a recorded rejected push.
2. Use `When an agent calls the workflow`; do not substitute a Standard agent flow.
3. Add narrow typed inputs with descriptions and required fields.
4. Use only the necessary workflow nodes: functions, variables, branching, loops, connectors, human review, agents, or AI actions. An Agent node is optional, not mandatory.
5. Configure deterministic action ordering and explicit error paths.
6. Configure `Respond to the agent` with non-empty typed success, partial, and error outputs. Wire outputs to actual upstream action values.
7. Never return placeholder, timestamp-invented, or success-shaped receipt IDs. If the downstream integration is not implemented, return an explicit blocked/not-integrated result.
8. Push, publish the agent, and add the `WorkflowTool` definition to the owning agent's `capabilities\tools\` in the workspace.
9. Pull the agent and verify both `capabilities\tools\*.mcs.yml` with `kind: WorkflowTool` and `workflows\<name>-<id>\workflow.json`.

### Other tools

- Add connector, MCP, REST API, computer-use, prompt, or other supported tools only when the design selects that creation method. Author them as `capabilities\tools\*.mcs.yml` (and `pac connector create --solution-unique-name` for custom connectors), then push.
- Bind connection references and environment variables through the workspace or `pac solution create-settings` + `--settings-file`. Only end-user OAuth consent is `manual`.
- Do not substitute a generic connector or MCP server when the required tool is a workflow.
- Verify exact inputs, outputs, authentication, connection references, permissions, timeouts, retry/idempotency, side effects, and error behavior.

### Connected agents

- Publish each child with `pac copilot publish`, then add a `ConnectedAgentTool` definition with an exact, distinct routing description to the parent workspace and push. Use the parent agent picker only after a recorded rejected push.
- Verify the parent workspace contains one `ConnectedAgentTool` definition per child under `capabilities\tools`.
- Keep child knowledge and tools focused on its domain. Avoid duplicate knowledge across children unless the architecture explicitly requires overlap.

### Memory and native file capabilities

- Enable memory only when the design specifies its purpose, allowed data, retention/reset behavior, transparency, and evaluation scope.
- Configure native Word, Excel, PowerPoint, and PDF capabilities only when required and verify the corresponding live capability rather than relying on harness defaults.

## B3. Persist descriptions and instructions

Persist instructions and the functional ≤50-word description through the workspace (`agent.mcs.yml`) and push. Connected-agent routing always requires a description. If the pulled workspace exposes no primary description field, use a documented Dataverse/Power Platform API field when available. Otherwise use the UI as a recorded exception, or record the limitation as a blocker. After every component change, re-align instructions with exact live component names without restating platform-default knowledge behavior.

Only when a pushed instruction edit is rejected (a recorded attempt) may the UI editor be used. Use real keyboard insertion rather than Playwright `fill()`, then Save, reload, `pac copilot pull`, and verify the Dataverse instruction segment:

```javascript
const editor = page.getByRole('textbox', { name: 'Agent instructions' });
await editor.click();
await page.keyboard.press('Control+A');
await page.keyboard.insertText(instructions);
```

## B4. Publish, pull, verify, and package one scenario solution

Publish every leaf agent first and the parent last with `pac copilot publish`, and confirm provisioning with `pac copilot status`. Pull and verify each source workspace independently:

```powershell
pac copilot list --environment "<verified environment URL>"
pac copilot pull --project-dir "<basePath>\output\build\project\<schemaName>"
```

Require Published/Active/Provisioned and verify the pulled GitHub workspace:

- `settings.mcs.yml`: `CliCopilot`, `CLICopilotRecognizer`, and `cliagent-1.0.0`
- `behaviors\`: every expected `InlineAgentSkill`
- `capabilities\knowledge\`: every expected knowledge source
- `capabilities\tools\`: every expected `WorkflowTool`, `ConnectedAgentTool`, connector, MCP, REST, or other tool
- `workflows\`: every expected workflow definition

Semantically inspect every `workflow.json`: input and response schemas are non-empty when data is required, outputs are wired to real action values, failure paths are explicit, and receipts cannot be fabricated. Treat missing integration or placeholder output as a blocked build.

Create or resolve one functional, scenario-level unmanaged solution in the verified environment. Its name describes the scenario capability and must not use the company/customer name. Add every live agent to that same solution with required components:

```powershell
pac solution add-solution-component `
  --environment "<verified environment URL>" `
  --solutionUniqueName "<functional scenario solution>" `
  --component "<agent-id>" `
  --componentType bot `
  --AddRequiredComponents
```

Repeat for the parent and every child. `--AddRequiredComponents` is necessary but not sufficient proof: inspect the live solution inventory and ensure every skill, knowledge source, workflow, tool, connection reference, environment variable, and connected-agent dependency is included. Add any missing required component explicitly using its verified component identity and type.

Export exactly one deployable ZIP:

```powershell
pac solution export `
  --environment "<verified environment URL>" `
  --name "<functional scenario solution>" `
  --path "<basePath>\output\build\packages\<functional-scenario-name>.zip" `
  --overwrite
```

Choose the managed state required by the deployment policy, but produce one deployable ZIP for the run. Retain unpacked/source projects rather than additional deployable ZIP variants.

Inspect the single ZIP and require all expected agents, bot components, skills, knowledge, tools, workflows, connection references, environment variables, and dependencies. Reject a ZIP that contains only the parent, only one child, or unresolved `MissingDependencies`.

Create `agent-solution-manifest.json` containing the scenario solution identity, the single package path/hash, primary agent, every child ID/schema/role, relationships, deployment order, project paths, and per-agent component inventories. A single-agent build uses the same manifest with one agent and no relationships.

## B5. GEPA readiness (GitHub Copilot harness)

For an Agency GitHub Copilot (GHCP) GEPA build, retain the harness signature and exact
configured skill/tool/knowledge inventory in construction evidence. Record the approved GHCP
memory isolation mode (`disabled` or `reset-between-tests`) before initial evaluation. Use
`disabled` only when memory is not required; otherwise verify a supported `reset-between-tests`
procedure. Never disable a required capability just to make the shadow testable. If state cannot
be isolated, record a GEPA blocker. Copilot Credits, native file/sandbox state and autonomous
triggers must be checked for both the original and shadow agent before GEPA execution.
