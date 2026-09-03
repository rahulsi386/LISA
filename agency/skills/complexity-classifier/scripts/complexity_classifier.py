#!/usr/bin/env python3
"""Deterministic support pipeline for requirement complexity classification."""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import html
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from validate_artifact_contracts import canonical_stage_root, validate_contract
from lisa_path_resolver import LisaConfigError, latest_file, resolve_lisa_config


VERSION = "2.0.0"
CACHE_VERSION = "2"
SKILL_ROOT = Path(__file__).resolve().parents[1]
RESOURCES = SKILL_ROOT / "resources"
ARTIFACT_CONTRACT = validate_contract(SKILL_ROOT)
REFERENCE_MANIFEST_PATH = RESOURCES / "reference-manifest.json"
RULES_PATH = RESOURCES / "classification-rules.json"
MODEL_SCHEMA_PATH = RESOURCES / "classification-model.schema.json"
OUTPUT_SCHEMA_PATH = RESOURCES / "classification-output.schema.json"
ASSESSMENT_SCHEMA_PATH = RESOURCES / "research-assessment.schema.json"
CLASSIFICATION_MANIFEST_SCHEMA_PATH = RESOURCES / "classification-manifest.schema.json"
TEMPLATE_PATH = RESOURCES / "classification.template.md"
PLATFORM_DECISION_PATH = SKILL_ROOT.parent / "Platform-Decision.md"

CLASSIFICATION_FILENAME = re.compile(
    r"^complexity-classification_[0-9]{8}_[0-9]{6}(_[0-9]{3})?\.(md|json)$"
)
REQUIREMENT_FILENAME = re.compile(
    r"^requirement-analysis_[0-9]{8}_[0-9]{6}(_[0-9]{3})?\.json$"
)
REQUIRED_HEADINGS = [
    "Reference Documentation Consulted",
    "Final Classification",
    "Agentic Platform, Code Tier and Harness",
    "Comprehensive Justification",
    "Extracted Evidence",
    "Solution Component Inventory",
    "Allowed-Tool PoC Feasibility",
    "Architecture and Sequence Design Contract",
    "Counts",
    "Gaps and Conflicts",
    "Classification JSON",
]
IN_SCOPE_STATUSES = {
    "Required",
    "Confirmed",
    "Current",
    "Preferred",
    "Near-term",
}
RESEARCH_ORDER = {
    "copilot": 0,
    "foundry": 1,
    "agent-framework": 2,
}
FOUNDRY_REFERENCE_IDS = {
    "foundry-agent-service",
    "azure-rbac",
    "azure-policy",
    "azure-monitor",
    "azure-pipelines",
}
AGENT_FRAMEWORK_REFERENCE_IDS = {"agent-framework"}
DEFAULT_CONVERSATIONAL_CHANNELS = [
    "Microsoft Teams",
    "Microsoft 365 Copilot",
]


class ClassifierError(RuntimeError):
    """A user-actionable classification pipeline failure."""


