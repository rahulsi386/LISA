#!/usr/bin/env python3
"""End-to-end orchestration for the Solution Designer packaged fast path."""

from __future__ import annotations

import argparse
import binascii
import copy
import hashlib
import importlib.metadata
import json
import math
import os
import re
import shutil
import subprocess
import struct
import sys
import tempfile
import time
import uuid
import zlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from validate_artifact_contracts import canonical_stage_root, validate_contract
from lisa_path_resolver import LisaConfigError, latest_file, resolve_lisa_config


VERSION = "4.1.1"
CACHE_VERSION = "5"
SKILL_ROOT = Path(__file__).resolve().parents[1]
RESOURCES = SKILL_ROOT / "resources"
ARTIFACT_CONTRACT = validate_contract(SKILL_ROOT)
SCRIPTS = SKILL_ROOT / "scripts"
MODEL_SCHEMA = RESOURCES / "design-model.schema.json"
INSPECTION_SCHEMA = RESOURCES / "inspection.schema.json"
REFERENCE_MANIFEST = RESOURCES / "reference-manifest.json"
ICON_MANIFEST = RESOURCES / "icon-manifest.json"
FAST_PATH = SCRIPTS / "Invoke-FastPath.ps1"
# Liveness guard only: terminates a hung diagram-generation subprocess.
# This is not an execution budget and does not bound how long generation may legitimately take.
GENERATION_TIMEOUT_SECONDS = 3600
LAYOUT_PROFILES = ("Balanced", "Spacious", "Wide")
DEFAULT_MAX_REPAIR_ATTEMPTS = 2
INSPECTION_CLOCK_SKEW_SECONDS = 30
EVIDENCE_ARTIFACT_NAMES = (
    "browser-evidence.json",
    "inspection-architecture.png",
    "inspection-sequence.png",
    "inspection-preview.png",
)
FINAL_ARTIFACT_NAMES = {
    "preview.html",
    "design-model.json",
    "diagram-manifest.json",
    "validation-report.json",
    "render-report.json",
    "generation-report.json",
    "inspection-report.json",
    "source-report.json",
    "candidate-report.json",
    *EVIDENCE_ARTIFACT_NAMES,
}
MODE_BY_TREATMENT = {
    "block": "blocked", "defer": "deferred", "manual-handoff": "manual",
    "simulate": "simulated", "static-sample-data": "simulated",
    "build": "real", "configure": "real", "existing": "real",
}
MODE_PRIORITY = ("blocked", "deferred", "manual", "simulated", "real")


def _conservative_mode(modes: list[str]) -> str:
    if any(mode not in MODE_PRIORITY for mode in modes):
        raise DesignerError("Unknown classified implementation mode")
    return next((mode for mode in MODE_PRIORITY if mode in modes), "real")


def _preserve_fields(source: dict, target: dict, fields: dict[str, str]) -> None:
    for original, normalized in fields.items():
        if original in source:
            target[normalized] = copy.deepcopy(source[original])


class DesignerError(RuntimeError):
    """A user-actionable designer failure."""


