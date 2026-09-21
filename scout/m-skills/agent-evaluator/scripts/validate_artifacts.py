#!/usr/bin/env python3
"""Validate this skill's lifecycle stage against its packaged artifact contract.

The implementation is shared; see `lifecycle_artifacts.py` in the local-skills root.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT.parent))

from lifecycle_artifacts import (  # noqa: E402
    ArtifactError,
    load_object,
    validate_cli,
)
from lifecycle_artifacts import validate as _validate  # noqa: E402

__all__ = ["ArtifactError", "load_object", "validate"]


def validate(root: Path) -> dict:
    return _validate(root, SKILL_ROOT)


if __name__ == "__main__":
    raise SystemExit(validate_cli(SKILL_ROOT))
