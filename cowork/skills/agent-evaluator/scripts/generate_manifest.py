#!/usr/bin/env python3
"""Generate and validate this skill's hash-bound lifecycle stage manifest.

The implementation is shared; see `lifecycle_artifacts.py` in the local-skills root.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT.parent))

from lifecycle_artifacts import ArtifactError, publish_cli  # noqa: E402
from lifecycle_artifacts import publish as _publish  # noqa: E402

__all__ = ["ArtifactError", "publish"]


def publish(root: Path, status: str, summary: str, source_runs: list[str]) -> dict:
    return _publish(root, SKILL_ROOT, status, summary, source_runs)


if __name__ == "__main__":
    raise SystemExit(publish_cli(SKILL_ROOT))
