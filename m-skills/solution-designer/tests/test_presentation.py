from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


RENDERER = Path(__file__).resolve().parents[1] / "renderer"


class PresentationTests(unittest.TestCase):
    def run_node(self, source: str) -> dict:
        result = subprocess.run(
            ["node", "-e", source], cwd=RENDERER, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def test_wrapping_uses_font_metrics_without_losing_long_names(self):
        result = self.run_node(
            """
const {Typography} = require('./typography');
const t = new Typography();
const source = 'Wide WWW characters and ExtremelyLongUnbrokenProcurementIdentifierWithoutAnyAbbreviation';
const lines = t.wrap(source, 176, 16, 600);
console.log(JSON.stringify({
    fits: lines.every(line => t.measure(line,16,600).width <= 173),
    preserved: lines.join('').replace(/\\s/g,'') === source.replace(/\\s/g,''),
    variedGlyphWidths: t.measure('WWW',16).width > t.measure('iii',16).width,
    lines: lines.length
}));
"""
        )
        self.assertTrue(result["fits"])
        self.assertTrue(result["preserved"])
        self.assertTrue(result["variedGlyphWidths"])
        self.assertGreater(result["lines"], 2)

    def test_card_content_grows_without_fixed_description_offsets(self):
        result = self.run_node(
            """
const {Typography} = require('./typography');
const {prepareCard} = require('./generate');
const t = new Typography();
const component = {id:'agent', name:'Agent', kind:'agent', implementationStatus:'configure',
    description:'Grounded answers.', members:[], buildOwner:'agent-builder',
    pocScope:'included', productionStatus:'requires-hardening'};
const icon = {verified:true};
const short = prepareCard(component, 310, t, true, false, icon);
const long = prepareCard({...component,
    name:'Enterprise procurement contract management and financial authorization agent',
    description:'Every required capability must remain visible. '.repeat(8),
    members:['A fully named external integration owned by the procurement operations team']},
    310,t,true,false,icon);
console.log(JSON.stringify({
    grows: long.height > short.height,
    descriptionBelowTitle: long.descriptionY > 44 + (long.title.length-1)*long.titleLeading,
    metadataBelowMembers: long.metadataY > long.membersY,
    noEllipsis: [...long.title,...long.description].every(line => !line.endsWith('...'))
}));
"""
        )
        self.assertTrue(all(result.values()), result)

    def test_sequence_long_names_phases_and_last_lifeline_self_call(self):
        result = self.run_node(
            """
const fs = require('fs');
const {Typography} = require('./typography');
const {sequenceDiagram} = require('./generate');
const {Resvg} = require('@resvg/resvg-js');
const {fontOptions} = require('./typography');
const names = ['Requester','Microsoft Teams','Procurement agent','Policy knowledge',
    'Finance approver','Request workflow','ERP integration',
    'Long enterprise procurement transaction reconciliation service'];
const components = names.map((name,index) => ({
    id:'n'+index,name,kind:index===2?'agent':'tool',implementationStatus:'configure'
}));
const sequence = components.slice(1).map((c,index) => ({
    from:'n'+index,to:c.id,label:'Perform the explicitly authorized procurement action',
    type:'call',implementationMode:'real',phase:index<3?'Intake and policy analysis':'Human decision and execution',
    fragment:index>=4?'alt [policy permits this action]':null
}));
sequence.push({from:'n7',to:'n7',label:'Reconcile an uncertain transaction outcome without creating a duplicate',
    type:'self',implementationMode:'real',phase:'Reconciliation'});
sequence.push({from:'n7',to:'n0',label:'Simulated: no data sent to the external financial system',
    type:'response',implementationMode:'simulated',phase:'Response'});
const model = {title:'Professional sequence fixture',summary:'Explicit participants, phases and failure-safe handling.',
    complexity:'High',coverage:{nativeBuildPercent:70,pocDemonstrationPercent:90},
    components,sequence,relationships:[]};
const uri = 'data:image/svg+xml;base64,'+fs.readFileSync('../resources/icons/copilot-studio.svg').toString('base64');
const icons = new Map(components.map(c=>[c.id,{uri,verified:true}]));
const result = sequenceDiagram(model,icons,new Typography(),'Balanced');
const bounds = result.svg.match(/viewBox="0 0 (\\d+) (\\d+)"/).slice(1).map(Number);
const texts = result.drawing.texts;
const overlaps = texts.flatMap((a,i)=>texts.slice(i+1).filter(b=>
    a.x < b.x+b.width-.5 && a.x+a.width > b.x+.5 &&
    a.y < b.y+b.height-.5 && a.y+a.height > b.y+.5).map(b=>[a.text,b.text]));
const image = new Resvg(result.svg,{font:fontOptions,logLevel:'error'}).render();
const lastSelfRoute = result.svg.match(/data-kind="message" data-from="n7" data-to="n7"[^>]*data-route="([^"]+)"/)[1]
    .split(';').map(point=>point.split(',').map(Number));
console.log(JSON.stringify({
    allTextInsideCanvas:texts.every(t=>t.x>=0 && t.y>=0 && t.x+t.width<=bounds[0] && t.y+t.height<=bounds[1]),
    overlaps,
    phases:(result.svg.match(/data-kind="phase"/g)||[]).length,
    fragments:(result.svg.match(/data-kind="fragment"/g)||[]).length,
    fontEmbedded:result.svg.includes('data:font/ttf;base64,'),
    fixedArrowheads:result.svg.includes('markerUnits="userSpaceOnUse"'),
    matchingSimulationArrowhead:result.svg.includes('fill="#08788F"'),
    lastSelfTurnsInward:lastSelfRoute[1][0] < lastSelfRoute[0][0],
    renderedWidth:image.width,
    allFontsReadable:[...result.svg.matchAll(/font-size="([\\d.]+)"/g)].every(m=>Number(m[1])>=11)
}));
"""
        )
        self.assertTrue(result["allTextInsideCanvas"])
        self.assertEqual(result["overlaps"], [])
        self.assertEqual(result["phases"], 4)
        self.assertEqual(result["fragments"], 1)
        self.assertTrue(result["fontEmbedded"])
        self.assertTrue(result["fixedArrowheads"])
        self.assertTrue(result["matchingSimulationArrowhead"])
        self.assertTrue(result["lastSelfTurnsInward"])
        self.assertTrue(result["allFontsReadable"])
        self.assertGreaterEqual(result["renderedWidth"], 1920)

    def test_small_text_palette_has_accessible_canvas_contrast(self):
        result = self.run_node(
            """
const {THEME} = require('./generate');
function luminance(color) {
    const values = color.match(/[0-9a-f]{2}/gi).map(x=>parseInt(x,16)/255)
        .map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);
    return values[0]*.2126 + values[1]*.7152 + values[2]*.0722;
}
const colors = ['ink','muted','blue','green','cyan','amber','gray','red','purple'];
console.log(JSON.stringify(Object.fromEntries(colors.map(key=>[
    key, (luminance(THEME.background)+.05)/(luminance(THEME[key])+.05)
]))));
"""
        )
        for color, contrast in result.items():
            self.assertGreaterEqual(contrast, 4.5, color)

    def test_runtime_and_boundary_metadata_are_compact_without_losing_exact_names(self):
        result = self.run_node("""
const {Typography}=require('./typography');
const {prepareCard}=require('./generate');
const c={id:'canonical',name:'Exact service name',kind:'tool',implementationStatus:'simulate',
  buildOwner:'external-team',pocScope:'represented',productionStatus:'gap',
  description:'Perform the exact approved role. Runtime: Exact hosting runtime. Boundary: Exact tenant.',
  members:['Exact hosting runtime','Extra canonical inventory member']};
const card=prepareCard(c,340,new Typography(),false,false,{verified:true});
console.log(JSON.stringify({description:card.description.join(' '),details:card.details,
  represented:card.representedMembers,members:card.members.map(m=>m.name),metadata:card.metadata.join(' ')}));
""")
        self.assertEqual(result["description"], "Perform the exact approved role.")
        self.assertIn("Exact hosting runtime", result["represented"])
        self.assertEqual(result["members"], ["Extra canonical inventory member"])
        self.assertEqual(result["details"][1]["value"], "Exact tenant")
        for value in ("Simulated", "External team", "PoC represented", "Production gap", "canonical"):
            self.assertIn(value, result["metadata"])

    def test_single_message_phases_use_compact_labels_not_full_width_panels(self):
        result = self.run_node("""
const fs=require('fs');
const {Typography}=require('./typography');
const {sequenceDiagram}=require('./generate');
const model=require('../tests/fixtures/procurement-reference-model.json');
model.sequence=model.sequence.slice(0,4).map((m,i)=>({...m,phase:'Exact phase '+i,fragment:null}));
const uri='data:image/svg+xml;base64,'+fs.readFileSync('../resources/icons/copilot-studio.svg').toString('base64');
const icons=new Map(model.components.map(c=>[c.id,{verified:true,uri}]));
const result=sequenceDiagram(model,icons,new Typography(),'Balanced');
console.log(JSON.stringify({quality:result.quality,compact:(result.svg.match(/data-treatment="compact-label"/g)||[]).length}));
""")
        self.assertEqual(result["compact"], 4)
        self.assertEqual(result["quality"]["validation"], "passed")
        self.assertEqual(result["quality"]["fullWidthSingleMessagePanels"], 0)

    def test_sequence_preserves_canonical_ids_and_collision_safe_legacy_occurrences(self):
        result = self.run_node("""
const fs=require('fs');
const {Typography}=require('./typography');
const {sequenceDiagram}=require('./generate');
const model=require('../tests/fixtures/procurement-reference-model.json');
model.sequence=model.sequence.slice(0,3).map((m,i)=>{
  const message={...m}; delete message.id;
  if(i===1) message.id='sequence-0001';
  if(i===2) message.id='exact-canonical-sequence';
  return message;
});
const uri='data:image/svg+xml;base64,'+fs.readFileSync('../resources/icons/copilot-studio.svg').toString('base64');
const icons=new Map(model.components.map(c=>[c.id,{verified:true,uri}]));
const result=sequenceDiagram(model,icons,new Typography(),'Balanced');
console.log(JSON.stringify({ids:result.quality.messageCoverage.map(m=>m.id),
  rendered:result.quality.messageCoverage.every(m=>result.svg.includes('data-id="'+m.id+'"')),
  order:result.quality.messageCoverage.map(m=>m.order)}));
""")
        self.assertEqual(result["ids"], ["sequence-0001-legacy", "sequence-0001", "exact-canonical-sequence"])
        self.assertEqual(result["order"], [1, 2, 3])
        self.assertTrue(result["rendered"])

    def test_inventory_names_are_preserved_once_even_without_members(self):
        result = self.run_node("""
const {Typography}=require('./typography');
const {prepareCard}=require('./generate');
const component={id:'component',name:'Exact component',kind:'tool',implementationStatus:'configure',
  buildOwner:'customer',pocScope:'included',productionStatus:'ready',
  description:'Exact role.',members:['Exact shared name'],
  inventoryNames:['Exact inventory-only name','Exact shared name','Exact component']};
const card=prepareCard(component,340,new Typography(),false,false,{verified:true});
console.log(JSON.stringify({all:card.canonicalMembers,
  separate:card.members.map(m=>m.name),represented:card.representedMembers}));
""")
        self.assertEqual(result["all"], ["Exact shared name", "Exact inventory-only name", "Exact component"])
        self.assertEqual(result["separate"], ["Exact shared name", "Exact inventory-only name"])
        self.assertEqual(result["represented"], ["Exact component"])

    def test_sequence_condition_order_and_action_control_do_not_synthesize_branches(self):
        result = self.run_node("""
const fs=require('fs');
const {Typography}=require('./typography');
const {sequenceDiagram}=require('./generate');
const model=require('../tests/fixtures/procurement-reference-model.json');
model.sequence=model.sequence.slice(0,2).map((m,i)=>({...m,order:(i+1)*10,fragment:null}));
model.sequence[0].relationshipId='exact-relationship';
model.sequence[0].condition='only after explicit approval';
model.sequence[0].actionControl={requiresApproval:true,execution:'manual'};
const before=JSON.stringify(model);
const uri='data:image/svg+xml;base64,'+fs.readFileSync('../resources/icons/copilot-studio.svg').toString('base64');
const icons=new Map(model.components.map(c=>[c.id,{verified:true,uri}]));
const result=sequenceDiagram(model,icons,new Typography(),'Balanced');
console.log(JSON.stringify({quality:result.quality,
  conditionVisible:result.drawing.texts.map(t=>t.text).join(' ').includes('Condition: only after explicit approval'),
  orderVisible:result.drawing.texts.some(t=>t.text.startsWith('10.')),
  fragments:(result.svg.match(/data-kind="fragment"/g)||[]).length,
  metadata:result.svg.includes('data-order="10"')&&result.svg.includes('data-relationship-id="exact-relationship"'),
  unchanged:JSON.stringify(model)===before}));
""")
        self.assertEqual(result["quality"]["validation"], "passed")
        self.assertEqual(result["quality"]["messageCoverage"][0]["order"], 10)
        self.assertEqual(result["quality"]["messageCoverage"][0]["occurrence"], 1)
        self.assertEqual(result["quality"]["messageCoverage"][0]["actionControl"],
                         {"requiresApproval": True, "execution": "manual"})
        self.assertTrue(result["conditionVisible"])
        self.assertTrue(result["orderVisible"])
        self.assertTrue(result["metadata"])
        self.assertTrue(result["unchanged"])
        self.assertEqual(result["fragments"], 0)

    def test_declared_participants_preserve_order_and_unused_lifelines(self):
        result = self.run_node("""
const fs=require('fs');
const {Typography}=require('./typography');
const {sequenceDiagram,sequenceParticipants}=require('./generate');
const model=require('../tests/fixtures/procurement-reference-model.json');
model.sequence=model.sequence.slice(0,2);
const legacy=sequenceParticipants(model);
model.sequenceParticipants=[{id:'monitor'},{componentId:'teams'},'requester','entra'];
const uri='data:image/svg+xml;base64,'+fs.readFileSync('../resources/icons/copilot-studio.svg').toString('base64');
const icons=new Map(model.components.map(c=>[c.id,{verified:true,uri}]));
const result=sequenceDiagram(model,icons,new Typography(),'Balanced');
console.log(JSON.stringify({legacy,quality:result.quality,
  lifelines:[...result.svg.matchAll(/data-kind="lifeline" data-component-id="([^"]+)"/g)].map(match=>match[1])}));
""")
        self.assertEqual(result["legacy"], ["requester", "teams", "entra"])
        self.assertEqual(result["quality"]["validation"], "passed")
        self.assertEqual(result["quality"]["participantIds"], ["monitor", "teams", "requester", "entra"])
        self.assertEqual(result["lifelines"], ["monitor", "teams", "requester", "entra"])

    def test_invalid_explicit_participant_contract_is_not_silently_repaired(self):
        result = self.run_node("""
const {sequenceParticipants}=require('./generate');
const base={components:[{id:'a'},{id:'b'},{id:'c'}],sequence:[{from:'a',to:'b'}]};
console.log(JSON.stringify([['a','b','missing'],['a','b','a'],['a','c'],'not an array'].map(sequenceParticipantsValue=>{
  try { sequenceParticipants({...base,sequenceParticipants:sequenceParticipantsValue}); return null; }
  catch(error) { return error.message; }
})));
""")
        self.assertIn("Unknown", result[0])
        self.assertIn("Duplicate", result[1])
        self.assertIn("Message endpoint missing", result[2])
        self.assertIn("must be an array", result[3])


if __name__ == "__main__":
    unittest.main()
