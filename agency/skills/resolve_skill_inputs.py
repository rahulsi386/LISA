#!/usr/bin/env python3
"""Resolve canonical config-relative input files for every local LISA skill."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lisa_path_resolver import (
    LisaConfigError,
    latest_file,
    load_object,
    resolve_lisa_config,
    resolve_relative,
)


def require_file(path: Path, label: str) -> str:
    if not path.is_file():
        raise LisaConfigError(f"Required {label} does not exist: {path}")
    return str(path.resolve())


def require_directory(path: Path, label: str) -> str:
    if not path.is_dir():
        raise LisaConfigError(f"Required {label} does not exist: {path}")
    return str(path.resolve())


def resolve_design(paths: Any) -> dict[str, str]:
    pointer_path = paths.design / "current-design.json"
    pointer = load_object(pointer_path)
    result = pointer.get("result")
    if not isinstance(result, dict):
        raise LisaConfigError("current-design.json is missing result")
    renders = result.get("renders")
    if not isinstance(renders, dict):
        raise LisaConfigError("current-design.json is missing result.renders")
    architecture_value = renders.get("solution_architecture_png")
    sequence_value = renders.get("sequence_png")
    if not isinstance(architecture_value, str) or not isinstance(sequence_value, str):
        raise LisaConfigError("current-design.json must contain relative PNG paths")
    architecture = resolve_relative(paths.base, architecture_value, "architecture path")
    sequence = resolve_relative(paths.base, sequence_value, "sequence path")
    return {
        "designPointer": require_file(pointer_path, "design pointer"),
        "solutionArchitecture": require_file(architecture, "solution architecture"),
        "sequenceDiagram": require_file(sequence, "sequence diagram"),
    }


def resolve_inputs(skill: str, config_path: Path) -> dict[str, Any]:
    paths = resolve_lisa_config(config_path)
    result: dict[str, Any] = {
        "skill": skill,
        "config": str(paths.config_path),
        "basePath": str(paths.base),
    }
    if skill == "requirement-analyzer":
        result["requirements"] = require_directory(paths.requirements, "requirements")
    elif skill == "complexity-classifier":
        result["analysis"] = str(
            latest_file(
                paths.analysis,
                "requirement-analysis_*.json",
                "analysis JSON",
                r"requirement-analysis_[0-9]{8}_[0-9]{6}(?:_[0-9]{3})?\.json",
            )
        )
    elif skill == "solution-designer":
        result["classification"] = str(
            latest_file(
                paths.classification,
                "complexity-classification_*.json",
                "classification JSON",
                r"complexity-classification_[0-9]{8}_[0-9]{6}(?:_[0-9]{3})?\.json",
            )
        )
    elif skill == "agent-builder":
        result["classification"] = str(
            latest_file(
                paths.classification,
                "complexity-classification_*.json",
                "classification JSON",
                r"complexity-classification_[0-9]{8}_[0-9]{6}(?:_[0-9]{3})?\.json",
            )
        )
        result.update(resolve_design(paths))
        result["copilotStudio"] = paths.config.get("copilotStudio", {})
    elif skill == "agent-evaluator":
        result["classification"] = str(
            latest_file(
                paths.classification,
                "complexity-classification_*.json",
                "classification JSON",
                r"complexity-classification_[0-9]{8}_[0-9]{6}(?:_[0-9]{3})?\.json",
            )
        )
        result["buildHandoff"] = require_file(
            paths.build / "agent-build-handoff.json", "build handoff"
        )
        result["evalData"] = require_directory(paths.eval_data, "evalData")
    elif skill == "agent-optimizer":
        result["evaluation"] = require_directory(paths.evaluation, "evaluation")
        for name in ("build-manifest.json", "agent-build-handoff.json"):
            candidate = paths.build / name
            if candidate.is_file():
                result[name.removesuffix(".json")] = str(candidate.resolve())
    elif skill == "artifact-generator":
        for name in (
            "analysis",
            "classification",
            "design",
            "build",
            "evaluation",
            "optimization",
        ):
            result[name] = require_directory(getattr(paths, name), name)
    elif skill == "artifact-publisher":
        if paths.workflow_pointer.is_file():
            result["workflowPointer"] = str(paths.workflow_pointer.resolve())
        result["runFolder"] = require_directory(paths.output, "output")
    elif skill == "postpublish-cleanup":
        result["output"] = require_directory(paths.output, "output")
    else:
        raise LisaConfigError(f"Unknown local skill: {skill}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill", required=True)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(resolve_inputs(args.skill, Path(args.config)), indent=2))
        return 0
    except (LisaConfigError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
