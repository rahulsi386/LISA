// Shared visual system for every generated diagram and the review page.
// Benchmark: the SDM Intelligent Operations Architecture Review (tinted cards,
// accent bars, dashed boundary zones, meaning-coded links, numbered sequence rail).
const PALETTE = Object.freeze({
  teal: Object.freeze({ line: "#087F82", fill: "#EEF9F7", border: "#80BFBB" }),
  blue: Object.freeze({ line: "#285FC7", fill: "#EFF4FE", border: "#9CB6EB" }),
  amber: Object.freeze({ line: "#9A5D08", fill: "#FFF7E8", border: "#D8B671" }),
  slate: Object.freeze({ line: "#65778D", fill: "#F4F7FA", border: "#B7C5D4" }),
  violet: Object.freeze({ line: "#7250AC", fill: "#F6F2FB", border: "#BCA8D5" }),
  green: Object.freeze({ line: "#237646", fill: "#EDF8F0", border: "#93BF9E" }),
  red: Object.freeze({ line: "#A63D37", fill: "#FFF2F0", border: "#D7A39F" }),
});
const INK = "#17273D";
const MUTED = "#53657A";
const CANVAS = "#FFFFFF";
const ZONE = Object.freeze({ stroke: "#CBD7E3", fill: "#F8FAFC", title: "#53657A", radius: 13 });
const STROKE = Object.freeze({ card: 1.2, hero: 2, edge: 1.8, zone: 1.2, accent: 4 });
const DASH = Object.freeze({ response: "7 5", pending: "2 5", zone: "5 5", lifeline: "4 6" });
const RADIUS = Object.freeze({ card: 10, label: 5 });
// Minimums are enforced by Test-Diagrams.ps1; engineering titles stay >=19px so
// they remain >=15px when a 2200px canvas is fitted to the 1800px preview width.
const TYPE = Object.freeze({
  diagramTitle: { size: 26, weight: 700 }, kicker: { size: 12, weight: 700 },
  subtitle: { size: 14, weight: 400 }, zoneTitle: { size: 14, weight: 700 },
  nodeTitle: { size: 19, weight: 650 }, heroTitle: { size: 23, weight: 700 },
  nodeCode: { size: 11, weight: 700 }, nodeCopy: { size: 14, weight: 400 },
  metadata: { size: 11, weight: 400 }, edgeLabel: { size: 12, weight: 600 },
  laneTitle: { size: 14, weight: 650 }, messageCopy: { size: 13, weight: 550 },
  stepNumber: { size: 11, weight: 700 }, bandTitle: { size: 12, weight: 700 },
  legend: { size: 12, weight: 400 }, statement: { size: 18, weight: 650 },
});
const ICON = Object.freeze({ card: 32, hero: 40 });
const CANVAS_TARGET = Object.freeze({ minimumWidth: 1280, maximumWidth: 2200, landscapeAspect: 1.25 });

// Component responsibility decides the card tone, never the product name.
const KIND_TONES = Object.freeze({
  actor: "slate", channel: "slate", agent: "blue", knowledge: "violet", data: "violet",
  tool: "teal", flow: "teal", integration: "teal", external: "teal", human: "amber",
  security: "slate", monitoring: "slate", alm: "slate",
});
const KIND_LEGEND = Object.freeze([
  ["slate", "People, channels and controls"], ["blue", "Agent and orchestration"],
  ["violet", "Knowledge and data"], ["teal", "Actions, integration and systems"],
  ["amber", "Human decision"], ["red", "Blocked"],
]);
const TREATMENT_TAGS = Object.freeze({
  block: "BLOCKED", defer: "DEFERRED", "manual-handoff": "MANUAL", simulate: "SIMULATED",
  "static-sample-data": "SAMPLE DATA", build: "BUILD", configure: "CONFIGURE", existing: "EXISTING",
});
// Link meaning follows the evidenced relationship type; line pattern shows implementation mode.
const MEANINGS = Object.freeze({
  evidence: { tone: "teal", label: "Evidence / retrieval" },
  query: { tone: "blue", label: "Request / response" },
  action: { tone: "amber", label: "Governed action" },
  identity: { tone: "violet", label: "Identity / access (authN, authZ)" },
  control: { tone: "slate", label: "Control / audit" },
  blocked: { tone: "red", label: "Blocked" },
});
const TYPE_MEANING = Object.freeze({
  retrieves: "evidence", reads: "evidence",
  writes: "action", triggers: "action", approves: "action",
  authenticates: "identity", authorizes: "identity", protects: "identity",
  governs: "control", monitors: "control", deploys: "control",
  communicates: "query", responds: "query", "publishes-to": "query", hosts: "query", integrates: "query",
});
const TARGET_MEANING = Object.freeze({
  knowledge: "evidence", data: "evidence", tool: "action", flow: "action", integration: "action",
  external: "action", human: "action", security: "identity", monitoring: "control", alm: "control",
});

