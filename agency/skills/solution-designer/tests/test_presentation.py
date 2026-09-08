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


if __name__ == "__main__":
    unittest.main()
