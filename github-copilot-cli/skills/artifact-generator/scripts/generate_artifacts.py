#!/usr/bin/env python3
"""Generate the final LISA solution document and execution-tree HTML."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from validate_artifact_contracts import validate_contract
from lisa_path_resolver import LisaConfigError, resolve_lisa_config

STAGE_SPECS = (
    ("analysis", "Requirement Analysis", "analysis"),
    ("classification", "Complexity Classification", "classification"),
    ("design", "Solution Design", "design"),
    ("build", "Agent Build", "build"),
    ("evaluation", "Agent Evaluation", "evaluation"),
    ("optimization", "Agent Optimization", "optimization"),
)
FINAL_MARKDOWN = "solution-document.md"
FINAL_HTML = "lisa-execution-tree.html"
FINAL_ARCHITECTURE = "solution-architecture.png"
FINAL_SEQUENCE = "solution-sequence.png"
FINAL_MANIFEST = "artifact-generation-manifest.json"
ARTIFACT_FOLDER = "artifacts"
ARTIFACT_CONTRACT = validate_contract(Path(__file__).resolve().parents[1])
if ARTIFACT_CONTRACT["rootFolder"] != ARTIFACT_FOLDER:
    raise RuntimeError("Artifact contract root does not match ARTIFACT_FOLDER")
GENERATED_NAMES = {FINAL_MARKDOWN, FINAL_HTML, FINAL_MANIFEST}


class GenerationError(RuntimeError):
    pass


@dataclass
class Artifact:
    stage: str
    path: str
    kind: str
    bytes: int | None
    sha256: str | None
    note: str = ""


@dataclass
class Stage:
    key: str
    name: str
    directory: str
    status: str = "not-recorded"
    run_id: str = "Not recorded"
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    timing_basis: str = "Not recorded"
    markdown: list[Path] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GenerationError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GenerationError(f"Expected a JSON object in {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_iso(value: str | None, default_zone: tzinfo = timezone.utc) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=default_zone)
    except ValueError:
        return None


def seconds_between(
    start: str | None,
    end: str | None,
    default_zone: tzinfo = timezone.utc,
) -> float | None:
    start_value = parse_iso(start, default_zone)
    end_value = parse_iso(end, default_zone)
    if not start_value or not end_value:
        return None
    return max(0.0, (end_value - start_value).total_seconds())


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "Not recorded"
    if seconds < 1:
        return f"{seconds:.3f} s"
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, remaining = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m {remaining:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m {remaining:02d}s"


def display_status(value: str) -> str:
    return value.replace("_", " ").replace("-", " ").strip().title()


def relative_portable(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise GenerationError(f"Path escapes resolved output root: {path}") from exc


def resolve_base_relative(value: str, output_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        raise GenerationError("Design pointer paths must be relative to basePath")
    resolved = (output_root.parent / path).resolve()
    try:
        resolved.relative_to(output_root.parent.resolve())
    except ValueError as exc:
        raise GenerationError("Design pointer path escapes basePath") from exc
    return resolved


def resolve_output(config_path: Path) -> tuple[dict[str, Any], Path, Path]:
    try:
        paths = resolve_lisa_config(config_path)
    except LisaConfigError as exc:
        raise GenerationError(str(exc)) from exc
    config = paths.config
    project_root = paths.base
    output_root = paths.output.resolve()
    if not output_root.is_dir():
        raise GenerationError(f"Resolved output folder does not exist: {output_root}")
    return config, project_root, output_root


def configured_zone(config: dict[str, Any]) -> tzinfo:
    time_zone = config.get("timeZone")
    if not isinstance(time_zone, str) or not time_zone.strip():
        return datetime.now().astimezone().tzinfo or timezone.utc
    try:
        return ZoneInfo(time_zone.strip())
    except ZoneInfoNotFoundError as exc:
        raise GenerationError(f"Unknown timeZone in lisa-config.json: {time_zone}") from exc


def configured_now(config: dict[str, Any]) -> datetime:
    return datetime.now(configured_zone(config))


def is_current_path(path: Path, stage_root: Path) -> bool:
    relative = path.relative_to(stage_root)
    for part in relative.parts:
        if part.startswith(".") or part.casefold() == "legacy":
            return False
    return path.name not in GENERATED_NAMES


def discover_markdown(stage_root: Path) -> list[Path]:
    if not stage_root.is_dir():
        return []
    return sorted(
        (
            path
            for path in stage_root.rglob("*.md")
            if path.is_file() and is_current_path(path, stage_root)
        ),
        key=lambda item: item.relative_to(stage_root).as_posix().casefold(),
    )


def newest(paths: Iterable[Path]) -> Path | None:
    values = list(paths)
    return max(values, key=lambda path: path.stat().st_mtime_ns) if values else None


def read_markdown(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GenerationError(f"Cannot read Markdown {path}: {exc}") from exc


def extract_sections(text: str, titles: Iterable[str]) -> str:
    wanted = {title.casefold() for title in titles}
    lines = text.splitlines()
    selected: list[str] = []
    index = 0
    while index < len(lines):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", lines[index])
        if not match or match.group(2).strip().casefold() not in wanted:
            index += 1
            continue
        level = len(match.group(1))
        end = index + 1
        while end < len(lines):
            next_heading = re.match(r"^(#{1,6})\s+", lines[end])
            if next_heading and len(next_heading.group(1)) <= level:
                break
            end += 1
        selected.extend(lines[index:end])
        selected.append("")
        index = end
    return "\n".join(selected).strip()


def demote_markdown(text: str, amount: int = 1, drop_title: bool = False) -> str:
    result: list[str] = []
    for line in text.strip().splitlines():
        match = re.match(r"^(#{1,6})(\s+.*)$", line)
        if match:
            if drop_title and len(match.group(1)) == 1:
                continue
            level = min(6, len(match.group(1)) + amount)
            line = "#" * level + match.group(2)
        result.append(line.rstrip())
    return "\n".join(result).strip()


def first_section_body(text: str, title: str) -> str:
    block = extract_sections(text, [title])
    lines = block.splitlines()
    if lines and lines[0].startswith("#"):
        lines = lines[1:]
    return "\n".join(lines).strip()


def add_file_artifact(
    stage: Stage,
    path: Path,
    output_root: Path,
    note: str = "",
) -> None:
    if not path.is_file():
        return
    relative = relative_portable(path, output_root)
    if any(part.casefold() == "legacy" or part.startswith(".") for part in Path(relative).parts):
        return
    if any(item.path == relative for item in stage.artifacts):
        return
    stage.artifacts.append(
        Artifact(
            stage=stage.name,
            path=relative,
            kind=path.suffix.lower().lstrip(".") or "file",
            bytes=path.stat().st_size,
            sha256=sha256(path),
            note=note,
        )
    )


def add_directory_summary(
    stage: Stage,
    path: Path,
    output_root: Path,
    note: str,
) -> None:
    if not path.is_dir():
        return
    files = [item for item in path.rglob("*") if item.is_file()]
    relative = relative_portable(path, output_root).rstrip("/") + "/"
    if any(item.path == relative for item in stage.artifacts):
        return
    stage.artifacts.append(
        Artifact(
            stage=stage.name,
            path=relative,
            kind="directory",
            bytes=sum(item.stat().st_size for item in files),
            sha256=None,
            note=f"{note}; {len(files)} files",
        )
    )


def load_manifest_artifacts(
    stage: Stage,
    manifest_path: Path,
    stage_root: Path,
    output_root: Path,
    include_optional: re.Pattern[str] | None = None,
) -> None:
    if not manifest_path.is_file():
        return
    manifest = load_object(manifest_path)
    stage.status = str(manifest.get("status", stage.status))
    stage.run_id = str(manifest.get("runId", stage.run_id))
    for record in manifest.get("artifacts", []):
        if not isinstance(record, dict):
            continue
        relative = str(record.get("relativePath", "")).replace("\\", "/")
        required = bool(record.get("required"))
        if not required and not (include_optional and include_optional.fullmatch(relative)):
            continue
        path = stage_root / Path(relative)
        if path.is_file():
            add_file_artifact(stage, path, output_root)
        elif path.is_dir() and required:
            add_directory_summary(stage, path, output_root, "Required stage directory")


def stage_analysis(stage: Stage, root: Path, output_root: Path) -> None:
    for path in root.glob("*"):
        if path.is_file() and path.suffix.lower() in {".md", ".json"}:
            add_file_artifact(stage, path, output_root)
    runs = []
    for path in root.glob(".requirement-analyzer/runs/*/run.json"):
        value = load_object(path)
        if value.get("status") == "validated":
            runs.append((path, value))
    if runs:
        _, value = max(runs, key=lambda item: str(item[1].get("started_at_local", "")))
        stage.run_id = str(value.get("run_id", stage.run_id))
        stage.status = str(value.get("status", stage.status))
        stage.started_at = value.get("started_at_local")
        stage.completed_at = value.get("validated_at_local") or value.get("rendered_at_local")
        duration = value.get("duration_seconds")
        stage.duration_seconds = float(duration) if isinstance(duration, (int, float)) else None
        stage.timing_basis = "Explicit requirement-analyzer run duration"


def stage_classification(stage: Stage, root: Path, output_root: Path) -> None:
    for path in root.glob("*"):
        if path.is_file() and path.suffix.lower() in {".md", ".json"}:
            add_file_artifact(stage, path, output_root)
    runs = []
    for path in root.glob(".complexity-classifier/runs/*/run.json"):
        value = load_object(path)
        if value.get("status") == "validated":
            runs.append((path, value))
    if runs:
        _, value = max(runs, key=lambda item: str(item[1].get("completed_at_local", "")))
        stage.run_id = str(value.get("run_id", stage.run_id))
        stage.status = str(value.get("status", stage.status))
        stage.started_at = value.get("started_at_local")
        stage.completed_at = value.get("completed_at_local")
        duration = value.get("duration_seconds")
        stage.duration_seconds = float(duration) if isinstance(duration, (int, float)) else None
        stage.timing_basis = "Explicit complexity-classifier run duration"


def stage_design(stage: Stage, root: Path, output_root: Path) -> dict[str, Any]:
    pointer_path = root / "current-design.json"
    if not pointer_path.is_file():
        return {}
    pointer = load_object(pointer_path)
    add_file_artifact(stage, pointer_path, output_root)
    stage.run_id = str(pointer.get("run_id", stage.run_id))
    stage.status = str(pointer.get("validation", stage.status))
    timings = pointer.get("result", {}).get("timings_ms", {})
    total = timings.get("total") if isinstance(timings, dict) else None
    if isinstance(total, (int, float)):
        stage.duration_seconds = float(total) / 1000
        stage.timing_basis = "Explicit solution-designer total timing"
    stage.completed_at = pointer.get("updated_at")
    directory_value = pointer.get("artifact_directory")
    if isinstance(directory_value, str):
        directory = resolve_base_relative(directory_value, output_root)
        try:
            directory.resolve().relative_to(output_root.resolve())
        except ValueError as exc:
            raise GenerationError("Design artifact directory escapes output root") from exc
        for path in sorted(directory.glob("*")):
            if path.is_file():
                add_file_artifact(stage, path, output_root)
    return pointer


def stage_build(stage: Stage, root: Path, output_root: Path) -> None:
    manifest_path = root / "build-manifest.json"
    load_manifest_artifacts(stage, manifest_path, root, output_root)
    live_path = root / "agent-live-state.json"
    if live_path.is_file():
        live = load_object(live_path)
        stage.completed_at = live.get("capturedAt")
    if stage.duration_seconds is None:
        stage.timing_basis = "Not recorded by builder"


def stage_evaluation(
    stage: Stage,
    root: Path,
    output_root: Path,
    default_zone: tzinfo = timezone.utc,
) -> None:
    manifest_path = root / "evaluation-manifest.json"
    load_manifest_artifacts(stage, manifest_path, root, output_root)
    observations_path = root / "evaluation-observations.json"
    if observations_path.is_file():
        value = load_object(observations_path)
        stage.run_id = str(value.get("runId", stage.run_id))
        stage.started_at = value.get("startedAt")
        stage.completed_at = value.get("completedAt")
        stage.duration_seconds = seconds_between(
            stage.started_at, stage.completed_at, default_zone
        )
        stage.timing_basis = "Evaluation observation start/completion timestamps"
    add_directory_summary(stage, root / "evidence", output_root, "Playwright evidence")


def stage_optimization(
    stage: Stage,
    root: Path,
    output_root: Path,
    default_zone: tzinfo = timezone.utc,
) -> None:
    manifest_path = root / "optimization-manifest.json"
    include = re.compile(
        r"rounds/round-[0-9]{3}/(?:"
        r"(?:before|after|rollback)-state-manifest\.json|"
        r"round-report\.md|"
        r"snapshots/(?:before|after|rollback)/[^/]+\.zip)"
    )
    load_manifest_artifacts(stage, manifest_path, root, output_root, include)
    log_path = root / "optimization-change-log.json"
    if log_path.is_file():
        value = load_object(log_path)
        stage.run_id = str(value.get("runId", stage.run_id))
        stage.completed_at = value.get("generatedAt")
    starts: list[str] = []
    for path in root.glob("rounds/round-*/before-state-manifest.json"):
        captured = load_object(path).get("capturedAt")
        if isinstance(captured, str):
            starts.append(captured)
    if starts:
        stage.started_at = min(
            starts,
            key=lambda item: parse_iso(item, default_zone)
            or datetime.max.replace(tzinfo=default_zone),
        )
    stage.duration_seconds = seconds_between(
        stage.started_at, stage.completed_at, default_zone
    )
    stage.timing_basis = (
        "Earliest before-state capture to final change-log timestamp"
        if stage.duration_seconds is not None
        else "Not recorded by optimizer"
    )


def collect_stages(
    output_root: Path,
    default_zone: tzinfo = timezone.utc,
) -> tuple[list[Stage], dict[str, Any]]:
    stages: list[Stage] = []
    design_pointer: dict[str, Any] = {}
    handlers = {
        "analysis": stage_analysis,
        "classification": stage_classification,
        "build": stage_build,
        "evaluation": stage_evaluation,
        "optimization": stage_optimization,
    }
    missing = [
        directory
        for _, _, directory in STAGE_SPECS
        if not (output_root / directory).is_dir()
    ]
    if missing:
        raise GenerationError(
            f"Resolved output root is missing required stage directories: {missing}"
        )
    for key, name, directory in STAGE_SPECS:
        root = output_root / directory
        stage = Stage(key=key, name=name, directory=directory)
        stage.markdown = discover_markdown(root)
        if key == "design":
            design_pointer = stage_design(stage, root, output_root)
        elif key in {"evaluation", "optimization"}:
            handlers[key](stage, root, output_root, default_zone)
        else:
            handlers[key](stage, root, output_root)
        for markdown_path in stage.markdown:
            add_file_artifact(stage, markdown_path, output_root, "Stage Markdown source")
        stages.append(stage)
    return stages, design_pointer


def markdown_by_name(stage: Stage, pattern: str) -> Path | None:
    expression = re.compile(pattern, re.IGNORECASE)
    return newest(path for path in stage.markdown if expression.fullmatch(path.name))


def markdown_table_row(values: Iterable[str]) -> str:
    return "| " + " | ".join(value.replace("|", "\\|").replace("\n", " ") for value in values) + " |"


def human_size(value: int | None) -> str:
    if value is None:
        return "—"
    size = float(value)
    units = ["B", "KB", "MB", "GB"]
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"


def stage_content(stage: Stage, pattern: str) -> str:
    path = markdown_by_name(stage, pattern)
    return read_markdown(path) if path else ""


def solution_identity(
    config: dict[str, Any],
    design_pointer: dict[str, Any],
    output_root: Path,
) -> tuple[str, dict[str, str]]:
    model: dict[str, Any] = {}
    directory_value = design_pointer.get("artifact_directory")
    if isinstance(directory_value, str):
        path = resolve_base_relative(directory_value, output_root) / "design-model.json"
        if path.is_file():
            model = load_object(path)
    title = str(model.get("title") or "LISA Agentic Solution")
    agent: dict[str, Any] = {}
    build_handoff = output_root / "build" / "agent-build-handoff.json"
    if build_handoff.is_file():
        agent = load_object(build_handoff).get("agent", {})
    return title, {
        "Customer": str(config.get("custName", "Not recorded")),
        "Target solution": title,
        "Implemented agent": str(agent.get("name", "Not recorded")),
        "Agent ID": str(agent.get("agentId", "Not recorded")),
        "Schema name": str(agent.get("schemaName", "Not recorded")),
        "Harness": str(agent.get("harness", model.get("harness", "Not recorded"))),
        "Environment": str(agent.get("environmentId", "Not recorded")),
        "Output route": "output",
    }


def design_details(
    design_pointer: dict[str, Any], output_root: Path
) -> tuple[str, list[tuple[str, int]]]:
    directory_value = design_pointer.get("artifact_directory")
    if not isinstance(directory_value, str):
        return "No current design pointer was available.", []
    directory = resolve_base_relative(directory_value, output_root)
    model_path = directory / "design-model.json"
    if not model_path.is_file():
        return "The current design model was not available.", []
    model = load_object(model_path)
    summary = str(model.get("summary", "No design summary was recorded."))
    counts: dict[str, int] = {}
    for component in model.get("components", []):
        if isinstance(component, dict):
            layer = str(component.get("layer", "unspecified"))
            counts[layer] = counts.get(layer, 0) + 1
    return summary, sorted(counts.items())


def relative_image(
    design_pointer: dict[str, Any], output_root: Path, key: str
) -> str | None:
    value = design_pointer.get("result", {}).get("renders", {}).get(key)
    if not isinstance(value, str):
        return None
    path = resolve_base_relative(value, output_root)
    if not path.is_file():
        return None
    return relative_portable(path, output_root)


def optional_object(path: Path) -> dict[str, Any]:
    return load_object(path) if path.is_file() else {}


def newest_json(directory: Path, pattern: str) -> dict[str, Any]:
    path = newest(directory.glob(pattern))
    return load_object(path) if path else {}


def item_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
    return names


def summarized_names(names: Iterable[str], empty: str = "None recorded") -> str:
    unique = list(dict.fromkeys(name for name in names if name))
    if not unique:
        return empty
    if len(unique) <= 5:
        return ", ".join(unique)
    return ", ".join(unique[:5]) + f", and {len(unique) - 5} more"


def count_label(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


def lifecycle_context(output_root: Path, design_pointer: dict[str, Any]) -> dict[str, Any]:
    classification = newest_json(
        output_root / "classification", "complexity-classification_*.json"
    )
    build_live = optional_object(output_root / "build" / "agent-live-state.json")
    build_handoff = optional_object(output_root / "build" / "agent-build-handoff.json")
    evaluation = optional_object(
        output_root / "evaluation" / "evaluation-observations.json"
    )
    optimization = optional_object(
        output_root / "optimization" / "optimization-plan.json"
    )
    design_model: dict[str, Any] = {}
    directory_value = design_pointer.get("artifact_directory")
    if isinstance(directory_value, str):
        design_model = optional_object(
            resolve_base_relative(directory_value, output_root) / "design-model.json"
        )

    components = classification.get("components", {})
    if not isinstance(components, dict):
        components = {}
    failed_results = [
        result
        for result in evaluation.get("results", [])
        if isinstance(result, dict) and result.get("status") == "FAIL"
    ]
    rounds = [
        item for item in optimization.get("rounds", []) if isinstance(item, dict)
    ]
    accepted_rounds = [
        item for item in rounds if item.get("status") == "accepted"
    ]
    rejected_rounds = [
        item for item in rounds if item.get("status") == "rejected-and-rolled-back"
    ]
    deferred = [
        item
        for item in optimization.get("deferredFindings", [])
        if isinstance(item, dict)
    ]
    live_components = [
        item
        for item in build_live.get("components", [])
        if isinstance(item, dict)
    ]
    live_knowledge = [
        str(item.get("name"))
        for item in live_components
        if item.get("type") == "knowledge"
    ]
    accepted_knowledge = [
        str(change.get("proposed"))
        for item in accepted_rounds
        for change in item.get("proposedChanges", [])
        if isinstance(change, dict)
        and change.get("surface") == "knowledge"
        and change.get("proposed")
    ]
    target_security = item_names(components.get("security_controls"))
    target_governance = item_names(components.get("governance_controls"))
    target_alm = item_names(components.get("alm"))
    target_tools = item_names(components.get("tools"))
    target_automation = item_names(components.get("automation"))
    target_knowledge = item_names(components.get("knowledge_sources"))
    agent = build_handoff.get("agent", {})
    if not isinstance(agent, dict):
        agent = {}
    evaluation_decision = (
        evaluation.get("optimizerHandoff", {}).get("evaluationDecision")
        if isinstance(evaluation.get("optimizerHandoff"), dict)
        else None
    ) or "NOT_RECORDED"
    return {
        "classification": classification,
        "designModel": design_model,
        "buildLive": build_live,
        "agent": agent,
        "evaluation": evaluation,
        "evaluationDecision": str(evaluation_decision),
        "failedResults": failed_results,
        "optimization": optimization,
        "rounds": rounds,
        "acceptedRounds": accepted_rounds,
        "rejectedRounds": rejected_rounds,
        "deferredFindings": deferred,
        "liveComponents": live_components,
        "liveKnowledge": list(dict.fromkeys(live_knowledge + accepted_knowledge)),
        "targetKnowledge": target_knowledge,
        "targetTools": target_tools,
        "targetAutomation": target_automation,
        "targetSecurity": target_security,
        "targetGovernance": target_governance,
        "targetAlm": target_alm,
    }


def failure_summary(result: dict[str, Any]) -> str:
    reasons = result.get("failureReasons")
    if isinstance(reasons, list) and reasons:
        return " ".join(str(item) for item in reasons)
    symptom = result.get("scenario") or result.get("actualResponse") or "Failed evaluation"
    return str(symptom)


def capability_summary(capabilities: Any) -> str:
    if not isinstance(capabilities, dict) or not capabilities:
        return "No live capability inventory was recorded"
    values: list[str] = []
    for key, value in capabilities.items():
        label = re.sub(r"(?<!^)(?=[A-Z])", " ", str(key)).replace("_", " ")
        label = label[:1].upper() + label[1:]
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value) or "none"
        elif isinstance(value, bool):
            rendered = "enabled" if value else "disabled"
        else:
            rendered = str(value)
        values.append(f"{label}: {rendered}")
    return "; ".join(values)


def remove_empty_evidence_columns(text: str) -> str:
    lines = text.splitlines()
    index = 0
    while index + 1 < len(lines):
        if not lines[index].lstrip().startswith("|") or not re.match(
            r"^\s*\|(?:\s*:?-+:?\s*\|)+\s*$", lines[index + 1]
        ):
            index += 1
            continue
        end = index + 2
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            end += 1
        rows = [
            [cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in lines[index:end]
        ]
        if (
            rows
            and rows[0]
            and rows[0][-1].casefold() == "evidence"
            and all(not row[-1] for row in rows[2:] if row)
        ):
            for offset, row in enumerate(rows):
                lines[index + offset] = "| " + " | ".join(row[:-1]) + " |"
        index = end
    return "\n".join(lines)


def customer_clean_markdown(text: str) -> str:
    cleaned = re.sub(r"\s*\[(?:REQ|OBS|GAP)-[A-Z0-9]+\]", "", text)
    cleaned = re.sub(r"\b[a-f0-9]{64}\b", "[internal integrity value omitted]", cleaned)
    cleaned = re.sub(r"[A-Za-z]:\\[^|\n]+", "[internal path omitted]", cleaned)
    cleaned = re.sub(r"\s*\(basis=[^)]*\)", "", cleaned)
    cleaned = re.sub(r"(?m)^- \*\*Research stage:\*\*.*\n?", "", cleaned)
    cleaned = re.sub(r"(?m)^Deterministic counts:.*\n?", "", cleaned)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return remove_empty_evidence_columns(cleaned).strip()


def customer_decision(value: str) -> str:
    return {
        "PASS": "Ready",
        "FAIL": "Not ready",
        "BLOCKED": "Further work required",
        "NOT_RUN": "Not evaluated",
        "NOT_RECORDED": "Not recorded",
    }.get(value.upper(), display_status(value))


def customer_stage_result(stage: Stage, context: dict[str, Any]) -> str:
    if stage.key == "analysis":
        return "Business needs, outcomes, scope, and gaps documented"
    if stage.key == "classification":
        classification = context["classification"]
        return " / ".join(
            str(value)
            for value in [
                classification.get("complexity"),
                classification.get("agentic_platform"),
                classification.get("harness"),
            ]
            if value
        ) or "Platform recommendation documented"
    if stage.key == "design":
        return (
            f"{len(context['designModel'].get('components', []))} architecture components "
            "with solution and sequence diagrams"
        )
    if stage.key == "build":
        agent = context["agent"]
        live_agent = context["buildLive"].get("agent", {})
        state = live_agent.get("state") if isinstance(live_agent, dict) else None
        return f"{agent.get('name', 'Agent')} · {state or 'Build completed'}"
    if stage.key == "evaluation":
        summary = context["evaluation"].get("summary", {})
        return (
            f"{summary.get('passed', 0)} of {summary.get('total', 0)} scenarios passed; "
            f"{customer_decision(context['evaluationDecision'])}"
        )
    if stage.key == "optimization":
        return (
            f"{count_label(len(context['acceptedRounds']), 'accepted round')}; "
            f"{count_label(len(context['rejectedRounds']), 'rolled-back round')}; "
            f"{count_label(len(context['deferredFindings']), 'deferred item')}"
        )
    return "Customer deliverables generated"


def render_solution_document(
    config: dict[str, Any],
    output_root: Path,
    stages: list[Stage],
    design_pointer: dict[str, Any],
    generated_at: str,
) -> str:
    stage_map = {stage.key: stage for stage in stages}
    title, identity = solution_identity(config, design_pointer, output_root)
    analysis_text = stage_content(stage_map["analysis"], r"requirement-analysis_.*\.md")
    classification_text = stage_content(
        stage_map["classification"], r"complexity-classification_.*\.md"
    )
    context = lifecycle_context(output_root, design_pointer)
    classification = context["classification"]
    agent = context["agent"]
    build_live = context["buildLive"]
    evaluation = context["evaluation"]
    failed_results = context["failedResults"]
    deferred_findings = context["deferredFindings"]
    accepted_rounds = context["acceptedRounds"]
    rejected_rounds = context["rejectedRounds"]
    target_label = " ".join(
        str(value)
        for value in [
            classification.get("complexity"),
            classification.get("agentic_platform"),
            (
                f"{classification.get('harness')}-harness"
                if classification.get("harness")
                else None
            ),
        ]
        if value
    ) or "Not recorded"
    build_state = (
        build_live.get("agent", {}).get("state")
        if isinstance(build_live.get("agent"), dict)
        else None
    ) or agent.get("state") or "Not recorded"
    implemented_agent = agent.get("name") or "Not recorded"
    evaluation_decision = context["evaluationDecision"]
    analysis_sections = extract_sections(
        analysis_text,
        [
            "Problem Statement",
            "Current State",
            "Desired Future State",
            "Goals",
            "Success Criteria",
            "Metrics and Baselines",
            "Data Sources",
            "Integrations",
            "Agentic Behavior",
            "Dependencies and Constraints",
            "Solution Components",
            "Scope and Delivery Phases",
        ],
    )
    classification_sections = extract_sections(
        classification_text,
        [
            "Final Classification",
            "Agentic Platform, Code Tier and Harness",
            "Comprehensive Justification",
        ],
    )
    executive = first_section_body(analysis_text, "Executive Summary")
    design_summary, design_counts = design_details(design_pointer, output_root)
    architecture_section = first_section_body(
        classification_text, "Architecture and Sequence Design Contract"
    )
    architecture_overview = (
        architecture_section.split("\n\n", 1)[0].strip()
        if architecture_section
        else design_summary
    )
    architecture_png = relative_image(
        design_pointer, output_root, "solution_architecture_png"
    )
    sequence_png = relative_image(design_pointer, output_root, "sequence_png")

    eval_summary: dict[str, Any] = {}
    observations = output_root / "evaluation" / "evaluation-observations.json"
    if observations.is_file():
        eval_summary = load_object(observations).get("summary", {})
    customer_identity = {
        "Customer": identity["Customer"],
        "Solution": identity["Target solution"],
        "Delivered agent": identity["Implemented agent"],
        "Platform": target_label,
        "Deployment status": build_state,
    }

    lines = [
        f"# {title} Solution Document",
        "",
        f"> Customer solution summary generated {generated_at}.",
        "",
        "## Executive Summary",
        "",
        customer_clean_markdown(executive)
        if executive
        else "No requirement-analysis executive summary was available.",
        "",
        (
            f"The classified target is **{target_label}**. The current implementation is "
            f"**{implemented_agent}** with live state **{build_state}**. Evaluation is "
            f"**{customer_decision(evaluation_decision)}** ({eval_summary.get('passed', 0)} passed, "
            f"{eval_summary.get('failed', 0)} failed), and optimization is "
            f"**{customer_decision(stage_map['optimization'].status)}** after "
            f"{count_label(len(accepted_rounds), 'accepted round')} and "
            f"{count_label(len(rejected_rounds), 'rolled-back round')}."
        ),
        "",
        (
            "The latest deployment decision remains evidence-driven. "
            + (
                f"{count_label(len(failed_results), 'evaluated scenario')} "
                + ("remains" if len(failed_results) == 1 else "remain")
                + " unresolved."
                if failed_results
                else "No failed evaluation scenario is recorded."
            )
            + (
                f" The optimizer records "
                f"{count_label(len(deferred_findings), 'deferred finding')}."
                if deferred_findings
                else ""
            )
        ),
        "",
        "## Solution Identity",
        "",
        "| Property | Value |",
        "|---|---|",
    ]
    lines.extend(
        markdown_table_row([key, value]) for key, value in customer_identity.items()
    )
    lines.extend(
        [
            "",
            "## Lifecycle Outcome and Performance",
            "",
            "| Stage | Outcome | Duration | Customer-relevant result |",
            "|---|---|---:|---|",
        ]
    )
    for stage in stages:
        lines.append(
            markdown_table_row(
                [
                    stage.name,
                    (
                        customer_decision(stage.status)
                        if stage.key in {"evaluation", "optimization"}
                        else display_status(stage.status)
                    ),
                    format_duration(stage.duration_seconds),
                    customer_stage_result(stage, context),
                ]
            )
        )

    lines.extend(
        [
            "",
            "## Requirements and Business Context",
            "",
            customer_clean_markdown(demote_markdown(analysis_sections, 1))
            if analysis_sections
            else "No current Analysis Markdown was available.",
            "",
            "## Platform Selection, Complexity, and Target Components",
            "",
            customer_clean_markdown(demote_markdown(classification_sections, 1))
            if classification_sections
            else "No current Classification Markdown was available.",
            "",
            "## Solution Architecture",
            "",
            customer_clean_markdown(architecture_overview),
            "",
        ]
    )
    if architecture_png:
        lines.extend(
            [
                "### Solution Architecture Diagram",
                "",
                f"![Solution architecture diagram]({FINAL_ARCHITECTURE})",
                "",
            ]
        )
    if sequence_png:
        lines.extend(
            [
                "### Sequence Diagram",
                "",
                f"![Solution sequence diagram]({FINAL_SEQUENCE})",
                "",
            ]
        )
    lines.extend(
        [
            "### Designed Component Distribution",
            "",
            "| Architecture layer | Components |",
            "|---|---:|",
        ]
    )
    lines.extend(markdown_table_row([layer, str(count)]) for layer, count in design_counts)
    lines.extend(
        [
            "",
            "## Delivered Solution",
            "",
            "| Property | Delivered state |",
            "|---|---|",
            markdown_table_row(["Agent", str(implemented_agent)]),
            markdown_table_row(["Status", str(build_state)]),
            markdown_table_row(
                ["Harness", str(classification.get("harness", "Not recorded"))]
            ),
            markdown_table_row(
                [
                    "Channels",
                    summarized_names(
                        build_live.get("capabilities", {}).get("channels", [])
                        if isinstance(build_live.get("capabilities"), dict)
                        else []
                    ),
                ]
            ),
            markdown_table_row(
                ["Knowledge", summarized_names(context["liveKnowledge"])]
            ),
            markdown_table_row(
                [
                    "Runtime controls",
                    capability_summary(build_live.get("capabilities")),
                ]
            ),
            "",
            "### Delivered Capabilities",
            "",
            "\n".join(
                f"- **{item.get('name', 'Component')}:** {display_status(str(item.get('status', 'recorded')))}"
                for item in context["liveComponents"]
            )
            or "- No delivered component inventory was recorded.",
            "",
            "## Evaluation and Readiness",
            "",
            f"**Current deployment decision:** {customer_decision(evaluation_decision)}",
            "",
            "| Evaluation outcome | Count |",
            "|---|---:|",
            markdown_table_row(["Passed", str(eval_summary.get("passed", 0))]),
            markdown_table_row(["Failed", str(eval_summary.get("failed", 0))]),
            markdown_table_row(["Blocked", str(eval_summary.get("blocked", 0))]),
            markdown_table_row(["Not run", str(eval_summary.get("notRun", 0))]),
            "",
            "### Remaining Evaluation Gaps",
            "",
            "| Scenario | Why it matters |",
            "|---|---|",
            "\n".join(
                markdown_table_row(
                    [
                        str(result.get("scenario", "Unresolved scenario")),
                        customer_clean_markdown(failure_summary(result)),
                    ]
                )
                for result in failed_results
            )
            or markdown_table_row(["None recorded", "No unresolved scenario was recorded"]),
            "",
            "## Optimization and Final State",
            "",
            "| Round | Outcome | Change areas | Customer impact |",
            "|---:|---|---|---|",
            "\n".join(
                markdown_table_row(
                    [
                        str(item.get("roundNumber", index)),
                        display_status(str(item.get("status", "recorded"))),
                        summarized_names(
                            [
                                str(change.get("surface"))
                                for change in item.get("proposedChanges", [])
                                if isinstance(change, dict) and change.get("surface")
                            ]
                        ),
                        (
                            "Improvement retained after evaluation"
                            if item.get("status") == "accepted"
                            else "Change was rolled back because the required improvement was not achieved"
                        ),
                    ]
                )
                for index, item in enumerate(context["rounds"], 1)
            )
            or markdown_table_row(
                ["Not recorded", "No round recorded", "Not recorded", "Not recorded"]
            ),
            "",
            "## Target State Versus Implemented Current State",
            "",
            "| Area | Classified/design target | Implemented current state | Readiness implication |",
            "|---|---|---|---|",
            markdown_table_row(
                [
                    "Architecture",
                    f"{len(context['designModel'].get('components', []))} designed components; {target_label}",
                    f"{len(context['liveComponents'])} build components; {implemented_agent}; {build_state}",
                    f"Latest evaluation decision: {customer_decision(evaluation_decision)}",
                ]
            ),
            markdown_table_row(
                [
                    "Knowledge",
                    summarized_names(context["targetKnowledge"]),
                    summarized_names(context["liveKnowledge"]),
                    (
                        "Review failed groundedness cases before production"
                        if failed_results
                        else "No failed evaluation case recorded"
                    ),
                ]
            ),
            markdown_table_row(
                [
                    "Tools and automation",
                    summarized_names(
                        context["targetTools"] + context["targetAutomation"]
                    ),
                    summarized_names(
                        [
                            str(item.get("name"))
                            for item in context["liveComponents"]
                            if item.get("type") in {"tool", "automation", "flow"}
                        ],
                        "No live tool or automation component recorded",
                    ),
                    (
                        f"{count_label(len(failed_results), 'evaluated scenario')} "
                        + ("remains" if len(failed_results) == 1 else "remain")
                        + " unresolved"
                        if failed_results
                        else "No failed scenario recorded"
                    ),
                ]
            ),
            markdown_table_row(
                [
                    "Security and governance",
                    summarized_names(
                        context["targetSecurity"] + context["targetGovernance"]
                    ),
                    capability_summary(build_live.get("capabilities")),
                    "Validate policy-required controls in the production environment",
                ]
            ),
            "",
            "## Security, Governance, Operations, and ALM",
            "",
            f"- **Current live capabilities:** {capability_summary(build_live.get('capabilities'))}.",
            f"- **Target security controls:** {summarized_names(context['targetSecurity'])}.",
            f"- **Target governance controls:** {summarized_names(context['targetGovernance'])}.",
            f"- **Target ALM controls:** {summarized_names(context['targetAlm'])}.",
            "- Treat classified and designed controls as target state until build evidence verifies their deployment.",
            "- Promote only through environment-aware ALM with validated dependencies, configuration, connections, rollback, and evaluator-owned regression gates.",
            "",
            "## Known Gaps and Required Actions",
            "",
        ]
    )
    if failed_results:
        for result in failed_results:
            lines.append(
                f"- **{result.get('scenario', 'Unresolved evaluation scenario')}.** "
                f"{customer_clean_markdown(failure_summary(result))}"
            )
    if deferred_findings:
        for finding in deferred_findings:
            lines.append(
                f"- {customer_clean_markdown(str(finding.get('reason', 'A required implementation item remains deferred.')))}"
            )
    if not failed_results and not deferred_findings:
        lines.append("- No failed evaluation case or deferred optimization finding is recorded.")
    lines.extend(
        [
            "",
            "Repeat the agreed evaluation suite after each deployable change; only observed evaluation evidence should change the deployment decision.",
            "",
            "## Customer Deliverables",
            "",
            "- [LISA execution tree](lisa-execution-tree.html)",
        ]
    )
    if architecture_png:
        lines.append(f"- [Solution architecture diagram]({FINAL_ARCHITECTURE})")
    if sequence_png:
        lines.append(f"- [Solution sequence diagram]({FINAL_SEQUENCE})")
    lines.extend(
        [
            "",
            "## Final Recommendations",
            "",
            "- **Close the remaining capability gaps.** Supply and verify the production services, connections, and automations required by the unresolved scenarios.",
            "- **Preserve target/current separation.** Treat designed capabilities as future state until deployment evidence confirms them.",
            "- **Keep evaluation authoritative.** Repeat the agreed customer scenarios after each material change and use the observed result for readiness decisions.",
            "- **Maintain governance through promotion.** Validate access, data protection, connection configuration, monitoring, and rollback before production release.",
        ]
    )
    for finding in deferred_findings:
        lines.append(
            "- "
            + customer_clean_markdown(
                str(
                    finding.get(
                        "reason",
                        "Supply and verify the missing implementation evidence.",
                    )
                )
            )
        )
    lines.append("")
    return "\n".join(lines)


THEME_SCRIPT = """<script>
  (() => {
    const param = new URLSearchParams(window.location.search).get("scoutTheme");
    const theme =
      param || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.setAttribute("data-theme", theme);
  })();
