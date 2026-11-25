# Lisa for Copilot Cowork

Release 1 contains two skills: analyze requirements, then classify the validated analysis. The only connector is Microsoft Learn over anonymous HTTPS. The package does not include solution design, deployment or tenant publishing. See [how Lisa handles project data](PRIVACY.md).

**[Download lisa.zip](dist/lisa.zip?raw=1)** and follow the [upload instructions](../README.md#upload-lisa-to-cowork). No local build is required.

Both skill runners need Python and Node.js 20+ (`node` on the execution host's `PATH`). Ajv is included in the ZIP: schema validation runs locally without npm, a network connection, or Python's `jsonschema` package. If Node is unavailable, the skills stop rather than publishing an unvalidated result.

## Try it with a OneDrive project

1. **Prepare a small test folder in OneDrive.** Create the layout below. Save `{"basePath":"."}` in `lisa-config.json`; the dot means the folder containing that file. In `brief.txt`, write a non-sensitive requirement, for example: “Employees need to ask which expenses are reimbursable and receive an answer that cites the travel policy.” Use the exact lowercase name `requirements`.

   ```text
   LISA-pilot/
     lisa-config.json
     requirements/
       brief.txt
   ```

2. **Start a Cowork task and attach the whole folder.** In the **Cowork** tab, open an existing project or select **+** next to **Projects** to create one. From the project's chat input, select **+ > Attach cloud files and folders** and choose `LISA-pilot` in OneDrive. The Cowork project groups your tasks; the attached OneDrive folder holds the files LISA processes.

3. **Run the analyzer.** Send: *“Use `lisa-requirement-analyzer` with the attached `LISA-pilot` folder and its `lisa-config.json`. Save the validated analysis in that project and show me the output paths.”* Open `LISA-pilot/output/analysis/` in OneDrive. Before continuing, confirm it contains a `requirement-analysis_<timestamp>.md`, its `.json` ledger, and the matching `-manifest.json` with `publication.status` set to `validated`.

4. **Classify the same analysis in a new task.** Attach the same OneDrive project folder and send: *“Use `lisa-complexity-classifier` with this config and the latest validated analysis. Use Microsoft Learn for research and show me the classification report and manifest.”* Check `LISA-pilot/output/classification/` for the timestamped Markdown report, JSON result, and `classification-manifest.json`. Keep the run folders, reports and manifests together; the classifier verifies the handoff, not just the report text.

If you start a new task, reattach the same OneDrive folder. If Cowork can preview the files but cannot read them from Python or save the outputs back to that folder, the run is incomplete. A report pasted into chat is not a substitute for the saved report and its manifest.

Microsoft Learn: [Use projects in Copilot Cowork](https://learn.microsoft.com/copilot/cowork/cowork-projects) · [Work with files in Cowork](https://learn.microsoft.com/copilot/cowork/use-cowork#work-with-files).

## Rebuild the plugin

From this directory, install the build dependencies (`python -m pip install Pillow jsonschema`). Run **`python build.py`** to validate the manifest against the checked-in [Teams v1.29 schema](https://developer.microsoft.com/json-schemas/teams/v1.29/MicrosoftTeams.schema.json), check the entry points and companion limits, and write `dist/lisa.zip`. `jsonschema` is a build dependency, not a skill runtime dependency.

Run `python test_package.py` with Node.js 20+ on `PATH` to exercise the extracted package. The skills use the checked-in validator in `cowork/skills`. When changing the validator or upgrading Ajv, run `npm ci` and `npm run bundle` here first. Include the regenerated validator and ZIP with the change.

## Pilot release checks

Local package tests do not exercise Cowork, Microsoft Learn or OneDrive. Before sharing this version:

For the runtime check, run `python build.py --dev-runtime-check` and privately upload the temporary ZIP it prints **only in an isolated test environment**. Run `lisa-runtime-check` there to verify runtimes, outbound HTTPS, the connector and file persistence. It uses the same app identity: do not distribute this diagnostic build or upload it over a pilot installation. The skill is absent from the released manifest and `dist/lisa.zip`.

For the Learn check, start with an empty classifier run and a validated sample analysis. Record how Cowork transfers the first fetch response to `save-reference` and the resulting ID, byte count and SHA-256. Then start a fresh task with the release ZIP: it must save all expected pages and reach `prepare` without an operator prompt, guessed tool aliases, or re-fetching the first page. A chat message saying the pages were fetched does not establish that handoff.

1. Install `dist/lisa.zip` privately and verify the name **Lisa**, both skills, and Microsoft Learn with no sign-in.
2. Repeat the walkthrough with **three authorized real requirement sets** on the pilot web and desktop clients. Start a fresh task for classification each time. Record the analysis and classification manifest paths and confirm all results persisted to OneDrive.
3. In each classification result, verify `ms-learn-mcp` was used and `azure-mcp`, `ms-eng-hub-mcp`, and `ms-icm-mcp` are `unavailable`. An inaccessible project, unavailable required connector or incomplete publication is a blocked run, not a pass.
4. Run the Cowork Plugin Evals kit (`gim-home/cowork-plugin-evals`) on the release ZIP. Record the kit revision, results, and any failures before sharing with pilot users.
