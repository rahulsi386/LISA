"""Pins the shared review visual system (SDM Architecture Review benchmark) and its machine gates."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
import unittest
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "procurement-reference-model.json"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
ET.register_namespace("", "http://www.w3.org/2000/svg")
ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
BOUNDARIES = {
    "requester": "user", "teams": "microsoft-365-tenant", "m365": "microsoft-365-tenant",
    "sharepoint": "microsoft-365-tenant", "powerbi": "microsoft-365-tenant",
    "agent": "power-platform-environment", "flow": "power-platform-environment",
    "dataverse": "power-platform-environment", "erp": "external-system", "fabric": "azure-subscription",
    "entra": "microsoft-365-tenant", "platform": "power-platform-environment", "monitor": "azure-subscription",
    "finance-controls": "external-system",
}
TYPES = {
    ("requester", "entra"): "authenticates", ("agent", "sharepoint"): "retrieves",
    ("flow", "erp"): "writes", ("agent", "flow"): "invokes",
}


def node(source: str) -> dict:
    result = subprocess.run(["node", "-e", source], cwd=ROOT / "renderer",
                            capture_output=True, text=True, timeout=60, check=False)
    if result.returncode:
        raise AssertionError(result.stderr or result.stdout)
    return json.loads(result.stdout)


class StyleTokenTests(unittest.TestCase):
    def test_palette_type_scale_and_canvas_targets_are_pinned(self):
        tokens = node("console.log(JSON.stringify(require('./style').TOKENS))")
        self.assertEqual(tokens["palette"]["teal"], {"line": "#087F82", "fill": "#EEF9F7", "border": "#80BFBB"})
        self.assertEqual(tokens["palette"]["blue"], {"line": "#285FC7", "fill": "#EFF4FE", "border": "#9CB6EB"})
        self.assertEqual(tokens["palette"]["amber"], {"line": "#9A5D08", "fill": "#FFF7E8", "border": "#D8B671"})
        self.assertEqual(tokens["palette"]["slate"], {"line": "#65778D", "fill": "#F4F7FA", "border": "#B7C5D4"})
        self.assertEqual(tokens["palette"]["violet"], {"line": "#7250AC", "fill": "#F6F2FB", "border": "#BCA8D5"})
        self.assertEqual(tokens["palette"]["green"], {"line": "#237646", "fill": "#EDF8F0", "border": "#93BF9E"})
        self.assertEqual(tokens["palette"]["red"], {"line": "#A63D37", "fill": "#FFF2F0", "border": "#D7A39F"})
        self.assertEqual(tokens["zone"]["stroke"], "#CBD7E3")
        self.assertEqual(tokens["dash"], {"response": "7 5", "pending": "2 5", "zone": "5 5", "lifeline": "4 6"})
        self.assertEqual(tokens["stroke"]["edge"], 1.8)
        self.assertEqual(tokens["stroke"]["accent"], 4)
        self.assertGreaterEqual(min(value["size"] for value in tokens["type"].values()), 11)
        # 19px engineering names stay >=15px when a 2200px canvas is fitted to 1800px.
        self.assertGreaterEqual(tokens["type"]["nodeTitle"]["size"] * 1800 / 2200, 15)
        self.assertGreaterEqual(tokens["type"]["heroTitle"]["size"] / tokens["type"]["nodeTitle"]["size"], 1.15)
        self.assertEqual(tokens["canvasTarget"], {"minimumWidth": 1280, "maximumWidth": 2200, "landscapeAspect": 1.25})

    def test_every_line_colour_meets_text_contrast_on_white_and_tone_fills(self):
        result = node("""
const {PALETTE}=require('./style');
const lum=c=>c.match(/[0-9a-f]{2}/gi).map(x=>parseInt(x,16)/255)
  .map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