</script>"""

THEME_CSS = """:root {
  color-scheme: light;
  --cp-bg: #f7f4ef;
  --cp-bg-elevated: #fcfbf8;
  --cp-surface: #ffffff;
  --cp-surface-soft: #f5f5f5;
  --cp-border: #dedede;
  --cp-border-strong: #919191;
  --cp-text: #242424;
  --cp-text-muted: #5c5c5c;
  --cp-text-soft: #6f6f6f;
  --cp-accent: #b11f4b;
  --cp-accent-hover: #9a1a41;
  --cp-accent-soft: rgba(177, 31, 75, 0.08);
  --cp-accent-fg: #ffffff;
  --cp-success: #16a34a;
  --cp-danger: #dc2626;
  --cp-warning: #f59e0b;
  --cp-link: #0078d4;
  --cp-shadow: 0 18px 48px rgba(0, 0, 0, 0.12);
  --cp-overlay: rgba(255, 255, 255, 0.8);
  --cp-panel: rgba(255, 255, 255, 0.86);
  --cp-panel-strong: rgba(255, 255, 255, 0.96);
  --cp-sheen: rgba(255, 255, 255, 0.55);
  --cp-highlight: rgba(177, 31, 75, 0.12);
}
html[data-theme="dark"] {
  color-scheme: dark;
  --cp-bg: #3d3b3a;
  --cp-bg-elevated: #343231;
  --cp-surface: #292929;
  --cp-surface-soft: #2e2e2e;
  --cp-border: #474747;
  --cp-border-strong: #5f5f5f;
  --cp-text: #dedede;
  --cp-text-muted: #919191;
  --cp-text-soft: #b0b0b0;
  --cp-accent: #fd8ea1;
  --cp-accent-hover: #fb7b91;
  --cp-accent-soft: rgba(253, 142, 161, 0.14);
  --cp-accent-fg: #1a1a1a;
  --cp-success: #4ade80;
  --cp-danger: #f87171;
  --cp-warning: #fbbf24;
  --cp-link: #4da6ff;
  --cp-shadow: 0 18px 48px rgba(0, 0, 0, 0.32);
  --cp-overlay: rgba(41, 41, 41, 0.88);
  --cp-panel: rgba(41, 41, 41, 0.72);
  --cp-panel-strong: rgba(41, 41, 41, 0.96);
  --cp-sheen: rgba(255, 255, 255, 0.04);
  --cp-highlight: rgba(253, 142, 161, 0.12);
}"""


def artifact_link(path: str) -> str:
    normalized = path.rstrip("/")
    prefix = f"{ARTIFACT_FOLDER}/"
    if normalized.startswith(prefix):
        normalized = normalized[len(prefix) :]
    else:
        normalized = "../" + normalized
    return quote(normalized, safe="/._-")


def render_artifact_rows(stage: Stage) -> str:
    rows: list[str] = []
    for artifact in sorted(stage.artifacts, key=lambda item: item.path.casefold()):
        label = html.escape(artifact.path)
        if artifact.kind == "directory":
            path_markup = f"<span class=\"artifact-path\">{label}</span>"
        else:
            path_markup = (
                f"<a class=\"artifact-path\" href=\"{artifact_link(artifact.path)}\">"
                f"{label}</a>"
            )
        note = html.escape(artifact.note or artifact.kind)
        rows.append(
            "<li>"
            f"{path_markup}"
            f"<span class=\"artifact-meta\">{html.escape(human_size(artifact.bytes))} · {note}</span>"
            "</li>"
        )
    return "".join(rows) or "<li><span class=\"artifact-meta\">No core artifact recorded</span></li>"


def status_class(status: str) -> str:
    value = status.casefold()
    if value in {"complete", "passed", "pass", "validated", "accepted"}:
        return "success"
    if value in {"fail", "failed", "blocked", "rolled-back", "rejected-and-rolled-back"}:
        return "danger"
    return "warning"


def render_execution_html(
    config: dict[str, Any],
    stages: list[Stage],
    generated_at: str,
    generator_run_id: str,
) -> str:
    tracked = sum(stage.duration_seconds or 0 for stage in stages)
    unrecorded = sum(stage.duration_seconds is None for stage in stages)
    max_duration = max((stage.duration_seconds or 0 for stage in stages), default=0)
    stage_cards: list[str] = []
    for index, stage in enumerate(stages, 1):
        percent = (
            max(2.0, (stage.duration_seconds or 0) / max_duration * 100)
            if max_duration and stage.duration_seconds is not None
            else 0
        )
        sources = "".join(
            f"<li><code>{html.escape(path.name)}</code></li>" for path in stage.markdown
        ) or "<li>None</li>"
        duration = format_duration(stage.duration_seconds)
        stage_cards.append(
            f"""
            <li class="stage" data-stage="{html.escape(stage.key)}" data-search="{html.escape((stage.name + ' ' + stage.run_id + ' ' + ' '.join(item.path for item in stage.artifacts)).casefold())}">
              <span class="stage-index" aria-hidden="true">{index}</span>
              <article class="stage-card">
                <header class="stage-header">
                  <div>
                    <p class="eyebrow">Stage {index}</p>
                    <h2>{html.escape(stage.name)}</h2>
                  </div>
                  <span class="badge {status_class(stage.status)}">{html.escape(display_status(stage.status))}</span>
                </header>
                <dl class="metadata">
                  <div><dt>Run ID</dt><dd><code>{html.escape(stage.run_id)}</code></dd></div>
                  <div><dt>Duration</dt><dd>{html.escape(duration)}</dd></div>
                  <div><dt>Markdown</dt><dd>{len(stage.markdown)}</dd></div>
                  <div><dt>Core artifacts</dt><dd>{len(stage.artifacts)}</dd></div>
                </dl>
                <div class="timing" title="{html.escape(stage.timing_basis)}">
                  <span style="width: {percent:.2f}%"></span>
                </div>
                <p class="timing-basis">{html.escape(stage.timing_basis)}</p>
                <details>
                  <summary>Stage Markdown</summary>
                  <ul class="source-list">{sources}</ul>
                </details>
                <details>
                  <summary>Core artifacts</summary>
                  <ul class="artifact-list">{render_artifact_rows(stage)}</ul>
                </details>
              </article>
            </li>"""
        )

    css = (
        THEME_CSS
        + """
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--cp-bg);
  color: var(--cp-text);
  font-family: "Segoe UI", Aptos, Calibri, -apple-system, BlinkMacSystemFont, sans-serif;
}
a { color: var(--cp-link); }
button, input { font: inherit; }
code {
  font-family: Consolas, "Courier New", Courier, monospace;
  overflow-wrap: anywhere;
}
.shell { width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 40px 0 64px; }
.hero {
  padding: 28px;
  background: var(--cp-surface);
  border: 1px solid var(--cp-border);
  border-radius: 16px;
  box-shadow: 0 0 2px var(--cp-border), 0 1px 2px var(--cp-border);
}
.eyebrow {
  margin: 0 0 4px;
  color: var(--cp-accent);
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
h1 { margin: 0; font-size: clamp(2rem, 5vw, 3.5rem); line-height: 1.05; }
h2 { margin: 0; font-size: 1.35rem; }
.subtitle { max-width: 760px; color: var(--cp-text-muted); line-height: 1.6; }
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-top: 24px;
}
.metric {
  padding: 16px;
  background: var(--cp-surface-soft);
  border: 1px solid var(--cp-border);
  border-radius: 0.625rem;
}
.metric strong { display: block; font-size: 1.35rem; }
.metric span { color: var(--cp-text-muted); font-size: 0.82rem; }
.toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 24px 0 12px;
  padding: 12px;
  background: var(--cp-bg-elevated);
  border: 1px solid var(--cp-border);
  border-radius: 0.625rem;
}
.toolbar input {
  min-width: 0;
  flex: 1;
  padding: 10px 12px;
  color: var(--cp-text);
  background: var(--cp-surface);
  border: 1px solid var(--cp-border);
  border-radius: 0.625rem;
}
.toolbar button {
  padding: 10px 12px;
  color: var(--cp-accent-fg);
  background: var(--cp-accent);
  border: 0;
  border-radius: 0.625rem;
  cursor: pointer;
}
.toolbar button:hover { background: var(--cp-accent-hover); }
.tree {
  position: relative;
  margin: 0;
  padding: 12px 0;
  list-style: none;
}
.tree::before {
  content: "";
  position: absolute;
  top: 24px;
  bottom: 24px;
  left: 23px;
  width: 2px;
  background: var(--cp-border-strong);
}
.stage {
  position: relative;
  display: grid;
  grid-template-columns: 48px 1fr;
  gap: 16px;
  margin: 0 0 20px;
}
.stage[hidden] { display: none; }
.stage-index {
  z-index: 1;
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  color: var(--cp-accent-fg);
  background: var(--cp-accent);
  border: 4px solid var(--cp-bg);
  border-radius: 50%;
  font-weight: 800;
}
.stage-card {
  padding: 20px;
  background: var(--cp-surface);
  border: 1px solid var(--cp-border);
  border-radius: 16px;
  box-shadow: 0 0 2px var(--cp-border), 0 1px 2px var(--cp-border);
}
.stage-header { display: flex; gap: 16px; align-items: flex-start; justify-content: space-between; }
.badge {
  padding: 5px 9px;
  border: 1px solid var(--cp-border);
  border-radius: 0.625rem;
  font-size: 0.75rem;
  font-weight: 700;
  white-space: nowrap;
}
.badge.success { color: var(--cp-success); }
.badge.danger { color: var(--cp-danger); }
.badge.warning { color: var(--cp-warning); }
.metadata {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 1fr;
  gap: 8px;
  margin: 16px 0;
}
.metadata div {
  min-width: 0;
  padding: 10px;
  background: var(--cp-surface-soft);
  border-radius: 0.625rem;
}
.metadata dt { color: var(--cp-text-muted); font-size: 0.72rem; text-transform: uppercase; }
.metadata dd { margin: 4px 0 0; font-weight: 600; }
.timing { height: 8px; overflow: hidden; background: var(--cp-border); border-radius: 0.625rem; }
.timing span { display: block; height: 100%; background: var(--cp-accent); }
.timing-basis { margin: 6px 0 16px; color: var(--cp-text-muted); font-size: 0.78rem; }
details { border-top: 1px solid var(--cp-border); }
summary { padding: 12px 0; cursor: pointer; font-weight: 600; }
.artifact-list, .source-list { margin: 0 0 12px; padding-left: 20px; }
.artifact-list li { margin: 8px 0; }
.artifact-path { overflow-wrap: anywhere; font-family: Consolas, "Courier New", Courier, monospace; }
.artifact-meta { display: block; color: var(--cp-text-muted); font-size: 0.78rem; }
.footer { color: var(--cp-text-muted); font-size: 0.82rem; text-align: center; }
@media (max-width: 760px) {
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .metadata { grid-template-columns: 1fr 1fr; }
  .toolbar { flex-wrap: wrap; }
  .toolbar input { flex-basis: 100%; }
}
@media (max-width: 480px) {
  .shell { width: min(100% - 20px, 1120px); padding-top: 16px; }
  .hero, .stage-card { padding: 16px; }
  .stage { grid-template-columns: 36px 1fr; gap: 8px; }
  .stage-index { width: 36px; height: 36px; border-width: 3px; }
  .tree::before { left: 17px; }
  .summary-grid, .metadata { grid-template-columns: 1fr; }
}
"""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LISA Execution Tree</title>
<link rel="icon" href="data:,">
{THEME_SCRIPT}
<style>
{css}
</style>
</head>
<body>
<main class="shell">
  <section class="hero">
    <p class="eyebrow">LISA lifecycle</p>
    <h1>Execution tree</h1>
    <p class="subtitle">Config-resolved lifecycle view for {html.escape(str(config.get("custName", "Unknown customer")))}. It links each stage to its current Markdown and core artifacts and distinguishes measured execution time from missing timing evidence.</p>
    <div class="summary-grid">
      <div class="metric"><strong>{len(stages)}</strong><span>Lifecycle stages</span></div>
      <div class="metric"><strong>{format_duration(tracked)}</strong><span>Tracked execution</span></div>
      <div class="metric"><strong>{sum(len(stage.artifacts) for stage in stages)}</strong><span>Core artifacts</span></div>
      <div class="metric"><strong>{unrecorded}</strong><span>Durations not recorded</span></div>
    </div>
  </section>
  <nav class="toolbar" aria-label="Execution tree controls">
    <input id="search" type="search" placeholder="Filter stages or artifacts" aria-label="Filter stages or artifacts">
    <button id="expand" type="button">Expand all</button>
    <button id="collapse" type="button">Collapse all</button>
  </nav>
  <ol class="tree">
    {''.join(stage_cards)}
  </ol>
  <p class="footer">Generated {html.escape(generated_at)} · Run <code>{html.escape(generator_run_id)}</code> · Output route <code>output</code></p>
</main>
<script>
(() => {{
  const stages = Array.from(document.querySelectorAll(".stage"));
  const search = document.getElementById("search");
  search.addEventListener("input", () => {{
    const query = search.value.trim().toLowerCase();
    stages.forEach((stage) => {{
      stage.hidden = query.length > 0 && !stage.dataset.search.includes(query);
    }});
  }});
  document.getElementById("expand").addEventListener("click", () => {{
    document.querySelectorAll("details").forEach((item) => {{ item.open = true; }});
  }});
  document.getElementById("collapse").addEventListener("click", () => {{
    document.querySelectorAll("details").forEach((item) => {{ item.open = false; }});
  }});
}})();
</script>
</body>
</html>
"""


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_copy(source: Path, destination: Path) -> None:
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def validate_outputs(
    markdown_path: Path,
    html_path: Path,
    stages: list[Stage],
    output_root: Path,
) -> None:
    markdown = markdown_path.read_text(encoding="utf-8")
    html_text = html_path.read_text(encoding="utf-8")
    if len(markdown) < 5000:
        raise GenerationError("Generated solution document is unexpectedly small")
    if len(html_text) < 10000:
        raise GenerationError("Generated execution tree is unexpectedly small")
    for stage in stages:
        if stage.name not in markdown or f'data-stage="{stage.key}"' not in html_text:
            raise GenerationError(f"Generated outputs omit stage: {stage.name}")
        for source in stage.markdown:
            read_markdown(source)
    if (
        markdown_path.parent.name != ARTIFACT_FOLDER
        or html_path.parent != markdown_path.parent
        or markdown_path.parent.parent.resolve() != output_root.resolve()
    ):
        raise GenerationError("Artifact-generator outputs must be under Output\\artifacts")
    forbidden_customer_content = [
        r"[A-Za-z]:\\",
        r"\b[a-f0-9]{64}\b",
        r"\b(?:REQ|OBS|GAP|EVAL|OPT-FINDING|BLD|SDR|CC|RA)-[A-Z0-9_-]+\b",
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
        r"Persisted Agent Instructions",
        r"Core Artifact Inventory",
        r"Source Markdown Register",
        r"Test Case Observations",
        r"SHA-256",
        r"\bbasis=",
        r"\bdocs=",
        r"\bsources=",
        r"\[internal ",
    ]
    for pattern in forbidden_customer_content:
        if re.search(pattern, markdown, re.IGNORECASE):
            raise GenerationError(
                f"Customer solution document contains internal content: {pattern}"
            )
    required_html = [
        "scoutTheme",
        "--cp-bg",
        "--cp-accent",
        '"Segoe UI", Aptos, Calibri',
        "Filter stages or artifacts",
    ]
    if any(value not in html_text for value in required_html):
        raise GenerationError("Execution tree does not satisfy the HTML theme/UI contract")
    if re.search(r"<(?:script|link)[^>]+(?:src|href)=[\"']https?://", html_text, re.I):
        raise GenerationError("Execution tree contains an external script or stylesheet")


