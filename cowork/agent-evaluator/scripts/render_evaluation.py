#!/usr/bin/env python3
"""Render every derived evaluation artifact from the model-authored dataset, rubric, and observations.

The model writes only `evaluation-dataset.json`, `evaluation-rubric.json`, and the per-test
captured results in `evaluation-observations.json`. This script copies dataset fields into the
observations, recomputes counts and gate aggregates, refuses an unsupported PASS, and writes
`evaluation-dataset.csv`, `regression-baseline.json` (only when no prior baseline exists),
`evaluation-run-report.md`, and `deployment-gate-summary.md`.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT.parent))

from lifecycle_artifacts import ArtifactError, load_object, validate_schema  # noqa: E402

RESOURCES = SKILL_ROOT / "resources"
GATES = (
    ("LLM_AS_JUDGE", "llmAsJudge", "LLM-as-Judge"),
    ("TOOL_USE", "toolUse", "Tool Use"),
    ("GROUNDEDNESS", "groundedness", "Groundedness"),
    ("REGRESSION", "regression", "Regression"),
)
CSV_COLUMNS = (
    "id", "scenario", "sourceType", "sourceReferences", "userPrompt", "expectedResponse",
    "expectedBehavior", "responseAssertions", "expectedKnowledgeSources", "requiredTools",
    "prohibitedBehavior", "evaluationTypes", "severity", "passCriteria", "failCriteria",
)
COPIED_FIELDS = ("scenario", "userPrompt", "expectedResponse")
MANIFEST_STATUS = {"PASS": "pass", "FAIL": "fail", "BLOCKED": "blocked", "NOT_RUN": "blocked"}
EXECUTED = {"PASS", "FAIL"}


def write_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def write_json(path: Path, value: dict[str, Any]) -> None:
    write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def compact(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "" if value is None else str(value)


def cell(value: Any) -> str:
    return compact(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def quote(text: str | None) -> str:
    if not text:
        return "> Not available"
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def hydrate(dataset: dict[str, Any], observations: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = {case["id"]: case for case in dataset["testCases"]}
    if len(cases) != len(dataset["testCases"]):
        raise ArtifactError("Dataset test-case IDs must be unique")
    results = observations.get("results", [])
    result_ids = [item.get("testCaseId") for item in results]
    if len(result_ids) != len(set(result_ids)) or set(result_ids) != set(cases):
        missing = sorted(set(cases) - set(result_ids))
        extra = sorted(set(result_ids) - set(cases))
        raise ArtifactError(
            f"Observations must cover every dataset test exactly once; missing={missing}, extra={extra}"
        )
    for result in results:
        case = cases[result["testCaseId"]]
        for field in COPIED_FIELDS:
            if field in result and result[field] != case[field]:
                raise ArtifactError(
                    f"{result['testCaseId']}.{field} differs from the dataset; omit copied fields"
                )
            result[field] = case[field]
    observations["results"] = sorted(results, key=lambda item: item["testCaseId"])
    observations["summary"] = {
        "total": len(results),
        "passed": sum(item["status"] == "PASS" for item in results),
        "failed": sum(item["status"] == "FAIL" for item in results),
        "blocked": sum(item["status"] == "BLOCKED" for item in results),
        "notRun": sum(item["status"] == "NOT_RUN" for item in results),
    }
    return cases


def check_results(cases: dict[str, dict[str, Any]], results: list[dict[str, Any]]) -> None:
    errors = []
    for result in results:
        test_id = result["testCaseId"]
        if result["status"] not in EXECUTED:
            continue
        if not result["playwrightObservations"].get("evidence"):
            errors.append(f"{test_id} was executed without browser evidence")
        for gate, key, _ in GATES:
            if gate not in cases[test_id]["evaluationTypes"]:
                continue
            outcome = result.get("gateResults", {}).get(key)
            if not isinstance(outcome, dict) or "status" not in outcome:
                errors.append(f"{test_id} lacks gateResults.{key}")
            elif result["status"] == "PASS" and outcome["status"] in {"FAIL", "NOT_OBSERVABLE"}:
                errors.append(f"{test_id} is PASS but {key} is {outcome['status']}")
    if errors:
        raise ArtifactError("; ".join(errors))


def gate_summary(results: list[dict[str, Any]], rubric: dict[str, Any]) -> dict[str, Any]:
    summary = {}
    for gate, key, _ in GATES:
        outcomes = [item.get("gateResults", {}).get(key) for item in results]
        outcomes = [item for item in outcomes if isinstance(item, dict)]
        scores = [
            float(item["score"]) for item in outcomes
            if item.get("status") in {"PASS", "FAIL"} and isinstance(item.get("score"), (int, float))
        ]
        threshold = float(rubric["gates"][gate]["passThreshold"])
        average = round(sum(scores) / len(scores), 2) if scores else None
        summary[key] = {
            "scored": len(scores),
            "average": average,
            "threshold": threshold,
            "notObservable": sum(item.get("status") == "NOT_OBSERVABLE" for item in outcomes),
            "status": "NOT_APPLICABLE" if average is None else ("PASS" if average >= threshold else "FAIL"),
        }
    return summary


def pass_blockers(
    cases: dict[str, dict[str, Any]],
    results: list[dict[str, Any]],
    gates: dict[str, Any],
    rubric: dict[str, Any],
) -> list[str]:
    reasons = []
    unexecuted = [item["testCaseId"] for item in results if item["status"] not in EXECUTED]
    if unexecuted:
        reasons.append(f"blocked or not-run tests: {unexecuted}")
    if rubric["overall"]["criticalTestsMustPass"]:
        critical = [
            item["testCaseId"] for item in results
            if cases[item["testCaseId"]]["severity"] == "critical" and item["status"] != "PASS"
        ]
        if critical:
            reasons.append(f"critical tests not passed: {critical}")
    failed_gates = [key for key, value in gates.items() if value["status"] == "FAIL"]
    if failed_gates:
        reasons.append(f"gates below threshold: {failed_gates}")
    scores = [
        float(outcome["score"])
        for item in results
        for outcome in item.get("gateResults", {}).values()
        if isinstance(outcome, dict)
        and outcome.get("status") in {"PASS", "FAIL"}
        and isinstance(outcome.get("score"), (int, float))
    ]
    minimum = float(rubric["overall"]["minimumAverage"])
    if scores and sum(scores) / len(scores) < minimum:
        reasons.append(f"overall average below {minimum}")
    return reasons


def build_run_id(root: Path) -> tuple[str | None, str | None]:
    handoff_path = root.parent / "build" / "agent-build-handoff.json"
    if not handoff_path.is_file():
        return None, None
    handoff = load_object(handoff_path)
    return handoff.get("runId"), handoff.get("instructions", {}).get("sha256")


def resolve_baseline(
    root: Path, observations: dict[str, Any], instruction_sha: str | None
) -> tuple[dict[str, Any], bool]:
    path = root / "regression-baseline.json"
    run_id = observations["runId"]
    if path.is_file():
        existing = load_object(path)
        if existing.get("sourceRunId") != run_id or existing.get("approvalStatus") != "candidate-unapproved":
            return existing, False
    sha = observations.get("instructionSha256") or instruction_sha
    if not sha:
        raise ArtifactError("Cannot create a regression baseline without the instruction SHA-256")
    results = observations["results"]
    baseline = {
        "schemaVersion": "1.0",
        "baselineId": f"{observations['testSetId']}-{run_id}",
        "approvalStatus": "candidate-unapproved",
        "createdAt": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "sourceRunId": run_id,
        "agent": {
            "name": observations["agent"]["name"],
            "agentId": observations["agent"]["agentId"],
            "harness": observations["agent"]["harness"],
            "instructionSha256": sha,
        },
        "summary": {
            "passed": observations["summary"]["passed"],
            "failed": observations["summary"]["failed"],
        },
        "cases": [
            {
                "testCaseId": item["testCaseId"],
                "status": item["status"],
                "scores": {
                    key: outcome.get("score")
                    for key, outcome in item.get("gateResults", {}).items()
                    if isinstance(outcome, dict)
                },
                "userPrompt": item["userPrompt"],
                "expectedResponse": item["expectedResponse"],
                "actualResponse": item["actualResponse"],
            }
            for item in results
        ],
    }
    validate_schema(baseline, RESOURCES / "regression-baseline.schema.json", "Regression baseline")
    write_json(path, baseline)
    return baseline, True


def regression_lines(baseline: dict[str, Any], created: bool, results: list[dict[str, Any]]) -> list[str]:
    if created:
        return [
            f"No prior baseline existed. Created candidate baseline `{baseline['baselineId']}` from "
            "this run; regression was not enforced."
        ]
    current = {item["testCaseId"]: item["status"] for item in results}
    regressed = [
        case["testCaseId"] for case in baseline["cases"]
        if case["status"] == "PASS" and current.get(case["testCaseId"], "NOT_RUN") != "PASS"
    ]
    lines = [
        f"Baseline `{baseline['baselineId']}` ({baseline['approvalStatus']}) from "
        f"`{baseline['sourceRunId']}`."
    ]
    lines.append(
        f"Regressed tests: {', '.join(regressed)}." if regressed
        else "No previously passing test regressed."
    )
    return lines


def dataset_csv(dataset: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_COLUMNS)
    for case in dataset["testCases"]:
        writer.writerow([compact(case.get(column)) for column in CSV_COLUMNS])
    return buffer.getvalue()


def blockers_and_unobservable(results: list[dict[str, Any]]) -> list[str]:
    lines = []
    for item in results:
        if item["status"] in {"BLOCKED", "NOT_RUN"}:
            lines.append(f"- {item['testCaseId']} {item['status']}: {item.get('blocker') or 'No reason recorded'}")
        for _, key, label in GATES:
            outcome = item.get("gateResults", {}).get(key)
            if isinstance(outcome, dict) and outcome.get("status") == "NOT_OBSERVABLE":
                lines.append(f"- {item['testCaseId']} {label} NOT_OBSERVABLE: {outcome.get('rationale', '')}")
    return lines or ["- None"]


def run_report(
    dataset: dict[str, Any],
    observations: dict[str, Any],
    cases: dict[str, dict[str, Any]],
    regression: list[str],
) -> str:
    agent = observations["agent"]
    summary = observations["summary"]
    handoff = observations["optimizerHandoff"]
    gates = observations["gateSummary"]
    lines = [
        "# Agent Evaluation Run Report",
        "",
        "## Run Metadata",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Run ID | {observations['runId']} |",
        f"| Test set | {cell(observations['testSetId'])} |",
        f"| Agent | {cell(agent['name'])} ({cell(agent['agentId'])}) |",
        f"| Harness | {cell(agent['harness'])} |",
        f"| Surface used | {cell(agent['surface'])} |",
        f"| Environment | {cell(agent['environmentId'])} |",
        f"| Started / completed | {observations['startedAt']} / {observations['completedAt']} |",
    ]
    if observations.get("instructionSha256"):
        lines.append(f"| Instruction SHA-256 | {observations['instructionSha256']} |")
    lines += ["", "## Source and Requirement Coverage", "", "| Source | Type | Authority | Tests |", "|---|---|---|---:|"]
    for source in dataset["sources"]:
        count = sum(
            any(ref["source"] == source["name"] for ref in case["sourceReferences"])
            for case in dataset["testCases"]
        )
        lines.append(f"| {cell(source['name'])} | {cell(source['type'])} | {source['authority']} | {count} |")
    severities = {level: 0 for level in ("critical", "high", "medium", "low")}
    for case in dataset["testCases"]:
        severities[case["severity"]] += 1
    lines += [
        "",
        "Severity coverage: " + ", ".join(f"{level} {count}" for level, count in severities.items()) + ".",
        "",
        "## Execution Summary",
        "",
        f"Total {summary['total']}; passed {summary['passed']}; failed {summary['failed']}; "
        f"blocked {summary['blocked']}; not run {summary['notRun']}.",
        "",
        "## Gate Summary",
        "",
        "| Gate | Scored | Average | Threshold | Not observable | Result |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for _, key, label in GATES:
        value = gates[key]
        average = "-" if value["average"] is None else value["average"]
        lines.append(
            f"| {label} | {value['scored']} | {average} | {value['threshold']} | "
            f"{value['notObservable']} | {value['status']} |"
        )
    lines += ["", "## Test Case Observations"]
    for item in observations["results"]:
        seen = item["playwrightObservations"]
        notes = "; ".join(
            part for part in (
                f"surface {seen.get('surfaceUsed')}",
                f"reset {seen.get('conversationReset')}",
                f"completed {seen.get('responseCompleted')}",
                f"attempts {item['attempts']}",
                f"{item['durationMs']} ms",
                "citations " + (", ".join(seen.get("citationsObserved", [])) or "none"),
                "tools " + (", ".join(seen.get("toolActivityObserved", [])) or "none"),
                "errors " + (", ".join(seen.get("uiErrors", [])) or "none"),
                "evidence " + (", ".join(seen.get("evidence", [])) or "none"),
                seen.get("notes") or "",
            ) if part
        )
        lines += [
            "",
            f"### {item['testCaseId']}: {item['scenario']}",
            "",
            "**User prompt:**",
            "",
            quote(item["userPrompt"]),
            "",
            "**Expected response:**",
            "",
            quote(item["expectedResponse"]),
            "",
            "**Actual response:**",
            "",
            quote(item.get("actualResponse")),
            "",
            f"**Playwright observations:** {notes}",
            "",
            "| Gate | Status | Score | Rationale |",
            "|---|---|---:|---|",
        ]
        for gate, key, label in GATES:
            outcome = item.get("gateResults", {}).get(key)
            if gate not in cases[item["testCaseId"]]["evaluationTypes"] or not isinstance(outcome, dict):
                lines.append(f"| {label} | NOT_APPLICABLE | - | Not in scope for this test |")
                continue
            score = outcome.get("score")
            lines.append(
                f"| {label} | {outcome.get('status')} | {'-' if score is None else score} | "
                f"{cell(outcome.get('rationale', ''))} |"
            )
        reasons = item.get("failureReasons") or ([item["blocker"]] if item.get("blocker") else [])
        lines += [
            "",
            f"**Overall result:** {item['status']}",
            "",
            f"**Failure reasons or blocker:** {cell('; '.join(map(str, reasons))) or 'None'}",
        ]
    failures = [
        f"- {item['testCaseId']} ({cases[item['testCaseId']]['severity']}) {item['status']}: "
        f"{cell('; '.join(map(str, item.get('failureReasons') or [])) or item.get('blocker') or 'No reason recorded')}"
        for item in observations["results"] if item["status"] != "PASS"
    ]
    lines += ["", "## Failures and Blockers", "", *(failures or ["- None"])]
    findings = [
        f"- {finding.get('id')} ({finding.get('severity')}; {', '.join(finding.get('failedGates', []))}): "
        f"{cell(finding.get('observedSymptom', ''))} Retest: {', '.join(finding.get('requiredRetestScope', []))}."
        for finding in handoff["findings"]
    ]
    lines += [
        "",
        "## Optimizer Handoff",
        "",
        f"Eligible for optimization: {handoff['eligibleForOptimization']}.",
        "",
        *(findings or ["- No findings."]),
        "",
        "## Regression Comparison",
        "",
        *regression,
        "",
        "## Overall Decision",
        "",
        f"**{handoff['evaluationDecision']}**",
        "",
    ]
    return "\n".join(lines)


def gate_report(observations: dict[str, Any], cases: dict[str, dict[str, Any]], regression: list[str], root: Path) -> str:
    agent = observations["agent"]
    summary = observations["summary"]
    handoff = observations["optimizerHandoff"]
    serious = [
        f"- {item['testCaseId']} ({cases[item['testCaseId']]['severity']})"
        for item in observations["results"]
        if item["status"] == "FAIL" and cases[item["testCaseId"]]["severity"] in {"critical", "high"}
    ]
    retest = sorted({
        test for finding in handoff["findings"] for test in finding.get("requiredRetestScope", [])
    })
    artifacts = [
        "evaluation-dataset.json", "evaluation-dataset.csv", "evaluation-rubric.json",
        "evaluation-observations.json", "regression-baseline.json", "evaluation-run-report.md",
        "deployment-gate-summary.md",
    ] + sorted(
        path.relative_to(root).as_posix()
        for path in (root / "evidence").glob("*") if path.is_file()
    )
    lines = [
        "# Deployment Gate Summary",
        "",
        f"**Overall decision:** {handoff['evaluationDecision']}",
        "",
        f"- Harness: {agent['harness']}; surface used: {agent['surface']}",
        f"- Tests: passed {summary['passed']}, failed {summary['failed']}, blocked {summary['blocked']}, not run {summary['notRun']}",
        "",
        "## Mandatory gates",
        "",
        *[
            f"- {label}: {observations['gateSummary'][key]['status']}"
            for _, key, label in GATES
        ],
        "",
        "## Critical and high-severity failures",
        "",
        *(serious or ["- None"]),
        "",
        "## Blockers and unobservable criteria",
        "",
        *blockers_and_unobservable(observations["results"]),
        "",
        "## Regression",
        "",
        *regression,
        "",
        "## Remediation and retest scope",
        "",
        f"- Retest: {', '.join(retest) if retest else 'None'}",
        f"- Optimizer eligible: {handoff['eligibleForOptimization']}; findings: "
        f"{', '.join(str(item.get('id')) for item in handoff['findings']) or 'None'}",
        "",
        "## Artifacts (relative to `output/evaluation`)",
        "",
        *[f"- {name}" for name in artifacts],
        "",
    ]
    return "\n".join(lines)


def render(root: Path) -> dict[str, Any]:
    root = root.resolve()
    if root.name != "evaluation" or not root.is_dir():
        raise ArtifactError(f"Expected an existing evaluation folder: {root}")
    dataset = load_object(root / "evaluation-dataset.json")
    rubric = load_object(root / "evaluation-rubric.json")
    observations_path = root / "evaluation-observations.json"
    observations = load_object(observations_path)
    validate_schema(dataset, RESOURCES / "evaluation-dataset.schema.json", "Evaluation dataset")
    validate_schema(rubric, RESOURCES / "evaluation-rubric.schema.json", "Evaluation rubric")
    if dataset["testSetId"] != observations.get("testSetId"):
        raise ArtifactError("Dataset and observations use different test-set IDs")

    cases = hydrate(dataset, observations)
    results = observations["results"]
    observations["gateSummary"] = gate_summary(results, rubric)
    validate_schema(observations, RESOURCES / "evaluation-observations.schema.json", "Evaluation observations")
    check_results(cases, results)
    decision = observations["optimizerHandoff"]["evaluationDecision"]
    if decision == "PASS":
        reasons = pass_blockers(cases, results, observations["gateSummary"], rubric)
        if reasons:
            raise ArtifactError("Deployment gate cannot PASS: " + "; ".join(reasons))

    build_run, instruction_sha = build_run_id(root)
    baseline, created = resolve_baseline(root, observations, instruction_sha)
    regression = regression_lines(baseline, created, results)
    write_json(observations_path, observations)
    write_text(root / "evaluation-dataset.csv", dataset_csv(dataset))
    write_text(root / "evaluation-run-report.md", run_report(dataset, observations, cases, regression))
    write_text(root / "deployment-gate-summary.md", gate_report(observations, cases, regression, root))

    source_runs = [run for run in (build_run, baseline["sourceRunId"]) if run and run != observations["runId"]]
    return {
        "status": "rendered",
        "decision": decision,
        "manifestStatus": MANIFEST_STATUS[decision],
        "sourceRuns": list(dict.fromkeys(source_runs)),
        "baselineCreated": created,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render derived evaluation artifacts")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(render(Path(args.root)), indent=2))
        return 0
    except (ArtifactError, KeyError, TypeError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
