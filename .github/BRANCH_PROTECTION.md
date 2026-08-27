# Main branch protection

The `main` branch must be protected in GitHub repository settings. Direct commits to `main` are not allowed; every change must be proposed through a pull request and merged only after approval.

## Required repository ruleset

Create or update a repository ruleset for `refs/heads/main` with these requirements:

- Enforcement status: **Active**
- Target: **Branch**
- Include pattern: `refs/heads/main`
- Bypass list: empty unless a separately documented break-glass process is approved
- Require a pull request before merging
- Require at least **1 approving review**
- Dismiss stale approvals when new commits are pushed
- Require approval from someone other than the last pusher
- Require conversation resolution before merge
- Block branch deletion
- Block non-fast-forward updates

The JSON template in [`repository-rulesets/main-pr-approval.json`](./repository-rulesets/main-pr-approval.json) records the expected GitHub ruleset configuration for audit and setup.

## Verification

Repository administrators should periodically verify that the active GitHub ruleset matches this document. This repository-level setting is what enforces the policy; the files in this directory document and standardize the required configuration.
