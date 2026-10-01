# Automation precedence — programmatic first, browser last

Read this file for every build before the first remote write. It governs **how** each component
is created; the build path files govern **what** is built. When a build path and this file
disagree, this file wins.

## 1. The automation ladder

| Rung | Method (`automationLedger.method`) | Copilot Studio | Microsoft Cowork |
|---|---|---|---|
| 1 | `pac-cli` | **Mandatory first attempt** with the latest PAC CLI | Not applicable |
| 2 | `programmatic` | Only after a recorded PAC attempt: PAC-produced solution files plus `pac solution import`, Microsoft 365 Agents Toolkit (`atk`), Microsoft Graph, Dataverse Web API, or Power Platform API | **First choice**: generated package files, `atk`, Microsoft Graph |
| 3 | `browser` | Last resort: only when rungs 1 and 2 have no supported route or were rejected | Allowed directly when no programmatic route exists |
| — | `manual` | Human-only acts no tool may perform: end-user OAuth consent, admin approval, licensing purchase | Same |

Rules:

1. **Copilot Studio never skips rung 1.** Before any rung-2 or rung-3 operation, run the closest
   PAC command and record its exact command and outcome in `programmaticAttempts`. "PAC probably
   cannot do this" is not an attempt.
2. **Rung 3 is per operation, not per build.** A browser step for one component never licenses
   browser work for another. Return to PAC for everything after the browser step.
3. **Reconcile after every Copilot Studio browser step.** Run `pac copilot pull` (or
   `pac copilot clone` into an empty folder for an agent created in the UI), confirm the change
   persisted, and record the evidence in `reconciliation`. All later edits go through the workspace.
4. **Cowork may use the browser directly** when this file lists no programmatic route for the
   operation; record `fallbackJustification`. Where a programmatic route exists (plugin
   packaging, `atk install`), use it first.
5. **Never invent definition schemas.** Derive every new YAML/JSON definition from, in order:
   a `pac copilot init` scaffold, a cloned or pulled reference agent in the same environment,
   `pac copilot extract-template`, or the Copilot Studio Visual Studio Code extension schema. A push
   that the service rejects is a recorded `rejected` attempt, not a reason to guess again.
6. **Never automate identity.** Do not script sign-in, MFA, consent, or approval screens. Record
   them as `manual`.

## 2. Toolchain gate (before the first remote write)

Record the results in `automationToolchain`. The packaged validator rejects a Copilot Studio
build whose installed PAC is older than the recorded latest version.

```powershell
# PAC installed as a .NET global tool (the LISA default)
dotnet tool update --global Microsoft.PowerApps.CLI.Tool
pac help                                   # capture "Version: x.y.z" as pacVersion
```

Record the latest published version as `pacLatestVersion`, using the NuGet feed
`https://api.nuget.org/v3-flatcontainer/microsoft.powerapps.cli.tool/index.json` or the update
command's output. If PAC was installed another way, update it through that channel. If the latest
version cannot be established or installed, stop before remote writes: the build is `blocked`.
Don't continue on an older PAC.

For Cowork plugins or Microsoft 365 channel packages, install the Microsoft 365 Agents Toolkit CLI
(version 1.1.12 or later) and record `atkVersion`:

```powershell
npm install -g @microsoft/m365agentstoolkit-cli
atk --version
atk auth login
```

Confirm command availability from live help output (`pac copilot help`, `pac copilot init help`,
`atk help`) rather than from this file alone; record any drift as a build risk.

## 3. Copilot Studio component matrix

The sync workspace is created by `pac copilot init --environment` (new agent) or
`pac copilot clone` (existing agent). `pac copilot push` uploads changed definitions, **including
knowledge files, cloud flows, and connection references**. `pac copilot pull` performs a
three-way merge and downloads knowledge files. On a push conflict, pull first; never force.

