const { escapeXml: esc } = require("./typography");
const style = require("./style");

const DIAGRAMS = [
  { id: "business", prefix: "BA", title: "Business architecture",
    caption: "Leadership view: who starts the work, what the solution does, the decisions people keep, the outcome, and the controls that apply everywhere." },
  { id: "architecture", prefix: "SA", title: "Engineering architecture",
    caption: "Engineering view: exact products, runtimes, deployment boundaries, ownership, PoC treatment and typed relationships for the build." },
  { id: "sequence", prefix: "SD", title: "Sequence diagram",
    caption: "Numbered interactions in order, including approvals, failure branches and implementation modes." },
];
const PHASES = [
  { key: "build", label: "P1 / BUILD", title: "Build and configure", treatments: ["build", "configure", "existing"] },
  { key: "demonstrate", label: "P2 / DEMONSTRATE", title: "Demonstrate with disclosure", treatments: ["simulate", "static-sample-data"] },
  { key: "handoff", label: "P3 / HAND OFF", title: "Hand off to owners", treatments: ["manual-handoff"] },
  { key: "deferred", label: "P4 / DEFERRED", title: "Deferred or blocked", treatments: ["defer", "block"] },
];
const TREATMENT = {
  build: "Build", configure: "Configure", existing: "Existing", simulate: "Simulated",
  "static-sample-data": "Sample data", "manual-handoff": "Manual hand-off", defer: "Deferred", block: "Blocked",
};

function text(value) { return esc(value == null ? "" : String(value)); }
function list(values) { return (values || []).filter(Boolean).map(text).join(", "); }
function initials(title) {
  const letters = String(title).split(/\s+/).filter(word => /^[A-Za-z0-9]/.test(word)).map(word => word[0].toUpperCase());
  return (letters.slice(0, 3).join("") || "AR").replace(/[^A-Z0-9]/g, "");
}
function dimensionsFor(options, key) {
  const value = options[key];
  return Number.isSafeInteger(value?.width) && value.width > 0 && Number.isSafeInteger(value?.height) && value.height > 0
    ? ` width="${value.width}" height="${value.height}"` : "";
}
function hasSourceFiles(options, model) {
  const candidate = options.sources === false ? null :
    options.sources || options.sourceReport || model.sources || model.sourceReport;
  const metadata = candidate?.sources || candidate;
  return options.sources === true || Boolean(
    metadata?.drawio && metadata?.architectureMermaid && metadata?.sequenceMermaid
  );
}

function figure(model, diagram, options, sources) {
  const file = `${diagram.prefix}_${model.scenarioSlug}`;
  const mermaid = sources ? `<a href="${file}.mmd" download>Mermaid</a>` : "";
  return `
          <figure id="${diagram.id}" class="view view-${diagram.id}">
            <div class="figure-bar">
              <div><strong>${diagram.title}</strong><p id="${diagram.id}-caption">${text(diagram.caption)}</p></div>
              <div class="downloads" aria-label="${diagram.title} files"><a href="${file}.svg">Open SVG</a><a href="${file}.png" download>PNG</a>${mermaid}</div>
            </div>
            <input class="native-size" type="checkbox" id="${diagram.id}-native">
            <label class="native-label" for="${diagram.id}-native">Actual size (scroll to explore)</label>
            <div class="diagram-stage" tabindex="0" role="region" aria-label="${diagram.title} image" aria-describedby="${diagram.id}-caption">
              <img src="${file}.png" alt="${text(model.title)} - ${diagram.title}"${dimensionsFor(options, diagram.id)} loading="eager" decoding="sync">
            </div>
          </figure>`;
}