def _json_load(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-finite JSON constant: {value}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    except (OSError, ValueError) as exc:
        raise DesignerError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise DesignerError(f"Expected a JSON object in {path}")
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
        _replace_atomic_file(Path(temporary), path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _replace_atomic_file(source: Path, destination: Path) -> None:
    # Windows sync/indexing handles can briefly deny a file rename. Retrying the
    # same atomic operation preserves the old file; never truncate it in place.
    for attempt in range(6):
        try:
            os.replace(source, destination)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 5:
                raise
            time.sleep(0.05 * (attempt + 1))


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


def _directory_hash(path: Path) -> str:
    values = []
    for item in sorted(path.rglob("*"), key=lambda value: str(value).casefold()):
        if item.is_file():
            values.append(
                {
                    "path": str(item.relative_to(path)).replace("/", "\\"),
                    "sha256": _sha256_file(item),
                }
            )
    return _canonical_hash(values)


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(is_junction and is_junction())


def _assert_no_links(path: Path) -> None:
    absolute = _absolute(path)
    parts = absolute.parts
    current = Path(parts[0])
    for part in parts[1:]:
        current /= part
        if current.exists() and _is_link_or_junction(current):
            raise DesignerError(f"Path contains a link or junction: {current}")


def _safe_path(path: Path, design_root: Path) -> Path:
    _assert_no_links(path)
    resolved = path.resolve(strict=False)
    if not _is_within(resolved, design_root):
        raise DesignerError(f"Generated artifact escapes Design: {path}")
    return resolved


def _local_time(value: str | None) -> datetime:
    if not value:
        return datetime.now().astimezone()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DesignerError(f"Invalid authoritative local time: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DesignerError("Authoritative local time must include a UTC offset")
    return parsed


def _run_local_time(run: dict[str, Any]) -> str:
    started = datetime.fromisoformat(run["started_at_local"])
    elapsed = max(0.0, time.time() - float(run["started_epoch"]))
    return (started + timedelta(seconds=elapsed)).isoformat()


def _schema_validate(value: dict[str, Any], schema_path: Path, label: str) -> None:
    try:
        import jsonschema
    except ImportError as exc:
        raise DesignerError(
            "jsonschema is required; install the local-skills requirements.txt"
        ) from exc
    try:
        jsonschema.Draft202012Validator(_json_load(schema_path)).validate(value)
    except jsonschema.ValidationError as exc:
        location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
        raise DesignerError(
            f"{label} schema error at {location}: {exc.message}"
        ) from exc


def _validate_model_semantics(model: dict[str, Any]) -> None:
    _schema_validate(model, MODEL_SCHEMA, "Design model")
    component_ids = [item["id"] for item in model["components"]]
    if len(component_ids) != len(set(component_ids)):
        raise DesignerError("Design model component IDs must be unique")
    known_ids = set(component_ids)
    component_by_id = {item["id"]: item for item in model["components"]}
    for collection in ("relationships", "sequence"):
        identifiers = [item["id"] for item in model[collection] if "id" in item]
        if len(identifiers) != len(set(identifiers)):
            raise DesignerError(f"Design model {collection} IDs must be unique")
    orders = [item["order"] for item in model["sequence"] if "order" in item]
    if orders and (len(orders) != len(model["sequence"]) or orders != sorted(set(orders))):
        raise DesignerError("Sequence order must be explicit, unique and increasing")
    real_statuses = {"build", "configure", "existing"}
    for component in model["components"]:
        if component["implementationStatus"] in {"build", "configure"} and component["buildOwner"] == "unassigned":
            raise DesignerError(f"Buildable component lacks an assigned builder path: {component['id']}")
    for relationship in model["relationships"]:
        if relationship["from"] not in known_ids or relationship["to"] not in known_ids:
            raise DesignerError(
                "Architecture relationship references an unknown component: "
                f"{relationship['from']} -> {relationship['to']}"
            )
        if relationship["from"] == relationship["to"]:
            raise DesignerError("Architecture relationships cannot be self-referential")
        endpoint_statuses = {
            component_by_id[relationship["from"]]["implementationStatus"],
            component_by_id[relationship["to"]]["implementationStatus"],
        }
        if relationship["implementationMode"] == "real" and not endpoint_statuses.issubset(real_statuses):
            raise DesignerError(
                "A real architecture relationship cannot connect simulated, manual, deferred, or blocked components"
            )
    participants: set[str] = set()
    relationships_by_id = {item["id"]: item for item in model["relationships"] if "id" in item}
    for message in model["sequence"]:
        if message["from"] not in known_ids or message["to"] not in known_ids:
            raise DesignerError(
                "Sequence message references an unknown component: "
                f"{message['from']} -> {message['to']}"
            )
        participants.update((message["from"], message["to"]))
        same_endpoint = message["from"] == message["to"]
        if same_endpoint != (message["type"] == "self"):
            raise DesignerError("Self-call semantics require type self and identical endpoints")
        if same_endpoint and component_by_id[message["from"]]["kind"] in {"actor", "channel", "human"}:
            raise DesignerError("Self-call semantics require an executable component")
        matches = [
            item for item in model["relationships"]
            if (item["from"], item["to"]) == (message["from"], message["to"])
            or message["type"] == "response"
            and (item["to"], item["from"]) == (message["from"], message["to"])
        ]
        relationship_id = message.get("relationshipId")
        if relationship_id:
            reference = relationships_by_id.get(relationship_id)
            if reference not in matches:
                raise DesignerError(f"Sequence relationshipId {relationship_id} disagrees with its directed endpoints")
            matches = [reference]
        if not same_endpoint and not matches:
            raise DesignerError(
                "Every sequence message must map to a directed architecture relationship (reverse only for response): "
                f"{message['from']} -> {message['to']}"
            )
        if matches and any(item["implementationMode"] != message["implementationMode"] for item in matches):
            raise DesignerError("Architecture/sequence implementation modes disagree; specify an unambiguous relationshipId")
        if message["type"] not in {"response", "self"} and any(item["style"] == "response" for item in matches):
            raise DesignerError("A call or approval cannot use a response-only architecture relationship")
        if message["implementationMode"] == "real" and any(
            component_by_id[identifier]["implementationStatus"] not in real_statuses
            for identifier in (message["from"], message["to"])
        ):
            raise DesignerError("Real sequence interaction conflicts with component implementation status")
        if message["type"] == "approval" and component_by_id[message["to"]]["kind"] != "human":
            raise DesignerError("Approval action must target a classified human approval component")
        if message["implementationMode"] == "simulated" and not message["label"].lstrip().casefold().startswith("simulated:"):
            raise DesignerError(
                "Simulated sequence messages must be visibly labelled as simulated"
            )
    if len(participants) > 8:
        raise DesignerError("Sequence diagrams support at most eight participants")
    if len(participants) < 2:
        raise DesignerError("Sequence diagrams require at least two participants")
    for boundary in model.get("trustBoundaries", []):
        if not set(boundary.get("component_ids", boundary.get("componentIds", []))).issubset(known_ids):
            raise DesignerError("Trust boundary references an unknown component")
    presentation = model.get("presentation", {})
    if not set(presentation.get("primary_path", presentation.get("primaryPath", []))).issubset(known_ids):
        raise DesignerError("Presentation primary path references an unknown component")
    primary_agent = presentation.get("primary_agent_id", presentation.get("primaryAgentId"))
    if primary_agent and (primary_agent not in known_ids or component_by_id[primary_agent]["kind"] != "agent"):
        raise DesignerError("Presentation primary agent must reference an agent")
    _validate_action_controls(model)
    reference_keys = {
        item["key"] for item in _json_load(REFERENCE_MANIFEST)["sources"]
    }
    unknown_references = set(model["referenceKeys"]) - reference_keys
    if unknown_references:
        raise DesignerError(
            f"Design model references unknown guidance keys: {sorted(unknown_references)}"
        )
    if "architecture-diagrams" not in model["referenceKeys"]:
        raise DesignerError("Design model must include architecture-diagrams guidance")


def _validate_action_controls(model: dict[str, Any]) -> None:
    component_by_id = {item["id"]: item for item in model["components"]}
    relationships = {item["id"]: item for item in model["relationships"] if "id" in item}
    known_capabilities = {item["id"] for item in model.get("capabilityAssessments", [])}
    expected_controls = {
        item["id"]: {"capabilityId": item["id"], "actionImpact": item.get("action_impact"),
                     "pocTreatment": item["poc_treatment"], "buildContract": item["build_contract"]}
        for item in model.get("capabilityAssessments", []) if item.get("build_contract")
    }
    supplied_controls = {item["capabilityId"]: item for item in model.get("actionControls", [])}
    if expected_controls and supplied_controls != expected_controls:
        raise DesignerError("Normalized actionControls disagree with source capability contracts")
    if known_capabilities:
        for message in model["sequence"]:
            if message.get("capabilityId") and message["capabilityId"] not in known_capabilities:
                raise DesignerError("Sequence references an unknown capabilityId")
    for control in model.get("actionControls", []):
        capability_id = control["capabilityId"]
        contract = control.get("buildContract", {})
        high_impact = control.get("actionImpact") in {"high-impact-write", "irreversible-or-safety-critical"}
        messages = [item for item in model["sequence"] if item.get("capabilityId") == capability_id]
        if any(item.get("actionControl", contract) != contract for item in messages):
            raise DesignerError(f"Sequence actionControl disagrees with classified capability {capability_id}")
        if not high_impact and not contract.get("approval_required"):
            continue
        errors = []
        if not messages:
            errors.append("explicit capability-linked sequence")
        if not contract.get("approval_required"):
            errors.append("classified approval_required control")
        approvals = [item for item in messages if item["type"] == "approval"]
        actions = [
            item for item in messages if item["type"] == "call"
            and component_by_id[item["from"]]["kind"] not in {"actor", "channel", "human"}
            and (
                component_by_id[item["to"]]["kind"] in {"tool", "data", "integration", "external", "flow"}
                or relationships.get(item.get("relationshipId"), {}).get("access") in {"write", "read-write", "execute"}
            )
        ]
        if not approvals:
            errors.append("approval request")
        else:
            first_action = min((model["sequence"].index(item) for item in actions), default=len(model["sequence"]))
            confirmed = any(
                model["sequence"].index(approval) < model["sequence"].index(result) < first_action
                and result["type"] == "response"
                and (result["from"], result["to"]) == (approval["to"], approval["from"])
                and result.get("branchKind") == "success"
                for approval in approvals for result in messages
            )
            if not confirmed:
                errors.append("successful approval result before action")
        branches = {item.get("branchKind") for item in messages}
        required = {"rejection"} if high_impact and contract.get("approval_required") else set()
        for field, branch in (("error_result", "failure"), ("timeout_behavior", "timeout")):
            if high_impact and contract.get(field) and str(contract[field]).casefold() not in {"none", "n/a", "not applicable"}:
                required.add(branch)
        simulated = control.get("pocTreatment") in {"simulate", "static-sample-data"}
        if high_impact and (simulated or contract.get("simulation_disclosure")):
            required.add("simulation")
        errors.extend(f"{branch} branch" for branch in sorted(required - branches))
        if high_impact and simulated and not any(
            item.get("branchKind") == "simulation" and item.get("simulationDisclosure")
            for item in messages
        ):
            errors.append("explicit simulation disclosure")
        if errors:
            raise DesignerError(
                f"Classifier repair required for {capability_id}: missing " + ", ".join(errors)
                + ". No approval, branch, or external success is inferred from prose."
            )


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")
    return normalized[:70] or "Agentic_Solution"


def _component_id(value: str, existing: set[str]) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    if not base or not base[0].isalpha():
        base = "component-" + base
    base = base[:36] or "component"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base[:32]}-{suffix}"
        suffix += 1
    existing.add(candidate)
    return candidate


def _item_name(item: dict[str, Any], fallback: str) -> str:
    return str(item.get("name") or fallback).strip()


def _summary_text(classification: dict[str, Any], title: str) -> str:
    platform = classification.get("agentic_platform", "the evidenced platform")
    return (
        f"{title} uses {platform} to deliver the evidenced agent interactions, "
        "data access, controls, and human handoffs."
    )[:300]


def _diagram_title(value: str) -> str:
    title = re.sub(r"^conversational\s+", "", value.strip(), flags=re.IGNORECASE)
    return (title.title() if title.islower() else title)[:80] or "Agentic Solution"


def _product_identity(value: str) -> str:
    # Exact aliases tolerate namespace separators, not arbitrary substring matches.
    return re.sub(r"[\W_]+", "", value.casefold())


def _icon_for(
    name: str, kind: str, platform: str, product_service: str = ""
) -> str:
    manifest = _json_load(ICON_MANIFEST)
    keys = {item["key"] for item in manifest["icons"]}
    aliases: dict[str, str] = {}
    for alias, key in manifest["aliases"].items():
        normalized = _product_identity(alias)
        if key not in keys or (normalized in aliases and aliases[normalized] != key):
            raise DesignerError(f"Invalid or ambiguous product icon alias: {alias}")
        aliases[normalized] = key
    for identity in (product_service, name):
        key = aliases.get(_product_identity(identity))
        if key:
            return key
    if kind in {"actor", "human"}:
        return "users"
    return "generic-component"


def _meaningful_summary(component: dict[str, Any]) -> bool:
    text = str(
        component.get("text")
        or component.get("configuration")
        or ""
    ).strip()
    return bool(text and text.casefold() != "none evidenced")


def _identity_text(component: dict[str, Any]) -> str:
    values = [
        str(component.get("platform", "")).strip(),
        str(component.get("tool", "")).strip(),
        str(component.get("configuration", "")).strip(),
    ]
    return "; ".join(value for value in values if value)


def _reference_keys_from_classification(
    classification: dict[str, Any],
) -> list[str]:
    references = ["architecture-diagrams"]
    valid_reference_keys = {
        item["key"] for item in _json_load(REFERENCE_MANIFEST)["sources"]
    }

    def add(key: str) -> None:
        if key in valid_reference_keys and key not in references:
            references.append(key)

    platform = classification["agentic_platform"]
    values = classification["components"]
    if platform in {"Copilot Studio", "Hybrid"}:
        for key in (
            "copilot-studio-overview",
            "copilot-studio-harnesses",
            "copilot-studio-orchestration",
        ):
            add(key)
        if classification.get("harness") == "Copilot chat":
            add("m365-declarative-agents")
    if values.get("knowledge_sources") and platform in {"Copilot Studio", "Hybrid"}:
        add("copilot-studio-knowledge")
    if values.get("tools") and platform in {"Copilot Studio", "Hybrid"}:
        add("copilot-studio-tools")
    if (
        values.get("triggers") or values.get("automation")
    ) and platform in {"Copilot Studio", "Hybrid"}:
        add("copilot-studio-agent-flows")
    if values.get("connected_agents") or len(values.get("agents", [])) > 1:
        add("copilot-studio-connected-agents")
    if _meaningful_summary(values.get("authentication", {})):
        add("copilot-studio-authentication")

    all_component_text = json.dumps(values, ensure_ascii=False).casefold()
    if (
        platform == "Azure AI Foundry"
        or "foundry" in all_component_text
        or (
            platform == "Hybrid"
            and classification.get("code_tier") == "Pro-code"
        )
    ):
        add("foundry-agent-service")
    if "purview" in all_component_text:
        add("microsoft-purview")
    if "data loss" in all_component_text or "dlp" in all_component_text:
        add("power-platform-data-policies")
    if "managed environment" in all_component_text:
        add("power-platform-managed-environments")
    if "alm" in all_component_text or "lifecycle" in all_component_text:
        add("power-platform-alm")
    return references


def _build_design_model_from_topology(
    classification_path: Path,
    classification: dict[str, Any],
) -> dict[str, Any]:
    topology = classification["solution_topology"]
    topology_ids = [item["id"] for item in topology["components"]]
    if len(topology_ids) != len(set(topology_ids)):
        raise DesignerError("Classifier topology component IDs must be unique")
    for collection in ("relationships", "sequence_flows"):
        for item in topology[collection]:
            if not {item["source_id"], item["target_id"]}.issubset(topology_ids):
                raise DesignerError(f"Classifier {collection} references an unknown component")
    platform = classification["agentic_platform"]
    category_layer = {
        "actor": "users",
        "channel": "channels",
        "agent": "agent-platform",
        "agent-platform": "agent-platform",
        "knowledge-source": "agent-platform",
        "tool": "data-integration",
        "automation": "data-integration",
        "integration": "data-integration",
        "data-source": "data-integration",
        "data-store": "data-integration",
        "external-system": "data-integration",
        "identity": "governance",
        "security": "governance",
        "governance": "governance",
        "alm": "monitoring",
        "monitoring": "monitoring",
        "human-approval": "agent-platform",
    }
    category_kind = {
        "actor": "actor",
        "channel": "channel",
        "agent": "agent",
        "agent-platform": "external",
        "knowledge-source": "knowledge",
        "tool": "tool",
        "automation": "flow",
        "integration": "integration",
        "data-source": "data",
        "data-store": "data",
        "external-system": "external",
        "identity": "security",
        "security": "security",
        "governance": "security",
        "alm": "alm",
        "monitoring": "monitoring",
        "human-approval": "human",
    }
    delivery = classification.get("delivery_assessment", {})
    capabilities = delivery.get("capabilities", [])
    included_capabilities = set(
        delivery.get("poc_scope", {}).get("included_capability_ids", [])
    )
    capabilities_by_component: dict[str, list[dict[str, Any]]] = {}
    for capability in capabilities:
        for component_id in capability.get("component_ids", []):
            capabilities_by_component.setdefault(component_id, []).append(capability)

    treatment_priority = {
        "block": 7,
        "defer": 6,
        "manual-handoff": 5,
        "simulate": 4,
        "static-sample-data": 4,
        "build": 3,
        "configure": 2,
        "existing": 1,
    }
    mode_by_treatment = MODE_BY_TREATMENT

    def component_disposition(item: dict[str, Any]) -> tuple[str, str, str, str]:
        mapped = capabilities_by_component.get(item["id"], [])
        # Capabilities describe end-to-end delivery, not the shared runtime they traverse.
        # A sample-data tool must not turn its hosting agent or ingress into sample data.
        if item["category"] in {"actor", "channel", "agent", "agent-platform", "identity", "security", "governance", "alm", "monitoring", "human-approval"}:
            mapped = [value for value in mapped if value.get("component_ids") == [item["id"]]]
        explicit = item.get("implementation_status", item.get("poc_treatment"))
        if explicit is not None and explicit not in mode_by_treatment:
            raise DesignerError(f"Component {item['id']} has an invalid runtime implementation_status")
        if "implementation_status" in item and "poc_treatment" in item and item["implementation_status"] != item["poc_treatment"]:
            raise DesignerError(f"Component {item['id']} runtime implementation_status and poc_treatment disagree")
        if explicit in mode_by_treatment:
            treatment = explicit
            return (
                treatment, item.get("build_owner", "customer" if treatment == "existing" else "agent-builder"),
                item.get("poc_scope", "represented" if treatment in {"simulate", "static-sample-data", "manual-handoff"} else "excluded" if treatment in {"block", "defer"} else "included"),
                item.get("production_status", "ready" if treatment == "existing" else "requires-hardening"),
            )
        if mapped:
            selected = max(
                mapped,
                key=lambda value: treatment_priority[value["poc_treatment"]],
            )
            treatment = selected["poc_treatment"]
            owners = {value["build_owner"] for value in mapped}
            owner = owners.pop() if len(owners) == 1 else "unassigned"
            poc_scope = (
                "represented"
                if treatment in {"simulate", "static-sample-data", "manual-handoff"}
                else "included"
                if any(value["id"] in included_capabilities for value in mapped)
                else "excluded"
            )
            production_status = (
                "ready"
                if all(value["implementation_status"] in {"native", "configurable"} for value in mapped)
                else "requires-hardening"
                if any(value["implementation_status"] == "partial" for value in mapped)
                else "gap"
            )
            return treatment, owner, poc_scope, production_status
        if item["lifecycle"] == "existing":
            return "existing", "customer", "included", "ready"
        return ("build" if item["lifecycle"] == "build" else "configure"), item.get("build_owner", "agent-builder"), "included", "requires-hardening"

    component_modes: dict[str, str] = {}
    design_components = []
    for item in topology["components"]:
        treatment, owner, poc_scope, production_status = component_disposition(item)
        owner = item.get("build_owner", owner)
        poc_scope = item.get("poc_scope", poc_scope)
        production_status = item.get("production_status", production_status)
        component_modes[item["id"]] = mode_by_treatment[treatment]
        visual_status = (
            "existing"
            if treatment == "existing"
            else "tbd"
            if treatment in {"manual-handoff", "defer", "block"}
            else "to-create"
        )
        members = list(
            dict.fromkeys(
                value
                for value in (
                    item["product_service"],
                    item["hosting_runtime"],
                    *item.get("inventory_names", []),
                )
                if value and value.casefold() != item["name"].casefold()
            )
        )
        component = {
            "id": item["id"],
            "name": item["name"],
            "layer": category_layer[item["category"]],
            "kind": category_kind[item["category"]],
            "status": visual_status,
            "implementationStatus": treatment,
            "buildOwner": owner,
            "pocScope": poc_scope,
            "productionStatus": production_status,
            "iconKey": _icon_for(
                item["name"],
                category_kind[item["category"]],
                platform,
                product_service=item["product_service"],
            ),
            "description": (
                f"{item['role']} Runtime: {item['hosting_runtime']}. "
                f"Boundary: {item['deployment_boundary']}."
            ),
            "roleDescription": item["role"],
            "productService": item["product_service"],
            "hostingRuntime": item["hosting_runtime"],
            "deploymentBoundary": item["deployment_boundary"],
        }
        _preserve_fields(item, component, {
            "inventory_names": "inventoryNames", "component_type": "componentType",
            "lifecycle": "lifecycle", "category": "sourceCategory",
            "environment_scope": "environmentScope", "visual_role": "visualRole",
            "visual_group": "visualGroup", "presentation": "presentation",
            "reliability": "reliability", "scalability": "scalability", "security": "security",
            "reference_ids": "referenceIds", "source_refs": "sourceRefs",
        })
        mapped_ids = [value["id"] for value in capabilities_by_component.get(item["id"], [])]
        component["capabilityIds"] = mapped_ids
        if "allowed_tools" in delivery:
            component["allowedToolScope"] = {
                "allowedTools": copy.deepcopy(delivery["allowed_tools"]),
                "capabilityIds": mapped_ids,
                "allowedProducts": list(dict.fromkeys(
                    value["allowed_product"] for value in capabilities_by_component.get(item["id"], [])
                    if value.get("allowed_product")
                )),
            }
        gaps = [gap for gap in delivery.get("production_readiness_gaps", []) if set(gap.get("capability_ids", [])) & set(mapped_ids)]
        if gaps:
            component["productionGaps"] = copy.deepcopy(gaps)
        if members:
            component["members"] = members
        if item["evidence_ids"]:
            component["evidenceIds"] = item["evidence_ids"]
        design_components.append(component)

    style_by_type = {
        "responds": "response",
        "approves": "optional",
        "protects": "optional",
        "governs": "optional",
        "deploys": "optional",
        "monitors": "optional",
    }
    relationships = []
    relationship_sources = topology["relationships"]
    flow_sources = sorted(topology["sequence_flows"], key=lambda value: value["order"])
    capabilities_by_id = {value["id"]: value for value in capabilities}

    def matching_relationship(flow: dict) -> int | None:
        if flow["message_type"] == "self":
            if flow.get("relationship_id"):
                raise DesignerError("Self-call cannot reference an architecture relationship")
            return None
        candidates = [
            index for index, relation in enumerate(relationship_sources)
            if (relation["source_id"], relation["target_id"]) == (flow["source_id"], flow["target_id"])
        ]
        if flow["message_type"] == "response" and (not candidates or flow.get("relationship_id")):
            candidates += [
                index for index, relation in enumerate(relationship_sources)
                if (relation["target_id"], relation["source_id"]) == (flow["source_id"], flow["target_id"])
                and index not in candidates
            ]
        if flow.get("relationship_id"):
            candidates = [index for index in candidates if relationship_sources[index].get("id") == flow["relationship_id"]]
        elif len(candidates) > 1:
            exact = [index for index in candidates if relationship_sources[index]["interaction"] == flow["action"]]
            if exact:
                candidates = exact
        if len(candidates) != 1:
            raise DesignerError(f"Classifier repair required: sequence {flow.get('id', flow['order'])} needs one directed relationship_id")
        return candidates[0]

    flow_relationships = [matching_relationship(flow) for flow in flow_sources]

    def flow_capability(flow: dict) -> dict | None:
        if flow.get("capability_id"):
            if flow["capability_id"] not in capabilities_by_id:
                raise DesignerError(f"Unknown sequence capability_id: {flow['capability_id']}")
            return capabilities_by_id[flow["capability_id"]]
        matches = [
            value for value in capabilities
            if {flow["source_id"], flow["target_id"]}.issubset(value.get("component_ids", []))
        ]
        return max(matches, key=lambda value: (treatment_priority[value["poc_treatment"]], value["id"])) if matches else None

    for index, item in enumerate(relationship_sources):
        linked_flows = [flow for flow, link in zip(flow_sources, flow_relationships) if link == index]
        explicit_modes = [
            value["implementation_mode"] for value in [item, *linked_flows]
            if "implementation_mode" in value
        ]
        if len(set(explicit_modes)) > 1:
            raise DesignerError(f"Architecture/sequence implementation modes disagree for {item.get('id', index)}")
        mapped_modes = [
            mode_by_treatment[capability["poc_treatment"]]
            for flow in linked_flows if (capability := flow_capability(flow))
        ]
        mode = explicit_modes[0] if explicit_modes else _conservative_mode(
            mapped_modes + [component_modes[item["source_id"]], component_modes[item["target_id"]]]
        )
        label = item["interaction"]
        if mode == "simulated" and not label.lstrip().casefold().startswith("simulated:"):
            label = f"Simulated: {label}"
        relationship = {
            "id": item.get("id", f"legacy-rel-{index + 1:03d}"),
            "from": item["source_id"],
            "to": item["target_id"],
            "label": label,
            "style": style_by_type.get(item["relationship_type"], "call"),
            "implementationMode": mode,
            "relationshipType": item["relationship_type"],
        }
        _preserve_fields(item, relationship, {
            "direction": "direction", "integration_method": "integrationMethod",
            "protocol": "protocol", "data_flow": "dataFlow", "access": "access",
            "authentication": "authentication", "synchronous": "synchronous",
            "failure_behavior": "failureBehavior", "reference_ids": "referenceIds",
            "source_refs": "sourceRefs", "presentation": "presentation",
        })
        if item["evidence_ids"]:
            relationship["evidenceIds"] = item["evidence_ids"]
        relationships.append(relationship)

    sequence = []
    for item, relation_index in zip(flow_sources, flow_relationships):
        matching_capability = flow_capability(item)
        mode = relationships[relation_index]["implementationMode"] if relation_index is not None else item.get(
            "implementation_mode", component_modes[item["source_id"]]
        )
        action = item["action"]
        if mode == "simulated" and not action.lstrip().casefold().startswith("simulated:"):
            action = f"Simulated: {action}"
        message = {
            "id": item.get("id", f"legacy-seq-{item['order']:03d}"),
            "order": item["order"],
            "from": item["source_id"],
            "to": item["target_id"],
            "label": action,
            "type": item["message_type"],
            "implementationMode": mode,
            "capabilityId": matching_capability["id"] if matching_capability else None,
            "relationshipId": relationships[relation_index]["id"] if relation_index is not None else None,
            "condition": item["condition"],
            "phase": item["phase"],
            "fragment": (
                f"alt [{item['condition']}]" if item["condition"] else None
            ),
        }
        _preserve_fields(item, message, {
            "branch_kind": "branchKind", "simulation_disclosure": "simulationDisclosure",
            "reference_ids": "referenceIds", "source_refs": "sourceRefs",
            "presentation": "presentation",
        })
        if matching_capability and matching_capability.get("build_contract"):
            message["actionControl"] = copy.deepcopy(matching_capability["build_contract"])
        if item["evidence_ids"]:
            message["evidenceIds"] = item["evidence_ids"]
        sequence.append(message)

    agent_components = [
        item for item in topology["components"] if item["category"] == "agent"
    ]
    title = (
        agent_components[0]["name"]
        if agent_components
        else "Agentic Solution"
    )
    model = {
        "scenarioSlug": _slug(title),
        "title": title,
        "summary": topology["architecture_summary"],
        "complexity": classification["complexity"],
        "coverage": {
            "nativeBuildPercent": classification.get("coverage", {}).get("native_build_percent", 0),
            "pocDemonstrationPercent": classification.get("coverage", {}).get("poc_demonstration_percent", 0),
            "unsupportedPercent": classification.get("coverage", {}).get("unsupported_percent", 0),
            "unknownPercent": classification.get("coverage", {}).get("unknown_percent", 0),
        },
        "sourceClassification": str(classification_path),
        "sourceClassificationSha256": _sha256_file(classification_path),
        "referenceKeys": _reference_keys_from_classification(classification),
        "components": design_components,
        "relationships": relationships,
        "sequence": sequence,
    }
    _preserve_fields(topology, model, {
        "trust_boundaries": "trustBoundaries", "environments": "environments",
        "architecture_principles": "architecturePrinciples", "presentation": "presentation",
    })
    _preserve_fields(delivery, model, {
        "allowed_tools": "allowedTools", "poc_scope": "pocScope",
        "production_readiness_gaps": "productionReadinessGaps", "capabilities": "capabilityAssessments",
    })
    model["actionControls"] = [
        {"capabilityId": value["id"], "actionImpact": value.get("action_impact"),
         "pocTreatment": value["poc_treatment"], "buildContract": copy.deepcopy(value["build_contract"])}
        for value in capabilities if value.get("build_contract")
    ]
    _validate_model_semantics(model)
    return model


def _build_design_model(
    classification_path: Path, classification: dict[str, Any]
) -> dict[str, Any]:
    required = {
        "complexity",
        "agentic_platform",
        "harness",
        "code_tier",
        "components",
    }
    missing = sorted(required - set(classification))
    if missing:
        raise DesignerError(
            "Classification JSON is missing fields: " + ", ".join(missing)
        )
    if classification.get("solution_topology"):
        return _build_design_model_from_topology(
            classification_path, classification
        )
    source_hash = _sha256_file(classification_path)
    components_value = classification["components"]
    agent_items = components_value.get("agents", [])
    platform_capabilities = components_value.get(
        "platform_capabilities", []
    )
    source_agent_name = (
        _item_name(agent_items[0], "Agentic Solution")
        if agent_items
        else "Agentic Solution"
    )
    primary_name = source_agent_name
    title = _diagram_title(primary_name)
    platform = classification["agentic_platform"]
    existing_ids: set[str] = set()
    components: list[dict[str, Any]] = []

    def add_component(
        name: str,
        layer: str,
        kind: str,
        status: str,
        description: str,
        icon_key: str | None = None,
        members: list[str] | None = None,
        evidence_ids: list[str] | None = None,
        implementation_status: str | None = None,
        build_owner: str | None = None,
        poc_scope: str = "included",
        production_status: str = "requires-hardening",
    ) -> str:
        identifier = _component_id(name, existing_ids)
        component = {
                "id": identifier,
                "name": name,
                "layer": layer,
                "kind": kind,
                "status": status,
                "implementationStatus": implementation_status or (
                    "existing" if status == "existing" else "configure" if status == "to-create" else "defer"
                ),
                "buildOwner": build_owner or (
                    "customer" if status == "existing" else "agent-builder" if status == "to-create" else "unassigned"
                ),
                "pocScope": poc_scope,
                "productionStatus": production_status,
                "iconKey": icon_key or _icon_for(name, kind, platform),
                "description": description[:140],
            }
        if members:
            component["members"] = list(dict.fromkeys(members))
        if evidence_ids:
            component["evidenceIds"] = list(dict.fromkeys(evidence_ids))
        components.append(component)
        return identifier

    def item_evidence(items: list[dict[str, Any]]) -> list[str]:
        return list(
            dict.fromkeys(
                identifier
                for item in items
                for identifier in item.get("evidence_ids", [])
            )
        )

    actor_id = add_component(
        "User / Requester",
        "users",
        "actor",
        "tbd",
        "Actor is not explicitly named in the classification",
        "users",
        implementation_status="existing",
        build_owner="customer",
        production_status="ready",
    )
    agent_id = add_component(
        primary_name,
        "agent-platform",
        "agent",
        "to-create",
        f"{platform}; {classification['harness'] or 'no harness'}; instructions and orchestration",
        members=[
            _item_name(item, "Platform capability")
            for item in platform_capabilities
        ],
        evidence_ids=item_evidence(
            agent_items[:1] + platform_capabilities
        ),
    )

    channel_ids: list[str] = []
    for item in components_value.get("communication_channels", []):
        name = _item_name(item, "Evidenced Channel")
        channel_ids.append(
            add_component(
                name,
                "channels",
                "channel",
                "existing",
                "Evidenced interaction channel",
                members=[name],
                evidence_ids=item_evidence([item]),
            )
        )

    knowledge_id = None
    knowledge = components_value.get("knowledge_sources", [])
    if knowledge:
        names = [_item_name(item, "Knowledge source") for item in knowledge]
        knowledge_id = add_component(
            "Knowledge Sources" if len(names) > 1 else names[0],
            "agent-platform",
            "knowledge",
            "existing",
            f"{len(names)} evidenced sources used for grounding",
            members=names,
            evidence_ids=item_evidence(knowledge),
        )

    tool_id = None
    tools = components_value.get("tools", [])
    if tools:
        tool_names = [_item_name(item, "Evidenced Tool") for item in tools]
        name = tool_names[0] if len(tool_names) == 1 else "Agent Tools and Services"
        tool_id = add_component(
            name,
            "data-integration",
            "tool",
            "to-create",
            f"{len(tool_names)} evidenced tools or services",
            members=tool_names,
            evidence_ids=item_evidence(tools),
        )

    data_id = None
    data_items = components_value.get("data", [])
    if data_items:
        names = [_item_name(item, "Data source") for item in data_items]
        data_id = add_component(
            "Data Sources and Stores" if len(names) > 1 else names[0],
            "data-integration",
            "data",
            "existing",
            f"{len(names)} evidenced data sources or stores",
            members=names,
            evidence_ids=item_evidence(data_items),
        )

    automation_id = None
    automation = (
        components_value.get("triggers", [])
        + components_value.get("automation", [])
    )
    if automation:
        names = [_item_name(item, "Automation") for item in automation]
        automation_id = add_component(
            "Automation and Triggers" if len(names) > 1 else names[0],
            "data-integration",
            "flow",
            "to-create",
            f"{len(names)} evidenced automations or triggers",
            members=names,
            evidence_ids=item_evidence(automation),
        )

    integration_id = None
    integrations = components_value.get("integration", [])
    if integrations:
        names = [_item_name(item, "Integration") for item in integrations]
        integration_id = add_component(
            "Integration Endpoints" if len(names) > 1 else names[0],
            "data-integration",
            "integration",
            "tbd",
            f"{len(names)} evidenced integration boundaries",
            members=names,
            evidence_ids=item_evidence(integrations),
        )

    connected_id = None
    delegated = (
        components_value.get("connected_agents", [])
        + agent_items[1:]
    )
    if delegated:
        names = [_item_name(item, "Connected agent") for item in delegated]
        connected_id = add_component(
            "Connected Agents" if len(names) > 1 else names[0],
            "agent-platform",
            "agent",
            "to-create",
            "; ".join(names[:3]),
            members=names,
            evidence_ids=item_evidence(delegated),
        )

    skill_id = None
    skills = components_value.get("skills", [])
    if skills:
        names = [_item_name(item, "Skill") for item in skills]
        skill_id = add_component(
            "Agent Skills" if len(names) > 1 else names[0],
            "agent-platform",
            "tool",
            "to-create",
            "; ".join(names[:3]),
            members=names,
            evidence_ids=item_evidence(skills),
        )

    human_id = None
    authz = components_value.get("authorization", {})
    governance = components_value.get("governance", {})
    governance_controls = components_value.get("governance_controls", [])
    human_text = (
        f"{_identity_text(authz)} "
        + " ".join(_item_name(item, "") for item in governance_controls)
    )
    if re.search(r"\b(human|approval|approver|legal|officer)\b", human_text, re.I):
        human_id = add_component(
            "Human Approval Authorities",
            "agent-platform",
            "human",
            "existing",
            "Human approval and Legal review boundaries",
            "users",
            evidence_ids=list(
                dict.fromkeys(
                    authz.get("evidence_ids", [])
                    + governance.get("evidence_ids", [])
                )
            ),
        )

    governance_id = None
    security = components_value.get("security", {})
    security_controls = components_value.get("security_controls", [])
    auth = components_value.get("authentication", {})
    auth_text = _identity_text(auth) or str(auth.get("text", ""))
    auth_evidenced = _meaningful_summary(auth) and not re.search(
        r"\b(not specified|none evidenced|not evidenced)\b",
        auth_text,
        re.IGNORECASE,
    )
    governance_text = " ".join(
        [
            _identity_text(auth),
            _identity_text(authz),
            str(security.get("text", "")),
            str(governance.get("text", "")),
            "; ".join(_item_name(item, "") for item in security_controls),
            "; ".join(_item_name(item, "") for item in governance_controls),
        ]
    ).strip()
    if governance_text:
        governance_members = list(
            dict.fromkeys(
                [
                    value
                    for value in (
                        str(auth.get("platform", "")).strip(),
                        str(auth.get("tool", "")).strip(),
                        str(authz.get("platform", "")).strip(),
                        str(authz.get("tool", "")).strip(),
                    )
                    if value
                ]
                + [
                    _item_name(item, "")
                    for item in security_controls + governance_controls
                    if _item_name(item, "")
                ]
            )
        )
        governance_id = add_component(
            "Identity, Security, and Governance",
            "governance",
            "security",
            "existing" if auth_evidenced else "tbd",
            (
                "Authentication TBD; policy compliance and approvals governed"
                if not auth_evidenced
                else f"{len(governance_members)} explicit identity, security, and governance tools"
            ),
            members=governance_members,
            evidence_ids=list(
                dict.fromkeys(
                    auth.get("evidence_ids", [])
                    + authz.get("evidence_ids", [])
                    + [
                        evidence_id
                        for item in security_controls + governance_controls
                        for evidence_id in item.get("evidence_ids", [])
                    ]
                )
            ),
        )

    alm_id = None
    alm_items = components_value.get("alm", [])
    if alm_items:
        alm_names = [_item_name(item, "ALM control") for item in alm_items]
        alm_id = add_component(
            "Application Lifecycle Management",
            "monitoring",
            "alm",
            "to-create",
            f"{len(alm_names)} evidenced or mandatory ALM controls",
            members=alm_names,
            evidence_ids=item_evidence(alm_items),
        )

    relationships: list[dict[str, str]] = []

    def interaction_mode(source: str, target: str) -> str:
        statuses = {
            item["implementationStatus"]
            for item in components
            if item["id"] in {source, target}
        }
        if "block" in statuses:
            return "blocked"
        if "defer" in statuses:
            return "deferred"
        if "manual-handoff" in statuses:
            return "manual"
        if statuses & {"simulate", "static-sample-data"}:
            return "simulated"
        return "real"

    def relationship(
        source: str, target: str, label: str, style: str = "call"
    ) -> None:
        if source and target and source != target:
            mode = interaction_mode(source, target)
            visible_label = (
                f"Simulated: {label}" if mode == "simulated" else label
            )
            relationships.append(
                {"id": f"legacy-rel-{len(relationships) + 1:03d}", "from": source, "to": target, "label": visible_label, "style": style, "implementationMode": mode}
            )

    if channel_ids:
        for channel_id in channel_ids:
            relationship(actor_id, channel_id, "Conversation")
            relationship(channel_id, agent_id, "User request")
    else:
        relationship(actor_id, agent_id, "User request")
    if knowledge_id:
        relationship(agent_id, knowledge_id, "Grounded retrieval")
    if tool_id:
        relationship(agent_id, tool_id, "Tool or service call")
    if tool_id and data_id:
        relationship(tool_id, data_id, "Read or update data")
    elif data_id:
        relationship(agent_id, data_id, "Read required data")
    if automation_id:
        relationship(automation_id, agent_id, "Scheduled monitoring")
    if integration_id:
        relationship(tool_id or agent_id, integration_id, "System integration")
    if connected_id:
        relationship(agent_id, connected_id, "Delegate work")
    if skill_id:
        relationship(agent_id, skill_id, "Apply structured skill")
    if human_id:
        relationship(agent_id, human_id, "Approval or review request", "optional")
    if governance_id:
        relationship(governance_id, agent_id, "Guardrails and controls", "optional")
        if auth_evidenced:
            relationship(actor_id, governance_id, "Authenticate user")
    if alm_id:
        relationship(alm_id, agent_id, "Lifecycle and deployment controls", "optional")
    relationship(agent_id, actor_id, "Grounded response", "response")

    sequence: list[dict[str, Any]] = []

    def message(
        source: str,
        target: str,
        label: str,
        message_type: str,
        phase: str,
        fragment: str | None = None,
    ) -> None:
        mode = interaction_mode(source, target)
        visible_label = (
            f"Simulated: {label}" if mode == "simulated" else label
        )
        item: dict[str, Any] = {
            "id": f"legacy-seq-{len(sequence) + 1:03d}",
            "order": len(sequence) + 1,
            "from": source,
            "to": target,
            "label": visible_label,
            "type": message_type,
            "implementationMode": mode,
            "capabilityId": None,
            "phase": phase[:40],
            "fragment": fragment,
        }
        if message_type != "self":
            matches = [relation for relation in relationships if (relation["from"], relation["to"]) == (source, target)]
            if not matches and message_type == "response":
                matches = [relation for relation in relationships if (relation["to"], relation["from"]) == (source, target)]
            if matches:
                item["relationshipId"] = matches[0]["id"]
        sequence.append(item)

    if auth_evidenced:
        message(actor_id, governance_id, "Authenticate user", "call", "Authentication")
        message(governance_id, actor_id, "Return authenticated session", "response", "Authentication")
    message(actor_id, channel_ids[0] if channel_ids else agent_id, "Submit request", "call", "Request")
    if channel_ids:
        message(channel_ids[0], agent_id, "Deliver request", "call", "Request")
    message(agent_id, agent_id, "Plan grounded response", "self", "Orchestration")
    if knowledge_id:
        message(agent_id, knowledge_id, "Retrieve grounded knowledge", "call", "Grounding")
        message(knowledge_id, agent_id, "Return grounded evidence", "response", "Grounding")
    if automation_id:
        current_participants = {
            identifier
            for item in sequence
            for identifier in (item["from"], item["to"])
        }
        future_participants = {
            identifier
            for identifier in (
                tool_id,
                data_id,
                connected_id,
                human_id,
                integration_id if not tool_id else None,
            )
            if identifier
        }
        if len(current_participants | future_participants | {automation_id}) <= 8:
            message(
                automation_id,
                agent_id,
                "Trigger automated cycle",
                "call",
                "Automation",
            )
        else:
            message(
                agent_id,
                agent_id,
                "Handle scheduled or event trigger",
                "self",
                "Automation",
            )
    if tool_id:
        message(agent_id, tool_id, "Invoke tool or service", "call", "Action")
    if tool_id and data_id:
        message(tool_id, data_id, "Read required records", "call", "Action")
        message(data_id, tool_id, "Return data results", "response", "Action")
        message(tool_id, agent_id, "Return action results", "response", "Action")
    if integration_id and not tool_id:
        message(agent_id, integration_id, "Invoke integration", "call", "Action")
        message(integration_id, agent_id, "Return integration result", "response", "Action")
    if connected_id:
        message(agent_id, connected_id, "Delegate specialist work", "call", "Delegation")
        message(connected_id, agent_id, "Return delegated result", "response", "Delegation")
    if human_id:
        message(
            agent_id,
            human_id,
            "Request governed decision",
            "approval",
            "Human decision",
        )
        message(human_id, agent_id, "Return decision", "response", "Human decision")
    message(agent_id, actor_id, "Return response", "response", "Response")
    references = _reference_keys_from_classification(classification)

    model = {
        "scenarioSlug": _slug(primary_name),
        "title": title,
        "summary": _summary_text(classification, title),
        "complexity": classification["complexity"],
        "coverage": {
            "nativeBuildPercent": classification.get("coverage", {}).get("native_build_percent", 0),
            "pocDemonstrationPercent": classification.get("coverage", {}).get("poc_demonstration_percent", 0),
            "unsupportedPercent": classification.get("coverage", {}).get("unsupported_percent", 0),
            "unknownPercent": classification.get("coverage", {}).get("unknown_percent", 0),
        },
        "sourceClassification": str(classification_path),
        "sourceClassificationSha256": source_hash,
        "referenceKeys": references,
        "components": components,
        "relationships": relationships,
        "sequence": sequence,
    }
    delivery = classification.get("delivery_assessment", {})
    _preserve_fields(delivery, model, {
        "allowed_tools": "allowedTools", "poc_scope": "pocScope",
        "production_readiness_gaps": "productionReadinessGaps", "capabilities": "capabilityAssessments",
    })
    if delivery.get("capabilities"):
        model["actionControls"] = [
            {"capabilityId": value["id"], "actionImpact": value.get("action_impact"),
             "pocTreatment": value["poc_treatment"], "buildContract": copy.deepcopy(value["build_contract"])}
            for value in delivery["capabilities"] if value.get("build_contract")
        ]
    _validate_model_semantics(model)
    return model


def _validate_license_provenance(manifest: dict[str, Any]) -> dict[str, str]:
    licenses = {}
    packs = manifest.get("packs", {})
    if not isinstance(packs, dict):
        raise DesignerError("Packaged icon manifest packs must be an object")
    for pack, metadata in packs.items():
        if not isinstance(metadata, dict):
            raise DesignerError(f"Packaged icon pack metadata is invalid: {pack}")
        for prefix in ("license", "repositoryLicense"):
            file_key, hash_key = prefix + "File", prefix + "Sha256"
            if file_key not in metadata and hash_key not in metadata:
                continue
            name, expected = metadata.get(file_key), metadata.get(hash_key)
            if not isinstance(name, str) or not name or not isinstance(expected, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
                raise DesignerError(f"Packaged license provenance metadata is incomplete: {pack}")
            path = _safe_path(RESOURCES / name, RESOURCES)
            if not path.is_file():
                raise DesignerError(f"Packaged license is missing: {pack} ({name})")
            actual = _sha256_file(path)
            if actual != expected.lower():
                raise DesignerError(
                    f"Packaged license provenance hash mismatch: {pack} ({name}); "
                    f"expected {expected.lower()}, got {actual}"
                )
            licenses[name] = actual
    return licenses


def _resource_hashes() -> dict[str, str]:
    try:
        networkx_version = importlib.metadata.version("networkx")
    except importlib.metadata.PackageNotFoundError as exc:
        raise DesignerError("NetworkX is required; install the Agency Python prerequisites before running design.") from exc
    manifest = _json_load(ICON_MANIFEST)
    licenses = _validate_license_provenance(manifest)
    for icon in manifest["icons"]:
        icon_path = RESOURCES / icon["file"]
        if not _is_within(icon_path, RESOURCES / "icons"):
            raise DesignerError(f"Icon asset escapes the packaged icon directory: {icon['key']}")
        _assert_no_links(icon_path)
        if not icon_path.is_file():
            raise DesignerError(f"Packaged icon is missing: {icon['key']}")
        if icon.get("sha256") and _sha256_file(icon_path) != icon["sha256"]:
            raise DesignerError(f"Packaged icon provenance hash mismatch: {icon['key']}")
    files = [
        RESOURCES / "artifact-contract.json",
        MODEL_SCHEMA,
        INSPECTION_SCHEMA,
        REFERENCE_MANIFEST,
        ICON_MANIFEST,
        FAST_PATH,
        SCRIPTS / "New-Diagrams.ps1",
        SCRIPTS / "Render-Diagrams.ps1",
        SCRIPTS / "Test-Diagrams.ps1",
        SCRIPTS / "source_artifacts.py",
        SCRIPTS / "inspect_preview.js",
    ]
    return {
        **{path.name: _sha256_file(path) for path in files},
        "icons": _directory_hash(RESOURCES / "icons"),
        "license_provenance": _canonical_hash(licenses),
        "layout_engine": _sha256_file(SCRIPTS / "layout_engine.py"),
        "networkx_version": networkx_version,
        "renderer": _directory_hash(SKILL_ROOT / "renderer"),
        "orchestrator": _sha256_file(Path(__file__).resolve()),
    }


def _cache_key(classification: Path, model: dict[str, Any]) -> str:
    return _canonical_hash(
        {
            "version": CACHE_VERSION,
            "classification": _sha256_file(classification),
            "model": _canonical_hash(model),
            "resources": _resource_hashes(),
        }
    )


def _safe_artifact_name(name: str) -> bool:
    return (
        isinstance(name, str) and bool(name) and name not in {".", ".."}
        and not any(character in name for character in ("/", "\\", ":"))
        and Path(name).name == name and not Path(name).is_absolute()
    )


def _validate_source_artifacts(root: Path) -> None:
    model = _json_load(root / "design-model.json")
    for name in (f"Design_{model['scenarioSlug']}.drawio", f"SA_{model['scenarioSlug']}.mmd",
                 f"SD_{model['scenarioSlug']}.mmd", "source-report.json"):
        path = _safe_path(root / name, root)
        if not path.is_file() or not path.stat().st_size:
            raise DesignerError(f"Editable source artifact missing: {name}")
    try:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / "source_artifacts.py"), "validate",
             "--model", str(root / "design-model.json"), "--output", str(root)],
            capture_output=True, text=True, check=False, timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise DesignerError("Editable source validation timed out") from exc
    if completed.returncode:
        raise DesignerError("Editable source validation failed: " + (completed.stderr or completed.stdout).strip())
    try:
        result = json.loads(completed.stdout)
    except (ValueError, TypeError) as exc:
        raise DesignerError("Editable source validator did not return a validation report") from exc
    if not isinstance(result, dict) or result.get("validation") != "passed":
        raise DesignerError("Editable source validation did not pass")


def _cache_valid(
    cache_dir: Path, cache_key: str, expected_artifacts: set[str]
) -> bool:
    manifest_path = cache_dir / "cache-manifest.json"
    if not manifest_path.exists():
        return False
    try:
        _assert_no_links(manifest_path)
        manifest = _json_load(manifest_path)
    except DesignerError:
        return False
    if manifest.get("cache_key") != cache_key:
        return False
    if not isinstance(manifest.get("artifacts"), dict):
        return False
    artifact_names = set(manifest["artifacts"])
    if artifact_names != expected_artifacts:
        return False
    for name, expected_hash in manifest.get("artifacts", {}).items():
        if not _safe_artifact_name(name):
            return False
        try:
            artifact = _safe_path(cache_dir / name, cache_dir)
        except DesignerError:
            return False
        if not _is_within(artifact, cache_dir):
            return False
        if not artifact.exists() or _sha256_file(artifact) != expected_hash:
            return False
    inspection = cache_dir / "inspection-report.json"
    if not inspection.exists():
        return False
    try:
        value = _json_load(inspection)
        _schema_validate(value, INSPECTION_SCHEMA, "Cached inspection")
        if value["status"] != "passed" or value["issues"] or not all(value["checks"].values()):
            return False
        model = _json_load(cache_dir / "design-model.json")
        _validate_model_semantics(model)
        _validate_source_artifacts(cache_dir)
        _candidate_ranking(cache_dir, _json_load(cache_dir / "generation-report.json"))
        slug = model["scenarioSlug"]
        if (
            value["solution_architecture_png_sha256"] != _sha256_file(cache_dir / f"SA_{slug}.png")
            or value["sequence_png_sha256"] != _sha256_file(cache_dir / f"SD_{slug}.png")
            or _json_load(cache_dir / "generation-report.json").get("structuralValidation") != "passed"
        ):
            return False
        _validate_browser_evidence(cache_dir, value, _json_load(cache_dir / "generation-report.json").get("inspectionContext"))
    except (DesignerError, OSError, KeyError, TypeError):
        return False
    return True


def _inspection_template(run_id: str, revision: int = 0) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "revision": revision,
        "inspected_at": "",
        "status": "failed",
        "solution_architecture_png_sha256": "0" * 64,
        "sequence_png_sha256": "0" * 64,
        "checks": {
            name: False
            for name in _json_load(INSPECTION_SCHEMA)["properties"]["checks"]["required"]
        },
        "issues": ["Inspection not completed."],
        "summary": "Inspect both rendered PNGs and the HTML preview before finalization.",
    }


