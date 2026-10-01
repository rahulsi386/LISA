#!/usr/bin/env python3
"""Generate and validate this skill's hash-bound lifecycle stage manifest.

The implementation is shared; see `lifecycle_artifacts.py` in the local-skills root.
Builder-specific automation and classification checks run before publication.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT.parent))

from lifecycle_artifacts import STATUS_CHOICES, ArtifactError  # noqa: E402
from lifecycle_artifacts import publish as _publish  # noqa: E402
from validate_artifacts import (  # noqa: E402
    load_object,
    validate_automation_ledger,
    validate_classification_reconciliation,
)

__all__ = ["ArtifactError", "main", "publish"]


def publish(root: Path, status: str, summary: str, source_runs: list[str]) -> dict:
    validate_classification_reconciliation(root)
    validate_automation_ledger(root, load_object(root / "agent-build-handoff.json"))
    return _publish(root, SKILL_ROOT, status, summary, source_runs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish the agent-builder lifecycle manifest")
    parser.add_argument("--root", required=True)
    parser.add_argument("--status", required=True, choices=list(STATUS_CHOICES))
    parser.add_argument("--summary", required=True)
    parser.add_argument("--source-run", action="append", default=[])
    args = parser.parse_args(argv)
    try:
        result = publish(Path(args.root), args.status, args.summary, args.source_run)
    except (ArtifactError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
