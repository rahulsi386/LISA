# LISA Agency plugin

This directory packages the ten LISA Copilot Agent Delivery skills as one Agency plugin. It is a
self-contained distribution copied from `m-skills`; the original Scout installation remains
unchanged.

## Included components

- `agency.json`: Agency engine, category, and draft governance metadata.
- `plugin.json`: Copilot plugin manifest registering the shared skills directory.
- `.claude-plugin/plugin.json`: Claude-compatible manifest registering the same skills directory.
- `.mcp.json`: Playwright MCP server used by browser-dependent stages.
- `skills/`: all LISA skills, shared Python modules, contracts, resources, tests, renderer, fonts,
  icons, and the packaged Windows layout engine.
- `scripts/Test-LisaAgencyPrerequisites.ps1`: prerequisite validation and optional dependency
  restoration.
- `lisa-config.example.json`: project-relative configuration template.

The Agency copy replaces Scout-specific skill loading, question, and root-path terminology. The
stage implementations, contracts, checkpoint format, artifact schemas, and safety gates are
otherwise preserved.

## Requirements

- Windows 11
- Agency 1.0 or newer
- Python 3.11 or newer
- PowerShell 7 or newer
- Node.js 18 or newer and npm
- Microsoft Edge for the bundled Playwright MCP configuration
- Internet access to PyPI and npm during dependency restoration
- Modern Power Platform CLI (`pac`) for Copilot Studio build, evaluation, and optimization stages
- Valid Microsoft tenant, Copilot Studio, SharePoint, and browser authentication for cloud stages

Run the prerequisite checker from the repository root:

```powershell
pwsh -File .\agency\scripts\Test-LisaAgencyPrerequisites.ps1 `
  -InstallPythonPackages `
  -RestoreRenderer `
  -RequireCloudStages
```

Omit `-RequireCloudStages` when using only local analysis, classification, design, artifact, and
cleanup capabilities. The script does not authenticate Agency, PAC, Microsoft 365, Copilot Studio,
or SharePoint.

## Project configuration

LISA data belongs in the target project, not in the installed plugin directory. Create these items
in the repository where Agency will run:

```text
<project>/
|-- lisa-config.json
|-- requirements/
|-- evalData/
`-- output/
```

Start from `lisa-config.example.json`. Keep `basePath` set to `.` when the configuration is in the
project root, or use another path relative to the configuration file. Fill in tenant and library
values before running cloud stages. Do not use the Scout-specific `%USERPROFILE%\.scout\LISA`
default.

Validate routing before invoking a stage:

```powershell
python "$env:AGENCY_PLUGIN_DIR\skills\lisa_path_resolver.py" `
  --config "$env:AGENCY_REPO_DIR\lisa-config.json"
```

When the Claude-compatible engine exposes `CLAUDE_PLUGIN_ROOT` instead, use that variable for the
plugin root. Every stage accepts an explicit configuration path through its documented command.

## Local use

From this directory, launch either Agency engine with the local plugin:

```powershell
Set-Location .\agency
agency claude --plugin local:.
```

The equivalent Copilot engine can be used when supported by the installed Agency version:

```powershell
agency copilot --plugin local:.
```

Invoke `/cad-orchestrator` in Copilot or `/lisa:cad-orchestrator` in Claude for the complete
workflow, and include the full path to `lisa-config.json` when it is outside the current project.
Use `/skills info cad-orchestrator` in Copilot to verify discovery before starting. The
orchestrator executes sibling skills in the current session and falls back to reading their
packaged `SKILL.md` files when the engine does not expose direct skill invocation.

After publishing this plugin through an Agency marketplace, installation follows the marketplace
form documented by Agency:

```powershell
agency plugin install market:lisa@<marketplace-repository>
```

## Browser authentication and security

The bundled Playwright MCP server launches Microsoft Edge with a persistent workspace-specific
profile. Sign in interactively to the required Microsoft tenant before running browser-dependent
stages. Keep Agency, PAC, Copilot Studio, and SharePoint on the same tenant identity.

Artifact Publisher executes the packaged `fast-sharepoint-publisher.js` through Playwright MCP's
`browser_run_code_unsafe` tool. This is arbitrary code execution in the Playwright server process.
The MCP configuration also enables `--allow-unrestricted-file-access` so the server can load the
runner from the installed plugin directory. Install this plugin only from a trusted source and
review changes to the runner and MCP configuration before updating it.

The publisher still requires explicit manifest validation, checkpointed remote intents, fresh
SharePoint read-back, and the existing publication guard before it can report `PUBLISHED`.

## Validation

Run the plugin structural tests:

```powershell
python .\tests\test_plugin.py -v
```

Run all copied Python tests from the plugin root:

```powershell
Get-ChildItem .\skills -Recurse -Filter "test*.py" | ForEach-Object {
  python $_.FullName
  if ($LASTEXITCODE -ne 0) { throw "Test failed: $($_.FullName)" }
}
```

Run the Artifact Publisher JavaScript tests and Solution Designer renderer self-test:

```powershell
node .\skills\artifact-publisher\tests\test_fast_publisher.js
npm --prefix .\skills\solution-designer\renderer test
```

## Current limitations

- This distribution is Windows-oriented because LISA uses PowerShell, PAC CLI, Microsoft Edge, and
  a packaged Windows layout engine.
- Agency does not replace tenant authentication. Cloud stages stop if PAC and browser identities do
  not match the configured environment.
- Human approval remains mandatory after classification and build. Cleanup still requires the
  exact phrase `DELETE OUTPUT` for the fingerprinted inventory.
- The Scout schedule in `m-automations/automations.json` is not included. Configure scheduling with
  an Agency-supported automation mechanism after validating the interactive workflow.
- `agency.json` uses draft layer-4 governance metadata. Marketplace owners must replace or certify
  that metadata according to their internal review process before broad distribution.

## Updating the copy

Treat `m-skills` as the implementation source. When refreshing this distribution, copy maintained
files while excluding generated `node_modules`, `bin`, `obj`, cache, and virtual-environment
directories; then reapply the Agency adaptations in `cad-orchestrator`, `agent-builder`,
`artifact-publisher`, and `postpublish-cleanup`. Run the full validation commands above before
publishing.