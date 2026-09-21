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
function plan(input,profile='Balanced',family='story') {
  const p = composeArchitecture(input,PROFILES[profile],
    (c,w,hero,compact)=>prepareCard(c,w,t,hero,compact,{verified:true}),180,undefined,family);
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
        self.assertLessEqual(result["mainRowCount"], 2)
        self.assertLessEqual(result["width"], 2200, "Native text must remain readable at 1800px fit width.")
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

    def test_duplicate_channel_edges_do_not_strand_the_alternate_channel(self):
        result = self.run_node("""
const nodes=[component('user','actor'),component('teams','channel'),
  component('m365','channel'),component('agent','agent')];
const input=model(nodes,[edge('user','teams'),edge('user','m365'),
  edge('teams','agent'),edge('teams','agent'),edge('m365','agent'),edge('agent','teams','response')]);
console.log(JSON.stringify(plan(input)));
""")
        self.assertIn({"teams", "m365"}, [set(ids) for ids in result["columns"]])
        self.assertEqual(len(result["cards"]), 4)

    def test_three_families_have_distinct_geometry_without_changing_the_graph(self):
        result = self.run_node("""
const input=require('../tests/fixtures/procurement-reference-model.json');
const before=JSON.stringify(input);
const plans=['story','hub','boundary'].map(family=>plan(input,'Balanced',family));
console.log(JSON.stringify({plans,unchanged:before===JSON.stringify(input)}));
""")
        self.assertTrue(result["unchanged"])
        fingerprints = []
        for plan in result["plans"]:
            fingerprints.append([(card["id"], card["x"], card["y"]) for card in plan["cards"]])
            self.assertEqual(len(plan["cards"]), 14)
        self.assertEqual(len({json.dumps(value) for value in fingerprints}), 3)

    def test_primary_agent_hint_survives_an_upstream_agent_on_the_evidenced_path(self):
        result = self.run_node("""
const nodes=[component('user','actor'),component('entry-agent','agent'),
  {...component('primary-agent','agent'),visual_role:'primary'},component('action','tool')];
const input=model(nodes,[edge('user','entry-agent'),edge('entry-agent','primary-agent'),edge('primary-agent','action')]);
input.presentation={primary_agent_id:'primary-agent',primary_path:['user','entry-agent','primary-agent','action']};
console.log(JSON.stringify({story:plan(input),hub:plan(input,'Balanced','hub')}));
""")
        for family in ("story", "hub"):
            self.assertEqual([card["id"] for card in result[family]["cards"] if card["hero"]], ["primary-agent"])
        self.assertEqual(result["hub"]["spine"], ["user", "entry-agent", "primary-agent"])

    def test_target_width_is_applied_but_cannot_bypass_fit_width_readability(self):
        result = self.run_node("""
const input=model([component('user','actor'),component('agent','agent'),component('action','tool')],
  [edge('user','agent'),edge('agent','action')]);
input.presentation={target_width:1440};
const narrow=plan(input);
input.presentation.target_width=4000;
const clamped=plan(input);
console.log(JSON.stringify({narrow,clamped}));
""")
        self.assertLessEqual(result["narrow"]["width"], 1440)
        self.assertTrue(result["narrow"]["widthHint"]["applied"])
        self.assertFalse(result["narrow"]["widthHint"]["clamped"])
        self.assertLessEqual(result["clamped"]["width"], 2200)
        self.assertTrue(result["clamped"]["widthHint"]["clamped"])

    def test_visual_groups_and_cross_cutting_roles_preserve_every_component(self):
        result = self.run_node("""
const nodes=[component('user','actor'),component('agent','agent'),
  {...component('knowledge-a','knowledge'),visual_group:'Exact shared group'},
  {...component('knowledge-b','knowledge'),visualGroup:'Exact shared group'},
  {...component('control','tool'),visual_role:'cross-cutting'}];
const input=model(nodes,[edge('user','agent'),edge('agent','knowledge-a'),
  edge('agent','knowledge-b'),edge('control','agent')]);
const before=JSON.stringify(input);
console.log(JSON.stringify({layout:plan(input,'Balanced','boundary'),unchanged:before===JSON.stringify(input)}));
""")
        self.assertEqual(len(result["layout"]["cards"]), 5)
        self.assertTrue(result["unchanged"])
        self.assertEqual(next(card["role"] for card in result["layout"]["cards"] if card["id"] == "control"), "control")
        self.assertIn("Exact shared group", [heading["text"] for heading in result["layout"]["headings"]])

    def test_preferred_composition_changes_only_the_bounded_tie_break_order(self):
        result = self.run_node("""
const {compositionFamilies}=require('./composition');
console.log(JSON.stringify({
  hinted:compositionFamilies({presentation:{preferred_composition:'boundary'}}),
  invalid:compositionFamilies({presentation:{preferred_composition:'unknown'}})}));
""")
        self.assertEqual(result["hinted"], ["boundary", "story", "hub"])
        self.assertEqual(result["invalid"], ["story", "hub", "boundary"])


@unittest.skipUnless(POWERSHELL, "PowerShell is unavailable")
class AdaptiveRenderTests(unittest.TestCase):
    def test_varied_requirements_pass_the_real_generation_and_geometry_path(self):
        procurement = json.loads(FIXTURE.read_text(encoding="utf-8"))
        # This older visual fixture depicts grounding supply; the sequence makes the request explicit.
        # Keep the integration fixture consistent with the directed source contract.
        grounding = next(edge for edge in procurement["relationships"]
                         if edge["from"] == "sharepoint" and edge["to"] == "agent")
        grounding["from"], grounding["to"] = "agent", "sharepoint"
        grounding["style"] = "call"
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
                ], capture_output=True, text=True, timeout=1200, check=False)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                report = json.loads((design / "run-report.json").read_text(encoding="utf-8-sig"))
                self.assertEqual(report["structuralValidation"], "passed", report)
                sa = ET.parse(design / f"SA_{model['scenarioSlug']}.svg").getroot()
                self.assertFalse(any(e.get("data-kind") == "container" for e in sa.iter()))
                nodes = [e for e in sa.iter() if e.get("data-kind") == "node"]
                self.assertEqual({e.get("data-component-id") for e in nodes}, {c["id"] for c in model["components"]})
                self.assertEqual(len(nodes), len(model["components"]))
                expected = sorted(
                    (e["from"], e["to"], e["implementationMode"]) for e in model["relationships"]
                )
                actual = sorted(
                    (e.get("data-from"), e.get("data-to"), e.get("data-implementation-mode"))
                    for e in sa.iter() if e.get("data-kind") in {"connector", "control-annotation"}
                )
                self.assertEqual(actual, expected)
                self.assertTrue((design / f"SA_{model['scenarioSlug']}.png").is_file())
                preview = (design / "preview.html").read_text(encoding="utf-8")
                for source_name in (f"Design_{model['scenarioSlug']}.drawio",
                                    f"SA_{model['scenarioSlug']}.mmd", f"SD_{model['scenarioSlug']}.mmd"):
                    self.assertTrue((design / source_name).is_file())
                    self.assertIn(f'href="{source_name}"', preview)
                manifest = json.loads((design / "diagram-manifest.json").read_text(encoding="utf-8-sig"))
                self.assertIn(manifest["layoutQuality"]["composition"]["strategy"],
                              {"relationship-driven-story", "relationship-driven-hub", "relationship-driven-boundary"})
                self.assertEqual(manifest["layoutQuality"]["validation"], "passed")
                self.assertGreater(manifest["layoutQuality"]["score"], 0)


if __name__ == "__main__":
    unittest.main()
