"""Offline Ajv schema validation for the Cowork analysis and classification skills."""

import json
import subprocess
from pathlib import Path
from typing import Any


def validate_schema(schema: dict[str, Any], value: Any, label: str, error_type: type[RuntimeError]) -> None:
    runner = Path(__file__).with_name("design-validator.cjs")
    try:
        result = subprocess.run(
            ["node", str(runner)], cwd=runner.parent,
            input=json.dumps({"schema": schema, "value": value}, allow_nan=False),
            capture_output=True, encoding="utf-8", timeout=60,
        )
    except FileNotFoundError as exc:
        raise error_type(f"{label}: Node.js is required for Ajv validation; put node on PATH") from exc
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise error_type(f"{label}: could not run Ajv validation: {exc}") from exc
    if result.returncode:
        raise error_type(f"{label} {result.stderr.strip() or 'Ajv validation failed'}")
