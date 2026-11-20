# Build path A — Standard harness (PAC CLI / classic authoring)

Read this file only when the validated platform is Microsoft Copilot Studio and the harness is
`Standard`. The shared gates in `SKILL.md` Sections 1–8 still apply.

Use for rule-based and predictable Standard-harness agents.

## A1. Create after confirmation

```powershell
pac copilot init `
  --name "<display name>" `
  --publisher-prefix "<prefix>" `
  --schema-name "<prefix_schemaName>" `
  --instructions "Short initial instruction; full instructions follow after scaffold." `
  --project-dir "<project-dir>" `
  --template minimal `
  --environment "<confirmed environment URL>"
```

Use a short one-line initial instruction (multiline CLI args can fail). Treat successful `init` as a remote import; record the agent ID and schema name. Ensure the agent is solution-aware under the approved custom publisher. Then update `agent.mcs.yml` with the Section 5 instruction contract and inspect `settings.mcs.yml` to align model knowledge, file analysis, semantic search, authentication, access, connectability, and orchestration mode with the approved design instead of accepting scaffold defaults.

Prefer generative orchestration for new Standard-harness agents. Do not introduce classic orchestration or classic topics unless the approved design explicitly requires migration/compatibility behavior and the rationale is recorded.

Disable capabilities unless required:

```yaml
gptCapabilities:
  webBrowsing: false
  codeInterpreter: false
```

## A2. Add only approved components

Knowledge files go under `<project-dir>\knowledge\`. Patterns:

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

Do not use `PublicWebsiteSearchSource`. For Dataverse, verify Dataverse Search, table permissions, search config, and Quick Find columns. If PAC-authored YAML for a source fails, configure it through the Copilot Studio UI, then pull and use the platform-generated YAML. Add nothing the approved design does not require.

For every action/connector/flow, apply Section 5.3 descriptions and Section 4 resilience controls. Use environment variables and connection references, configure end-user credentials unless an approved service identity is required, and keep secrets in Key Vault-backed environment variables. Configure Application Insights/correlation telemetry when required or approved; otherwise add it to the recommendation backlog.

## A3. Push, publish, verify

```powershell
pac copilot push --project-dir "<project-dir>"
pac copilot publish --bot "<schema name or agent ID>" --environment "<confirmed environment URL>"
pac copilot list --environment "<confirmed environment URL>"
```

Before publishing the build for evaluation, run the available construction/security checks, resolve build-breaking findings, and record non-blocking recommendations. Confirm Published/Active/Provisioned — do not rely only on exit code. After any UI change, `pac copilot pull` and confirm it did not drift the aligned instructions. Behavioral scoring remains out of scope for this skill.

## A4. Browser fallback (after the first publish)

Some components PAC cannot create/upload: **file/document knowledge (PDF/DOCX uploads)**, **agent flows / Power Automate flows and connection references**, **channels**, and the agent **Details-page Description** field. Procedure: isolate (remove only the failing local definition so CLI-supported components publish), complete the first publish, then open the agent in Copilot Studio for the confirmed environment via browser automation and finish each pending component (upload files and wait for indexing; build flows and bind connections; set the Details description; add approved channels). Then `pac copilot pull`, reconcile, re-publish, re-verify.

## A5. Package

```powershell
pac copilot pack --publisher-prefix "<prefix>" --project-dir "<basePath>\output\build\project\<schemaName>" --solution-name "<solution name>" --output-path "<basePath>\output\build\packages"
```

If `pack` rejects the workspace, fall back to `pac solution export --name "<solution unique name>" --path "<output folder>" --overwrite`. Keep the unpacked source project and produce exactly one deployable ZIP using the managed state required by deployment policy. Confirm the `.zip` exists, inspect solution contents and missing dependencies, and record its absolute path.
