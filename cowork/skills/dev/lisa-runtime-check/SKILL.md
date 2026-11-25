---
name: lisa-runtime-check
description: Check which runtimes, connectors, and project file operations this Cowork test session actually supports. For private diagnostic builds only.
---

# Check the Cowork runtime

Use only in an isolated test project. Report each observation as **observed**, **failed** (give the reason), or **not run**. Run checks in the skill execution host, not on the user's workstation. Do not install dependencies, search for credentials, enumerate tenant data, or send project data in requests.

1. Run `python --version`. If available, run `python -c "import MODULE"` separately for `jsonschema`, `docx`, `pptx`, `pypdf`, `PIL`, and `networkx`, replacing `MODULE` with each import name. Report import failures, not just package presence.
2. Run `node --version`, then `node -e "require('@resvg/resvg-js')"` to test the installed renderer. A missing package is not evidence that a bundled native module would fail. Run `pwsh --version` separately.
3. Test the Learn handoff independently of outbound HTTPS. In a fresh isolated task with a validated sample analysis, use the installed classifier's `init-references`. From the returned manifest take the **first ID and URL**, call the advertised Learn page-fetch action once as the agent, and follow the `save-reference` step in the classifier workflow. Record the actual action label, response shape (not the page body), supported transfer operation (result-file export or direct text binding), and the runner's saved ID, byte count and read-back SHA-256. A returned URL, chat preview, manually reconstructed file or journal replay is not a pass. If the body cannot be passed through unchanged, stop the handoff check and report the observed limitation without probing alternate names. Report this separately from a Python request to `https://learn.microsoft.com/` with a 10-second timeout; success at one does not imply success at the other.
4. With the user's permission, create a new uniquely named marker containing a random non-sensitive value in the attached OneDrive test folder (exclusive creation, never overwrite). Reopen it through the script host. Have the user reattach the same folder in a **new task**, then read back the value from the marker file. Report same-task read/write and cross-task persistence separately. If a stable path cannot be established, mark the stage handoff blocked.
5. Record observed elapsed time for the checks. If the host does not report an execution time limit, mark the limit **unknown**; do not run an unbounded test or infer a limit from a short successful command.

Return the observations to the tester. Do not treat this diagnostic as a successful production skill run.