def _prepare(args: argparse.Namespace) -> int:
    started_epoch = time.time()
    started = _local_time(args.local_time)
    try:
        paths = resolve_lisa_config(Path(args.config))
        classification = latest_file(
            paths.classification,
            "complexity-classification_*.json",
            "complexity-classification JSON",
            r"complexity-classification_[0-9]{8}_[0-9]{6}(?:_[0-9]{3})?\.json",
        )
    except LisaConfigError as exc:
        raise DesignerError(str(exc)) from exc
    classification_value = _json_load(classification)
    temp_output = paths.output.resolve()
    _assert_no_links(temp_output)
    design_root = canonical_stage_root(temp_output, ARTIFACT_CONTRACT["rootFolder"])
    _safe_path(design_root, design_root)
    if design_root.parent != temp_output.resolve():
        raise DesignerError("design must be a direct child of tempOutputPath")

    model = _build_design_model(classification, classification_value)
    cache_key = _cache_key(classification, model)
    internal = design_root / ".solution-designer"
    run_id = (
        f"SDR-{started.strftime('%Y%m%d_%H%M%S')}-"
        f"{_sha256_file(classification)[:8].upper()}-"
        f"{uuid.uuid4().hex[:8].upper()}"
    )
    run_dir = internal / "runs" / run_id
    stage_parent = design_root / ".staging" / _sha256_bytes(
        run_id.encode("utf-8")
    )[:10]
    stage_design = stage_parent / "design"
    cache_dir = internal / "cache" / f"v{CACHE_VERSION}" / cache_key
    for directory in (run_dir, stage_design, cache_dir.parent):
        _safe_path(directory, design_root)
        directory.mkdir(parents=True, exist_ok=True)
    model_path = stage_design / "design-model.json"
    _atomic_write_json(model_path, model)

    run_path = run_dir / "run.json"
    inspection_template_path = run_dir / "inspection-template.json"
    expected_cache_artifacts = set(
        _artifact_names(stage_design, model["scenarioSlug"])
        + ["generation-report.json", "inspection-report.json", *EVIDENCE_ARTIFACT_NAMES]
    )
    cache_hit = _cache_valid(
        cache_dir, cache_key, expected_cache_artifacts
    )
    _atomic_write_json(inspection_template_path, _inspection_template(run_id))
    run = {
        "schema_version": "1.0",
        "skill_version": VERSION,
        "run_id": run_id,
        "started_epoch": started_epoch,
        "started_at_local": started.isoformat(),
        "classification_path": str(classification),
        "classification_sha256": _sha256_file(classification),
        "temp_output_path": str(temp_output.resolve()),
        "design_root": str(design_root),
        "run_directory": str(run_dir),
        "stage_parent": str(stage_parent),
        "stage_design": str(stage_design),
        "model_path": str(model_path),
        "model_sha256": _sha256_file(model_path),
        "inspection_template_path": str(inspection_template_path),
        "cache_key": cache_key,
        "cache_directory": str(cache_dir),
        "cache_hit": cache_hit,
        "expected_cache_artifacts": sorted(expected_cache_artifacts),
        "resource_hashes": _resource_hashes(),
        "model_ms": round((time.time() - started_epoch) * 1000),
        "max_repair_attempts": getattr(args, "max_repair_attempts", DEFAULT_MAX_REPAIR_ATTEMPTS),
        "repair_attempts": [],
        "revision": 0,
        "attempted_layout_profiles": [],
        "passing_layout_profiles": [],
        "selected_layout_profiles": [],
        "inspected_layout_profiles": [],
        "status": "prepared",
    }
    _atomic_write_json(run_path, run)
    print(
        json.dumps(
            {
                "status": "prepared",
                "run": str(run_path),
                "design_model": str(model_path),
                "inspection_template": str(inspection_template_path),
                "cache_hit": cache_hit,
                "cache_directory": str(cache_dir) if cache_hit else "",
                "design_root": str(design_root),
            },
            indent=2,
        )
    )
    return 0


