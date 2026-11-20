from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = r"""
const {visualQuality}=require('./quality');
const components=[{id:'a',name:'Exact requester',kind:'actor'},
  {id:'b',name:'Exact action',kind:'tool'}];
const relationship={id:'canonical-link',from:'a',to:'b',label:'Exact purpose',
  style:'call',implementationMode:'real'};
const cards=components.map((component,i)=>({id:component.id,component,
  x:80+i*480,y:130,width:300,height:220,titleSize:19,hero:false}));
const fixture={model:{components,relationships:[relationship]},cards,drawing:{texts:[]},
  layout:{routes:[{id:'canonical-link',sourceId:'a',targetId:'b',
    points:[{x:380,y:240},{x:560,y:240}]}],
    metrics:{crossings:0,sharedLaneLength:0,oppositeLaneLength:0,bends:0}},
  width:900,height:500,coverage:[{...relationship,representation:'routed'}]};
"""


class NumericalQualityTests(unittest.TestCase):
    def check(self, change: str = "") -> dict:
        result = subprocess.run(["node", "-e", BASE + change +
                                 "\nconsole.log(JSON.stringify(visualQuality(fixture)));"],
                                cwd=ROOT / "renderer", capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_passing_metrics_have_a_finite_higher_is_better_score_and_reasons(self):
        quality = self.check()
        self.assertEqual(quality["validation"], "passed")
        self.assertGreater(quality["score"], 80)
        self.assertTrue(all(gate["reason"] and gate["passed"] for gate in quality["gates"]))

    def test_identifiable_visual_defects_each_have_a_blocking_gate(self):
        for name, mutation in {
            "crossings": "fixture.layout.metrics.crossings=2;",
            "shared-lanes": "fixture.layout.metrics.sharedLaneLength=100;",
            "opposite-lanes": "fixture.layout.metrics.oppositeLaneLength=50;",
            "fit-width-readability": "fixture.width=3600;",
            "content-density": "fixture.cards[0].height=1000;",
            "agent-emphasis": "fixture.cards[0].component.kind='agent';",
            "geometry-bounds-overlap": "fixture.cards[1].x=200;",
            "relationship-coverage": "fixture.coverage[0].implementationMode='simulated';",
            "route-detour": "fixture.layout.routes[0].points=[{x:380,y:240},"
                "...Array.from({length:24},(_,i)=>({x:i%2?24:876,y:24})),{x:560,y:240}];",
        }.items():
            with self.subTest(gate=name):
                quality = self.check(mutation)
                self.assertEqual(quality["validation"], "failed")
                self.assertFalse(next(g["passed"] for g in quality["gates"] if g["name"] == name))
                self.assertTrue(any(issue.startswith(name + ":") for issue in quality["issues"]))

    def test_one_crossing_in_a_complex_graph_is_not_an_impossible_zero_crossing_rule(self):
        quality = self.check("""
fixture.layout.metrics.crossings=1;
fixture.layout.routes=Array.from({length:4},(_,i)=>({...fixture.layout.routes[0],id:'route'+i}));
""")
        self.assertTrue(next(g["passed"] for g in quality["gates"] if g["name"] == "crossings"))

    def test_duplicate_missing_and_reversed_relationships_fail_coverage(self):
        for mutation in ("fixture.coverage=[];", "fixture.coverage.push(fixture.coverage[0]);",
                         "fixture.coverage[0].from='b';fixture.coverage[0].to='a';",
                         "fixture.coverage[0].direction='bidirectional';",
                         "fixture.coverage[0].relationshipType='governs';"):
            quality = self.check(mutation)
            self.assertFalse(next(g["passed"] for g in quality["gates"] if g["name"] == "relationship-coverage"))

    def test_occurrence_ids_match_editable_sources_without_overwriting_canonical_ids(self):
        source = """
const {identified}=require('./quality');
const records=[{label:'same'},{id:'relationship-0001',label:'same'},
  {id:'relationship-0001-legacy',label:'same'},{label:'same'}];
const before=JSON.stringify(records);
console.log(JSON.stringify({ids:identified(records,'relationship').map(item=>item.id),
  sequence:identified([{},{}],'sequence').map(item=>item.id),unchanged:before===JSON.stringify(records)}));
"""
        result = subprocess.run(["node", "-e", source], cwd=ROOT / "renderer",
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(values["ids"], ["relationship-0001-legacy-legacy", "relationship-0001",
                                         "relationship-0001-legacy", "relationship-0004"])
        self.assertEqual(values["sequence"], ["sequence-0001", "sequence-0002"])
        self.assertTrue(values["unchanged"])


class CandidateQualityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = ROOT / "tests" / f".visual-quality-{uuid.uuid4().hex}"
        cls.design = cls.work / "design"
        cls.design.mkdir(parents=True)
        cls.addClassCleanup(shutil.rmtree, cls.work)
        cls.model = json.loads((ROOT / "tests" / "fixtures" / "procurement-reference-model.json").read_text(encoding="utf-8"))
        for index, edge in enumerate(cls.model["relationships"]):
            edge["id"] = f"canonical-{index:03}"
        cls.model["trustBoundaries"] = [{"id": "exact-trust-boundary", "name": "Exact tenant trust boundary",
                                       "component_ids": ["agent", "teams"], "controls": ["Exact control policy"]}]
        cls.model["presentation"] = {"primary_agent_id": "agent",
                                    "primary_path": ["requester", "teams", "agent", "flow", "erp"]}
        cls.model_path = cls.design / "design-model.json"
        cls.model_path.write_text(json.dumps(cls.model), encoding="utf-8")
        result = cls.generate(cls.model_path, cls.design)
        if result.returncode:
            raise AssertionError(result.stderr + result.stdout)
        cls.manifest = json.loads((cls.design / "diagram-manifest.json").read_text(encoding="utf-8"))
        cls.report = json.loads((cls.design / "composition-candidates-Balanced.json").read_text(encoding="utf-8"))
        cls.svg = ET.parse(cls.design / f"SA_{cls.model['scenarioSlug']}.svg").getroot()

    @staticmethod
    def generate(model: Path, design: Path) -> subprocess.CompletedProcess:
        return subprocess.run([
            "node", str(ROOT / "renderer" / "generate.js"),
            "--model", str(model), "--output", str(design),
            "--icons", str(ROOT / "resources" / "icon-manifest.json"),
            "--references", str(ROOT / "resources" / "reference-manifest.json"), "--profile", "Balanced",
        ], cwd=ROOT, capture_output=True, text=True, timeout=420, check=False)

    def test_all_families_are_evaluated_and_the_best_passing_score_wins(self):
        self.assertEqual([c["family"] for c in self.report["candidates"]], ["story", "hub", "boundary"])
        passing = [c for c in self.report["candidates"] if c["validation"] == "passed"]
        best = max(passing, key=lambda c: c["score"])
        self.assertEqual(self.report["selected"], best["family"])
        self.assertEqual(self.manifest["layoutQuality"]["score"], best["score"])
        self.assertEqual(self.manifest["layoutQuality"]["validation"], "passed")
        for candidate in self.report["candidates"]:
            self.assertTrue((self.design / candidate["layoutInput"]).is_file())
            self.assertTrue((self.design / candidate["layoutOutput"]).is_file())

    def test_canonical_edges_and_controls_are_represented_exactly_once(self):
        displayed = [element for element in self.svg.iter()
                     if element.get("data-kind") in {"connector", "control-annotation"}]
        self.assertEqual(len(displayed), len(self.model["relationships"]))
        expected = {edge["id"]: edge for edge in self.model["relationships"]}
        for element in displayed:
            edge = expected[element.get("data-id")]
            for key, attribute in (("from", "data-from"), ("to", "data-to"), ("style", "data-style"),
                                   ("implementationMode", "data-implementation-mode"), ("label", "data-label")):
                self.assertEqual(element.get(attribute), edge[key])
        self.assertTrue(any(element.get("data-kind") == "control-annotation" for element in displayed))
        nodes = {e.get("data-component-id"): e for e in self.svg.iter() if e.get("data-kind") == "node"}
        for component in self.model["components"]:
            visible = "".join("".join(nodes[component["id"]].itertext()).split())
            self.assertIn("".join(component["name"].split()), visible)
            members = [e.get("data-name") for e in nodes[component["id"]].iter() if e.get("data-kind") == "member"]
            self.assertCountEqual(members, list(dict.fromkeys(
                component.get("members", []) + component.get("inventoryNames", []))))

    def test_boundary_annotations_are_visible_and_hints_do_not_modify_model(self):
        self.assertEqual(json.loads(self.model_path.read_text(encoding="utf-8")), self.model)
        boundary = next(e for e in self.svg.iter() if e.get("data-kind") == "trust-boundary")
        content = "".join(boundary.itertext())
        self.assertIn("Exact tenant trust boundary", content)
        self.assertIn("Exact control policy", content)
        self.assertIn("agent, teams", content)
        self.assertEqual(self.manifest["layoutQuality"]["composition"]["spine"][0], "requester")

    def test_sources_are_hidden_without_a_passed_source_gate(self):
        self.assertEqual(self.manifest["editableSources"], {"validation": "not-present", "sources": False})
        preview = (self.design / "preview.html").read_text(encoding="utf-8")
        self.assertNotIn(f'href="Design_{self.model["scenarioSlug"]}.drawio"', preview)

    def test_read_only_source_gate_passes_then_tampering_blocks_before_presentation(self):
        design = self.work / "source-gate" / "design"
        design.mkdir(parents=True)
        model_path = design / "design-model.json"
        model_path.write_text(json.dumps(self.model), encoding="utf-8")
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts" / "source_artifacts.py"), "generate",
            "--model", str(model_path), "--output", str(design),
        ], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        before = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in design.iterdir()}
        source = ("const {validateEditableSources}=require('./generate');"
                  f"console.log(JSON.stringify(validateEditableSources({json.dumps(self.model)},"
                  f"{json.dumps(str(model_path))},{json.dumps(str(design))})));")
        result = subprocess.run(["node", "-e", source], cwd=ROOT / "renderer",
                                capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["sources"], True)
        after = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in design.iterdir()}
        self.assertEqual(before, after, "Source validation must never rewrite source artifacts.")
        mermaid = design / f"SA_{self.model['scenarioSlug']}.mmd"
        mermaid.write_text(mermaid.read_text(encoding="utf-8") + "\n%% changed after source gate\n", encoding="utf-8")
        result = self.generate(model_path, design)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Editable sources failed validation before presentation", result.stderr)
        self.assertFalse(list(design.glob(".layout-*.json")))
        self.assertFalse((design / "diagram-manifest.json").exists())
        self.assertFalse((design / "preview.html").exists())

    def test_impossible_content_fails_all_candidates_and_preserves_exact_diagnostics(self):
        design = self.work / "blocked" / "design"
        design.mkdir(parents=True)
        model = copy.deepcopy(self.model)
        model["components"][0]["description"] = "Required exceptionally verbose information. " * 150
        source = design / "design-model.json"
        source.write_text(json.dumps(model), encoding="utf-8")
        result = self.generate(source, design)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads((design / "composition-candidates-Balanced.json").read_text(encoding="utf-8"))
        self.assertEqual(report["validation"], "failed")
        self.assertIsNone(report["selected"])
        self.assertEqual(len(report["candidates"]), 3)
        self.assertTrue(all(candidate["issues"] for candidate in report["candidates"]))
        self.assertIn("Diagnostics preserved", result.stderr)
        self.assertFalse((design / "diagram-manifest.json").exists())

    @unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell"), "PowerShell unavailable")
    def test_svg_validator_rejects_changed_scoped_relationship_and_missing_gates(self):
        design = self.work / "tampered" / "design"
        design.mkdir(parents=True)
        for name in (f"SA_{self.model['scenarioSlug']}.svg", f"SD_{self.model['scenarioSlug']}.svg",
                     "diagram-manifest.json"):
            shutil.copy2(self.design / name, design / name)
        sa_path = design / f"SA_{self.model['scenarioSlug']}.svg"
        tree = ET.parse(sa_path)
        scope = next(e for e in tree.getroot().iter() if e.get("data-kind") == "control-annotation")
        scope.set("data-implementation-mode", "blocked")
        tree.write(sa_path, encoding="utf-8", xml_declaration=True)
        shell = shutil.which("pwsh") or shutil.which("powershell")
        command = [shell, "-NoProfile", "-File", str(ROOT / "scripts" / "Test-Diagrams.ps1"),
                   "-SolutionArchitecture", str(sa_path),
                   "-SequenceDiagram", str(design / f"SD_{self.model['scenarioSlug']}.svg"),
                   "-OutputPath", str(design / "validation-report.json")]
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads((design / "validation-report.json").read_text(encoding="utf-8-sig"))
        self.assertTrue(any("implementationMode" in issue or "blocked" in issue for issue in report["issues"]))
        shutil.copy2(self.design / sa_path.name, sa_path)
        manifest = copy.deepcopy(self.manifest)
        del manifest["layoutQuality"]["gates"]
        (design / "diagram-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        result = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        self.assertNotEqual(result.returncode, 0)
        report = json.loads((design / "validation-report.json").read_text(encoding="utf-8-sig"))
        self.assertTrue(any("mandatory numerical" in issue for issue in report["issues"]))


if __name__ == "__main__":
    unittest.main()
