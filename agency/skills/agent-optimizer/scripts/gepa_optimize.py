"""Run one resumable Agency GEPA step; live operations remain host-owned."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gepa_runtime import ArtifactError, abort_search, accept_host_response, advance, initialize, session_lock
from lisa_path_resolver import LisaConfigError, resolve_lisa_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["init", "advance", "seal-reflection", "abort"])
    parser.add_argument("--config", required=True)
    parser.add_argument("--reason")
    args = parser.parse_args()
    try:
        paths = resolve_lisa_config(Path(args.config))
        with session_lock(paths):
            if args.action == "init":
                session = initialize(paths)
                result = {"status": "initialized", "runId": session["runId"]}
            elif args.action == "advance":
                result = advance(paths)
            elif args.action == "abort":
                if not args.reason or not args.reason.strip():
                    raise ArtifactError("Abort requires a non-secret --reason")
                result = abort_search(paths, args.reason)
            else:
                result = accept_host_response(paths, "reflection")
        print(json.dumps(result, indent=2))
        return 3 if result["status"] == "awaiting-host" else 2 if result["status"] in ("blocked", "budget-exhausted") else 0
    except (ArtifactError, LisaConfigError, OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())