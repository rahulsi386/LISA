from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "solution_designer.py"
FIXTURE = (
    SKILL_ROOT
    / "tests"
    / "fixtures"
    / "complexity-classification_20260813_120000.json"
)


class SolutionDesignerTests(unittest.TestCase):
    maxDiff = None

    def run_cli(self, *arguments: str, expected: int = 0) -> dict:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            expected,
            completed.returncode,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        return json.loads(completed.stdout.strip() or completed.stderr.strip())

    def prepare(
        self, temporary: Path, local_time: str = "2026-08-13T12:30:00+05:30"
    ) -> tuple[dict, dict]:
        output = temporary / "output"
        classification_dir = output / "classification"
        classification_dir.mkdir(parents=True, exist_ok=True)
        classification = classification_dir / FIXTURE.name
        shutil.copy2(FIXTURE, classification)
        config = temporary / "lisa-config.json"
        config.write_text(json.dumps({"basePath": "."}), encoding="utf-8")
        prepared = self.run_cli(
            "prepare",
            "--config",
            str(config),
            "--local-time",
            local_time,
        )
        run = json.loads(Path(prepared["run"]).read_text(encoding="utf-8"))
        self.assertEqual((output / "design").resolve(), Path(run["design_root"]))
        self.assertTrue(Path(prepared["design_model"]).is_relative_to(output / "design"))
        self.assertEqual(
            {"classification", "design"},
            {item.name for item in output.iterdir()},
        )
        return prepared, run

    def test_prepare_builds_valid_model_without_invented_auth_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, _ = self.prepare(Path(directory))
            model = json.loads(
                Path(prepared["design_model"]).read_text(encoding="utf-8")
            )
            self.assertEqual("Procurement Guidance Agent", model["title"])
            self.assertTrue(model["sourceClassificationSha256"])
            actor = next(
                item for item in model["components"] if item["kind"] == "actor"
            )
            channels = [
                item for item in model["components"] if item["kind"] == "channel"
            ]
            self.assertEqual("users", actor["layer"])
            self.assertEqual(
                {"Microsoft Teams", "Microsoft 365 Copilot"},
                {item["name"] for item in channels},
            )
            self.assertTrue(all(item["layer"] == "channels" for item in channels))
            auth_messages = [
                message
                for message in model["sequence"]
                if "authenticat" in message["label"].casefold()
            ]
            self.assertEqual([], auth_messages)
            governance_components = [
                item
                for item in model["components"]
                if item["name"] == "Identity, Security, and Governance"
            ]
            self.assertEqual("tbd", governance_components[0]["status"])

    def test_prepare_consumes_solution_topology_without_inference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            classification_dir = temporary / "output" / "classification"
            classification_dir.mkdir(parents=True)
            classification_path = classification_dir / FIXTURE.name
            classification = json.loads(FIXTURE.read_text(encoding="utf-8"))
            classification["solution_topology"] = {
                "architecture_summary": "Explicit architecture-ready topology.",
                "components": [
                    {
                        "id": "procurement-user",
                        "name": "Procurement analyst",
                        "category": "actor",
                        "product_service": "Microsoft 365 user",
                        "hosting_runtime": "Microsoft 365",
                        "deployment_boundary": "user",
                        "lifecycle": "existing",
                        "role": "Requests governed procurement analysis.",
                        "evidence_ids": ["REQ-001"],
                    },
                    {
                        "id": "teams-channel",
                        "name": "Microsoft Teams",
                        "category": "channel",
                        "product_service": "Microsoft Teams",
                        "hosting_runtime": "Microsoft 365",
                        "deployment_boundary": "channel",
                        "lifecycle": "existing",
                        "role": "Publishes the conversational experience.",
                        "evidence_ids": [],
                    },
                    {
                        "id": "procurement-agent",
                        "name": "Procurement Guidance and Spend Analysis Agent",
                        "category": "agent",
                        "product_service": "Microsoft Copilot Studio",
                        "hosting_runtime": "Power Platform environment",
                        "deployment_boundary": "power-platform-environment",
                        "lifecycle": "configure",
                        "role": "Orchestrates grounded procurement guidance and analysis.",
                        "evidence_ids": ["REQ-001"],
                    },
                    {
                        "id": "analytics-api",
                        "name": "Procurement Analytics API",
                        "category": "tool",
                        "product_service": "Azure Functions and Azure API Management",
                        "hosting_runtime": "Azure Functions",
                        "deployment_boundary": "azure-subscription",
                        "lifecycle": "build",
                        "role": "Performs procurement analytics.",
                        "evidence_ids": ["REQ-004"],
                    },
                ],
                "relationships": [
                    {
                        "source_id": "procurement-user",
                        "target_id": "teams-channel",
                        "relationship_type": "communicates",
                        "interaction": "Submit procurement request",
                        "evidence_ids": ["REQ-001"],
                    },
                    {
                        "source_id": "teams-channel",
                        "target_id": "procurement-agent",
                        "relationship_type": "publishes-to",
                        "interaction": "Deliver authenticated request",
                        "evidence_ids": ["REQ-001"],
                    },
                    {
                        "source_id": "procurement-agent",
                        "target_id": "analytics-api",
                        "relationship_type": "invokes",
                        "interaction": "Invoke procurement analytics",
                        "evidence_ids": ["REQ-004"],
                    },
                    {
                        "source_id": "procurement-agent",
                        "target_id": "procurement-user",
                        "relationship_type": "responds",
                        "interaction": "Return governed analysis",
                        "evidence_ids": ["REQ-001"],
                    },
                ],
                "sequence_flows": [
                    {
                        "order": 1,
                        "phase": "Request",
                        "source_id": "procurement-user",
                        "target_id": "teams-channel",
                        "action": "Submit procurement request",
                        "message_type": "call",
                        "condition": None,
                        "evidence_ids": ["REQ-001"],
                    },
                    {
                        "order": 2,
                        "phase": "Request",
                        "source_id": "teams-channel",
                        "target_id": "procurement-agent",
                        "action": "Deliver authenticated request",
                        "message_type": "call",
                        "condition": None,
                        "evidence_ids": ["REQ-001"],
                    },
                    {
                        "order": 3,
                        "phase": "Action",
                        "source_id": "procurement-agent",
                        "target_id": "analytics-api",
                        "action": "Invoke procurement analytics",
                        "message_type": "call",
                        "condition": "when analytics is required",
                        "evidence_ids": ["REQ-004"],
                    },
                    {
                        "order": 4,
                        "phase": "Response",
                        "source_id": "procurement-agent",
                        "target_id": "procurement-user",
                        "action": "Return governed analysis",
                        "message_type": "response",
                        "condition": None,
                        "evidence_ids": ["REQ-001"],
                    },
                ],
            }
            classification["coverage"] = {
                "native_build_percent": 65,
                "poc_demonstration_percent": 90,
                "unsupported_percent": 35,
                "unknown_percent": 0,
            }
            classification["delivery_assessment"] = {
                "poc_scope": {
                    "included_capability_ids": ["CAP-ANALYTICS"]
                },
                "capabilities": [
                    {
                        "id": "CAP-ANALYTICS",
                        "component_ids": ["analytics-api"],
                        "poc_treatment": "simulate",
                        "build_owner": "agent-builder",
                        "implementation_status": "demonstrable-only",
                    }
                ],
            }
            classification_path.write_text(
                json.dumps(classification, indent=2), encoding="utf-8"
            )
            config = temporary / "lisa-config.json"
            config.write_text(json.dumps({"basePath": "."}), encoding="utf-8")
            prepared = self.run_cli(
                "prepare",
                "--config",
                str(config),
                "--local-time",
                "2026-08-13T12:30:00+05:30",
            )
            model = json.loads(
                Path(prepared["design_model"]).read_text(encoding="utf-8")
            )
            self.assertEqual(
                "Procurement Guidance and Spend Analysis Agent",
                model["title"],
            )
            self.assertEqual(
                {
                    "Procurement analyst",
                    "Microsoft Teams",
                    "Procurement Guidance and Spend Analysis Agent",
                    "Procurement Analytics API",
                },
                {item["name"] for item in model["components"]},
            )
            self.assertNotIn(
                "Agent Tools and Services",
                {item["name"] for item in model["components"]},
            )
            self.assertIn(
                "Azure Functions and Azure API Management",
                next(
                    item
                    for item in model["components"]
                    if item["id"] == "analytics-api"
                )["members"],
            )
            self.assertEqual(
                "Simulated: Invoke procurement analytics",
                next(
                    item
                    for item in model["relationships"]
                    if item["from"] == "procurement-agent"
                    and item["to"] == "analytics-api"
                )["label"],
            )
            analytics = next(
                item for item in model["components"] if item["id"] == "analytics-api"
            )
            self.assertEqual("simulate", analytics["implementationStatus"])
            self.assertEqual("represented", analytics["pocScope"])
            self.assertEqual(65, model["coverage"]["nativeBuildPercent"])
            simulated_messages = [
                item
                for item in model["sequence"]
                if item["implementationMode"] == "simulated"
            ]
            self.assertTrue(simulated_messages)
            self.assertTrue(
                all("Simulated:" in item["label"] for item in simulated_messages)
            )
            generated = self.run_cli(
                "generate",
                "--run",
                prepared["run"],
            )
            self.assertEqual("awaiting_inspection", generated["status"])
            slug = model["scenarioSlug"]
            architecture_svg = Path(
                prepared["design_model"]
            ).parent / f"SA_{slug}.svg"
            sequence_svg = Path(prepared["design_model"]).parent / f"SD_{slug}.svg"
            architecture_text = architecture_svg.read_text(encoding="utf-8")
            sequence_text = sequence_svg.read_text(encoding="utf-8")
            self.assertIn('data-implementation-status="simulate"', architecture_text)
            self.assertIn('data-implementation-mode="simulated"', architecture_text)
            self.assertIn('data-implementation-mode="simulated"', sequence_text)
            self.assertIn("Native 65% | PoC 90%", architecture_text)

    def test_generation_is_pending_until_inspection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            generated = self.run_cli("generate", "--run", prepared["run"])
            self.assertEqual("awaiting_inspection", generated["status"])
            generation_report = json.loads(
                Path(run["stage_design"], "run-report.json").read_text(encoding="utf-8")
            )
            self.assertEqual("pending-inspection", generation_report["validation"])
            self.assertEqual("passed", generation_report["structuralValidation"])
            model = json.loads(Path(run["model_path"]).read_text(encoding="utf-8"))
            slug = model["scenarioSlug"]
            architecture_svg = Path(
                run["stage_design"], f"SA_{slug}.svg"
            ).read_text(encoding="utf-8")
            self.assertIn('data-id="users"', architecture_svg)
            self.assertIn('data-id="channels"', architecture_svg)
            for component in model["components"]:
                for member in component.get("members", []):
                    self.assertIn(f'data-name="{member}"', architecture_svg)
            self.assertFalse(
                Path(run["design_root"], f"SA_{slug}.svg").exists()
            )

    def test_finalize_publishes_atomically_and_cache_reuses(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            prepared, run = self.prepare(temporary)
            generated = self.run_cli("generate", "--run", prepared["run"])
            inspection = json.loads(
                Path(generated["inspection_template"]).read_text(encoding="utf-8")
            )
            inspection["status"] = "passed"
            inspection["inspected_at"] = "2026-08-13T12:30:10+05:30"
            inspection["checks"] = {key: True for key in inspection["checks"]}
            inspection["issues"] = []
            inspection["summary"] = "Both rendered diagrams passed visual inspection."
            inspection_path = Path(run["run_directory"]) / "inspection.completed.json"
            inspection_path.write_text(json.dumps(inspection, indent=2), encoding="utf-8")
            result = self.run_cli(
                "finalize",
                "--run",
                prepared["run"],
                "--inspection",
                str(inspection_path),
            )
            self.assertEqual("passed", result["validation"])
            for path in (
                result["solution_architecture_diagram"],
                result["sequence_diagram"],
                result["renders"]["solution_architecture_png"],
                result["renders"]["sequence_png"],
            ):
                self.assertTrue(Path(path).exists())
                self.assertTrue(Path(path).is_relative_to(temporary / "output" / "design"))
            final_report = json.loads(
                (
                    Path(result["solution_architecture_diagram"]).parent
                    / "run-report.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual("passed", final_report["renderedInspection"])
            pointer = json.loads(
                (temporary / "output" / "design" / "current-design.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                Path(result["solution_architecture_diagram"]).parent,
                (temporary / pointer["artifact_directory"]).resolve(),
            )
            artifact_root = temporary / "output" / "design" / "artifacts"
            self.assertEqual(artifact_root.resolve(), Path(result["solution_architecture_diagram"]).parent)
            self.assertFalse(any(path.is_dir() for path in artifact_root.iterdir()))

            second, second_run = self.prepare(
                temporary, "2026-08-13T12:31:00+05:30"
            )
            self.assertTrue(second["cache_hit"])
            reused = self.run_cli("reuse", "--run", second["run"])
            self.assertEqual("validated-cache-hit", reused["cache_status"])
            self.assertLess(reused["timings_ms"]["total"], 30000)
            self.assertEqual("validated", json.loads(Path(second["run"]).read_text())["status"])

    def test_failed_inspection_cannot_finalize(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            generated = self.run_cli("generate", "--run", prepared["run"])
            result = self.run_cli(
                "finalize",
                "--run",
                prepared["run"],
                "--inspection",
                generated["inspection_template"],
                expected=2,
            )
            self.assertIn("Rendered inspection failed", result["error"])

    def test_staged_artifact_tampering_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            generated = self.run_cli("generate", "--run", prepared["run"])
            inspection = json.loads(
                Path(generated["inspection_template"]).read_text(encoding="utf-8")
            )
            inspection["status"] = "passed"
            inspection["inspected_at"] = "2026-08-13T12:30:10+05:30"
            inspection["checks"] = {key: True for key in inspection["checks"]}
            inspection["issues"] = []
            inspection["summary"] = "Inspection passed."
            inspection_path = Path(run["run_directory"]) / "inspection.tamper.json"
            inspection_path.write_text(json.dumps(inspection, indent=2), encoding="utf-8")
            slug = json.loads(Path(run["model_path"]).read_text())["scenarioSlug"]
            svg = Path(run["stage_design"]) / f"SA_{slug}.svg"
            svg.write_text(svg.read_text(encoding="utf-8") + " ", encoding="utf-8")
            result = self.run_cli(
                "finalize",
                "--run",
                prepared["run"],
                "--inspection",
                str(inspection_path),
                expected=2,
            )
            self.assertIn("Staged artifact changed", result["error"])

    def test_semantically_invalid_model_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            model = json.loads(Path(prepared["design_model"]).read_text(encoding="utf-8"))
            model["relationships"][0]["to"] = "missing-component"
            invalid = Path(run["run_directory"]) / "invalid-model.json"
            invalid.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "validate-model",
                "--model",
                str(invalid),
                expected=2,
            )
            self.assertIn("unknown component", result["error"])

    def test_same_second_prepares_have_unique_run_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            first, _ = self.prepare(temporary)
            second, _ = self.prepare(temporary)
            self.assertNotEqual(first["run"], second["run"])

    def test_skill_has_no_budget_or_approval_instructions(self) -> None:
        instructions = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for banned in (
            "Advisory execution budget",
            "eight minutes",
            "Eight-Minute",
            "sub-eight-minute",
            "--max-minutes",
            "budget-exceeded",
            "m_ask_user",
            "explicit confirmation",
            "stop and wait",
        ):
            self.assertNotIn(banned, instructions, banned)
        self.assertIn(
            "Balanced first for at most 18 components",
            instructions,
        )
        self.assertIn(
            "@resvg/resvg-js",
            instructions,
        )


if __name__ == "__main__":
    unittest.main()
