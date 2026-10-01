#!/usr/bin/env python3
"""Validate this skill's lifecycle stage against its packaged artifact contract.

The implementation is shared; see `lifecycle_artifacts.py` in the local-skills root.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT.parent))

from lifecycle_artifacts import (  # noqa: E402
    ArtifactError,
    load_object,
)
from lifecycle_artifacts import validate as _validate  # noqa: E402

__all__ = [
    "ArtifactError",
    "load_object",
    "main",
    "validate",
    "validate_automation_ledger",
    "validate_classification_reconciliation",
]

# Roadmap platforms LISA designs for but does not build yet.
FUTURE_PLATFORM = re.compile(r"\b(foundry|agent framework)\b", re.IGNORECASE)
COPILOT_STUDIO = "Microsoft Copilot Studio"
ATK_TOOL = re.compile(r"(^|[\s`])atk(\s|$)")


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value)[:3])


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_automation_ledger(root: Path, handoff: dict) -> None:
    """Enforce programmatic-first construction (PAC first for Copilot Studio)."""
    try:
        _check_automation_ledger(root, handoff)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ArtifactError(
            f"agent-build-handoff.json has a missing or malformed automation record: {exc!r}"
        ) from exc


def _check_automation_ledger(root: Path, handoff: dict) -> None:
    ledger = handoff["automationLedger"]
    toolchain = handoff["automationToolchain"]
    problems: list[str] = []

    covered = {entry["componentId"] for entry in ledger}
    unlogged = sorted(
        item["componentId"]
        for item in handoff["componentDispositions"]
        if item["actualDisposition"] in {"built", "configured"}
        and item["componentId"] not in covered
    )
    if unlogged:
        problems.append(f"built/configured components without automationLedger entries: {unlogged}")

    for index, entry in enumerate(ledger):
        label = f"automationLedger[{index}] ({entry['componentId']}: {entry['operation']})"
        method = entry["method"]
        pac_attempted = any(
            attempt["method"] == "pac-cli" for attempt in entry["programmaticAttempts"]
        )
        if entry["platform"] == COPILOT_STUDIO and method in {"programmatic", "browser"} and not pac_attempted:
            problems.append(f"{label} uses {method} without a recorded PAC CLI attempt")
        if method in {"browser", "manual"} and not _has_text(entry["fallbackJustification"]):
            problems.append(f"{label} uses {method} without fallbackJustification")
        if (
            entry["platform"] == COPILOT_STUDIO
            and method == "browser"
            and not _has_text(entry["reconciliation"])
        ):
            problems.append(f"{label} browser step lacks PAC pull/clone reconciliation")
        if ATK_TOOL.search(entry["tool"]) and not _has_text(toolchain["atkVersion"]):
            problems.append(f"{label} uses atk without automationToolchain.atkVersion")

    if any(entry["platform"] == COPILOT_STUDIO for entry in ledger):
        installed, latest = toolchain["pacVersion"], toolchain["pacLatestVersion"]
        if not (_has_text(installed) and _has_text(latest) and _has_text(toolchain["pacLatestSource"])):
            problems.append("Copilot Studio builds must record pacVersion, pacLatestVersion, and pacLatestSource")
        elif _version(installed) < _version(latest):
            problems.append(f"PAC CLI {installed} is older than the latest {latest}")

    for package in handoff["artifacts"].get("coworkPackages", []):
        path = root / package["relativePath"]
        if not path.is_file():
            problems.append(f"Cowork package is missing: {package['relativePath']}")
            continue
        if path.stat().st_size != package["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != package["sha256"]:
            problems.append(f"Cowork package hash or size differs: {package['relativePath']}")

    if problems:
        raise ArtifactError("Automation precedence violations: " + "; ".join(problems))


def validate_future_platform_contracts(classification: dict, handoff: dict) -> None:
    future_ids = {
        item["id"]
        for item in classification.get("solution_topology", {}).get("components", [])
        if FUTURE_PLATFORM.search(
            f"{item.get('product_service', '')} {item.get('hosting_runtime', '')}"
        )
    }
    if not future_ids:
        return
    built = sorted(
        item["componentId"]
        for item in handoff["componentDispositions"]
        if item["componentId"] in future_ids
        and item["actualDisposition"] in {"built", "configured"}
    )
    if built:
        raise ArtifactError(
            f"Roadmap-platform components cannot be built by LISA yet: {built}"
        )
    contracted = {
        item["componentId"] for item in handoff.get("futurePlatformContracts", [])
    }
    missing = sorted(future_ids - contracted)
    if missing:
        raise ArtifactError(
            f"Roadmap-platform components need futurePlatformContracts entries: {missing}"
        )


def validate_classification_reconciliation(root: Path) -> None:
    handoff = load_object(root / "agent-build-handoff.json")
    relative_classification = Path(
        handoff["inputs"]["classificationRelativePath"]
    )
    classification_path = next(
        (
            candidate
            for parent in [root, *root.parents]
            if (candidate := parent / relative_classification).is_file()
        ),
        None,
    )
    if classification_path is None:
        return

    classification = load_object(classification_path)
    expected_component_ids = {
        item["id"]
        for item in classification.get("solution_topology", {}).get(
            "components", []
        )
    }
    disposition_ids = [
        item["componentId"] for item in handoff["componentDispositions"]
    ]
    if len(disposition_ids) != len(set(disposition_ids)):
        raise ArtifactError("Builder component dispositions contain duplicate IDs")
    if set(disposition_ids) != expected_component_ids:
        raise ArtifactError(
            "Builder handoff must reconcile every classified topology component; "
            f"missing={sorted(expected_component_ids - set(disposition_ids))}, "
            f"extra={sorted(set(disposition_ids) - expected_component_ids)}"
        )
    validate_future_platform_contracts(classification, handoff)

    planned = classification.get("coverage", {})
    plan = handoff["classificationPlan"]
    actual = handoff["actualCoverage"]
    comparisons = {
        "classificationPlan.nativeBuildPercent": (
            plan["nativeBuildPercent"],
            planned.get("native_build_percent"),
        ),
        "classificationPlan.pocDemonstrationPercent": (
            plan["pocDemonstrationPercent"],
            planned.get("poc_demonstration_percent"),
        ),
        "actualCoverage.plannedNativePercent": (
            actual["plannedNativePercent"],
            planned.get("native_build_percent"),
        ),
        "actualCoverage.plannedPocPercent": (
            actual["plannedPocPercent"],
            planned.get("poc_demonstration_percent"),
        ),
    }
    mismatches = [
        name
        for name, (observed, expected) in comparisons.items()
        if expected is None or observed != expected
    ]
    if mismatches:
        raise ArtifactError(
            "Builder planned coverage differs from the classifier: "
            + ", ".join(mismatches)
        )
    expected_capabilities = len(
        classification.get("delivery_assessment", {}).get("capabilities", [])
    )
    if plan["capabilityCount"] != expected_capabilities:
        raise ArtifactError(
            "Builder capability count differs from the classifier"
        )


def validate(root: Path) -> dict:
    result = _validate(root, SKILL_ROOT)
    validate_classification_reconciliation(root)
    validate_automation_ledger(root, load_object(root / "agent-build-handoff.json"))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the agent-builder artifact set")
    parser.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    try:
        result = validate(Path(args.root))
    except (ArtifactError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