function roadmap(model) {
  const capabilities = model.capabilityAssessments || [];
  const gaps = model.productionReadinessGaps || [];
  const phases = PHASES.map(phase => {
    const members = capabilities.filter(item => phase.treatments.includes(item.poc_treatment));
    const ids = new Set(members.map(item => item.id));
    const phaseGaps = gaps.filter(gap => (gap.capability_ids || []).some(id => ids.has(id)));
    return { ...phase, members, phaseGaps };
  }).filter(phase => phase.members.length);
  if (!phases.length) return "";
  const cards = phases.map(phase => `
        <article class="phase phase-${phase.key}"><div class="phase-label">${phase.label}</div><h3>${phase.title}</h3>
          <ul>${phase.members.map(item => `<li>${text(item.name || item.id)} <span class="muted">${text(item.id)}</span></li>`).join("")}</ul>
          <div class="gate"><strong>Gate:</strong> ${phase.phaseGaps.length
            ? `${phase.phaseGaps.length} readiness gap${phase.phaseGaps.length === 1 ? "" : "s"} to close before production.`
            : "no readiness gap recorded for this group."}</div></article>`).join("");
  return `
    <section id="delivery" aria-labelledby="delivery-title">
      <div class="section-heading"><div><div class="index">01 / Delivery path</div><h2 id="delivery-title">Earn the right to automate.</h2><p>Capabilities grouped by their classified PoC treatment. Each group has its own readiness gate.</p></div><span class="tag">PoC scope, not a schedule</span></div>
      <div class="roadmap">${cards}
      </div>
    </section>`;
}

function principles(model) {
  const values = model.architecturePrinciples || [];
  if (!values.length) return "";
  return `
      <div class="note-grid">${values.map(item => `
        <article class="note"><h3>${text(String(item.dimension || "Principle").replace(/^./, c => c.toUpperCase()))}</h3><p>${text(item.decision || "")}</p>${item.implementation ? `<p class="fine">${text(item.implementation)}</p>` : ""}</article>`).join("")}
      </div>`;
}

function sequenceNarrative(model) {
  let phase = null;
  const rows = [];
  model.sequence.forEach((message, index) => {
    if (message.phase && message.phase !== phase) {
      phase = message.phase;
      rows.push(`<li class="phase-row">${text(phase)}</li>`);
    }
    const condition = message.condition ? ` <span class="muted">(${text(message.condition)})</span>` : "";
    const mode = message.implementationMode && message.implementationMode !== "real" ? ` <span class="mode">${text(message.implementationMode)}</span>` : "";
    rows.push(`<li><strong>${message.order ?? index + 1}.</strong> ${text(message.label)}${condition}${mode}</li>`);
  });
  return `<details><summary>Plain-language sequence</summary><div class="details-content"><ol class="narrative">${rows.join("")}</ol></div></details>`;
}

function gates(model) {
  const gaps = model.productionReadinessGaps || [];
  const cards = gaps.map((gap, index) => `
        <article class="decision-card"><div class="number">GATE ${String(index + 1).padStart(2, "0")} / ${text(gap.id || "READINESS")}</div>
          <h3>${text(gap.description || gap.name || "Production readiness gap")}</h3>
          <p>${text(gap.production_impact || "")}</p>
          ${gap.poc_impact ? `<p class="fine">PoC impact: ${text(gap.poc_impact)}</p>` : ""}
          <div class="evidence">Owner: ${text(gap.owner || "TBD")}${(gap.capability_ids || []).length ? ` / Capabilities: ${list(gap.capability_ids)}` : ""}</div></article>`).join("");
  return `
    <section id="gates" aria-labelledby="gates-title">
      <div class="section-heading"><div><div class="index">04 / Architecture approval gates</div><h2 id="gates-title">Resolve these before committing the production design.</h2><p>Readiness gaps recorded by classification, not assumptions hidden behind a diagram.</p></div><span class="tag">${gaps.length} recorded gap${gaps.length === 1 ? "" : "s"}</span></div>
      ${cards ? `<div class="decision-grid">${cards}
      </div>` : `<p class="empty">No production readiness gaps were recorded by classification.</p>`}
    </section>`;
}