| Component / operation | Rung 1: PAC (required attempt) | Rung 2 (after PAC) | Rung 3 (browser) is justified only when |
|---|---|---|---|
| Target, identity, tenant | `pac auth list`, `pac env who`, `pac org who`, `pac env list` | — | Never |
| Solution and publisher | `pac copilot init` creates it; `pac solution init`, `pac solution add-solution-component --AddRequiredComponents` | — | Never |
| Standard (classic) agent | `pac copilot init --template minimal --environment <url>` | `pac copilot pack` + `pac solution import` + `pac copilot clone` | Both PAC routes are rejected by the service |
| Agent from an approved template | `pac copilot extract-template` + `pac copilot create --solution` | — | Never |
| GitHub Copilot-harness agent | `pac copilot init --authoring-mode cli-copilot --environment <url>` | `init` without `--environment`, then `pack` + `pac solution import` + `clone` | The updated PAC still lacks `cli-copilot` |
| Copilot chat-harness agent | `pac copilot list`; `pac copilot clone` when the agent is listed | — | No PAC command creates it; create it on the Microsoft 365 Copilot agent page, then clone it if it is listed |
| Existing agent (resume or reconcile) | `pac copilot clone --bot <id> --output-dir <empty dir>` | — | Never |
| Instructions, AI settings, orchestration mode, capability flags (web browsing, code interpreter, file analysis, memory) | Edit `agent.mcs.yml` / `settings.mcs.yml`, `pac copilot push`, `pac copilot pull` | — | The pulled workspace exposes no field for the setting |
| Agent description | Workspace field when the pulled definition exposes one, then push | A documented Dataverse or Power Platform API field | Neither exposes the field |
| Topics, entities, variables, conditions, Adaptive Cards, HTTP nodes | `topics\*.mcs.yml` + push | — | Push rejects a reference-derived definition |
| Knowledge: SharePoint, OneDrive, public website, Dataverse, Graph connector | Knowledge definition YAML + push | — | Push rejects a reference-derived definition |
| Knowledge: uploaded files | Place files in `knowledge\files\` + push; wait for indexing, verify with pull | — | Push rejects the file type or size |
| Agent flows / cloud flows / GitHub-harness workflows | `workflows\<name>\workflow.json` + `metadata.yaml` + push | Flow in an unpacked solution + `pac solution pack` + `pac solution import` | Both routes are rejected |
| Connection references | `connectionreferences.mcs.yml` + push | Bind with `pac solution create-settings` + `pac solution import --settings-file` | Never |
| Connections (OAuth, user-delegated) | `pac connection list/create` (service principal only) | `pac solution import --settings-file` with an existing connection ID | Interactive consent: record the consent itself as `manual`; use the browser only to open the consent screen |
| Environment variables and secrets | Solution component + `pac solution create-settings` / `--settings-file` | — | Never |
| Tools: prompts, connectors, REST API, MCP, computer use | `actions\*.mcs.yml` / `capabilities\tools\*.mcs.yml` + push | — | Push rejects a reference-derived definition |
| Custom connectors | `pac connector init`, `pac connector create --solution-unique-name`, `pac connector update` | — | Never |
| Event and schedule triggers | `trigger\*.mcs.yml` + workflow + push | — | Push rejects a reference-derived definition |
| Skills (GitHub harness) | `behaviors\<name>.mcs.yml` (`kind: InlineAgentSkill`) derived from a pulled reference + push | — | Push rejects the definition; upload the `SKILL.md` or ZIP in the UI, then pull |
| Connected / child agents | Publish child, then `ConnectedAgentTool` definition in the parent + push | — | Push rejects the definition |
| Component collections | `pac copilot clone --component-collection <id>` + push | — | Never |
| Multilingual content | `pac copilot extract-translation` / `merge-translation` | — | Never |
| Publish and provisioning | `pac copilot publish`, `pac copilot status`, `pac copilot list` | — | Never |
| Teams + Microsoft 365 channel package | `pac copilot-studio download-agent-channel-manifest --channel-name M365` | `atk install --file-path <zip> --scope Personal` for maker testing | Enabling the channel or submitting for org availability has no programmatic route; admin approval is `manual` |
| Other channels (web, Direct Line, custom website, SharePoint, telephony) | Search current `pac copilot help` output and record the result | Documented Power Platform API, if any | No programmatic route exists |
| Authentication settings | `settings.mcs.yml` + push when exposed | — | The workspace exposes no field |
| Solution checker / security scan | `pac solution check` | — | The scan exists only in the Copilot Studio UI |
| Export, package, deploy | `pac copilot pack`, `pac solution export`, `pac solution import`, `pac pipeline deploy` | — | Never |
| Capacity and credit checks | `pac licensing` (read-only) | — | Never |
| Governance (Managed Environments, DLP, consent bypass) | `pac environment-management`, `pac admin dlp-policy`, `pac copilot-studio set-connector-consent-bypass`, only when approved and in scope | — | Never; otherwise record a recommendation |

The builder never runs `pac copilot-studio run-maker-evaluation-test-set` or other behavioral
evaluation. That belongs to `agent-evaluator`.

## 4. Microsoft Cowork component matrix

Cowork plugins are Microsoft 365 app packages: a ZIP with `manifest.json` (schema v1.28),
`color.png` (192×192), `outline.png` (32×32), `skills\<name>\SKILL.md`, and optional tool
description files. Author them as source files under `project\<plugin-slug>\` so the package is
reproducible.

| Component / operation | Programmatic route (use first) | Browser allowed directly when |
|---|---|---|
| Custom skill | Write `skills\<name>\SKILL.md` with `name` + `description` frontmatter (Agent Skills standard; body within about 3,000 words; detail in `references\`) | — authoring is always file-based |
| Skills-only or skills + connector plugin | Write `manifest.json` (`agentSkills` ≤ 20 folders, `agentConnectors` with `remoteMcpServer`) or `atk import openplugin --path <dir> --privacy-url <url> --terms-url <url>`; `atk package --manifest-file .\appPackage\manifest.json --output-package-file <zip> --output-folder <dir>` | — |
| Package validation | Check ASKILL manifest, package, connector, and companion-file rules before upload; v1.28 rejects properties it doesn't define (for example `packageName`) | — |
| Install for the maker (personal test) | `atk install --file-path <zip> --scope Personal`; record `TitleId` and `AppId` | `atk` install is rejected for the package |
| Connector OAuth client registration | Agents Toolkit OAuth client registration; reference its `referenceId` in `OAuthPluginVault` | The tenant doesn't allow toolkit registration (Teams Developer Portal) |
| Standalone personal skill (not in a plugin) | Prefer a skills-only plugin for reproducibility | Upload the `.md`/`.zip`/`.skill` from **Customize → Skills → Upload skill** |
| Custom instructions (Preferences) | None documented | Always; persist the exact text as evidence |
| Share with specific users | None documented | Always (**Share** dialog) |
| Tenant or organization distribution | Microsoft Graph Teams app catalog submission when the tenant permits it | Microsoft 365 admin center upload; approval itself is `manual` |
| Connector user consent | None; each user signs in | Always `manual` |

Persist `agenticPlatform: Microsoft Cowork` and `harness: null`. Record each package in
`artifacts.coworkPackages` (path under `project\`, SHA-256, bytes). Cowork packages never go in
`packages\`, which is reserved for the Power Platform solution ZIP.

## 5. Automation ledger (required in `agent-build-handoff.json`)

Record one entry per remote write or package operation, in execution order:

```json
{
  "automationToolchain": {
    "pacVersion": "2.12.2",
    "pacLatestVersion": "2.12.2",
    "pacLatestSource": "dotnet tool update output",
    "atkVersion": "1.1.12 | null",
    "verifiedAt": "ISO-8601 timestamp"
  },
  "automationLedger": [
    {
      "componentId": "<classifier component id or live component name>",
      "operation": "add-uploaded-knowledge",
      "platform": "Microsoft Copilot Studio | Microsoft Cowork",
      "method": "pac-cli | programmatic | browser | manual",
      "tool": "pac copilot push",
      "evidence": "evidence/<descriptive-name>.txt or concise command result",
      "programmaticAttempts": [
        {"method": "pac-cli", "tool": "pac copilot push", "outcome": "unsupported | rejected | failed", "evidence": ""}
      ],
      "fallbackJustification": "null, or why no programmatic route exists",
      "reconciliation": "null, or the pac copilot pull/clone read-back after a browser step"
    }
  ]
}
```

The packaged validator enforces:

- Every `built` or `configured` component disposition has at least one ledger entry.
- A Copilot Studio `programmatic` or `browser` entry lists a prior `pac-cli` attempt. A `browser`
  entry also needs `fallbackJustification` and `reconciliation`.
- A `browser` or `manual` entry on any platform needs `fallbackJustification`.
- A build with Copilot Studio entries records a PAC version no older than `pacLatestVersion`.
- An entry whose tool uses `atk` requires `atkVersion`.