def _json_load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClassifierError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ClassifierError(f"Expected a JSON object in {path}")
    return value


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_text(
        path, json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _assert_no_link_components(path: Path) -> None:
    absolute = _absolute(path)
    parts = absolute.parts
    if not parts:
        raise ClassifierError(f"Invalid empty path: {path}")
    current = Path(parts[0])
    for part in parts[1:]:
        current /= part
        if current.exists() and _is_link_or_junction(current):
            raise ClassifierError(f"Path contains a link or junction: {current}")


def _safe_write_path(path: Path, classification_root: Path) -> Path:
    _assert_no_link_components(path)
    resolved = path.resolve(strict=False)
    if not _is_within(resolved, classification_root):
        raise ClassifierError(
            f"Generated artifact escapes Classification: {path}"
        )
    return resolved


def _authoritative_local_time(value: str | None) -> datetime:
    if not value:
        return datetime.now().astimezone()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ClassifierError(f"Invalid authoritative local time: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ClassifierError("Authoritative local time must include a UTC offset")
    return parsed


def _run_local_time(run: dict[str, Any]) -> str:
    start = datetime.fromisoformat(run["started_at_local"])
    elapsed = max(0.0, time.time() - float(run["started_epoch"]))
    return (start + timedelta(seconds=elapsed)).isoformat()


def _timestamp_for_output(root: Path, now: datetime) -> str:
    base = now.strftime("%Y%m%d_%H%M%S")

    def available(candidate: str) -> bool:
        markdown = root / f"complexity-classification_{candidate}.md"
        json_path = root / f"complexity-classification_{candidate}.json"
        runs = root / ".complexity-classifier" / "runs"
        prior = list(runs.glob(f"CC-{candidate}-*")) if runs.exists() else []
        return not markdown.exists() and not json_path.exists() and not prior

    if available(base):
        return base
    start = now.microsecond // 1000
    for offset in range(1000):
        candidate = f"{base}_{(start + offset) % 1000:03d}"
        if available(candidate):
            return candidate
    raise ClassifierError("Could not reserve a unique classification timestamp")


def _find_lisa_config(input_path: Path, temp_output: Path) -> Path | None:
    candidates: list[Path] = []
    for parent in [input_path.parent, *input_path.parents]:
        candidates.append(parent / "lisa-config.json")
        if len(candidates) >= 8:
            break
    candidates.insert(0, temp_output / "lisa-config.json")
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    return None


def _extract_configured_channels(value: Any, key_path: str = "") -> list[str]:
    channels: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            child_path = f"{key_path}.{key}" if key_path else str(key)
            if re.search(
                r"(channel|publish|surface|teams|copilot)",
                str(key),
                flags=re.IGNORECASE,
            ):
                if isinstance(item, str) and item.strip():
                    channels.append(item.strip())
                elif isinstance(item, list):
                    channels.extend(
                        str(entry).strip()
                        for entry in item
                        if isinstance(entry, (str, int)) and str(entry).strip()
                    )
            channels.extend(_extract_configured_channels(item, child_path))
    elif isinstance(value, list):
        for item in value:
            channels.extend(_extract_configured_channels(item, key_path))
    normalized: list[str] = []
    for channel in channels:
        lower = channel.casefold()
        if "copilot chat" in lower:
            name = "Microsoft 365 Copilot Chat"
        elif "teams" in lower:
            name = "Microsoft Teams"
        elif "microsoft 365 copilot" in lower or "m365 copilot" in lower:
            name = "Microsoft 365 Copilot"
        elif "power pages" in lower:
            name = "Microsoft Power Pages"
        elif "web" in lower:
            name = "Web"
        elif "mobile" in lower:
            name = "Mobile"
        else:
            name = channel
        if name not in normalized:
            normalized.append(name)
    return normalized


def _channel_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    patterns = {
        "Microsoft Teams": r"\bmicrosoft teams\b|\bteams channel\b",
        "Microsoft 365 Copilot Chat": r"\bcopilot chat\b",
        "Microsoft 365 Copilot": r"\bmicrosoft 365 copilot\b(?!\s+chat)|\bm365 copilot\b(?!\s+chat)",
        "Microsoft Power Pages": r"\bpower pages\b",
        "Web": r"\bweb channel\b|\bweb site\b|\bwebsite channel\b",
        "Mobile": r"\bmobile channel\b|\bmobile app\b",
    }
    values: list[dict[str, Any]] = []
    for name, pattern in patterns.items():
        identifiers = [
            item["finding_id"]
            for item in findings
            if re.search(pattern, item.get("statement", ""), re.IGNORECASE)
        ]
        if identifiers:
            values.append({"name": name, "finding_ids": identifiers})
    return values


def _validate_requirement_analysis(
    path: Path, data: dict[str, Any]
) -> None:
    if not REQUIREMENT_FILENAME.fullmatch(path.name):
        raise ClassifierError(
            f"Input filename is not a timestamped requirement analysis: {path.name}"
        )
    required = {
        "findings",
        "source_annotations",
        "knowledge_sources",
        "integrations",
        "agentic_behaviors",
        "sections",
    }
    missing = sorted(required - set(data))
    if missing:
        raise ClassifierError(
            f"Requirement analysis is missing fields: {', '.join(missing)}"
        )
    findings = data["findings"]
    identifiers = [item.get("finding_id") for item in findings]
    if not findings or len(identifiers) != len(set(identifiers)):
        raise ClassifierError("Requirement findings must be nonempty and uniquely identified")


def _section_items(
    blocks: Any, in_scope_ids: set[str]
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    if not isinstance(blocks, list):
        return values

    def add(text: str, evidence_ids: list[str]) -> None:
        scoped_ids = [
            identifier for identifier in evidence_ids if identifier in in_scope_ids
        ]
        if (
            text
            and scoped_ids
            and not _contains_classic_topic_text(text)
        ):
            values.append({"text": text, "evidence_ids": scoped_ids})

    for block in blocks:
        if not isinstance(block, dict):
            continue
        if "text" in block:
            add(str(block["text"]), block.get("finding_ids", []))
        for item in block.get("items", []):
            if isinstance(item, dict) and "text" in item:
                add(str(item["text"]), item.get("finding_ids", []))
        for row in block.get("rows", []):
            if isinstance(row, dict):
                add(
                    " | ".join(str(cell) for cell in row.get("cells", [])),
                    row.get("finding_ids", []),
                )
    return values


def _build_evidence_summary(
    data: dict[str, Any],
    lisa_config_path: Path | None,
    lisa_config: dict[str, Any] | None,
) -> dict[str, Any]:
    findings = data["findings"]
    in_scope = [
        {
            "finding_id": item["finding_id"],
            "kind": item["kind"],
            "status": item["status"],
            "statement": item["statement"],
        }
        for item in findings
        if item.get("status") in IN_SCOPE_STATUSES
        and item.get("kind") != "Analyst-identified gap"
        and not _contains_classic_topic_text(item.get("statement", ""))
    ]
    gaps = [
        {
            "finding_id": item["finding_id"],
            "statement": item["statement"],
            "status": item["status"],
        }
        for item in findings
        if item.get("kind") in {"Analyst-identified gap", "Conflict"}
    ]
    in_scope_ids = {item["finding_id"] for item in in_scope}
    configured_channels = (
        _extract_configured_channels(lisa_config) if lisa_config else []
    )
    evidenced_channels = _channel_findings(in_scope)

    def scoped_structured_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scoped: list[dict[str, Any]] = []
        for item in items:
            identifiers = [
                identifier
                for identifier in item.get("finding_ids", [])
                if identifier in in_scope_ids
            ]
            if not identifiers:
                continue
            candidate = copy.deepcopy(item)
            candidate["finding_ids"] = identifiers
            if _contains_classic_topic_text(
                json.dumps(candidate, ensure_ascii=False)
            ):
                continue
            scoped.append(candidate)
        return scoped

    sections = data.get("sections", {})
    return {
        "run_id": data.get("run_id", ""),
        "in_scope_findings": in_scope,
        "gaps_and_conflicts": gaps,
        "source_annotations": scoped_structured_items(
            data.get("source_annotations", [])
        ),
        "knowledge_sources": scoped_structured_items(
            data.get("knowledge_sources", [])
        ),
        "integrations": scoped_structured_items(data.get("integrations", [])),
        "agentic_behaviors": scoped_structured_items(
            data.get("agentic_behaviors", [])
        ),
        "goals": _section_items(sections.get("Goals", []), in_scope_ids),
        "metrics": _section_items(
            sections.get("Metrics and Baselines", []), in_scope_ids
        ),
        "data_sources": _section_items(
            sections.get("Data Sources", []), in_scope_ids
        ),
        "data_types": _section_items(
            sections.get("Data Types", []), in_scope_ids
        ),
        "solution_components": _section_items(
            sections.get("Solution Components", []), in_scope_ids
        ),
        "scope": _section_items(
            sections.get("Scope and Delivery Phases", []), in_scope_ids
        ),
        "lisa_config": {
            "path": str(lisa_config_path) if lisa_config_path else "",
            "sha256": _sha256_file(lisa_config_path) if lisa_config_path else "",
            "configured_channels": configured_channels,
        },
        "evidenced_channels": evidenced_channels,
            "platform_decision": {
                "path": str(PLATFORM_DECISION_PATH),
                "sha256": _sha256_file(PLATFORM_DECISION_PATH),
            },
    }


def _reference_cache_path(root: Path, reference_id: str) -> Path:
    return root / f"{reference_id}.json"


def _strip_html_excerpt(content: str) -> str:
    content = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    content = re.sub(r"<[^>]+>", " ", content)
    return re.sub(r"\s+", " ", html.unescape(content)).strip()[:2000]


def _refresh_reference(
    reference: dict[str, Any],
    cache_root: Path,
    reviewed_at: str,
    offline: bool,
    ttl_hours: float,
    packaged_verified: bool,
) -> dict[str, Any]:
    cache_path = _reference_cache_path(cache_root, reference["id"])
    cached = _json_load(cache_path) if cache_path.exists() else {}
    manifest_fingerprint = _canonical_hash(reference)
    cache_compatible = (
        cached.get("manifest_fingerprint") == manifest_fingerprint
    )
    result = {
        "id": reference["id"],
        "title": reference["title"],
        "url": reference["url"],
        "domain": reference["domain"],
        "required": bool(reference.get("required")),
        "reviewed_at": reviewed_at,
        "status": "not-retrieved",
        "etag": cached.get("etag", ""),
        "last_modified": cached.get("last_modified", ""),
        "content_sha256": cached.get("content_sha256", ""),
        "excerpt": cached.get("excerpt", ""),
        "limitation": "",
        "retrieved_at": cached.get("retrieved_at", ""),
        "manifest_fingerprint": manifest_fingerprint,
    }
    if offline:
        if packaged_verified:
            result["status"] = "packaged-verified"
            result["content_sha256"] = _canonical_hash(reference)
            result["retrieved_at"] = reviewed_at
        else:
            result["status"] = "failed"
            result["limitation"] = "No verified packaged or cached reference is available."
        return result
    if (
        cache_compatible
        and cached.get("retrieved_at")
        and cached.get("content_sha256")
    ):
        try:
            cached_at = datetime.fromisoformat(
                str(cached["retrieved_at"]).replace("Z", "+00:00")
            )
            if cached_at.tzinfo is None:
                cached_at = cached_at.astimezone()
            if (
                datetime.now().astimezone() - cached_at
            ).total_seconds() < ttl_hours * 3600:
                result.update(cached)
                result["reviewed_at"] = reviewed_at
                result["status"] = "fresh-cache"
                return result
        except ValueError:
            pass

    parsed = urllib.parse.urlparse(reference["url"])
    if parsed.scheme != "https" or parsed.hostname != "learn.microsoft.com":
        raise ClassifierError(
            f"Reference is not an official Microsoft Learn URL: {reference['url']}"
        )
    headers = {
        "User-Agent": "Microsoft-Scout-Complexity-Classifier/1.0",
        "Accept": "text/html",
    }
    if cache_compatible and cached.get("etag"):
        headers["If-None-Match"] = cached["etag"]
    if cache_compatible and cached.get("last_modified"):
        headers["If-Modified-Since"] = cached["last_modified"]
    request = urllib.request.Request(reference["url"], headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = response.read(512 * 1024)
            text = payload.decode(
                response.headers.get_content_charset() or "utf-8", errors="replace"
            )
            title_match = re.search(
                r"<title[^>]*>(.*?)</title>",
                text,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if title_match:
                result["title"] = re.sub(
                    r"\s+", " ", html.unescape(title_match.group(1))
                ).strip()
            result.update(
                {
                    "status": "retrieved",
                    "etag": response.headers.get("ETag", ""),
                    "last_modified": response.headers.get("Last-Modified", ""),
                    "content_sha256": _sha256_bytes(payload),
                    "excerpt": _strip_html_excerpt(text),
                    "retrieved_at": datetime.now().astimezone().isoformat(),
                }
            )
    except urllib.error.HTTPError as exc:
        if exc.code == 304 and cache_compatible:
            for key in (
                "title",
                "etag",
                "last_modified",
                "content_sha256",
                "excerpt",
            ):
                result[key] = cached.get(key, result.get(key, ""))
            result["status"] = "not-modified"
        elif cache_compatible:
            result["status"] = "cached-after-error"
            result["limitation"] = f"HTTP {exc.code} during conditional refresh."
        else:
            result["status"] = "failed"
            result["limitation"] = f"HTTP {exc.code} during retrieval."
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        if cache_compatible:
            result["status"] = "cached-after-error"
            result["limitation"] = f"Refresh failed: {type(exc).__name__}."
        else:
            result["status"] = "failed"
            result["limitation"] = f"Retrieval failed: {type(exc).__name__}."
    if result["status"] in {
        "retrieved",
        "not-modified",
        "cached-after-error",
    }:
        _atomic_write_json(cache_path, result)
    return result


def _reference_stage(reference_id: str) -> str:
    if reference_id in AGENT_FRAMEWORK_REFERENCE_IDS:
        return "agent-framework"
    if reference_id in FOUNDRY_REFERENCE_IDS:
        return "foundry"
    return "copilot"


def _refresh_references(
    root: Path, reviewed_at: str, offline: bool, research_stage: str
) -> list[dict[str, Any]]:
    manifest = _json_load(REFERENCE_MANIFEST_PATH)
    try:
        verified_at = datetime.fromisoformat(
            manifest["verified_at"].replace("Z", "+00:00")
        )
        if verified_at.tzinfo is None:
            verified_at = verified_at.astimezone()
        packaged_verified = (
            datetime.now().astimezone() - verified_at
        ).total_seconds() <= float(
            manifest["verification_max_age_days"]
        ) * 86400
    except (KeyError, ValueError):
        packaged_verified = False
    ttl_hours = float(manifest.get("refresh_ttl_hours", 24))
    maximum_stage = RESEARCH_ORDER[research_stage]
    references = [
        reference
        for reference in manifest["references"]
        if RESEARCH_ORDER[_reference_stage(reference["id"])] <= maximum_stage
    ]
    root.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        pending = {
            executor.submit(
                _refresh_reference,
                reference,
                root,
                reviewed_at,
                offline,
                ttl_hours,
                packaged_verified,
            ): reference
            for reference in references
        }
        for future in concurrent.futures.as_completed(pending):
            reference = pending[future]
            try:
                results[reference["id"]] = future.result()
            except Exception as exc:
                results[reference["id"]] = {
                    **reference,
                    "reviewed_at": reviewed_at,
                    "status": "failed",
                    "etag": "",
                    "last_modified": "",
                    "content_sha256": "",
                    "excerpt": "",
                    "limitation": f"Refresh worker failed: {type(exc).__name__}.",
                    "retrieved_at": "",
                    "manifest_fingerprint": _canonical_hash(reference),
                }
    ordered = [results[item["id"]] for item in references]
    failures = [
        item
        for item in ordered
        if item.get("required")
        and item["status"] == "failed"
    ]
    if failures:
        raise ClassifierError(
            "Required Microsoft references could not be reviewed: "
            + ", ".join(item["id"] for item in failures)
        )
    return ordered


def _grounded_item(
    name: str,
    basis: str,
    evidence_ids: list[str] | None = None,
    reference_ids: list[str] | None = None,
    source_refs: list[str] | None = None,
    implementation_tier: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "name": name,
        "selection_basis": basis,
        "evidence_ids": evidence_ids or [],
        "reference_ids": reference_ids or [],
        "source_refs": source_refs or [],
    }
    if implementation_tier:
        item["implementation_tier"] = implementation_tier
    return item


def _default_channel_items(summary: dict[str, Any]) -> list[dict[str, Any]]:
    configured = summary.get("lisa_config", {}).get("configured_channels", [])
    if configured:
        return [
            _grounded_item(
                name,
                "configured",
                reference_ids=[
                    "copilot-studio-channels",
                    "m365-declarative-agents",
                ],
                source_refs=[summary["lisa_config"]["path"]],
            )
            for name in configured
        ]
    evidenced = summary.get("evidenced_channels", [])
    if evidenced:
        return [
            _grounded_item(
                item["name"],
                "evidenced",
                evidence_ids=item["finding_ids"],
                reference_ids=["copilot-studio-channels"],
            )
            for item in evidenced
        ]
    return [
        _grounded_item(
            name,
            "default",
            reference_ids=[
                "copilot-studio-teams-channel"
                if name == "Microsoft Teams"
                else "m365-declarative-agents"
            ],
        )
        for name in DEFAULT_CONVERSATIONAL_CHANNELS
    ]


def _model_template(
    run_id: str, evidence_summary: dict[str, Any], research_stage: str
) -> dict[str, Any]:
    in_scope_findings = evidence_summary.get("in_scope_findings", [])
    default_capabilities = []
    for index, finding in enumerate(in_scope_findings, 1):
        default_capabilities.append(
            {
                "id": f"CAP-{index:03d}",
                "name": finding["statement"][:160],
                "requirement_ids": [finding["finding_id"]],
                "business_priority": "must",
                "business_weight": 5,
                "work_type": "adaptive-reasoning",
                "action_impact": "read-only",
                "dependencies": [],
                "component_ids": [],
                "implementation_status": "unknown",
                "coverage_factor": 0,
                "demonstration_factor": 0,
                "allowed_product": None,
                "harness": None,
                "implementation_method": "Resolve during architecture classification.",
                "supported_portion": "No supported portion has been validated yet.",
                "unsupported_portion": "Feasibility requires current product evidence.",
                "poc_treatment": "block",
                "build_owner": "unassigned",
                "build_contract": {
                    "inputs": [],
                    "outputs": [],
                    "authentication": "Not yet resolved.",
                    "authorization": "Not yet resolved.",
                    "approval_required": False,
                    "side_effects": "No action is permitted until resolved.",
                    "success_result": "Not yet defined.",
                    "partial_result": "Not yet defined.",
                    "error_result": "Report the unresolved capability.",
                    "timeout_behavior": "Stop without claiming success.",
                    "idempotency": "Not applicable until an action is selected.",
                    "configuration_refs": [],
                    "simulation_disclosure": None,
                },
                "verification_method": "Validate against current allowed-product capability evidence.",
                "confidence": "low",
            }
        )
    return {
        "schema_version": "3.0",
        "run_id": run_id,
        "research_stage": research_stage,
        "platform_assessment": {
            "copilot_studio_fit": "full",
            "cowork_fit": "not-assessed",
            "foundry_fit": "not-assessed",
            "agent_framework_fit": "not-assessed",
            "unmet_requirements": [],
            "decision_summary": "Assess every in-scope requirement against Copilot Studio, Power Platform, and Microsoft 365 capabilities before escalating research.",
        },
        "requirement_assessments": [],
        "agentic_platform": "Copilot Studio",
        "code_tier": "No-code",
        "harness": "Standard",
        "harness_rationale": "",
        "billing_implication": "",
        "delivery_assessment": {
            "allowed_tools": [
                "Microsoft Copilot Studio",
                "Microsoft 365 Copilot Chat",
                "Microsoft Cowork",
                "Microsoft Teams",
            ],
            "platform_gates": [],
            "candidate_scores": [],
            "solution_complexity": "Low",
            "capabilities": default_capabilities,
            "poc_scope": {
                "objective": "Demonstrate the validated customer journey using only allowed tools and clearly disclosed simulations.",
                "included_capability_ids": [],
                "excluded_capability_ids": [
                    item["id"] for item in default_capabilities
                ],
                "test_data_boundary": "Use approved non-production or synthetic test data only.",
            },
            "production_readiness_gaps": [],
        },
        "components": {
            "agents": [],
            "platform_capabilities": [
                _grounded_item(
                    "Copilot Studio generative orchestration and instructions",
                    "recommended",
                    reference_ids=[
                        "copilot-studio-fundamentals",
                        "copilot-studio-orchestration",
                        "copilot-studio-harnesses",
                        "copilot-studio-guidance",
                        "power-platform-well-architected",
                    ],
                    implementation_tier="No-code",
                )
            ],
            "knowledge_sources": [],
            "tools": [
                {
                    **_grounded_item(
                        "Grounded knowledge retrieval",
                        "recommended",
                        reference_ids=[
                            "copilot-studio-knowledge",
                            "copilot-studio-tools",
                        ],
                        implementation_tier="No-code",
                    ),
                    "integrability": "easily-integrable",
                    "implementation": "Configure the Copilot Studio knowledge capability and supported native action.",
                    "creation_method": "Native action",
                }
            ],
            "skills": [],
            "connected_agents": [],
            "triggers": [],
            "automation": [],
            "integration": [
                {
                    **_grounded_item(
                        "Microsoft 365 and Power Platform standard connectors",
                        "recommended",
                        reference_ids=[
                            "copilot-studio-tools",
                            "power-automate",
                        ],
                        implementation_tier="No-code",
                    ),
                    "method": "Native connector",
                    "integrability": "easily-integrable",
                }
            ],
            "data": [
                _grounded_item(
                    "Microsoft Dataverse solution configuration and operational state",
                    "recommended",
                    reference_ids=["dataverse"],
                    implementation_tier="No-code",
                )
            ],
            "authentication": {
                "platform": "Microsoft Entra ID",
                "tool": "Copilot Studio user authentication",
                "configuration": "Authenticate users with Microsoft Entra ID and use connector connection references for downstream actions.",
                "selection_basis": "mandatory-baseline",
                "evidence_ids": [],
                "reference_ids": [
                    "entra-id",
                    "copilot-studio-authentication"
                ],
                "source_refs": []
            },
            "authorization": {
                "platform": "Microsoft Entra ID and source-system permissions",
                "tool": "Copilot Studio and connector authorization",
                "configuration": "Apply least privilege, connection references, source permissions, and human approval for binding actions.",
                "selection_basis": "mandatory-baseline",
                "evidence_ids": [],
                "reference_ids": [
                    "entra-id",
                    "copilot-studio-authentication"
                ],
                "source_refs": []
            },
            "security_controls": [
                _grounded_item(
                    "Power Platform data policies and Microsoft Purview protection",
                    "mandatory-baseline",
                    reference_ids=["power-platform-dlp", "microsoft-purview"],
                    implementation_tier="No-code",
                )
            ],
            "governance_controls": [
                _grounded_item(
                    "Power Platform Managed Environment governance",
                    "mandatory-baseline",
                    reference_ids=["managed-environments", "power-platform-dlp"],
                    implementation_tier="No-code",
                )
            ],
            "alm": [
                _grounded_item(
                    "Power Platform solutions, environment variables, connection references, and deployment pipelines",
                    "mandatory-baseline",
                    reference_ids=["power-platform-alm"],
                    implementation_tier="No-code",
                )
            ],
            "communication_channels": _default_channel_items(evidence_summary),
        },
        "solution_topology": {
            "architecture_summary": "",
            "architecture_principles": [
                {
                    "dimension": "reusable",
                    "decision": "Prefer reusable Microsoft managed capabilities and shared solution components.",
                    "implementation": "Package shared connectors, actions, prompts, environment variables, and connection references for reuse.",
                    "reference_ids": [
                        "copilot-studio-guidance",
                        "power-platform-well-architected",
                        "power-platform-alm",
                    ],
                },
                {
                    "dimension": "modular",
                    "decision": "Separate channels, agent orchestration, tools, data, integrations, and cross-cutting controls.",
                    "implementation": "Use explicit contracts and independently deployable or configurable components.",
                    "reference_ids": [
                        "copilot-studio-guidance",
                        "power-platform-well-architected",
                    ],
                },
                {
                    "dimension": "reliable",
                    "decision": "Design observable failure boundaries and governed recovery behavior.",
                    "implementation": "Specify monitoring, retries, timeouts, idempotency, human escalation, and graceful degradation per interaction.",
                    "reference_ids": [
                        "copilot-studio-guidance",
                        "power-platform-well-architected",
                    ],
                },
                {
                    "dimension": "secure",
                    "decision": "Apply zero-trust identity, least privilege, data policies, and information protection.",
                    "implementation": "Use Microsoft Entra ID, source-system authorization, Power Platform data policies, and Microsoft Purview.",
                    "reference_ids": [
                        "entra-id",
                        "power-platform-dlp",
                        "microsoft-purview",
                    ],
                },
                {
                    "dimension": "scalable",
                    "decision": "Use managed services and stateless interfaces that scale independently.",
                    "implementation": "Separate agent orchestration from tools and data services, and define capacity, throttling, and concurrency controls.",
                    "reference_ids": [
                        "copilot-studio-guidance",
                        "power-platform-well-architected",
                    ],
                },
            ],
            "components": [],
            "relationships": [],
            "trust_boundaries": [],
            "environments": [],
            "sequence_flows": [],
        },
        "flags": {
            "requires_pro_code": False,
            "requires_custom_or_gateway": False,
            "uses_low_code": False,
            "autonomous_multistep": False,
            "uses_memory": False,
        },
        "justification_paragraphs": [],
        "gaps": [],
    }


def _validate_against_schema(
    value: dict[str, Any], schema_path: Path, label: str
) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise ClassifierError(
            "jsonschema is required; install the local-skills requirements.txt"
        ) from exc
    try:
        jsonschema.Draft202012Validator(_json_load(schema_path)).validate(value)
    except jsonschema.ValidationError as exc:
        location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
        raise ClassifierError(
            f"{label} schema error at {location}: {exc.message}"
        ) from exc


def _schema_validate(model: dict[str, Any]) -> None:
    _validate_against_schema(
        model, MODEL_SCHEMA_PATH, "Classification model"
    )


def _cache_key(
    input_path: Path,
    references: list[dict[str, Any]],
    lisa_config_sha256: str = "",
    research_assessment_hashes: list[str] | None = None,
) -> str:
    reference_signature = [
        {
            "id": item["id"],
            "url": item["url"],
            "etag": item.get("etag", ""),
            "last_modified": item.get("last_modified", ""),
            "content_sha256": item.get("content_sha256", ""),
            "semantic_sha256": _sha256_bytes(
                (
                    f"{item.get('title', '')}|{item.get('excerpt', '')}"
                ).encode("utf-8")
            ),
        }
        for item in references
    ]
    return _canonical_hash(
        {
            "version": CACHE_VERSION,
            "skill_version": VERSION,
            "script_sha256": _sha256_file(Path(__file__).resolve()),
            "input_path": str(input_path).casefold(),
            "input_sha256": _sha256_file(input_path),
            "lisa_config_sha256": lisa_config_sha256,
            "research_assessment_hashes": research_assessment_hashes or [],
            "rules_sha256": _sha256_file(RULES_PATH),
            "model_schema_sha256": _sha256_file(MODEL_SCHEMA_PATH),
            "output_schema_sha256": _sha256_file(OUTPUT_SCHEMA_PATH),
            "assessment_schema_sha256": _sha256_file(ASSESSMENT_SCHEMA_PATH),
            "template_sha256": _sha256_file(TEMPLATE_PATH),
            "reference_manifest_sha256": _sha256_file(REFERENCE_MANIFEST_PATH),
                        "platform_decision_sha256": _sha256_file(PLATFORM_DECISION_PATH),
            "references": reference_signature,
        }
    )


def _resource_hashes() -> dict[str, str]:
    return {
        "script": _sha256_file(Path(__file__).resolve()),
        "reference_manifest": _sha256_file(REFERENCE_MANIFEST_PATH),
        "rules": _sha256_file(RULES_PATH),
        "model_schema": _sha256_file(MODEL_SCHEMA_PATH),
        "output_schema": _sha256_file(OUTPUT_SCHEMA_PATH),
        "assessment_schema": _sha256_file(ASSESSMENT_SCHEMA_PATH),
        "template": _sha256_file(TEMPLATE_PATH),
        "platform_decision": _sha256_file(PLATFORM_DECISION_PATH),
    }


def _load_model_cache(path: Path, key: str, run_id: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    cached = _json_load(path)
    model = cached.get("model")
    if (
        cached.get("version") != CACHE_VERSION
        or cached.get("cache_key") != key
        or not isinstance(model, dict)
        or cached.get("model_sha256") != _canonical_hash(model)
    ):
        return None
    reused = copy.deepcopy(model)
    reused["run_id"] = run_id
    try:
        _schema_validate(reused)
    except ClassifierError:
        return None
    return reused


def _prepare(args: argparse.Namespace) -> int:
    started_epoch = time.time()
    started_at = _authoritative_local_time(args.local_time)
    try:
        paths = resolve_lisa_config(Path(args.config))
        input_path = latest_file(
            paths.analysis,
            "requirement-analysis_*.json",
            "requirement-analysis JSON",
            r"requirement-analysis_[0-9]{8}_[0-9]{6}(?:_[0-9]{3})?\.json",
        )
    except LisaConfigError as exc:
        raise ClassifierError(str(exc)) from exc
    data = _json_load(input_path)
    _validate_requirement_analysis(input_path, data)

    temp_output = paths.output.resolve()
    _assert_no_link_components(temp_output)
    classification_root = canonical_stage_root(
        temp_output, ARTIFACT_CONTRACT["rootFolder"]
    )
    _assert_no_link_components(classification_root)
    if classification_root.parent != temp_output.resolve():
        raise ClassifierError(
            "classification must be a direct child of tempOutputPath"
        )

    timestamp = _timestamp_for_output(classification_root, started_at)
    input_hash = _sha256_file(input_path)
    run_id = f"CC-{timestamp}-{input_hash[:8].upper()}"
    internal = classification_root / ".complexity-classifier"
    run_dir = internal / "runs" / run_id
    reference_cache = internal / "reference-cache"
    model_cache_root = internal / "classification-cache" / f"v{CACHE_VERSION}"
    for directory in (run_dir, reference_cache, model_cache_root):
        _safe_write_path(directory, classification_root)
        directory.mkdir(parents=True, exist_ok=True)

    lisa_config_path = _find_lisa_config(input_path, temp_output)
    lisa_config = _json_load(lisa_config_path) if lisa_config_path else None
    research_stage = "copilot"
    references = _refresh_references(
        reference_cache,
        started_at.date().isoformat(),
        args.offline,
        research_stage,
    )
    evidence_summary = _build_evidence_summary(
        data, lisa_config_path, lisa_config
    )
    lisa_config_sha256 = (
        _sha256_file(lisa_config_path) if lisa_config_path else ""
    )
    cache_key = _cache_key(
        input_path, references, lisa_config_sha256
    )
    cache_path = model_cache_root / f"{cache_key}.json"
    reused_model = _load_model_cache(cache_path, cache_key, run_id)

    run_path = run_dir / "run.json"
    summary_path = run_dir / "evidence-summary.json"
    references_path = run_dir / "references.json"
    draft_path = run_dir / "classification-model.draft.json"
    reused_path = run_dir / "classification-model.reused.json"
    target_markdown = (
        classification_root / f"complexity-classification_{timestamp}.md"
    )
    target_json = target_markdown.with_suffix(".json")
    for target in (target_markdown, target_json):
        _safe_write_path(target, classification_root)

    run = {
        "schema_version": "1.0",
        "skill_version": VERSION,
        "run_id": run_id,
        "started_at_local": started_at.isoformat(),
        "started_epoch": started_epoch,
        "input_path": str(input_path),
        "input_sha256": input_hash,
        "temp_output_path": str(temp_output.resolve()),
        "classification_root": str(classification_root),
        "run_directory": str(run_dir),
        "evidence_summary_path": str(summary_path),
        "references_path": str(references_path),
        "reference_cache_path": str(reference_cache.resolve()),
        "model_draft_path": str(draft_path),
        "reused_model_path": str(reused_path) if reused_model else "",
        "target_markdown_path": str(target_markdown),
        "target_json_path": str(target_json),
        "cache_key": cache_key,
        "cache_path": str(cache_path),
        "classification_cache_hit": reused_model is not None,
        "research_stage": research_stage,
        "lisa_config_path": str(lisa_config_path) if lisa_config_path else "",
        "lisa_config_sha256": lisa_config_sha256,
        "offline": bool(args.offline),
        "research_assessments": [],
        "reference_failures": sum(
            1 for item in references if item["status"] == "failed"
        ),
        "resource_hashes": _resource_hashes(),
        "status": "prepared",
    }
    _atomic_write_json(summary_path, evidence_summary)
    _atomic_write_json(references_path, references)
    _atomic_write_json(
        draft_path,
        _model_template(run_id, evidence_summary, research_stage),
    )
    if reused_model:
        _atomic_write_json(reused_path, reused_model)
    run["evidence_summary_sha256"] = _sha256_file(summary_path)
    run["references_sha256"] = _sha256_file(references_path)
    _atomic_write_json(run_path, run)
    print(
        json.dumps(
            {
                "status": "prepared",
                "run": str(run_path),
                "evidence_summary": str(summary_path),
                "references": str(references_path),
                "model_draft": str(draft_path),
                "classification_cache_hit": run["classification_cache_hit"],
                "reused_model": run["reused_model_path"],
                "target_markdown": str(target_markdown),
                "reference_failures": run["reference_failures"],
                "research_stage": research_stage,
                "lisa_config": run["lisa_config_path"],
            },
            indent=2,
        )
    )
    return 0


def _load_run(path: Path) -> dict[str, Any]:
    run = _json_load(path)
    run_dir = Path(run.get("run_directory", "")).resolve()
    if path.resolve().parent != run_dir or path.name != "run.json":
        raise ClassifierError("Run file is not the expected run.json")
    classification_root = Path(run["classification_root"]).resolve()
    if classification_root.name != ARTIFACT_CONTRACT["rootFolder"]:
        raise ClassifierError("Run output root is not classification")
    if classification_root.parent != Path(run["temp_output_path"]).resolve():
        raise ClassifierError("classification is not directly under tempOutputPath")
    if run.get("resource_hashes") != _resource_hashes():
        raise ClassifierError(
            "Classifier resources changed after preparation; start a new run"
        )
    if not _is_within(run_dir, classification_root):
        raise ClassifierError("Run directory escapes classification")
    reference_cache = Path(run.get("reference_cache_path", "")).resolve()
    expected_reference_cache = (
        classification_root / ".complexity-classifier" / "reference-cache"
    ).resolve()
    if reference_cache != expected_reference_cache or not _is_within(
        reference_cache, classification_root
    ):
        raise ClassifierError("Reference cache path is inconsistent")
    expected_artifacts = {
        "evidence_summary_path": (
            "evidence-summary.json",
            "evidence_summary_sha256",
        ),
        "references_path": ("references.json", "references_sha256"),
        "model_draft_path": ("classification-model.draft.json", None),
    }
    for key, (expected_name, hash_key) in expected_artifacts.items():
        artifact = Path(run.get(key, "")).resolve()
        if not _is_within(artifact, run_dir) or artifact.name != expected_name:
            raise ClassifierError(f"{key} escapes or mismatches the run directory")
        if not artifact.exists():
            raise ClassifierError(f"Prepared artifact is missing: {artifact}")
        if hash_key and _sha256_file(artifact) != run.get(hash_key):
            raise ClassifierError(f"Prepared artifact changed after preparation: {artifact}")
    input_path = Path(run["input_path"])
    if not input_path.exists() or _sha256_file(input_path) != run["input_sha256"]:
        raise ClassifierError(
            "Requirement analysis changed after preparation; start a new run"
        )
    config_path = run.get("lisa_config_path", "")
    if config_path:
        config = Path(config_path)
        if not config.exists() or _sha256_file(config) != run.get("lisa_config_sha256"):
            raise ClassifierError(
                "lisa-config.json changed after preparation; start a new run"
            )
    for assessment in run.get("research_assessments", []):
        assessment_path = Path(assessment["path"]).resolve()
        if not _is_within(assessment_path, run_dir):
            raise ClassifierError("Persisted research assessment escapes run directory")
        if (
            not assessment_path.exists()
            or _sha256_file(assessment_path) != assessment["sha256"]
        ):
            raise ClassifierError(
                "Persisted research assessment changed after expansion"
            )
    return run


def _expand_research(args: argparse.Namespace) -> int:
    run_path = Path(args.run).resolve()
    run = _load_run(run_path)
    if run.get("status") != "prepared":
        raise ClassifierError("Only prepared runs can expand research")
    current = run["research_stage"]
    target = args.stage
    if RESEARCH_ORDER[target] != RESEARCH_ORDER[current] + 1:
        raise ClassifierError(
            f"Research must expand sequentially from {current} to the next stage"
        )
    assessment_path = Path(args.assessment).resolve()
    run_dir = Path(run["run_directory"]).resolve()
    if not _is_within(assessment_path, run_dir):
        raise ClassifierError(
            "Research assessment must be stored inside the run directory"
        )
    assessment = _json_load(assessment_path)
    _validate_against_schema(
        assessment, ASSESSMENT_SCHEMA_PATH, "Research assessment"
    )
    if assessment["run_id"] != run["run_id"]:
        raise ClassifierError("Research assessment run_id does not match")
    if assessment["stage"] != current:
        raise ClassifierError(
            f"Research assessment stage must be {current}"
        )
    if assessment["fit"] == "full":
        raise ClassifierError(
            f"{current} fully satisfies the requirements; later-platform research is prohibited"
        )
    summary = _json_load(Path(run["evidence_summary_path"]))
    in_scope_ids = {
        item["finding_id"] for item in summary["in_scope_findings"]
    }
    assessment_ids = {
        identifier
        for item in assessment["unmet_requirements"]
        for identifier in item["evidence_ids"]
    }
    unknown_ids = assessment_ids - in_scope_ids
    if unknown_ids:
        raise ClassifierError(
            f"Research assessment cites non-scope IDs: {sorted(unknown_ids)}"
        )
    if current == "foundry":
        copilot_assessment = next(
            (
                item
                for item in run.get("research_assessments", [])
                if item["stage"] == "copilot"
            ),
            None,
        )
        if not copilot_assessment:
            raise ClassifierError(
                "Foundry assessment requires the persisted Copilot assessment"
            )
        copilot_unmet_ids = {
            identifier
            for item in copilot_assessment["unmet_requirements"]
            for identifier in item["evidence_ids"]
        }
        if not assessment_ids.issubset(copilot_unmet_ids):
            raise ClassifierError(
                "Foundry unmet requirements must descend from Copilot unmet requirements"
            )
    persisted_assessment = run_dir / f"research-assessment-{current}.json"
    _atomic_write_json(persisted_assessment, assessment)
    references = _refresh_references(
        Path(run["reference_cache_path"]),
        datetime.fromisoformat(run["started_at_local"]).date().isoformat(),
        bool(run.get("offline")),
        target,
    )
    references_path = Path(run["references_path"])
    _atomic_write_json(references_path, references)
    input_path = Path(run["input_path"])
    cache_key = _cache_key(
        input_path,
        references,
        run.get("lisa_config_sha256", ""),
        [
            item["sha256"]
            for item in list(run.get("research_assessments", []))
            + [
                {
                    "sha256": _sha256_file(persisted_assessment)
                }
            ]
        ],
    )
    cache_root = (
        Path(run["classification_root"])
        / ".complexity-classifier"
        / "classification-cache"
        / f"v{CACHE_VERSION}"
    )
    cache_path = cache_root / f"{cache_key}.json"
    reused_path = Path(run["run_directory"]) / "classification-model.reused.json"
    reused_model = _load_model_cache(
        cache_path, cache_key, run["run_id"]
    )
    draft_path = Path(run["model_draft_path"])
    assessments = list(run.get("research_assessments", []))
    assessments.append(
        {
            "stage": current,
            "path": str(persisted_assessment),
            "sha256": _sha256_file(persisted_assessment),
            "fit": assessment["fit"],
            "unmet_requirements": assessment["unmet_requirements"],
            "summary": assessment["summary"],
        }
    )
    draft = _model_template(run["run_id"], summary, target)
    copilot_assessment = next(
        (item for item in assessments if item["stage"] == "copilot"),
        None,
    )
    foundry_assessment = next(
        (item for item in assessments if item["stage"] == "foundry"),
        None,
    )
    if copilot_assessment:
        draft["platform_assessment"]["copilot_studio_fit"] = copilot_assessment["fit"]
        draft["platform_assessment"]["unmet_requirements"] = [
            _grounded_item(
                f"{item['name']}: {item['reason']}",
                "evidenced",
                evidence_ids=item["evidence_ids"],
            )
            for item in copilot_assessment["unmet_requirements"]
        ]
    if foundry_assessment:
        draft["platform_assessment"]["foundry_fit"] = foundry_assessment["fit"]
        draft["platform_assessment"]["unmet_requirements"] = [
            _grounded_item(
                f"{item['name']}: {item['reason']}",
                "evidenced",
                evidence_ids=item["evidence_ids"],
            )
            for item in foundry_assessment["unmet_requirements"]
        ]
    _atomic_write_json(
        draft_path,
        draft,
    )
    if reused_model:
        _atomic_write_json(reused_path, reused_model)
    elif reused_path.exists():
        reused_path.unlink()
    run.update(
        {
            "research_stage": target,
            "cache_key": cache_key,
            "cache_path": str(cache_path),
            "classification_cache_hit": reused_model is not None,
            "reused_model_path": str(reused_path) if reused_model else "",
            "references_sha256": _sha256_file(references_path),
            "reference_failures": sum(
                1 for item in references if item["status"] == "failed"
            ),
            "research_assessments": assessments,
        }
    )
    _atomic_write_json(run_path, run)
    print(
        json.dumps(
            {
                "status": "research-expanded",
                "research_stage": target,
                "references": str(references_path),
                "model_draft": str(draft_path),
                "classification_cache_hit": run["classification_cache_hit"],
                "reused_model": run["reused_model_path"],
                "reference_failures": run["reference_failures"],
            },
            indent=2,
        )
    )
    return 0


def _collect_component_evidence_ids(model: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    components = model["components"]
    for key in (
        "agents",
        "platform_capabilities",
        "knowledge_sources",
        "skills",
        "connected_agents",
        "triggers",
        "automation",
        "integration",
        "data",
        "security_controls",
        "governance_controls",
        "alm",
        "communication_channels",
    ):
        for item in components[key]:
            values.update(item["evidence_ids"])
    for item in components["tools"]:
        values.update(item["evidence_ids"])
    for key in ("authentication", "authorization"):
        values.update(components[key]["evidence_ids"])
    topology = model["solution_topology"]
    for key in ("components", "relationships", "trust_boundaries", "sequence_flows"):
        for item in topology[key]:
            values.update(item["evidence_ids"])
    return values


def _collect_component_reference_ids(model: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    components = model["components"]
    for key in (
        "agents",
        "platform_capabilities",
        "knowledge_sources",
        "skills",
        "connected_agents",
        "triggers",
        "automation",
        "integration",
        "data",
        "security_controls",
        "governance_controls",
        "alm",
        "communication_channels",
    ):
        for item in components[key]:
            values.update(item["reference_ids"])
    for item in components["tools"]:
        values.update(item["reference_ids"])
    for key in ("authentication", "authorization"):
        values.update(components[key]["reference_ids"])
    topology = model["solution_topology"]
    for key in ("components", "relationships", "trust_boundaries", "sequence_flows"):
        for item in topology[key]:
            values.update(item["reference_ids"])
    for item in topology["architecture_principles"]:
        values.update(item["reference_ids"])
    for item in topology["environments"]:
        values.update(item["reference_ids"])
    for item in model["gaps"]:
        values.update(item["reference_ids"])
    for item in model["platform_assessment"]["unmet_requirements"]:
        values.update(item["reference_ids"])
    return values


def _collect_gap_evidence_ids(model: dict[str, Any]) -> set[str]:
    return {
        identifier
        for item in model["gaps"]
        for identifier in item["evidence_ids"]
    }


def _collect_assessment_evidence_ids(model: dict[str, Any]) -> set[str]:
    return {
        identifier
        for item in model["platform_assessment"]["unmet_requirements"]
        for identifier in item["evidence_ids"]
    }


def _contains_classic_topic_text(value: str) -> bool:
    return bool(
        re.search(
            r"\b(classic\s+(copilot\s+studio\s+)?topics?|"
            r"copilot\s+studio\s+topics?|topic-based\s+authoring)\b",
            value,
            flags=re.IGNORECASE,
        )
    )


def _contains_topic(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_contains_topic(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_topic(item) for item in value)
    if isinstance(value, str):
        return _contains_classic_topic_text(value)
    return False


def _classification_inventory_names(model: dict[str, Any]) -> set[str]:
    components = model["components"]
    names = {
        item["name"]
        for key in (
            "agents",
            "platform_capabilities",
            "knowledge_sources",
            "tools",
            "skills",
            "connected_agents",
            "triggers",
            "automation",
            "integration",
            "data",
            "security_controls",
            "governance_controls",
            "alm",
            "communication_channels",
        )
        for item in components[key]
    }
    for key in ("authentication", "authorization"):
        names.update(
            {
                components[key]["platform"],
                components[key]["tool"],
            }
        )
    return {name for name in names if name}


def _validate_solution_topology(model: dict[str, Any]) -> None:
    topology = model["solution_topology"]
    components = model["components"]
    topology_components = topology["components"]
    component_ids = [item["id"] for item in topology_components]
    if len(component_ids) != len(set(component_ids)):
        raise ClassifierError("Solution topology component IDs must be unique")
    component_names = [item["name"].strip().casefold() for item in topology_components]
    if len(component_names) != len(set(component_names)):
        raise ClassifierError("Solution topology component names must be unique")
    known_ids = set(component_ids)
    by_id = {item["id"]: item for item in topology_components}

    generic_names = {
        "api",
        "custom api",
        "data store",
        "database",
        "generic",
        "integration",
        "integration layer",
        "other",
        "platform",
        "service",
        "storage",
        "tbd",
        "tool",
        "unknown",
        "unspecified",
        "workflow",
    }
    generic_components = [
        item["id"]
        for item in topology_components
        if item["name"].strip().casefold() in generic_names
        or item["product_service"].strip().casefold() in generic_names
    ]
    if generic_components:
        raise ClassifierError(
            "Topology components require exact product/service names rather than "
            f"generic labels: {sorted(generic_components)}"
        )

    required_categories = {
        "actor",
        "agent",
        "agent-platform",
        "tool",
        "data-store",
        "identity",
        "security",
        "governance",
        "alm",
        "monitoring",
    }
    if components["communication_channels"]:
        required_categories.add("channel")
    if components["knowledge_sources"]:
        required_categories.add("knowledge-source")
    if components["triggers"] or components["automation"]:
        required_categories.add("automation")
    if components["integration"]:
        required_categories.add("integration")
    present_categories = {item["category"] for item in topology_components}
    missing_categories = required_categories - present_categories
    if missing_categories:
        raise ClassifierError(
            "Solution topology is missing required architecture categories: "
            f"{sorted(missing_categories)}"
        )
    microsoft_tokens = (
        "microsoft",
        "azure",
        "copilot studio",
        "power platform",
        "power automate",
        "dataverse",
        "sharepoint",
        "teams",
        "entra",
        "purview",
        "application insights",
    )
    non_microsoft_components = [
        item["id"]
        for item in topology_components
        if item["component_type"] not in {"human", "external"}
        and not any(
            token in item["product_service"].casefold()
            for token in microsoft_tokens
        )
    ]
    if non_microsoft_components:
        raise ClassifierError(
            "Managed, configurable, and deployable topology components must name "
            "their Microsoft implementation service: "
            f"{sorted(non_microsoft_components)}"
        )

    platform_components = [
        item
        for item in topology_components
        if item["category"] == "agent-platform"
    ]
    if not any(
        model["agentic_platform"].casefold()
        in item["product_service"].casefold()
        for item in platform_components
    ):
        raise ClassifierError(
            "The topology must explicitly name the selected agentic platform as "
            "an agent-platform component"
        )

    inventory_names = _classification_inventory_names(model)
    mapped_inventory: dict[str, list[str]] = {}
    for item in topology_components:
        for name in item["inventory_names"]:
            if name not in inventory_names:
                raise ClassifierError(
                    f"Topology component '{item['id']}' maps unknown inventory name: {name}"
                )
            mapped_inventory.setdefault(name, []).append(item["id"])
    missing_inventory = inventory_names - set(mapped_inventory)
    duplicate_inventory = {
        name: identifiers
        for name, identifiers in mapped_inventory.items()
        if len(identifiers) != 1
    }
    if missing_inventory:
        raise ClassifierError(
            "Every classified component must map to the solution topology; "
            f"missing={sorted(missing_inventory)}"
        )
    if duplicate_inventory:
        raise ClassifierError(
            "Each classified component must map to exactly one topology component; "
            f"duplicates={duplicate_inventory}"
        )

    relationship_ids = [item["id"] for item in topology["relationships"]]
    if len(relationship_ids) != len(set(relationship_ids)):
        raise ClassifierError("Solution topology relationship IDs must be unique")
    for relationship in topology["relationships"]:
        if (
            relationship["source_id"] not in known_ids
            or relationship["target_id"] not in known_ids
        ):
            raise ClassifierError(
                "Topology relationship references an unknown component: "
                f"{relationship['source_id']} -> {relationship['target_id']}"
            )
        if relationship["source_id"] == relationship["target_id"]:
            raise ClassifierError(
                "Topology architecture relationships cannot be self-referential"
            )

    relationship_types = {
        item["relationship_type"] for item in topology["relationships"]
    }
    mandatory_relationship_types = {
        "authenticates",
        "authorizes",
        "protects",
        "governs",
        "deploys",
        "monitors",
    }
    missing_relationship_types = (
        mandatory_relationship_types - relationship_types
    )
    if missing_relationship_types:
        raise ClassifierError(
            "The topology is missing required cross-cutting relationships: "
            f"{sorted(missing_relationship_types)}"
        )
    category_by_id = {
        item["id"]: item["category"] for item in topology_components
    }
    category_relationships = {
        "authenticates": "identity",
        "authorizes": "identity",
        "protects": "security",
        "governs": "governance",
        "deploys": "alm",
        "monitors": "monitoring",
    }
    for relationship_type, category in category_relationships.items():
        if not any(
            item["relationship_type"] == relationship_type
            and category
            in {
                category_by_id[item["source_id"]],
                category_by_id[item["target_id"]],
            }
            for item in topology["relationships"]
        ):
            raise ClassifierError(
                f"Relationship type '{relationship_type}' must connect the "
                f"corresponding '{category}' component"
            )
    if not any(
        item["relationship_type"] in {"reads", "writes"}
        and {
            category_by_id[item["source_id"]],
            category_by_id[item["target_id"]],
        }
        & {"data-source", "data-store"}
        for item in topology["relationships"]
    ):
        raise ClassifierError(
            "A read or write relationship must connect an explicit data source or store"
        )
    connected_component_ids = {
        identifier
        for item in topology["relationships"]
        for identifier in (item["source_id"], item["target_id"])
    }
    orphaned_components = known_ids - connected_component_ids
    if orphaned_components:
        raise ClassifierError(
            "Every topology component must participate in an explicit relationship; "
            f"orphaned={sorted(orphaned_components)}"
        )
    category_reference_groups = {
        "identity": {
            "entra-id",
            "copilot-studio-authentication",
            "azure-rbac",
            "cowork-get-started",
        },
        "security": {
            "power-platform-dlp",
            "microsoft-purview",
            "azure-key-vault",
            "azure-policy",
            "cowork-overview",
            "cowork-get-started",
        },
        "governance": {
            "managed-environments",
            "power-platform-dlp",
            "azure-policy",
            "cowork-overview",
            "cowork-customize",
        },
        "alm": {
            "power-platform-alm",
            "power-platform-pipelines",
            "azure-pipelines",
            "cowork-customize",
        },
        "monitoring": {
            "copilot-studio-analytics",
            "application-insights",
            "azure-monitor",
            "power-platform-well-architected",
            "cowork-overview",
        },
        "data-store": {
            "dataverse",
            "copilot-studio-sharepoint",
            "azure-sql-database",
            "azure-storage",
            "azure-cosmos-db",
            "cowork-overview",
        },
    }
    for category, required_references in category_reference_groups.items():
        category_references = {
            reference
            for item in topology_components
            if item["category"] == category
            for reference in item["reference_ids"]
        }
        if not (required_references & category_references):
            raise ClassifierError(
                f"Topology category '{category}' must cite applicable Microsoft "
                f"documentation: {sorted(required_references)}"
            )

    actor_ids = {
        item["id"] for item in topology_components if item["category"] == "actor"
    }
    channel_ids = {
        item["id"] for item in topology_components if item["category"] == "channel"
    }
    agent_ids = {
        item["id"] for item in topology_components if item["category"] == "agent"
    }
    if channel_ids:
        actor_to_channel = {
            item["target_id"]
            for item in topology["relationships"]
            if item["source_id"] in actor_ids
            and item["target_id"] in channel_ids
            and item["relationship_type"] == "communicates"
        }
        channel_to_agent = {
            item["source_id"]
            for item in topology["relationships"]
            if item["source_id"] in channel_ids
            and item["target_id"] in agent_ids
            and item["relationship_type"] == "publishes-to"
        }
        if (
            not channel_ids.issubset(actor_to_channel)
            or not channel_ids.issubset(channel_to_agent)
        ):
            raise ClassifierError(
                "Every conversational channel must be wired as Actor -> Channel -> Agent"
            )

    if components["triggers"]:
        trigger_names = {item["name"] for item in components["triggers"]}
        trigger_component_ids = {
            item["id"]
            for item in topology_components
            if trigger_names & set(item["inventory_names"])
        }
        wired_trigger_ids = {
            item["source_id"]
            for item in topology["relationships"]
            if item["relationship_type"] == "triggers"
            and item["target_id"] in agent_ids
        }
        if trigger_component_ids - wired_trigger_ids:
            raise ClassifierError(
                "Every invocation trigger must explicitly target its agent in the topology"
            )

    principle_dimensions = [
        item["dimension"] for item in topology["architecture_principles"]
    ]
    required_dimensions = {
        "reusable",
        "modular",
        "reliable",
        "secure",
        "scalable",
    }
    if set(principle_dimensions) != required_dimensions or len(
        principle_dimensions
    ) != len(required_dimensions):
        raise ClassifierError(
            "Architecture principles must cover reusable, modular, reliable, "
            "secure, and scalable exactly once"
        )

    trust_ids = [item["id"] for item in topology["trust_boundaries"]]
    if len(trust_ids) != len(set(trust_ids)):
        raise ClassifierError("Trust-boundary IDs must be unique")
    for boundary in topology["trust_boundaries"]:
        unknown = set(boundary["component_ids"]) - known_ids
        if unknown:
            raise ClassifierError(
                f"Trust boundary '{boundary['id']}' references unknown components: "
                f"{sorted(unknown)}"
            )

    environment_names = [item["name"] for item in topology["environments"]]
    if set(environment_names) != {"Development", "Test", "Production"} or len(
        environment_names
    ) != 3:
        raise ClassifierError(
            "Environment topology must define Development, Test, and Production exactly once"
        )
    for environment in topology["environments"]:
        unknown = set(environment["component_ids"]) - known_ids
        if unknown:
            raise ClassifierError(
                f"Environment '{environment['name']}' references unknown components: "
                f"{sorted(unknown)}"
            )

    sequence_ids = [item["id"] for item in topology["sequence_flows"]]
    sequence_orders = [item["order"] for item in topology["sequence_flows"]]
    if len(sequence_ids) != len(set(sequence_ids)):
        raise ClassifierError("Sequence-flow IDs must be unique")
    if sequence_orders != list(range(1, len(sequence_orders) + 1)):
        raise ClassifierError(
            "Sequence-flow order must be contiguous and already sorted from one"
        )
    sequence_participants: set[str] = set()
    architecture_pairs = {
        (item["source_id"], item["target_id"])
        for item in topology["relationships"]
    }
    bidirectional_pairs = {
        (item["target_id"], item["source_id"])
        for item in topology["relationships"]
        if item["direction"] == "bidirectional"
    }
    for flow in topology["sequence_flows"]:
        if flow["source_id"] not in known_ids or flow["target_id"] not in known_ids:
            raise ClassifierError(
                "Sequence flow references an unknown component: "
                f"{flow['source_id']} -> {flow['target_id']}"
            )
        if (
            flow["message_type"] == "self"
            and flow["source_id"] != flow["target_id"]
        ):
            raise ClassifierError("Self sequence flows must target their source")
        if (
            flow["message_type"] != "self"
            and flow["source_id"] == flow["target_id"]
        ):
            raise ClassifierError(
                "Only self sequence flows can reference the same component"
            )
        if flow["message_type"] != "self" and (
            flow["source_id"],
            flow["target_id"],
        ) not in (architecture_pairs | bidirectional_pairs):
            raise ClassifierError(
                "Every non-self sequence interaction must be represented by an "
                "architecture relationship: "
                f"{flow['source_id']} -> {flow['target_id']}"
            )
        sequence_participants.update((flow["source_id"], flow["target_id"]))
    if len(sequence_participants) > 8:
        raise ClassifierError(
            "The architecture-ready sequence contract supports at most eight participants"
        )
    phases = {item["phase"] for item in topology["sequence_flows"]}
    if "Authentication" not in phases or "Response" not in phases:
        raise ClassifierError(
            "Sequence flows must include explicit Authentication and Response phases"
        )


def _validate_delivery_assessment(
    model: dict[str, Any],
    in_scope_ids: set[str],
    consulted_reference_ids: set[str],
    delegated_personal_required: bool,
    cowork_skill_required: bool,
    cowork_plugin_required: bool,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    delivery = model["delivery_assessment"]
    capabilities = delivery["capabilities"]
    capability_ids = [item["id"] for item in capabilities]
    if len(capability_ids) != len(set(capability_ids)):
        raise ClassifierError("Delivery capability IDs must be unique")
    known_capability_ids = set(capability_ids)
    topology_component_ids = {
        item["id"] for item in model["solution_topology"]["components"]
    }
    required_gates = {
        "product-availability",
        "allowed-tool-compliance",
        "authentication",
        "least-privilege",
        "test-data",
        "action-control",
        "simulation-disclosure",
        "auditability",
        "builder-path",
    }
    gate_keys = [
        (item["product"], item["gate"]) for item in delivery["platform_gates"]
    ]
    if len(gate_keys) != len(set(gate_keys)):
        raise ClassifierError("Platform gate assessments must be unique per product and gate")
    for gate in delivery["platform_gates"]:
        unknown_gate_references = set(gate["evidence_refs"]) - consulted_reference_ids
        if unknown_gate_references:
            raise ClassifierError(
                f"Gate {gate['product']} / {gate['gate']} cites unconsulted evidence: "
                f"{sorted(unknown_gate_references)}"
            )
        if gate["result"] == "exception-required" and not gate["exception_owner"]:
            raise ClassifierError(
                f"Gate {gate['product']} / {gate['gate']} requires an exception owner"
            )
    expected_category_weights = {
        "security-data-control": 20,
        "safety-action-control": 15,
        "functional-reasoning-fit": 15,
        "data-tools-channels-integration": 15,
        "reliability-observability-support": 12,
        "engineering-alm-portability": 10,
        "cost-capacity-effort": 8,
        "availability-maturity-risk": 5,
    }
    score_products = [item["product"] for item in delivery["candidate_scores"]]
    if len(score_products) != len(set(score_products)):
        raise ClassifierError("Candidate platform scores must be unique per product")
    platform_scores = []
    for candidate in delivery["candidate_scores"]:
        categories = candidate["categories"]
        category_names = [item["category"] for item in categories]
        if set(category_names) != set(expected_category_weights) or len(category_names) != len(set(category_names)):
            raise ClassifierError(
                f"Candidate '{candidate['product']}' must score every platform category exactly once"
            )
        for category in categories:
            if category["weight"] != expected_category_weights[category["category"]]:
                raise ClassifierError(
                    f"Candidate '{candidate['product']}' has an invalid weight for {category['category']}"
                )
            unknown_score_references = set(category["evidence_refs"]) - consulted_reference_ids
            if unknown_score_references:
                raise ClassifierError(
                    f"Candidate '{candidate['product']}' score cites unconsulted evidence: "
                    f"{sorted(unknown_score_references)}"
                )
        weighted_score = sum(
            category["score"] / 5 * category["weight"]
            for category in categories
        )
        platform_scores.append(
            {
                "product": candidate["product"],
                "weighted_score": round(weighted_score, 2),
            }
        )
    covered_requirement_ids = {
        identifier
        for item in capabilities
        for identifier in item["requirement_ids"]
    }
    unknown_requirements = covered_requirement_ids - in_scope_ids
    missing_requirements = in_scope_ids - covered_requirement_ids
    if unknown_requirements or missing_requirements:
        raise ClassifierError(
            "Delivery capabilities must cover every in-scope requirement and no "
            "unknown requirements; "
            f"missing={sorted(missing_requirements)}, "
            f"unknown={sorted(unknown_requirements)}"
        )

    expected_weights = {"must": 5, "should": 3, "could": 1}
    allowed_status_factors = {
        "native": (1.0, 1.0),
        "configurable": (1.0, 1.0),
        "demonstrable-only": (0.0, 0.25),
        "unsupported": (0.0, 0.0),
        "unknown": (0.0, 0.0),
    }
    simulation_treatments = {"simulate", "static-sample-data"}
    build_treatments = {"build", "configure"}
    for item in capabilities:
        if item["business_weight"] != expected_weights[item["business_priority"]]:
            raise ClassifierError(
                f"Capability '{item['id']}' weight must match its business priority"
            )
        unknown_dependencies = set(item["dependencies"]) - known_capability_ids
        if unknown_dependencies or item["id"] in item["dependencies"]:
            raise ClassifierError(
                f"Capability '{item['id']}' has invalid dependencies: "
                f"{sorted(unknown_dependencies | ({item['id']} & set(item['dependencies'])))}"
            )
        unknown_components = set(item["component_ids"]) - topology_component_ids
        if unknown_components:
            raise ClassifierError(
                f"Capability '{item['id']}' references unknown topology components: "
                f"{sorted(unknown_components)}"
            )
        if item["implementation_status"] != "unknown" and not item["component_ids"]:
            raise ClassifierError(
                f"Resolved capability '{item['id']}' must map to topology components"
            )
        if item["implementation_status"] in allowed_status_factors:
            expected_native, expected_demo = allowed_status_factors[
                item["implementation_status"]
            ]
            if (
                item["coverage_factor"] != expected_native
                or item["demonstration_factor"] != expected_demo
            ):
                raise ClassifierError(
                    f"Capability '{item['id']}' has invalid coverage factors for "
                    f"status {item['implementation_status']}"
                )
        elif item["implementation_status"] == "partial":
            if not 0 < item["coverage_factor"] < 1:
                raise ClassifierError(
                    f"Partial capability '{item['id']}' requires coverage_factor between zero and one"
                )
            if not item["coverage_factor"] <= item["demonstration_factor"] <= 1:
                raise ClassifierError(
                    f"Partial capability '{item['id']}' demonstration coverage cannot be below native coverage"
                )
        if item["implementation_status"] in {
            "native",
            "configurable",
            "partial",
            "demonstrable-only",
        } and item["allowed_product"] not in delivery["allowed_tools"]:
            raise ClassifierError(
                f"Capability '{item['id']}' must select an allowed product"
            )
        if item["poc_treatment"] in build_treatments and item["build_owner"] != "agent-builder":
            raise ClassifierError(
                f"Buildable capability '{item['id']}' must be owned by agent-builder"
            )
        if item["poc_treatment"] in simulation_treatments:
            disclosure = item["build_contract"]["simulation_disclosure"]
            if not disclosure:
                raise ClassifierError(
                    f"Simulated capability '{item['id']}' requires an explicit user-visible disclosure"
                )
        if item["action_impact"] in {
            "high-impact-write",
            "irreversible-or-safety-critical",
        } and not item["build_contract"]["approval_required"]:
            raise ClassifierError(
                f"High-impact capability '{item['id']}' requires explicit approval"
            )
        if item["implementation_status"] in {"unsupported", "unknown"} and item["poc_treatment"] in build_treatments:
            raise ClassifierError(
                f"Unsupported capability '{item['id']}' cannot be marked for build"
            )

    selected_products = {
        item["allowed_product"]
        for item in capabilities
        if item["implementation_status"] in {
            "native",
            "configurable",
            "partial",
            "demonstrable-only",
        }
    }
    assessed_products = set(selected_products)
    if delegated_personal_required:
        assessed_products.add("Microsoft Cowork")
        if model["platform_assessment"]["cowork_fit"] == "not-assessed":
            raise ClassifierError(
                "Explicit delegated personal work requires a Microsoft Cowork fit assessment"
            )
    gates_by_product: dict[str, dict[str, dict[str, Any]]] = {}
    for product in assessed_products:
        if product not in score_products:
            raise ClassifierError(
                f"Selected product '{product}' requires evidence-backed category scores"
            )
        product_gates = {
            item["gate"]: item for item in delivery["platform_gates"]
            if item["product"] == product
        }
        missing_gates = required_gates - set(product_gates)
        if missing_gates:
            raise ClassifierError(
                f"Selected product '{product}' is missing PoC gates: {sorted(missing_gates)}"
            )
        blockers = [
            gate["gate"]
            for gate in product_gates.values()
            if gate["result"] == "fail" and gate["blocker_for_poc"]
        ]
        if blockers and product in selected_products:
            raise ClassifierError(
                f"Selected product '{product}' failed blocking PoC gates: {sorted(blockers)}"
            )
        gates_by_product[product] = product_gates

    if delegated_personal_required:
        cowork_gates = gates_by_product["Microsoft Cowork"]
        cowork_blocked = any(
            gate["result"] == "fail" and gate["blocker_for_poc"]
            for gate in cowork_gates.values()
        )
        cowork_viable = (
            model["platform_assessment"]["cowork_fit"] == "full"
            and not cowork_blocked
        )
        delegated_capabilities = [
            item
            for item in capabilities
            if item["work_type"] == "delegated-personal-work"
        ]
        if not delegated_capabilities:
            raise ClassifierError(
                "Explicit delegated personal work must map to a delegated-personal-work capability"
            )
        if cowork_skill_required and not model["components"]["skills"]:
            raise ClassifierError(
                "A consistent reusable delegated-work method requires an explicit Cowork skill"
            )
        if cowork_plugin_required and not any(
            item["creation_method"] == "Plugin"
            for item in model["components"]["tools"]
        ):
            raise ClassifierError(
                "Live external-system access for delegated personal work requires an explicit Cowork plugin"
            )
        if cowork_viable:
            if model["agentic_platform"] != "Microsoft Cowork":
                raise ClassifierError(
                    "A full viable Cowork fit must select Microsoft Cowork for explicit delegated personal work"
                )
            incorrectly_mapped = [
                item["id"]
                for item in delegated_capabilities
                if item["allowed_product"] != "Microsoft Cowork"
                or item["implementation_status"]
                not in {"native", "configurable", "partial", "demonstrable-only"}
            ]
            if incorrectly_mapped:
                raise ClassifierError(
                    "Delegated personal-work capabilities must use viable Cowork; "
                    f"invalid={sorted(incorrectly_mapped)}"
                )
        else:
            substituted = [
                item["id"]
                for item in delegated_capabilities
                if item["allowed_product"] != "Microsoft Cowork"
                and item["implementation_status"]
                in {"native", "configurable", "partial", "demonstrable-only"}
            ]
            if substituted:
                raise ClassifierError(
                    "Unavailable or unsuitable Cowork cannot be silently replaced for explicit delegated personal work; "
                    f"block or defer={sorted(substituted)}"
                )

    included = set(delivery["poc_scope"]["included_capability_ids"])
    excluded = set(delivery["poc_scope"]["excluded_capability_ids"])
    if included & excluded or included | excluded != known_capability_ids:
        raise ClassifierError(
            "PoC included and excluded capability IDs must be disjoint and cover every capability"
        )
    for gap in delivery["production_readiness_gaps"]:
        unknown_gap_capabilities = set(gap["capability_ids"]) - known_capability_ids
        if unknown_gap_capabilities:
            raise ClassifierError(
                f"Production gap '{gap['id']}' references unknown capabilities: "
                f"{sorted(unknown_gap_capabilities)}"
            )

    total_weight = sum(item["business_weight"] for item in capabilities)
    native_weight = sum(
        item["business_weight"] * item["coverage_factor"]
        for item in capabilities
    )
    demonstration_weight = sum(
        item["business_weight"] * item["demonstration_factor"]
        for item in capabilities
    )
    unknown_weight = sum(
        item["business_weight"]
        for item in capabilities
        if item["implementation_status"] == "unknown"
    )
    unsupported_weight = sum(
        item["business_weight"] * (1 - item["coverage_factor"])
        for item in capabilities
        if item["implementation_status"] != "unknown"
    )
    coverage = {
        "native_build_percent": round(native_weight / total_weight * 100, 2),
        "poc_demonstration_percent": round(
            demonstration_weight / total_weight * 100, 2
        ),
        "unsupported_percent": round(
            unsupported_weight / total_weight * 100, 2
        ),
        "unknown_percent": round(unknown_weight / total_weight * 100, 2),
    }
    return coverage, platform_scores


def _score_model(
    model: dict[str, Any],
    evidence_summary: dict[str, Any],
) -> dict[str, Any]:
    _schema_validate(model)
    if model["run_id"] != evidence_summary["classifier_run_id"]:
        raise ClassifierError("Classification model run_id does not match the run")
    if model["research_stage"] != evidence_summary["research_stage"]:
        raise ClassifierError("Model research_stage does not match the active run")
    if _contains_topic(model):
        raise ClassifierError("Classic Topics are prohibited from the classification model")

    in_scope_ids = {
        item["finding_id"]
        for item in evidence_summary["in_scope_findings"]
    }
    gap_ids = {
        item["finding_id"] for item in evidence_summary["gaps_and_conflicts"]
    }
    requirement_assessment_ids = [
        item["finding_id"]
        for item in model["requirement_assessments"]
    ]
    if len(requirement_assessment_ids) != len(set(requirement_assessment_ids)):
        raise ClassifierError("Requirement assessments contain duplicate finding IDs")
    if set(requirement_assessment_ids) != in_scope_ids:
        missing = in_scope_ids - set(requirement_assessment_ids)
        extra = set(requirement_assessment_ids) - in_scope_ids
        raise ClassifierError(
            "Requirement assessments must cover every in-scope finding exactly once; "
            f"missing={sorted(missing)}, extra={sorted(extra)}"
        )
    incomplete = [
        item["finding_id"]
        for item in model["requirement_assessments"]
        if item["status"] != "satisfied"
    ]
    if incomplete:
        raise ClassifierError(
            f"Final solution leaves requirements unmet: {sorted(incomplete)}"
        )
    unknown_components = _collect_component_evidence_ids(model) - in_scope_ids
    if unknown_components:
        raise ClassifierError(
            "Components reference non-scope or unknown evidence IDs: "
            f"{sorted(unknown_components)}"
        )
    unknown_gaps = _collect_gap_evidence_ids(model) - gap_ids
    if unknown_gaps:
        raise ClassifierError(
            f"Model gaps reference non-gap or unknown IDs: {sorted(unknown_gaps)}"
        )
    unknown_assessment = _collect_assessment_evidence_ids(model) - in_scope_ids
    if unknown_assessment:
        raise ClassifierError(
            "Platform-assessment gaps reference non-scope or unknown IDs: "
            f"{sorted(unknown_assessment)}"
        )
    consulted_reference_ids = set(evidence_summary["consulted_reference_ids"])
    unknown_references = (
        _collect_component_reference_ids(model) - consulted_reference_ids
    )
    if unknown_references:
        raise ClassifierError(
            "Components reference documentation that was not consulted: "
            f"{sorted(unknown_references)}"
        )
    assessment_reference_ids = {
        reference_id
        for item in model["requirement_assessments"]
        for reference_id in item["reference_ids"]
    }
    unknown_assessment_references = (
        assessment_reference_ids - consulted_reference_ids
    )
    if unknown_assessment_references:
        raise ClassifierError(
            "Requirement assessments cite unconsulted documentation: "
            f"{sorted(unknown_assessment_references)}"
        )
    allowed_platforms = {
        "copilot": {"Copilot Studio", "Microsoft Cowork"},
        "foundry": {"Copilot Studio", "Microsoft Cowork", "Azure AI Foundry"},
        "agent-framework": {
            "Copilot Studio",
            "Microsoft Cowork",
            "Azure AI Foundry",
            "Microsoft Agent Framework",
        },
    }[model["research_stage"]]
    invalid_assessment_platforms = {
        item["platform"]
        for item in model["requirement_assessments"]
        if item["platform"] not in allowed_platforms
    }
    if invalid_assessment_platforms:
        raise ClassifierError(
            "Requirement assessments reference a platform beyond the active "
            f"research stage: {sorted(invalid_assessment_platforms)}"
        )

    stage = model["research_stage"]
    assessment = model["platform_assessment"]
    if stage == "copilot":
        forbidden = consulted_reference_ids & (
            FOUNDRY_REFERENCE_IDS | AGENT_FRAMEWORK_REFERENCE_IDS
        )
        if forbidden:
            raise ClassifierError(
                "Copilot-stage research cannot include Foundry or Agent Framework references"
            )
        selected_stage_one_fit = {
            "Copilot Studio": assessment["copilot_studio_fit"],
            "Microsoft Cowork": assessment["cowork_fit"],
        }.get(model["agentic_platform"])
        if selected_stage_one_fit != "full":
            raise ClassifierError(
                "The selected Stage 1 platform must have full fit; otherwise "
                "publish a blocked allowed-tool assessment or expand research"
            )
        if model["agentic_platform"] not in {"Copilot Studio", "Microsoft Cowork"}:
            raise ClassifierError(
                "Stage 1 publication must select Copilot Studio or Microsoft Cowork"
            )
        if assessment["unmet_requirements"]:
            raise ClassifierError(
                "A full Stage 1 fit cannot contain unmet requirements"
            )
        if (
            assessment["foundry_fit"] != "not-assessed"
            or assessment["agent_framework_fit"] != "not-assessed"
        ):
            raise ClassifierError(
                "Unconsulted platforms must remain not-assessed"
            )
    elif stage == "foundry":
        if (
            assessment["copilot_studio_fit"] == "full"
            or assessment["cowork_fit"] == "full"
        ):
            raise ClassifierError(
                "Foundry research is prohibited when an allowed Stage 1 platform fully fits"
            )
        if not assessment["unmet_requirements"]:
            raise ClassifierError(
                "Foundry escalation requires evidence-linked Copilot Studio gaps"
            )
        if assessment["foundry_fit"] != "full":
            raise ClassifierError(
                "Foundry must fully satisfy the remaining requirements or research must expand to Agent Framework"
            )
        if assessment["agent_framework_fit"] != "not-assessed":
            raise ClassifierError(
                "Agent Framework must remain not-assessed at the Foundry stage"
            )
        if model["agentic_platform"] not in {"Azure AI Foundry", "Hybrid"}:
            raise ClassifierError(
                "Foundry-stage publication must select Foundry or Hybrid"
            )
    else:
        if (
            assessment["copilot_studio_fit"] == "full"
            or assessment["cowork_fit"] == "full"
        ):
            raise ClassifierError(
                "Agent Framework research is prohibited when an allowed Stage 1 platform fully fits"
            )
        if assessment["foundry_fit"] not in {"partial", "not-fit"}:
            raise ClassifierError(
                "Agent Framework escalation requires an unresolved Foundry gap"
            )
        if assessment["agent_framework_fit"] != "full":
            raise ClassifierError(
                "Agent Framework must fully satisfy the remaining requirements"
            )

    persisted_assessments = {
        item["stage"]: item
        for item in evidence_summary.get("research_assessments", [])
    }
    if stage in {"foundry", "agent-framework"}:
        copilot_persisted = persisted_assessments.get("copilot")
        if not copilot_persisted:
            raise ClassifierError(
                "Foundry or Agent Framework publication requires a persisted Copilot assessment"
            )
        if assessment["copilot_studio_fit"] != copilot_persisted["fit"]:
            raise ClassifierError(
                "Model Copilot fit does not match the persisted assessment"
            )
    if stage == "agent-framework":
        foundry_persisted = persisted_assessments.get("foundry")
        if not foundry_persisted:
            raise ClassifierError(
                "Agent Framework publication requires a persisted Foundry assessment"
            )
        if assessment["foundry_fit"] != foundry_persisted["fit"]:
            raise ClassifierError(
                "Model Foundry fit does not match the persisted assessment"
            )
    if stage in {"foundry", "agent-framework"}:
        prior_stage = "copilot" if stage == "foundry" else "foundry"
        expected_unmet = {
            identifier
            for item in persisted_assessments[prior_stage]["unmet_requirements"]
            for identifier in item["evidence_ids"]
        }
        modeled_unmet = _collect_assessment_evidence_ids(model)
        if modeled_unmet != expected_unmet:
            raise ClassifierError(
                "Model unmet requirements do not match the persisted prior-stage assessment"
            )
    if stage == "agent-framework":
        if model["agentic_platform"] not in {
            "Pro-code (Microsoft Agent Framework)",
            "Hybrid",
        }:
            raise ClassifierError(
                "Agent Framework stage must select Agent Framework or Hybrid"
            )

    platform = model["agentic_platform"]
    harness = model["harness"]
    if platform in {"Copilot Studio", "Hybrid"} and harness is None:
        raise ClassifierError("Copilot Studio solutions require a harness")
    if platform == "Microsoft Cowork" and harness != "Cowork":
        raise ClassifierError("Microsoft Cowork solutions require the Cowork runtime")
    if platform not in {"Copilot Studio", "Microsoft Cowork", "Hybrid"} and harness is not None:
        raise ClassifierError("Non-Copilot-Studio solutions require harness null")
    if platform != "Microsoft Cowork" and harness == "Cowork":
        raise ClassifierError("The Cowork runtime requires Microsoft Cowork")

    components = model["components"]
    _validate_solution_topology(model)
    delegated_personal_required = any(
        re.search(
            r"\b(personal digital worker|delegated personal work|"
            r"work on behalf of (?:a|the) (?:user|employee|leader)|"
            r"personal workforce automation)\b",
            item.get("statement", ""),
            flags=re.IGNORECASE,
        )
        for item in evidence_summary["in_scope_findings"]
    )
    in_scope_statements = "\n".join(
        item.get("statement", "")
        for item in evidence_summary["in_scope_findings"]
    )
    cowork_skill_required = bool(
        delegated_personal_required
        and re.search(
            r"\b(standard|same|consistent|repeatable|reusable)\b.*"
            r"\b(method|methodology|structure|procedure|format)\b|"
            r"\b(method|methodology|structure|procedure|format)\b.*"
            r"\b(across|every|consisten|repeat|reus)",
            in_scope_statements,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    cowork_plugin_required = bool(
        delegated_personal_required
        and re.search(
            r"\b(external|third-party)\b.*\b(system|product|service)\b.*"
            r"\b(retriev|current|without manual export|without manual upload|connect)",
            in_scope_statements,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    coverage, platform_scores = _validate_delivery_assessment(
        model,
        in_scope_ids,
        consulted_reference_ids,
        delegated_personal_required,
        cowork_skill_required,
        cowork_plugin_required,
    )
    rules = _json_load(RULES_PATH)
    low_thresholds = rules["thresholds"]["low"]
    medium_thresholds = rules["thresholds"]["medium"]
    for key in (
        "agents",
        "platform_capabilities",
        "knowledge_sources",
        "skills",
        "connected_agents",
        "triggers",
        "automation",
        "integration",
        "data",
        "security_controls",
        "governance_controls",
        "alm",
        "communication_channels",
        "tools",
    ):
        items = components[key]
        names = [item["name"].strip().casefold() for item in items]
        if len(names) != len(set(names)):
            raise ClassifierError(f"Duplicate component identities in {key}")
    gap_names = [item["name"].strip().casefold() for item in model["gaps"]]
    if len(gap_names) != len(set(gap_names)):
        raise ClassifierError("Duplicate component identities in gaps")
    cited_in_justification = set(
        re.findall(
            r"\[([A-Z]+-[A-F0-9]+)\]",
            "\n".join(model["justification_paragraphs"]),
        )
    )
    if not cited_in_justification:
        raise ClassifierError(
            "Comprehensive justification must cite decisive evidence IDs"
        )
    if not (cited_in_justification & in_scope_ids):
        raise ClassifierError(
            "Comprehensive justification must cite at least one in-scope finding"
        )
    unknown_justification = cited_in_justification - (in_scope_ids | gap_ids)
    if unknown_justification:
        raise ClassifierError(
            "Justification references unknown evidence IDs: "
            f"{sorted(unknown_justification)}"
        )
    counts = {
        "knowledge_sources": len(components["knowledge_sources"]),
        "easily_integrable_tools": sum(
            1
            for item in components["tools"]
            if item["integrability"] == "easily-integrable"
        ),
        "skills": len(components["skills"]),
        "connected_agents": len(components["connected_agents"]),
    }
    custom_tool = any(
        item["integrability"] == "custom" for item in components["tools"]
    )
    flags = model["flags"]
    custom_integration = any(
        item["integrability"] == "custom"
        or item["method"]
        in {"Custom connector", "Custom API", "MCP", "Gateway"}
        for item in components["integration"]
    )
    custom_required = custom_tool or custom_integration
    tiered_components = (
        components["platform_capabilities"]
        + components["tools"]
        + components["triggers"]
        + components["automation"]
        + components["integration"]
        + components["data"]
        + components["security_controls"]
        + components["governance_controls"]
        + components["alm"]
    )
    low_code_component = any(
        item["implementation_tier"] == "Low-code"
        for item in tiered_components
    )
    pro_code_component = any(
        item["implementation_tier"] == "Pro-code"
        for item in tiered_components
    )
    for tool in components["tools"]:
        if tool["creation_method"] in {
            "MCP server",
            "Custom connector",
            "Custom API",
        } and tool["integrability"] != "custom":
            raise ClassifierError(
                f"{tool['creation_method']} tool '{tool['name']}' must be classified as custom"
            )
        if (
            tool["integrability"] == "custom"
            and tool["implementation_tier"] == "No-code"
        ):
            raise ClassifierError("Custom tools cannot use the No-code tier")
        if (
            tool["implementation_tier"] == "Pro-code"
            and tool["integrability"] != "custom"
        ):
            raise ClassifierError("Pro-code tools must be custom")

    pro_platform = platform in {
        "Azure AI Foundry",
        "Pro-code (Microsoft Agent Framework)",
        "Hybrid",
    }
    pro_code_required = pro_platform or pro_code_component
    derived_tier = (
        "Pro-code"
        if pro_code_required
        else "Low-code"
        if low_code_component
        else "No-code"
    )
    if model["code_tier"] != derived_tier:
        raise ClassifierError(
            f"Code tier must be derived as {derived_tier} from the component inventory"
        )
    if derived_tier in {"No-code", "Low-code"} and platform not in {
        "Copilot Studio",
        "Microsoft Cowork",
    }:
        raise ClassifierError(
            f"{derived_tier} tier requires Copilot Studio or Microsoft Cowork"
        )
    if flags["requires_pro_code"] != pro_code_required:
        raise ClassifierError(
            "requires_pro_code must be derived from the platform and component tiers"
        )
    if flags["uses_low_code"] != low_code_component:
        raise ClassifierError(
            "uses_low_code must be derived from low-code component tiers"
        )
    if flags["requires_custom_or_gateway"] != custom_required:
        raise ClassifierError(
            "requires_custom_or_gateway must be derived from custom tools or "
            "custom/gateway/middleware/API integration components"
        )

    chat_channels = [
        item
        for item in components["communication_channels"]
        if re.search(r"\bcopilot\s+chat\b", item["name"], re.IGNORECASE)
    ]
    if harness == "Copilot chat" and not chat_channels:
        raise ClassifierError(
            "Copilot chat harness requires a Copilot Chat communication channel"
        )
    if chat_channels and harness != "Copilot chat":
        raise ClassifierError(
            "Copilot Chat communication channel requires the Copilot chat harness"
        )
    if platform == "Microsoft Cowork":
        cowork_channels = [
            item
            for item in components["communication_channels"]
            if "cowork" in item["name"].casefold()
        ]
        if not cowork_channels:
            raise ClassifierError(
                "Microsoft Cowork solutions require an explicit Cowork experience channel"
            )

    component_reference_ids = _collect_component_reference_ids(model)
    if platform in {"Copilot Studio", "Hybrid"}:
        required_copilot_refs = {
            "copilot-studio-fundamentals",
            "copilot-studio-harnesses",
            "copilot-studio-guidance",
            "power-platform-well-architected",
        }
        missing_refs = required_copilot_refs - component_reference_ids
        if missing_refs:
            raise ClassifierError(
                "Copilot Studio design must cite core, harness, guidance, and "
                f"Well-Architected references: {sorted(missing_refs)}"
            )
        for tool in components["tools"]:
            if not (
                set(tool["reference_ids"])
                & {
                    "copilot-studio-tools",
                    "power-automate",
                    "copilot-studio-autonomous",
                }
            ):
                raise ClassifierError(
                    f"Copilot Studio tool '{tool['name']}' must cite tool or workflow documentation"
                )
    if platform == "Microsoft Cowork":
        required_cowork_refs = {
            "cowork-overview",
            "cowork-get-started",
        }
        missing_refs = required_cowork_refs - component_reference_ids
        if missing_refs:
            raise ClassifierError(
                "Cowork design must cite overview and setup documentation: "
                f"{sorted(missing_refs)}"
            )
        if (components["skills"] or any(
            item["creation_method"] == "Plugin" for item in components["tools"]
        )) and "cowork-customize" not in component_reference_ids:
            raise ClassifierError(
                "Cowork skills and plugins must cite Cowork customization documentation"
            )
    if platform in {"Azure AI Foundry", "Hybrid"} and stage == "foundry":
        if "foundry-agent-service" not in component_reference_ids:
            raise ClassifierError(
                "Foundry selection must cite Foundry Agent Service documentation"
            )
    if platform in {"Pro-code (Microsoft Agent Framework)", "Hybrid"} and stage == "agent-framework":
        if "agent-framework" not in component_reference_ids:
            raise ClassifierError(
                "Agent Framework selection must cite Agent Framework documentation"
            )

    conversational = any(
        item.get("behavior") == "Conversational"
        and item.get("requirement_status") in IN_SCOPE_STATUSES
        for item in evidence_summary.get("agentic_behaviors", [])
    )
    channel_names = {
        item["name"].casefold() for item in components["communication_channels"]
    }
    configured_channels = evidence_summary.get("lisa_config", {}).get(
        "configured_channels", []
    )
    evidenced_channels = [
        item["name"] for item in evidence_summary.get("evidenced_channels", [])
    ]
    if conversational and platform != "Microsoft Cowork":
        expected_channels = (
            configured_channels
            or evidenced_channels
            or DEFAULT_CONVERSATIONAL_CHANNELS
        )
        expected_normalized = {name.casefold() for name in expected_channels}
        if channel_names != expected_normalized:
            raise ClassifierError(
                "Conversational channels must exactly follow configured, evidenced, "
                f"or default precedence; expected={sorted(expected_channels)}"
            )
        expected_basis = (
            "configured"
            if configured_channels
            else "evidenced"
            if evidenced_channels
            else "default"
        )
        for channel in components["communication_channels"]:
            if channel["selection_basis"] != expected_basis:
                raise ClassifierError(
                    f"Channel '{channel['name']}' must use selection_basis={expected_basis}"
                )
            if expected_basis == "configured" and not channel["source_refs"]:
                raise ClassifierError(
                    f"Configured channel '{channel['name']}' must cite lisa-config.json"
                )
            if expected_basis == "evidenced" and not channel["evidence_ids"]:
                raise ClassifierError(
                    f"Evidenced channel '{channel['name']}' must cite requirement findings"
                )

    autonomous = any(
        item.get("behavior") == "Autonomous"
        and item.get("requirement_status") in IN_SCOPE_STATUSES
        for item in evidence_summary.get("agentic_behaviors", [])
    )
    autonomous_agents = {
        item["name"]
        for item in components["agents"]
        if "Autonomous" in item["behaviors"]
    }
    if autonomous and not autonomous_agents:
        raise ClassifierError(
            "At least one agent must be marked Autonomous"
        )
    if autonomous_agents and not components["triggers"]:
        raise ClassifierError(
            "Autonomous agents require at least one explicit invocation trigger"
        )
    if autonomous_agents:
        autonomous_ids = {
            identifier
            for item in evidence_summary.get("agentic_behaviors", [])
            if item.get("behavior") == "Autonomous"
            for identifier in item.get("finding_ids", [])
        }
        if not any(
            set(trigger["evidence_ids"]) & autonomous_ids
            for trigger in components["triggers"]
        ):
            raise ClassifierError(
                "Autonomous trigger must cite the autonomous behavior requirement"
            )
        trigger_agents = {
            agent_name
            for trigger in components["triggers"]
            for agent_name in trigger["agent_names"]
        }
        unknown_trigger_agents = trigger_agents - {
            item["name"] for item in components["agents"]
        }
        if unknown_trigger_agents:
            raise ClassifierError(
                f"Triggers reference unknown agents: {sorted(unknown_trigger_agents)}"
            )
        missing_trigger_agents = autonomous_agents - trigger_agents
        if missing_trigger_agents:
            raise ClassifierError(
                "Every autonomous agent requires a trigger; missing="
                f"{sorted(missing_trigger_agents)}"
            )

    mandatory_reference_groups: dict[str, set[str]]
    if platform == "Copilot Studio":
        mandatory_reference_groups = {
            "authentication": {"entra-id", "copilot-studio-authentication"},
            "authorization": {"entra-id", "copilot-studio-authentication"},
        }
    elif platform == "Microsoft Cowork":
        mandatory_reference_groups = {
            "authentication": {"entra-id", "cowork-get-started"},
            "authorization": {"entra-id", "cowork-get-started"},
        }
    elif platform == "Hybrid":
        mandatory_reference_groups = {
            "authentication": {
                "entra-id",
                "copilot-studio-authentication",
                "azure-rbac",
            },
            "authorization": {
                "entra-id",
                "copilot-studio-authentication",
                "azure-rbac",
            },
        }
    else:
        mandatory_reference_groups = {
            "authentication": {"entra-id", "azure-rbac"},
            "authorization": {"entra-id", "azure-rbac"},
        }
    for key, required_refs in mandatory_reference_groups.items():
        missing = required_refs - set(components[key]["reference_ids"])
        if missing:
            raise ClassifierError(
                f"{key} must cite researched Microsoft identity documentation: {sorted(missing)}"
            )
    security_refs = {
        reference
        for item in components["security_controls"]
        for reference in item["reference_ids"]
    }
    governance_refs = {
        reference
        for item in components["governance_controls"]
        for reference in item["reference_ids"]
    }
    alm_refs = {
        reference
        for item in components["alm"]
        for reference in item["reference_ids"]
    }
    if platform == "Copilot Studio":
        if not ({"power-platform-dlp", "microsoft-purview"} & security_refs):
            raise ClassifierError(
                "Copilot Studio security must cite DLP or Microsoft Purview"
            )
        if not ({"managed-environments", "power-platform-dlp"} & governance_refs):
            raise ClassifierError(
                "Copilot Studio governance must cite Managed Environments or DLP"
            )
        if "power-platform-alm" not in alm_refs:
            raise ClassifierError("Copilot Studio ALM must cite Power Platform ALM")
    elif platform == "Microsoft Cowork":
        if not ({"cowork-overview", "cowork-get-started", "microsoft-purview"} & security_refs):
            raise ClassifierError(
                "Cowork security must cite Cowork or Microsoft Purview guidance"
            )
        if not ({"cowork-overview", "cowork-customize"} & governance_refs):
            raise ClassifierError(
                "Cowork governance must cite Cowork capability or customization guidance"
            )
        if "cowork-customize" not in alm_refs:
            raise ClassifierError(
                "Cowork lifecycle must cite reproducible skill and plugin customization guidance"
            )
    else:
        if not ({"azure-policy", "azure-monitor", "microsoft-purview"} & security_refs):
            raise ClassifierError(
                "Azure-hosted security must cite Azure Policy, Azure Monitor, or Purview"
            )
        if "azure-policy" not in governance_refs:
            raise ClassifierError("Azure-hosted governance must cite Azure Policy")
        if "azure-pipelines" not in alm_refs:
            raise ClassifierError("Azure-hosted ALM must cite Azure Pipelines")
        if platform == "Hybrid":
            if "power-platform-alm" not in alm_refs:
                raise ClassifierError(
                    "Hybrid ALM must also cite Power Platform ALM"
                )
            if not ({"managed-environments", "power-platform-dlp"} & governance_refs):
                raise ClassifierError(
                    "Hybrid governance must also cite Managed Environments or DLP"
                )

    high_reasons: list[str] = []
    if pro_code_required:
        high_reasons.append("An evidenced requirement needs pro-code capability.")
    if custom_required:
        high_reasons.append(
            "An evidenced tool or integration needs custom connectivity, a gateway, middleware, or code."
        )
    if platform in {
        "Azure AI Foundry",
        "Pro-code (Microsoft Agent Framework)",
        "Hybrid",
    }:
        high_reasons.append(f"The selected platform is {platform}.")
    if (
        counts["easily_integrable_tools"]
        > medium_thresholds["max_easily_integrable_tools"]
    ):
        high_reasons.append("Easily-integrable tool count exceeds three.")
    if counts["skills"] > medium_thresholds["max_skills"]:
        high_reasons.append("Skill count exceeds five.")
    if counts["connected_agents"] > medium_thresholds["max_connected_agents"]:
        high_reasons.append("Connected-agent count exceeds three.")

    if high_reasons:
        complexity = "High"
        reasons = high_reasons
    elif (
        platform in {"Copilot Studio", "Microsoft Cowork"}
        and model["code_tier"] == "No-code"
        and not flags["uses_low_code"]
        and counts["easily_integrable_tools"]
        <= low_thresholds["max_easily_integrable_tools"]
        and counts["skills"] <= low_thresholds["max_skills"]
        and counts["connected_agents"]
        <= low_thresholds["max_connected_agents"]
    ):
        complexity = "Low"
        reasons = [
            "The solution fits an allowed managed no-code platform within every Low threshold."
        ]
    else:
        complexity = "Medium"
        reasons = [
            "No High trigger applies, but the solution exceeds or falls outside the Low no-code profile."
        ]

    if (
        harness == "GitHub Copilot"
        and not (
            components["skills"]
            or flags["autonomous_multistep"]
            or flags["uses_memory"]
        )
    ):
        raise ClassifierError(
            "GitHub Copilot harness requires skills, memory, or autonomous multi-step orchestration"
        )
    if (
        harness in {"Standard", "Copilot chat"}
        and (
            components["skills"]
            or flags["autonomous_multistep"]
            or flags["uses_memory"]
        )
    ):
        raise ClassifierError(
            f"{harness} harness conflicts with skills, memory, or autonomous multi-step orchestration"
        )
    if harness == "Cowork" and platform != "Microsoft Cowork":
        raise ClassifierError("Cowork runtime requires Microsoft Cowork")

    return {
        "complexity": complexity,
        "counts": counts,
        "decisive_reasons": reasons,
        "coverage": coverage,
        "platform_scores": platform_scores,
    }


def _escape_table(value: Any) -> str:
    return str(value).replace("\r", " ").replace("\n", "<br>").replace("|", "\\|")


def _evidence_citation(ids: list[str]) -> str:
    return " ".join(f"[{item}]" for item in ids) if ids else "None evidenced"


def _grounding_suffix(item: dict[str, Any]) -> str:
    parts = [f"basis={item['selection_basis']}"]
    if item.get("evidence_ids"):
        parts.append(_evidence_citation(item["evidence_ids"]))
    if item.get("reference_ids"):
        parts.append(
            "docs=" + ", ".join(item["reference_ids"])
        )
    if item.get("source_refs"):
        parts.append(
            "sources=" + ", ".join(item["source_refs"])
        )
    return " | ".join(parts)


def _render_reference_table(references: list[dict[str, Any]]) -> str:
    lines = [
        "| Title | Absolute URL | Date reviewed | Status / limitation |",
        "|---|---|---|---|",
    ]
    for item in references:
        status = item["status"]
        if item.get("limitation"):
            status += f": {item['limitation']}"
        lines.append(
            "| "
            + " | ".join(
                _escape_table(value)
                for value in (
                    item["title"],
                    item["url"],
                    item["reviewed_at"],
                    status,
                )
            )
            + " |"
        )
    return "\n".join(lines)


def _render_items(items: list[dict[str, Any]]) -> str:
    if not items:
        return "None evidenced"
    return "\n".join(
        (
            f"- {item['name']}"
            + (
                f" — {item['implementation_tier']}"
                if item.get("implementation_tier")
                else ""
            )
            + f" ({_grounding_suffix(item)})"
        )
        for item in items
    )


def _render_components(model: dict[str, Any]) -> str:
    components = model["components"]
    sections = [
        ("Agents", _render_items(components["agents"])),
        (
            "Agent development platform capabilities",
            _render_items(components["platform_capabilities"]),
        ),
        ("Knowledge sources", _render_items(components["knowledge_sources"])),
    ]
    if components["tools"]:
        tools = "\n".join(
            (
                f"- {item['name']} — {item['integrability']}; "
                f"{item['implementation_tier']}; "
                f"creation method: {item['creation_method']}; "
                f"{item['implementation']} ({_grounding_suffix(item)})"
            )
            for item in components["tools"]
        )
    else:
        tools = "None evidenced"
    sections.append(("Tools / actions", tools))
    if components["triggers"]:
        triggers = "\n".join(
            (
                f"- {item['name']} — {item['trigger_type']}; "
                f"{item['implementation_tier']}; mechanism: {item['mechanism']} "
                f"({_grounding_suffix(item)})"
            )
            for item in components["triggers"]
        )
    else:
        triggers = "None evidenced"
    sections.append(("Invocation triggers", triggers))
    for title, key in (
        ("Skills", "skills"),
        ("Connected / child agents", "connected_agents"),
        ("Automation", "automation"),
        ("Integration", "integration"),
        ("Data", "data"),
        ("Security controls", "security_controls"),
        ("Governance controls", "governance_controls"),
        ("ALM", "alm"),
    ):
        sections.append((title, _render_items(components[key])))
    for title, key in (
        ("Authentication", "authentication"),
        ("Authorization", "authorization"),
    ):
        item = components[key]
        sections.append(
            (
                title,
                (
                    f"Platform: {item['platform']}; tool: {item['tool']}; "
                    f"configuration: {item['configuration']} "
                    f"({_grounding_suffix(item)})"
                ),
            )
        )
    sections.append(
        (
            "Communication channels",
            _render_items(components["communication_channels"]),
        )
    )
    return "\n\n".join(f"### {title}\n{content}" for title, content in sections)


def _render_delivery_assessment(
    model: dict[str, Any], coverage: dict[str, float], platform_scores: list[dict[str, Any]]
) -> str:
    delivery = model["delivery_assessment"]
    lines = [
        "### Coverage",
        "| Measure | Percent |",
        "|---|---:|",
        f"| Native build coverage | {coverage['native_build_percent']:.2f}% |",
        f"| PoC demonstration coverage | {coverage['poc_demonstration_percent']:.2f}% |",
        f"| Unsupported coverage | {coverage['unsupported_percent']:.2f}% |",
        f"| Unknown coverage | {coverage['unknown_percent']:.2f}% |",
        "",
        "### Allowed-product category scores",
        "| Product | Weighted score |",
        "|---|---:|",
        *[
            f"| {_escape_table(item['product'])} | {item['weighted_score']:.2f}/100 |"
            for item in platform_scores
        ],
        "",
        "### Capability dispositions",
        "| Capability | Priority | Allowed product | Status | PoC treatment | Owner | Supported / unsupported |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in delivery["capabilities"]:
        split = item["supported_portion"]
        if item["unsupported_portion"]:
            split += " / " + item["unsupported_portion"]
        lines.append(
            "| "
            + " | ".join(
                _escape_table(value)
                for value in (
                    f"{item['id']}: {item['name']}",
                    item["business_priority"],
                    item["allowed_product"] or "Outside allowed tools / unresolved",
                    item["implementation_status"],
                    item["poc_treatment"],
                    item["build_owner"],
                    split,
                )
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "### PoC scope",
            f"- Objective: {delivery['poc_scope']['objective']}",
            f"- Included capabilities: {', '.join(delivery['poc_scope']['included_capability_ids']) or 'None'}",
            f"- Excluded capabilities: {', '.join(delivery['poc_scope']['excluded_capability_ids']) or 'None'}",
            f"- Test data boundary: {delivery['poc_scope']['test_data_boundary']}",
        ]
    )
    return "\n".join(lines)


def _topology_grounding(item: dict[str, Any]) -> str:
    parts = []
    if item.get("evidence_ids"):
        parts.append(_evidence_citation(item["evidence_ids"]))
    if item.get("reference_ids"):
        parts.append("docs=" + ", ".join(item["reference_ids"]))
    if item.get("source_refs"):
        parts.append("sources=" + ", ".join(item["source_refs"]))
    return "; ".join(parts)


def _render_solution_topology(model: dict[str, Any]) -> str:
    topology = model["solution_topology"]
    principles = [
        "| Quality | Decision | Implementation | Microsoft guidance |",
        "|---|---|---|---|",
    ]
    principles.extend(
        "| "
        + " | ".join(
            _escape_table(value)
            for value in (
                item["dimension"],
                item["decision"],
                item["implementation"],
                ", ".join(item["reference_ids"]),
            )
        )
        + " |"
        for item in topology["architecture_principles"]
    )

    components = [
        "| ID | Exact component | Category | Microsoft product/service | Runtime and boundary | Lifecycle | Role | Quality controls | Inventory mapping | Grounding |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    components.extend(
        "| "
        + " | ".join(
            _escape_table(value)
            for value in (
                item["id"],
                item["name"],
                item["category"],
                item["product_service"],
                f"{item['hosting_runtime']}; {item['deployment_boundary']}; {item['environment_scope']}",
                item["lifecycle"],
                item["role"],
                (
                    f"Reliability: {item['reliability']}; "
                    f"Scalability: {item['scalability']}; "
                    f"Security: {item['security']}"
                ),
                ", ".join(item["inventory_names"]) or "Architecture recommendation",
                _topology_grounding(item),
            )
        )
        + " |"
        for item in topology["components"]
    )

    relationships = [
        "| ID | Source | Target | Type | Interaction | Method / protocol | Data and access | Authentication | Execution / failure behavior | Grounding |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    relationships.extend(
        "| "
        + " | ".join(
            _escape_table(value)
            for value in (
                item["id"],
                item["source_id"],
                item["target_id"],
                item["relationship_type"],
                f"{item['interaction']} ({item['direction']})",
                f"{item['integration_method']}; {item['protocol']}",
                f"{item['data_flow']}; access={item['access']}",
                item["authentication"],
                (
                    f"{'synchronous' if item['synchronous'] else 'asynchronous'}; "
                    f"{item['failure_behavior']}"
                ),
                _topology_grounding(item),
            )
        )
        + " |"
        for item in topology["relationships"]
    )

    trust = [
        "| Boundary | Type | Components | Controls | Grounding |",
        "|---|---|---|---|---|",
    ]
    trust.extend(
        "| "
        + " | ".join(
            _escape_table(value)
            for value in (
                item["name"],
                item["boundary_type"],
                ", ".join(item["component_ids"]),
                ", ".join(item["controls"]),
                _topology_grounding(item),
            )
        )
        + " |"
        for item in topology["trust_boundaries"]
    )

    environments = [
        "| Environment | Purpose | Component IDs | Promotion mechanism | Microsoft guidance |",
        "|---|---|---|---|---|",
    ]
    environments.extend(
        "| "
        + " | ".join(
            _escape_table(value)
            for value in (
                item["name"],
                item["purpose"],
                ", ".join(item["component_ids"]),
                item["promotion_via"],
                ", ".join(item["reference_ids"]),
            )
        )
        + " |"
        for item in topology["environments"]
    )

    sequence = [
        "| Order | Phase | Source | Target | Interaction | Type / condition | Grounding |",
        "|---:|---|---|---|---|---|---|",
    ]
    sequence.extend(
        "| "
        + " | ".join(
            _escape_table(value)
            for value in (
                item["order"],
                item["phase"],
                item["source_id"],
                item["target_id"],
                item["action"],
                (
                    item["message_type"]
                    + (f"; {item['condition']}" if item["condition"] else "")
                ),
                _topology_grounding(item),
            )
        )
        + " |"
        for item in topology["sequence_flows"]
    )

    return "\n\n".join(
        [
            topology["architecture_summary"],
            "### Architecture quality decisions\n" + "\n".join(principles),
            "### Canonical architecture components\n" + "\n".join(components),
            "### Explicit component relationships\n" + "\n".join(relationships),
            "### Trust boundaries\n" + "\n".join(trust),
            "### Environment and ALM topology\n" + "\n".join(environments),
            "### Ordered sequence contract\n" + "\n".join(sequence),
        ]
    )


def _render_evidence(summary: dict[str, Any]) -> str:
    parts = []
    for title, key in (
        ("Goals", "goals"),
        ("Data sources", "data_sources"),
        ("Data types", "data_types"),
        ("Metrics", "metrics"),
        ("Solution components", "solution_components"),
    ):
        values = summary.get(key, [])
        parts.append(
            f"### {title}\n"
            + (
                "\n".join(
                    f"- {item['text']} {_evidence_citation(item['evidence_ids'])}"
                    for item in values
                )
                if values
                else "None evidenced"
            )
        )
    integrations = summary.get("integrations", [])
    parts.append(
        "### Integrations\n"
        + (
            "\n".join(
                (
                    f"- {item.get('name', 'Integration')}: "
                    f"{item.get('purpose', '')} "
                    f"{_evidence_citation(item.get('finding_ids', []))}"
                )
                for item in integrations
            )
            if integrations
            else "None evidenced"
        )
    )
    behaviors = summary.get("agentic_behaviors", [])
    parts.append(
        "### Agentic behavior\n"
        + (
            "\n".join(
                (
                    f"- {item.get('behavior')}: {item.get('requirement_status')} — "
                    f"{item.get('evidenced_behavior', '')} "
                    f"{_evidence_citation(item.get('finding_ids', []))}"
                )
                for item in behaviors
            )
            if behaviors
            else "None evidenced"
        )
    )
    return "\n\n".join(parts)


def _output_object(
    run: dict[str, Any],
    model: dict[str, Any],
    score: dict[str, Any],
    references: list[dict[str, Any]],
    evidence_summary: dict[str, Any],
) -> dict[str, Any]:
    components = model["components"]
    public_references = [
        {
            key: item.get(key, "")
            for key in (
                "id",
                "title",
                "url",
                "domain",
                "reviewed_at",
                "status",
                "etag",
                "last_modified",
                "content_sha256",
                "limitation",
            )
        }
        for item in references
    ]
    return {
        "complexity": score["complexity"],
        "research_stage": model["research_stage"],
        "platform_assessment": model["platform_assessment"],
        "agentic_platform": model["agentic_platform"],
        "harness": model["harness"],
        "code_tier": model["code_tier"],
        "counts": score["counts"],
        "delivery_assessment": model["delivery_assessment"],
        "coverage": score["coverage"],
        "platform_scores": score["platform_scores"],
        "components": components,
        "solution_topology": model["solution_topology"],
        "reference_sources": public_references,
        "justification": "\n\n".join(model["justification_paragraphs"]),
        "harness_rationale": model["harness_rationale"],
        "billing_implication": model["billing_implication"],
        "decisive_reasons": score["decisive_reasons"],
        "gaps": model["gaps"],
        "input_analysis": run["input_path"],
        "output_markdown": run["target_markdown_path"],
    }


def _render_markdown(
    model: dict[str, Any],
    score: dict[str, Any],
    references: list[dict[str, Any]],
    summary: dict[str, Any],
    output: dict[str, Any],
) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    platform = "\n".join(
        [
            f"- **Agentic platform:** {model['agentic_platform']}",
            f"- **Research stage:** {model['research_stage']}",
            (
                "- **Copilot Studio feasibility:** "
                f"{model['platform_assessment']['copilot_studio_fit']}"
            ),
            (
                "- **Microsoft Cowork feasibility:** "
                f"{model['platform_assessment']['cowork_fit']}"
            ),
            (
                "- **Platform decision:** "
                f"{model['platform_assessment']['decision_summary']}"
            ),
            f"- **Code tier:** {model['code_tier']}",
            f"- **Harness:** {model['harness'] or 'Not applicable'}",
            f"- **Harness rationale:** {model['harness_rationale']}",
            f"- **Billing implication:** {model['billing_implication']}",
        ]
    )
    threshold = (
        f"Deterministic counts: {score['counts']['knowledge_sources']} knowledge "
        f"sources, {score['counts']['easily_integrable_tools']} easily-integrable "
        f"tools, {score['counts']['skills']} skills, and "
        f"{score['counts']['connected_agents']} connected agents. "
        + " ".join(score["decisive_reasons"])
    )
    justification = "\n\n".join(model["justification_paragraphs"] + [threshold])
    counts = "\n".join(
        [
            "| Counted element | Count |",
            "|---|---:|",
            f"| Knowledge sources | {score['counts']['knowledge_sources']} |",
            f"| Easily-integrable tool calls | {score['counts']['easily_integrable_tools']} |",
            f"| Skills | {score['counts']['skills']} |",
            f"| Connected agents | {score['counts']['connected_agents']} |",
        ]
    )
    gaps = _render_items(model["gaps"])
    values = {
        "REFERENCES": _render_reference_table(references),
        "COMPLEXITY": score["complexity"],
        "PLATFORM": platform,
        "JUSTIFICATION": justification,
        "EVIDENCE": _render_evidence(summary),
        "COMPONENTS": _render_components(model),
        "DELIVERY": _render_delivery_assessment(
            model, score["coverage"], score["platform_scores"]
        ),
        "TOPOLOGY": _render_solution_topology(model),
        "COUNTS": counts,
        "GAPS": gaps,
        "JSON": json.dumps(output, indent=2, ensure_ascii=False),
    }
    template = re.sub(
        r"\{\{([A-Z]+)\}\}",
        lambda match: values.get(match.group(1), match.group(0)),
        template,
    )
    if re.search(r"\{\{[^}]+\}\}", template):
        raise ClassifierError("Classification template has unresolved placeholders")
    return template.rstrip() + "\n"


def _validate_markdown(path: Path, text: str, output: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not CLASSIFICATION_FILENAME.fullmatch(path.name):
        errors.append(f"Invalid classification filename: {path.name}")
    if not text.startswith("# Complexity Classification\n"):
        errors.append("Markdown must begin with '# Complexity Classification'")
    headings = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    if headings != REQUIRED_HEADINGS:
        errors.append("Markdown section order does not match the contract")
    if re.search(r"\{\{[^}]+\}\}", text):
        errors.append("Markdown has unresolved template placeholders")
    if _contains_topic(output) or _contains_classic_topic_text(text):
        errors.append("Classic Topics appear in the output")
    return errors


def _write_model_cache(run: dict[str, Any], model: dict[str, Any]) -> None:
    cached_model = copy.deepcopy(model)
    cached_model["run_id"] = "CACHE"
    payload = {
        "version": CACHE_VERSION,
        "cache_key": run["cache_key"],
        "created_at_local": _run_local_time(run),
        "model": cached_model,
        "model_sha256": _canonical_hash(cached_model),
    }
    _safe_write_path(Path(run["cache_path"]), Path(run["classification_root"]))
    _atomic_write_json(Path(run["cache_path"]), payload)


def _publish(args: argparse.Namespace) -> int:
    run_path = Path(args.run).resolve()
    run = _load_run(run_path)
    if run.get("status") != "prepared":
        raise ClassifierError(
            f"Run status {run.get('status')} cannot be published again"
        )
    model_path = Path(args.model).resolve()
    if not _is_within(model_path, Path(run["run_directory"])):
        raise ClassifierError("Classification model must be inside the run directory")
    model = _json_load(model_path)
    summary = _json_load(Path(run["evidence_summary_path"]))
    summary["classifier_run_id"] = run["run_id"]
    references_value = json.loads(
        Path(run["references_path"]).read_text(encoding="utf-8")
    )
    if not isinstance(references_value, list):
        raise ClassifierError("Reference artifact must contain an array")
    references = references_value
    summary["research_stage"] = run["research_stage"]
    summary["research_assessments"] = run.get(
        "research_assessments", []
    )
    accepted_reference_statuses = {
        "retrieved",
        "not-modified",
        "fresh-cache",
        "cached-after-error",
        "packaged-verified",
    }
    summary["consulted_reference_ids"] = [
        item["id"]
        for item in references
        if item["status"] in accepted_reference_statuses
        and item.get("content_sha256")
    ]
    failed_required = [
        item["id"]
        for item in references
        if item.get("required")
        and item["id"] not in summary["consulted_reference_ids"]
    ]
    if failed_required:
        raise ClassifierError(
            f"Required references were not reviewed: {failed_required}"
        )
    score = _score_model(model, summary)
    output = _output_object(run, model, score, references, summary)
    try:
        import jsonschema
        jsonschema.Draft202012Validator(
            _json_load(OUTPUT_SCHEMA_PATH)
        ).validate(output)
    except ImportError as exc:
        raise ClassifierError(
            "jsonschema is required; install the local-skills requirements.txt"
        ) from exc
    except jsonschema.ValidationError as exc:
        location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
        raise ClassifierError(
            f"Classification output schema error at {location}: {exc.message}"
        ) from exc
    markdown = _render_markdown(model, score, references, summary, output)
    markdown_path = Path(run["target_markdown_path"])
    json_path = Path(run["target_json_path"])
    errors = _validate_markdown(markdown_path, markdown, output)
    if errors:
        raise ClassifierError("Classification validation failed:\n- " + "\n- ".join(errors))
    _safe_write_path(markdown_path, Path(run["classification_root"]))
    _safe_write_path(json_path, Path(run["classification_root"]))
    _atomic_write_text(markdown_path, markdown)
    _atomic_write_json(json_path, output)
    if _json_load(json_path) != output:
        raise ClassifierError("Published JSON differs from the normalized output")
    run.update(
        {
            "status": "validated",
            "completed_at_local": _run_local_time(run),
            "duration_seconds": round(time.time() - float(run["started_epoch"]), 3),
            "complexity": score["complexity"],
            "counts": score["counts"],
            "markdown_sha256": _sha256_file(markdown_path),
            "json_sha256": _sha256_file(json_path),
        }
    )
    manifest_path = Path(run["classification_root"]) / "classification-manifest.json"
    project_root = Path(run["temp_output_path"]).parent
    manifest = {
        "schemaVersion": "1.0",
        "stage": "classification",
        "runId": run["run_id"],
        "status": "validated",
        "generatedAt": run["completed_at_local"],
        "input": {
            "relativePath": Path(run["input_path"]).relative_to(project_root).as_posix(),
            "sha256": run["input_sha256"],
            "bytes": Path(run["input_path"]).stat().st_size,
        },
        "artifacts": [
            {
                "relativePath": markdown_path.relative_to(project_root).as_posix(),
                "sha256": run["markdown_sha256"],
                "bytes": markdown_path.stat().st_size,
            },
            {
                "relativePath": json_path.relative_to(project_root).as_posix(),
                "sha256": run["json_sha256"],
                "bytes": json_path.stat().st_size,
            },
        ],
    }
    _validate_against_schema(
        manifest, CLASSIFICATION_MANIFEST_SCHEMA_PATH, "Classification manifest"
    )
    _safe_write_path(manifest_path, Path(run["classification_root"]))
    _atomic_write_json(manifest_path, manifest)
    run["manifest_path"] = str(manifest_path)
    run["manifest_sha256"] = _sha256_file(manifest_path)
    _write_model_cache(run, model)
    _atomic_write_json(run_path, run)
    print(
        json.dumps(
            {
                "status": "validated",
                "complexity": score["complexity"],
                "agentic_platform": model["agentic_platform"],
                "code_tier": model["code_tier"],
                "harness": model["harness"],
                "counts": score["counts"],
                "markdown": str(markdown_path),
                "json": str(json_path),
                "manifest": str(manifest_path),
                "classification_cache_hit": run["classification_cache_hit"],
                "duration_seconds": run["duration_seconds"],
            },
            indent=2,
        )
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Complexity Classifier deterministic support pipeline"
    )
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser(
        "prepare", help="Resolve input, refresh references, and prepare a model"
    )
    prepare.add_argument(
        "--config",
        required=True,
        help="lisa-config.json; analysis and output resolve from relative basePath",
    )
    prepare.add_argument("--local-time")
    prepare.add_argument(
        "--offline",
        action="store_true",
        help="Use the packaged reference manifest without network retrieval",
    )
    prepare.set_defaults(handler=_prepare)

    expand = commands.add_parser(
        "expand-research",
        help="Expand sequentially from Copilot research to Foundry or Agent Framework",
    )
    expand.add_argument("--run", required=True)
    expand.add_argument(
        "--stage",
        required=True,
        choices=["foundry", "agent-framework"],
    )
    expand.add_argument("--assessment", required=True)
    expand.set_defaults(handler=_expand_research)

    publish = commands.add_parser(
        "publish", help="Score, render, validate, publish, and cache"
    )
    publish.add_argument("--run", required=True)
    publish.add_argument("--model", required=True)
    publish.set_defaults(handler=_publish)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ClassifierError as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc)}, indent=2),
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": f"Filesystem operation failed: {exc}",
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
