# Build path D — Microsoft Cowork skills and plugins

Read this file only when the validated platform is Microsoft Cowork, or for the Cowork portion of
a mixed build. The shared gates in `SKILL.md` Sections 1–8 and
`resources\automation-precedence.md` (Section 4) apply. Record every operation in
`automationLedger` with `platform: Microsoft Cowork`.

Microsoft Cowork is an independent agentic platform/tool, not a Copilot Studio harness. Persist
`agenticPlatform: Microsoft Cowork` and `harness: null`.

Use Cowork only when both hold:

- the classifier marks the capability buildable;
- current tenant evidence confirms Cowork availability, licensing, required plugins or skills,
  identity behavior, and governance.

Cowork has no PAC route. Use the programmatic route where one exists; otherwise the browser is
allowed directly, with a recorded `fallbackJustification`.

## D1. Verify the target

Verify the browser identity, tenant ID, Microsoft 365 Copilot licensing, Cowork availability, and
plugin/skill policy before saving anything. Custom plugins aren't supported in Cowork on mobile.
In tenants with Microsoft Purview Information Barriers, plugin and skill uploads are blocked: record
the component as blocked.

## D2. Author skills and plugins as source files (programmatic)

Create the plugin under `<basePath>\output\build\project\<plugin-slug>\`:

```text
project/<plugin-slug>/
├── appPackage/manifest.json   # Microsoft 365 app manifest v1.28
├── appPackage/color.png       # 192×192
├── appPackage/outline.png     # 32×32
├── appPackage/tools/*.json    # only when a connector declares mcpToolDescription
└── appPackage/skills/<skill-name>/SKILL.md (+ references/)
```

- **Skills.** Each `SKILL.md` needs frontmatter `name` and a trigger-rich `description`
  ("Use when …"), with one responsibility and a numbered workflow. Name connector tools
  explicitly, define the output format, and include no secrets or hard-coded paths. Move detail
  beyond about 3,000 words into `references\`. Don't duplicate Cowork built-in skills.
- **Plugin manifest.** List at most 20 skill folders in `agentSkills` (`{ "folder": "./skills/<name>" }`).
  Add `agentConnectors` only for an approved remote MCP server:
  - Streamable HTTPS with `tools/list` and `tools/call`.
  - Authorization is `None`, `OAuthPluginVault` with a registered `referenceId`, or omitted for
    Dynamic Client Registration.
  - API-key authentication isn't available in Cowork.
  - The v1.28 schema rejects undefined properties such as `packageName`.
- **Existing Claude/Cursor plugin.** Import it with
  `atk import openplugin --path <dir> --output <project> --privacy-url <url> --terms-url <url>`.
  Then replace placeholder connector `referenceId` values before packaging.

## D3. Package, validate, install (programmatic)

```powershell
atk package --manifest-file ".\appPackage\manifest.json" `
  --output-package-file ".\appPackage\build\<plugin-slug>.zip" --output-folder ".\appPackage\build"
atk install --file-path ".\appPackage\build\<plugin-slug>.zip" --scope Personal
```

1. Before `atk install`, check the ASKILL manifest, package, connector, and companion-file
   validation rules. Every referenced folder and tool file must exist in the ZIP.
2. Record the returned `TitleId` and `AppId`.
3. Record the package in `artifacts.coworkPackages`.
4. If `atk install` is rejected, record the attempt. Then upload the same ZIP from Cowork
   **Customize → Plugins → Upload plugin** and choose **Only you** for the build.

## D4. Browser-only Cowork operations

These operations have no documented programmatic route. Use the browser directly, and store
screenshots or exported configuration beneath `build\evidence`:

- custom instructions on **Customize → Preferences** (persist the exact text);
- a standalone personal skill (prefer a skills-only plugin for reproducibility);
- **Share** with specific users;
- Microsoft 365 admin center upload for tenant distribution, unless a Microsoft Graph app-catalog
  submission succeeds.

Admin approval and each user's connector sign-in are `manual`.

## D5. Verify and reconcile

1. Verify that the plugin, its skills, and its connectors appear under Cowork
   **Customize → Plugins/Skills** for the build identity.
2. Verify permissions and user-visible simulation disclosures.
3. Verify the actual delegated result, without claiming shared-application behavior.
4. Use `buildMode: cowork-configuration`. Cowork plugin ZIPs live under `project\` and in
   `artifacts.coworkPackages`, never in `packages\`.
5. If Cowork is unavailable or differs from the classification, mark the component blocked or
   deferred and recalculate coverage. Don't substitute Copilot Studio without classifier review.