def _load_run(path: Path, expected_status: set[str]) -> dict[str, Any]:
    run = _json_load(path)
    required = {
        "run_id", "started_epoch", "started_at_local", "temp_output_path",
        "design_root", "run_directory", "stage_parent", "stage_design",
        "model_path", "model_sha256", "classification_path", "classification_sha256",
        "inspection_template_path", "cache_key", "cache_directory", "status",
    }
    missing = sorted(required - set(run))
    if missing:
        raise DesignerError("Run metadata is incomplete: " + ", ".join(missing))
    path_keys = {
        "temp_output_path", "design_root", "run_directory", "stage_parent",
        "stage_design", "model_path", "classification_path",
        "inspection_template_path", "cache_directory",
    }
    if any(not isinstance(run[key], str) or not run[key] for key in path_keys):
        raise DesignerError("Run metadata contains an invalid path")
    if (
        not re.fullmatch(r"SDR-[0-9]{8}_[0-9]{6}-[A-F0-9]{8}-[A-F0-9]{8}", str(run["run_id"]))
        or any(
            not re.fullmatch(r"[a-f0-9]{64}", str(run[key]))
            for key in ("cache_key", "classification_sha256", "model_sha256")
        )
    ):
        raise DesignerError("Run identity or canonical hash metadata is invalid")
    maximum = run.get("max_repair_attempts", DEFAULT_MAX_REPAIR_ATTEMPTS)
    revision = run.get("revision", 0)
    attempts = run.get("repair_attempts", [])
    if (
        type(maximum) is not int or not 0 <= maximum <= DEFAULT_MAX_REPAIR_ATTEMPTS
        or type(revision) is not int or revision < 0
        or not isinstance(attempts, list) or len(attempts) > maximum
        or revision > len(attempts)
    ):
        raise DesignerError("Run repair bounds or revision metadata are invalid")
    profile_histories = {}
    for key in ("attempted_layout_profiles", "passing_layout_profiles", "selected_layout_profiles", "inspected_layout_profiles"):
        values = run.get(key)
        if (
            not isinstance(values, list)
            or any(profile not in LAYOUT_PROFILES for profile in values)
            or len(values) != len(set(values))
        ):
            raise DesignerError(f"Run {key} history is invalid")
        profile_histories[key] = values
    profiles = profile_histories["attempted_layout_profiles"]
    passing_profiles = profile_histories["passing_layout_profiles"]
    selected_profiles = profile_histories["selected_layout_profiles"]
    inspected_profiles = profile_histories["inspected_layout_profiles"]
    if (
        not set(passing_profiles).issubset(profiles)
        or not set(selected_profiles).issubset(passing_profiles)
        or not set(inspected_profiles).issubset(selected_profiles)
    ):
        raise DesignerError("Generated, passing, selected and inspected profile histories disagree")
    for number, attempt in enumerate(attempts, start=1):
        if (
            not isinstance(attempt, dict) or attempt.get("revision") != number
            or attempt.get("profile") not in profiles
            or attempt.get("profile") not in passing_profiles
            or attempt.get("previous_selected_profile") not in inspected_profiles
            or attempt.get("status") not in {"running", "failed", "awaiting_inspection"}
        ):
            raise DesignerError("Run repair-attempt history is invalid")
    successful_revisions = [
        item["revision"] for item in attempts if item["status"] == "awaiting_inspection"
    ]
    if revision != max([0] + successful_revisions):
        raise DesignerError("Active revision is not the latest successful generation")
    if len({item["profile"] for item in attempts}) != len(attempts):
        raise DesignerError("A repair layout profile was attempted more than once")
    successful_profiles = [item["profile"] for item in attempts if item["status"] == "awaiting_inspection"]
    if run["status"] == "awaiting_inspection" and (
        not selected_profiles or selected_profiles[1:] != successful_profiles
        or selected_profiles[-1] != run.get("selected_layout_profile")
    ):
        raise DesignerError("Selected profile history must describe the active rendered revisions")
    if run["status"] == "prepared" and any(profile_histories.values()):
        raise DesignerError("Prepared runs cannot claim generated or inspected layouts")
    try:
        if not isinstance(run["started_at_local"], str) or not run["started_at_local"]:
            raise ValueError("Missing start time")
        started_epoch = float(run["started_epoch"])
        started_at = _local_time(run["started_at_local"])
    except (TypeError, ValueError) as exc:
        raise DesignerError("Run start timestamp is invalid") from exc
    if not math.isfinite(started_epoch) or started_epoch <= 0 or started_epoch > time.time() + INSPECTION_CLOCK_SKEW_SECONDS:
        raise DesignerError("Run start timestamp is invalid")
    temp_output = Path(run["temp_output_path"]).resolve()
    design_root = (temp_output / ARTIFACT_CONTRACT["rootFolder"]).resolve()
    run_id = str(run["run_id"])
    run_dir = (
        design_root / ".solution-designer" / "runs" / run_id
    ).resolve()
    stage_parent = (
        design_root
        / ".staging"
        / _sha256_bytes(run_id.encode("utf-8"))[:10]
    ).resolve()
    revision_root = stage_parent / f"revision-{revision}" if revision else stage_parent
    stage_design = (revision_root / "design").resolve()
    model_path = (stage_design / "design-model.json").resolve()
    cache_dir = (
        design_root
        / ".solution-designer"
        / "cache"
        / f"v{CACHE_VERSION}"
        / str(run["cache_key"])
    ).resolve()
    inspection_template = (run_dir / "inspection-template.json").resolve()
    for number, attempt in enumerate(attempts, start=1):
        expected_evidence = stage_parent / f"revision-{number}" / "failed-inspection.json"
        if (
            Path(attempt.get("inspection_path", "")).resolve() != expected_evidence
            or type(attempt.get("previous_revision")) is not int
            or not 0 <= attempt["previous_revision"] < number
        ):
            raise DesignerError("Run repair evidence path or previous revision is invalid")
        previous_profiles = {0: selected_profiles[0]} if selected_profiles else {}
        previous_profiles.update({item["revision"]: item["profile"] for item in attempts if item["status"] == "awaiting_inspection"})
        if previous_profiles.get(attempt["previous_revision"]) != attempt.get("previous_selected_profile"):
            raise DesignerError("Repair inspection does not match its previously selected profile")
        _safe_path(expected_evidence, design_root)
        if (
            not expected_evidence.is_file()
            or _sha256_file(expected_evidence) != attempt.get("inspection_sha256")
        ):
            raise DesignerError("Failed inspection evidence changed after repair")
        previous_revision = attempt["previous_revision"]
        previous_root = stage_parent / f"revision-{previous_revision}" if previous_revision else stage_parent
        previous_design = previous_root / "design"
        if attempt.get("previous_stage_design") != str(previous_design):
            raise DesignerError("Archived browser evidence has an invalid revision path")
        for name, expected_hash in attempt.get("previous_browser_evidence_artifacts", {}).items():
            if name not in EVIDENCE_ARTIFACT_NAMES:
                raise DesignerError("Archived browser evidence has an invalid artifact name")
            artifact = _safe_path(previous_design / name, design_root)
            if not artifact.is_file() or _sha256_file(artifact) != expected_hash:
                raise DesignerError("Archived browser evidence changed after repair")
    if path.resolve().parent != run_dir or path.name != "run.json":
        raise DesignerError("Run path is not the expected run.json")
    if design_root.name != ARTIFACT_CONTRACT["rootFolder"]:
        raise DesignerError("Run output root is not design")
    if design_root.parent != temp_output:
        raise DesignerError("design is not directly beneath tempOutputPath")
    if not _is_within(run_dir, design_root):
        raise DesignerError("Run directory escapes design")
    expected_paths = {
        "design_root": design_root,
        "run_directory": run_dir,
        "stage_parent": stage_parent,
        "stage_design": stage_design,
        "model_path": model_path,
        "cache_directory": cache_dir,
        "inspection_template_path": inspection_template,
    }
    for key, expected in expected_paths.items():
        actual = Path(run[key]).resolve()
        if actual != expected:
            raise DesignerError(f"Run metadata path mismatch for {key}")
        _safe_path(expected, design_root)
        _assert_no_links(expected)
    if run.get("status") not in expected_status:
        raise DesignerError(
            f"Run status {run.get('status')} is invalid for this operation"
        )
    classification = Path(run["classification_path"])
    if (
        not classification.exists()
        or _sha256_file(classification) != run["classification_sha256"]
    ):
        raise DesignerError("Classification changed after preparation")
    if not model_path.exists() or _sha256_file(model_path) != run["model_sha256"]:
        raise DesignerError("Design model changed after preparation")
    model = _json_load(model_path)
    expected_cache_artifacts = sorted(
        _artifact_names(stage_design, model["scenarioSlug"])
        + ["generation-report.json", "inspection-report.json", *EVIDENCE_ARTIFACT_NAMES]
    )
    if run.get("expected_cache_artifacts") != expected_cache_artifacts:
        raise DesignerError("Run cache-artifact allowlist is inconsistent")
    if run.get("resource_hashes") != _resource_hashes():
        raise DesignerError("Designer resources changed after preparation")
    expected_cache_key = _canonical_hash(
        {
            "version": CACHE_VERSION,
            "classification": run["classification_sha256"],
            "model": _canonical_hash(model),
            "resources": run["resource_hashes"],
        }
    )
    if run.get("cache_key") != expected_cache_key:
        raise DesignerError("Run cache key does not match canonical model and resources")
    if run["status"] == "awaiting_inspection":
        slug = model["scenarioSlug"]
        if run.get("scenario_slug") != slug:
            raise DesignerError("Run scenario does not match the canonical model")
        if run.get("selected_layout_profile") not in profiles:
            raise DesignerError("Active layout profile is missing from run history")
        for key, name in {
            "solution_architecture_png": f"SA_{slug}.png",
            "sequence_png": f"SD_{slug}.png",
            "html_preview": "preview.html",
            "generation_report_path": "run-report.json",
        }.items():
            if not isinstance(run.get(key), str) or Path(run[key]).resolve() != stage_design / name:
                raise DesignerError(f"Run metadata path mismatch for {key}")
        initial_design = stage_parent / "design"
        initial_seal = attempts[0].get("previous_staged_artifacts", {}) if attempts else run.get("staged_artifacts", {})
        if not isinstance(initial_seal, dict):
            raise DesignerError("Initial candidate-ranking seal is invalid")
        for name in ("candidate-report.json", "run-report.json", "diagram-manifest.json"):
            artifact = _safe_path(initial_design / name, design_root)
            if not artifact.is_file() or _sha256_file(artifact) != initial_seal.get(name):
                raise DesignerError(f"Initial candidate-ranking evidence changed: {name}")
        initial_report = _json_load(initial_design / "run-report.json")
        initial_passing = _candidate_ranking(initial_design, initial_report)
        if (
            passing_profiles != initial_passing
            or profiles != initial_report.get("attemptedLayoutProfiles")
            or selected_profiles[0] != initial_report.get("selectedLayoutProfile")
        ):
            raise DesignerError("Profile histories disagree with the sealed initial candidate ranking")
        generated_at = _local_time(run.get("generated_at_local"))
        if (
            not run.get("generated_at_local")
            or generated_at < started_at
            or (generated_at - _local_time(_run_local_time(run))).total_seconds() > INSPECTION_CLOCK_SKEW_SECONDS
        ):
            raise DesignerError("Run generation timestamp is invalid")
    return run


