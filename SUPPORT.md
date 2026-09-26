# Support

LISA is a community-maintained project with best-effort support through
[GitHub Issues](https://github.com/rahulsi386/LISA/issues). It is not a Microsoft-supported product
and provides no SLA or production-readiness guarantee.

Before opening an issue, check the [plugin guide](github-copilot/README.md), its troubleshooting
section, and existing issues. For Scout, start with the [Scout guide](scout/README.md).

For a reproducible bug, include:

- The LISA commit/version, host and engine, OS, Python, Node.js, PowerShell, and PAC versions.
- The skill/stage, expected result, actual result, and minimal reproduction using synthetic data.
- The exact failing command and a short redacted error excerpt.
- Whether local tests pass and whether the issue requires an authenticated cloud service.

Do not attach customer requirements, full checkpoints, screenshots with private data, browser state,
tokens, or complete tenant configuration. Report vulnerabilities through [SECURITY.md](SECURITY.md).

Feature requests should describe the user problem, affected host, desired behavior, and compatibility
or permission implications. Maintainers prioritize reproducible correctness and security issues;
requesting a feature does not commit the project to implementing it.