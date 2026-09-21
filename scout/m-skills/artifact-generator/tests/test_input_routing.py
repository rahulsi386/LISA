from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS_ROOT))

from lisa_path_resolver import LisaConfigError, resolve_lisa_config  # noqa: E402
from resolve_skill_inputs import resolve_inputs  # noqa: E402


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class SkillInputRoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.config = self.base / "lisa-config.json"
        write_json(
            self.config,
            {
                "basePath": ".",
                "copilotStudio": {
                    "environmentId": "environment-001",
                    "environmentUrl": "https://example.crm.dynamics.com",
                },
            },
        )
        (self.base / "requirements").mkdir()
        (self.base / "evalData").mkdir()
        output = self.base / "output"
        for stage in (
            "analysis",
            "classification",
            "design",
            "build",
            "evaluation",
            "optimization",
            "artifacts",
            "publication",
        ):
            (output / stage).mkdir(parents=True)
        write_json(
            output / "analysis" / "requirement-analysis_20260818_120000.json",
            {"schemaVersion": "fixture"},
        )
        write_json(
            output / "classification" / "complexity-classification_20260818_120100.json",
            {"schemaVersion": "fixture"},
        )
        write_json(output / "build" / "agent-build-handoff.json", {"fixture": True})
        write_json(output / "build" / "build-manifest.json", {"fixture": True})
        design_artifacts = output / "design" / "artifacts"
        design_artifacts.mkdir(parents=True)
        architecture = design_artifacts / "SA_Fixture.png"
        sequence = design_artifacts / "SD_Fixture.png"
        architecture.write_bytes(b"architecture")
        sequence.write_bytes(b"sequence")
        write_json(
            output / "design" / "current-design.json",
            {
                "result": {
                    "renders": {
                        "solution_architecture_png": architecture.relative_to(
                            self.base
                        ).as_posix(),
                        "sequence_png": sequence.relative_to(self.base).as_posix(),
                    }
                }
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_all_skills_resolve_only_canonical_inputs(self) -> None:
        for skill in (
            "requirement-analyzer",
            "complexity-classifier",
            "solution-designer",
            "agent-builder",
            "agent-evaluator",
            "agent-optimizer",
            "artifact-generator",
            "artifact-publisher",
            "postpublish-cleanup",
        ):
            resolved = resolve_inputs(skill, self.config)
            self.assertEqual(self.base.resolve(), Path(resolved["basePath"]))

    def test_latest_selection_does_not_search_nested_folders(self) -> None:
        nested = self.base / "output" / "analysis" / "nested"
        nested.mkdir()
        write_json(
            nested / "requirement-analysis_20990101_000000.json",
            {"schemaVersion": "wrong"},
        )
        resolved = resolve_inputs("complexity-classifier", self.config)
        self.assertTrue(
            resolved["analysis"].endswith(
                "output\\analysis\\requirement-analysis_20260818_120000.json"
            )
            or resolved["analysis"].endswith(
                "output/analysis/requirement-analysis_20260818_120000.json"
            )
        )

    def test_absolute_base_path_is_supported(self) -> None:
        write_json(self.config, {"basePath": str(self.base.resolve())})
        self.assertEqual(self.base.resolve(), resolve_lisa_config(self.config).base)

    def test_publisher_ignores_legacy_run_state_routing(self) -> None:
        write_json(
            self.base / "output" / "lisa-run-state.json",
            {"runFolder": str((self.base / "elsewhere").resolve())},
        )
        resolved = resolve_inputs("artifact-publisher", self.config)
        self.assertEqual((self.base / "output").resolve(), Path(resolved["runFolder"]))

    def test_absolute_design_pointer_paths_are_rejected(self) -> None:
        pointer = self.base / "output" / "design" / "current-design.json"
        write_json(
            pointer,
            {
                "result": {
                    "renders": {
                        "solution_architecture_png": str(pointer.resolve()),
                        "sequence_png": str(pointer.resolve()),
                    }
                }
            },
        )
        with self.assertRaises(LisaConfigError):
            resolve_inputs("agent-builder", self.config)


if __name__ == "__main__":
    unittest.main()