def generate(config_path: Path) -> dict[str, Any]:
    started = time.perf_counter()
    config, project_root, output_root = resolve_output(config_path)
    zone = configured_zone(config)
    stages, design_pointer = collect_stages(output_root, zone)
    timestamp = datetime.now(zone)
    run_seed = f"{timestamp.isoformat()}|{config_path.resolve()}|{output_root}"
    run_id = (
        "ART-"
        + timestamp.strftime("%Y%m%d-%H%M%S-")
        + hashlib.sha256(run_seed.encode("utf-8")).hexdigest()[:8].upper()
    )
    generated_at = timestamp.isoformat()

    artifact_root = output_root / ARTIFACT_FOLDER
    artifact_root.mkdir(parents=True, exist_ok=True)
    architecture_relative = relative_image(
        design_pointer, output_root, "solution_architecture_png"
    )
    sequence_relative = relative_image(design_pointer, output_root, "sequence_png")
    diagram_outputs: list[tuple[Path, Path, str]] = []
    if architecture_relative:
        diagram_outputs.append(
            (
                output_root / Path(architecture_relative),
                artifact_root / FINAL_ARCHITECTURE,
                "Customer solution architecture diagram",
            )
        )
    if sequence_relative:
        diagram_outputs.append(
            (
                output_root / Path(sequence_relative),
                artifact_root / FINAL_SEQUENCE,
                "Customer solution sequence diagram",
            )
        )
    for source, destination, _ in diagram_outputs:
        atomic_copy(source, destination)

    generator_stage = Stage(
        key="artifact-generation",
        name="Artifact Generation",
        directory=".",
        status="complete",
        run_id=run_id,
        started_at=generated_at,
        completed_at=generated_at,
        duration_seconds=max(0.001, time.perf_counter() - started),
        timing_basis="Measured by artifact-generator",
    )
    generator_stage.artifacts = [
        Artifact(
            stage=generator_stage.name,
            path=f"{ARTIFACT_FOLDER}/{FINAL_MARKDOWN}",
            kind="md",
            bytes=None,
            sha256=None,
            note="Final solution document; self-referential SHA-256 omitted",
        ),
        Artifact(
            stage=generator_stage.name,
            path=f"{ARTIFACT_FOLDER}/{FINAL_HTML}",
            kind="html",
            bytes=None,
            sha256=None,
            note="LISA execution tree; self-referential SHA-256 omitted",
        ),
    ]
    for _, destination, note in diagram_outputs:
        generator_stage.artifacts.append(
            Artifact(
                stage=generator_stage.name,
                path=f"{ARTIFACT_FOLDER}/{destination.name}",
                kind="png",
                bytes=destination.stat().st_size,
                sha256=sha256(destination),
                note=note,
            )
        )
    all_stages = stages + [generator_stage]
    markdown_path = artifact_root / FINAL_MARKDOWN
    html_path = artifact_root / FINAL_HTML
    generator_stage.duration_seconds = max(0.001, time.perf_counter() - started)
    markdown = ""
    html_text = ""
    for _ in range(8):
        markdown = render_solution_document(
            config, output_root, all_stages, design_pointer, generated_at
        )
        html_text = render_execution_html(config, all_stages, generated_at, run_id)
        markdown_bytes = len(markdown.encode("utf-8"))
        html_bytes = len(html_text.encode("utf-8"))
        if (
            generator_stage.artifacts[0].bytes == markdown_bytes
            and generator_stage.artifacts[1].bytes == html_bytes
        ):
            break
        generator_stage.artifacts[0].bytes = markdown_bytes
        generator_stage.artifacts[1].bytes = html_bytes
    else:
        raise GenerationError("Generated artifact sizes did not converge")
    if (
        generator_stage.artifacts[0].bytes != len(markdown.encode("utf-8"))
        or generator_stage.artifacts[1].bytes != len(html_text.encode("utf-8"))
    ):
        raise GenerationError("Generated artifact size inventory is inconsistent")

    atomic_write(markdown_path, markdown)
    atomic_write(html_path, html_text)
    validate_outputs(markdown_path, html_path, all_stages, output_root)
    published_paths = [markdown_path, html_path] + [
        destination for _, destination, _ in diagram_outputs
    ]
    manifest = {
        "schemaVersion": "1.0",
        "stage": "artifacts",
        "runId": run_id,
        "status": "passed",
        "generatedAt": generated_at,
        "configSha256": sha256(config_path.resolve()),
        "artifacts": [
            {
                "relativePath": path.relative_to(project_root).as_posix(),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in published_paths
        ],
    }
    try:
        import jsonschema

        schema_path = (
            Path(__file__).resolve().parents[1]
            / "resources"
            / "artifact-generation-manifest.schema.json"
        )
        jsonschema.Draft202012Validator(
            load_object(schema_path),
            format_checker=jsonschema.FormatChecker(),
        ).validate(manifest)
    except ImportError as exc:
        raise GenerationError(
            "jsonschema is required to validate the artifact manifest"
        ) from exc
    except jsonschema.ValidationError as exc:
        location = ".".join(str(item) for item in exc.absolute_path) or "<root>"
        raise GenerationError(
            f"Artifact manifest schema error at {location}: {exc.message}"
        ) from exc
    manifest_path = artifact_root / FINAL_MANIFEST
    atomic_write(
        manifest_path,
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
    )
    for obsolete in (output_root / FINAL_MARKDOWN, output_root / FINAL_HTML):
        if obsolete.is_file():
            obsolete.unlink()
    return {
        "status": "passed",
        "runId": run_id,
        "config": str(config_path.resolve()),
        "projectRoot": str(project_root),
        "outputRoot": str(output_root),
        "artifactRoot": str(artifact_root),
        "solutionDocument": str(markdown_path),
        "executionTree": str(html_path),
        "manifest": str(manifest_path),
        "durationSeconds": round(time.perf_counter() - started, 3),
        "stageCount": len(all_stages),
        "markdownSourceCount": sum(len(stage.markdown) for stage in stages),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to config/lisa-config.json")
    args = parser.parse_args()
    try:
        print(json.dumps(generate(Path(args.config)), indent=2))
        return 0
    except (GenerationError, OSError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
