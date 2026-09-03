from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SKILLS = (
    "cad-orchestrator",
    "requirement-analyzer",
    "complexity-classifier",
    "solution-designer",
    "agent-builder",
    "agent-evaluator",
    "agent-optimizer",
    "artifact-generator",
    "artifact-publisher",
    "postpublish-cleanup",
)


class AgencyPluginTests(unittest.TestCase):
    def test_manifests_parse(self) -> None:
        for relative_path in (
            "agency.json",
            ".mcp.json",
            ".claude-plugin/plugin.json",
            "lisa-config.example.json",
        ):
            with self.subTest(relative_path=relative_path):
                value = json.loads((PLUGIN_ROOT / relative_path).read_text(encoding="utf-8"))
                self.assertIsInstance(value, dict)

    def test_agency_manifest_declares_supported_engines(self) -> None:
        manifest = json.loads((PLUGIN_ROOT / "agency.json").read_text(encoding="utf-8"))
        self.assertEqual(["copilot", "claude"], manifest["engines"])

    def test_all_skills_are_registered_and_present(self) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        registered = tuple(
            Path(value).parent.name for value in manifest.get("skills", [])
        )
        self.assertEqual(EXPECTED_SKILLS, registered)
        for name in EXPECTED_SKILLS:
            skill_path = PLUGIN_ROOT / "skills" / name / "SKILL.md"
            self.assertTrue(skill_path.is_file(), skill_path)
            text = skill_path.read_text(encoding="utf-8")
            match = re.search(r'^name:\s*["\']?([^"\'\r\n]+)', text, re.MULTILINE)
            self.assertIsNotNone(match, skill_path)
            self.assertEqual(name, match.group(1).strip())

    def test_shared_runtime_is_packaged(self) -> None:
        for name in (
            "lisa_path_resolver.py",
            "resolve_skill_inputs.py",
            "workflow_checkpoint.py",
            "workflow-checkpoint.schema.json",
            "workflow-checkpointing.md",
            "lifecycle_artifacts.py",
            "artifact-contract.schema.json",
            "validate_artifact_contracts.py",
            "Platform-Decision.md",
        ):
            self.assertTrue((PLUGIN_ROOT / "skills" / name).is_file(), name)

    def test_scout_runtime_tokens_are_removed(self) -> None:
        forbidden = (
            "m_get_skill",
            "m_ask_user",
            "<local-skills-root>",
            "<scout-data-dir>",
        )
        for skill_path in (PLUGIN_ROOT / "skills").glob("*/SKILL.md"):
            text = skill_path.read_text(encoding="utf-8")
            for token in forbidden:
                with self.subTest(skill=skill_path.parent.name, token=token):
                    self.assertNotIn(token, text)

    def test_playwright_mcp_supports_publisher(self) -> None:
        manifest = json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        args = manifest["mcpServers"]["playwright"]["args"]
        self.assertIn("@playwright/mcp@0.0.80", args)
        self.assertFalse(any(value.endswith("@latest") for value in args))
        self.assertIn("--allow-unrestricted-file-access", args)
        publisher = (
            PLUGIN_ROOT / "skills" / "artifact-publisher" / "SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("browser_run_code_unsafe", publisher)

    def test_example_config_is_project_relative(self) -> None:
        config = json.loads(
            (PLUGIN_ROOT / "lisa-config.example.json").read_text(encoding="utf-8")
        )
        self.assertEqual(".", config["basePath"])


if __name__ == "__main__":
    unittest.main()