def _candidate_ranking(root: Path, generation: dict[str, Any]) -> list[str]:
    """Validate reported scores without confusing geometric passes with visual acceptance."""
    report = _json_load(root / "candidate-report.json")
    candidates = report.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise DesignerError("Candidate report must contain evaluated layout profiles")
    profiles, orders, passing = [], [], []
    for candidate in candidates:
        if not isinstance(candidate, dict) or candidate.get("profile") not in LAYOUT_PROFILES:
            raise DesignerError("Candidate report contains an invalid layout profile")
        profile = candidate["profile"]
        order = candidate.get("order")
        status = candidate.get("validation")
        if profile in profiles or type(order) is not int or order < 0 or order in orders or status not in {"passed", "failed"}:
            raise DesignerError("Candidate report profile, order or validation is inconsistent")
        profiles.append(profile)
        orders.append(order)
        if status == "passed":
            score = candidate.get("score")
            if type(score) not in {float, int} or not math.isfinite(score):
                raise DesignerError("Passing candidates require finite numeric presentation-quality scores")
            passing.append(candidate)
    attempted = generation.get("attemptedLayoutProfiles")
    if profiles != attempted or orders != sorted(orders):
        raise DesignerError("Candidate report disagrees with attempted generation profiles")
    ranked = sorted(passing, key=lambda candidate: (-candidate["score"], candidate["order"]))
    if not ranked:
        raise DesignerError("Candidate report contains no passing layout profile")
    selected = ranked[0]["profile"]
    if report.get("selectedLayoutProfile") != selected or generation.get("selectedLayoutProfile") != selected:
        raise DesignerError("Selected layout is not the highest passing score with deterministic order tie-break")
    quality = _json_load(root / "diagram-manifest.json").get("layoutQuality", {})
    if (
        not isinstance(quality, dict) or quality.get("validation") != "passed"
        or type(quality.get("score")) not in {int, float}
        or quality["score"] != ranked[0]["score"]
    ):
        raise DesignerError("Selected candidate score disagrees with its passing layoutQuality manifest")
    return [candidate["profile"] for candidate in ranked]


