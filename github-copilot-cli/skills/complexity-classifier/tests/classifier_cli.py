"""Run the real classifier CLI with a deterministic reference-verification clock."""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "classifier_test_cli", SKILL_ROOT / "scripts" / "complexity_classifier.py",
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Cannot load the classifier CLI")
classifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(classifier)
manifest = json.loads(classifier.REFERENCE_MANIFEST_PATH.read_text(encoding="utf-8"))
REFERENCE_TIME = datetime.fromisoformat(manifest["verified_at"]) + timedelta(hours=1)


class ReferenceClock(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return REFERENCE_TIME.astimezone(tz)
        return REFERENCE_TIME.astimezone().replace(tzinfo=None)


if __name__ == "__main__":
    with patch.object(classifier, "datetime", ReferenceClock):
        raise SystemExit(classifier.main())