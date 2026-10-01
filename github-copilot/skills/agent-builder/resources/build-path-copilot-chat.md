# Build path C — Copilot chat harness (agent for Microsoft 365 Copilot)

Read this file only when the validated platform is Microsoft Copilot Studio and the harness is
`Copilot chat`. The shared gates in `SKILL.md` Sections 1–8 and
`resources\automation-precedence.md` apply. Record every remote write in `automationLedger`.

Use when the selected runtime is the Copilot chat harness. Do not create a Standard-harness custom
agent and infer that adding the Microsoft 365 channel changes its harness.

## C1. Programmatic probe, then create

1. Pass the toolchain gate with the latest PAC.
2. Check whether the target environment already has the agent:
   - Run `pac copilot list --environment "<verified environment URL>"`.
   - Run `pac copilot init help`, and record the result as a `pac-cli` attempt.
3. If the agent already exists and is listed, `pac copilot clone` it and continue at C2.
4. No documented PAC command creates a Copilot chat-harness agent. After the recorded PAC
   attempt, creating it is the justified browser exception. Before the first Save/Create:
   - Open Copilot Studio for the verified environment.
   - Verify that the browser identity/tenant matches the PAC-confirmed user/tenant.
   - Verify that the environment picker matches the verified environment.
   - On any mismatch, stop and report it.
5. Create the agent in Copilot Studio:
   1. Select **Agents** → **Microsoft 365 Copilot** → **Add**.
   2. Set a representative name (current limit: 42 characters), a ≤50-word routing
      description, the Section 5 instructions, and approved suggested prompts.
   3. Select **Create**, and record the agent ID/resource identity.
6. Reconcile immediately. Run `pac copilot list`. If the agent is listed, `pac copilot clone` it
   into `<basePath>\output\build\project\<schemaName>` and record `reconciliation`. From then on,
   every change goes through the workspace (`push`/`pull`). If it is not listed, record that as
   the justification for each later UI operation.

This surface creates an **agent for Microsoft 365 Copilot** powered by the Copilot chat harness.
It is different from publishing a custom Standard-harness agent to the Teams + Microsoft 365
channel.

## C2. Add bounded tools and knowledge

Copilot chat-harness agents can use approved prompts, agent flows, computer use, custom
connectors, MCP, and REST API tools where the tenant supports them.

- In a cloned workspace, author each knowledge source and tool definition from a pulled
  reference and push it (see `automation-precedence.md` Section 3).
- Create custom connectors with `pac connector create --solution-unique-name`.
- Use the UI only for an operation whose push was rejected, or when the agent can't be cloned.
- Keep web browsing off unless explicitly approved.
- Apply Sections 4 and 5.3 to each tool.
- If the design grows into GitHub-exclusive skills, memory, native Office/PDF file
  creation/editing, long autonomous planning/recovery, or external-customer publishing, stop and
  reassess the harness instead of forcing the capability into this path.

SharePoint knowledge uses the runtime user's permissions. Verify:

- site/library scope, permissions, freshness, and missing-evidence behavior;
- for each tool: user versus maker authentication, narrow inputs, descriptions, completion
  output, side effects, confirmation, error behavior, and first-run connection experience.

## C3. Publish, deploy internally, verify, and package

1. Publish with `pac copilot publish` when the agent is PAC-visible. Otherwise publish from the
   agent overview as a recorded exception.
2. Download the Microsoft 365 package with
   `pac copilot-studio download-agent-channel-manifest --agent-id "<agent ID>" --channel-name M365 --out-file "<project-dir>\m365-channel.zip"`.
   Use `atk install --file-path <zip> --scope Personal` for maker verification.
3. For organizational availability:
   - complete the catalog information required by Microsoft 365/Teams admin policy;
   - admin approval is `manual`;
   - verify availability in Microsoft 365 Copilot/Teams with an authorized test user.
4. Add the live bot and required components to the governed solution with
   `pac solution add-solution-component --AddRequiredComponents`, before non-development
   deployment or packaging. Export with `pac solution export`.
5. If no supported solution operation exists for this surface, record the limitation and use the
   documented tenant-supported export path. Never relabel a Standard-harness artifact as a
   Copilot chat-harness package.
6. Inspect dependencies, and retain source and managed release artifacts as required.