def _generate_candidate(
    run: dict[str, Any], stage_design: Path, profile: str | None = None
) -> dict[str, Any]:
    model_path = stage_design / "design-model.json"
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(FAST_PATH),
        "-ModelPath",
        str(model_path),
        "-TempOutputPath",
        str(stage_design.parent),
        "-DeadlineSeconds",
        str(GENERATION_TIMEOUT_SECONDS),
    ]
    if profile:
        command.extend(["-LayoutProfile", profile])
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=GENERATION_TIMEOUT_SECONDS,
            env={**os.environ, "LISA_PYTHON": sys.executable},
        )
    except subprocess.TimeoutExpired as exc:
        raise DesignerError(
            "Packaged fast path stopped responding and was terminated"
        ) from exc
    if completed.returncode:
        details = completed.stderr.strip() or completed.stdout.strip()
        failed_report = stage_design / "run-report.json"
        if failed_report.is_file():
            try:
                failed = _json_load(failed_report)
                issues = failed.get("validationIssues", []) + failed.get("candidateFailures", [])
                if issues:
                    details += "\nGeneration report: " + "; ".join(str(issue) for issue in issues)
            except DesignerError:
                pass
        raise DesignerError(
            "Packaged fast path failed:\n"
            + details
        )
    generation_report_path = stage_design / "run-report.json"
    report = _json_load(generation_report_path)
    if (
        report.get("structuralValidation") != "passed"
        or report.get("validation") != "pending-inspection"
        or report.get("renderedInspection") != "pending"
    ):
        raise DesignerError(
            "Structural generation failed: "
            + "; ".join(report.get("validationIssues", []))
        )
    selected = report.get("selectedLayoutProfile")
    attempted = report.get("attemptedLayoutProfiles", [selected])
    if (
        not isinstance(attempted, list)
        or selected not in LAYOUT_PROFILES or selected not in attempted
        or any(value not in LAYOUT_PROFILES for value in attempted)
        or len(attempted) != len(set(attempted))
        or (profile and (selected != profile or attempted != [profile]))
        or (not profile and set(attempted) != set(LAYOUT_PROFILES))
    ):
        raise DesignerError("Generator returned an inconsistent layout-profile selection")
    if _sha256_file(model_path) != run["model_sha256"]:
        raise DesignerError("Generator changed the canonical design model")
    preview = stage_design / "preview.html"
    if (
        not isinstance(report.get("htmlPreview"), str)
        or Path(report["htmlPreview"]).resolve() != preview
        or not preview.is_file()
        or preview.stat().st_size == 0
    ):
        raise DesignerError("Generator did not produce the expected HTML preview")
    report["attemptedLayoutProfiles"] = attempted
    report["passingLayoutProfiles"] = _candidate_ranking(stage_design, report)
    report["modelMs"] = run["model_ms"]
    _atomic_write_json(generation_report_path, report)
    return report


def _seal_candidate(
    run_path: Path, run: dict[str, Any], stage_design: Path, report: dict[str, Any]
) -> int:
    slug = _json_load(stage_design / "design-model.json")["scenarioSlug"]
    _validate_source_artifacts(stage_design)
    generated_at = _run_local_time(run)
    report["inspectionContext"] = {
        "run_id": run["run_id"], "revision": run.get("revision", 0),
        "generated_at": generated_at, "model_sha256": run["model_sha256"],
    }
    _atomic_write_json(stage_design / "run-report.json", report)
    sa_png = stage_design / f"SA_{slug}.png"
    sd_png = stage_design / f"SD_{slug}.png"
    template = _inspection_template(run["run_id"], run.get("revision", 0))
    template["solution_architecture_png_sha256"] = _sha256_file(sa_png)
    template["sequence_png_sha256"] = _sha256_file(sd_png)
    staged_names = _artifact_names(stage_design, slug) + [
        "run-report.json"
    ]
    staged_hashes = {
        name: _sha256_file(stage_design / name)
        for name in staged_names
    }
    _atomic_write_json(Path(run["inspection_template_path"]), template)
    run.update(
        {
            "status": "awaiting_inspection",
            "generated_at_local": generated_at,
            "scenario_slug": slug,
            "stage_design": str(stage_design),
            "model_path": str(stage_design / "design-model.json"),
            "solution_architecture_png": str(sa_png),
            "sequence_png": str(sd_png),
            "html_preview": str(stage_design / "preview.html"),
            "generation_report_path": str(stage_design / "run-report.json"),
            "staged_artifacts": staged_hashes,
            "browser_evidence_artifacts": {},
            "selected_layout_profile": report["selectedLayoutProfile"],
            "selected_layout_profiles": run.get("selected_layout_profiles", []) + [report["selectedLayoutProfile"]],
            "passing_layout_profiles": run.get("passing_layout_profiles") or report["passingLayoutProfiles"],
            "attempted_layout_profiles": list(dict.fromkeys(
                run.get("attempted_layout_profiles", []) + report["attemptedLayoutProfiles"]
            )),
        }
    )
    _atomic_write_json(run_path, run)
    print(
        json.dumps(
            {
                "status": "awaiting_inspection",
                "solution_architecture_png": str(sa_png),
                "sequence_png": str(sd_png),
                "html_preview": str(stage_design / "preview.html"),
                "inspection_template": run["inspection_template_path"],
                "revision": run.get("revision", 0),
                "layout_profile": report["selectedLayoutProfile"],
                "passing_layout_profiles": run["passing_layout_profiles"],
                "selected_layout_profiles": run["selected_layout_profiles"],
                "inspected_layout_profiles": run["inspected_layout_profiles"],
                "remaining_repair_attempts": run.get("max_repair_attempts", DEFAULT_MAX_REPAIR_ATTEMPTS) - len(run.get("repair_attempts", [])),
            },
            indent=2,
        )
    )
    return 0


def _run_fast_path(run_path: Path) -> int:
    run = _load_run(run_path, {"prepared"})
    report = _generate_candidate(run, Path(run["stage_design"]))
    _load_run(run_path, {"prepared"})
    return _seal_candidate(run_path, run, Path(run["stage_design"]), report)


def _validate_staged(run: dict[str, Any]) -> None:
    stage_design = Path(run["stage_design"])
    expected_names = set(_artifact_names(stage_design, run["scenario_slug"]) + ["run-report.json"])
    hashes = run.get("staged_artifacts", {})
    if not isinstance(hashes, dict) or set(hashes) != expected_names:
        raise DesignerError("Run does not contain a complete sealed staged-artifact allowlist")
    for name, expected_hash in hashes.items():
        artifact = _safe_path(stage_design / name, Path(run["design_root"]))
        if not artifact.is_file() or _sha256_file(artifact) != expected_hash:
            raise DesignerError(f"Staged artifact changed after generation: {name}")
    report = _json_load(stage_design / "run-report.json")
    _validate_source_artifacts(stage_design)
    ranked = _candidate_ranking(stage_design, report)
    if report.get("passingLayoutProfiles") != ranked:
        raise DesignerError("Sealed passing-profile ranking disagrees with candidate report")
    if (
        report.get("structuralValidation") != "passed"
        or report.get("validation") != "pending-inspection"
        or report.get("renderedInspection") != "pending"
        or report.get("selectedLayoutProfile") != run.get("selected_layout_profile")
    ):
        raise DesignerError("Sealed generation report is not a candidate awaiting inspection")


