# Build path C — Copilot chat harness (Microsoft 365 Copilot agent page)

Read this file only when the validated platform is Microsoft Copilot Studio and the harness is
`Copilot chat`. The shared gates in `SKILL.md` Sections 1–8 still apply.

Use when the selected runtime is the Copilot chat harness. Do not create a Standard-harness custom agent and infer that adding the Microsoft 365 channel changes its harness.

## C1. Create after confirmation

Open Copilot Studio for the verified environment. Verify the browser identity/tenant matches the PAC-confirmed user/tenant and the environment picker matches the verified environment. Record both; on any mismatch, stop and report it before the first remote Save/Create. When they match, proceed.

After confirmation:

1. Select **Agents** in the sidebar.
2. Select **Microsoft 365 Copilot** from the agent list.
3. On the **Agents** card, select **Add**.
4. Set a representative name (current limit: 42 characters), a ≤50-word routing description, the Section 5 instructions, and approved suggested prompts.
5. Add approved SharePoint or Copilot/Graph connector knowledge. Web browsing remains off unless explicitly approved.
6. Select **Create**, record the agent ID/resource identity, save/reload, and verify the instructions and description persisted.

This starting surface creates an **agent for Microsoft 365 Copilot** powered by the Copilot chat harness. It is different from publishing a custom Standard-harness agent to the Teams + Microsoft 365 channel.

## C2. Add bounded tools and knowledge

Copilot chat-harness agents can use approved prompts, agent flows, computer use, custom connectors, MCP, and REST API tools where the tenant/UI supports them. Apply Sections 4 and 5.3 to each tool. If the design grows into GitHub-exclusive skills, memory, native Office/PDF file creation/editing, long autonomous planning/recovery, or external-customer publishing, stop and reassess the harness instead of forcing the capability into this path.

SharePoint knowledge uses the runtime user's permissions. Verify site/library scope, permissions, freshness, and missing-evidence behavior. For each tool, verify user versus maker authentication, narrow inputs, descriptions, completion output, side effects, confirmation, error behavior, and first-run connection experience.

## C3. Publish, deploy internally, verify, and package

Publish from the agent overview. Complete the catalog information and availability options required by the organization's Microsoft 365/Teams catalog and admin policy. This harness publishes to internal users; verify availability in Microsoft 365 Copilot/Teams with an authorized test user.

Use supported PAC/solution tooling to add the live bot and required components to the governed solution before non-development deployment or packaging. If the preview surface exposes no supported solution operation, record the limitation and use the documented tenant-supported export path; never relabel a Standard-harness artifact as a Copilot chat-harness package. Inspect dependencies and retain source and managed release artifacts as required.
