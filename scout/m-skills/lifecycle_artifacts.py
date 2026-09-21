#!/usr/bin/env python3
"""Shared lifecycle-artifact contract engine for the build, evaluation, and optimization stages.

`agent-builder`, `agent-evaluator`, and `agent-optimizer` publish and validate structurally
identical artifact sets that differ only by their packaged `artifact-contract.json`. This module
holds that single implementation; each skill keeps a thin entry point under its own scripts
folder so the documented per-skill invocations continue to work.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_artifact_contracts import validate_contract

STATUS_CHOICES = (
    "prepared",
    "in-progress",
    "complete",
    "pass",
    "fail",
    "blocked",
    "rolled-back",
)


class ArtifactError(RuntimeError):
    pass


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ArtifactError(f"Expected an object in {path}")
    return value


def validate_schema(value: dict[str, Any], schema_path: Path, label: str) -> None:
    try:
        import jsonschema

    except ImportError as exc:
        raise ArtifactError("Install jsonschema to validate lifecycle artifacts") from exc
    validator = jsonschema.Draft202012Validator(
        load_object(schema_path),
        format_checker=jsonschema.FormatChecker(),
    )
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path))
    if errors:
        error = errors[0]
        location = ".".join(str(item) for item in error.absolute_path) or "<root>"
        raise ArtifactError(f"{label} schema error at {location}: {error.message}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_path(root: Path, relative: str) -> Path:
    normalized = relative.replace("\\", "/")
    value = Path(normalized)
    if value.is_absolute() or ".." in value.parts or re.match(r"^[A-Za-z]:", relative):
        raise ArtifactError(f"Unsafe artifact path: {relative}")
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ArtifactError(f"Artifact escapes {root}: {relative}") from exc
    return path


def inventory(root: Path, manifest_name: str) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if relative == manifest_name:
            continue
        if path.is_symlink():
            raise ArtifactError(f"Symbolic links are not allowed: {relative}")
        result[relative] = path
    return result


def artifact_name(relative: str) -> str:
    path = Path(relative)
    if path.suffix:
        stem = path.as_posix()[: -len(path.suffix)]
        extension = path.suffix.lower()
    else:
        stem = path.as_posix()
        extension = ""
    stem = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")
    if not stem:
        raise ArtifactError(f"Cannot derive artifact name from {relative}")
    return f"{stem}{extension}"


def artifact_kind(path: Path) -> str:
    if path.is_dir():
        return "directory"
    return {
        ".json": "json",
        ".md": "markdown",
        ".csv": "csv",
        ".png": "image",
        ".jpg": "image",
        ".jpeg": "image",
        ".zip": "package",
    }.get(path.suffix.lower(), "source")


def schema_for(contract: dict[str, Any], relative: str) -> str | None:
    for item in contract["files"]:
        if item["relativePath"] == relative:
            return item["schema"]
    for rule in contract.get("artifactRules", []):
        if re.fullmatch(rule["pattern"], relative):
            return rule.get("schema")
    return None


def required_for(
    contract: dict[str, Any], relative: str, dynamic_required: set[str]
) -> bool:
    fixed = {
        item["relativePath"]
        for item in contract["files"] + contract["directories"]
        if item["required"] and item["relativePath"] != contract["manifest"]
    }
    return relative in fixed or relative in dynamic_required


def check_forbidden(contract: dict[str, Any], paths: set[str]) -> None:
    for relative in paths:
        for pattern in contract.get("forbiddenPathPatterns", []):
            if re.search(pattern, relative):
                raise ArtifactError(f"Forbidden artifact path: {relative}")


def validate_stage(
    root: Path,
    contract: dict[str, Any],
    manifest: dict[str, Any],
    resources: Path,
) -> set[str]:
    stage = contract["stage"]
    run_id = manifest["runId"]
    dynamic_required: set[str] = set()

    if stage == "build":
        handoff = load_object(root / "agent-build-handoff.json")
        live = load_object(root / "agent-live-state.json")
        if handoff["runId"] != run_id or live["runId"] != run_id:
            raise ArtifactError("Build artifact run IDs do not match the manifest")
        if handoff["instructions"]["sha256"] != live["instructionsSha256"]:
            raise ArtifactError("Instruction hashes differ between build artifacts")
        instruction_path = safe_path(root, handoff["instructions"]["relativePath"])
        if not instruction_path.is_file() or sha256(instruction_path) != live["instructionsSha256"]:
            raise ArtifactError("Persisted instruction artifact hash does not match live state")
        for package in handoff["artifacts"]["packages"]:
            package_path = safe_path(root, package["relativePath"])
            if (
                not package_path.is_file()
                or sha256(package_path) != package["sha256"]
                or package_path.stat().st_size != package["bytes"]
            ):
                raise ArtifactError(
                    f"Build handoff package mismatch: {package['relativePath']}"
                )
        if handoff["artifacts"]["packages"] != live["packages"]:
            raise ArtifactError("Build handoff and live-state package records differ")
        for path in (root / "packages").iterdir():
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                if not re.fullmatch(contract["patterns"]["package"], relative):
                    raise ArtifactError(f"Invalid package name: {relative}")
        for path in (root / "evidence").iterdir():
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                if not re.fullmatch(contract["patterns"]["evidence"], relative):
                    raise ArtifactError(f"Invalid evidence name: {relative}")
        primary_agent = handoff["agent"]

    elif stage == "evaluation":
        observations = load_object(root / "evaluation-observations.json")
        dataset = load_object(root / "evaluation-dataset.json")
        baseline = load_object(root / "regression-baseline.json")
        if observations["runId"] != run_id:
            raise ArtifactError("Evaluation observation run ID does not match the manifest")
        if (
            baseline["sourceRunId"] != run_id
            and baseline["sourceRunId"] not in manifest["sourceRuns"]
        ):
            raise ArtifactError(
                "Regression baseline sourceRunId is absent from manifest provenance"
            )
        if dataset["testSetId"] != observations["testSetId"]:
            raise ArtifactError("Dataset and observations use different test-set IDs")
        dataset_ids = [item["id"] for item in dataset["testCases"]]
        result_ids = [item["testCaseId"] for item in observations["results"]]
        if (
            len(dataset_ids) != len(set(dataset_ids))
            or len(result_ids) != len(set(result_ids))
            or set(dataset_ids) != set(result_ids)
        ):
            raise ArtifactError("Evaluation results do not cover the dataset exactly once")
        counts = observations["summary"]
        if counts["total"] != len(observations["results"]):
            raise ArtifactError("Evaluation result count does not match summary.total")
        actual_counts = {
            "passed": sum(item["status"] == "PASS" for item in observations["results"]),
            "failed": sum(item["status"] == "FAIL" for item in observations["results"]),
            "blocked": sum(item["status"] == "BLOCKED" for item in observations["results"]),
            "notRun": sum(item["status"] == "NOT_RUN" for item in observations["results"]),
        }
        if any(counts[key] != value for key, value in actual_counts.items()):
            raise ArtifactError("Evaluation status counts do not match the results")
        expected_status = {
            "PASS": "pass",
            "FAIL": "fail",
            "BLOCKED": "blocked",
            "NOT_RUN": "blocked",
        }[observations["optimizerHandoff"]["evaluationDecision"]]
        if manifest["status"] != expected_status:
            raise ArtifactError("Evaluation manifest status disagrees with gate decision")
        for result in observations["results"]:
            for relative in result["playwrightObservations"]["evidence"]:
                if not safe_path(root, relative).is_file():
                    raise ArtifactError(f"Referenced evidence is missing: {relative}")
        for path in (root / "evidence").iterdir():
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                if not re.fullmatch(contract["patterns"]["evidence"], relative):
                    raise ArtifactError(f"Invalid evidence name: {relative}")
        if not any(value.startswith("BLD-") for value in manifest["sourceRuns"]):
            raise ArtifactError("Evaluation manifest must reference its source build run")
        primary_agent = observations["agent"]

    else:
        plan = load_object(root / "optimization-plan.json")
        change_log = load_object(root / "optimization-change-log.json")
        if plan["runId"] != run_id:
            raise ArtifactError("Optimization plan run ID does not match the manifest")
        if change_log["runId"] != run_id:
            raise ArtifactError("Optimization change-log run ID does not match the manifest")
        evaluation_run = plan["sourceEvaluation"]["runId"]
        if evaluation_run not in manifest["sourceRuns"]:
            raise ArtifactError("Optimization manifest omits its source evaluation run")
        rounds = plan["rounds"]
        expected_ids = [f"round-{index:03d}" for index in range(1, len(rounds) + 1)]
        actual_ids = [item.get("roundId") for item in rounds]
        if actual_ids != expected_ids:
            raise ArtifactError("Optimization rounds must be ordered, contiguous, and unique")
        if [item.get("roundId") for item in change_log["rounds"]] != expected_ids:
            raise ArtifactError("Optimization change log does not cover every round in order")
        round_root = root / "rounds"
        directory_ids = sorted(path.name for path in round_root.iterdir() if path.is_dir())
        if directory_ids != expected_ids:
            raise ArtifactError("Round directories do not match optimization-plan.json")
        if any(not path.is_dir() for path in round_root.iterdir()):
            raise ArtifactError("The rounds folder may contain only round directories")

        for round_item in rounds:
            round_id = round_item["roundId"]
            if round_item["roundNumber"] != int(round_id[-3:]):
                raise ArtifactError(f"Round number does not match {round_id}")
            directory = round_root / round_id
            round_report = f"rounds/{round_id}/round-report.md"
            if not (root / round_report).is_file():
                raise ArtifactError(f"Missing round report: {round_report}")
            dynamic_required.add(round_report)
            dynamic_required.add(f"rounds/{round_id}")

            status = round_item["status"]
            applied = {
                "applied-awaiting-retest",
                "accepted",
                "rejected-and-rolled-back",
            }
            states: list[tuple[str, str, str]] = []
            if status in applied:
                states.extend(
                    [
                        ("before-state-manifest.json", "before", "before"),
                        ("after-state-manifest.json", "after", "after"),
                    ]
                )
            if status == "rejected-and-rolled-back":
                states.append(
                    ("rollback-state-manifest.json", "rolled-back", "rollback")
                )
            for filename, state, snapshot_name in states:
                relative = f"rounds/{round_id}/{filename}"
                snapshot = f"rounds/{round_id}/snapshots/{snapshot_name}"
                if not (root / relative).is_file():
                    raise ArtifactError(f"Missing state manifest: {relative}")
                if not (root / snapshot).is_dir():
                    raise ArtifactError(f"Missing state snapshot: {snapshot}")
                state_value = load_object(root / relative)
                validate_schema(
                    state_value,
                    resources / "optimization-state-manifest.schema.json",
                    relative,
                )
                if (
                    state_value["runId"] != run_id
                    or state_value["roundId"] != round_id
                    or state_value["state"] != state
                    or state_value["snapshotRelativePath"] != snapshot
                ):
                    raise ArtifactError(f"State identity mismatch: {relative}")
                package = state_value["package"]
                if package is not None:
                    package_path = safe_path(root, package["relativePath"])
                    if (
                        not package_path.is_file()
                        or sha256(package_path) != package["sha256"]
                        or package_path.stat().st_size != package["bytes"]
                    ):
                        raise ArtifactError(
                            f"Optimization package mismatch: {package['relativePath']}"
                        )
                dynamic_required.update({relative, snapshot})
        primary_agent = plan["agent"]

    manifest_agent = manifest["agent"]
    source_agent_id = primary_agent.get("agentId") or primary_agent.get("botId")
    for key, expected in {
        "name": primary_agent.get("name"),
        "agentId": source_agent_id,
        "agenticPlatform": primary_agent.get("agenticPlatform"),
        "harness": primary_agent.get("harness"),
        "environmentId": primary_agent.get("environmentId"),
    }.items():
        if manifest_agent.get(key) != expected:
            raise ArtifactError(f"Manifest agent.{key} does not match stage artifacts")
    return dynamic_required


def validate(root: Path, skill_root: Path) -> dict[str, Any]:
    resources = skill_root / "resources"
    contract = load_object(resources / "artifact-contract.json")
    validate_contract(skill_root)
    root = root.resolve()
    if root.name != contract["rootFolder"] or not root.is_dir():
        raise ArtifactError(f"Expected existing {contract['rootFolder']} folder: {root}")

    for item in contract["files"]:
        path = safe_path(root, item["relativePath"])
        if item["required"] and not path.is_file():
            raise ArtifactError(f"Missing required file: {item['relativePath']}")
        if path.is_file() and item["schema"]:
            validate_schema(
                load_object(path),
                resources / item["schema"],
                item["relativePath"],
            )
    for item in contract["directories"]:
        path = safe_path(root, item["relativePath"])
        if item["required"] and not path.is_dir():
            raise ArtifactError(f"Missing required directory: {item['relativePath']}")

    manifest = load_object(root / contract["manifest"])
    validate_schema(
        manifest,
        resources / "lifecycle-artifact-manifest.schema.json",
        contract["manifest"],
    )
    if (
        manifest["stage"] != contract["stage"]
        or manifest["rootFolder"] != contract["rootFolder"]
    ):
        raise ArtifactError("Manifest stage/root does not match artifact contract")
    if not re.fullmatch(contract["runIdPattern"], manifest["runId"]):
        raise ArtifactError(f"Invalid {contract['stage']} run ID")
    if manifest["status"] not in contract["allowedStatuses"]:
        raise ArtifactError(
            f"Invalid {contract['stage']} status: {manifest['status']}"
        )

    dynamic_required = validate_stage(root, contract, manifest, resources)
    actual = inventory(root, contract["manifest"])
    check_forbidden(contract, set(actual))

    records: dict[str, dict[str, Any]] = {}
    names: set[str] = set()
    for item in manifest["artifacts"]:
        relative = item["relativePath"].replace("\\", "/")
        safe_path(root, relative)
        if relative == contract["manifest"]:
            raise ArtifactError("A manifest cannot inventory or hash itself")
        if item["name"] in names or relative in records:
            raise ArtifactError("Manifest contains duplicate artifact identities")
        names.add(item["name"])
        records[relative] = item

    if set(records) != set(actual):
        missing = sorted(set(actual) - set(records))
        stale = sorted(set(records) - set(actual))
        raise ArtifactError(
            f"Manifest inventory mismatch; unlisted={missing}, missing={stale}"
        )

    for relative, path in actual.items():
        item = records[relative]
        expected_required = required_for(contract, relative, dynamic_required)
        expected_schema = schema_for(contract, relative)
        if item["name"] != artifact_name(relative):
            raise ArtifactError(f"Non-standard artifact name: {item['name']}")
        if item["kind"] != artifact_kind(path):
            raise ArtifactError(f"Incorrect artifact kind: {relative}")
        if item["required"] != expected_required:
            raise ArtifactError(f"Incorrect required flag: {relative}")
        if item["schema"] != expected_schema:
            raise ArtifactError(f"Incorrect schema reference: {relative}")
        if path.is_dir():
            if item["sha256"] is not None or item["bytes"] is not None:
                raise ArtifactError(f"Directory hash/size must be null: {relative}")
        elif item["sha256"] != sha256(path) or item["bytes"] != path.stat().st_size:
            raise ArtifactError(f"Hash or size mismatch: {relative}")

    return {
        "status": "passed",
        "stage": contract["stage"],
        "runId": manifest["runId"],
        "root": str(root),
        "artifactCount": len(manifest["artifacts"]),
    }


def primary_metadata(
    root: Path, contract: dict[str, Any]
) -> tuple[str, dict[str, Any], set[str]]:
    stage = contract["stage"]
    if stage == "build":
        value = load_object(root / "agent-build-handoff.json")
        return value["runId"], value["agent"], set()
    if stage == "evaluation":
        value = load_object(root / "evaluation-observations.json")
        return value["runId"], value["agent"], set()
    value = load_object(root / "optimization-plan.json")
    return value["runId"], value["agent"], {value["sourceEvaluation"]["runId"]}


def dynamic_required(root: Path, contract: dict[str, Any]) -> set[str]:
    if contract["stage"] != "optimization":
        return set()
    plan = load_object(root / "optimization-plan.json")
    required: set[str] = set()
    for item in plan["rounds"]:
        round_id = item["roundId"]
        required.update(
            {
                f"rounds/{round_id}",
                f"rounds/{round_id}/round-report.md",
            }
        )
        if item["status"] in {
            "applied-awaiting-retest",
            "accepted",
            "rejected-and-rolled-back",
        }:
            required.update(
                {
                    f"rounds/{round_id}/before-state-manifest.json",
                    f"rounds/{round_id}/after-state-manifest.json",
                    f"rounds/{round_id}/snapshots/before",
                    f"rounds/{round_id}/snapshots/after",
                }
            )
        if item["status"] == "rejected-and-rolled-back":
            required.update(
                {
                    f"rounds/{round_id}/rollback-state-manifest.json",
                    f"rounds/{round_id}/snapshots/rollback",
                }
            )
    return required


def normalized_agent(source: dict[str, Any]) -> dict[str, Any]:
    agent_id = source.get("agentId") or source.get("botId")
    result: dict[str, Any] = {
        "name": source.get("name"),
        "agentId": agent_id,
        "harness": source.get("harness"),
        "environmentId": source.get("environmentId"),
    }
    if source.get("agenticPlatform") is not None:
        result["agenticPlatform"] = source["agenticPlatform"]
    if source.get("schemaName") is not None:
        result["schemaName"] = source["schemaName"]
    if source.get("environmentUrl") is not None:
        result["environmentUrl"] = source["environmentUrl"]
    return result


def build_manifest(
    root: Path,
    contract: dict[str, Any],
    status: str,
    summary: str,
    source_runs: list[str],
) -> dict[str, Any]:
    run_id, source_agent, inferred_sources = primary_metadata(root, contract)
    if not re.fullmatch(contract["runIdPattern"], run_id):
        raise ArtifactError(f"Invalid {contract['stage']} run ID: {run_id}")
    sources = sorted(set(source_runs) | inferred_sources)
    if contract["stage"] == "evaluation" and not any(
        item.startswith("BLD-") for item in sources
    ):
        raise ArtifactError("Evaluation publication requires --source-run BLD-...")

    dynamic = dynamic_required(root, contract)
    paths = inventory(root, contract["manifest"])
    artifacts: list[dict[str, Any]] = []
    names: set[str] = set()
    for relative in sorted(paths):
        path = paths[relative]
        name = artifact_name(relative)
        if name in names:
            raise ArtifactError(f"Generated artifact name is not unique: {name}")
        names.add(name)
        is_directory = path.is_dir()
        artifacts.append(
            {
                "name": name,
                "relativePath": relative,
                "kind": artifact_kind(path),
                "required": required_for(contract, relative, dynamic),
                "sha256": None if is_directory else sha256(path),
                "bytes": None if is_directory else path.stat().st_size,
                "schema": schema_for(contract, relative),
            }
        )
    return {
        "schemaVersion": "1.0",
        "stage": contract["stage"],
        "runId": run_id,
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "rootFolder": contract["rootFolder"],
        "agent": normalized_agent(source_agent),
        "sourceRuns": sources,
        "artifacts": artifacts,
        "summary": summary,
    }


def publish(
    root: Path,
    skill_root: Path,
    status: str,
    summary: str,
    source_runs: list[str],
) -> dict[str, Any]:
    root = root.resolve()
    contract = load_object(skill_root / "resources" / "artifact-contract.json")
    if root.name != contract["rootFolder"] or not root.is_dir():
        raise ArtifactError(f"Expected existing {contract['rootFolder']} folder: {root}")
    if status not in contract["allowedStatuses"]:
        raise ArtifactError(f"Invalid {contract['stage']} status: {status}")
    manifest = root / contract["manifest"]
    previous = manifest.read_bytes() if manifest.is_file() else None
    candidate = build_manifest(root, contract, status, summary, source_runs)
    temporary = manifest.with_name(f".{manifest.name}.tmp")
    temporary.write_text(
        json.dumps(candidate, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, manifest)
    try:
        return validate(root, skill_root)
    except Exception:
        if previous is None:
            manifest.unlink(missing_ok=True)
        else:
            temporary.write_bytes(previous)
            os.replace(temporary, manifest)
        raise


def validate_cli(skill_root: Path) -> int:
    parser = argparse.ArgumentParser(description="Validate a lifecycle stage artifact set")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(validate(Path(args.root), skill_root), indent=2))
        return 0
    except ArtifactError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


def publish_cli(skill_root: Path) -> int:
    parser = argparse.ArgumentParser(description="Publish a lifecycle stage manifest")
    parser.add_argument("--root", required=True)
    parser.add_argument("--status", required=True, choices=list(STATUS_CHOICES))
    parser.add_argument("--summary", required=True)
    parser.add_argument("--source-run", action="append", default=[])
    args = parser.parse_args()
    try:
        result = publish(
            Path(args.root),
            skill_root,
            args.status,
            args.summary,
            args.source_run,
        )
        print(json.dumps(result, indent=2))
        return 0
    except (ArtifactError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