const ratio=(a,b)=>(Math.max(lum(a),lum(b))+.05)/(Math.min(lum(a),lum(b))+.05);
console.log(JSON.stringify(Object.fromEntries(Object.entries(PALETTE).map(([k,v])=>[k,
  Math.min(ratio(v.line,'#FFFFFF'),ratio(v.line,v.fill))]))));
""")
        for tone, contrast in result.items():
            self.assertGreaterEqual(contrast, 4.2, tone)

    def test_link_meaning_follows_relationship_type_before_target_kind(self):
        result = node("""
const {linkMeaning,linkPattern}=require('./style');
const byId=new Map([['k',{kind:'knowledge'}],['f',{kind:'flow'}],['e',{kind:'security'}],['a',{kind:'agent'}]]);
console.log(JSON.stringify({
  retrieves:linkMeaning({to:'a',relationshipType:'retrieves'},byId),
  authenticates:linkMeaning({to:'a',relationshipType:'authenticates'},byId),
  invokesFlow:linkMeaning({to:'f',relationshipType:'invokes'},byId),
  invokesAgent:linkMeaning({to:'a',relationshipType:'invokes'},byId),
  legacyKnowledge:linkMeaning({to:'k',style:'call'},byId),
  legacyIdentity:linkMeaning({to:'e',style:'call'},byId),
  blocked:linkMeaning({to:'a',implementationMode:'blocked',relationshipType:'retrieves'},byId),
  groundedResponse:linkMeaning({from:'k',to:'a',style:'response',relationshipType:'responds'},byId),
  agentResponse:linkMeaning({from:'a',to:'f',style:'response',relationshipType:'responds'},byId),
  response:linkPattern({style:'response',implementationMode:'real'}),
  simulated:linkPattern({style:'call',implementationMode:'simulated'}),
  call:linkPattern({style:'call',implementationMode:'real'})}));
""")
        self.assertEqual(result, {
            "retrieves": "evidence", "authenticates": "identity", "invokesFlow": "action", "invokesAgent": "query",
            "legacyKnowledge": "evidence", "legacyIdentity": "identity", "blocked": "blocked",
            "groundedResponse": "evidence", "agentResponse": "query",
            "response": "7 5", "simulated": "2 5", "call": "",
        })

    def test_conformance_gate_rejects_colours_sizes_and_strokes_outside_the_tokens(self):
        result = node("""
const {styleConformance}=require('./style');
console.log(JSON.stringify({
  clean:styleConformance('<svg><defs><path fill="#123456"/></defs><rect fill="#EEF9F7" stroke="#80BFBB" stroke-width="1.2"/><text font-size="14" fill="#17273D">x</text></svg>'),
  dirty:styleConformance('<svg><rect fill="#FF00FF" stroke-width="3"/><text font-size="15">x</text></svg>')}));
