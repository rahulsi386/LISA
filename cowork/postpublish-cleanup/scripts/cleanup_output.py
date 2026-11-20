#!/usr/bin/env python3
"""Inventory or remove contents from a config-resolved LISA output folder."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from validate_artifact_contracts import validate_contract
from lisa_path_resolver import LisaConfigError, resolve_lisa_config

CONFIRMATION = "DELETE OUTPUT"
SAMPLE_LIMIT = 20
ARTIFACT_CONTRACT = validate_contract(Path(__file__).resolve().parents[1])
if ARTIFACT_CONTRACT["producesArtifacts"]:
    raise RuntimeError("Cleanup artifact contract must not declare generated artifacts")


class CleanupError(RuntimeError):
    pass


class PartialCleanupError(CleanupError):
    def __init__(
        self,
        message: str,
        *,
        deleted_files: int,
        deleted_directories: int,
        deleted_bytes: int,
        output_root: Path,
    ) -> None:
        super().__init__(message)
        self.deleted_files = deleted_files
        self.deleted_directories = deleted_directories
        self.deleted_bytes = deleted_bytes
        self.output_root = output_root

    def public(self) -> dict[str, Any]:
        return {
            "status": "failed",
            "partial": True,
            "error": str(self),
            "outputRoot": str(self.output_root),
            "deletedFilesSoFar": self.deleted_files,
            "deletedDirectoriesSoFar": self.deleted_directories,
            "deletedBytesSoFar": self.deleted_bytes,
            "rootPreserved": self.output_root.is_dir(),
        }


@dataclass
class Inventory:
    customer: str
    config_path: Path
    project_root: Path
    output_root: Path
    files: list[Path]
    file_metadata: dict[Path, tuple[int, int]]
    directories: list[Path]
    total_bytes: int
    fingerprint: str

    def public(self) -> dict[str, Any]:
        samples = [
            path.relative_to(self.output_root).as_posix()
            for path in self.files[:SAMPLE_LIMIT]
        ]
        return {
            "status": "inventory",
            "customer": self.customer,
            "config": str(self.config_path),
            "projectRoot": str(self.project_root),
            "outputRoot": str(self.output_root),
            "fileCount": len(self.files),
            "directoryCount": len(self.directories),
            "totalBytes": self.total_bytes,
            "fingerprint": self.fingerprint,
            "sampleFiles": samples,
            "sampleTruncated": len(self.files) > SAMPLE_LIMIT,
            "rootWillBePreserved": True,
            "requiresConfirmation": bool(self.files or self.directories),
            "confirmationPhrase": CONFIRMATION,
        }


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CleanupError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CleanupError(f"Expected a JSON object in {path}")
    return value


def is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, OSError):
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def reject_reparse_chain(candidate: Path, project_root: Path) -> None:
    current = candidate
    paths: list[Path] = []
    while True:
        paths.append(current)
        if current == project_root or current.parent == current:
            break
        current = current.parent
    for path in reversed(paths):
        if path.exists() and is_reparse_point(path):
            raise CleanupError(f"Reparse point is not allowed in output path: {path}")


def resolve_output(config_path: Path) -> tuple[dict[str, Any], Path, Path]:
    try:
        paths = resolve_lisa_config(config_path)
    except LisaConfigError as exc:
        raise CleanupError(str(exc)) from exc
    config = paths.config
    project_root = paths.base
    candidate = paths.output
    reject_reparse_chain(candidate, project_root)
    output_root = candidate.resolve()
    if not output_root.is_dir():
        raise CleanupError(f"Resolved output folder does not exist: {output_root}")
    if output_root == project_root or output_root.parent == output_root:
        raise CleanupError("Refusing to clean an unsafe output root")
    return config, project_root, output_root


def walk_entries(output_root: Path) -> tuple[list[Path], list[Path]]:
    files: list[Path] = []
    directories: list[Path] = []
    stack = [output_root]
    while stack:
        directory = stack.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise CleanupError(f"Cannot inspect {directory}: {exc}") from exc
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink() or is_reparse_point(path):
                raise CleanupError(f"Reparse point found beneath output root: {path}")
            try:
                if entry.is_dir(follow_symlinks=False):
                    directories.append(path)
                    stack.append(path)
                elif entry.is_file(follow_symlinks=False):
                    files.append(path)
                else:
                    raise CleanupError(f"Unsupported filesystem entry: {path}")
            except OSError as exc:
                raise CleanupError(f"Cannot inspect entry {path}: {exc}") from exc
    files.sort(key=lambda path: path.relative_to(output_root).as_posix().casefold())
    directories.sort(
        key=lambda path: path.relative_to(output_root).as_posix().casefold()
    )
    return files, directories


def inventory(config_path: Path) -> Inventory:
    config, project_root, output_root = resolve_output(config_path)
    files, directories = walk_entries(output_root)
    digest = hashlib.sha256()
    digest.update(f"root\0{str(output_root).casefold()}\n".encode("utf-8"))
    total_bytes = 0
    file_metadata: dict[Path, tuple[int, int]] = {}
    for directory in directories:
        relative = directory.relative_to(output_root).as_posix()
        digest.update(f"d\0{relative}\n".encode("utf-8"))
    for path in files:
        try:
            metadata = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise CleanupError(f"Cannot stat {path}: {exc}") from exc
        relative = path.relative_to(output_root).as_posix()
        total_bytes += metadata.st_size
        file_metadata[path] = (metadata.st_size, metadata.st_mtime_ns)
        digest.update(
            f"f\0{relative}\0{metadata.st_size}\0{metadata.st_mtime_ns}\n".encode(
                "utf-8"
            )
        )
    return Inventory(
        customer=str(config["custName"]),
        config_path=config_path.expanduser().resolve(),
        project_root=project_root,
        output_root=output_root,
        files=files,
        file_metadata=file_metadata,
        directories=directories,
        total_bytes=total_bytes,
        fingerprint=digest.hexdigest(),
    )


def unlink_file(path: Path) -> None:
    try:
        path.unlink()
    except PermissionError:
        try:
            os.chmod(path, stat.S_IWRITE)
            path.unlink()
        except OSError as exc:
            raise CleanupError(f"Cannot delete read-only file {path}: {exc}") from exc
    except OSError as exc:
        raise CleanupError(f"Cannot delete file {path}: {exc}") from exc


def execute_cleanup(
    config_path: Path,
    expected_fingerprint: str,
    confirmation: str,
) -> dict[str, Any]:
    if confirmation != CONFIRMATION:
        raise CleanupError(
            f"Exact confirmation phrase required: {CONFIRMATION}"
        )
    if not re.fullmatch(r"[a-f0-9]{64}", expected_fingerprint):
        raise CleanupError("Expected fingerprint must be a lowercase SHA-256 value")
    current = inventory(config_path)
    if not hmac.compare_digest(current.fingerprint, expected_fingerprint):
        raise CleanupError(
            "Output contents changed after consent; inventory and consent must be repeated"
        )

    deleted_files = 0
    deleted_directories = 0
    deleted_bytes = 0

    def partial(message: str) -> PartialCleanupError:
        return PartialCleanupError(
            message,
            deleted_files=deleted_files,
            deleted_directories=deleted_directories,
            deleted_bytes=deleted_bytes,
            output_root=current.output_root,
        )

    for path in current.files:
        if is_reparse_point(path):
            raise partial(f"Reparse point appeared before deletion: {path}")
        try:
            metadata = path.stat(follow_symlinks=False)
        except OSError as exc:
            raise partial(f"Cannot revalidate file {path}: {exc}") from exc
        expected_metadata = current.file_metadata[path]
        if (metadata.st_size, metadata.st_mtime_ns) != expected_metadata:
            raise partial(
                f"File changed after consent and was preserved: {path}"
            )
        try:
            unlink_file(path)
        except CleanupError as exc:
            raise partial(f"{exc}; cleanup is partial") from exc
        deleted_files += 1
        deleted_bytes += metadata.st_size
    for path in sorted(
        current.directories,
        key=lambda value: len(value.relative_to(current.output_root).parts),
        reverse=True,
    ):
        if is_reparse_point(path):
            raise partial(f"Reparse point appeared before deletion: {path}")
        try:
            path.rmdir()
        except OSError as exc:
            raise partial(f"Cannot remove directory {path}: {exc}") from exc
        deleted_directories += 1

    try:
        remaining = list(os.scandir(current.output_root))
    except OSError as exc:
        raise partial(f"Cannot verify output root: {exc}") from exc
    if remaining:
        raise partial(
            "Cleanup did not leave the output root empty; newly added content was preserved"
        )
    return {
        "status": "passed",
        "customer": current.customer,
        "outputRoot": str(current.output_root),
        "deletedFiles": deleted_files,
        "deletedDirectories": deleted_directories,
        "deletedBytes": deleted_bytes,
        "rootPreserved": current.output_root.is_dir(),
        "rootEmpty": True,
        "fingerprint": current.fingerprint,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inventory", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-fingerprint")
    parser.add_argument("--confirm")
    args = parser.parse_args()
    try:
        config_path = Path(args.config)
        if args.inventory:
            result = inventory(config_path).public()
        else:
            if not args.expected_fingerprint or args.confirm is None:
                raise CleanupError(
                    "--execute requires --expected-fingerprint and --confirm"
                )
            result = execute_cleanup(
                config_path,
                args.expected_fingerprint,
                args.confirm,
            )
        print(json.dumps(result, indent=2))
        return 0
    except PartialCleanupError as exc:
        print(json.dumps(exc.public(), indent=2), file=sys.stderr)
        return 2
    except (CleanupError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
