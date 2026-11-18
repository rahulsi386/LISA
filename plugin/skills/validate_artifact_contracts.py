#!/usr/bin/env python3
"""Validate local-skill artifact contracts against the shared contract schema."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = ROOT / "artifact-contract.schema.json"


class ContractError(RuntimeError):
    pass


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"Expected a JSON object in {path}")
    return value


def validate_contract(skill_root: Path) -> dict[str, Any]:
    contract_path = skill_root / "resources" / "artifact-contract.json"
    contract = load_object(contract_path)
    try:
        import jsonschema

        jsonschema.Draft202012Validator(load_object(SCHEMA_PATH)).validate(contract)
    except ImportError as exc:
        raise ContractError("jsonschema is required to validate artifact contracts") from exc
    except jsonschema.ValidationError as exc:
        location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
        raise ContractError(
            f"{skill_root.name} contract error at {location}: {exc.message}"
        ) from exc

    if contract["skill"] != skill_root.name:
        raise ContractError(
            f"Contract skill {contract['skill']!r} does not match {skill_root.name!r}"
        )
    root_folder = contract["rootFolder"]
    if root_folder is not None and root_folder != root_folder.lower():
        raise ContractError(f"Artifact root must be lowercase: {root_folder}")

    seen: set[str] = set()
    resources = skill_root / "resources"
    for item in contract["files"]:
        relative = item["relativePath"].replace("\\", "/")
        if relative in seen:
            raise ContractError(f"Duplicate artifact path in {skill_root.name}: {relative}")
        seen.add(relative)
        schema = item.get("schema")
        if schema and not (resources / schema).is_file():
            raise ContractError(
                f"Referenced schema does not exist for {skill_root.name}: {schema}"
            )
    result_schema = contract.get("resultSchema")
    if result_schema and not (resources / result_schema).is_file():
        raise ContractError(
            f"Result schema does not exist for {skill_root.name}: {result_schema}"
        )
    for name, pattern in contract["patterns"].items():
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ContractError(
                f"Invalid naming pattern {name!r} for {skill_root.name}: {exc}"
            ) from exc
    if contract.get("runIdPattern"):
        try:
            re.compile(contract["runIdPattern"])
        except re.error as exc:
            raise ContractError(
                f"Invalid run ID pattern for {skill_root.name}: {exc}"
            ) from exc
    return contract


def canonical_stage_root(output_root: Path, root_folder: str) -> Path:
    """Create a lowercase stage root, safely migrating a case-only legacy name."""
    if root_folder != root_folder.lower() or not re.fullmatch(r"[a-z][a-z0-9-]*", root_folder):
        raise ContractError(f"Stage root must be lowercase kebab-case: {root_folder}")
    output_root.mkdir(parents=True, exist_ok=True)
    matches = [
        path
        for path in output_root.iterdir()
        if path.is_dir() and path.name.casefold() == root_folder.casefold()
    ]
    canonical = output_root / root_folder
    exact = [path for path in matches if path.name == root_folder]
    legacy = [path for path in matches if path.name != root_folder]
    if exact and legacy:
        raise ContractError(
            f"Conflicting canonical and legacy stage folders exist: {exact[0]}, {legacy[0]}"
        )
    if len(legacy) > 1:
        raise ContractError(f"Multiple legacy stage folders conflict with {canonical}")
    if legacy:
        temporary = output_root / f".{root_folder}-case-migration-{os.getpid()}"
        if temporary.exists():
            raise ContractError(f"Case-migration path already exists: {temporary}")
        legacy[0].rename(temporary)
        try:
            temporary.rename(canonical)
        except BaseException:
            temporary.rename(legacy[0])
            raise
    canonical.mkdir(parents=True, exist_ok=True)
    if canonical.resolve().parent != output_root.resolve():
        raise ContractError(f"Stage root escapes output root: {canonical}")
    return canonical.resolve()


def validate_all(skill: str | None = None) -> list[dict[str, Any]]:
    roots = [ROOT / skill] if skill else [
        path
        for path in sorted(ROOT.iterdir())
        if path.is_dir() and (path / "SKILL.md").is_file()
    ]
    return [validate_contract(path) for path in roots]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skill")
    args = parser.parse_args()
    try:
        contracts = validate_all(args.skill)
        print(
            json.dumps(
                {
                    "status": "passed",
                    "validated": len(contracts),
                    "skills": [item["skill"] for item in contracts],
                },
                indent=2,
            )
        )
        return 0
    except (ContractError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