function platformDecision(model) {
  const decision = model.decision;
  if (!decision) return "";
  const suitability = decision.suitability;
  const comparison = decision.comparison || [];
  const rows = comparison.map(item => `<tr class="${item.selected ? "selected" : ""}"><td>${text(item.platform)}${item.selected ? ' <span class="pill">Selected</span>' : ""}</td><td>${text(item.fit)}</td><td>${(item.pros || []).map(text).join("<br>")}</td><td>${(item.cons || []).map(text).join("<br>")}</td><td>${text(item.rationale)}</td></tr>`).join("");
  return `
    <section id="decision" aria-labelledby="decision-title">
      <div class="section-heading"><div><div class="index">05 / Platform decision</div><h2 id="decision-title">Why this platform, and why an agent.</h2><p>Precedence: Microsoft Cowork, Copilot Studio, Azure AI Foundry, then Microsoft Agent Framework. The first full fit is selected.</p></div><span class="tag">${text(decision.agenticPlatform)} / ${text(decision.codeTier)}${decision.harness ? ` / ${text(decision.harness)} harness` : ""}</span></div>
      <div class="decision-grid">
        <article class="decision-card"><div class="number">SELECTED PLATFORM</div><h3>${text(decision.agenticPlatform)}</h3><p>${text(decision.summary)}</p></article>
        ${suitability ? `<article class="decision-card"><div class="number">AGENTIC SUITABILITY / ${text(String(suitability.recommendation).toUpperCase())}</div><h3>${text(suitability.recommendation === "deterministic" ? "Solve it without an agent." : suitability.recommendation === "hybrid" ? "Agent for judgment, automation for rules." : "An agent is warranted.")}</h3><p>${text(suitability.summary)}</p>${suitability.deterministicAlternative ? `<p class="fine">Deterministic alternative: ${text(suitability.deterministicAlternative)}</p>` : ""}</article>` : ""}
      </div>
      ${rows ? `<div class="panel table-wrap comparison"><table><thead><tr><th scope="col">Platform</th><th scope="col">Fit</th><th scope="col">Pros</th><th scope="col">Cons</th><th scope="col">Decision rationale</th></tr></thead><tbody>${rows}</tbody></table></div>` : ""}
    </section>`;
}

