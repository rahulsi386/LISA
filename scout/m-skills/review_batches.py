"""Lossless, deterministic, byte-bounded model-facing evidence batches."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable


class ReviewBatchError(RuntimeError):
    """Evidence cannot be represented within the requested review contract."""


def _bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ReviewBatchError(f"Review evidence must be valid UTF-8 JSON: {exc}") from exc


def _write(path: Path, content: bytes) -> None:
    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ReviewBatchError(f"Review output cannot be a link: {path}")
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_review_batches(
    directory: Path,
    records: Iterable[dict[str, Any]],
    *,
    max_bytes: int = 16384,
) -> dict[str, Any]:
    """Preserve each record and its metadata, splitting only text at codepoint boundaries.

    The budget covers the entire serialized batch, not just its text. Token counts vary
    by tokenizer; UTF-8 byte size is a reproducible limit, not a claimed token measurement.
    """
    if type(max_bytes) is not int or max_bytes < 256:
        raise ReviewBatchError("Review batch max_bytes must be an integer of at least 256")
    directory = Path(os.path.abspath(directory))
    for component in (*reversed(directory.parents), directory):
        if component.is_symlink() or (
            hasattr(component, "is_junction") and component.is_junction()
        ):
            raise ReviewBatchError(f"Review directory cannot use links: {component}")
    directory.mkdir(parents=True, exist_ok=True)
    envelope = {"schema_version": "1.0", "records": []}
    base_size = len(_bytes(envelope)) + 1
    current: list[dict[str, Any]] = []
    current_size = base_size
    batches: list[dict[str, Any]] = []
    seen: set[str] = set()
    content_hash = hashlib.sha256()
    fragment_count = 0

    def flush() -> None:
        nonlocal current, current_size
        if not current:
            return
        payload = _bytes({**envelope, "records": current}) + b"\n"
        if len(payload) > max_bytes:
            raise ReviewBatchError("Serialized review batch exceeded its byte budget")
        digest = hashlib.sha256(payload).hexdigest()
        batch_id = f"B-{digest}"
        name = f"{batch_id}.json"
        _write(directory / name, payload)
        batches.append({
            "batch_id": batch_id, "path": name, "sha256": digest,
            "byte_count": len(payload), "first_record_id": current[0]["record_id"],
            "last_record_id": current[-1]["record_id"], "fragment_count": len(current),
        })
        current = []
        current_size = base_size

    def append(fragment: dict[str, Any]) -> None:
        nonlocal current_size, fragment_count
        size = len(_bytes(fragment))
        if current and current_size + size + 1 > max_bytes:
            flush()
        if base_size + size > max_bytes:
            raise ReviewBatchError(f"Review record metadata exceeds byte budget: {fragment['record_id']}")
        current_size += size + (1 if current else 0)
        current.append(fragment)
        fragment_count += 1

    for record in records:
        if not isinstance(record, dict):
            raise ReviewBatchError("Review records must be JSON objects")
        identifier = record.get("record_id")
        text = record.get("text")
        if not isinstance(identifier, str) or not identifier.strip() or not isinstance(text, str):
            raise ReviewBatchError("Review records require nonempty record_id and string text")
        if identifier in seen:
            raise ReviewBatchError(f"Duplicate review record_id: {identifier}")
        if "part" in record or "final_part" in record:
            raise ReviewBatchError("part and final_part are reserved review-fragment fields")
        seen.add(identifier)
        content_hash.update(_bytes(record) + b"\n")
        complete = {**record, "part": 1, "final_part": True}
        if base_size + len(_bytes(complete)) <= max_bytes:
            append(complete)
            continue
        offset = 0
        part = 1
        while offset < len(text):
            low, high, length = 1, min(len(text) - offset, max_bytes), 0
            while low <= high:
                count = (low + high) // 2
                fragment = {
                    **record, "text": text[offset:offset + count], "part": part,
                    "final_part": offset + count == len(text),
                }
                if base_size + len(_bytes(fragment)) <= max_bytes:
                    length = count
                    low = count + 1
                else:
                    high = count - 1
            if not length:
                raise ReviewBatchError(f"Review record metadata exceeds byte budget: {identifier}")
            append({
                **record, "text": text[offset:offset + length], "part": part,
                "final_part": offset + length == len(text),
            })
            offset += length
            part += 1
        if not text:
            raise ReviewBatchError(f"Review record metadata exceeds byte budget: {identifier}")
    flush()
    index = {
        "schema_version": "1.0", "max_bytes": max_bytes, "record_count": len(seen),
        "fragment_count": fragment_count, "batches": batches,
        "content_sha256": content_hash.hexdigest(),
        "total_batch_bytes": sum(item["byte_count"] for item in batches),
    }
    page: list[dict[str, Any]] = []
    page_number = 1

    def page_bytes(items: list[dict[str, Any]], next_page: str) -> bytes:
        return _bytes({"batches": items, "next_page": next_page}) + b"\n"

    for batch in batches:
        entry = {"path": batch["path"], "byte_count": batch["byte_count"]}
        next_name = f"index-page-{page_number + 1:06d}.json"
        if page and len(page_bytes([*page, entry], next_name)) > max_bytes:
            _write(directory / f"index-page-{page_number:06d}.json", page_bytes(page, next_name))
            page_number += 1
            page = []
        page.append(entry)
        if len(page_bytes(page, f"index-page-{page_number + 1:06d}.json")) > max_bytes:
            raise ReviewBatchError("Review byte budget is too small for an index entry")
    if page:
        _write(directory / f"index-page-{page_number:06d}.json", page_bytes(page, ""))
    overview = {
        "record_count": len(seen), "fragment_count": fragment_count,
        "batch_count": len(batches), "max_bytes": max_bytes,
        "total_batch_bytes": index["total_batch_bytes"],
        "first_page": "index-page-000001.json" if batches else "",
    }
    overview_path = directory / "overview.json"
    _write(overview_path, _bytes(overview) + b"\n")
    index["first_page"] = overview["first_page"]
    index_path = directory / "index.json"
    _write(index_path, _bytes(index) + b"\n")
    return {**index, "index_path": str(index_path), "overview_path": str(overview_path)}