function tone(name) {
  const value = PALETTE[name];
  if (!value) throw new Error(`Unknown palette tone: ${name}`);
  return value;
}

function componentTone(component) {
  return component.implementationStatus === "block" ? "red" : KIND_TONES[component.kind] || "slate";
}

function linkMeaning(edge, byId) {
  if (edge.implementationMode === "blocked") return "blocked";
  const source = byId.get(edge.from);
  const response = edge.relationshipType === "responds" || edge.style === "response" || edge.type === "response";
  // Grounded content returned by a knowledge or data source is evidence, whichever way it is typed.
  if (response && ["knowledge", "data"].includes(source?.kind)) return "evidence";
  const typed = TYPE_MEANING[edge.relationshipType || ""];
  if (typed) return typed;
  const target = byId.get(edge.to);
  if (edge.relationshipType === "invokes") return TARGET_MEANING[target?.kind] === "action" ? "action" : "query";
  if (response) return "query";
  if (edge.type === "approval") return "action";
  return TARGET_MEANING[target?.kind] || "query";
}

function linkPattern(edge) {
  if (["simulated", "manual", "deferred"].includes(edge.implementationMode)) return DASH.pending;
  return edge.style === "call" || edge.type === "call" || edge.type === "approval" || edge.type === "self" ? "" : DASH.response;
}

const MODE_WORDS = Object.freeze({ simulated: "Simulated", manual: "Manual", deferred: "Deferred", blocked: "Blocked" });

function componentCodes(model) {
  return new Map(model.components.map((component, index) => [component.id, `C${String(index + 1).padStart(2, "0")}`]));
}

function relationshipCodes(relationships) {
  return new Map(relationships.map((edge, index) => [edge.id, `R${String(index + 1).padStart(2, "0")}`]));
}

function humanize(value) {
  return String(value).replace(/[-_]+/g, " ").replace(/\s+/g, " ").trim().toUpperCase();
}

const TOKENS = Object.freeze({
  palette: PALETTE, ink: INK, muted: MUTED, canvas: CANVAS, zone: ZONE, stroke: STROKE,
  dash: DASH, radius: RADIUS, type: TYPE, icon: ICON, canvasTarget: CANVAS_TARGET,
});

// Machine gate: every painted colour, stroke width and font size must come from the tokens.
function styleConformance(svg) {
  const colours = new Set([INK, MUTED, CANVAS, ZONE.stroke, ZONE.fill, ZONE.title, "none",
    ...Object.values(PALETTE).flatMap(value => [value.line, value.fill, value.border])].map(c => c.toUpperCase()));
  const sizes = new Set(Object.values(TYPE).map(value => value.size));
  const strokes = new Set([...Object.values(STROKE), 1, .7].map(Number));
  const body = svg.replace(/<defs>[^]*?<\/defs>/, "");
  const issues = [];
  for (const [, attribute, value] of body.matchAll(/\s(fill|stroke)="([^"]+)"/g)) {
    if (value.startsWith("url(")) continue;
    if (!colours.has(value.toUpperCase())) issues.push(`${attribute} ${value} is not a style token`);
  }
  for (const [, value] of body.matchAll(/\sfont-size="([\d.]+)"/g)) {
    if (!sizes.has(Number(value))) issues.push(`font-size ${value} is not on the type scale`);
  }
  for (const [, value] of body.matchAll(/\sstroke-width="([\d.]+)"/g)) {
    if (!strokes.has(Number(value))) issues.push(`stroke-width ${value} is not a style token`);
  }
  return { validation: issues.length ? "failed" : "passed", issues: [...new Set(issues)] };
}

module.exports = {
  PALETTE, INK, MUTED, CANVAS, ZONE, STROKE, DASH, RADIUS, TYPE, ICON, CANVAS_TARGET, TOKENS,
  KIND_TONES, KIND_LEGEND, TREATMENT_TAGS, MEANINGS, MODE_WORDS,
  tone, componentTone, linkMeaning, linkPattern, componentCodes, relationshipCodes, humanize, styleConformance,
};
