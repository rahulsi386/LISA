from __future__ import annotations

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "procurement-reference-model.json"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")
NODE_SETUP = """
const {composeArchitecture} = require('./composition');
const {prepareCard, PROFILES} = require('./generate');
const {Typography} = require('./typography');
const t = new Typography();
function component(id,kind,layer) {
  return {id,name:id,kind,layer:layer || (kind==='actor'?'users':kind==='channel'?'channels':'agent-platform'),
    description:'An evidenced component.',implementationStatus:'existing',buildOwner:'customer',
    pocScope:'included',productionStatus:'ready'};
}
const edge = (from,to,style='call') => ({from,to,style,label:'Evidenced interaction',implementationMode:'real'});
function model(components,relationships) {
  return {components,relationships,sequence:relationships.slice(0,6)};
}
function plan(input,profile='Balanced') {
  const p = composeArchitecture(input,PROFILES[profile],
    (c,w,hero,compact)=>prepareCard(c,w,t,hero,compact,{verified:true}),180);
  return {...p,cards:p.cards.map(c=>({id:c.id,x:c.x,y:c.y,width:c.width,height:c.height,
    role:c.storyRole,kind:c.component.kind,hero:c.hero}))};
}
"""


class AdaptiveCompositionTests(unittest.TestCase):
    def run_node(self, source: str) -> dict:
        result = subprocess.run(
            ["node", "-e", NODE_SETUP + source], cwd=ROOT / "renderer",
            capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def test_procurement_uses_parallel_channels_and_an_unboxed_main_path(self):
        result = self.run_node("""
const input = require('../tests/fixtures/procurement-reference-model.json');
console.log(JSON.stringify(plan(input)));
""")
        self.assertEqual(result["spine"][0], "requester")
        self.assertEqual(result["spine"][-3:], ["agent", "flow", "erp"])
        self.assertIn(set(["teams", "m365"]), [set(ids) for ids in result["columns"]])
        self.assertEqual(len(result["cards"]), 14)
        self.assertEqual(result["mainRowCount"], 1)
        roles = {card["id"]: card["role"] for card in result["cards"]}
        for identity in ("sharepoint", "dataverse", "fabric", "powerbi"):
            self.assertEqual(roles[identity], "supporting")
        self.assertEqual(sum(value == "control" for value in roles.values()), 4)
        cards = {card["id"]: card for card in result["cards"]}
        self.assertLess(cards["fabric"]["x"], cards["powerbi"]["x"])
        self.assertEqual(cards["fabric"]["y"], cards["powerbi"]["y"])

    def test_same_components_with_different_dependencies_get_different_compositions(self):
        result = self.run_node("""
const nodes = [component('user','actor'),component('agent','agent'),
  component('flow','flow'),component('erp','external')];
const direct = plan(model(nodes,[edge('user','agent'),edge('agent','erp'),edge('agent','flow')]));
const chained = plan(model(nodes,[edge('user','agent'),edge('agent','flow'),edge('flow','erp')]));
console.log(JSON.stringify({direct,chained}));
""")
        self.assertEqual(result["direct"]["spine"], ["user", "agent", "erp"])
        self.assertEqual(result["chained"]["spine"], ["user", "agent", "flow", "erp"])
        self.assertEqual(len(result["direct"]["cards"]), len(result["chained"]["cards"]))

    def test_retrieval_has_no_placeholder_automation_or_business_system_stage(self):
        result = self.run_node("""
const nodes = [component('user','actor'),component('agent','agent'),
  component('policies','knowledge'),component('catalog','knowledge')];
console.log(JSON.stringify(plan(model(nodes,[edge('user','agent'),
  edge('agent','policies'),edge('agent','catalog')]))));
""")
        self.assertEqual(result["spine"], ["user", "agent"])
        self.assertEqual(len(result["columns"]), 2)
        self.assertEqual(result["width"], 1280)
        self.assertEqual(len(result["cards"]), 4)

    def test_autonomous_integration_does_not_invent_an_agent_or_channel(self):
        result = self.run_node("""
const nodes = [component('source','external','data-integration'),
  component('worker','integration','data-integration'),component('target','external','data-integration')];
console.log(JSON.stringify(plan(model(nodes,[edge('source','worker'),
  edge('worker','target'),edge('target','worker','response')]))));
""")
        self.assertEqual(result["spine"], ["source", "worker", "target"])
        self.assertFalse(any(card["hero"] for card in result["cards"]))

    def test_conversational_path_wins_over_a_direct_sequence_shortcut(self):
        result = self.run_node("""
const nodes = [component('user','actor'),component('teams','channel'),component('agent','agent')];
console.log(JSON.stringify(plan(model(nodes,[edge('user','agent'),
  edge('user','teams'),edge('teams','agent')]))));
""")
        self.assertEqual(result["spine"], ["user", "teams", "agent"])

    def test_multiple_agents_cycles_and_disconnected_requirements_are_not_dropped(self):
        result = self.run_node("""
const nodes = [component('user','actor'),component('primary','agent'),component('specialist','agent'),
  component('action','tool'),component('isolated','knowledge')];
console.log(JSON.stringify(plan(model(nodes,[edge('user','primary'),
  edge('primary','specialist'),edge('specialist','action'),edge('action','primary')]))));
""")
        self.assertEqual(result["spine"], ["user", "primary", "specialist", "action"])
        self.assertEqual(len(result["cards"]), 5)
        self.assertEqual([card["id"] for card in result["cards"] if card["hero"]], ["primary"])
        self.assertEqual(next(card["role"] for card in result["cards"] if card["id"] == "isolated"), "supporting")

    def test_large_graph_wraps_without_overlap_or_component_loss(self):
        result = self.run_node("""
const nodes = Array.from({length:30},(_,i)=>component('n'+i,i===0?'agent':'tool'));
const edges = nodes.slice(1).map((c,i)=>edge('n'+i,c.id));
const p = plan(model(nodes,edges));
const overlaps = p.cards.flatMap((a,i)=>p.cards.slice(i+1).filter(b=>
  a.x<b.x+b.width && a.x+a.width>b.x && a.y<b.y+b.height && a.y+a.height>b.y));
console.log(JSON.stringify({count:p.cards.length,mainRows:p.mainRowCount,
  supportRows:p.supportRowCount,overlaps:overlaps.length,
  bounded:p.cards.every(c=>c.x>=48 && c.x+c.width<=p.width-48 && c.y+c.height<p.bottom),
  deterministic:JSON.stringify(p)===JSON.stringify(plan(model(nodes,edges)))}));
""")
        self.assertEqual(result["count"], 30)
        self.assertGreater(result["mainRows"], 1)
        self.assertGreater(result["supportRows"], 1)
        self.assertEqual(result["overlaps"], 0)
        self.assertTrue(result["bounded"])
        self.assertTrue(result["deterministic"])

    def test_dense_hub_sizes_the_canvas_from_supporting_requirements(self):
        result = self.run_node("""
const small = [component('agent','agent'),component('policy','knowledge')];
const large = [component('agent','agent'),
  ...Array.from({length:20},(_,i)=>component('policy'+i,'knowledge'))];
const smallPlan = plan(model(small,[edge('agent','policy')]));
const largePlan = plan(model(large,large.slice(1).map(c=>edge('agent',c.id))));
console.log(JSON.stringify({small:smallPlan.width,large:largePlan.width,
  columns:largePlan.columns.length,count:largePlan.cards.length}));
""")
        self.assertGreater(result["large"], result["small"])
        self.assertEqual(result["columns"], 1)
        self.assertEqual(result["count"], 21)

    def test_return_routes_get_space_below_stage_headings(self):
        result = self.run_node("""
const nodes = [component('flow','flow'),component('erp','external')];
const forward = plan(model(nodes,[edge('flow','erp')]));
const returning = plan(model(nodes,[edge('flow','erp'),edge('erp','flow','optional')]));
console.log(JSON.stringify({before:forward.cards[0].y,after:returning.cards[0].y,
  headingsUnchanged:forward.headings[0].y===returning.headings[0].y}));
""")
        self.assertGreaterEqual(result["after"] - result["before"], 67)
        self.assertTrue(result["headingsUnchanged"])


@unittest.skipUnless(POWERSHELL, "PowerShell is unavailable")
class AdaptiveRenderTests(unittest.TestCase):
    def test_varied_requirements_pass_the_real_generation_and_geometry_path(self):
        procurement = json.loads(FIXTURE.read_text(encoding="utf-8"))
        retrieval = copy.deepcopy(procurement)
        keep = {"requester", "teams", "agent", "sharepoint", "dataverse", "entra"}
        retrieval["components"] = [c for c in retrieval["components"] if c["id"] in keep]
        retrieval["relationships"] = [e for e in retrieval["relationships"] if e["from"] in keep and e["to"] in keep]
        retrieval["sequence"] = retrieval["sequence"][:9]
        retrieval["scenarioSlug"] = "Retrieval"
        retrieval["title"] = "Procurement policy and draft assistant"
        retrieval["summary"] = "Grounded policy guidance and draft state; no ERP submission capability is included."
        integration = copy.deepcopy(procurement)
        keep = {"flow", "erp", "fabric", "powerbi", "monitor"}
        integration["components"] = [c for c in integration["components"] if c["id"] in keep]
        integration["relationships"] = [e for e in integration["relationships"] if e["from"] in keep and e["to"] in keep]
        integration["sequence"] = [e for e in integration["sequence"] if e["from"] in keep and e["to"] in keep]
        integration["scenarioSlug"] = "Integration"
        integration["title"] = "Procurement integration and insights"
        integration["summary"] = "Controlled ERP integration and governed analytics without a conversational channel."
        for model in (procurement, retrieval, integration):
            with self.subTest(scenario=model["scenarioSlug"]), tempfile.TemporaryDirectory(
                prefix=".adaptive-", dir=ROOT / "tests"
            ) as temporary:
                design = Path(temporary) / "design"
                design.mkdir()
                model_path = design / "design-model.json"
                model_path.write_text(json.dumps(model), encoding="utf-8")
                result = subprocess.run([
                    POWERSHELL, "-NoProfile", "-File", str(ROOT / "scripts" / "Invoke-FastPath.ps1"),
                    "-ModelPath", str(model_path), "-TempOutputPath", temporary,
                ], capture_output=True, text=True, timeout=180, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads((design / "run-report.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(report["structuralValidation"], "passed", report)
                sa = ET.parse(design / f"SA_{model['scenarioSlug']}.svg").getroot()
                self.assertFalse(any(e.get("data-kind") == "container" for e in sa.iter()))
                nodes = [e for e in sa.iter() if e.get("data-kind") == "node"]
                self.assertEqual({e.get("data-component-id") for e in nodes}, {c["id"] for c in model["components"]})
                self.assertEqual(len(nodes), len(model["components"]))
                controls = {c["id"] for c in model["components"] if c["layer"] in {"governance", "monitoring"}}
                expected = sorted(
                    (e["from"], e["to"], e["implementationMode"]) for e in model["relationships"]
                    if e["from"] not in controls and e["to"] not in controls
                )
                actual = sorted(
                    (e.get("data-from"), e.get("data-to"), e.get("data-implementation-mode"))
                    for e in sa.iter() if e.get("data-kind") == "connector"
                )
                self.assertEqual(actual, expected)
                self.assertTrue((design / f"SA_{model['scenarioSlug']}.png").is_file())
                manifest = json.loads((design / "diagram-manifest.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(manifest["layoutQuality"]["composition"]["strategy"], "relationship-driven-story")


if __name__ == "__main__":
    unittest.main()
