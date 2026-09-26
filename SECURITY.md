# Security Policy

## Reporting a vulnerability

Do not disclose vulnerabilities, exploit details, tenant identifiers, credentials, or customer
data in public issues or pull requests.

Use GitHub's **Security > Advisories > Report a vulnerability** on
[rahulsi386/LISA](https://github.com/rahulsi386/LISA/security/advisories/new) when private vulnerability
reporting is enabled. If that option is unavailable, open a public issue containing only a request
for a private security contact, with no technical or sensitive details. Wait for a private channel
before sharing the report. Administrators should enable this feature as described in [GOVERNANCE.md](GOVERNANCE.md).

In the private report, include the affected commit/version, minimal reproduction, impact, relevant
configuration with secrets removed, and suggested mitigations. Use synthetic data when possible.
If a secret has already been exposed, revoke or rotate it through the issuing service immediately.

## Support scope

Security fixes target the current `main` branch until versioned releases and supported maintenance
branches are announced. No historical release receives a guaranteed backport. Support is best
effort; there is no response or remediation SLA. A passing CI check is not a security certification.

## Trust boundaries

- Install only reviewed plugin revisions and dependencies, and inspect updates before enabling them.
- Use least-privileged identities and non-production environments for testing remote operations.
- Playwright has unrestricted local file access; isolate sensitive files from the execution workspace.
- Treat source requirements, imported skills, model output, and remote content as untrusted data.
- Never commit tokens, cookies, browser storage state, private keys, or customer delivery artifacts.
- Preserve the runtime review, publication-verification, and exact-phrase cleanup gates.

Current runtime limitations, including the floating Azure MCP dependency, remain documented in the
[plugin safety guidance](github-copilot-cli/README.md#limitations-and-safety). Repository governance
does not change those runtime permissions or dependencies.