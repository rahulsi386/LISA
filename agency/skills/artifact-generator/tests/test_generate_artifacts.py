from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from generate_artifacts import GenerationError, generate, resolve_output  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


class ArtifactGeneratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name) / "ProjectLISA"
        self.config = self.project / "config" / "lisa-config.json"
        self.output = self.project / "output"
        self.output.mkdir(parents=True)
        write_json(
            self.config,
            {
                "version": "1.0.0",
                "basePath": "..",
                "custName": "Fixture Customer",
                "timeZone": "Asia/Kolkata",
            },
        )
        self.create_fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_fixture(self) -> None:
        analysis = self.output / "analysis"
        write(
            analysis / "requirement-analysis_20260818_120000.md",
            """# Requirement Analysis

## Executive Summary
Fixture analysis marker describes the required solution.

## Problem Statement
- Manual work is slow.

## Desired Future State
- Automate governed work.

## Goals
- Improve outcomes.

## Gaps and Conflicts
- Production endpoint is missing.
""",
        )
        write_json(
            analysis
            / ".requirement-analyzer"
            / "runs"
            / "RA-20260818_120000-ABCDEF12"
            / "run.json",
            {
                "run_id": "RA-20260818_120000-ABCDEF12",
                "status": "validated",
                "started_at_local": "2026-08-18T12:00:00+05:30",
                "validated_at_local": "2026-08-18T12:02:00+05:30",
                "duration_seconds": 120,
            },
        )
        write(
            analysis / "legacy" / "old.md",
            "# Legacy marker that must not be included\n",
        )

        classification = self.output / "classification"
        write(
            classification / "complexity-classification_20260818_120200.md",
            """# Complexity Classification

## Final Classification
**High**

## Agentic Platform, Code Tier and Harness
- **Agentic platform:** Copilot Studio
- **Harness:** Standard

## Comprehensive Justification
Fixture classification marker supports the platform choice.

## Solution Component Inventory
### Agents
- Fixture Agent

## Architecture and Sequence Design Contract
The fixture uses a governed single-agent architecture.

## Gaps and Conflicts
- Analytics is pending.
""",
        )
        write_json(
            classification
            / ".complexity-classifier"
            / "runs"
            / "CC-20260818_120200-ABCDEF12"
            / "run.json",
            {
                "run_id": "CC-20260818_120200-ABCDEF12",
                "status": "validated",
                "started_at_local": "2026-08-18T12:02:00+05:30",
                "completed_at_local": "2026-08-18T12:02:01+05:30",
                "duration_seconds": 1,
            },
        )

        design = self.output / "design"
        artifacts = design / "artifacts"
        artifacts.mkdir(parents=True)
        write_json(
            artifacts / "design-model.json",
            {
                "title": "Fixture Agent",
                "summary": "Fixture design marker.",
                "components": [
                    {"layer": "users"},
                    {"layer": "agent-platform"},
                ],
            },
        )
        (artifacts / "architecture.png").write_bytes(b"png")
        (artifacts / "sequence.png").write_bytes(b"png")
        write_json(
            design / "current-design.json",
            {
                "run_id": "SDR-20260818_120300-ABCDEF12",
                "artifact_directory": artifacts.relative_to(self.project).as_posix(),
                "validation": "passed",
                "result": {
                    "renders": {
                        "solution_architecture_png": (artifacts / "architecture.png").relative_to(self.project).as_posix(),
                        "sequence_png": (artifacts / "sequence.png").relative_to(self.project).as_posix(),
                    },
                    "timings_ms": {"total": 3000},
                },
                "updated_at": "2026-08-18T12:03:03+05:30",
            },
        )

        build = self.output / "build"
        write(
            build / "agent-build-report.md",
            "# Agent Build Report\n\n## Build result\nFixture build marker.\n",
        )
        write(
            build / "agent-instructions.md",
            "# Identity\nFixture instruction marker.\n",
        )
        write_json(
            build / "build-manifest.json",
            {
                "status": "complete",
                "runId": "BLD-20260818-120400-ABCDEF12",
                "artifacts": [
                    {
                        "relativePath": "agent-build-report.md",
                        "required": True,
                    },
                    {
                        "relativePath": "agent-instructions.md",
                        "required": True,
                    },
                ],
            },
        )
        write_json(
            build / "agent-live-state.json",
            {"capturedAt": "2026-08-18T12:04:00+05:30"},
        )
        write_json(
            build / "agent-build-handoff.json",
            {
                "agent": {
                    "name": "Fixture Agent",
                    "agentId": "fixture-id",
                    "schemaName": "fixture_Agent",
                    "harness": "Standard",
                    "environmentId": "fixture-environment",
                }
            },
        )

        evaluation = self.output / "evaluation"
        write(
            evaluation / "evaluation-run-report.md",
            "# Agent Evaluation Run Report\n\n## Execution Summary\nFixture evaluation marker.\n",
        )
        write(
            evaluation / "deployment-gate-summary.md",
            "# Deployment Gate Summary\n\n**Overall decision:** FAIL\n",
        )
        write_json(
            evaluation / "evaluation-manifest.json",
            {
                "status": "fail",
                "runId": "EVAL-20260818-120500-ABCDEF12",
                "artifacts": [
                    {
                        "relativePath": "evaluation-run-report.md",
                        "required": True,
                    },
                    {
                        "relativePath": "deployment-gate-summary.md",
                        "required": True,
                    },
                ],
            },
        )
        write_json(
            evaluation / "evaluation-observations.json",
            {
                "runId": "EVAL-20260818-120500-ABCDEF12",
                "startedAt": "2026-08-18T12:05:00+05:30",
                "completedAt": "2026-08-18T12:15:00+05:30",
                "summary": {
                    "total": 2,
                    "passed": 1,
                    "failed": 1,
                    "blocked": 0,
                    "notRun": 0,
                },
                "results": [
                    {
                        "testCaseId": "EVAL-099",
                        "scenario": "Fixture dynamic failure",
                        "status": "FAIL",
                        "failureReasons": ["Fixture endpoint is missing."],
                    }
                ],
                "optimizerHandoff": {
                    "evaluationDecision": "FAIL",
                    "eligibleForOptimization": True,
                    "findings": [],
                },
            },
        )
        (evaluation / "evidence").mkdir()
        (evaluation / "evidence" / "EVAL-001-attempt-01.png").write_bytes(b"png")

        optimization = self.output / "optimization"
        write(
            optimization / "optimization-run-report.md",
            "# Agent Optimization Run Report\n\n## Final optimization status\nFixture optimization marker.\n",
        )
        write(
            optimization / "rounds" / "round-001" / "round-report.md",
            "# Round 1\nAccepted.\n",
        )
        write_json(
            optimization / "optimization-manifest.json",
            {
                "status": "blocked",
                "runId": "OPT-20260818-121500-ABCDEF12",
                "artifacts": [
                    {
                        "relativePath": "optimization-run-report.md",
                        "required": True,
                    },
                    {
                        "relativePath": "rounds/round-001/round-report.md",
                        "required": False,
                    },
                ],
            },
        )
        write_json(
            optimization / "optimization-change-log.json",
            {
                "runId": "OPT-20260818-121500-ABCDEF12",
                "generatedAt": "2026-08-18T12:20:00+05:30",
            },
        )
        write_json(
            optimization / "optimization-plan.json",
            {
                "rounds": [],
                "deferredFindings": [
                    {
                        "id": "OPT-FIXTURE-001",
                        "reason": "Fixture implementation is unavailable.",
                    }
                ],
            },
        )
        write_json(
            optimization
            / "rounds"
            / "round-001"
            / "before-state-manifest.json",
            {"capturedAt": "2026-08-18T12:15:00+05:30"},
        )

    def test_generates_config_resolved_outputs(self) -> None:
        result = generate(self.config)
        self.assertEqual(result["status"], "passed")
        artifact_root = self.output / "artifacts"
        markdown = (artifact_root / "solution-document.md").read_text(encoding="utf-8")
        html = (artifact_root / "lisa-execution-tree.html").read_text(encoding="utf-8")
        for marker in [
            "Fixture analysis marker",
            "Fixture classification marker",
            "Fixture Agent",
            "Fixture dynamic failure",
            "Fixture endpoint is missing",
            "Fixture implementation is unavailable",
        ]:
            self.assertIn(marker, markdown)
        self.assertNotIn("Legacy marker", markdown)
        self.assertEqual(markdown.count("### Executive Summary"), 0)
        self.assertNotIn("EVAL-099", markdown)
        self.assertNotIn("OPT-FIXTURE-001", markdown)
        self.assertNotIn("fixture-id", markdown)
        self.assertNotIn("Core Artifact Inventory", markdown)
        self.assertNotIn("Source Markdown Register", markdown)
        self.assertNotIn("Persisted Agent Instructions", markdown)
        self.assertIn("](solution-architecture.png)", markdown)
        self.assertIn("](solution-sequence.png)", markdown)
        self.assertTrue((artifact_root / "solution-architecture.png").is_file())
        self.assertTrue((artifact_root / "solution-sequence.png").is_file())
        self.assertFalse((self.output / "solution-document.md").exists())
        self.assertFalse((self.output / "lisa-execution-tree.html").exists())
        self.assertIn('data-stage="artifact-generation"', html)
        self.assertIn("--cp-accent", html)
        self.assertIn('"Segoe UI", Aptos, Calibri', html)
        self.assertIn("10m 00s", html)
        self.assertIn("../analysis/requirement-analysis_20260818_120000.md", html)
        self.assertNotIn("<script src=", html)

    def test_resolves_output_from_relative_base_path(self) -> None:
        _, _, resolved = resolve_output(self.config)
        self.assertEqual(resolved, self.output.resolve())

    def test_supports_absolute_base_path(self) -> None:
        write_json(
            self.config,
            {
                "basePath": str(self.project.resolve()),
                "custName": "Fixture Customer",
            },
        )
        _, _, resolved = resolve_output(self.config)
        self.assertEqual(self.output.resolve(), resolved)

    def test_requires_configured_base_path(self) -> None:
        write_json(self.config, {"custName": "Fixture Customer"})
        with self.assertRaises(GenerationError):
            resolve_output(self.config)

    def test_rejects_missing_stage_directory(self) -> None:
        shutil.rmtree(self.output / "evaluation")
        with self.assertRaises(GenerationError):
            generate(self.config)

    def test_normalizes_naive_stage_timestamps(self) -> None:
        path = self.output / "evaluation" / "evaluation-observations.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["startedAt"] = "2026-08-18T12:05:00"
        value["completedAt"] = "2026-08-18T12:15:00"
        write_json(path, value)
        self.assertEqual(generate(self.config)["status"], "passed")

    def test_rejects_unknown_timezone_during_generation(self) -> None:
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config["timeZone"] = "Invalid/Timezone"
        write_json(self.config, config)
        with self.assertRaises(GenerationError):
            generate(self.config)


if __name__ == "__main__":
    unittest.main()
