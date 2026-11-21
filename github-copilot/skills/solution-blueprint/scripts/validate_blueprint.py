#!/usr/bin/env python3
"""Validate a generated Solution Blueprint HTML file.

Checks the embedded <script type="application/json" id="blueprint-data"> block against
resources/blueprint-data.schema.json, then runs semantic checks that a JSON Schema cannot
express. Uses the `jsonschema` package when installed (it is in LISA's requirements.txt);
otherwise falls back to a small built-in validator covering the keywords the schema uses.

Usage:
    python validate_blueprint.py <blueprint.html> [--json]
Exit code 0 = valid, 1 = invalid, 2 = file or data block unreadable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = SKILL_DIR / "resources" / "blueprint-data.schema.json"
DATA_BLOCK = re.compile(
    r'<script[^>]*\bid="blueprint-data"[^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL
)
ROUTES = [
    "DA + skills", "Pro-code DA with MCP", "Pro-code DA without MCP",
    "Standard harness", "GHCP harness", "Cowork plugins", "Scout",
]
SCORE_KEYS = [
    "fit", "implementationSpeed", "governance", "extensibility",
    "integrationReadiness", "userExperience", "operationalComplexity",
]


class BlueprintError(Exception):
    """Raised when the HTML or its data block cannot be read."""


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def extract_data(html: str) -> dict:
    blocks = DATA_BLOCK.findall(html)
    if len(blocks) != 1:
        raise BlueprintError(f"expected exactly one blueprint-data block, found {len(blocks)}")
    try:
        data = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        raise BlueprintError(f"blueprint-data is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BlueprintError("blueprint-data must be a JSON object")
    return data


# ---------------------------------------------------------------- schema validation
_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "integer": int, "number": (int, float), "null": type(None),
}


def _is_type(value, name: str) -> bool:
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES[name])


def _fallback_validate(value, schema: dict, root: dict, path: str, errors: list) -> None:
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            errors.append(f"{path}: unsupported $ref {ref}")
            return
        schema = root["$defs"][ref.split("/")[-1]]
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, t) for t in types):
            errors.append(f"{path}: expected {'/'.join(types)}")
            return
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} is not one of {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: must not be empty")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
    if _is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > maximum {schema['maximum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: allows at most {schema['maxItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                _fallback_validate(item, schema["items"], root, f"{path}[{i}]", errors)
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required '{key}'")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                _fallback_validate(item, props[key], root, f"{path}.{key}", errors)
            elif isinstance(schema.get("additionalProperties"), dict):
                _fallback_validate(item, schema["additionalProperties"], root, f"{path}.{key}", errors)


def schema_errors(data: dict, schema: dict) -> list[str]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        errors: list[str] = []
        _fallback_validate(data, schema, schema, "$", errors)
        return errors
    validator = jsonschema.Draft202012Validator(schema)
    return [
        f"$.{'.'.join(str(p) for p in err.absolute_path)}: {err.message}".replace("$.:", "$:")
        for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    ]


# ---------------------------------------------------------------- semantic checks
def semantic_errors(data: dict, html: str) -> list[str]:
    errors: list[str] = []
    routes = data.get("routes") or []
    names = [r.get("name") for r in routes if isinstance(r, dict)]
    missing = [r for r in ROUTES if r not in names]
    if missing:
        errors.append(f"routes: all 7 routes must be scored; missing {missing}")
    if len(set(names)) != len(names):
        errors.append("routes: a route is listed more than once")

    for route in routes:
        if not isinstance(route, dict):
            continue
        scores = route.get("scores") or {}
        if all(isinstance(scores.get(k), int) for k in SCORE_KEYS):
            expected = sum(scores[k] for k in SCORE_KEYS)
            if route.get("total") != expected:
                errors.append(
                    f"routes[{route.get('name')}]: total {route.get('total')} != sum of scores {expected}"
                )

    by_name = {r.get("name"): r for r in routes if isinstance(r, dict)}
    primary = data.get("recommendedRoute", "")
    primary_routes = [n for n in ROUTES if n and n in primary]
    for name in primary_routes:
        if by_name.get(name, {}).get("gate") == "Fail" and not _has_exception(data, name):
            errors.append(
                f"recommendedRoute: '{name}' has a failed gate and no recorded exception (gates beat scores)"
            )

    ids = {r.get("id") for r in data.get("requirements", []) if isinstance(r, dict)}
    for comp in data.get("components", []) or []:
        for rid in (comp.get("requirementIds") or []) if isinstance(comp, dict) else []:
            if rid not in ids:
                errors.append(f"components[{comp.get('name')}]: unknown requirement ID {rid}")

    if data.get("mode") == "standalone" and re.search(r"\bLISA\b", _visible_text(html)):
        errors.append("mode is standalone but the visible blueprint mentions LISA")
    if data.get("mode") == "lisa":
        for art in data.get("sourceArtifacts", []):
            if not art.get("sha256"):
                errors.append(f"sourceArtifacts[{art.get('path')}]: sha256 is required in LISA mode")
    return errors


def _has_exception(data: dict, route: str) -> bool:
    for gate in data.get("gates", []) or []:
        if isinstance(gate, dict) and gate.get("results", {}).get(route) == "Exception" and gate.get("owner"):
            return True
    return False


def _visible_text(html: str) -> str:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"<[^>]+>", " ", text)


# ---------------------------------------------------------------- entry points
def validate_html(html: str, schema: dict | None = None) -> list[str]:
    data = extract_data(html)
    return schema_errors(data, schema or load_schema()) + semantic_errors(data, html)


def validate_file(path: Path) -> list[str]:
    try:
        html = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BlueprintError(f"cannot read {path}: {exc}") from exc
    return validate_html(html)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("blueprint", type=Path, help="generated <slug>-blueprint.html")
    parser.add_argument("--json", action="store_true", help="print a JSON result")
    args = parser.parse_args(argv)
    try:
        errors = validate_file(args.blueprint)
    except BlueprintError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}) if args.json else f"ERROR: {exc}")
        return 2
    if args.json:
        print(json.dumps({"status": "valid" if not errors else "invalid", "errors": errors}, indent=2))
    elif errors:
        print(f"INVALID ({len(errors)} issue(s)):")
        for err in errors:
            print(f"  - {err}")
    else:
        print("VALID")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
