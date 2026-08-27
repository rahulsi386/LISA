#!/usr/bin/env python3
"""Synchronize generated local skill metadata from canonical SKILL.md files."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
METADATA_PATH = ROOT / "skills-metadata.json"


class MetadataError(RuntimeError):
    pass


def scalar(value: str) -> str:
    value = value.strip()
    if value.startswith(('"', "'")):
        try:
            return json.loads(value) if value.startswith('"') else value[1:-1]
        except (json.JSONDecodeError, IndexError) as exc:
            raise MetadataError(f"Invalid frontmatter scalar: {value}") from exc
    return value


def read_skill(path: Path) -> tuple[str, str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.fullmatch(r"---\r?\n(.*?)\r?\n---\r?\n(.*)", text, re.DOTALL)
    if not match:
        raise MetadataError(f"Invalid SKILL.md frontmatter: {path}")
    frontmatter, instructions = match.groups()
    fields: dict[str, str] = {}
    for line in frontmatter.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() in {"name", "description"}:
            fields[key.strip()] = scalar(value)
    if not fields.get("name") or not fields.get("description"):
        raise MetadataError(f"Missing name or description: {path}")
    return fields["name"], fields["description"], instructions.rstrip() + "\n"


def atomic_write(path: Path, value: list[dict[str, Any]]) -> None:
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def synchronize() -> dict[str, Any]:
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    if not isinstance(metadata, list):
        raise MetadataError("skills-metadata.json must contain an array")
    entries = {
        item.get("name"): item
        for item in metadata
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    updated: list[str] = []
    for skill_path in sorted(ROOT.glob("*/SKILL.md")):
        name, description, instructions = read_skill(skill_path)
        entry = entries.get(name)
        if entry is None:
            raise MetadataError(f"No metadata registry entry exists for {name}")
        entry["description"] = description
        entry["instructions"] = instructions
        updated.append(name)
    atomic_write(METADATA_PATH, metadata)
    return {"status": "synchronized", "count": len(updated), "skills": updated}


if __name__ == "__main__":
    print(json.dumps(synchronize(), indent=2))