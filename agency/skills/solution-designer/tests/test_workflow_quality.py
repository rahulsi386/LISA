from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import unittest
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch


SKILL_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "solution_designer_workflow", SKILL_ROOT / "scripts" / "solution_designer.py"
)
designer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(designer)
FIXTURE = SKILL_ROOT / "tests" / "fixtures" / "complexity-classification_20260813_120000.json"


class ProductIconTests(unittest.TestCase):
    def test_product_display_names_are_explicit_and_resolve_to_their_own_icons(self) -> None:
        icons = designer._json_load(designer.ICON_MANIFEST)["icons"]
        for icon in icons:
            with self.subTest(key=icon["key"]):
                if icon["key"] in {"generic-component", "users"}:
                    self.assertNotIn("displayName", icon)
                    continue
                self.assertTrue(icon["official"])
                self.assertTrue(icon["displayName"])
                self.assertEqual(
                    icon["key"], designer._icon_for(icon["displayName"], "service", "")
                )

    def test_explicit_products_and_namespace_aliases(self) -> None:
        cases = {
            "Microsoft 365 Copilot": "microsoft-365-copilot",
            "M365::Copilot": "microsoft-365-copilot",
            "Microsoft.Agent365": "agent-365",
            "Microsoft365::Teams": "microsoft-teams",
            "Microsoft.Teams": "microsoft-teams",
            "Microsoft365/SharePoint": "microsoft-sharepoint",
            "SharePoint Online": "microsoft-sharepoint",
            "Microsoft::Fabric": "microsoft-fabric",
            "Microsoft.Fabric.PowerBI": "power-bi",
            "PowerBI": "power-bi",
            "Azure::ServiceBus": "service-bus",
            "Microsoft.ServiceBus": "service-bus",
            "Microsoft.Azure.ServiceBus": "service-bus",
            "Microsoft.Dynamics365.Finance": "dynamics-finance",
            "Dynamics 365 Finance and Operations": "dynamics-finance-operations",
            "Microsoft Entra Verified ID": "entra-verified-id",
            "Azure AI Foundry": "microsoft-foundry",
            "Azure AI Foundry Agent Service": "foundry-agent-service",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(expected, designer._icon_for(name, "service", "Hybrid"))

    def test_ambiguous_and_custom_names_do_not_borrow_product_icons(self) -> None:
        for name in (
            "Microsoft 365", "Microsoft Purview", "Custom SQL Parser",
            "Storage Reconciliation", "Business Function", "User Insights API",
            "Finance Approval Service", "Foundry Research", "Copilot",
            "Microsoft 365 Copilot Custom Proxy", "Teams-compatible Custom Chat",
            "Azure Functions and Azure API Management",
        ):
            with self.subTest(name=name):
                self.assertEqual(
                    "generic-component", designer._icon_for(name, "tool", "Copilot Studio")
                )
        self.assertEqual(
            "generic-component", designer._icon_for("Custom agent", "agent", "Hybrid")
        )
        self.assertEqual("users", designer._icon_for("Legal approver", "human", "Hybrid"))

    def test_product_service_is_explicit_and_does_not_rewrite_name(self) -> None:
        self.assertEqual(
            "dynamics-finance",
            designer._icon_for(
                "Procurement ledger", "data", "Hybrid",
                product_service="Microsoft Dynamics 365 Finance",
            ),
        )
        classification = designer._json_load(FIXTURE)
        model = designer._build_design_model(FIXTURE, classification)
        self.assertEqual(
            classification["components"]["agents"][0]["name"],
            next(item["name"] for item in model["components"] if item["kind"] == "agent"),
        )
        self.assertEqual(
            {"Microsoft Teams": "microsoft-teams", "Microsoft 365 Copilot": "microsoft-365-copilot"},
            {item["name"]: item["iconKey"] for item in model["components"] if item["kind"] == "channel"},
        )

    def test_added_artwork_is_packaged_with_original_hashes_and_sources(self) -> None:
        manifest = designer._json_load(designer.ICON_MANIFEST)
        icons = {item["key"]: item for item in manifest["icons"]}
        for key in (
            "microsoft-teams", "microsoft-sharepoint", "microsoft-365-copilot",
            "microsoft-fabric", "power-bi", "service-bus", "dynamics-finance",
        ):
            with self.subTest(key=key):
                icon = icons[key]
                asset = designer.RESOURCES / icon["file"]
                content = asset.read_bytes()
                self.assertEqual(hashlib.sha256(content).hexdigest(), icon["sha256"])
                self.assertTrue(icon["official"])
                self.assertTrue(icon["sourceUrl"].startswith("https://"))
                self.assertTrue(icon["productName"])
                if icon["mediaType"] == "image/png":
                    self.assertEqual(b"\x89PNG\r\n\x1a\n", content[:8])
                else:
                    self.assertEqual("{http://www.w3.org/2000/svg}svg", ET.fromstring(content).tag)
        for pack in ("Power Platform", "Microsoft Fabric"):
            entry = manifest["packs"][pack]
            prefix = "repositoryLicense" if pack == "Microsoft Fabric" else "license"
            self.assertEqual(
                entry[prefix + "Sha256"],
                designer._sha256_file(designer.RESOURCES / entry[prefix + "File"]),
            )
        self.assertFalse(manifest["timedRunNetworkAccess"])


class RepairWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = SKILL_ROOT / "tests" / (".workflow-quality-" + uuid.uuid4().hex)
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        classification = self.root / "output" / "classification" / FIXTURE.name
        classification.parent.mkdir(parents=True)
        shutil.copy2(FIXTURE, classification)
        self.config = self.root / "lisa-config.json"
        self.config.write_text(json.dumps({"basePath": "."}), encoding="utf-8")
        self.clock = 1788789600.0
        self.addCleanup(patch.stopall)
        patch.object(designer.time, "time", side_effect=lambda: self.clock).start()
        patch.object(designer, "_resource_hashes", return_value={"test-resource": "a" * 64}).start()
        self.generator = patch.object(
            designer.subprocess, "run", side_effect=self.generate_fixture
        ).start()

    def invoke(self, *args: str, expected: int = 0) -> dict:
        output = io.StringIO()
        error = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            result = designer.main(list(args))
        self.assertEqual(expected, result, output.getvalue() + error.getvalue())
        return json.loads(output.getvalue() or error.getvalue())

    def prepare(self, maximum: int = 2) -> tuple[Path, dict]:
        prepared = self.invoke(
            "prepare", "--config", str(self.config),
            "--local-time", "2026-09-07T20:00:00+05:30",
            "--max-repair-attempts", str(maximum),
        )
        path = Path(prepared["run"])
        return path, designer._json_load(path)

    def generate_fixture(self, command: list[str], **kwargs) -> subprocess.CompletedProcess:
        stage = Path(command[command.index("-TempOutputPath") + 1]) / "design"
        profile = command[command.index("-LayoutProfile") + 1] if "-LayoutProfile" in command else "Balanced"
        model = designer._json_load(stage / "design-model.json")
        slug = model["scenarioSlug"]
        for name in designer._artifact_names(stage, slug):
            if name == "design-model.json":
                continue
            if name.endswith(".json"):
                designer._atomic_write_json(stage / name, {"test_fixture": True})
            else:
                (stage / name).write_bytes(f"test fixture only: {profile} {name}".encode())
        designer._atomic_write_json(
            stage / "run-report.json",
            {
                "validation": "pending-inspection", "structuralValidation": "passed",
                "renderedInspection": "pending", "validationIssues": [],
                "selectedLayoutProfile": profile, "attemptedLayoutProfiles": [profile],
                "htmlPreview": str(stage / "preview.html"),
                "timingsMs": {"total": 5},
            },
        )
        self.clock += 5
        return subprocess.CompletedProcess(command, 0, "", "")

    def candidate(self, maximum: int = 2) -> tuple[Path, dict]:
        path, _ = self.prepare(maximum)
        result = self.invoke("generate", "--run", str(path))
        self.assertEqual("awaiting_inspection", result["status"])
        return path, designer._json_load(path)

    def inspection(self, run: dict, passed: bool = False) -> Path:
        value = designer._json_load(Path(run["inspection_template_path"]))
        value.update(
            status="passed" if passed else "failed",
            inspected_at=designer._run_local_time(run),
            issues=[] if passed else ["Connector overlaps a label in the test fixture."],
            summary="Test-only inspection evidence.",
        )
        value["checks"] = {name: passed for name in value["checks"]}
        path = Path(run["run_directory"]) / f"inspection-{uuid.uuid4().hex}.json"
        designer._atomic_write_json(path, value)
        return path

    def assert_unpublished(self, run: dict) -> None:
        self.assertFalse((Path(run["design_root"]) / "current-design.json").exists())
        self.assertFalse((Path(run["design_root"]) / "artifacts").exists())

    def test_structural_pass_is_only_an_inspection_candidate(self) -> None:
        _, run = self.candidate()
        self.assert_unpublished(run)
        template = designer._json_load(Path(run["inspection_template_path"]))
        self.assertEqual("failed", template["status"])
        self.assertFalse(any(template["checks"].values()))

    def test_repair_preserves_model_and_evidence_and_requires_new_inspection(self) -> None:
        path, original = self.candidate()
        failed = self.inspection(original)
        failed_bytes = failed.read_bytes()
        result = self.invoke("repair", "--run-state", str(path), "--inspection", str(failed))
        repaired = designer._json_load(path)
        self.assertEqual(("Spacious", 1), (result["layout_profile"], result["revision"]))
        self.assertNotEqual(original["stage_design"], repaired["stage_design"])
        self.assertEqual(Path(result["html_preview"]).parent, Path(repaired["stage_design"]))
        self.assertTrue(Path(original["html_preview"]).is_file())
        self.assertTrue(Path(repaired["html_preview"]).is_file())
        self.assertIn("preview.html", repaired["staged_artifacts"])
        self.assertEqual(original["model_sha256"], repaired["model_sha256"])
        self.assertEqual(
            Path(original["model_path"]).read_bytes(), Path(repaired["model_path"]).read_bytes()
        )
        self.assertEqual(original["classification_sha256"], repaired["classification_sha256"])
        self.assertEqual(original["cache_key"], repaired["cache_key"])
        self.assertEqual(failed_bytes, failed.read_bytes())
        designer._validate_staged(original)
        designer._validate_staged(repaired)
        evidence = repaired["repair_attempts"][0]
        self.assertEqual(
            designer._json_load(failed), designer._json_load(Path(evidence["inspection_path"]))
        )
        template = designer._json_load(Path(repaired["inspection_template_path"]))
        self.assertEqual((1, "", "failed"), (template["revision"], template["inspected_at"], template["status"]))
        self.assertFalse(any(template["checks"].values()))
        self.assertNotEqual(
            designer._json_load(failed)["solution_architecture_png_sha256"],
            template["solution_architecture_png_sha256"],
        )
        self.assert_unpublished(repaired)
        passed = self.inspection(repaired, True)
        published = self.invoke("finalize", "--run", str(path), "--inspection", str(passed))
        self.assertEqual("passed", published["validation"])
        self.assertEqual(Path(published["html_preview"]).read_bytes(), Path(repaired["html_preview"]).read_bytes())
        artifacts = Path(repaired["design_root"]) / "artifacts"
        self.assertEqual(
            {f"{kind}_{repaired['scenario_slug']}.{ext}" for kind in ("SA", "SD") for ext in ("svg", "png")},
            {item.name for item in artifacts.iterdir() if item.suffix in {".svg", ".png"}},
        )

    def test_explicit_profile_is_forwarded_without_hidden_fallback(self) -> None:
        path, run = self.candidate()
        result = self.invoke(
            "repair", "--run", str(path), "--inspection", str(self.inspection(run)),
            "--layout-profile", "Wide",
        )
        self.assertEqual("Wide", result["layout_profile"])
        self.assertIn("-LayoutProfile", self.generator.call_args.args[0])
        self.assertEqual(
            ["Balanced", "Wide"], designer._json_load(path)["attempted_layout_profiles"]
        )

    def test_missing_or_changed_preview_cannot_publish(self) -> None:
        path, run = self.candidate()
        preview = Path(run["html_preview"])
        original = preview.read_bytes()
        passed = self.inspection(run, True)
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing:
                    preview.unlink()
                else:
                    preview.write_bytes(original + b"changed")
                result = self.invoke("finalize", "--run", str(path), "--inspection", str(passed), expected=2)
                self.assertIn("Staged artifact changed after generation: preview.html", result["error"])
                preview.write_bytes(original)
                self.assert_unpublished(run)

    def test_generator_must_produce_the_preview(self) -> None:
        path, run = self.prepare()
        def without_preview(command, **kwargs):
            result = self.generate_fixture(command, **kwargs)
            (Path(command[command.index("-TempOutputPath") + 1]) / "design" / "preview.html").unlink()
            return result
        self.generator.side_effect = without_preview
        result = self.invoke("generate", "--run", str(path), expected=2)
        self.assertIn("expected HTML preview", result["error"])
        self.assert_unpublished(run)

    def test_preview_inspection_is_required(self) -> None:
        path, run = self.candidate()
        passed = self.inspection(run, True)
        inspection = designer._json_load(passed)
        inspection["checks"]["html_preview"] = False
        designer._atomic_write_json(passed, inspection)
        result = self.invoke("finalize", "--run", str(path), "--inspection", str(passed), expected=2)
        self.assertIn("html_preview", result["error"])
        self.assert_unpublished(run)

    def test_cached_preview_is_hash_protected(self) -> None:
        path, run = self.candidate()
        self.invoke("finalize", "--run", str(path), "--inspection", str(self.inspection(run, True)))
        cache = Path(run["cache_directory"])
        expected = set(run["expected_cache_artifacts"])
        self.assertIn("preview.html", expected)
        self.assertTrue(designer._cache_valid(cache, run["cache_key"], expected))
        preview = cache / "preview.html"
        preview.write_bytes(preview.read_bytes() + b"changed")
        self.assertFalse(designer._cache_valid(cache, run["cache_key"], expected))
        preview.unlink()
        self.assertFalse(designer._cache_valid(cache, run["cache_key"], expected))

    def test_repair_is_bounded_and_each_profile_is_attempted_once(self) -> None:
        path, run = self.candidate()
        for revision, profile in ((1, "Spacious"), (2, "Wide")):
            result = self.invoke("repair", "--run", str(path), "--inspection", str(self.inspection(run)))
            self.assertEqual((revision, profile), (result["revision"], result["layout_profile"]))
            run = designer._json_load(path)
        result = self.invoke(
            "repair", "--run", str(path), "--inspection", str(self.inspection(run)), expected=2
        )
        self.assertIn("exhausted", result["error"])
        self.assertEqual(3, self.generator.call_count)
        self.assert_unpublished(run)

    def test_failed_repair_consumes_attempt_and_preserves_previous_seal(self) -> None:
        path, original = self.candidate(maximum=1)
        failed = self.inspection(original)
        self.generator.side_effect = lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "fixture failure")
        result = self.invoke("repair", "--run", str(path), "--inspection", str(failed), expected=2)
        self.assertIn("fixture failure", result["error"])
        run = designer._json_load(path)
        self.assertEqual("failed", run["repair_attempts"][0]["status"])
        self.assertEqual(original["staged_artifacts"], run["staged_artifacts"])
        self.assertEqual(original["stage_design"], run["stage_design"])
        designer._validate_staged(run)
        result = self.invoke("repair", "--run", str(path), "--inspection", str(failed), expected=2)
        self.assertIn("exhausted", result["error"])
        self.assert_unpublished(run)

    def test_failed_profile_is_not_retried_and_next_revision_can_succeed(self) -> None:
        path, original = self.candidate()
        failed = self.inspection(original)
        self.generator.side_effect = lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "fixture failure")
        self.invoke("repair", "--run", str(path), "--inspection", str(failed), expected=2)
        self.generator.side_effect = self.generate_fixture
        result = self.invoke("repair", "--run", str(path), "--inspection", str(failed))
        self.assertEqual((2, "Wide"), (result["revision"], result["layout_profile"]))
        designer._load_run(path, {"awaiting_inspection"})

    def test_inspection_after_seven_minutes_can_finalize(self) -> None:
        path, run = self.candidate()
        self.clock += 1200
        result = self.invoke("finalize", "--run", str(path), "--inspection", str(self.inspection(run, True)))
        self.assertEqual("passed", result["validation"])

    def test_failed_inspection_never_publishes(self) -> None:
        path, run = self.candidate()
        result = self.invoke("finalize", "--run", str(path), "--inspection", str(self.inspection(run)), expected=2)
        self.assertIn("Rendered inspection failed", result["error"])
        self.assert_unpublished(run)

    def test_stale_revision_inspection_cannot_finalize_repaired_candidate(self) -> None:
        path, run = self.candidate()
        stale = self.inspection(run, True)
        self.invoke("repair", "--run", str(path), "--inspection", str(self.inspection(run)))
        result = self.invoke("finalize", "--run", str(path), "--inspection", str(stale), expected=2)
        self.assertIn("revision", result["error"])
        self.assert_unpublished(run)

    def test_naive_future_and_pregeneration_timestamps_are_rejected(self) -> None:
        path, run = self.candidate()
        generated = datetime.fromisoformat(run["generated_at_local"])
        for value in (
            "2026-09-07T20:00:05",
            (generated + timedelta(hours=1)).isoformat(),
            (generated - timedelta(seconds=2)).isoformat(),
        ):
            with self.subTest(value=value):
                inspection = self.inspection(run, True)
                content = designer._json_load(inspection)
                content["inspected_at"] = value
                designer._atomic_write_json(inspection, content)
                self.invoke("finalize", "--run", str(path), "--inspection", str(inspection), expected=2)
        self.assert_unpublished(run)

    def test_repair_refuses_tampered_staging(self) -> None:
        path, run = self.candidate()
        artifact = Path(run["stage_design"]) / f"SA_{run['scenario_slug']}.svg"
        artifact.write_bytes(artifact.read_bytes() + b"changed")
        result = self.invoke("repair", "--run", str(path), "--inspection", str(self.inspection(run)), expected=2)
        self.assertIn("Staged artifact changed", result["error"])
        self.assertEqual(1, self.generator.call_count)

    def test_repair_revalidates_run_cache_key_resources_and_seal_allowlist(self) -> None:
        path, original = self.candidate()
        failed = self.inspection(original)
        for field in ("cache_key", "resource_hashes", "staged_artifacts"):
            with self.subTest(field=field):
                run = json.loads(json.dumps(original))
                if field == "cache_key":
                    run[field] = "f" * 64
                    run["cache_directory"] = str(Path(run["cache_directory"]).with_name(run[field]))
                elif field == "resource_hashes":
                    run[field] = {"test-resource": "changed"}
                else:
                    run[field].pop("diagram-manifest.json")
                designer._atomic_write_json(path, run)
                self.invoke("repair", "--run", str(path), "--inspection", str(failed), expected=2)
        designer._atomic_write_json(path, original)
        self.assertEqual(1, self.generator.call_count)

    def test_repair_evidence_is_sealed(self) -> None:
        path, run = self.candidate()
        self.invoke("repair", "--run", str(path), "--inspection", str(self.inspection(run)))
        run = designer._json_load(path)
        evidence = Path(run["repair_attempts"][0]["inspection_path"])
        evidence.write_text("{}", encoding="utf-8")
        result = self.invoke("finalize", "--run", str(path), "--inspection", str(self.inspection(run, True)), expected=2)
        self.assertIn("evidence changed", result["error"])
        self.assert_unpublished(run)

    def test_repair_rejects_already_attempted_profile(self) -> None:
        path, run = self.candidate()
        result = self.invoke(
            "repair", "--run", str(path), "--inspection", str(self.inspection(run)),
            "--layout-profile", "Balanced", expected=2,
        )
        self.assertIn("unattempted", result["error"])
        self.assertEqual(1, self.generator.call_count)

    def test_zero_configured_repairs_are_enforced(self) -> None:
        path, run = self.candidate(maximum=0)
        result = self.invoke("repair", "--run", str(path), "--inspection", str(self.inspection(run)), expected=2)
        self.assertIn("exhausted", result["error"])
        self.assertEqual(1, self.generator.call_count)


if __name__ == "__main__":
    unittest.main()
