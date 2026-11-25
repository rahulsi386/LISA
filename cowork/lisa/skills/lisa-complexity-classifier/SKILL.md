---
name: lisa-complexity-classifier
description: Classify the complexity and platform fit of a validated LISA requirement analysis using Microsoft Learn. Produces a scored report and classification artifacts in the same OneDrive project.
---

# Classify a validated analysis in Cowork

Open the same OneDrive project, at the same filesystem path used for analysis, and use its `lisa-config.json`. Run Python from this skill's directory. If the validated analysis is missing or no longer bound to this project, stop and direct the user to **lisa-requirement-analyzer**. Do not edit the manifest to make validation pass.

The runner invokes `node` (Node.js 20+) for local validation with the bundled Ajv library. If Node is unavailable, report the blocker; do not skip validation.

Microsoft Learn (`ms-learn-mcp`) is the only configured connector. Use generic product/capability queries; do not send project documents, names, private URLs, or credentials. Record `azure-mcp`, `ms-eng-hub-mcp` and `ms-icm-mcp` as `unavailable` because they are not included in Release 1; do not attempt to sign in to them. If Learn is unavailable, or the runner cannot refresh a required public reference, report the blocker instead of inventing evidence.

Follow `references/workflow.md`, starting with **Mandatory boundaries** and **Prepare and trusted input**. Run `init-references`. Fetch the **first manifest URL only** with the Learn action exposed to the agent and pass the actual Markdown to `save-reference`. A `saved` receipt means the runner read back matching bytes. Continue with the remaining entries and then `ingest-references` and `prepare` **without pausing for confirmation**. Do not call connector names from scripts, fetch a successful page twice, or recover text from chat or a journal. If the first response cannot be transferred to a file or stdin, stop there and report the handoff blocker; do not fetch the whole manifest first.

Read all indexed evidence batches and the applicable decision and design guidance. Complete the research register and model, expanding research only when the persisted gap gate requires it, then publish with the runner. Do not hand-score complexity or mark an unchecked reference as consulted.

Return the report, JSON and manifest paths under `output/classification/` for user review. This is the last skill in Release 1; do not claim to have run a solution designer or deploy anything.
