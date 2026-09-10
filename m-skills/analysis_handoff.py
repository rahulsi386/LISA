"""Hash-linked publication boundary between requirement analysis and classification."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


LEDGER_NAME = re.compile(r"requirement-analysis_[0-9]{8}_[0-9]{6}(?:_[0-9]{3})?\.json")
RUN_ID = re.compile(r"RA-[0-9]{8}_[0-9]{6}(?:_[0-9]{3})?-[A-F0-9]{8}")
SHA256 = re.compile(r"[a-f0-9]{64}")


class AnalysisHandoffError(RuntimeError):
    """An analysis is not a complete, intact publication."""


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                   allow_nan=False).encode("utf-8")
    ).hexdigest()


def _checked_path(path: Path) -> Path:
    absolute = Path(os.path.abspath(path))
    for component in (*reversed(absolute.parents), absolute):
        if component.is_symlink() or (
            hasattr(component, "is_junction") and component.is_junction()
        ):
            raise AnalysisHandoffError(f"Analysis handoff cannot use links: {component}")
    return absolute


def _read(path: Path) -> bytes:
    try:
        return _checked_path(path).read_bytes()
    except OSError as exc:
        raise AnalysisHandoffError(f"Cannot read analysis handoff artifact {path}: {exc}") from exc


def _object(payload: bytes, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise AnalysisHandoffError(f"Invalid analysis handoff JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AnalysisHandoffError(f"Analysis handoff must contain an object: {path}")
    return value


def _timestamp(value: Any) -> None:
    if not isinstance(value, str):
        raise AnalysisHandoffError("Analysis publication requires validated_at_local")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise AnalysisHandoffError("Analysis validation timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AnalysisHandoffError("Analysis validation timestamp requires a timezone")


def _source_manifest(manifest: dict[str, Any]) -> None:
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise AnalysisHandoffError("Analysis manifest has an invalid run ID")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not all(isinstance(item, dict) for item in sources):
        raise AnalysisHandoffError("Analysis manifest requires its source inventory")
    count = manifest.get("source_count")
    if type(count) is not int or count != len(sources):
        raise AnalysisHandoffError("Analysis manifest source count differs from its inventory")
    if manifest.get("manifest_sha256") != _canonical_hash(sources):
        raise AnalysisHandoffError("Analysis source inventory hash does not match its manifest")
    root = manifest.get("requirements_root")
    if not isinstance(root, str) or not Path(root).is_absolute() or Path(root).name != "requirements":
        raise AnalysisHandoffError("Analysis manifest requires an absolute requirements root")


def _paths(ledger_path: Path) -> tuple[Path, Path, Path]:
    ledger = _checked_path(ledger_path)
    if not LEDGER_NAME.fullmatch(ledger.name):
        raise AnalysisHandoffError(f"Invalid requirement-analysis ledger filename: {ledger.name}")
    return ledger, ledger.with_suffix(".md"), ledger.with_name(f"{ledger.stem}-manifest.json")


def build_validated_manifest(
    source_manifest: dict[str, Any],
    ledger_path: Path,
    markdown_path: Path,
    validated_at_local: str,
) -> dict[str, Any]:
    """Build the commit marker; callers must publish it LAST, after all validation."""
    ledger_path, expected_markdown, _ = _paths(ledger_path)
    if _checked_path(markdown_path) != expected_markdown:
        raise AnalysisHandoffError("Analysis Markdown must be the matching ledger sibling")
    _source_manifest(source_manifest)
    _timestamp(validated_at_local)
    ledger_bytes = _read(ledger_path)
    ledger = _object(ledger_bytes, ledger_path)
    if ledger.get("run_id") != source_manifest["run_id"]:
        raise AnalysisHandoffError("Analysis ledger and source manifest run IDs differ")
    result = copy.deepcopy(source_manifest)
    result["publication"] = {
        "schema_version": "1.0",
        "status": "validated",
        "run_id": source_manifest["run_id"],
        "validated_at_local": validated_at_local,
        "ledger": {
            "path": ledger_path.name,
            "sha256": hashlib.sha256(ledger_bytes).hexdigest(),
        },
        "markdown": {
            "path": expected_markdown.name,
            "sha256": hashlib.sha256(_read(expected_markdown)).hexdigest(),
        },
    }
    return result


def load_validated_analysis(
    ledger_path: Path,
    *,
    expected_requirements_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load one bytes-bound ledger; a timestamp or file's existence is not approval."""
    ledger_path, markdown_path, manifest_path = _paths(ledger_path)
    manifest_bytes = _read(manifest_path)
    manifest = _object(manifest_bytes, manifest_path)
    _source_manifest(manifest)
    publication = manifest.get("publication")
    if not isinstance(publication, dict) or (
        publication.get("schema_version") != "1.0"
        or publication.get("status") != "validated"
        or publication.get("run_id") != manifest["run_id"]
    ):
        raise AnalysisHandoffError("Analysis has no validated publication marker; publish it first")
    _timestamp(publication.get("validated_at_local"))
    if expected_requirements_root is not None:
        expected_root = _checked_path(expected_requirements_root)
        if _checked_path(Path(manifest["requirements_root"])) != expected_root:
            raise AnalysisHandoffError("Analysis requirements root differs from lisa-config.json")
        if ledger_path.parent != expected_root.parent / "output" / "analysis":
            raise AnalysisHandoffError("Analysis handoff is outside the configured analysis directory")
    ledger: dict[str, Any] | None = None
    for key, path in (("ledger", ledger_path), ("markdown", markdown_path)):
        artifact = publication.get(key)
        if not isinstance(artifact, dict) or artifact.get("path") != path.name:
            raise AnalysisHandoffError(f"Analysis publication {key} path is not its exact sibling")
        expected_hash = artifact.get("sha256")
        if not isinstance(expected_hash, str) or not SHA256.fullmatch(expected_hash):
            raise AnalysisHandoffError(f"Analysis publication {key} hash is invalid")
        payload = _read(path)
        if hashlib.sha256(payload).hexdigest() != expected_hash:
            raise AnalysisHandoffError(f"Analysis publication {key} hash does not match")
        if key == "ledger":
            ledger = _object(payload, path)
    if ledger is None or ledger.get("run_id") != manifest["run_id"]:
        raise AnalysisHandoffError("Analysis ledger and validated manifest run IDs differ")
    if _read(manifest_path) != manifest_bytes:
        raise AnalysisHandoffError("Analysis publication changed while loading; retry after publication")
    return ledger, manifest


def select_latest_validated_analysis(
    analysis_directory: Path,
    *,
    expected_requirements_root: Path | None = None,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Select without resolving away links; never fall back past an invalid latest run."""
    root = _checked_path(analysis_directory)
    if not root.is_dir():
        raise AnalysisHandoffError(f"Analysis directory does not exist: {root}")
    candidates = []
    for candidate in root.glob("requirement-analysis_*.json"):
        if LEDGER_NAME.fullmatch(candidate.name):
            _checked_path(candidate)
            if candidate.is_file():
                candidates.append(candidate)
    if not candidates:
        raise AnalysisHandoffError(f"No requirement-analysis JSON found in {root}")
    latest = max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))
    ledger, manifest = load_validated_analysis(
        latest, expected_requirements_root=expected_requirements_root,
    )
    return latest, ledger, manifest