function reference(model, options) {
  const codes = style.componentCodes(model);
  const byId = new Map(model.components.map(item => [item.id, item]));
  const endpoint = id => `${text(codes.get(id) || "")} ${text(byId.get(id)?.name || id)}`;
  const components = model.components.map(item => `<tr><td>${text(codes.get(item.id))}</td><td>${text(item.id)}</td><td>${text(item.name)}</td><td>${text(item.productService || "")}</td><td>${text(item.deploymentBoundary || item.layer)}</td><td>${text(item.buildOwner)}</td><td>${text(TREATMENT[item.implementationStatus] || item.implementationStatus)}</td></tr>`).join("");
  const relationships = model.relationships.map((edge, index) => {
    const meaning = style.MEANINGS[style.linkMeaning(edge, byId)];
    return `<tr><td>R${String(index + 1).padStart(2, "0")}</td><td>${endpoint(edge.from)}</td><td>${endpoint(edge.to)}</td><td>${text(edge.label)}</td><td><span class="swatch" style="background:${style.PALETTE[meaning.tone].line}"></span>${text(meaning.label)}</td><td>${text(edge.relationshipType || edge.style)}</td><td>${text(edge.implementationMode)}</td></tr>`;
  }).join("");
  const capabilities = (model.capabilityAssessments || []).map(item => `<tr><td>${text(item.id)}</td><td>${text(item.name || "")}</td><td>${text(item.business_priority || "")}</td><td>${text(TREATMENT[item.poc_treatment] || item.poc_treatment)}</td><td>${list(item.component_ids)}</td></tr>`).join("");
  const boundaries = (model.trustBoundaries || []).map(item => `<tr><td>${text(item.id || "")}</td><td>${text(item.name || item.label || "")}</td><td>${list(item.component_ids || item.componentIds)}</td></tr>`).join("");
  const references = (options.references || []).filter(value => typeof value === "string").map(value => `<li>${text(value)}</li>`).join("");
  return `
    <section id="reference" aria-labelledby="reference-title">
      <div class="section-heading"><div><div class="index">06 / Developer &amp; reviewer reference</div><h2 id="reference-title">Traceable components, not unexplained boxes.</h2><p>Every diagram card maps to a classified component or capability.</p></div></div>
      <details><summary>Component index / ${model.components.length} components</summary><div class="details-content table-wrap"><table><thead><tr><th scope="col">Code</th><th scope="col">ID</th><th scope="col">Component</th><th scope="col">Product / service</th><th scope="col">Boundary</th><th scope="col">Owner</th><th scope="col">Treatment</th></tr></thead><tbody>${components}</tbody></table></div></details>
      ${relationships ? `<details><summary>Relationship index / ${model.relationships.length} links (R-codes on the engineering diagram)</summary><div class="details-content table-wrap"><table><thead><tr><th scope="col">Code</th><th scope="col">From</th><th scope="col">To</th><th scope="col">Interaction</th><th scope="col">Meaning</th><th scope="col">Type</th><th scope="col">Mode</th></tr></thead><tbody>${relationships}</tbody></table></div></details>` : ""}
      ${capabilities ? `<details><summary>Capability-to-component mapping</summary><div class="details-content table-wrap"><table><thead><tr><th scope="col">ID</th><th scope="col">Capability</th><th scope="col">Priority</th><th scope="col">Treatment</th><th scope="col">Components</th></tr></thead><tbody>${capabilities}</tbody></table></div></details>` : ""}
      ${boundaries ? `<details><summary>Trust boundaries</summary><div class="details-content table-wrap"><table><thead><tr><th scope="col">ID</th><th scope="col">Boundary</th><th scope="col">Components</th></tr></thead><tbody>${boundaries}</tbody></table></div></details>` : ""}
      ${references ? `<details><summary>Guidance consulted</summary><div class="details-content"><ul class="references">${references}</ul></div></details>` : ""}
    </section>`;
}

