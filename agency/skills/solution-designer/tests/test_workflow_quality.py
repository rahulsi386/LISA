from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import time
import unittest
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from test_model_semantics import fixture_browser_evidence, fixture_png


SKILL_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "solution_designer_workflow", SKILL_ROOT / "scripts" / "solution_designer.py"
)
designer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(designer)
FIXTURE = SKILL_ROOT / "tests" / "fixtures" / "complexity-classification_20260813_120000.json"
REAL_SUBPROCESS_RUN = subprocess.run


def private_api(module, **overrides):
    return SimpleNamespace(**{
        **{name: value for name, value in vars(module).items() if not name.startswith("__")},
        **overrides,
    })


def remove_test_directory(path: Path, remove=shutil.rmtree, sleep=time.sleep) -> None:
    for attempt in range(6):
        if not path.exists():
            return
        try:
            remove(path)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in {5, 32, 33} or attempt == 5:
                raise
            sleep(0.1 * (attempt + 1))


class LayoutRuntimeTests(unittest.TestCase):
    def test_page_only_browser_collector_is_self_contained_and_callable(self) -> None:
        completed = REAL_SUBPROCESS_RUN([
            "node", "-e",
            "const c=require(process.argv[1]);const s=c.makeMcpInvocation('C:\\\\fixture\\\\run.json');"
            "const fn=new Function('return ('+s+')')();"
            "const forbidden=/require\\(|import\\(|process\\./.test(c.collectBrowserEvidenceInPage.toString());"
            "if(typeof fn!=='function'||forbidden)process.exit(1);",
            str(SKILL_ROOT / "scripts" / "inspect_preview.js"),
        ], capture_output=True, text=True)
        self.assertEqual(0, completed.returncode, completed.stderr)

    def test_cache_fingerprints_router_source_and_networkx_version(self) -> None:
        before = designer._resource_hashes()
        router = SKILL_ROOT / "scripts" / "layout_engine.py"
        self.assertEqual(before["layout_engine"], hashlib.sha256(router.read_bytes()).hexdigest())
        metadata = private_api(designer.importlib.metadata, version=Mock(return_value="changed"))
        with patch.object(designer, "importlib", private_api(designer.importlib, metadata=metadata)):
            after = designer._resource_hashes()
        self.assertNotEqual(before["networkx_version"], after["networkx_version"])
        self.assertNotEqual(designer._canonical_hash(before), designer._canonical_hash(after))

    def test_generation_forwards_the_current_python_interpreter(self) -> None:
        launch = Mock(side_effect=subprocess.TimeoutExpired("test", 1))
        with patch.object(designer, "subprocess", private_api(subprocess, run=launch)):
            with self.assertRaises(designer.DesignerError):
                designer._generate_candidate({}, SKILL_ROOT / "tests" / "design")
        self.assertEqual(launch.call_args.kwargs["env"]["LISA_PYTHON"], sys.executable)


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
        self.addCleanup(remove_test_directory, self.root)
        classification = self.root / "output" / "classification" / FIXTURE.name
        classification.parent.mkdir(parents=True)
        shutil.copy2(FIXTURE, classification)
        self.config = self.root / "lisa-config.json"
        self.config.write_text(json.dumps({"basePath": "."}), encoding="utf-8")
        self.clock = 1788789600.0
        self.fixture_scores = {"Balanced": 90, "Spacious": 80, "Wide": 70}
        self.fixture_failed_profiles = set()
        self.enterContext(patch.object(designer, "time", private_api(time, time=lambda: self.clock)))
        self.enterContext(patch.object(designer, "os", private_api(designer.os)))
        self.enterContext(patch.object(designer, "_resource_hashes", return_value={"test-resource": "a" * 64}))
        self.generator = Mock(side_effect=self.generate_fixture)
        def run_isolated(command, **kwargs):
            if isinstance(command, (list, tuple)) and str(designer.FAST_PATH) in command:
                return self.generator(command, **kwargs)
            return REAL_SUBPROCESS_RUN(command, **kwargs)
        self.enterContext(patch.object(designer, "subprocess", private_api(subprocess, run=run_isolated)))

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
        stage = (Path(command[command.index("-TempOutputPath") + 1]) / "design").resolve()
        self.assertTrue(stage.is_relative_to(self.root.resolve()), "Fixture generation must stay in its owned test directory")
        attempted = [command[command.index("-LayoutProfile") + 1]] if "-LayoutProfile" in command else list(designer.LAYOUT_PROFILES)
        candidates = [
            {"profile": profile, "order": order,
             "validation": "failed" if profile in self.fixture_failed_profiles else "passed",
             "score": None if profile in self.fixture_failed_profiles else self.fixture_scores[profile],
             "issues": ["Synthetic geometry failure"] if profile in self.fixture_failed_profiles else []}
            for order, profile in enumerate(attempted)
        ]
        passing = sorted(
            [candidate for candidate in candidates if candidate["validation"] == "passed"],
            key=lambda candidate: (-candidate["score"], candidate["order"]),
        )
        if not passing:
            return subprocess.CompletedProcess(command, 1, "", "No synthetic candidate passed geometry")
        profile = passing[0]["profile"]
        model = designer._json_load(stage / "design-model.json")
        slug = model["scenarioSlug"]
        for name in designer._artifact_names(stage, slug):
            if name == "design-model.json" or name.endswith((".drawio", ".mmd")) or name == "source-report.json":
                continue
            if name.endswith(".json"):
                designer._atomic_write_json(stage / name, {"test_fixture": True})
            elif name.endswith(".png"):
                (stage / name).write_bytes(fixture_png(color=20 + designer.LAYOUT_PROFILES.index(profile)))
            else:
                (stage / name).write_bytes(f"test fixture only: {profile} {name}".encode())
        generated_sources = REAL_SUBPROCESS_RUN(
            [sys.executable, str(designer.SCRIPTS / "source_artifacts.py"), "generate",
             "--model", str(stage / "design-model.json"), "--output", str(stage)],
            capture_output=True, text=True,
        )
        self.assertEqual(0, generated_sources.returncode, generated_sources.stderr)
        designer._atomic_write_json(stage / "diagram-manifest.json", {
            "test_fixture": True,
            "layoutQuality": {"validation": "passed", "score": self.fixture_scores[profile]},
        })
        designer._atomic_write_json(stage / "candidate-report.json", {
            "selection": "Synthetic fixture score ranking, not visual acceptance.",
            "selectedLayoutProfile": profile, "candidates": candidates,
        })
        designer._atomic_write_json(
            stage / "run-report.json",
            {
                "validation": "pending-inspection", "structuralValidation": "passed",
                "renderedInspection": "pending", "validationIssues": [],
                "selectedLayoutProfile": profile, "attemptedLayoutProfiles": attempted,
                "candidateReport": str(stage / "candidate-report.json"),
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
        if passed:
            fixture_browser_evidence(designer, run, value)
        path = Path(run["run_directory"]) / f"inspection-{uuid.uuid4().hex}.json"
        designer._atomic_write_json(path, value)
        if passed:
            self.invoke("attach-browser-evidence", "--run", str(Path(run["run_directory"]) / "run.json"),
                        "--evidence", str(Path(run["stage_design"]) / "browser-evidence.json"), "--inspection", str(path))
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
        self.assertEqual(list(designer.LAYOUT_PROFILES), run["attempted_layout_profiles"])
        self.assertEqual(["Balanced"], run["selected_layout_profiles"])
        self.assertEqual([], run["inspected_layout_profiles"])

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
            {item.name for item in artifacts.iterdir() if item.suffix in {".svg", ".png"} and not item.name.startswith("inspection-")},
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
            list(designer.LAYOUT_PROFILES), designer._json_load(path)["attempted_layout_profiles"]
        )
        self.assertEqual(["Balanced", "Wide"], designer._json_load(path)["selected_layout_profiles"])
        self.assertEqual(["Balanced"], designer._json_load(path)["inspected_layout_profiles"])

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

    def test_repair_is_bounded_and_each_profile_is_selected_once(self) -> None:
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
        completed = self.inspection(run, True)
        evidence.write_text("{}", encoding="utf-8")
        result = self.invoke("finalize", "--run", str(path), "--inspection", str(completed), expected=2)
        self.assertIn("evidence changed", result["error"])
        self.assert_unpublished(run)

    def test_repair_rejects_already_inspected_profile(self) -> None:
        path, run = self.candidate()
        result = self.invoke(
            "repair", "--run", str(path), "--inspection", str(self.inspection(run)),
            "--layout-profile", "Balanced", expected=2,
        )
        self.assertIn("uninspected", result["error"])
        self.assertEqual(1, self.generator.call_count)

    def test_zero_configured_repairs_are_enforced(self) -> None:
        path, run = self.candidate(maximum=0)
        result = self.invoke("repair", "--run", str(path), "--inspection", str(self.inspection(run)), expected=2)
        self.assertIn("exhausted", result["error"])
        self.assertEqual(1, self.generator.call_count)

    def test_old_all_true_assertions_are_not_browser_evidence(self) -> None:
        path, run = self.candidate()
        inspection = self.inspection(run, True)
        value = designer._json_load(inspection)
        value.pop("browser_evidence")
        designer._atomic_write_json(inspection, value)
        result = self.invoke("finalize", "--run", str(path), "--inspection", str(inspection), expected=2)
        self.assertIn("browser_evidence", result["error"])
        self.assert_unpublished(run)

    def test_missing_or_changed_browser_screenshot_fails_closed(self) -> None:
        path, run = self.candidate()
        inspection = self.inspection(run, True)
        screenshot = Path(run["stage_design"]) / "inspection-preview.png"
        original = screenshot.read_bytes()
        for missing in (True, False):
            with self.subTest(missing=missing):
                if missing:
                    screenshot.unlink()
                else:
                    screenshot.write_bytes(original + b"tampered")
                result = self.invoke("finalize", "--run", str(path), "--inspection", str(inspection), expected=2)
                self.assertIn("screenshot missing or changed", result["error"])
                screenshot.write_bytes(original)
        self.assert_unpublished(run)

    def test_browser_receipt_rejects_stale_identity_dimensions_and_links(self) -> None:
        _, run = self.candidate()
        inspection_path = self.inspection(run, True)
        inspection = designer._json_load(inspection_path)
        root = Path(run["stage_design"])
        evidence_path = root / "browser-evidence.json"
        original = designer._json_load(evidence_path)
        context = designer._json_load(root / "run-report.json")["inspectionContext"]
        for mutate in (
            lambda value: value.update(revision=1),
            lambda value: value.update(model_sha256="e" * 64),
            lambda value: value.update(captured_at=(datetime.fromisoformat(value["generated_at"]) - timedelta(seconds=2)).isoformat()),
            lambda value: value["diagrams"]["architecture"].update(natural_width=1),
            lambda value: value["diagrams"]["architecture"].update(actual_width=1),
            lambda value: value["links"][0].update(href="..\\outside.svg"),
            lambda value: value["screenshots"]["preview"].update(path="..\\outside.png"),
            lambda value: value["artifact_sha256"].update({"preview.html": "e" * 64}),
        ):
            value = json.loads(json.dumps(original))
            mutate(value)
            designer._atomic_write_json(evidence_path, value)
            inspection["browser_evidence"]["sha256"] = designer._sha256_file(evidence_path)
            with self.assertRaises(designer.DesignerError):
                designer._validate_browser_evidence(root, inspection, context)
        designer._atomic_write_json(evidence_path, original)
        self.assert_unpublished(run)

    def test_attachment_does_not_claim_visual_judgment(self) -> None:
        path, run = self.candidate()
        inspection_path = self.inspection(run, False)
        value = designer._json_load(inspection_path)
        fixture_browser_evidence(designer, run, value)
        designer._atomic_write_json(inspection_path, value)
        result = self.invoke("attach-browser-evidence", "--run", str(path),
                             "--evidence", str(Path(run["stage_design"]) / "browser-evidence.json"),
                             "--inspection", str(inspection_path))
        self.assertTrue(result["human_vision_judgment_required"])
        attached = designer._json_load(inspection_path)
        self.assertFalse(any(attached["checks"].values()))
        self.assertEqual("failed", attached["status"])

    def test_source_validation_cannot_be_bypassed_by_updating_seal_hash(self) -> None:
        path, run = self.candidate()
        completed = self.inspection(run, True)
        source = Path(run["stage_design"]) / f"SA_{run['scenario_slug']}.mmd"
        source.write_text("flowchart LR\nA --> B\n", encoding="utf-8")
        updated = designer._json_load(path)
        updated["staged_artifacts"][source.name] = designer._sha256_file(source)
        designer._atomic_write_json(path, updated)
        result = self.invoke("finalize", "--run", str(path), "--inspection", str(completed), expected=2)
        self.assertIn("Editable source validation failed", result["error"])
        self.assert_unpublished(run)

    def test_cache_seals_evidence_and_sources_and_preserves_inspection_time(self) -> None:
        path, run = self.candidate()
        completed = self.inspection(run, True)
        original = designer._json_load(completed)
        result = self.invoke("finalize", "--run", str(path), "--inspection", str(completed))
        cache = Path(run["cache_directory"])
        cached = designer._json_load(cache / "inspection-report.json")
        self.assertEqual(original, cached)
        self.assertIn(f"v{designer.CACHE_VERSION}", cache.parts)
        self.assertEqual("5", designer.CACHE_VERSION)
        self.assertEqual({"drawio", "architecture_mermaid", "sequence_mermaid", "report"}, set(result["editable_sources"]))
        for name in (*designer.EVIDENCE_ARTIFACT_NAMES, f"Design_{run['scenario_slug']}.drawio", "source-report.json", "candidate-report.json"):
            self.assertIn(name, run["expected_cache_artifacts"])
        screenshot = cache / "inspection-architecture.png"
        screenshot.write_bytes(screenshot.read_bytes() + b"changed")
        self.assertFalse(designer._cache_valid(cache, run["cache_key"], set(run["expected_cache_artifacts"])))

    def test_publication_rolls_back_on_pointer_failure(self) -> None:
        first_path, first = self.candidate()
        self.invoke("finalize", "--run", str(first_path), "--inspection", str(self.inspection(first, True)))
        root = Path(first["design_root"])
        original = {item.name: item.read_bytes() for item in (root / "artifacts").iterdir()}
        pointer = (root / "current-design.json").read_bytes()
        second_path, second = self.candidate()
        completed = self.inspection(second, True)
        with patch.object(designer, "_write_current_pointer", side_effect=OSError("test pointer failure")):
            self.invoke("finalize", "--run", str(second_path), "--inspection", str(completed), expected=2)
        self.assertEqual(pointer, (root / "current-design.json").read_bytes())
        self.assertEqual(original, {item.name: item.read_bytes() for item in (root / "artifacts").iterdir()})

    def test_failed_cache_commit_never_publishes_partial_artifacts(self) -> None:
        path, run = self.candidate()
        completed = self.inspection(run, True)
        with patch.object(designer, "_write_cache", side_effect=OSError("test cache failure")):
            self.invoke("finalize", "--run", str(path), "--inspection", str(completed), expected=2)
        self.assert_unpublished(run)

    def test_atomic_file_replacement_retries_transient_windows_sharing_denial(self) -> None:
        target = self.root / "atomic-write.json"
        target.write_text("original", encoding="utf-8")
        original_replace = designer.os.replace
        calls = []
        def transient_replace(source, destination):
            calls.append((source, destination))
            if len(calls) == 1:
                error = PermissionError("Synthetic Windows sharing denial")
                error.winerror = 32
                raise error
            return original_replace(source, destination)
        with patch.object(designer.os, "replace", side_effect=transient_replace), patch.object(designer.time, "sleep"):
            designer._atomic_write_text(target, "replacement")
        self.assertEqual(2, len(calls))
        self.assertEqual("replacement", target.read_text(encoding="utf-8"))

    def test_fixture_cleanup_retries_transient_windows_sharing_denial(self) -> None:
        nested = self.root / "cleanup-check"
        nested.mkdir()
        (nested / "report.json").write_text("{}", encoding="utf-8")
        original_remove = shutil.rmtree
        calls = []
        def transient_remove(path):
            calls.append(path)
            if len(calls) == 1:
                error = PermissionError("Synthetic Windows sharing denial")
                error.winerror = 32
                raise error
            return original_remove(path)
        remove_test_directory(nested, remove=transient_remove, sleep=lambda _: None)
        self.assertEqual(2, len(calls))
        self.assertFalse(nested.exists())

    def test_repair_uses_best_uninspected_passing_score_after_all_profiles_were_generated(self) -> None:
        self.fixture_scores.update(Wide=98, Balanced=93, Spacious=80)
        path, run = self.candidate()
        self.assertEqual("Wide", run["selected_layout_profile"])
        self.assertEqual(["Wide", "Balanced", "Spacious"], run["passing_layout_profiles"])
        self.assertEqual(list(designer.LAYOUT_PROFILES), run["attempted_layout_profiles"])
        result = self.invoke("repair", "--run", str(path), "--inspection", str(self.inspection(run)))
        repaired = designer._json_load(path)
        self.assertEqual("Balanced", result["layout_profile"])
        self.assertEqual(["Wide", "Balanced"], repaired["selected_layout_profiles"])
        self.assertEqual(["Wide"], repaired["inspected_layout_profiles"])
        self.assertEqual(list(designer.LAYOUT_PROFILES), repaired["attempted_layout_profiles"])
        self.assertEqual(1, result["remaining_repair_attempts"])

    def test_failed_geometry_profiles_are_not_repair_candidates(self) -> None:
        self.fixture_failed_profiles.add("Spacious")
        path, run = self.candidate()
        self.assertEqual(["Balanced", "Wide"], run["passing_layout_profiles"])
        result = self.invoke("repair", "--run", str(path), "--inspection", str(self.inspection(run)))
        self.assertEqual("Wide", result["layout_profile"])
        repaired = designer._json_load(path)
        blocked = self.invoke("repair", "--run", str(path), "--inspection", str(self.inspection(repaired)), expected=2)
        self.assertIn("No uninspected passing", blocked["error"])
        self.assertEqual(["Balanced", "Wide"], designer._json_load(path)["inspected_layout_profiles"])
        self.assertEqual(2, self.generator.call_count)

    def test_single_passing_candidate_does_not_trigger_a_repair_loop(self) -> None:
        self.fixture_failed_profiles.update({"Spacious", "Wide"})
        path, run = self.candidate()
        result = self.invoke("repair", "--run", str(path), "--inspection", str(self.inspection(run)), expected=2)
        self.assertIn("No uninspected passing", result["error"])
        current = designer._json_load(path)
        self.assertEqual(["Balanced"], current["inspected_layout_profiles"])
        self.assertEqual([], current["repair_attempts"])
        self.assertEqual(1, self.generator.call_count)

    def test_candidate_score_ties_use_generation_order(self) -> None:
        self.fixture_scores = {profile: 90 for profile in designer.LAYOUT_PROFILES}
        _, run = self.candidate()
        self.assertEqual(list(designer.LAYOUT_PROFILES), run["passing_layout_profiles"])
        self.assertEqual("Balanced", run["selected_layout_profile"])

    def test_generator_cannot_seal_a_lower_ranked_selected_candidate(self) -> None:
        path, run = self.prepare()
        def select_low_score(command, **kwargs):
            completed = self.generate_fixture(command, **kwargs)
            stage = Path(command[command.index("-TempOutputPath") + 1]) / "design"
            for name in ("candidate-report.json", "run-report.json"):
                value = designer._json_load(stage / name)
                value["selectedLayoutProfile"] = "Wide"
                designer._atomic_write_json(stage / name, value)
            return completed
        self.generator.side_effect = select_low_score
        result = self.invoke("generate", "--run", str(path), expected=2)
        self.assertIn("highest passing score", result["error"])
        self.assert_unpublished(run)

    def test_selected_score_must_match_its_geometry_manifest(self) -> None:
        path, run = self.prepare()
        def change_manifest_score(command, **kwargs):
            completed = self.generate_fixture(command, **kwargs)
            stage = Path(command[command.index("-TempOutputPath") + 1]) / "design"
            manifest = designer._json_load(stage / "diagram-manifest.json")
            manifest["layoutQuality"]["score"] = 1
            designer._atomic_write_json(stage / "diagram-manifest.json", manifest)
            return completed
        self.generator.side_effect = change_manifest_score
        result = self.invoke("generate", "--run", str(path), expected=2)
        self.assertIn("score disagrees", result["error"])
        self.assert_unpublished(run)

    def test_first_passing_profile_without_all_candidates_is_rejected(self) -> None:
        path, run = self.prepare()
        def omit_profiles(command, **kwargs):
            completed = self.generate_fixture(command, **kwargs)
            stage = Path(command[command.index("-TempOutputPath") + 1]) / "design"
            report = designer._json_load(stage / "run-report.json")
            report["attemptedLayoutProfiles"] = ["Balanced"]
            designer._atomic_write_json(stage / "run-report.json", report)
            return completed
        self.generator.side_effect = omit_profiles
        self.invoke("generate", "--run", str(path), expected=2)
        self.assert_unpublished(run)

    def test_profile_history_cannot_invent_passing_or_inspected_layouts(self) -> None:
        self.fixture_failed_profiles.add("Wide")
        path, original = self.candidate()
        for field, values in (
            ("passing_layout_profiles", ["Balanced", "Spacious", "Wide"]),
            ("selected_layout_profiles", ["Balanced", "Spacious"]),
            ("inspected_layout_profiles", ["Wide"]),
        ):
            with self.subTest(field=field):
                current = json.loads(json.dumps(original))
                current[field] = values
                designer._atomic_write_json(path, current)
                with self.assertRaises(designer.DesignerError):
                    designer._load_run(path, {"awaiting_inspection"})
        designer._atomic_write_json(path, original)

    def test_candidate_report_is_published_and_independently_validated_on_cache_reuse(self) -> None:
        path, run = self.candidate()
        result = self.invoke("finalize", "--run", str(path), "--inspection", str(self.inspection(run, True)))
        published = Path(result["candidate_report"])
        self.assertTrue(published.is_file())
        pointer = designer._json_load(Path(run["design_root"]) / "current-design.json")
        self.assertIn("candidate-report.json", pointer["artifacts"])
        self.assertEqual("output/design/artifacts/candidate-report.json", pointer["result"]["candidate_report"])
        final_run = designer._json_load(path)
        self.assertEqual(["Balanced"], final_run["inspected_layout_profiles"])
        cache = Path(run["cache_directory"])
        expected = set(run["expected_cache_artifacts"])
        self.assertTrue(designer._cache_valid(cache, run["cache_key"], expected))
        candidate_report = designer._json_load(cache / "candidate-report.json")
        candidate_report["candidates"][1]["score"] = 999
        designer._atomic_write_json(cache / "candidate-report.json", candidate_report)
        manifest = designer._json_load(cache / "cache-manifest.json")
        manifest["artifacts"]["candidate-report.json"] = designer._sha256_file(cache / "candidate-report.json")
        designer._atomic_write_json(cache / "cache-manifest.json", manifest)
        self.assertFalse(designer._cache_valid(cache, run["cache_key"], expected))


class FixtureIsolationTests(unittest.TestCase):
    def test_fixture_restores_only_owned_mocks_and_keeps_packaged_paths(self):
        paths = {key: getattr(designer, key) for key in (
            "RESOURCES", "ICON_MANIFEST", "MODEL_SCHEMA", "INSPECTION_SCHEMA", "REFERENCE_MANIFEST"
        )}
        original_time = time.time
        original_subprocess = subprocess.run
        original_os = designer.os
        original_replace = original_os.replace
        marker = SimpleNamespace(value="original")
        external_patch = patch.object(marker, "value", "external-owner")
        external_patch.start()
        case = RepairWorkflowTests("test_structural_pass_is_only_an_inspection_candidate")
        try:
            try:
                case.setUp()
                self.assertIs(time.time, original_time)
                self.assertIs(subprocess.run, original_subprocess)
                self.assertIs(original_os.replace, original_replace)
                self.assertIsNot(designer.time, time)
                self.assertIsNot(designer.subprocess, subprocess)
                self.assertIsNot(designer.os, original_os)
                for key, value in paths.items():
                    self.assertIs(getattr(designer, key), value)
            finally:
                self.assertTrue(case.doCleanups())
            self.assertEqual("external-owner", marker.value)
            self.assertIs(designer.time, time)
            self.assertIs(designer.subprocess, subprocess)
            self.assertIs(designer.os, original_os)
            for key, value in paths.items():
                self.assertIs(getattr(designer, key), value)
        finally:
            external_patch.stop()

    def test_fixture_writers_reject_packaged_resource_destinations(self):
        case = RepairWorkflowTests("test_structural_pass_is_only_an_inspection_candidate")
        try:
            case.setUp()
            with self.assertRaisesRegex(AssertionError, "owned test directory"):
                case.generate_fixture(["powershell", "-TempOutputPath", str(SKILL_ROOT / "resources")])
            with self.assertRaisesRegex(AssertionError, "owned tests directory"):
                fixture_browser_evidence(designer, {"stage_design": str(SKILL_ROOT / "resources")}, {})
        finally:
            self.assertTrue(case.doCleanups())

    def test_resource_tampering_uses_a_copy_and_an_isolated_module(self):
        work = SKILL_ROOT / "tests" / (".resource-isolation-" + uuid.uuid4().hex)
        work.mkdir()
        self.addCleanup(remove_test_directory, work)
        resources = work / "resources"
        shutil.copytree(SKILL_ROOT / "resources", resources)
        before_paths = {key: getattr(designer, key) for key in (
            "RESOURCES", "ICON_MANIFEST", "MODEL_SCHEMA", "INSPECTION_SCHEMA", "REFERENCE_MANIFEST"
        )}
        isolated = importlib.util.module_from_spec(SPEC)
        original_search_path = list(sys.path)
        try:
            SPEC.loader.exec_module(isolated)
        finally:
            sys.path[:] = original_search_path
        isolated.RESOURCES = resources
        for key in ("ICON_MANIFEST", "MODEL_SCHEMA", "INSPECTION_SCHEMA", "REFERENCE_MANIFEST"):
            setattr(isolated, key, resources / before_paths[key].name)
        manifest = isolated._json_load(isolated.ICON_MANIFEST)
        relative = manifest["packs"]["Power Platform"]["licenseFile"]
        packaged = (SKILL_ROOT / "resources" / relative).resolve()
        copied = (resources / relative).resolve()
        self.assertTrue(copied.is_relative_to(work.resolve()))
        self.assertNotEqual(packaged, copied)
        before = designer._sha256_file(packaged)
        copied.write_bytes(b"A")
        self.assertEqual(hashlib.sha256(b"A").hexdigest(), isolated._sha256_file(copied))
        self.assertEqual(before, designer._sha256_file(packaged))
        for key, value in before_paths.items():
            self.assertIs(getattr(designer, key), value)

    def test_python_and_collector_license_gates_reject_private_copy_tampering(self):
        work = SKILL_ROOT / "tests" / (".license-gate-fixture-" + uuid.uuid4().hex)
        resources = work / "resources"
        work.mkdir()
        self.addCleanup(remove_test_directory, work)
        shutil.copytree(SKILL_ROOT / "resources", resources)
        fixture_license = resources / "icons" / "licenses" / "synthetic-fixture-license.txt"
        fixture_license.parent.mkdir(parents=True, exist_ok=True)
        fixture_license.write_bytes(b"Synthetic license fixture, not a Microsoft license.\n")
        manifest = {"packs": {"Synthetic fixture": {
            "licenseFile": "icons/licenses/synthetic-fixture-license.txt",
            "licenseSha256": designer._sha256_file(fixture_license),
        }}}
        designer._atomic_write_json(resources / "icon-manifest.json", manifest)
        isolated = importlib.util.module_from_spec(SPEC)
        original_search_path = list(sys.path)
        try:
            SPEC.loader.exec_module(isolated)
        finally:
            sys.path[:] = original_search_path
        isolated.RESOURCES = resources
        isolated.ICON_MANIFEST = resources / "icon-manifest.json"
        self.assertTrue(isolated._validate_license_provenance(manifest))
        command = [
            "node", "-e",
            "const c=require(process.argv[1]);c.validateLicenseProvenance(process.argv[2])"
            ".then(()=>console.log('passed')).catch(e=>{console.error(e.message);process.exitCode=2});",
            str(SKILL_ROOT / "scripts" / "inspect_preview.js"), str(resources),
        ]
        accepted = REAL_SUBPROCESS_RUN(command, capture_output=True, text=True)
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        fixture_license.write_bytes(b"Tampered synthetic license fixture.\n")
        with self.assertRaisesRegex(isolated.DesignerError, "Packaged license provenance hash mismatch"):
            isolated._validate_license_provenance(manifest)
        rejected = REAL_SUBPROCESS_RUN(command, capture_output=True, text=True)
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("Packaged license provenance hash mismatch", rejected.stderr)
        scripts = work / "scripts"
        scripts.mkdir()
        copied_collector = scripts / "inspect_preview.js"
        shutil.copy2(SKILL_ROOT / "scripts" / "inspect_preview.js", copied_collector)
        run_path = work / "run.json"
        designer._atomic_write_json(run_path, {
            "resource_hashes": {"icon-manifest.json": designer._sha256_file(resources / "icon-manifest.json")}
        })
        wrapper = work / "browser-collector.js"
        blocked_entrypoints = REAL_SUBPROCESS_RUN([
            "node", "-e",
            "const c=require(process.argv[1]);const page=new Proxy({},"
            "{get(){throw new Error('Browser accessed before license gate')}});"
            "(async()=>{for(const call of [()=>c.collectBrowserEvidence(page,{runPath:process.argv[2]}),"
            "()=>c.emitMcpInvocation(process.argv[2],process.argv[3])]){"
            "try{await call();throw new Error('Mismatched license was accepted')}"
            "catch(e){if(!e.message.includes('license provenance hash mismatch'))throw e}}})()"
            ".catch(e=>{console.error(e.message);process.exitCode=2});",
            str(copied_collector), str(run_path), str(wrapper),
        ], capture_output=True, text=True)
        self.assertEqual(0, blocked_entrypoints.returncode, blocked_entrypoints.stderr)
        self.assertFalse(wrapper.exists())

    def test_collector_requires_resource_binding_before_browser_access(self):
        work = SKILL_ROOT / "tests" / (".collector-binding-fixture-" + uuid.uuid4().hex)
        work.mkdir()
        self.addCleanup(remove_test_directory, work)
        run_path = work / "run.json"
        designer._atomic_write_json(run_path, {"status": "awaiting_inspection"})
        completed = REAL_SUBPROCESS_RUN([
            "node", "-e",
            "const c=require(process.argv[1]);const page=new Proxy({},"
            "{get(){throw new Error('Browser accessed before provenance gate')}});"
            "c.collectBrowserEvidence(page,{runPath:process.argv[2]})"
            ".then(()=>process.exitCode=1).catch(e=>{if(!e.message.includes('resource-manifest binding'))"
            "{console.error(e.message);process.exitCode=2}});",
            str(SKILL_ROOT / "scripts" / "inspect_preview.js"), str(run_path),
        ], capture_output=True, text=True)
        self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