def _validate_inspection(run: dict[str, Any], inspection: dict[str, Any]) -> None:
    _schema_validate(inspection, INSPECTION_SCHEMA, "Inspection")
    if inspection["run_id"] != run["run_id"]:
        raise DesignerError("Inspection run_id does not match the active run")
    if inspection.get("revision", 0) != run.get("revision", 0):
        raise DesignerError("Inspection revision does not match the active rendered candidate")
    if not inspection["inspected_at"]:
        raise DesignerError("Inspection inspected_at must record an actual inspection time")
    inspected_at = _local_time(inspection["inspected_at"])
    generated_at = _local_time(run["generated_at_local"])
    # One second permits ISO timestamps recorded without fractional seconds.
    if inspected_at < generated_at - timedelta(seconds=1):
        raise DesignerError("Inspection predates the active rendered candidate")
    if inspected_at > _local_time(_run_local_time(run)) + timedelta(seconds=INSPECTION_CLOCK_SKEW_SECONDS):
        raise DesignerError("Inspection timestamp is in the future")
    for key, path_key, label in (
        ("solution_architecture_png_sha256", "solution_architecture_png", "Solution Architecture"),
        ("sequence_png_sha256", "sequence_png", "Sequence"),
    ):
        if _sha256_file(Path(run[path_key])) != inspection[key]:
            raise DesignerError(f"{label} PNG changed after inspection")
    if inspection["status"] == "passed" or inspection.get("browser_evidence"):
        _validate_browser_evidence(
            Path(run["stage_design"]), inspection,
            _json_load(Path(run["generation_report_path"])).get("inspectionContext"),
            now=_local_time(_run_local_time(run)),
        )
        sealed_evidence = run.get("browser_evidence_artifacts")
        if not sealed_evidence or set(sealed_evidence) != set(EVIDENCE_ARTIFACT_NAMES):
            raise DesignerError("Browser evidence is not attached and sealed; use attach-browser-evidence")
        for name, expected in sealed_evidence.items():
            if _sha256_file(Path(run["stage_design"]) / name) != expected:
                raise DesignerError(f"Browser evidence changed after attachment: {name}")


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise DesignerError(f"Browser evidence is not a PNG image: {path.name}")
    offset, compressed, dimensions, ended = 8, bytearray(), None, False
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        end = offset + 12 + length
        if end > len(data) or binascii.crc32(kind + payload) & 0xffffffff != int.from_bytes(data[end - 4:end], "big"):
            raise DesignerError(f"PNG image checksum is invalid: {path.name}")
        if kind == b"IHDR":
            if dimensions or length != 13 or offset != 8:
                raise DesignerError(f"PNG image header is invalid: {path.name}")
            width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
            if not 0 < width <= 32768 or not 0 < height <= 32768 or width * height > 100_000_000 or compression or filtering or interlace:
                raise DesignerError(f"Unsupported PNG image dimensions/encoding: {path.name}")
            dimensions = (width, height)
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            ended = True
            if length or end != len(data):
                raise DesignerError(f"PNG image trailer is invalid: {path.name}")
            break
        offset = end
    if not dimensions or not ended or not compressed:
        raise DesignerError(f"PNG image is incomplete: {path.name}")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
    valid_depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
    if channels is None or depth not in valid_depths[color]:
        raise DesignerError(f"PNG image format is invalid: {path.name}")
    expected_size = height * (1 + (width * channels * depth + 7) // 8)
    try:
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(compressed, expected_size + 1)
        if len(decoded) != expected_size or not decoder.eof or decoder.unused_data:
            raise ValueError("Invalid raster payload")
        row_size = expected_size // height
        if any(decoded[offset] > 4 for offset in range(0, expected_size, row_size)):
            raise ValueError("Invalid PNG scanline filter")
    except (zlib.error, ValueError) as exc:
        raise DesignerError(f"PNG image cannot be decoded: {path.name}") from exc
    return dimensions


def _validate_browser_evidence(
    root: Path, inspection: dict[str, Any], context: dict | None, now: datetime | None = None
) -> dict[str, Any]:
    descriptor = inspection.get("browser_evidence")
    if not isinstance(descriptor, dict) or descriptor.get("path") != "browser-evidence.json":
        raise DesignerError("Inspection requires browser_evidence; all-true checks and hashes alone are not inspection evidence")
    report_path = _safe_path(root / descriptor["path"], root)
    if not report_path.is_file() or _sha256_file(report_path) != descriptor.get("sha256"):
        raise DesignerError("Browser evidence report is missing or changed")
    evidence = _json_load(report_path)
    import jsonschema
    schema = _json_load(INSPECTION_SCHEMA)
    try:
        jsonschema.Draft202012Validator({
            "$ref": "#/$defs/browserEvidence", "$defs": schema["$defs"]
        }).validate(evidence)
    except jsonschema.ValidationError as exc:
        raise DesignerError(f"Browser evidence schema error: {exc.message}") from exc
    if not context:
        raise DesignerError("Generation has no sealed inspection context")
    for field in ("run_id", "revision", "generated_at", "model_sha256"):
        if evidence[field] != context.get(field):
            raise DesignerError(f"Browser evidence {field} does not match the sealed generation")
    if evidence["run_id"] != inspection["run_id"] or evidence["revision"] != inspection.get("revision", 0):
        raise DesignerError("Browser evidence does not match inspection identity/revision")
    generated = _local_time(evidence["generated_at"])
    captured = _local_time(evidence["captured_at"])
    inspected = _local_time(inspection["inspected_at"])
    if captured < generated - timedelta(seconds=1) or captured > inspected + timedelta(seconds=1):
        raise DesignerError("Browser evidence capture is stale or later than the inspection")
    if now and captured > now + timedelta(seconds=INSPECTION_CLOCK_SKEW_SECONDS):
        raise DesignerError("Browser evidence timestamp is in the future")
    model = _json_load(root / "design-model.json")
    slug = model["scenarioSlug"]
    diagram_names = {f"{prefix}_{slug}.{extension}" for prefix in ("SA", "SD") for extension in ("svg", "png")}
    expected_names = diagram_names | {"preview.html", "design-model.json"}
    if set(evidence["artifact_sha256"]) != expected_names:
        raise DesignerError("Browser evidence must bind the model, preview and all four diagram assets")
    for name, expected in evidence["artifact_sha256"].items():
        path = _safe_path(root / name, root)
        if not path.is_file() or _sha256_file(path) != expected:
            raise DesignerError(f"Browser-viewed artifact changed: {name}")
    if evidence["model_sha256"] != evidence["artifact_sha256"]["design-model.json"]:
        raise DesignerError("Browser evidence model hash disagrees")
    links = evidence["links"]
    if {link["href"] for link in links} != diagram_names:
        raise DesignerError("Browser evidence must confirm four distinct sibling diagram links")
    for link in links:
        if not _safe_artifact_name(link["href"]) or link["sha256"] != evidence["artifact_sha256"][link["href"]]:
            raise DesignerError("Browser link confirmation has an invalid sibling path or hash")
    for key, prefix in (("architecture", "SA"), ("sequence", "SD")):
        image = evidence["diagrams"][key]
        filename = f"{prefix}_{slug}.png"
        if image["src"] != filename:
            raise DesignerError("Browser diagram references the wrong sibling image")
        natural = _png_dimensions(root / filename)
        if natural != (image["natural_width"], image["natural_height"]):
            raise DesignerError("Browser decoded natural image dimensions disagree")
        if any(abs(image[f"actual_{dimension}"] - value) > 1 for dimension, value in zip(("width", "height"), natural)):
            raise DesignerError("Browser actual-size toggle did not display native dimensions")
        if image["display_width"] > natural[0] + 1 or abs(image["display_width"] / image["display_height"] - natural[0] / natural[1]) > 0.01:
            raise DesignerError("Browser display dimensions stretch or distort the diagram")
    for key, screenshot in evidence["screenshots"].items():
        name = f"inspection-{key}.png"
        asset = "preview.html" if key == "preview" else f"{'SA' if key == 'architecture' else 'SD'}_{slug}.png"
        if screenshot["path"] != name or screenshot["viewed_asset"] != asset:
            raise DesignerError("Browser screenshot must reference a fixed sibling evidence file and viewed asset")
        path = _safe_path(root / name, root)
        if not path.is_file() or _sha256_file(path) != screenshot["sha256"]:
            raise DesignerError(f"Browser screenshot missing or changed: {name}")
        if _png_dimensions(path) != (screenshot["width"], screenshot["height"]):
            raise DesignerError(f"Browser screenshot dimensions disagree: {name}")
        if asset.endswith(".png") and screenshot["sha256"] == evidence["artifact_sha256"][asset]:
            raise DesignerError("A diagram file copied as its screenshot is not browser capture evidence")
    return evidence


def _attach_browser_evidence(run_path: Path, evidence_path: Path, inspection_path: Path) -> int:
    run = _load_run(run_path, {"awaiting_inspection"})
    _validate_staged(run)
    stage = Path(run["stage_design"])
    if evidence_path != stage / "browser-evidence.json":
        raise DesignerError("Collect browser evidence in the active staged design directory")
    inspection_path = _safe_path(inspection_path, Path(run["design_root"]))
    if inspection_path == evidence_path or inspection_path.name in run["staged_artifacts"]:
        raise DesignerError("Inspection attachment may not overwrite a staged artifact")
    inspection = _json_load(inspection_path)
    inspection["browser_evidence"] = {"path": "browser-evidence.json", "sha256": _sha256_file(evidence_path)}
    _schema_validate(inspection, INSPECTION_SCHEMA, "Inspection")
    _validate_browser_evidence(
        stage, inspection, _json_load(Path(run["generation_report_path"])).get("inspectionContext"),
        now=_local_time(_run_local_time(run)),
    )
    run["browser_evidence_artifacts"] = {name: _sha256_file(stage / name) for name in EVIDENCE_ARTIFACT_NAMES}
    _atomic_write_json(inspection_path, inspection)
    _atomic_write_json(run_path, run)
    print(json.dumps({"status": "evidence-attached", "inspection": str(inspection_path),
                      "browser_evidence": str(evidence_path),
                      "human_vision_judgment_required": True}, indent=2))
    return 0


def _repair(run_path: Path, inspection_path: Path, profile: str | None = None) -> int:
    run = _load_run(run_path, {"awaiting_inspection"})
    _validate_staged(run)
    inspection = _json_load(inspection_path)
    _validate_inspection(run, inspection)
    if inspection["status"] != "failed":
        raise DesignerError("Repair requires a failed rendered inspection")
    if not inspection["issues"] and all(inspection["checks"].values()):
        raise DesignerError("Failed inspection must identify an issue or failed check")
    run["inspected_layout_profiles"] = list(dict.fromkeys(
        run["inspected_layout_profiles"] + [run["selected_layout_profile"]]
    ))
    _atomic_write_json(run_path, run)
    attempts = run.get("repair_attempts", [])
    if any(attempt["status"] == "running" for attempt in attempts):
        raise DesignerError("A repair is already in progress; do not modify its sealed state")
    if len(attempts) >= run.get("max_repair_attempts", DEFAULT_MAX_REPAIR_ATTEMPTS):
        raise DesignerError("Bounded repair attempts exhausted; prepare a new run")
    prior_repairs = {attempt["profile"] for attempt in attempts}
    available = [
        value for value in run["passing_layout_profiles"]
        if value not in run["inspected_layout_profiles"] and value not in prior_repairs
    ]
    if not available:
        raise DesignerError("No uninspected passing layout profiles remain")
    selected = profile or available[0]
    if selected not in available:
        raise DesignerError("Repair must select an uninspected passing profile not previously retried")
    revision = len(attempts) + 1
    revision_root = _safe_path(Path(run["stage_parent"]) / f"revision-{revision}", Path(run["design_root"]))
    if revision_root.exists():
        raise DesignerError("Repair revision already exists; refusing to overwrite evidence")
    stage_design = revision_root / "design"
    stage_design.mkdir(parents=True)
    shutil.copy2(run["model_path"], stage_design / "design-model.json")
    evidence_path = revision_root / "failed-inspection.json"
    _atomic_write_json(evidence_path, inspection)
    attempt = {
        "revision": revision,
        "previous_revision": run.get("revision", 0),
        "previous_selected_profile": run["selected_layout_profile"],
        "profile": selected,
        "status": "running",
        "started_at_local": _run_local_time(run),
        "inspection_path": str(evidence_path),
        "inspection_sha256": _sha256_file(evidence_path),
        "previous_staged_artifacts": copy.deepcopy(run["staged_artifacts"]),
        "previous_stage_design": run["stage_design"],
        "previous_browser_evidence_artifacts": copy.deepcopy(run.get("browser_evidence_artifacts", {})),
    }
    run["repair_attempts"] = attempts + [attempt]
    run["attempted_layout_profiles"] = list(dict.fromkeys(run["attempted_layout_profiles"] + [selected]))
    _atomic_write_json(run_path, run)
    try:
        report = _generate_candidate(run, stage_design, selected)
        _load_run(run_path, {"awaiting_inspection"})
        _validate_staged(run)
    except (DesignerError, OSError) as exc:
        attempt.update(status="failed", error=str(exc), completed_at_local=_run_local_time(run))
        _atomic_write_json(run_path, run)
        raise
    attempt.update(status="awaiting_inspection", completed_at_local=_run_local_time(run))
    run["revision"] = revision
    return _seal_candidate(run_path, run, stage_design, report)


def _artifact_names(stage_design: Path, slug: str) -> list[str]:
    return [
        "design-model.json",
        f"SA_{slug}.svg",
        f"SD_{slug}.svg",
        f"SA_{slug}.png",
        f"SD_{slug}.png",
        "preview.html",
        "diagram-manifest.json",
        "validation-report.json",
        "render-report.json",
        "candidate-report.json",
        f"Design_{slug}.drawio",
        f"SA_{slug}.mmd",
        f"SD_{slug}.mmd",
        "source-report.json",
    ]


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=str(destination.parent),
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    try:
        shutil.copy2(source, temporary)
        _replace_atomic_file(Path(temporary), destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _commit_directory(temporary: Path, destination: Path) -> None:
    try:
        os.replace(temporary, destination)
        return
    except PermissionError:
        if destination.exists():
            raise
    destination.mkdir(parents=False, exist_ok=False)
    try:
        for item in temporary.iterdir():
            if not item.is_file():
                raise DesignerError(
                    f"Atomic publication supports files only: {item}"
                )
            _atomic_copy(item, destination / item.name)
        expected = {
            item.name: _sha256_file(item)
            for item in temporary.iterdir()
            if item.is_file()
        }
        observed = {
            item.name: _sha256_file(item)
            for item in destination.iterdir()
            if item.is_file()
        }
        if observed != expected:
            raise DesignerError(
                f"OneDrive-safe directory publication hash mismatch: {destination}"
            )
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def _replace_directory(temporary: Path, destination: Path, on_commit=None) -> None:
    backup = destination.with_name(
        f".{destination.name}.backup-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    )
    if backup.exists():
        raise DesignerError(f"Artifact publication backup already exists: {backup}")
    if destination.exists():
        os.replace(destination, backup)
    try:
        _commit_directory(temporary, destination)
        if on_commit:
            on_commit()
    except BaseException:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        if backup.exists():
            os.replace(backup, destination)
        raise
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


def _final_result(
    run: dict[str, Any],
    generation: dict[str, Any],
    inspection: dict[str, Any],
    cache_hit: bool,
    artifact_root: Path,
    manifest_root: Path | None = None,
) -> dict[str, Any]:
    slug = run["scenario_slug"]
    manifest = _json_load(
        (manifest_root or artifact_root) / "diagram-manifest.json"
    )
    total_ms = round((time.time() - float(run["started_epoch"])) * 1000)
    timings = generation.get("timingsMs", {})
    return {
        "solution_architecture_diagram": str(artifact_root / f"SA_{slug}.svg"),
        "sequence_diagram": str(artifact_root / f"SD_{slug}.svg"),
        "html_preview": str(artifact_root / "preview.html"),
        "renders": {
            "solution_architecture_png": str(artifact_root / f"SA_{slug}.png"),
            "sequence_png": str(artifact_root / f"SD_{slug}.png"),
        },
        "editable_sources": {
            "drawio": str(artifact_root / f"Design_{slug}.drawio"),
            "architecture_mermaid": str(artifact_root / f"SA_{slug}.mmd"),
            "sequence_mermaid": str(artifact_root / f"SD_{slug}.mmd"),
            "report": str(artifact_root / "source-report.json"),
        },
        "browser_evidence": str(artifact_root / "browser-evidence.json"),
        "candidate_report": str(artifact_root / "candidate-report.json"),
        "inspection_assurance": "Hash-bound browser observations plus recorded human/vision judgment; not browser attestation.",
        "scenario_slug": slug,
        "icon_manifest": manifest.get("icons", []),
        "reference_sources": manifest.get("referenceSources", []),
        "cache_status": "validated-cache-hit" if cache_hit else generation.get(
            "cacheStatus", "packaged-fresh"
        ),
        "timings_ms": {
            "model": generation.get("modelMs", 0),
            "generate": timings.get("generate", 0),
            "validate": timings.get("validate", 0),
            "render": timings.get("render", 0),
            "inspection": generation.get("inspectionMs", 0),
            "total": total_ms,
        },
        "validation": "passed",
        "validation_issues": [],
        "summary": inspection["summary"],
    }


def _write_cache(
    run: dict[str, Any], artifact_root: Path, artifacts: list[str]
) -> None:
    cache_dir = Path(run["cache_directory"])
    if cache_dir.exists():
        if _cache_valid(
            cache_dir,
            run["cache_key"],
            set(run["expected_cache_artifacts"]),
        ):
            return
        shutil.rmtree(cache_dir)
    temporary = cache_dir.with_name(
        cache_dir.name + ".tmp-" + str(os.getpid())
    )
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    cached_inspection = _json_load(artifact_root / "inspection-report.json")
    for name in artifacts:
        if name in {"inspection-report.json", "run-report.json"}:
            continue
        if not _safe_artifact_name(name):
            raise DesignerError(f"Unsafe cache artifact name: {name}")
        source = (artifact_root / name).resolve()
        if not _is_within(source, artifact_root):
            raise DesignerError(f"Cache artifact escapes publication root: {name}")
        shutil.copy2(source, temporary / name)
    _atomic_write_json(temporary / "inspection-report.json", cached_inspection)
    artifact_hashes = {
        item.name: _sha256_file(item)
        for item in temporary.iterdir()
        if item.is_file() and item.name != "cache-manifest.json"
    }
    _atomic_write_json(
        temporary / "cache-manifest.json",
        {
            "cache_key": run["cache_key"],
            "created_at_local": _run_local_time(run),
            "artifacts": artifact_hashes,
        },
    )
    if set(artifact_hashes) != set(run["expected_cache_artifacts"]):
        raise DesignerError("Cache artifact set does not match the expected allowlist")
    if not _cache_valid(temporary, run["cache_key"], set(run["expected_cache_artifacts"])):
        shutil.rmtree(temporary, ignore_errors=True)
        raise DesignerError("Cache evidence or editable source validation failed before commit")
    _commit_directory(temporary, cache_dir)


def _publish_versioned_set(
    run: dict[str, Any],
    source_root: Path,
    base_artifacts: list[str],
    generation: dict[str, Any],
    inspection: dict[str, Any],
    cache_hit: bool,
) -> tuple[dict[str, Any], Path, list[str]]:
    design_root = Path(run["design_root"])
    artifact_root = design_root / "artifacts"
    temporary = design_root / (
        f".artifacts.tmp-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    )
    temporary.mkdir(parents=True)
    try:
        for name in base_artifacts:
            if not _safe_artifact_name(name):
                raise DesignerError(f"Unsafe publication artifact name: {name}")
            source = (source_root / name).resolve()
            destination = (temporary / name).resolve()
            if not _is_within(source, source_root):
                raise DesignerError(f"Publication source escapes its root: {name}")
            if not _is_within(destination, temporary):
                raise DesignerError(f"Publication destination escapes staging: {name}")
            if not source.exists():
                raise DesignerError(f"Publication source is missing: {source}")
            shutil.copy2(source, destination)
        portable_generation = copy.deepcopy(generation)
        portable_generation["htmlPreview"] = "preview.html"
        portable_generation["candidateReport"] = "candidate-report.json"
        _atomic_write_json(temporary / "generation-report.json", portable_generation)
        _atomic_write_json(temporary / "inspection-report.json", inspection)
        _validate_source_artifacts(temporary)
        _candidate_ranking(temporary, portable_generation)
        _validate_browser_evidence(temporary, inspection, generation.get("inspectionContext"))
        published = base_artifacts + [
            "generation-report.json",
            "inspection-report.json",
        ]
        result = _final_result(
            run,
            generation,
            inspection,
            cache_hit,
            artifact_root,
            manifest_root=temporary,
        )
        artifact_hashes = {
            name: _sha256_file(temporary / name) for name in published
        }
        final_report = {
            "validation": "passed",
            "structuralValidation": generation.get("structuralValidation"),
            "renderedInspection": "passed",
            "validationIssues": [],
            "classificationPath": run["classification_path"],
            "classificationSha256": run["classification_sha256"],
            "resourceHashes": run["resource_hashes"],
            "cacheHit": cache_hit,
            "artifactDirectory": str(artifact_root),
            "completedAt": _run_local_time(run),
            "timingsMs": result["timings_ms"],
            "layoutProfiles": copy.deepcopy(generation.get("profileHistory", {})),
            "artifacts": artifact_hashes,
        }
        _atomic_write_json(temporary / "run-report.json", final_report)
        published.append("run-report.json")
        if not cache_hit:
            _write_cache(run, temporary, published)

        def commit_pointer() -> None:
            _write_current_pointer(run, result, artifact_root, published, cache_hit)

        if artifact_root.exists():
            existing = {
                item.name: _sha256_file(item)
                for item in artifact_root.iterdir()
                if item.is_file()
            }
            candidate = {
                item.name: _sha256_file(item)
                for item in temporary.iterdir()
                if item.is_file()
            }
            if existing != candidate:
                current_pointer = Path(run["design_root"]) / "current-design.json"
                current_run = (
                    _json_load(current_pointer).get("run_id")
                    if current_pointer.exists()
                    else ""
                )
                if current_run == run["run_id"]:
                    raise DesignerError(
                        f"Existing immutable artifact set differs: {artifact_root}"
                    )
                _replace_directory(temporary, artifact_root, commit_pointer)
            else:
                shutil.rmtree(temporary)
                commit_pointer()
        else:
            _commit_directory(temporary, artifact_root)
            try:
                commit_pointer()
            except BaseException:
                shutil.rmtree(artifact_root, ignore_errors=True)
                raise
        complete_hashes = {
            name: _sha256_file(artifact_root / name) for name in published
        }
        return result, artifact_root, published
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
        raise


def _write_current_pointer(
    run: dict[str, Any],
    result: dict[str, Any],
    artifact_root: Path,
    published: list[str],
    cache_hit: bool,
) -> None:
    base_root = Path(run["temp_output_path"]).resolve().parent

    def relative(path_value: str) -> str:
        path = Path(path_value).resolve()
        try:
            return path.relative_to(base_root).as_posix()
        except ValueError as exc:
            raise DesignerError(f"Current design path escapes basePath: {path}") from exc

    pointer_result = copy.deepcopy(result)
    pointer_result["solution_architecture_diagram"] = relative(
        result["solution_architecture_diagram"]
    )
    pointer_result["sequence_diagram"] = relative(result["sequence_diagram"])
    pointer_result["html_preview"] = relative(result["html_preview"])
    pointer_result["renders"]["solution_architecture_png"] = relative(
        result["renders"]["solution_architecture_png"]
    )
    pointer_result["renders"]["sequence_png"] = relative(
        result["renders"]["sequence_png"]
    )
    pointer_result["editable_sources"] = {
        key: relative(value) for key, value in result["editable_sources"].items()
    }
    pointer_result["browser_evidence"] = relative(result["browser_evidence"])
    pointer_result["candidate_report"] = relative(result["candidate_report"])
    pointer = {
        "run_id": run["run_id"],
        "artifact_directory": artifact_root.resolve().relative_to(base_root).as_posix(),
        "scenario_slug": run["scenario_slug"],
        "validation": "passed",
        "cache_hit": cache_hit,
        "artifacts": {
            name: _sha256_file(artifact_root / name) for name in published
        },
        "result": pointer_result,
        "updated_at": _run_local_time(run),
    }
    _atomic_write_json(Path(run["design_root"]) / "current-design.json", pointer)


def _finalize(run_path: Path, inspection_path: Path) -> int:
    run = _load_run(run_path, {"awaiting_inspection"})
    if any(attempt["status"] == "running" for attempt in run.get("repair_attempts", [])):
        raise DesignerError("Cannot finalize while a repair is in progress")
    inspection = _json_load(inspection_path)
    _schema_validate(inspection, INSPECTION_SCHEMA, "Inspection")
    if inspection["run_id"] != run["run_id"]:
        raise DesignerError("Inspection run_id does not match the active run")
    if inspection["status"] != "passed":
        raise DesignerError(
            "Rendered inspection failed: " + "; ".join(inspection["issues"])
        )
    _validate_staged(run)
    _validate_inspection(run, inspection)
    failed_checks = [
        name for name, passed in inspection["checks"].items() if not passed
    ]
    if failed_checks:
        raise DesignerError(
            "Rendered inspection has failed checks: " + ", ".join(failed_checks)
        )
    if inspection["issues"]:
        raise DesignerError("Passed inspection cannot contain issues")
    run["inspected_layout_profiles"] = list(dict.fromkeys(
        run["inspected_layout_profiles"] + [run["selected_layout_profile"]]
    ))
    generation = _json_load(Path(run["generation_report_path"]))
    generation["profileHistory"] = {
        name: list(run[f"{name}_layout_profiles"])
        for name in ("attempted", "passing", "selected", "inspected")
    }
    stage_design = Path(run["stage_design"])
    slug = run["scenario_slug"]
    artifacts = _artifact_names(stage_design, slug) + list(EVIDENCE_ARTIFACT_NAMES)
    generation["inspectionMs"] = max(
        0,
        round(
            (time.time() - float(run["started_epoch"])) * 1000
            - run.get("model_ms", 0)
            - generation.get("timingsMs", {}).get("total", 0)
        ),
    )
    result, artifact_root, published = _publish_versioned_set(
        run,
        stage_design,
        artifacts,
        generation,
        inspection,
        cache_hit=False,
    )
    run.update(
        {
            "status": "validated",
            "completed_at_local": _run_local_time(run),
            "duration_seconds": round(time.time() - float(run["started_epoch"]), 3),
            "result": result,
        }
    )
    _atomic_write_json(run_path, run)
    print(json.dumps(result, indent=2))
    return 0


def _reuse(run_path: Path) -> int:
    run = _load_run(run_path, {"prepared"})
    cache_dir = Path(run["cache_directory"])
    if not _cache_valid(
        cache_dir,
        run["cache_key"],
        set(run["expected_cache_artifacts"]),
    ):
        raise DesignerError("Validated design cache is unavailable or invalid")
    manifest = _json_load(cache_dir / "cache-manifest.json")
    for name, expected_hash in manifest["artifacts"].items():
        if not _safe_artifact_name(name):
            raise DesignerError(f"Unsafe cached artifact name: {name}")
        source = (cache_dir / name).resolve()
        if not _is_within(source, cache_dir):
            raise DesignerError(f"Cached artifact escapes cache root: {name}")
        if _sha256_file(source) != expected_hash:
            raise DesignerError(f"Cached artifact hash mismatch: {name}")
    model = _json_load(Path(run["model_path"]))
    slug = model["scenarioSlug"]
    run["scenario_slug"] = slug
    generation = _json_load(cache_dir / "generation-report.json")
    inspection = _json_load(cache_dir / "inspection-report.json")
    # Reuse preserves who/what/when was inspected; it is not a new browser inspection.
    base_artifacts = [
        name
        for name in manifest["artifacts"]
        if name not in {
            "generation-report.json",
            "inspection-report.json",
            "run-report.json",
        }
    ]
    result, artifact_root, published = _publish_versioned_set(
        run,
        cache_dir,
        base_artifacts,
        generation,
        inspection,
        cache_hit=True,
    )
    run.update(
        {
            "status": "validated",
            "completed_at_local": _run_local_time(run),
            "duration_seconds": round(time.time() - float(run["started_epoch"]), 3),
            "result": result,
        }
    )
    _atomic_write_json(run_path, run)
    print(json.dumps(result, indent=2))
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Solution Designer end-to-end orchestrator"
    )
    parser.add_argument("--version", action="version", version=VERSION)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser(
        "prepare", help="Generate a validated design model from classification JSON"
    )
    prepare.add_argument(
        "--config",
        required=True,
        help="lisa-config.json; classification and output resolve from relative basePath",
    )
    prepare.add_argument("--local-time")
    prepare.add_argument(
        "--max-repair-attempts", type=int, choices=range(DEFAULT_MAX_REPAIR_ATTEMPTS + 1),
        default=DEFAULT_MAX_REPAIR_ATTEMPTS,
        help="Maximum visual repair generations (0-2); no wall-clock inspection deadline",
    )
    prepare.set_defaults(handler=lambda args: _prepare(args))

    generate = commands.add_parser(
        "generate", help="Generate, validate, and render staged diagrams"
    )
    generate.add_argument("--run", "--run-state", dest="run", required=True)
    generate.set_defaults(
        handler=lambda args: _run_fast_path(Path(args.run).resolve())
    )

    attach = commands.add_parser(
        "attach-browser-evidence", help="Validate and seal collected browser observations without asserting visual checks"
    )
    attach.add_argument("--run", required=True)
    attach.add_argument("--evidence", required=True)
    attach.add_argument("--inspection", required=True)
    attach.set_defaults(handler=lambda args: _attach_browser_evidence(
        Path(args.run).resolve(), Path(args.evidence).resolve(), Path(args.inspection).resolve()
    ))

    repair = commands.add_parser(
        "repair", help="Regenerate an uninspected passing layout after a failed visual inspection"
    )
    repair.add_argument("--run", "--run-state", dest="run", required=True)
    repair.add_argument("--inspection", required=True)
    repair.add_argument("--layout-profile", choices=LAYOUT_PROFILES)
    repair.set_defaults(
        handler=lambda args: _repair(
            Path(args.run).resolve(), Path(args.inspection).resolve(), args.layout_profile
        )
    )

    finalize = commands.add_parser(
        "finalize", help="Validate rendered inspection and atomically publish"
    )
    finalize.add_argument("--run", required=True)
    finalize.add_argument("--inspection", required=True)
    finalize.set_defaults(
        handler=lambda args: _finalize(
            Path(args.run).resolve(), Path(args.inspection).resolve()
        )
    )

    reuse = commands.add_parser(
        "reuse", help="Atomically republish a validated cached diagram set"
    )
    reuse.add_argument("--run", required=True)
    reuse.set_defaults(handler=lambda args: _reuse(Path(args.run).resolve()))

    validate_model = commands.add_parser(
        "validate-model", help="Validate a design model against the packaged schema"
    )
    validate_model.add_argument("--model", required=True)
    validate_model.set_defaults(
        handler=lambda args: (
            _validate_model_semantics(
                _json_load(Path(args.model).resolve())
            )
            or print(
                json.dumps(
                    {
                        "status": "passed",
                        "model": str(Path(args.model).resolve()),
                    }
                )
            )
            or 0
        )
    )
    validate_resources = commands.add_parser(
        "validate-resources", help="Read-only validation of packaged icon/license provenance and resource hashes"
    )
    validate_resources.set_defaults(handler=lambda args: (
        print(json.dumps({"validation": "passed", "resource_hashes": _resource_hashes()}, indent=2)) or 0
    ))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except DesignerError as exc:
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
