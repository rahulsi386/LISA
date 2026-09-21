from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILLS = Path(__file__).resolve().parents[1] / "skills"
sys.path.insert(0, str(SKILLS))
from analysis_handoff import load_validated_analysis


def analyzer_fixtures():
    path = SKILLS / "requirement-analyzer" / "tests" / "test_requirement_analyzer.py"
    spec = importlib.util.spec_from_file_location("handoff_analyzer_test_support", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load analyzer fixture helpers: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.RequirementAnalyzerTests()


class AnalysisClassificationIntegrationTests(unittest.TestCase):
    def command(self, skill: str, *arguments: str, success: bool = True) -> dict:
        script_name = "requirement_analyzer.py" if skill == "requirement-analyzer" else "complexity_classifier.py"
        result = subprocess.run(
            [sys.executable, "-B", str(SKILLS / skill / "scripts" / script_name), *arguments],
            capture_output=True, text=True, encoding="utf-8", timeout=90,
        )
        if success:
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        return {"stdout": result.stdout, "stderr": result.stderr}

    def prepared_analysis(self, temporary: str) -> tuple[dict, Path, Path]:
        helper = analyzer_fixtures()
        run, manifest = helper.prepare_fixture(Path(temporary))
        draft = Path(run["run_directory"]) / "evidence-ledger.integration.json"
        draft.write_text(json.dumps(helper.make_draft_ledger(run, manifest)), encoding="utf-8")
        return run, Path(run["run_directory"]) / "run.json", draft

    def test_published_analyzer_handoff_is_accepted_by_classifier(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run, run_path, draft = self.prepared_analysis(temporary)
            published = self.command(
                "requirement-analyzer", "publish", "--run", str(run_path), "--ledger", str(draft),
            )
            ledger, manifest = load_validated_analysis(
                Path(published["ledger"]), expected_requirements_root=Path(run["requirements_root"]),
            )
            self.assertEqual("validated", manifest["publication"]["status"])
            classified = self.command(
                "complexity-classifier", "prepare", "--config", run["config_path"],
                "--local-time", run["started_at_local"], "--offline",
            )
            self.assertEqual("prepared", classified["status"])
            classification_run = json.loads(Path(classified["run"]).read_text(encoding="utf-8"))
            self.assertEqual(Path(published["ledger"]), Path(classification_run["input_path"]))
            self.assertEqual(manifest["publication"]["ledger"]["sha256"], classification_run["input_sha256"])
            self.assertTrue(ledger["findings"])

    def test_warm_analyzer_republication_still_produces_a_valid_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run, run_path, draft = self.prepared_analysis(temporary)
            first = self.command("requirement-analyzer", "publish", "--run", str(run_path),
                                 "--ledger", str(draft))
            before, _ = load_validated_analysis(Path(first["ledger"]))
            initial_classification = self.command(
                "complexity-classifier", "prepare", "--config", run["config_path"],
                "--local-time", run["started_at_local"], "--offline",
            )
            initial_classifier_run = json.loads(
                Path(initial_classification["run"]).read_text(encoding="utf-8"),
            )
            warm = self.command(
                "requirement-analyzer", "prepare", "--config", run["config_path"],
                "--local-time", run["started_at_local"], "--workers", "2",
            )
            self.assertTrue(warm["analysis_cache_hit"])
            second = self.command(
                "requirement-analyzer", "publish", "--run", warm["run"],
                "--ledger", warm["reused_ledger"],
            )
            after, marker = load_validated_analysis(
                Path(second["ledger"]), expected_requirements_root=Path(run["requirements_root"]),
            )
            self.assertNotEqual(before["run_id"], after["run_id"])
            self.assertEqual(before["findings"], after["findings"])
            self.assertEqual(after["run_id"], marker["publication"]["run_id"])
            classified = self.command(
                "complexity-classifier", "prepare", "--config", run["config_path"],
                "--local-time", run["started_at_local"], "--offline",
            )
            current = json.loads(Path(classified["run"]).read_text(encoding="utf-8"))
            self.assertEqual(Path(second["ledger"]), Path(current["input_path"]))
            self.assertEqual(initial_classifier_run["cache_key"], current["cache_key"])

    def test_classifier_rejects_newer_unvalidated_ledger_instead_of_using_old_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run, run_path, draft = self.prepared_analysis(temporary)
            published = self.command("requirement-analyzer", "publish", "--run", str(run_path),
                                     "--ledger", str(draft))
            original = Path(published["ledger"])
            candidate = original.with_name("requirement-analysis_20260908_235959_999.json")
            candidate.write_bytes(original.read_bytes())
            modified = original.stat().st_mtime_ns + 1_000_000_000
            os.utime(candidate, ns=(modified, modified))
            error = self.command(
                "complexity-classifier", "prepare", "--config", run["config_path"],
                "--local-time", run["started_at_local"], "--offline", success=False,
            )
            self.assertIn("manifest", (error["stdout"] + error["stderr"]).lower())


if __name__ == "__main__":
    unittest.main()
