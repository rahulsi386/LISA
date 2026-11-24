---
name: "artifact-generator"
description: "Generates a final solution document and an interactive LISA execution tree from config-resolved lifecycle stage artifacts."
---

# LISA Artifact Generator

## Purpose

Produce a customer-ready artifact set from completed LISA lifecycle stages:

1. `artifacts\solution-document.md` — a concise, customer-shareable solution document that synthesizes the decisions and outcomes worth the customer's time.
2. `artifacts\lisa-execution-tree.html` — a self-contained execution tree showing every LISA stage, its status, run ID, duration, source Markdown, and core artifacts.
3. `artifacts\solution-business-architecture.png`, `solution-architecture.png` and `solution-sequence.png` — customer-named copies of the current validated business, engineering and sequence renders when available.
4. `artifacts\artifact-generation-manifest.json` — the terminal hash inventory for the complete generated set.

The generator is read-only with respect to upstream stage folders. It never changes requirement, classification, design, build, evaluation, or optimization evidence.

When invoked by `cad-orchestrator`, follow `..\workflow-checkpointing.md`. Start the `artifacts`
stage when the `ART-*` ID is assigned; checkpoint input snapshot, render, validation, and publication
boundaries. Commit `artifact-generation-manifest.json` only after every listed artifact hash is final.

## Run

The packaged script is deterministic and does all reading, composition, redaction, validation,
and atomic publication. Do not read stage artifacts yourself, draft document content, or edit its
outputs. Run it with the config file only:

```powershell
python "<skill-dir>\scripts\generate_artifacts.py" --config "<path-to>\lisa-config.json"
```

- `lisa-config.json` must contain `basePath`. Set an IANA `timeZone` (for example
  `"Asia/Kolkata"`) when timestamps must follow a business timezone.
- The script reads only `<basePath>\output\analysis`, `classification`, `design`, `build`,
  `evaluation`, and `optimization`, and writes only `<basePath>\output\artifacts`. It rejects
  caller-supplied child paths and paths outside `basePath`.
- It excludes internal IDs, hashes, absolute paths, raw instructions, full test transcripts, and
  evidence registers from the customer document, and shows `Not recorded` for missing durations.

The skill is complete only when the command exits successfully and prints a JSON result with both
output paths. On failure, report the printed error; do not work around it by hand.
