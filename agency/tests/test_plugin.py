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
            "plugin.json",
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
        for relative_path in ("plugin.json", ".claude-plugin/plugin.json"):
            with self.subTest(relative_path=relative_path):
                manifest = json.loads((PLUGIN_ROOT / relative_path).read_text(encoding="utf-8"))
                self.assertEqual("lisa", manifest["name"])
                expected_skills = ["./skills/"] if relative_path.startswith(".claude-plugin/") else "./skills/"
                self.assertEqual(expected_skills, manifest["skills"])

        registered = {
            path.parent.name for path in (PLUGIN_ROOT / "skills").glob("*/SKILL.md")
        }
        self.assertEqual(set(EXPECTED_SKILLS), registered)
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
            "analysis_handoff.py",
            "review_batches.py",
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

    def test_both_engines_register_matching_mcp_servers(self) -> None:
        copilot = json.loads((PLUGIN_ROOT / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual("./.mcp.json", copilot["mcpServers"])
        shared = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        claude = json.loads(
            (PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )["mcpServers"]
        self.assertEqual({"playwright", "azure-mcp", "microsoft-learn"}, set(shared))
        self.assertEqual(set(shared), set(claude))
        for name in shared:
            with self.subTest(server=name):
                normalized = [{key: value for key, value in item.items() if key != "type"}
                              for item in (shared[name], claude[name])]
                self.assertEqual(normalized[0], normalized[1])
                self.assertEqual(shared[name].get("type", "stdio"), claude[name].get("type", "stdio"))

    def test_azure_mcp_uses_npx_latest_and_keeps_confirmation(self) -> None:
        servers = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        azure = servers["azure-mcp"]
        self.assertEqual("stdio", azure["type"])
        self.assertEqual("npx", azure["command"])
        self.assertEqual(
            ["-y", "@azure/mcp@latest", "server", "start", "--mode", "namespace"],
            azure["args"],
        )
        for option in ("--prerelease", "--ignore-failed-sources", "--read-only", "--namespace",
                       "--tool", "--disable-user-confirmation", "--enable-insecure-transports"):
            self.assertNotIn(option, azure["args"])
        self.assertFalse(any(value.startswith("--dangerously-") for value in azure["args"]))
        self.assertEqual({
            "AZURE_MCP_COLLECT_TELEMETRY": "false",
        }, azure["env"])

    def test_learn_mcp_uses_the_official_anonymous_remote_endpoint(self) -> None:
        servers = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
        learn = servers["microsoft-learn"]
        self.assertEqual("http", learn["type"])
        self.assertEqual("https://learn.microsoft.com/api/mcp", learn["url"])
        self.assertEqual({"type", "url", "description"}, set(learn))

    def test_prerequisites_cover_bundled_mcp_runtime(self) -> None:
        script = (PLUGIN_ROOT / "scripts" / "Test-LisaAgencyPrerequisites.ps1").read_text(encoding="utf-8")
        self.assertIn("-Command 'node'", script)
        self.assertIn("-Minimum ([version]'20.0.0')", script)
        self.assertNotIn("-Command 'dotnet'", script)
        self.assertIn("foreach ($command in 'npm', 'npx')", script)
        self.assertIn("[switch]$RequireAzureMcp", script)
        self.assertIn("Get-Command 'az'", script)
        self.assertNotIn("& az login", script)


if __name__ == "__main__":
    unittest.main()