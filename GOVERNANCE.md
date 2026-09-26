# Repository Governance

## Ownership and scope

LISA is maintained by [Rahul Prashant Singh (@rahulsi386)](https://github.com/rahulsi386).
The maintainer reviews contributions, resolves scope and compatibility questions, and approves
releases. [CODEOWNERS](.github/CODEOWNERS) requests owner review for repository changes.

This is a community-maintained project, not a Microsoft-supported product. Agency metadata
identifies a distribution target; it is not certification or an endorsement. Certification
remains `draft`. Passing local tests or CI does not establish production readiness.

Repository governance applies to both `github-copilot-cli/` and `scout/`. It does not replace the
runtime human approvals, tenant permissions, or publication and cleanup checks described in the
[plugin guide](github-copilot-cli/README.md).

## Contribution decisions

- Use a pull request and describe the behavior, risks, tests, and affected distributions.
- Obtain maintainer approval for scope changes, dependencies, security-sensitive changes, and releases.
- Preserve Scout-specific and plugin-specific behavior; do not blindly copy one distribution over the other.
- Never weaken validation or skip a failing test merely to obtain a passing check.
- Record user-visible changes and compatibility implications in [CHANGELOG.md](CHANGELOG.md).
- Discuss disagreements on the pull request; the maintainer records the final rationale there.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the local validation commands.

## Required GitHub settings

The following settings require a repository administrator. Committing this file, CODEOWNERS, or a
workflow does **not** enable them. Their remote state has not been verified by this change.

Configure a ruleset for `main` that:

- Requires pull requests, at least one non-author approval, and code-owner review.
- Dismisses stale approvals after new commits and requires resolved review conversations.
- Requires the `Plugin Checks`, `Scout Checks`, and `GEPA Checks` status checks after their first run.
- Requires the branch to be up to date and blocks force pushes and branch deletion.
- Restricts bypass access; document any emergency bypass and follow-up validation in the pull request.

Enable private vulnerability reporting, dependency alerts, and secret scanning/push protection
where available. Add another trusted code owner to CODEOWNERS before requiring approvals for
maintainer-authored pull requests; the sole code owner cannot approve their own pull request.

## CI boundary

The Windows CI workflow runs the plugin's local suites and renderer/publisher checks, a separate
synthetic GEPA engine check, and Scout's shared checkpoint, metadata, and evidence-contract tests.
It uses read-only repository permissions and does not receive tenant credentials or deploy agents.

CI does not validate live Copilot Studio behavior, SharePoint publication, cloud permissions,
Scout Desktop end-to-end operation, or final video rendering. Changes affecting those surfaces
need separately authorized manual testing, with redacted evidence linked from the pull request.

## Releases and compatibility

Before tagging a release, the maintainer must:

1. Confirm required checks passed on the release commit and review dependency/security findings.
2. Review the changelog, installation instructions, and any migration or rollback guidance.
3. Test installation on the affected hosts and perform any required live smoke tests with consent.
4. Update applicable plugin version metadata consistently and create a versioned tag and GitHub release.
5. Describe known limitations and unverified surfaces; never imply testing that did not occur.

Use semantic versioning for the plugin: breaking config, artifact, or workflow contracts require
a major version and migration guidance; backward-compatible features use a minor version; fixes
use a patch version. Existing checkpoints must not silently migrate between incompatible versions.
No release is created automatically by CI.

## License and conduct

Original LISA code is licensed under [MIT](LICENSE). Bundled fonts, images, dependencies, and other
third-party materials retain their own licenses and notices. The MIT license does not grant
trademark rights or rights to customer data and generated assets.

Keep discussions respectful, factual, and focused on the work. Harassment, discriminatory remarks,
and disclosure of private information are not acceptable; maintainers may moderate or restrict
participation. Use [SECURITY.md](SECURITY.md) for vulnerabilities and [SUPPORT.md](SUPPORT.md) for help.