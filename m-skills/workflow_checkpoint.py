#!/usr/bin/env python3
"""Persist constant-time, crash-safe LISA workflow and stage checkpoints."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from lisa_path_resolver import LisaConfigError, resolve_lisa_config


SCHEMA_VERSION = "1.0"
STAGES = (
    "analysis",
    "classification",
    "design",
    "build",
    "evaluation",
    "optimization",
    "artifacts",
    "publication",
    "cleanup",
)
ACTIVE_STATUSES = {"RUNNING", "WAITING", "RECONCILING"}
TERMINAL_STATUSES = {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"}
CHECKPOINT_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES
LOCK_TIMEOUT_SECONDS = 10.0
STALE_LOCK_SECONDS = 120.0


class CheckpointError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: dict[str, Any]) -> str:
    payload = deepcopy(value)
    payload.pop("integritySha256", None)
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def with_integrity(value: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(value)
    result["integritySha256"] = canonical_hash(result)
    return result


def validate_integrity(value: dict[str, Any], label: str) -> None:
    expected = value.get("integritySha256")
    if not isinstance(expected, str) or expected != canonical_hash(value):
        raise CheckpointError(f"Invalid integrity hash for {label}")


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CheckpointError(f"Cannot read checkpoint {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CheckpointError(f"Expected an object in {path}")
    return value


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def state_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / "checkpoint.lock"
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(descriptor, f"{os.getpid()} {now_iso()}\n".encode("ascii"))
        except FileExistsError:
            try:
                stale = time.time() - lock_path.stat().st_mtime > STALE_LOCK_SECONDS
            except FileNotFoundError:
                continue
            if stale:
                lock_path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise CheckpointError(f"Timed out waiting for {lock_path}")
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def checkpoint_root(config_path: Path) -> tuple[Path, Path, str]:
    paths = resolve_lisa_config(config_path)
    root = paths.base / ".lisa"
    return root, paths.config_path, sha256_file(paths.config_path)


def safe_relative(value: str, label: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or ".." in path.parts
        or re.match(r"^[A-Za-z]:", normalized)
    ):
        raise CheckpointError(f"{label} must be a safe relative path")
    return path.as_posix()


def workflow_id() -> str:
    current = datetime.now().astimezone()
    return f"WF-{current:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8].upper()}"


def run_root(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"WF-[0-9]{8}-[0-9]{6}-[A-F0-9]{8}", run_id):
        raise CheckpointError(f"Invalid workflow run ID: {run_id}")
    return root / "runs" / run_id


def valid_snapshot(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = load_object(path)
        validate_integrity(value, path.name)
        if value.get("schemaVersion") != SCHEMA_VERSION:
            return None
        return value
    except CheckpointError:
        return None


def select_snapshot(directory: Path) -> tuple[dict[str, Any], Path]:
    candidates = [
        (value, path)
        for path in (directory / "workflow.a.json", directory / "workflow.b.json")
        if (value := valid_snapshot(path)) is not None
    ]
    if not candidates:
        raise CheckpointError(f"No valid workflow snapshot exists in {directory}")
    return max(candidates, key=lambda item: item[0]["generation"])


def current_run(root: Path) -> tuple[dict[str, Any], Path]:
    primary = valid_snapshot(root / "current.json")
    pointers = [primary] if primary is not None else [
        value
        for path in (root / "current.a.json", root / "current.b.json")
        if (value := valid_snapshot(path)) is not None
    ]
    if not pointers:
        raise CheckpointError(f"No valid current workflow pointer exists in {root}")
    pointer = max(pointers, key=lambda item: item["generation"])
    directory = run_root(root, str(pointer.get("workflowRunId", "")))
    snapshot, snapshot_path = select_snapshot(directory)
    return snapshot, snapshot_path


def append_event(directory: Path, event: dict[str, Any]) -> None:
    path = directory / "events.ndjson"
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, sort_keys=True, ensure_ascii=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def commit_snapshot(root: Path, snapshot: dict[str, Any], event: str) -> dict[str, Any]:
    directory = run_root(root, snapshot["workflowRunId"])
    snapshot = with_integrity(snapshot)
    target = directory / ("workflow.a.json" if snapshot["generation"] % 2 else "workflow.b.json")
    atomic_write(target, snapshot)
    pointer = with_integrity(
        {
            "schemaVersion": SCHEMA_VERSION,
            "workflowRunId": snapshot["workflowRunId"],
            "generation": snapshot["generation"],
            "snapshot": target.relative_to(root).as_posix(),
            "updatedAt": snapshot["updatedAt"],
        }
    )
    pointer_slot = root / ("current.a.json" if snapshot["generation"] % 2 else "current.b.json")
    atomic_write(pointer_slot, pointer)
    atomic_write(root / "current.json", pointer)
    append_event(
        directory,
        {
            "at": snapshot["updatedAt"],
            "event": event,
            "generation": snapshot["generation"],
            "stage": snapshot["activeStage"],
            "status": snapshot["status"],
        },
    )
    return snapshot


def initialize(config_path: Path, requested_id: str | None = None) -> dict[str, Any]:
    root, _, config_hash = checkpoint_root(config_path)
    with state_lock(root):
        if (root / "current.json").is_file():
            existing, _ = current_run(root)
            if existing["status"] in ACTIVE_STATUSES:
                return existing
        run_id = requested_id or workflow_id()
        directory = run_root(root, run_id)
        directory.mkdir(parents=True, exist_ok=False)
        timestamp = now_iso()
        snapshot = {
            "schemaVersion": SCHEMA_VERSION,
            "workflowRunId": run_id,
            "generation": 1,
            "configSha256": config_hash,
            "status": "RUNNING",
            "activeStage": None,
            "activeStageRunId": None,
            "activeCheckpoint": None,
            "completedStages": {},
            "updatedAt": timestamp,
        }
        return commit_snapshot(root, snapshot, "workflow-initialized")


def update_snapshot(root: Path, snapshot: dict[str, Any], event: str) -> dict[str, Any]:
    snapshot["generation"] += 1
    snapshot["updatedAt"] = now_iso()
    snapshot.pop("integritySha256", None)
    return commit_snapshot(root, snapshot, event)


def start_stage(
    config_path: Path, stage: str, stage_run_id: str, phase: str, unit_id: str | None
) -> dict[str, Any]:
    if stage not in STAGES:
        raise CheckpointError(f"Unknown stage: {stage}")
    root, _, config_hash = checkpoint_root(config_path)
    with state_lock(root):
        snapshot, _ = current_run(root)
        if snapshot["configSha256"] != config_hash:
            raise CheckpointError("Configuration changed since workflow initialization")
        if snapshot["status"] not in {"RUNNING", "WAITING", "RECONCILING"}:
            raise CheckpointError(f"Workflow is {snapshot['status']}")
        checkpoint = {
            "schemaVersion": SCHEMA_VERSION,
            "workflowRunId": snapshot["workflowRunId"],
            "stage": stage,
            "stageRunId": stage_run_id,
            "generation": 1,
            "status": "RUNNING",
            "phase": phase,
            "unitId": unit_id,
            "inputMarkers": {},
            "pendingOperation": None,
            "lastReceipt": None,
            "updatedAt": now_iso(),
        }
        directory = run_root(root, snapshot["workflowRunId"])
        checkpoint_path = directory / "active-stage.json"
        checkpoint = with_integrity(checkpoint)
        atomic_write(directory / "active-stage.a.json", checkpoint)
        atomic_write(checkpoint_path, checkpoint)
        snapshot.update(
            {
                "status": "RUNNING",
                "activeStage": stage,
                "activeStageRunId": stage_run_id,
                "activeCheckpoint": checkpoint_path.relative_to(root).as_posix(),
            }
        )
        return update_snapshot(root, snapshot, "stage-started")


def update_checkpoint(
    config_path: Path,
    phase: str,
    unit_id: str | None,
    status: str,
    pending_operation: dict[str, Any] | None = None,
    receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in CHECKPOINT_STATUSES:
        raise CheckpointError(f"Invalid checkpoint status: {status}")
    root, _, _ = checkpoint_root(config_path)
    with state_lock(root):
        snapshot, _ = current_run(root)
        relative = snapshot.get("activeCheckpoint")
        if not isinstance(relative, str):
            raise CheckpointError("No active stage checkpoint")
        path = root / safe_relative(relative, "activeCheckpoint")
        checkpoint = select_stage_checkpoint(path.parent)
        checkpoint.update(
            {
                "generation": checkpoint["generation"] + 1,
                "status": status,
                "phase": phase,
                "unitId": unit_id,
                "updatedAt": now_iso(),
            }
        )
        if pending_operation is not None:
            checkpoint["pendingOperation"] = pending_operation
        if receipt is not None:
            checkpoint["lastReceipt"] = receipt
            checkpoint["pendingOperation"] = None
        checkpoint.pop("integritySha256", None)
        checkpoint = with_integrity(checkpoint)
        slot = path.parent / (
            "active-stage.a.json" if checkpoint["generation"] % 2 else "active-stage.b.json"
        )
        atomic_write(slot, checkpoint)
        atomic_write(path, checkpoint)
        snapshot["status"] = status
        update_snapshot(root, snapshot, "stage-checkpointed")
        return checkpoint


def complete_stage(
    config_path: Path,
    marker: str,
    marker_sha256: str,
    stage_status: str,
) -> dict[str, Any]:
    if stage_status not in {"COMMITTED", "BLOCKED"}:
        raise CheckpointError("Stage status must be COMMITTED or BLOCKED")
    if not re.fullmatch(r"[a-f0-9]{64}", marker_sha256):
        raise CheckpointError("Completion marker SHA-256 is invalid")
    paths = resolve_lisa_config(config_path)
    root, _, _ = checkpoint_root(config_path)
    with state_lock(root):
        snapshot, _ = current_run(root)
        stage = snapshot.get("activeStage")
        stage_run_id = snapshot.get("activeStageRunId")
        if not isinstance(stage, str) or not isinstance(stage_run_id, str):
            raise CheckpointError("No active stage can be completed")
        marker = safe_relative(marker, "completion marker")
        marker_path = (paths.base / Path(*PurePosixPath(marker).parts)).resolve()
        try:
            marker_path.relative_to(paths.base.resolve())
        except ValueError as exc:
            raise CheckpointError("Completion marker escapes basePath") from exc
        if not marker_path.is_file():
            raise CheckpointError(f"Completion marker does not exist: {marker_path}")
        if sha256_file(marker_path) != marker_sha256:
            raise CheckpointError("Completion marker hash does not match the file")
        snapshot["completedStages"][stage] = {
            "stageRunId": stage_run_id,
            "status": stage_status,
            "completionMarker": marker,
            "completionMarkerSha256": marker_sha256,
            "completedAt": now_iso(),
        }
        snapshot["status"] = "RUNNING" if stage_status == "COMMITTED" else "BLOCKED"
        snapshot["activeStage"] = None if stage_status == "COMMITTED" else stage
        snapshot["activeStageRunId"] = None if stage_status == "COMMITTED" else stage_run_id
        snapshot["activeCheckpoint"] = None if stage_status == "COMMITTED" else snapshot["activeCheckpoint"]
        return update_snapshot(root, snapshot, "stage-completed")


def finish(config_path: Path, status: str) -> dict[str, Any]:
    if status not in {"COMPLETED", "FAILED", "CANCELLED"}:
        raise CheckpointError("Workflow finish status is invalid")
    root, _, _ = checkpoint_root(config_path)
    with state_lock(root):
        snapshot, _ = current_run(root)
        if status == "COMPLETED" and snapshot.get("activeStage") is not None:
            raise CheckpointError("Cannot complete a workflow with an active stage")
        snapshot["status"] = status
        return update_snapshot(root, snapshot, "workflow-finished")


def select_stage_checkpoint(directory: Path) -> dict[str, Any]:
    primary = valid_snapshot(directory / "active-stage.json")
    candidates = [primary] if primary is not None else [
        value
        for path in (directory / "active-stage.a.json", directory / "active-stage.b.json")
        if (value := valid_snapshot(path)) is not None
    ]
    if not candidates:
        raise CheckpointError(f"No valid active stage checkpoint exists in {directory}")
    return max(candidates, key=lambda item: item["generation"])


def recover(config_path: Path) -> dict[str, Any]:
    root, _, config_hash = checkpoint_root(config_path)
    snapshot, snapshot_path = current_run(root)
    result: dict[str, Any] = {
        "workflow": snapshot,
        "snapshotPath": str(snapshot_path),
        "configMatches": snapshot["configSha256"] == config_hash,
        "resume": None,
    }
    relative = snapshot.get("activeCheckpoint")
    if isinstance(relative, str):
        checkpoint_path = root / safe_relative(relative, "activeCheckpoint")
    else:
        checkpoint_path = run_root(root, snapshot["workflowRunId"]) / "active-stage.json"
    if checkpoint_path.is_file() or any(
        (checkpoint_path.parent / name).is_file()
        for name in ("active-stage.a.json", "active-stage.b.json")
    ):
        checkpoint = select_stage_checkpoint(checkpoint_path.parent)
        if checkpoint.get("workflowRunId") != snapshot["workflowRunId"]:
            raise CheckpointError("Active checkpoint belongs to another workflow")
        completed = snapshot.get("completedStages", {}).get(checkpoint.get("stage"))
        if (
            isinstance(completed, dict)
            and completed.get("stageRunId") == checkpoint.get("stageRunId")
        ):
            return result
        action = "reconcile-remote-operation" if checkpoint.get("pendingOperation") else "continue-phase"
        result["resume"] = {
            "action": action,
            "stage": checkpoint["stage"],
            "stageRunId": checkpoint["stageRunId"],
            "phase": checkpoint["phase"],
            "unitId": checkpoint["unitId"],
            "checkpointPath": str(checkpoint_path),
            "pendingOperation": checkpoint.get("pendingOperation"),
        }
    return result


def parse_json(raw: str | None, label: str) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CheckpointError(f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CheckpointError(f"{label} must be an object")
    return value


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--config", required=True)
    commands = value.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--workflow-run-id")
    commands.add_parser("show")
    commands.add_parser("recover")
    start = commands.add_parser("start-stage")
    start.add_argument("--stage", required=True, choices=STAGES)
    start.add_argument("--stage-run-id", required=True)
    start.add_argument("--phase", required=True)
    start.add_argument("--unit-id")
    checkpoint = commands.add_parser("checkpoint")
    checkpoint.add_argument("--phase", required=True)
    checkpoint.add_argument("--unit-id")
    checkpoint.add_argument("--status", choices=sorted(CHECKPOINT_STATUSES), default="RUNNING")
    checkpoint.add_argument("--pending-operation-json")
    checkpoint.add_argument("--receipt-json")
    complete = commands.add_parser("complete-stage")
    complete.add_argument("--marker", required=True)
    complete.add_argument("--marker-sha256", required=True)
    complete.add_argument("--stage-status", choices=["COMMITTED", "BLOCKED"], default="COMMITTED")
    finish_parser = commands.add_parser("finish")
    finish_parser.add_argument("--status", choices=["COMPLETED", "FAILED", "CANCELLED"], required=True)
    return value


def main() -> int:
    args = parser().parse_args()
    config = Path(args.config)
    try:
        if args.command == "init":
            result = initialize(config, args.workflow_run_id)
        elif args.command == "show":
            root, _, _ = checkpoint_root(config)
            result, _ = current_run(root)
        elif args.command == "recover":
            result = recover(config)
        elif args.command == "start-stage":
            result = start_stage(config, args.stage, args.stage_run_id, args.phase, args.unit_id)
        elif args.command == "checkpoint":
            result = update_checkpoint(
                config,
                args.phase,
                args.unit_id,
                args.status,
                parse_json(args.pending_operation_json, "pending-operation-json"),
                parse_json(args.receipt_json, "receipt-json"),
            )
        elif args.command == "complete-stage":
            result = complete_stage(config, args.marker, args.marker_sha256, args.stage_status)
        elif args.command == "finish":
            result = finish(config, args.status)
        else:
            raise CheckpointError(f"Unsupported command: {args.command}")
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except (CheckpointError, LisaConfigError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())