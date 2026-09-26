# Contributing to LISA

Contributions are reviewed by the maintainer under [GOVERNANCE.md](GOVERNANCE.md). By submitting
original contributions, you agree they are provided under the repository's [MIT license](LICENSE).
Submit only material you have the right to contribute and retain third-party notices.

## Prepare a change

1. Start from an up-to-date `main` and create a focused branch.
2. Discuss substantial workflow, dependency, or compatibility changes in an issue first.
3. Identify whether the plugin, Scout, shared setup, or multiple distributions are affected.
4. Add or update regression tests and documentation alongside behavior changes.
5. Update the Unreleased section of [CHANGELOG.md](CHANGELOG.md).

Keep real tenant configuration, customer inputs, credentials, browser state, and generated delivery
artifacts out of commits. Use synthetic fixtures. Do not run cloud deployment, publication, or
cleanup as part of local test setup.

## Local validation

Use Windows with PowerShell 7, Python 3.13, and Node.js 22 to match CI. From the repository root,
prepare an isolated Python environment and restore the renderer:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r github-copilot-cli/requirements.txt
npm --prefix github-copilot-cli/skills/solution-designer/renderer ci
pwsh -File scripts/Test-LisaRepository.ps1 -Suite Plugin
pwsh -File scripts/Test-LisaRepository.ps1 -Suite Scout
```

Run the optional GEPA engine check separately, as CI does:

```powershell
python -m pip install -r github-copilot-cli/skills/agent-optimizer/requirements-gepa.txt
pwsh -File scripts/Test-LisaRepository.ps1 -Suite Gepa
```

The runner uses only repository test directories, invokes each skill's tests separately to avoid
duplicate module names, and returns a nonzero exit code on failure. The classifier's test-only CLI
clock makes offline fixtures deterministic; production reference freshness validation is unchanged.
Do not refresh verification timestamps just to make tests pass.

The supported runtime prerequisites remain documented in the [plugin guide](github-copilot-cli/README.md).
The CI version choices are tested combinations, not a claim that every supported version is covered.
Scout checks cover shared infrastructure only; tests requiring its platform-specific diagram engine
or Desktop host must also be run in the supported Scout environment when those components change.

## Pull request checklist

- Describe the problem, change, affected distributions, and compatibility implications.
- List exact validation commands and results, including skips and tests not run.
- Include redacted evidence for authorized live tests when relevant; never upload raw credentials or customer data.
- Explain any permission, dependency, remote-write, or deletion behavior changes.
- Preserve host-specific diagram and GEPA implementations when changing shared code.
- Request code-owner review and resolve comments before merging.

Report vulnerabilities privately using [SECURITY.md](SECURITY.md), not in a public issue or pull request.