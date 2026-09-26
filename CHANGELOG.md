# Changelog

User-visible changes are recorded here. Unreleased entries are not a published release.

## Unreleased

### Added

- MIT license for original LISA code, with Rahul Prashant Singh as copyright holder.
- Repository ownership, contribution, security-reporting, support, and release policies.
- Documented existing code ownership and administrator guidance for protected branches and private reporting.
- Windows CI and a matching local runner for plugin tests, Scout shared-infrastructure checks,
  and the synthetic GEPA engine test. CI performs no tenant operations.

### Fixed

- Plugin artifact test fixtures now include a validated analysis handoff and the standalone video contract.
- Offline classifier tests use a test-only reference clock instead of expiring with the wall clock;
  fresh and expired reference behavior is covered explicitly.

### Unchanged

- Runtime checkpoint enforcement, cloud permissions, executable dependency versions, and draft
  certification are unchanged. Live agent behavior and publication still require authorized manual validation.