function createPreview(model, options = {}) {
  if (!/^[A-Za-z0-9_]+$/.test(model.scenarioSlug)) throw new Error("Invalid preview scenario slug");
  const sources = hasSourceFiles(options, model);
  const coverage = model.coverage || {};
  const components = model.components || [];
  const relationships = model.relationships || [];
  const capabilityCount = (model.capabilityAssessments || []).length;
  const decision = model.decision || null;
  const delivery = roadmap({ ...model, components });
  const reviewModel = { ...model, components, relationships, sequence: model.sequence || [] };
  const business = figure(model, DIAGRAMS[0], options, sources);
  const engineering = figure(model, DIAGRAMS[1], options, sources);
  const sequence = figure(model, DIAGRAMS[2], options, sources);
  const nav = [
    delivery ? '<a href="#delivery">Delivery</a>' : "", '<a href="#solution-architecture">Architecture</a>',
    '<a href="#sequences">Sequence</a>', '<a href="#gates">Gates</a>', decision ? '<a href="#decision">Decision</a>' : "",
    '<a href="#reference">Reference</a>',
  ].join("");
  const drawio = `Design_${model.scenarioSlug}.drawio`;
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="referrer" content="no-referrer">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file: data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; object-src 'none'">
  <title>${text(model.title)} | Architecture Review</title>
  <style>
    :root{--ink:${style.INK};--muted:${style.MUTED};--line:#d9e2ec;--paper:#f3f6fa;--navy:#101f35;--teal:${style.PALETTE.teal.line};--blue:${style.PALETTE.blue.line};--amber:${style.PALETTE.amber.line};--violet:${style.PALETTE.violet.line};--green:${style.PALETTE.green.line};--slate:${style.PALETTE.slate.line};--red:${style.PALETTE.red.line};--zone:${style.ZONE.stroke}}
    *{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:90px}body{margin:0;color:var(--ink);background:var(--paper);font:15px/1.6 "Segoe UI",Arial,sans-serif}
    a{color:#255bb4;text-underline-offset:3px}a:focus-visible,input:focus-visible,label:focus-visible,summary:focus-visible,.diagram-stage:focus-visible{outline:3px solid #2469cf;outline-offset:4px}
    .skip{position:absolute;left:16px;top:-80px;background:#fff;padding:10px;z-index:10}.skip:focus{top:10px}
    .topbar{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid var(--line)}.topbar-inner{max-width:1560px;margin:auto;display:flex;gap:24px;align-items:center;justify-content:space-between;padding:13px 28px}
    .brand{display:flex;align-items:center;gap:12px;font-size:14px;font-weight:700;letter-spacing:.02em}.mark{display:grid;place-items:center;background:var(--navy);color:#fff;min-width:37px;height:37px;padding:0 6px;border-radius:10px;font-size:12px;letter-spacing:.08em}
    nav{display:flex;gap:22px}nav a{text-decoration:none;font-size:13px;font-weight:600;color:var(--muted)}nav a:hover{color:var(--teal)}.status-flag{background:#fff3cc;color:#704800;font-size:11px;letter-spacing:.08em;font-weight:750;padding:5px 10px;border-radius:5px}
    main{max-width:1560px;margin:auto;padding:28px}.hero{border-radius:20px;background:linear-gradient(115deg,#12243c,#132e40);color:#fff;padding:42px 46px;display:grid;grid-template-columns:1.6fr 1fr;gap:46px}
    .eyebrow{font-size:11px;font-weight:700;letter-spacing:.17em;text-transform:uppercase;color:#7dd2cf}.hero h1{font-size:clamp(29px,3.1vw,44px);line-height:1.15;letter-spacing:-.035em;margin:14px 0 18px;overflow-wrap:anywhere}
    .hero p{color:#cedae7;max-width:760px;margin:0;font-size:16px;overflow-wrap:anywhere}.hero-meta{display:flex;gap:9px;flex-wrap:wrap;margin-top:26px}.hero-meta span{font-size:11px;color:#d2e4ec;border:1px solid #ffffff28;padding:5px 10px;border-radius:20px}
    .hero-side{border-left:1px solid #ffffff24;padding-left:34px;display:flex;flex-direction:column;justify-content:center}.hero-side .big{font-size:52px;line-height:1.1;letter-spacing:-.04em;font-weight:650}.hero-side .big small{font-size:20px;color:#9eb4c7;font-weight:400}.complexity{color:#ffda8d;font-size:11px;font-weight:750;letter-spacing:.14em;margin-bottom:8px}.hero-side p{font-size:13px;color:#bacddc;margin:14px 0 22px}.stats{display:flex;gap:30px}.stats strong{font-size:24px;display:block;line-height:1.3}.stats span{font-size:11px;color:#a9bfce}
    .decision-strip{background:#fff;border:1px solid var(--line);border-left:4px solid var(--teal);border-radius:10px;margin:20px 0 32px;padding:17px 22px;display:flex;gap:18px;align-items:baseline}.decision-strip strong{white-space:nowrap;color:var(--teal);font-size:12px;text-transform:uppercase;letter-spacing:.08em}.decision-strip p{margin:0;font-size:14px}
    section{margin:34px 0}.section-heading{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;margin-bottom:17px}.section-heading h2{font-size:25px;letter-spacing:-.025em;margin:0;line-height:1.3}.section-heading p{margin:6px 0 0;color:var(--muted);font-size:13px}.index{font-size:11px;letter-spacing:.12em;color:var(--teal);font-weight:750;margin-bottom:6px}.tag{font-size:11px;padding:4px 9px;border-radius:20px;background:#e6edf5;color:#4c607a;white-space:nowrap}
    .roadmap{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px}.phase{background:#fff;border:1px solid var(--line);border-top:3px solid var(--teal);border-radius:10px;padding:18px 20px}.phase-demonstrate{border-top-color:var(--blue)}.phase-handoff{border-top-color:var(--violet)}.phase-deferred{border-top-color:#cb8a22}.phase-label{font-size:11px;color:var(--muted);letter-spacing:.08em;font-weight:700}.phase h3{font-size:17px;margin:6px 0}.phase ul{margin:0;padding-left:18px;font-size:12px;color:var(--muted)}.phase .gate{border-top:1px solid #e9edf3;margin-top:14px;padding-top:11px;font-size:11px}
    .panel{background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden;box-shadow:0 3px 13px #223b5610}.toolbar{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:12px;padding:15px 20px;border-bottom:1px solid var(--line)}
    .view-toggle{position:absolute;opacity:0;width:1px;height:1px}.segmented{display:flex;flex-wrap:wrap;gap:4px;background:#edf2f7;border-radius:8px;padding:4px}.segmented label{border-radius:5px;color:#53657a;padding:8px 14px;font-size:12px;font-weight:650;cursor:pointer}
    #view-business:checked~.toolbar label[for="view-business"],#view-engineering:checked~.toolbar label[for="view-engineering"]{background:#fff;color:#143d70;box-shadow:0 1px 4px #17273d1a}
    #view-business:focus-visible~.toolbar label[for="view-business"],#view-engineering:focus-visible~.toolbar label[for="view-engineering"]{outline:3px solid #2469cf;outline-offset:2px}
    .view{display:none;margin:0}#view-business:checked~.views .view-business,#view-engineering:checked~.views .view-architecture,.view-sequence{display:block}
    .figure-bar{display:flex;gap:20px;justify-content:space-between;align-items:flex-start;padding:14px 21px;border-bottom:1px solid var(--line);background:#fbfcfe}.figure-bar p{margin:2px 0 0;font-size:12px;color:var(--muted);max-width:900px}.downloads{display:flex;gap:10px;flex-wrap:wrap}.downloads a,.doc-links a{background:#fff;border:1px solid #ccd9e5;border-radius:6px;padding:6px 11px;text-decoration:none;font-size:12px;font-weight:600;white-space:nowrap}
    .native-size{margin:14px 0 0 21px;vertical-align:middle}.native-label{display:inline-block;margin:10px 0 0 4px;font-size:12px;color:var(--muted);cursor:pointer}.diagram-stage{overflow:auto;padding:12px;background:#fff}.diagram-stage img{display:block;width:auto;max-width:100%;height:auto;margin:auto}.native-size:checked~.diagram-stage img{max-width:none;margin:0}
    .legend{display:flex;flex-wrap:wrap;gap:13px;font-size:11px;padding:12px 21px;border-top:1px solid var(--line);color:var(--muted)}.legend span{display:flex;align-items:center;gap:6px}.swatch{display:inline-block;width:18px;height:3px;background:var(--blue);margin-right:6px;vertical-align:middle}.swatch.dashed{height:0;background:none;border-top:2px dashed var(--slate)}.swatch.dotted{height:0;background:none;border-top:2px dotted var(--slate)}.swatch.zone{height:10px;background:#f8fafc;border:1px dashed var(--zone);border-radius:3px}
    .note-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin-top:16px}.note{padding:17px 20px;background:#fff;border:1px solid var(--line);border-radius:10px}.note h3{font-size:13px;margin:0 0 7px}.note p{font-size:12px;color:var(--muted);margin:0 0 6px}
    .decision-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:15px}.decision-card{padding:22px;background:#fff;border:1px solid var(--line);border-radius:11px}.decision-card .number{font-size:11px;font-weight:750;color:var(--teal)}.decision-card h3{font-size:16px;margin:6px 0 8px}.decision-card p{font-size:13px;color:var(--muted);margin:0 0 6px}.decision-card .evidence{margin-top:12px;font-size:11px;color:#4d6580}
    .comparison{margin-top:16px}.pill{font-size:10px;background:#e3f4ef;color:var(--green);border-radius:10px;padding:2px 7px;margin-left:4px}tr.selected td{background:#f5fbf8}
    details{background:#fff;border:1px solid var(--line);border-radius:10px;margin:12px 0}summary{padding:17px 20px;cursor:pointer;font-weight:650;font-size:14px}details .details-content{padding:0 20px 20px}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px}th{text-align:left;background:#eef3f8;font-size:11px;color:#42566f}td,th{padding:11px 13px;border-bottom:1px solid #e3eaf1;vertical-align:top}td:first-child{font-weight:650}tbody tr:last-child td{border-bottom:0}
    .narrative{font-size:13px;padding-left:0;list-style:none}.narrative li{margin:4px 0}.narrative .phase-row{margin-top:14px;font-size:11px;font-weight:750;letter-spacing:.1em;text-transform:uppercase;color:var(--teal)}.mode{font-size:10px;background:#fff3cc;color:#704800;border-radius:10px;padding:1px 7px}
    .muted,.fine,.empty{color:var(--muted)}.fine{font-size:11px}.references{font-size:12px;overflow-wrap:anywhere}
    .handoff{display:flex;gap:20px;justify-content:space-between;align-items:center;background:#eaf1f7;border:1px solid #d3dfe9;border-radius:12px;padding:22px 25px}.handoff h3{font-size:16px;margin:0 0 5px}.handoff p{font-size:12px;margin:0;color:var(--muted)}.doc-links{display:flex;gap:10px;flex-wrap:wrap}
    footer{border-top:1px solid var(--line);margin-top:34px;padding:20px 0 10px;display:flex;gap:20px;justify-content:space-between;font-size:11px;color:var(--muted)}
    @media(max-width:1100px){.hero{grid-template-columns:1.5fr 1fr;padding:32px;gap:25px}.decision-grid{grid-template-columns:1fr}.figure-bar{flex-direction:column}nav{gap:12px}}
    @media(max-width:700px){main{padding:16px}nav{display:none}.hero{grid-template-columns:1fr;padding:26px}.hero-side{border-left:0;border-top:1px solid #ffffff24;padding:23px 0 0}.decision-strip{display:block}.section-heading{align-items:flex-start;flex-direction:column}.handoff{flex-direction:column;align-items:flex-start}footer{flex-direction:column}}
    @media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
    @page{size:A3 landscape;margin:12mm}
    @media print{body{background:#fff;font-size:11px}.topbar{position:static}nav,.segmented,.downloads,.native-label,.doc-links,.skip{display:none!important}main{padding:0;max-width:none}.hero{print-color-adjust:exact;-webkit-print-color-adjust:exact}.view{display:block!important;break-inside:avoid}.diagram-stage{overflow:visible}.diagram-stage img{max-width:100%!important}details:not([open]){display:none}#sequences{break-before:page}}
  </style>
</head>
<body>
  <a class="skip" href="#main">Skip to architecture review</a>
  <header class="topbar">
    <div class="topbar-inner">
      <div class="brand"><span class="mark" aria-hidden="true">${text(initials(model.title))}</span><span>${text(model.title)}</span></div>
      <nav aria-label="Sections">${nav}</nav>
      <span class="status-flag">PROPOSED</span>
    </div>
  </header>
  <main id="main">
    <div class="hero">
      <div>
        <div class="eyebrow">Architecture review / decision brief</div>
        <h1>${text(model.title)}</h1>
        <p>${text(model.summary)}</p>
        <div class="hero-meta">${decision ? `<span>${text(decision.agenticPlatform)}</span><span>${text(decision.codeTier)}</span>` : ""}<span>${text(model.complexity)} complexity</span><span>Proposed architecture / not deployed</span></div>
      </div>
      <div class="hero-side">
        <div class="complexity">${text(String(model.complexity || "").toUpperCase())} COMPLEXITY</div>
        <div class="big">${text(coverage.nativeBuildPercent ?? 0)}% <small>native build</small></div>
        <p>PoC demonstration ${text(coverage.pocDemonstrationPercent ?? 0)}%${coverage.unsupportedPercent !== undefined ? `, unsupported ${text(coverage.unsupportedPercent)}%` : ""}${coverage.unknownPercent !== undefined ? `, unknown ${text(coverage.unknownPercent)}%` : ""}. Classified coverage, not an effort estimate.</p>
        <div class="stats"><div><strong>${components.length}</strong><span>components</span></div><div><strong>${capabilityCount}</strong><span>capabilities</span></div><div><strong>${relationships.length}</strong><span>relationships</span></div></div>
      </div>
    </div>
    <div class="decision-strip"><strong>Recommended decision</strong><p>${text(decision?.summary || model.summary)}</p></div>
${delivery}
    <section id="solution-architecture" aria-labelledby="architecture-title">
      <div class="section-heading"><div><div class="index">02 / Solution architecture</div><h2 id="architecture-title">Two views of one solution.</h2><p>Choose the business overview or the engineering component view. Both describe the same proposed solution.</p></div><span class="tag">${components.length} components / ${relationships.length} relationships</span></div>
      <div class="panel">
        <input class="view-toggle" type="radio" name="architecture-view" id="view-business" checked>
        <input class="view-toggle" type="radio" name="architecture-view" id="view-engineering">
        <div class="toolbar"><div class="segmented" role="group" aria-label="Architecture view"><label for="view-business">Business overview</label><label for="view-engineering">Engineering view</label></div></div>
        <div class="views">${business}${engineering}
        </div>
        <div class="legend" aria-label="Line legend">${Object.values(style.MEANINGS).map(meaning => `<span><i class="swatch" style="background:${style.PALETTE[meaning.tone].line}" aria-hidden="true"></i>${text(meaning.label)}</span>`).join("")}<span><i class="swatch dashed" aria-hidden="true"></i>Response / optional</span><span><i class="swatch dotted" aria-hidden="true"></i>Simulated, manual or deferred</span><span><i class="swatch zone" aria-hidden="true"></i>Deployment boundary (engineering)</span></div>
      </div>${principles(model)}
    </section>

    <section id="sequences" aria-labelledby="sequence-title">
      <div class="section-heading"><div><div class="index">03 / Interaction sequence</div><h2 id="sequence-title">How the solution behaves, including when it must stop.</h2><p>Numbered messages show the operating contract. Alternative branches are mutually exclusive, not consecutive actions.</p></div><span class="tag">${reviewModel.sequence.length} interactions</span></div>
      <div class="panel"><div class="views">${sequence}
      </div></div>
      ${sequenceNarrative(reviewModel)}
    </section>
${gates(model)}
${platformDecision(model)}
${reference(reviewModel, options)}
    <div class="handoff"><div><h3>Keep the review with its diagrams.</h3><p>This page loads the three diagrams from sibling files. Move or share the artifact folder as a unit; no JavaScript, server or network access is required.</p></div>${sources ? `<div class="doc-links"><a href="${drawio}" download>Editable Draw.io (all diagrams)</a></div>` : ""}</div>
    <footer><span>${text(model.title)} / Architecture review / proposed, not deployed</span><span>Self-contained local review. No scripts, external assets or telemetry. A review is not evidence of deployment or approval.</span></footer>
  </main>
</body>
</html>
`;
}

module.exports = { createPreview, DIAGRAMS };
