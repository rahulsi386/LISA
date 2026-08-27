#!/usr/bin/env python3
"""End-to-end orchestration for the Solution Designer packaged fast path."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from validate_artifact_contracts import canonical_stage_root, validate_contract
from lisa_path_resolver import LisaConfigError, latest_file, resolve_lisa_config


VERSION = "3.0.0"
CACHE_VERSION = "3"
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
FINAL_ARTIFACT_NAMES = {
    "design-model.json",
    "diagram-manifest.json",
    "validation-report.json",
    "render-report.json",
    "generation-report.json",
    "inspection-report.json",
}


class DesignerError(RuntimeError):
    """A user-actionable designer failure."""


def _json_load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
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
    real_statuses = {"build", "configure", "existing"}
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
    architecture_pairs = {
        (item["from"], item["to"]) for item in model["relationships"]
    }
    reverse_pairs = {
        (item["to"], item["from"])
        for item in model["relationships"]
    }
    for message in model["sequence"]:
        if message["from"] not in known_ids or message["to"] not in known_ids:
            raise DesignerError(
                "Sequence message references an unknown component: "
                f"{message['from']} -> {message['to']}"
            )
        participants.update((message["from"], message["to"]))
        if message["type"] != "self" and (
            message["from"], message["to"]
        ) not in architecture_pairs | reverse_pairs:
            raise DesignerError(
                "Every sequence message must map to an architecture relationship: "
                f"{message['from']} -> {message['to']}"
            )
        if message["implementationMode"] == "simulated" and "simulat" not in message["label"].casefold():
            raise DesignerError(
                "Simulated sequence messages must be visibly labelled as simulated"
            )
    if len(participants) > 8:
        raise DesignerError("Sequence diagrams support at most eight participants")
    if len(participants) < 2:
        raise DesignerError("Sequence diagrams require at least two participants")
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
    custom_tools = [
        item
        for item in classification.get("components", {}).get("tools", [])
        if item.get("integrability") == "custom"
    ]
    if platform == "Hybrid" and custom_tools:
        return (
            "Copilot Studio provides grounded procurement guidance while a custom "
            "analytics service evaluates operational data, anomalies, forecasts, "
            "pricing, and compliance."
        )
    return (
        f"{title} uses {platform} to deliver the evidenced agent interactions, "
        "data access, controls, and human handoffs."
    )[:300]


def _primary_agent_name(value: str) -> str:
    words = value.split()
    if words and words[0].casefold() == "conversational":
        words = words[1:]
    shortened = " ".join(words).strip()
    if len(shortened) <= 36:
        return shortened.title() if shortened.islower() else shortened
    essential = [
        word
        for word in words
        if word.casefold() not in {"assistant", "conversational", "solution"}
    ]
    shortened = " ".join(essential[:4]).strip()
    return (shortened or "Agentic Solution")[:36]


def _icon_for(name: str, kind: str, platform: str) -> str:
    lower = name.casefold()
    mappings = [
        ("copilot studio", "copilot-studio"),
        ("power automate", "power-automate"),
        ("dataverse", "dataverse"),
        ("entra", "entra-id"),
        ("foundry", "foundry-agent-service"),
        ("azure monitor", "azure-monitor"),
        ("sql", "sql-database"),
        ("storage", "storage-account"),
        ("api management", "api-management"),
        ("function", "function-apps"),
        ("key vault", "key-vault"),
        ("application insights", "azure-monitor"),
        ("purview", "azure-information-protection"),
        ("power platform", "power-platform"),
        ("microsoft 365", "agent-365"),
        ("custom connector", "custom-connector"),
        ("user", "users"),
        ("approver", "users"),
    ]
    for token, key in mappings:
        if token in lower:
            return key
    if kind == "agent":
        if platform in {"Copilot Studio", "Hybrid"}:
            return "copilot-studio"
        if platform == "Azure AI Foundry":
            return "foundry-agent-service"
        return "generic-component"
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
    lifecycle_status = {
        "existing": "existing",
        "configure": "to-create",
        "build": "to-create",
        "recommended": "to-create",
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
    mode_by_treatment = {
        "block": "blocked",
        "defer": "deferred",
        "manual-handoff": "manual",
        "simulate": "simulated",
        "static-sample-data": "simulated",
        "build": "real",
        "configure": "real",
        "existing": "real",
    }

    def component_disposition(item: dict[str, Any]) -> tuple[str, str, str, str]:
        mapped = capabilities_by_component.get(item["id"], [])
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
        return "configure", "agent-builder", "included", "requires-hardening"

    component_modes: dict[str, str] = {}
    design_components = []
    for item in topology["components"]:
        treatment, owner, poc_scope, production_status = component_disposition(item)
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
                f"{item['name']} {item['product_service']}",
                category_kind[item["category"]],
                platform,
            ),
            "description": (
                f"{item['role']} Runtime: {item['hosting_runtime']}. "
                f"Boundary: {item['deployment_boundary']}."
            ),
        }
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
    for item in topology["relationships"]:
        endpoint_modes = {
            component_modes[item["source_id"]],
            component_modes[item["target_id"]],
        }
        mode = next(
            (
                candidate
                for candidate in ("blocked", "deferred", "manual", "simulated")
                if candidate in endpoint_modes
            ),
            "real",
        )
        label = item["interaction"]
        if mode == "simulated" and "simulat" not in label.casefold():
            label = f"Simulated: {label}"[:42]
        relationship = {
            "from": item["source_id"],
            "to": item["target_id"],
            "label": label,
            "style": style_by_type.get(item["relationship_type"], "call"),
            "implementationMode": mode,
        }
        if item["evidence_ids"]:
            relationship["evidenceIds"] = item["evidence_ids"]
        relationships.append(relationship)

    sequence = []
    for item in sorted(topology["sequence_flows"], key=lambda value: value["order"]):
        matching_capability = next(
            (
                capability
                for capability in capabilities
                if item["source_id"] in capability.get("component_ids", [])
                and item["target_id"] in capability.get("component_ids", [])
            ),
            None,
        )
        mode = (
            mode_by_treatment[matching_capability["poc_treatment"]]
            if matching_capability
            else next(
                (
                    candidate
                    for candidate in ("blocked", "deferred", "manual", "simulated")
                    if candidate
                    in {
                        component_modes[item["source_id"]],
                        component_modes[item["target_id"]],
                    }
                ),
                "real",
            )
        )
        action = item["action"]
        if mode == "simulated" and "simulat" not in action.casefold():
            action = f"Simulated: {action}"[:56]
        message = {
            "from": item["source_id"],
            "to": item["target_id"],
            "label": action,
            "type": item["message_type"],
            "implementationMode": mode,
            "capabilityId": matching_capability["id"] if matching_capability else None,
            "phase": item["phase"],
            "fragment": (
                f"alt [{item['condition']}]" if item["condition"] else None
            ),
        }
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
        "title": title[:80],
        "summary": topology["architecture_summary"][:300],
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
    primary_name = _primary_agent_name(source_agent_name)
    title = primary_name[:80]
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
        build_owner: str = "unassigned",
        poc_scope: str = "included",
        production_status: str = "requires-hardening",
    ) -> str:
        identifier = _component_id(name, existing_ids)
        component = {
                "id": identifier,
                "name": name[:60],
                "layer": layer,
                "kind": kind,
                "status": status,
                "implementationStatus": implementation_status or (
                    "existing" if status == "existing" else "configure" if status == "to-create" else "defer"
                ),
                "buildOwner": build_owner,
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
    for item in components_value.get("communication_channels", [])[:2]:
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
    if governance_text and len(components) < 12:
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
    if alm_items and len(components) < 12:
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
        if source and target and source != target and len(relationships) < 20:
            mode = interaction_mode(source, target)
            visible_label = (
                f"Simulated: {label}" if mode == "simulated" else label
            )
            relationships.append(
                {"from": source, "to": target, "label": visible_label[:42], "style": style, "implementationMode": mode}
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
            "from": source,
            "to": target,
            "label": visible_label[:56],
            "type": message_type,
            "implementationMode": mode,
            "capabilityId": None,
            "phase": phase[:40],
            "fragment": fragment,
        }
        sequence.append(item)

    if auth_evidenced:
        message(actor_id, governance_id, "Authenticate user", "call", "Authentication")
        message(governance_id, actor_id, "Return authenticated session", "response", "Authentication")
    message(actor_id, agent_id, "Submit request", "call", "Request")
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
            "alt [approval required]",
        )
        message(human_id, agent_id, "Return decision", "response", "Human decision")
    message(agent_id, actor_id, "Return response", "response", "Response")
    if len(sequence) > 20:
        sequence = sequence[:19] + [sequence[-1]]

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
        "components": components[:12],
        "relationships": relationships,
        "sequence": sequence,
    }
    _validate_model_semantics(model)
    return model


def _resource_hashes() -> dict[str, str]:
    files = [
        MODEL_SCHEMA,
        INSPECTION_SCHEMA,
        REFERENCE_MANIFEST,
        ICON_MANIFEST,
        FAST_PATH,
        SCRIPTS / "New-Diagrams.ps1",
        SCRIPTS / "Render-Diagrams.ps1",
        SCRIPTS / "Test-Diagrams.ps1",
    ]
    return {
        **{path.name: _sha256_file(path) for path in files},
        "icons": _directory_hash(RESOURCES / "icons"),
        "layout_engine": _directory_hash(RESOURCES / "layout-engine"),
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
    return bool(name) and Path(name).name == name and not Path(name).is_absolute()


def _cache_valid(
    cache_dir: Path, cache_key: str, expected_artifacts: set[str]
) -> bool:
    manifest_path = cache_dir / "cache-manifest.json"
    if not manifest_path.exists():
        return False
    try:
        manifest = _json_load(manifest_path)
    except DesignerError:
        return False
    if manifest.get("cache_key") != cache_key:
        return False
    artifact_names = set(manifest.get("artifacts", {}))
    if artifact_names != expected_artifacts:
        return False
    for name, expected_hash in manifest.get("artifacts", {}).items():
        if not _safe_artifact_name(name):
            return False
        artifact = (cache_dir / name).resolve()
        if not _is_within(artifact, cache_dir):
            return False
        if not artifact.exists() or _sha256_file(artifact) != expected_hash:
            return False
    inspection = cache_dir / "inspection-report.json"
    if not inspection.exists() or _json_load(inspection).get("status") != "passed":
        return False
    return True


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
        + ["generation-report.json", "inspection-report.json"]
    )
    cache_hit = _cache_valid(
        cache_dir, cache_key, expected_cache_artifacts
    )
    inspection_template = {
        "run_id": run_id,
        "inspected_at": "",
        "status": "failed",
        "solution_architecture_png_sha256": "0" * 64,
        "sequence_png_sha256": "0" * 64,
        "checks": {
            "spelling": False,
            "clipping": False,
            "icon_correctness": False,
            "connector_visibility": False,
            "primary_agent_hierarchy": False,
            "empty_space": False,
            "label_collisions": False,
            "sequence_phase_grouping": False,
            "truncation": False,
            "overall_composition": False,
        },
        "issues": ["Inspection not completed."],
        "summary": "Inspect both rendered PNGs before finalization.",
    }
    _atomic_write_json(inspection_template_path, inspection_template)
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
    stage_design = (stage_parent / "design").resolve()
    model_path = (stage_design / "design-model.json").resolve()
    cache_dir = (
        design_root
        / ".solution-designer"
        / "cache"
        / f"v{CACHE_VERSION}"
        / str(run["cache_key"])
    ).resolve()
    inspection_template = (run_dir / "inspection-template.json").resolve()
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
        + ["generation-report.json", "inspection-report.json"]
    )
    if run.get("expected_cache_artifacts") != expected_cache_artifacts:
        raise DesignerError("Run cache-artifact allowlist is inconsistent")
    if run.get("resource_hashes") != _resource_hashes():
        raise DesignerError("Designer resources changed after preparation")
    return run


def _run_fast_path(run_path: Path) -> int:
    run = _load_run(run_path, {"prepared"})
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(FAST_PATH),
        "-ModelPath",
        run["model_path"],
        "-TempOutputPath",
        run["stage_parent"],
        "-DeadlineSeconds",
        str(GENERATION_TIMEOUT_SECONDS),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=GENERATION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise DesignerError(
            "Packaged fast path stopped responding and was terminated"
        ) from exc
    if completed.returncode:
        raise DesignerError(
            "Packaged fast path failed:\n"
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    generation_report_path = Path(run["stage_design"]) / "run-report.json"
    report = _json_load(generation_report_path)
    if report.get("structuralValidation") != "passed":
        raise DesignerError(
            "Structural generation failed: "
            + "; ".join(report.get("validationIssues", []))
        )
    report["modelMs"] = run["model_ms"]
    _atomic_write_json(generation_report_path, report)
    slug = _json_load(Path(run["model_path"]))["scenarioSlug"]
    sa_png = Path(run["stage_design"]) / f"SA_{slug}.png"
    sd_png = Path(run["stage_design"]) / f"SD_{slug}.png"
    template = _json_load(Path(run["inspection_template_path"]))
    template["solution_architecture_png_sha256"] = _sha256_file(sa_png)
    template["sequence_png_sha256"] = _sha256_file(sd_png)
    _atomic_write_json(Path(run["inspection_template_path"]), template)
    staged_names = _artifact_names(Path(run["stage_design"]), slug) + [
        "run-report.json"
    ]
    staged_hashes = {
        name: _sha256_file(Path(run["stage_design"]) / name)
        for name in staged_names
    }
    run.update(
        {
            "status": "awaiting_inspection",
            "generated_at_local": _run_local_time(run),
            "scenario_slug": slug,
            "solution_architecture_png": str(sa_png),
            "sequence_png": str(sd_png),
            "generation_report_path": str(generation_report_path),
            "staged_artifacts": staged_hashes,
        }
    )
    _atomic_write_json(run_path, run)
    print(
        json.dumps(
            {
                "status": "awaiting_inspection",
                "solution_architecture_png": str(sa_png),
                "sequence_png": str(sd_png),
                "inspection_template": run["inspection_template_path"],
            },
            indent=2,
        )
    )
    return 0


def _artifact_names(stage_design: Path, slug: str) -> list[str]:
    return [
        "design-model.json",
        f"SA_{slug}.svg",
        f"SD_{slug}.svg",
        f"SA_{slug}.png",
        f"SD_{slug}.png",
        "diagram-manifest.json",
        "validation-report.json",
        "render-report.json",
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
        os.replace(temporary, destination)
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


def _replace_directory(temporary: Path, destination: Path) -> None:
    backup = destination.with_name(
        f".{destination.name}.backup-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    )
    if backup.exists():
        raise DesignerError(f"Artifact publication backup already exists: {backup}")
    if destination.exists():
        os.replace(destination, backup)
    try:
        _commit_directory(temporary, destination)
    except BaseException:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        if backup.exists():
            os.replace(backup, destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


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
        "renders": {
            "solution_architecture_png": str(artifact_root / f"SA_{slug}.png"),
            "sequence_png": str(artifact_root / f"SD_{slug}.png"),
        },
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
    cached_inspection["run_id"] = "CACHE"
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
        _atomic_write_json(temporary / "generation-report.json", generation)
        _atomic_write_json(temporary / "inspection-report.json", inspection)
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
            "artifacts": artifact_hashes,
        }
        _atomic_write_json(temporary / "run-report.json", final_report)
        published.append("run-report.json")
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
                _replace_directory(temporary, artifact_root)
                temporary = artifact_root
            else:
                shutil.rmtree(temporary)
        else:
            _commit_directory(temporary, artifact_root)
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
    pointer_result["renders"]["solution_architecture_png"] = relative(
        result["renders"]["solution_architecture_png"]
    )
    pointer_result["renders"]["sequence_png"] = relative(
        result["renders"]["sequence_png"]
    )
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
    inspection = _json_load(inspection_path)
    _schema_validate(inspection, INSPECTION_SCHEMA, "Inspection")
    if inspection["run_id"] != run["run_id"]:
        raise DesignerError("Inspection run_id does not match the active run")
    if inspection["status"] != "passed":
        raise DesignerError(
            "Rendered inspection failed: " + "; ".join(inspection["issues"])
        )
    try:
        inspected_at = datetime.fromisoformat(
            inspection["inspected_at"].replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise DesignerError("Inspection inspected_at is not valid ISO 8601") from exc
    run_started = datetime.fromisoformat(run["started_at_local"])
    elapsed_inspection = (inspected_at - run_started).total_seconds()
    if elapsed_inspection < 0 or elapsed_inspection > 420:
        raise DesignerError(
            "Rendered inspection was not completed inside the bounded work budget"
        )
    failed_checks = [
        name for name, passed in inspection["checks"].items() if not passed
    ]
    if failed_checks:
        raise DesignerError(
            "Rendered inspection has failed checks: " + ", ".join(failed_checks)
        )
    if inspection["issues"]:
        raise DesignerError("Passed inspection cannot contain issues")
    sa_png = Path(run["solution_architecture_png"])
    sd_png = Path(run["sequence_png"])
    if _sha256_file(sa_png) != inspection["solution_architecture_png_sha256"]:
        raise DesignerError("Solution Architecture PNG changed after inspection")
    if _sha256_file(sd_png) != inspection["sequence_png_sha256"]:
        raise DesignerError("Sequence PNG changed after inspection")
    generation = _json_load(Path(run["generation_report_path"]))
    stage_design = Path(run["stage_design"])
    design_root = Path(run["design_root"])
    slug = run["scenario_slug"]
    artifacts = _artifact_names(stage_design, slug)
    expected_staged = run.get("staged_artifacts", {})
    for name, expected_hash in expected_staged.items():
        artifact = stage_design / name
        if not artifact.exists() or _sha256_file(artifact) != expected_hash:
            raise DesignerError(
                f"Staged artifact changed after generation: {name}"
            )
    if not expected_staged:
        raise DesignerError("Run does not contain sealed staged-artifact hashes")
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
    _write_cache(run, artifact_root, published)
    _write_current_pointer(
        run, result, artifact_root, published, cache_hit=False
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
    inspection["run_id"] = run["run_id"]
    inspection["inspected_at"] = _run_local_time(run)
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
    _write_current_pointer(
        run, result, artifact_root, published, cache_hit=True
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
    prepare.set_defaults(handler=lambda args: _prepare(args))

    generate = commands.add_parser(
        "generate", help="Generate, validate, and render staged diagrams"
    )
    generate.add_argument("--run", required=True)
    generate.set_defaults(
        handler=lambda args: _run_fast_path(Path(args.run).resolve())
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
