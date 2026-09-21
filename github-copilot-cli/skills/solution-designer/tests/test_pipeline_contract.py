from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


@unittest.skipUnless(POWERSHELL, "PowerShell is required for the packaged pipeline")
class PipelineContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix=".pipeline-", dir=ROOT / "tests")
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.output = Path(cls.workspace.name) / "design"
        cls.output.mkdir()
        cls.model = cls.output / "design-model.json"
        cls.model.write_bytes((ROOT / "resources" / "design-model.example.json").read_bytes())
        cls.model_hash = hashlib.sha256(cls.model.read_bytes()).hexdigest()
        cls.env = dict(os.environ, LISA_PYTHON=sys.executable)
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-File", str(ROOT / "scripts" / "Invoke-FastPath.ps1"),
             "-ModelPath", str(cls.model), "-TempOutputPath", cls.workspace.name],
            env=cls.env, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=1200,
        )
        if result.returncode:
            raise AssertionError(result.stderr + "\n" + result.stdout)
        cls.report = json.loads((cls.output / "run-report.json").read_text())

    def test_sources_precede_presentation_and_remain_editable(self):
        self.assertEqual(
            self.report["pipelineStages"],
            ["drawio", "mermaid", "presentation", "raster", "inspection"],
        )
        self.assertEqual(self.report["validation"], "pending-inspection")
        source = json.loads((self.output / "source-report.json").read_text())
        self.assertEqual(source["validation"], "passed")
        pages = ET.parse(self.output / "Design_Service_Request_Agent.drawio").findall("diagram")
        self.assertEqual(len(pages), 2)
        for page in pages:
            self.assertGreater(len(page.findall(".//mxCell[@vertex='1']")), 1)
            self.assertGreater(len(page.findall(".//mxCell[@edge='1']")), 0)
        for prefix in ("SA", "SD"):
            for suffix in ("mmd", "svg", "png"):
                self.assertGreater((self.output / f"{prefix}_Service_Request_Agent.{suffix}").stat().st_size, 0)
        self.assertEqual(self.model_hash, hashlib.sha256(self.model.read_bytes()).hexdigest())

    def test_all_profiles_are_ranked_and_failures_are_retained(self):
        candidates = json.loads((self.output / "candidate-report.json").read_text())
        self.assertEqual([c["profile"] for c in candidates["candidates"]], ["Balanced", "Spacious", "Wide"])
        passing = [c for c in candidates["candidates"] if c["validation"] == "passed"]
        self.assertTrue(passing)
        winner = max(passing, key=lambda candidate: candidate["score"])
        self.assertEqual(winner["profile"], candidates["selectedLayoutProfile"])
        manifest = json.loads((self.output / "diagram-manifest.json").read_text())
        self.assertEqual(manifest["layoutQuality"]["candidateReport"], "candidate-report.json")
        self.assertTrue((self.output / manifest["layoutQuality"]["candidateReport"]).is_file())
        for candidate in candidates["candidates"]:
            self.assertTrue(Path(candidate["directory"]).is_dir())
            self.assertIsInstance(candidate["compositionReport"], dict)
            if candidate["validation"] == "failed":
                self.assertTrue(candidate["issues"])

    def test_tampered_mermaid_blocks_presentation_regeneration(self):
        path = self.output / "SA_Service_Request_Agent.mmd"
        original = path.read_bytes()
        svg = self.output / "SA_Service_Request_Agent.svg"
        before = hashlib.sha256(svg.read_bytes()).hexdigest()
        try:
            path.write_bytes(original + b"\nInjected --> Unreviewed\n")
            result = subprocess.run(
                [POWERSHELL, "-NoProfile", "-File", str(ROOT / "scripts" / "New-Diagrams.ps1"),
                 "-ModelPath", str(self.model), "-OutputDirectory", str(self.output),
                 "-SourcesPrepared"],
                env=self.env, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=60,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source", (result.stdout + result.stderr).lower())
            self.assertEqual(before, hashlib.sha256(svg.read_bytes()).hexdigest())
        finally:
            path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
