"""Freeze evaluator-owned GEPA inputs or seal one candidate evaluation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gepa_runtime import ArtifactError, accept_host_response, freeze_evaluation, session_lock
from lisa_path_resolver import LisaConfigError, resolve_lisa_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "seal"])
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        paths = resolve_lisa_config(Path(args.config))
        with session_lock(paths):
            result = freeze_evaluation(paths) if args.action == "freeze" else accept_host_response(paths, "evaluation")
        print(json.dumps(result, indent=2))
        return 0
    except (ArtifactError, LisaConfigError, OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())