""")
        self.assertEqual(result["clean"]["validation"], "passed")
        self.assertEqual(result["dirty"]["validation"], "failed")
        self.assertEqual(len(result["dirty"]["issues"]), 3)


class ReferenceStyleRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = ROOT / "tests" / f".reference-style-{uuid.uuid4().hex}"
        cls.design = cls.work / "design"
        cls.design.mkdir(parents=True)
        cls.addClassCleanup(shutil.rmtree, cls.work, ignore_errors=True)
        model = json.loads(FIXTURE.read_text(encoding="utf-8"))
        for component in model["components"]:
            component["deploymentBoundary"] = BOUNDARIES[component["id"]]
        for index, edge in enumerate(model["relationships"]):
            edge["id"] = f"rel-{index + 1:02}"
            if (edge["from"], edge["to"]) in TYPES:
                edge["relationshipType"] = TYPES[(edge["from"], edge["to"])]
        model["sequence"][9]["fragment"] = "alt accepted"
        model["sequence"][10]["fragment"] = "alt accepted"
        cls.model = model
        path = cls.design / "design-model.json"
        path.write_text(json.dumps(model), encoding="utf-8")
        result = subprocess.run([
            "node", str(ROOT / "renderer" / "generate.js"), "--model", str(path), "--output", str(cls.design),
            "--icons", str(ROOT / "resources" / "icon-manifest.json"),
            "--references", str(ROOT / "resources" / "reference-manifest.json"), "--profile", "Balanced",
        ], cwd=ROOT, capture_output=True, text=True, timeout=420, check=False)
        if result.returncode:
            raise AssertionError(result.stderr + result.stdout)
        cls.manifest = json.loads((cls.design / "diagram-manifest.json").read_text(encoding="utf-8"))
        slug = model["scenarioSlug"]
        cls.sa = ET.parse(cls.design / f"SA_{slug}.svg").getroot()
        cls.sd = ET.parse(cls.design / f"SD_{slug}.svg").getroot()
        cls.ba = ET.parse(cls.design / f"BA_{slug}.svg").getroot()

    @staticmethod
    def texts(element) -> list[str]:
        return ["".join(e.itertext()) for e in element.iter() if e.tag.endswith("text")]

    def test_all_three_diagrams_pass_style_conformance_and_record_the_benchmark(self):
        style = self.manifest["style"]
        self.assertEqual(style["benchmark"], "SDM Intelligent Operations Architecture Review")
        self.assertEqual(style["conformance"], {"business": "passed", "architecture": "passed", "sequence": "passed"})
        gate = next(g for g in self.manifest["layoutQuality"]["gates"] if g["name"] == "style-conformance")
        self.assertTrue(gate["passed"])

    def test_multi_boundary_design_selects_dashed_zones_that_enclose_their_members(self):
        quality = self.manifest["layoutQuality"]
        self.assertEqual(quality["composition"]["family"], "boundary")
        zones = [e for e in self.sa.iter() if e.get("data-kind") == "zone"]
        self.assertEqual({e.get("data-name") for e in zones},
                         {"user", "microsoft-365-tenant", "power-platform-environment", "external-system", "azure-subscription"})
        nodes = {e.get("data-component-id"): e for e in self.sa.iter() if e.get("data-kind") == "node"}
        box = lambda e: tuple(float(e.get(k)) for k in ("data-x", "data-y", "data-width", "data-height"))
        for zone in zones:
            zx, zy, zw, zh = box(zone)
            self.assertEqual(zone.find("{http://www.w3.org/2000/svg}rect").get("stroke-dasharray"), "5 5")
            for member in json.loads(zone.get("data-components")):
                self.assertEqual(nodes[member].get("data-deployment-boundary"), zone.get("data-name"))
                x, y, w, h = box(nodes[member])
                self.assertTrue(zx < x and zy < y and x + w < zx + zw and y + h < zy + zh, member)
        headings = " ".join(self.texts(self.sa))
        self.assertIn("POWER PLATFORM ENVIRONMENT", headings)

    def test_cards_carry_codes_treatments_and_accent_bars(self):
        codes = self.manifest["componentCodes"]
        self.assertEqual(codes["requester"], "C01")
        self.assertEqual(len(set(codes.values())), len(self.model["components"]))
        for component in self.model["components"]:
            element = next(e for e in self.sa.iter() if e.get("data-component-id") == component["id"]
                           and e.get("data-kind") == "node")
            visible = self.texts(element)
            self.assertIn(codes[component["id"]], visible)
            accent = [r for r in element.iter() if r.tag.endswith("rect") and r.get("width") == "4"]
            self.assertEqual(len(accent), 1, component["id"])

    def test_relationships_show_short_codes_and_meaning_colours(self):
        codes = self.manifest["relationshipCodes"]
        connectors = [e for e in self.sa.iter() if e.get("data-kind") == "connector"]
        labels = {e.get("data-owner"): " ".join(self.texts(e)) for e in self.sa.iter() if e.get("data-kind") == "connector-label"}
        for connector in connectors:
            self.assertEqual(connector.get("data-code"), codes[connector.get("data-id")])
            self.assertTrue(labels[connector.get("data-id")].startswith(codes[connector.get("data-id")] + " · "))
        meanings = {e.get("data-id"): e.get("data-meaning") for e in connectors}
        self.assertEqual(meanings["rel-08"], "evidence")
        self.assertEqual(meanings["rel-05"], "action")
        control = next(e for e in self.sa.iter() if e.get("data-kind") == "control-annotation")
        self.assertIn("R13", "".join(control.itertext()))
        self.assertTrue(any(e.get("data-kind") == "control-band" for e in self.sa.iter()))

    def test_sequence_has_numbered_rail_compact_lanes_and_toned_branch_bands(self):
        markers = [e for e in self.sd.iter() if e.get("data-kind") == "step-marker"]
        self.assertEqual([m.get("data-order") for m in markers], [str(i) for i in range(1, len(self.model["sequence"]) + 1)])
        for marker in markers:
            circle = next(e for e in marker.iter() if e.tag.endswith("circle"))
            self.assertEqual(circle.get("cx"), "34")
        lifelines = [e for e in self.sd.iter() if e.get("data-kind") == "lifeline"]
        for lifeline in lifelines:
            self.assertLessEqual(float(lifeline.get("data-width")), 220)
            self.assertLessEqual(float(lifeline.get("data-height")), 110)
        fragment = next(e for e in self.sd.iter() if e.get("data-kind") == "fragment")
        self.assertEqual(fragment.get("data-tone"), "green")
        self.assertIn("ALT ACCEPTED", " ".join(self.texts(fragment)))
        meanings = {e.get("data-label"): e.get("data-meaning") for e in self.sd.iter() if e.get("data-kind") == "message"}
        self.assertEqual(meanings["Authenticate"], "identity")
        self.assertEqual(meanings["Retrieve approved policy"], "evidence")
        self.assertEqual(meanings["Validate and create the requisition"], "action")

    def test_canvas_proportions_stay_presentation_ready(self):
        size = lambda root: [float(v) for v in root.get("viewBox").split()[2:]]
        ba_w, ba_h = size(self.ba)
        sa_w, sa_h = size(self.sa)
        sd_w, _ = size(self.sd)
        self.assertGreaterEqual(ba_w, 1600)
        self.assertLessEqual(ba_h / ba_w, 1.0, "The leadership view must stay landscape.")
        self.assertTrue(1280 <= sa_w <= 2200)
        self.assertLessEqual(sa_h / sa_w, 1.4)
        self.assertGreaterEqual(sd_w, 1920)

    @unittest.skipUnless(POWERSHELL, "PowerShell is required for SVG validation")
    def test_structural_validation_accepts_zones_and_rejects_an_intruding_card(self):
        slug = self.model["scenarioSlug"]
        command = lambda sa: subprocess.run([
            POWERSHELL, "-NoProfile", "-File", str(ROOT / "scripts" / "Test-Diagrams.ps1"),
            "-SolutionArchitecture", str(sa), "-SequenceDiagram", str(self.design / f"SD_{slug}.svg"),
            "-OutputPath", str(self.design / "validation.json"),
        ], capture_output=True, text=True, timeout=300, check=False)
        self.assertEqual(command(self.design / f"SA_{slug}.svg").returncode, 0,
                         (self.design / "validation.json").read_text(encoding="utf-8-sig"))
        tampered = copy.deepcopy(self.sa)
        zone = next(e for e in tampered.iter() if e.get("data-kind") == "zone" and e.get("data-name") == "user")
        zone.set("data-components", json.dumps(["requester", "agent"]))
        path = self.design / f"SA_{slug}.svg"
        original = path.read_bytes()
        try:
            ET.ElementTree(tampered).write(path, encoding="utf-8", xml_declaration=False)
            self.assertNotEqual(command(path).returncode, 0)
            report = json.loads((self.design / "validation.json").read_text(encoding="utf-8-sig"))
            self.assertTrue(any("outside zone" in issue for issue in report["issues"]), report["issues"])
        finally:
            path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
