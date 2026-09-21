#!/usr/bin/env python3
"""Validate this skill's lifecycle stage against its packaged artifact contract.

The implementation is shared; see `lifecycle_artifacts.py` in the local-skills root.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT.parent))

from lifecycle_artifacts import (  # noqa: E402
    ArtifactError,
    load_object,
    validate_cli,
)
from lifecycle_artifacts import validate as _validate  # noqa: E402

__all__ = [
    "ArtifactError",
    "load_object",
    "validate",
    "validate_classification_reconciliation",
]


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
    return result


if __name__ == "__main__":
    raise SystemExit(validate_cli(SKILL_ROOT))
