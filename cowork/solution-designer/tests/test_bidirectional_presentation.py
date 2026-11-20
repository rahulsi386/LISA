from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHELL = shutil.which("pwsh") or shutil.which("powershell")


class BidirectionalDrawingTests(unittest.TestCase):
    def test_rasterized_start_arrow_faces_the_source_without_changing_normal_arrows(self):
        source = """
const {Drawing}=require('./generate');
const {Typography,fontOptions}=require('./typography');
const {Resvg}=require('@resvg/resvg-js');
function sample(bidirectional) {
  const drawing=new Drawing(160,new Typography());
  drawing.arrow([{x:40,y:40},{x:110,y:40}],'#ff0000',false,'',bidirectional);
  const image=new Resvg(drawing.svg(80,'Direction test',''),{font:fontOptions}).render();
  const pixels=image.pixels;
  const red=(x,y)=>{const i=(y*image.width+x)*4;
    return pixels[i]>200 && pixels[i+1]<80 && pixels[i+2]<80 && pixels[i+3]>200;};
  return {source:red(46,42),target:red(103,42),outside:red(34,42)};
}
console.log(JSON.stringify({both:sample(true),normal:sample(false)}));
"""
        result = subprocess.run(["node", "-e", source], cwd=ROOT / "renderer",
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = json.loads(result.stdout)
        self.assertEqual(result["both"], {"source": True, "target": True, "outside": False})
        self.assertEqual(result["normal"], {"source": False, "target": True, "outside": False})


@unittest.skipUnless(SHELL, "PowerShell is required for SVG validation")
class BidirectionalPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.TemporaryDirectory(prefix=".bidirectional-", dir=ROOT / "tests")
        cls.addClassCleanup(cls.workspace.cleanup)
        cls.design = Path(cls.workspace.name) / "design"
        cls.design.mkdir()
        model = json.loads((ROOT / "resources" / "design-model.example.json").read_text())
        controls = {c["id"] for c in model["components"] if c["kind"] in {"security", "governance", "monitoring"}}
        for index, edge in enumerate(model["relationships"]):
            edge["id"] = f"direction-test-{index:03}"
        cls.routed = next(edge for edge in model["relationships"]
                          if not {edge["from"], edge["to"]} & controls)
        cls.scoped = next(edge for edge in model["relationships"]
                          if {edge["from"], edge["to"]} & controls)
        cls.routed["direction"] = cls.scoped["direction"] = "bidirectional"
        cls.model = model
        cls.model_path = cls.design / "design-model.json"
        cls.model_path.write_text(json.dumps(model), encoding="utf-8")
        for command in (
            [sys.executable, str(ROOT / "scripts" / "source_artifacts.py"), "generate",
             "--model", str(cls.model_path), "--output", str(cls.design)],
            ["node", str(ROOT / "renderer" / "generate.js"), "--model", str(cls.model_path),
             "--output", str(cls.design), "--icons", str(ROOT / "resources" / "icon-manifest.json"),
             "--references", str(ROOT / "resources" / "reference-manifest.json"), "--profile", "Balanced"],
        ):
            result = subprocess.run(command, capture_output=True, text=True, timeout=240)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
        cls.sa = cls.design / f"SA_{model['scenarioSlug']}.svg"
        cls.sd = cls.design / f"SD_{model['scenarioSlug']}.svg"
        cls.original = cls.sa.read_bytes()

    def validate(self):
        result = subprocess.run(
            [SHELL, "-NoProfile", "-File", str(ROOT / "scripts" / "Test-Diagrams.ps1"),
             "-SolutionArchitecture", str(self.sa), "-SequenceDiagram", str(self.sd),
             "-OutputPath", str(self.design / "validation-report.json")],
            capture_output=True, text=True, timeout=90,
        )
        return result, json.loads((self.design / "validation-report.json").read_text(encoding="utf-8-sig"))

    def test_sources_and_presentation_preserve_both_routed_and_scoped_directions(self):
        result, report = self.validate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        root = ET.fromstring(self.original)
        edge = next(e for e in root.iter() if e.get("data-id") == self.routed["id"])
        line = next(e for e in edge if e.tag.endswith("path"))
        self.assertEqual(line.get("marker-start"), line.get("marker-end")[:-1] + "-start)")
        scope = next(e for e in root.iter() if e.get("data-id") == self.scoped["id"])
        visible = "".join("".join(scope.itertext()).split())
        self.assertIn(self.scoped["from"] + "\u2194" + self.scoped["to"], visible)
        source_report = json.loads((self.design / "source-report.json").read_text())
        self.assertEqual(source_report["validation"], "passed")
        mermaid = (self.design / f"SA_{self.model['scenarioSlug']}.mmd").read_text()
        self.assertEqual(mermaid.count("<-->"), 2)
        self.assertFalse(report["issues"])

    def test_validator_rejects_missing_reverse_arrow_and_direction_tampering(self):
        for mutation, expected in (
            ("remove-start", "marker-start"),
            ("change-direction", "direction"),
            ("reverse-orientation", "source endpoint"),
            ("scope-arrow", "directional scope"),
        ):
            with self.subTest(mutation=mutation):
                root = ET.fromstring(self.original)
                edge = next(e for e in root.iter() if e.get("data-id") == self.routed["id"])
                line = next(e for e in edge if e.tag.endswith("path"))
                if mutation == "remove-start":
                    line.attrib.pop("marker-start")
                elif mutation == "change-direction":
                    edge.set("data-direction", "unidirectional")
                elif mutation == "reverse-orientation":
                    marker_id = line.get("marker-start")[5:-1]
                    next(e for e in root.iter() if e.get("id") == marker_id).set("orient", "180")
                else:
                    scope = next(e for e in root.iter() if e.get("data-id") == self.scoped["id"])
                    for element in scope.iter():
                        if element.text:
                            element.text = element.text.replace("\u2194", "\u2192")
                try:
                    self.sa.write_bytes(ET.tostring(root, encoding="utf-8"))
                    result, report = self.validate()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertTrue(any(expected in issue for issue in report["issues"]), report["issues"])
                finally:
                    self.sa.write_bytes(self.original)


if __name__ == "__main__":
    unittest.main()
