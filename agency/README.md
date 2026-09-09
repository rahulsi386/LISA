# LISA Agency plugin

This directory packages the ten LISA Copilot Agent Delivery skills as one Agency plugin. It is a
self-contained distribution copied from `m-skills`; the original Scout installation remains
unchanged.

## Included components

- `agency.json`: Agency engine, category, and draft governance metadata.
- `plugin.json`: Copilot plugin manifest registering the shared skills directory.
- `.claude-plugin/plugin.json`: Claude-compatible manifest registering the same skills directory.
- `.mcp.json`: Playwright, local Azure MCP, and remote Microsoft Learn MCP registrations for the
  Copilot engine.
- `.claude-plugin/plugin.json` also embeds the same MCP registrations for the Claude engine.
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
- Node.js 20 or newer, npm, and npx (use a currently supported Node.js LTS release)
- Microsoft Edge for the bundled Playwright MCP configuration
- Internet access to PyPI and the configured npm registry during dependency restoration and
  MCP package resolution and setup
- Access to `https://learn.microsoft.com/api/mcp` when using Microsoft Learn MCP
- Modern Power Platform CLI (`pac`) for Copilot Studio build, evaluation, and optimization stages
- Valid Microsoft tenant, Copilot Studio, SharePoint, and browser authentication for cloud stages
- An authenticated Azure identity with the appropriate Azure RBAC permissions for Azure MCP
  operations; Azure CLI is the recommended local sign-in method

Run the prerequisite checker from the repository root:

```powershell
pwsh -File .\agency\scripts\Test-LisaAgencyPrerequisites.ps1 `
  -InstallPythonPackages `
  -RestoreRenderer `
  -RequireCloudStages
```

Omit `-RequireCloudStages` when using only local analysis, classification, design, artifact, and
cleanup capabilities. Add `-RequireAzureMcp` to require Azure CLI for the recommended Azure MCP
sign-in flow; it is independent of the PAC-dependent `-RequireCloudStages` switch. The script
does not authenticate Agency, PAC, Azure, Microsoft 365, Copilot Studio, or SharePoint.

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

## Bundled Azure MCP server

Both engines register `azure-mcp` as a local stdio server using the official `@azure/mcp` npm
package and the `npx` launcher:

```powershell
npx -y @azure/mcp@latest server start --mode namespace
```

This bundles the launch configuration, not platform binaries. The engine starts the server over
stdio. `@azure/mcp@latest` selects the version assigned to the configured npm registry's `latest`
tag. npm can reuse cached packages and metadata according to its normal cache settings.
`-y` accepts npm's package-install prompt; it does not disable Azure MCP user confirmation.

There is no fixed Azure MCP version or global tool installation. Registry access is needed to
resolve and download packages that are not cached. Updates take effect when the MCP process
restarts, not while it is running; automatic updates can introduce behavior changes or newer
runtime requirements. A separate .NET SDK is not required for this npm launcher.

The existing Copilot manifest points to `.mcp.json`; the Claude-compatible manifest embeds the
matching registration. No separate per-user MCP configuration is required for this plugin
registration. Updating the plugin does not modify an existing global Azure MCP entry.

Azure MCP telemetry is disabled through `AZURE_MCP_COLLECT_TELEMETRY=false` in the server
environment. This does not disable user confirmation or suppress server failures.

The **full toolset** is exposed through namespace-based discovery: there is no read-only,
namespace, or individual-tool restriction. This includes operations that can create, update, or
delete Azure resources, subject to your Azure permissions. Full tool exposure is **not**
permission to perform those operations. Obtain explicit approval and confirm the tenant,
subscription, target resources, and expected effects before cloud changes. Do not disable the
server's user-confirmation prompts or the client's approval controls.

Authenticate outside the plugin before using Azure resources, for example:

```powershell
az login --tenant "<tenant-id>"
az account show --query "{tenantId:tenantId,subscriptionId:id,name:name}" -o json
```

Azure MCP uses Azure Identity and can also authenticate through supported developer credentials,
such as Visual Studio, Azure PowerShell, or Azure Developer CLI. PAC and browser sign-in do not
replace Azure authentication. Never put client secrets, access tokens, connection strings, or
tenant-specific credentials in the plugin manifests. Specify the intended subscription in
requests instead of assuming that the current default is correct.

Restart the Agency session after updating a local plugin; update or reinstall a marketplace
copy before restarting it. The bundled server supplements PAC and Playwright rather than
replacing them. Local skills retain their offline execution and approval requirements.

To resolve and check the runtime selected by the `latest` tag without invoking an Azure operation:

```powershell
npx -y @azure/mcp@latest server start --help
```

Use the organization's configured npm registry and trust settings. Resolve registry access or
certificate errors without disabling TLS verification. Node.js/npm are shared prerequisites
for Azure MCP, Playwright, and the diagram renderer.

Official references:

- Azure MCP package: `https://www.npmjs.com/package/@azure/mcp`
- Local configuration and authentication: `https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/how-to/github-copilot-cli`
- Server modes, permissions, and confirmation: `https://learn.microsoft.com/en-us/azure/developer/azure-mcp-server/tools/`
- Telemetry configuration: `https://github.com/microsoft/mcp/blob/main/servers/Azure.Mcp.Server/README.md#telemetry-configuration`

## Bundled Microsoft Learn MCP server

Both engines also register `microsoft-learn` using the official remote Streamable HTTP endpoint:

```json
{
  "type": "http",
  "url": "https://learn.microsoft.com/api/mcp"
}
```

This is a remote HTTPS service, not another local executable. No npm/.NET package, Azure login,
API key, or authorization header is needed for this server. It provides official documentation
search, complete article retrieval, and code sample search. Network access to the endpoint is
required; use an MCP client rather than opening it as a normal browser page.

The Azure MCP `documentation` router and the direct `microsoft-learn` server may expose similar
documentation capabilities. They remain separately named registrations. Their availability does
not override any skill's offline execution rules.

Official reference: `https://learn.microsoft.com/en-us/training/support/mcp`

## Evidence accuracy and bounded review

Requirement analysis and classification share a hash-linked publication boundary. The analyzer
publishes its validated manifest last; classification and the shared input resolver reject
missing, pending, mismatched, or modified handoffs rather than silently selecting older evidence.
For existing analyses without this marker, prepare a new run and publish it through the updated
analyzer; do not manufacture a validation marker by editing the files.

Model-facing evidence is provided in lossless JSON batches, with a compact overview and paginated
index. Review every required batch and every fragment of a split record. Full machine inventories
remain available on disk, but should not be pasted into the model alongside the same evidence
again. Batch limits are measured in UTF-8 bytes, not assumed tokenizer-specific token counts.
Content hashes permit unchanged processing artifacts to be reused without treating earlier
analysis prose as fresh source evidence.

## Validation

Run the plugin and shared evidence-contract tests:

```powershell
python -m unittest discover -s .\tests -p "test_*.py" -v
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
directories; then reapply the Agency adaptations in `cad-orchestrator`, `requirement-analyzer`,
`complexity-classifier`, `agent-builder`, `artifact-publisher`, and `postpublish-cleanup`, including
the shared `analysis_handoff.py`, `review_batches.py`, and input resolver changes. Run the full
validation commands above before publishing.