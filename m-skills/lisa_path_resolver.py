#!/usr/bin/env python3
"""Resolve canonical LISA child paths beneath a config-provided basePath."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class LisaConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class LisaPaths:
    config: dict[str, Any]
    config_path: Path
    base: Path
    requirements: Path
    output: Path
    analysis: Path
    classification: Path
    design: Path
    build: Path
    evaluation: Path
    optimization: Path
    artifacts: Path
    publication: Path
    eval_data: Path
    checkpoint_root: Path
    workflow_pointer: Path

    def public(self) -> dict[str, Any]:
        return {
            "configPath": str(self.config_path),
            "basePath": str(self.base),
            "requirements": str(self.requirements),
            "output": str(self.output),
            "analysis": str(self.analysis),
            "classification": str(self.classification),
            "design": str(self.design),
            "build": str(self.build),
            "evaluation": str(self.evaluation),
            "optimization": str(self.optimization),
            "artifacts": str(self.artifacts),
            "publication": str(self.publication),
            "evalData": str(self.eval_data),
            "checkpointRoot": str(self.checkpoint_root),
            "workflowPointer": str(self.workflow_pointer),
        }


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LisaConfigError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LisaConfigError(f"Expected a JSON object in {path}")
    return value


def _relative_parts(value: str, label: str) -> tuple[str, ...]:
    normalized = value.replace("/", "\\").strip()
    if not normalized:
        raise LisaConfigError(f"{label} must not be empty")
    if re.match(r"^[A-Za-z]:", normalized) or normalized.startswith("\\"):
        raise LisaConfigError(f"{label} must be relative")
    return tuple(part for part in normalized.split("\\") if part and part != ".")


def resolve_relative(base: Path, value: str, label: str) -> Path:
    parts = _relative_parts(value, label)
    candidate = (base / Path(*parts)).resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError as exc:
        raise LisaConfigError(f"{label} escapes basePath: {value}") from exc
    return candidate


def resolve_lisa_config(config_path: Path) -> LisaPaths:
    config_path = config_path.expanduser().resolve()
    if config_path.name.casefold() != "lisa-config.json":
        raise LisaConfigError("Configuration file must be named lisa-config.json")
    config = load_object(config_path)
    configured_base = config.get("basePath")
    if not isinstance(configured_base, str) or not configured_base.strip():
        raise LisaConfigError("lisa-config.json must define a relative basePath")
    configured_path = Path(configured_base).expanduser()
    base = (
        configured_path.resolve()
        if configured_path.is_absolute()
        else (config_path.parent / configured_path).resolve()
    )
    if not base.is_dir():
        raise LisaConfigError(f"Configured basePath does not exist: {base}")

    output = base / "output"
    return LisaPaths(
        config=config,
        config_path=config_path,
        base=base,
        requirements=base / "requirements",
        output=output,
        analysis=output / "analysis",
        classification=output / "classification",
        design=output / "design",
        build=output / "build",
        evaluation=output / "evaluation",
        optimization=output / "optimization",
        artifacts=output / "artifacts",
        publication=output / "publication",
        eval_data=base / "evalData",
        checkpoint_root=base / ".lisa",
        workflow_pointer=base / ".lisa" / "current.json",
    )


def latest_file(
    directory: Path,
    pattern: str,
    label: str,
    name_pattern: str | None = None,
) -> Path:
    if not directory.is_dir():
        raise LisaConfigError(f"{label} directory does not exist: {directory}")
    candidates = [
        path
        for path in directory.glob(pattern)
        if path.is_file()
        and (name_pattern is None or re.fullmatch(name_pattern, path.name))
    ]
    if not candidates:
        raise LisaConfigError(f"No {label} found in {directory}")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name)).resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(resolve_lisa_config(Path(args.config)).public(), indent=2))
        return 0
    except (LisaConfigError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
