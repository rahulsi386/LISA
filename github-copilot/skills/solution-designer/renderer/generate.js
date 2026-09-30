const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { Typography, escapeXml: esc } = require("./typography");
const { composeArchitecture, boundaryOf, compositionFamilies, isCrossCutting, visualRole, visualGroup } = require("./composition");
const { createPreview } = require("./preview");
const { businessArchitecture } = require("./business");
const { visualQuality, identified } = require("./quality");
const style = require("./style");

const { PALETTE, TYPE, STROKE, DASH, ZONE, ICON } = style;
// Named accents map one-to-one onto the shared review palette (renderer/style.js).
const THEME = Object.freeze({
  background: style.CANVAS, paper: style.CANVAS, ink: style.INK, muted: style.MUTED,
  border: ZONE.stroke, blue: PALETTE.blue.line, green: PALETTE.green.line, cyan: PALETTE.teal.line,
  amber: PALETTE.amber.line, gray: PALETTE.slate.line, red: PALETTE.red.line, purple: PALETTE.violet.line,
});
const PROFILES = {
  Balanced: { width: 1920, mainGap: 120, supportGap: 120, rowGap: 154 },
  Spacious: { width: 2240, mainGap: 160, supportGap: 150, rowGap: 184 },
  Wide: { width: 2560, mainGap: 190, supportGap: 180, rowGap: 214 },
};
const STATUS = {
  existing: "Existing", build: "Build", configure: "Configure", simulate: "Simulated",
  "static-sample-data": "Sample data", "manual-handoff": "Manual",
  defer: "Deferred", block: "Blocked",
};
const OWNERS = {
  "agent-builder": "Agent builder", customer: "Customer",
  "external-team": "External team", unassigned: "Owner TBD",
};
const PRODUCTION = { ready: "Production ready", "requires-hardening": "Needs hardening", gap: "Production gap" };
const CARD_HEAD = 22;
const PENDING_STATUS = new Set(["simulate", "static-sample-data", "manual-handoff", "defer"]);

function number(value) { return Math.round(value * 100) / 100; }
function boxAttrs(box) {
  return `data-x="${number(box.x)}" data-y="${number(box.y)}" ` +
    `data-width="${number(box.width)}" data-height="${number(box.height)}"`;
}
function linkColor(edge, byId) {
  return PALETTE[style.MEANINGS[style.linkMeaning(edge, byId)].tone].line;
}
function readJson(file) { return JSON.parse(fs.readFileSync(file, "utf8").replace(/^\uFEFF/, "")); }

class Drawing {
  constructor(width, typography) {
    this.width = width;
    this.typography = typography;
    this.parts = [];
    this.texts = [];
    this.markers = new Map();
    this.serial = 0;
  }
  add(svg) { this.parts.push(svg); }
  rect(box, fill, stroke = "none", radius = style.RADIUS.card, extras = "") {
    this.add(`<rect x="${number(box.x)}" y="${number(box.y)}" width="${number(box.width)}" ` +
      `height="${number(box.height)}" rx="${radius}" fill="${fill}" stroke="${stroke}" ${extras}/>`);
  }
  text(text, x, baseline, size = 14, color = THEME.muted, weight = 400, owner = "", center = false, role = "body", anchorEnd = false) {
    if (!String(text).trim()) return;
    const glyph = this.typography.measure(text, size, weight);
    // Position the glyph extent rather than approximating character advance.
    const drawX = x - glyph.x - (center ? glyph.width / 2 : anchorEnd ? glyph.width : 0);
    const bounds = {
      x: drawX + glyph.x, y: baseline + glyph.y, width: glyph.width, height: glyph.height,
    };
    this.texts.push({ ...bounds, owner, text, size, role });
    this.add(`<g data-kind="text-box" data-owner="${esc(owner)}" data-role="${esc(role)}" ${boxAttrs(bounds)}>` +
      `<text x="${number(drawX)}" y="${number(baseline)}" font-family="Inter" font-size="${size}" ` +
      `font-weight="${weight}" fill="${color}">${esc(text)}</text></g>`);
  }
  lines(lines, x, y, size, color, weight, owner, leading, center = false, role = "body") {
    lines.forEach((line, i) => this.text(line, x, y + i * leading, size, color, weight, owner, center, role));
  }
  image(icon, x, y, size) {
    this.add(`<image href="${icon.uri}" x="${number(x)}" y="${number(y)}" ` +
      `width="${size}" height="${size}" preserveAspectRatio="xMidYMid meet"/>`);
  }
  arrow(points, color, dash = "", attributes = "", bidirectional = false) {
    if (!this.markers.has(color)) this.markers.set(color, `arrow-${this.markers.size}`);
    const marker = this.markers.get(color);
    const pattern = dash === true ? DASH.response : dash || "";
    this.add(`<path d="M ${points.map(p => `${number(p.x)} ${number(p.y)}`).join(" L ")}" ` +
      `fill="none" stroke="${color}" stroke-width="${STROKE.edge}" stroke-linejoin="round" ` +
      `${pattern ? `stroke-dasharray="${pattern}"` : ""} marker-end="url(#${marker})" ` +
      `${bidirectional ? `marker-start="url(#${marker}-start)"` : ""} ${attributes}/>`);
  }
  header(model, kind, includeSummary = true) {
    const title = this.typography.wrap(model.title, this.width - 180, TYPE.diagramTitle.size, TYPE.diagramTitle.weight);
    const subtitleY = 108 + (title.length - 1) * 34;
    const summary = this.typography.wrap(includeSummary ? model.summary || "" : "", this.width - 120, TYPE.subtitle.size);
    const headerHeight = subtitleY + 22 + summary.length * 20;
    this.text(`SOLUTION DESIGN / ${kind.toUpperCase()}`, 60, 44, TYPE.kicker.size, PALETTE.teal.line, TYPE.kicker.weight, "header");
    this.lines(title, 60, 80, TYPE.diagramTitle.size, THEME.ink, TYPE.diagramTitle.weight, "header", 34, false, "title");
    this.text(`${model.complexity} complexity | Native ${model.coverage.nativeBuildPercent}% | PoC ${model.coverage.pocDemonstrationPercent}%`,
      60, subtitleY, TYPE.subtitle.size, THEME.muted, 400, "header");
    this.lines(summary, 60, subtitleY + 22, TYPE.subtitle.size, THEME.muted, 400, "header", 20);
    this.add(`<path d="M 60 ${headerHeight} H ${this.width - 60}" stroke="${ZONE.stroke}" stroke-width="1"/>`);
    return headerHeight + 28;
  }
  legend(y, icons, model, architecture = false, sequenceBands = [], sequenceLinks = null) {
    const legendId = "legend";
    const byId = new Map(model.components.map(c => [c.id, c]));
    const links = architecture ? model.relationships : sequenceLinks || model.sequence;
    const shown = architecture ? model.components : model.components.filter(c => links.some(l => l.from === c.id || l.to === c.id));
    const meanings = [...new Set(links.map(edge => style.linkMeaning(edge, byId)))];
    const entries = [
      ...[...new Set(shown.map(style.componentTone))]
        .map(name => style.KIND_LEGEND.find(([key]) => key === name))
        .filter(Boolean).map(([name, text]) => ({ text, card: name })),
      ...Object.entries(style.MEANINGS).filter(([key]) => meanings.includes(key))
        .map(([, meaning]) => ({ text: meaning.label, color: PALETTE[meaning.tone].line })),
      ...(links.some(edge => edge.style === "response" || edge.style === "optional" || edge.type === "response") ?
        [{ text: architecture ? "Response / optional" : "Response", color: THEME.gray, dash: DASH.response }] : []),
      ...(links.some(edge => ["simulated", "manual", "deferred"].includes(edge.implementationMode)) ?
        [{ text: "Simulated, manual or deferred", color: THEME.gray, dash: DASH.pending }] : []),
      ...(architecture && model.relationships.some(edge => edge.direction === "bidirectional")
        ? [{ text: "Bidirectional", color: THEME.gray, bidirectional: true }] : []),
      ...(architecture && model.components.some(c => style.componentTone(c) !== "red" && PENDING_STATUS.has(c.implementationStatus)) ?
        [{ text: "Dashed card: not built as production", card: "slate", dashedCard: true }] : []),
      ...sequenceBands.map(name => ({ text: { red: "Failure / rejection branch", green: "Success / approval branch",
        amber: "Conditional branch", slate: "Alternative branch" }[name], card: name })),
      { text: "Official Microsoft icon", icon: [...icons.values()].find(icon => icon.verified && icon.displayName) ||
        [...icons.values()].find(icon => icon.verified) },
      ...([...icons.values()].some(icon => !icon.verified) ?
        [{ text: "Generic component (not a product icon)", icon: [...icons.values()].find(icon => !icon.verified) }] : []),
    ].filter(entry => entry.color || entry.icon || entry.card);
    let x = 82;
    let row = 0;
    const slots = entries.map(entry => {
      const width = 56 + this.typography.measure(entry.text, TYPE.legend.size).width;
      if (x + width > this.width - 82) { row++; x = 82; }
      const slot = { ...entry, x, y: y + 58 + row * 34 };
      x += width + 30;
      return slot;
    });
    const height = 80 + row * 34;
    this.add(`<g data-kind="legend" data-id="${legendId}" ${boxAttrs({ x: 60, y, width: this.width - 120, height })}>`);
    this.rect({ x: 60, y, width: this.width - 120, height }, THEME.paper, ZONE.stroke, style.RADIUS.card, `stroke-width="${STROKE.card}"`);
    this.text("HOW TO READ THIS DIAGRAM", 82, y + 28, TYPE.kicker.size, THEME.muted, TYPE.kicker.weight, legendId);
    for (const slot of slots) {
      if (slot.icon) this.image(slot.icon, slot.x + 4, slot.y - 18, 22);
      else if (slot.card) {
        const tone = PALETTE[slot.card];
        this.rect({ x: slot.x, y: slot.y - 17, width: 32, height: 20 }, tone.fill, tone.border, 4,
          `stroke-width="${STROKE.card}"${slot.dashedCard ? ` stroke-dasharray="${DASH.response}"` : ""}`);
        this.rect({ x: slot.x, y: slot.y - 14, width: STROKE.accent, height: 14 }, tone.line, "none", 2);
      } else this.arrow([{ x: slot.x, y: slot.y - 6 }, { x: slot.x + 34, y: slot.y - 6 }], slot.color, slot.dash, "", slot.bidirectional);
      this.text(slot.text, slot.x + 44, slot.y, TYPE.legend.size, THEME.muted, TYPE.legend.weight, legendId);
    }
    this.add("</g>");
    return y + height + 36;
  }
  svg(height, title, description) {
    const defs = [...this.markers.entries()].map(([color, id]) =>
      `<marker id="${id}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" ` +
      `markerUnits="userSpaceOnUse" orient="auto"><path d="M 1 1 L 9 5 L 1 9 Z" fill="${color}"/></marker>` +
      `<marker id="${id}-start" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="9" markerHeight="9" ` +
      `markerUnits="userSpaceOnUse" orient="auto"><path d="M 9 1 L 1 5 L 9 9 Z" fill="${color}"/></marker>`).join("");
    return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" ` +
      `viewBox="0 0 ${this.width} ${Math.ceil(height)}" role="img" aria-labelledby="title desc">` +
      `<title id="title">${esc(title)}</title><desc id="desc">${esc(description)}</desc>` +
      `<defs>${defs}${this.typography.fontFace(title + description + this.parts.join(""))}</defs>` +
      `<rect width="${this.width}" height="${Math.ceil(height)}" fill="${THEME.background}"/>` +
      this.parts.join("\n") + "</svg>\n";
  }
}

function resolveIcons(model, manifest, manifestPath) {
  const definitions = new Map(manifest.icons.map(icon => [icon.key, icon]));
  const result = new Map();
  for (const component of model.components) {
    const key = definitions.has(component.iconKey) ? component.iconKey :
      manifest.aliases?.[component.iconKey.toLowerCase()] || "generic-component";
    const icon = definitions.get(key) || definitions.get("generic-component");
    if (!icon) throw new Error("Packaged generic icon is missing");
    const file = path.resolve(path.dirname(manifestPath), icon.file);
    const mime = path.extname(file).toLowerCase() === ".png" ? "image/png" : "image/svg+xml";
    const uri = `data:${mime};base64,${fs.readFileSync(file).toString("base64")}`;
    result.set(component.id, {
      key: icon.key, file: icon.file, uri, source: icon.sourcePack,
      verified: Boolean(icon.official), displayName: icon.displayName,
    });
  }
  return result;
}

function memberNames(component) {
  return [...new Set([...(component.members || []), ...(component.inventoryNames || [])])];
}

function prepareCard(component, width, typography, hero = false, compact = false, icon = {}, annotations = [], options = {}) {
  const { code = "", zoned = false } = options;
  const titleType = hero ? TYPE.heroTitle : TYPE.nodeTitle;
  const titleSize = titleType.size;
  const titleWeight = titleType.weight;
  const iconSize = hero ? ICON.hero : ICON.card;
  const titleWidth = width - iconSize - 56;
  const title = typography.wrap(component.name, titleWidth, titleSize, titleWeight);
  const titleLeading = hero ? 29 : 25;
  const product = productCaption(component, icon);
  const productLines = typography.wrap(product, titleWidth, 14);
  const titleHeight = Math.max(iconSize, title.length * titleLeading + productLines.length * 20);
  const legacy = component.description || "";
  const runtime = component.hostingRuntime || legacy.match(/Runtime:\s*([^]*?)(?:\.\s*Boundary:|$)/)?.[1]?.replace(/\.$/, "") || "";
  const boundary = boundaryOf(component);
  const role = component.roleDescription || legacy.replace(/\s*Runtime:[^]*$/, "").replace(/\s*Boundary:[^]*$/, "");
  const description = typography.wrap(role, width - 48, 14);
  const represented = new Set([component.name, product, component.productService, runtime, boundary].filter(Boolean));
  const canonicalMembers = memberNames(component);
  const members = canonicalMembers.filter(name => !represented.has(name)).map(name => ({
    name, lines: typography.wrap(name, width - 48, 14),
  }));
  const representedMembers = canonicalMembers.filter(name => represented.has(name));
  let nextY = 22 + CARD_HEAD + titleHeight + (description.length ? 22 : 4);
  const descriptionY = nextY;
  nextY += Math.max(0, description.length - 1) * 20;
  const membersY = nextY + (members.length ? 23 : 0);
  if (members.length) nextY = membersY +
    members.reduce((sum, member) => sum + member.lines.length * 20 + 3, 0) - 20;
  const details = [
    ...(component.productService && ![component.name, product].includes(component.productService) ?
      [{ label: "Service", value: component.productService }] : []),
    ...(runtime ? [{ label: "Runtime", value: runtime }] : []),
    // A painted deployment zone already names the boundary, unless it is also an inventory name.
    ...(boundary && !(zoned && !canonicalMembers.includes(boundary)) ? [{ label: "Boundary", value: boundary }] : []),
    ...(component.allowedToolScope?.allowedProducts?.length ?
      [{ label: "Allowed product", value: component.allowedToolScope.allowedProducts.join("; ") }] : []),
    ...(component.productionGaps || []).map(gap => ({ label: "Readiness gap",
      value: typeof gap === "string" ? gap : gap.description || gap.gap || gap.name || JSON.stringify(gap) })),
  ].map(detail => ({ ...detail, lines: typography.wrap(`${detail.label}: ${detail.value}`, width - 48, 11) }));
  const detailsY = nextY + (details.length ? 22 : 0);
  if (details.length) nextY = detailsY + details.reduce((sum, d) => sum + d.lines.length * 16 + 3, 0) - 16;
  nextY += 28;
  const owner = `${STATUS[component.implementationStatus] || component.implementationStatus} · ${OWNERS[component.buildOwner] || component.buildOwner || "Owner TBD"} · PoC ${component.pocScope || "TBD"}`;
  const metadata = [
    ...typography.wrap(owner, width - 48, 11),
    ...typography.wrap(`${PRODUCTION[component.productionStatus] || component.productionStatus || "Readiness TBD"} · ID ${component.id}`, width - 48, 11),
  ];
  const metadataY = nextY;
  nextY += Math.max(0, metadata.length - 1) * 16 + 20;
  const scopes = annotations.map(annotation => {
    const arrow = annotation.direction === "bidirectional" ? "↔" : "→";
    const text = `${annotation.code ? `${annotation.code} · ` : ""}${annotation.id} · ${annotation.from} ${arrow} ${annotation.to} · ${annotation.style} / ${annotation.implementationMode}`;
    const lines = typography.wrap(text, width - 48, 11);
    const labelLines = typography.wrap(annotation.label, width - 48, 13);
    const scope = { ...annotation, y: nextY + 10, lines, labelLines };
    nextY += 10 + lines.length * 16 + labelLines.length * 18 + 12;
    return scope;
  });
  if (!icon.verified) nextY += 16;
  return {
    id: component.id, component, width, height: Math.max(hero ? 200 : compact ? 128 : 148, nextY),
    title, titleSize, titleWeight, titleLeading, titleHeight, productLines, description, members, descriptionY,
    membersY, representedMembers, canonicalMembers, details, detailsY, scopes,
    metadataY, metadata, iconSize, hero, icon, code, tag: style.TREATMENT_TAGS[component.implementationStatus] || "",
    x: 0, y: 0,
  };
}

function productCaption(component, icon) {
  if (!icon.displayName) return "";
  const normalize = text => text.toLowerCase().replace(/[^a-z0-9]/g, "");
  const product = normalize(icon.displayName);
  return [component.name, ...memberNames(component)].some(value => normalize(value).includes(product))
    ? "" : icon.displayName;
}

function renderCard(drawing, card) {
  const c = card.component;
  const renderedMembers = new Set();
  const membership = (values, draw) => {
    const names = card.representedMembers.filter(name => values.includes(name) && !renderedMembers.has(name));
    names.forEach(name => renderedMembers.add(name));
    for (const name of names) drawing.add(`<g data-kind="member" data-name="${esc(name)}">`);
    draw();
    for (const name of names) drawing.add("</g>");
  };
  drawing.add(`<g id="node-${esc(c.id)}" data-kind="node" data-component-id="${esc(c.id)}" ` +
    `data-component-kind="${c.kind}" data-parent="${c.layer}" data-implementation-status="${c.implementationStatus}" ` +
    `data-story-role="${esc(card.storyRole || "component")}" ` +
    `data-build-owner="${esc(c.buildOwner || "")}" data-poc-scope="${esc(c.pocScope || "")}" ` +
    `data-production-status="${esc(c.productionStatus || "")}" data-deployment-boundary="${esc(boundaryOf(c))}" ` +
    `data-visual-role="${esc(visualRole(c))}" data-visual-group="${esc(visualGroup(c))}" ` +
    `data-members-count="${card.canonicalMembers.length}" ${boxAttrs(card)}>`);
  const tone = PALETTE[style.componentTone(c)];
  const pending = PENDING_STATUS.has(c.implementationStatus);
  drawing.rect(card, tone.fill, card.hero ? tone.line : tone.border, style.RADIUS.card,
    `stroke-width="${card.hero ? STROKE.hero : STROKE.card}"${pending ? ` stroke-dasharray="${DASH.response}"` : ""}`);
  drawing.rect({ x: card.x, y: card.y + 11, width: STROKE.accent, height: card.height - 22 }, tone.line, "none", 2);
  drawing.image(card.icon, card.x + 22, card.y + 22 + CARD_HEAD, card.iconSize);
  // The product name is the first painted text so it keeps the >=14px heading minimum.
  membership([c.name], () => drawing.lines(card.title, card.x + card.iconSize + 34, card.y + 42 + CARD_HEAD, card.titleSize,
    THEME.ink, card.titleWeight, c.id, card.titleLeading, false, "card-title"));
  membership([productCaption(c, card.icon)], () => drawing.lines(card.productLines, card.x + card.iconSize + 34,
    card.y + 42 + CARD_HEAD + card.title.length * card.titleLeading, 14, THEME.muted, 400,
    c.id, 20, false, "product-title"));
  if (card.code) drawing.text(card.code, card.x + 22, card.y + 25, TYPE.nodeCode.size, tone.line, TYPE.nodeCode.weight, c.id, false, "component-code");
  if (card.tag) drawing.text(card.hero ? `PRIMARY AGENT · ${card.tag}` : card.tag, card.x + card.width - 20, card.y + 25,
    TYPE.nodeCode.size, THEME.muted, TYPE.nodeCode.weight, c.id, false, "treatment", true);
  drawing.lines(card.description, card.x + 24, card.y + card.descriptionY, 14,
    THEME.muted, 400, c.id, 20);
  if (card.members.length) {
    let y = card.y + card.membersY;
    for (const member of card.members) {
      drawing.add(`<g data-kind="member" data-name="${esc(member.name)}">`);
      drawing.lines(member.lines, card.x + 24, y, 14, THEME.muted, 400, c.id, 20);
      drawing.add("</g>");
      y += member.lines.length * 20 + 3;
    }
  }
  let detailY = card.y + card.detailsY;
  for (const detail of card.details) {
    membership([detail.value], () => drawing.lines(detail.lines, card.x + 24, detailY, 11, THEME.muted, 400, c.id, 16, false, "metadata"));
    detailY += detail.lines.length * 16 + 3;
  }
  drawing.add(`<path d="M ${card.x + 24} ${card.y + card.metadataY - 17} H ${card.x + card.width - 24}" ` +
    `stroke="${THEME.border}" stroke-width=".7"/>`);
  drawing.lines(card.metadata, card.x + 24, card.y + card.metadataY, 11,
    THEME.muted, 400, c.id, 16, false, "metadata");
  for (const scope of card.scopes) {
    const color = scope.color || THEME.gray;
    drawing.add(`<g data-kind="control-annotation" data-id="${esc(scope.id)}" ` +
      `data-from="${esc(scope.from)}" data-to="${esc(scope.to)}" data-style="${esc(scope.style)}" ` +
      `data-direction="${esc(scope.direction || "unidirectional")}" ` +
      `data-relationship-type="${esc(scope.relationshipType || "")}" ` +
      `data-label="${esc(scope.label)}" data-implementation-mode="${esc(scope.implementationMode)}">`);
    drawing.lines(scope.lines, card.x + 24, card.y + scope.y, 11, color, 600, c.id, 16, false, "control-scope");
    drawing.lines(scope.labelLines, card.x + 24, card.y + scope.y + scope.lines.length * 16 + 2,
      13, color, 400, c.id, 18, false, "control-purpose");
    drawing.add("</g>");
  }
  if (!card.icon.verified) drawing.text("Generic component", card.x + 24, card.y + card.height - 13,
    11, THEME.muted, 400, c.id);
  drawing.add("</g>");
}

function crossingBridges(routes) {
  const bridges = new Map(routes.map(route => [route.id, []]));
  for (let i = 0; i < routes.length; i++) {
    const first = routes[i];
    for (let j = i + 1; j < routes.length; j++) {
      const second = routes[j];
      if ([first.sourceId, first.targetId].some(id => [second.sourceId, second.targetId].includes(id))) continue;
      for (let a = 1; a < first.points.length; a++) {
        for (let b = 1; b < second.points.length; b++) {
          const [a1, a2] = [first.points[a - 1], first.points[a]];
          const [b1, b2] = [second.points[b - 1], second.points[b]];
          const aVertical = Math.abs(a1.x - a2.x) < .1;
          const bVertical = Math.abs(b1.x - b2.x) < .1;
          if (aVertical === bVertical) continue;
          const [v1, v2, h1, h2] = aVertical ? [a1, a2, b1, b2] : [b1, b2, a1, a2];
          const x = v1.x;
          const y = h1.y;
          if (x > Math.min(h1.x, h2.x) && x < Math.max(h1.x, h2.x) &&
              y > Math.min(v1.y, v2.y) && y < Math.max(v1.y, v2.y)) {
            const list = bridges.get(second.id);
            if (!list.some(point => Math.abs(point.x - x) < .1 && Math.abs(point.y - y) < .1)) {
              list.push({ x, y, vertical: bVertical });
            }
          }
        }
      }
    }
  }
  return bridges;
}

function relationshipLabel(edge, code) {
  const mode = style.MODE_WORDS[edge.implementationMode];
  return `${code} · ${mode ? `${mode} · ` : ""}${edge.label}`;
}

function architectureCandidate(model, icons, typography, profile, output, python, family) {
  const controlIds = new Set(model.components.filter(isCrossCutting).map(c => c.id));
  const byId = new Map(model.components.map(c => [c.id, c]));
  const relationships = identified(model.relationships, "relationship").map(({ id, record }) => ({ ...record, id }));
  const codes = style.relationshipCodes(relationships);
  const componentCodes = style.componentCodes(model);
  const scopes = new Map([...controlIds].map(id => [id, []]));
  const coverage = relationships.map(edge => {
    const control = controlIds.has(edge.from) ? edge.from : controlIds.has(edge.to) ? edge.to : null;
    const item = { ...edge, representation: control ? "scoped-control-annotation" : "routed", ...(control ? { owner: control } : {}) };
    if (control) scopes.get(control).push({ ...item, code: codes.get(edge.id), color: linkColor(edge, byId) });
    return item;
  });
  const labelType = TYPE.edgeLabel;
  const labelMeasures = new Map(model.relationships.map((edge, index) => {
    const lines = typography.wrap(relationshipLabel(edge, codes.get(relationships[index].id)), 160, labelType.size, labelType.weight);
    return [edge, {
      lines, labelWidth: Math.max(...lines.map(line => typography.measure(line, labelType.size, labelType.weight).width), 60) + 18,
      labelHeight: lines.length * 17 + 10,
    }];
  }));
  const composition = composeArchitecture(model, PROFILES[profile],
    (c, width, hero, compact) => prepareCard(c, width, typography, hero, compact, icons.get(c.id), scopes.get(c.id) || [],
      { code: componentCodes.get(c.id), zoned: family === "boundary" && !isCrossCutting(c) && Boolean(boundaryOf(c)) }), 0,
    edge => ({ width: labelMeasures.get(edge).labelWidth, height: labelMeasures.get(edge).labelHeight }), family);
  const { width, cards } = composition;
  const drawing = new Drawing(width, typography);
  const top = drawing.header(model, "Engineering Architecture", false);
  const zones = composition.zones || [];
  for (const item of [...cards, ...composition.regions, ...composition.headings, ...zones]) item.y += top;
  const bottom = composition.bottom + top;
  const cardById = new Map(cards.map(card => [card.id, card]));
  const activeEdges = relationships.filter(edge => !controlIds.has(edge.from) && !controlIds.has(edge.to));
  const edgeInputs = activeEdges.map((edge, index) => {
    const source = cardById.get(edge.from);
    const target = cardById.get(edge.to);
    const sourceColumn = composition.columns.findIndex(ids => ids.includes(edge.from));
    const targetColumn = composition.columns.findIndex(ids => ids.includes(edge.to));
    const forward = sourceColumn >= 0 && targetColumn === sourceColumn + 1 &&
      Math.max(source.y, target.y) < Math.min(source.y + source.height, target.y + target.height);
    const returning = targetColumn >= 0 && sourceColumn > targetColumn && edge.style !== "call" &&
      Math.max(source.y, target.y) < Math.min(source.y + source.height, target.y + target.height);
    const supportChain = source.storyRole === "supporting" && target.storyRole === "supporting" &&
      Math.abs(source.y + source.height / 2 - target.y - target.height / 2) < .5 &&
      source.x + source.width < target.x &&
      !cards.some(card => card !== source && card !== target &&
        card.x > source.x && card.x < target.x &&
        card.y < source.y + source.height / 2 && card.y + card.height > source.y + source.height / 2);
    const hub = source.storyRole === "main-flow" ? source : target.storyRole === "main-flow" ? target : null;
    const satellite = hub === source ? target : source;
    const fanout = hub && satellite.storyRole === "supporting" && satellite.y > hub.y + hub.height;
    const hubOffset = fanout ? Math.max(.18, Math.min(.82,
      (satellite.x + satellite.width / 2 - hub.x) / hub.width)) : .5;
    return {
      id: edge.id, sourceId: edge.from, targetId: edge.to,
      label: edge.label, ...labelMeasures.get(model.relationships[relationships.indexOf(edge)]), edge,
      ...(forward || supportChain ? {
        sourceSide: source.x < target.x ? "right" : "left",
        targetSide: source.x < target.x ? "left" : "right",
        sourceOffset: source.component.kind === "actor" ?
          Math.max(.2, Math.min(.8, (target.y + target.height / 2 - source.y) / source.height)) : .5,
        targetOffset: source.component.kind === "channel" ?
          Math.max(.2, Math.min(.8, (source.y + source.height / 2 - target.y) / target.height)) : .5,
      } : returning ? {
        sourceSide: "top", targetSide: "top", sourceOffset: .5, targetOffset: .5,
      } : fanout ? {
        sourceSide: hub === source ? "bottom" : "top",
        targetSide: hub === source ? "top" : "bottom",
        sourceOffset: hub === source ? hubOffset : .5,
        targetOffset: hub === source ? .5 : hubOffset,
      } : {}),
    };
  });
  for (const item of edgeInputs) {
    const parallel = edgeInputs.filter(other => other.sourceId === item.sourceId && other.targetId === item.targetId);
    if (parallel.length > 1) {
      const offset = .2 + .6 * parallel.indexOf(item) / (parallel.length - 1);
      if (item.sourceSide) item.sourceOffset = offset;
      if (item.targetSide) item.targetOffset = offset;
    } else {
      item.preferredSourceSide = item.sourceSide;
      item.preferredTargetSide = item.targetSide;
      for (const key of ["sourceSide", "targetSide", "sourceOffset", "targetOffset"]) delete item[key];
    }
  }
  for (const region of composition.regions) {
    drawing.add(`<g data-kind="semantic-layer" data-id="${region.id}" ${boxAttrs(region)}/>`);
  }
  // Dashed zones are evidenced deployment boundaries; links leaving a zone cross a trust boundary.
  const paintedZones = zones.filter(zone => zone.painted);
  for (const zone of paintedZones) {
    drawing.add(`<g data-kind="zone" data-id="${esc(zone.id)}" data-name="${esc(zone.name)}" ` +
      `data-components="${esc(JSON.stringify(zone.cardIds))}" ${boxAttrs(zone)}>`);
    drawing.rect(zone, ZONE.fill, ZONE.stroke, ZONE.radius, `stroke-width="${STROKE.zone}" stroke-dasharray="${DASH.zone}"`);
    drawing.add("</g>");
  }
  const controlCards = cards.filter(card => card.storyRole === "control");
  let controlBand = null;
  if (controlCards.length) {
    const topEdge = Math.min(...controlCards.map(card => card.y)) - 48;
    const band = { x: 48, y: topEdge, width: width - 96,
      height: Math.max(...controlCards.map(card => card.y + card.height)) + 24 - topEdge };
    controlBand = band;
    drawing.add(`<g data-kind="control-band" data-id="cross-cutting-controls" ` +
      `data-components="${esc(JSON.stringify(controlCards.map(card => card.id)))}" ${boxAttrs(band)}>`);
    drawing.rect(band, PALETTE.slate.fill, PALETTE.slate.border, ZONE.radius, `stroke-width="${STROKE.zone}"`);
    drawing.add("</g>");
  }
  for (const [index, heading] of composition.headings.entries()) {
    drawing.text(heading.text, heading.x, heading.y, TYPE.zoneTitle.size, /^\d/.test(heading.text) ? PALETTE.blue.line : ZONE.title,
      TYPE.zoneTitle.weight, `heading-${index}`, false, "section-title");
  }
  const input = {
    canvasWidth: width, canvasHeight: bottom + 180, routePadding: 12,
    nodes: cards.map(({ id, x, y, width, height }) => ({ id, x, y, width, height })),
    edges: edgeInputs.map(({ lines, edge, ...item }) => item),
    labelExclusions: [
      { x: 0, y: 0, width, height: top - 8 },
      ...drawing.texts.map(text => ({ x: text.x - 6, y: text.y - 6, width: text.width + 12, height: text.height + 12 })),
      ...(controlBand ? [controlBand] : []),
      { x: 0, y: bottom, width, height: 180 },
    ],
    routingExclusions: [
      { x: 0, y: 0, width, height: top - 8 },
      { x: 0, y: bottom, width, height: 180 },
      ...(controlBand ? [controlBand] : []),
      ...drawing.texts.map(text => ({
        x: text.x - 6, y: text.y - 6, width: text.width + 12, height: text.height + 12,
      })),
    ],
  };
  const inputFile = path.join(output, `.layout-${profile}-${family}-input.json`);
  const outputFile = path.join(output, `.layout-${profile}-${family}-output.json`);
  fs.writeFileSync(inputFile, JSON.stringify(input));
  fs.rmSync(outputFile, { force: true });
  const helper = path.join(__dirname, "..", "scripts", "layout_engine.py");
  const result = spawnSync(python, [helper, inputFile, outputFile], { encoding: "utf8", timeout: 120000, windowsHide: true });
  if (result.error) throw result.error;
  if (!fs.existsSync(outputFile)) throw new Error(`Python layout router produced no result: ${result.stderr}`);
  const layout = readJson(outputFile);
  if (result.status !== 0 || layout.issues?.length) {
    throw new Error(`Python routing failed: ${(layout.issues || []).join("; ")} ${result.stderr || ""}`.trim());
  }
  const routeById = new Map(layout.routes.map(route => [route.id, route]));
  const bridges = crossingBridges(layout.routes);
  const edgeLabels = [];
  for (const item of edgeInputs) {
    const route = routeById.get(item.id);
    if (!route || route.points.length < 2) throw new Error(`Missing Python layout route: ${item.id}`);
    const { edge } = item;
    const color = linkColor(edge, byId);
    drawing.add(`<g data-kind="connector" data-id="${esc(item.id)}" data-from="${esc(edge.from)}" data-to="${esc(edge.to)}" ` +
      `data-label="${esc(edge.label)}" data-code="${esc(codes.get(item.id))}" data-style="${esc(edge.style)}" ` +
      `data-meaning="${style.linkMeaning(edge, byId)}" ` +
      `data-direction="${esc(edge.direction || "unidirectional")}" ` +
      `data-relationship-type="${esc(edge.relationshipType || "")}" ` +
      `data-implementation-mode="${edge.implementationMode}" data-route="${route.points.map(p => `${p.x},${p.y}`).join(";")}">`);
    drawing.arrow(route.points, color, style.linkPattern(edge), "", edge.direction === "bidirectional");
    for (const bridge of bridges.get(route.id) || []) {
      drawing.add(`<g data-kind="connector-bridge" data-x="${number(bridge.x)}" data-y="${number(bridge.y)}">`);
      drawing.add(`<circle cx="${number(bridge.x)}" cy="${number(bridge.y)}" r="6" fill="${THEME.background}"/>`);
      const arc = bridge.vertical ?
        `M ${bridge.x} ${bridge.y - 7} Q ${bridge.x + 10} ${bridge.y} ${bridge.x} ${bridge.y + 7}` :
        `M ${bridge.x - 7} ${bridge.y} Q ${bridge.x} ${bridge.y - 10} ${bridge.x + 7} ${bridge.y}`;
      drawing.add(`<path d="${arc}" fill="none" stroke="${color}" stroke-width="${STROKE.edge}"/>`);
      drawing.add("</g>");
    }
    drawing.add("</g>");
    edgeLabels.push({ item, route, color });
  }
  cards.forEach(card => renderCard(drawing, card));
  for (const { item, route, color } of edgeLabels) {
    const box = {
      x: route.labelX - item.labelWidth / 2, y: route.labelY - item.labelHeight / 2,
      width: item.labelWidth, height: item.labelHeight,
    };
    const id = `label-${item.id}`;
    drawing.add(`<g data-kind="connector-label" data-id="${id}" data-owner="${item.id}" ${boxAttrs(box)}>`);
    drawing.rect(box, THEME.background, "none", style.RADIUS.label);
    drawing.lines(item.lines, route.labelX, box.y + 18, labelType.size, color, labelType.weight, id, 17, true, "connector-text");
    drawing.add("</g>");
  }
  let summaryY = bottom;
  const boundaries = (model.trustBoundaries || []).map((boundary, index) => ({
    id: boundary.id || `boundary-${index + 1}`,
    name: boundary.name || boundary.label || boundary.id || `Boundary ${index + 1}`,
    componentIds: boundary.component_ids || boundary.componentIds || [],
    controls: boundary.controls || [], description: boundary.description || "",
  }));
  if (model.allowedTools?.length) boundaries.push({
    id: "allowed-tool-boundary", name: "Allowed-tool boundary", componentIds: [],
    controls: [], description: model.allowedTools.join("; "),
  });
  if (boundaries.length) {
    drawing.text("EVIDENCED BOUNDARY SCOPES", 72, summaryY + 18, TYPE.zoneTitle.size, ZONE.title, TYPE.zoneTitle.weight, "boundary-heading");
    summaryY += 48;
    for (const boundary of boundaries) {
      const detail = [
        `${boundary.name} [${boundary.id}]`,
        boundary.componentIds.length ? `Components: ${boundary.componentIds.join(", ")}` : "",
        boundary.description,
        boundary.controls.length ? `Controls: ${boundary.controls.map(control =>
          typeof control === "string" ? control : JSON.stringify(control)).join("; ")}` : "",
      ].filter(Boolean).join(" · ");
      const lines = typography.wrap(detail, width - 144, 13);
      drawing.add(`<g data-kind="trust-boundary" data-id="${esc(boundary.id)}" ` +
        `data-components="${esc(JSON.stringify(boundary.componentIds))}">`);
      drawing.lines(lines, 72, summaryY, 13, THEME.muted, 400, `boundary-${boundary.id}`, 19, false, "boundary-scope");
      drawing.add("</g>");
      summaryY += lines.length * 19 + 18;
    }
    summaryY += 10;
  }
  const statement = TYPE.statement;
  const summary = typography.wrap(model.summary, width - 192, statement.size, statement.weight);
  const summaryHeight = summary.length * 26 + 38;
  drawing.rect({ x: 60, y: summaryY, width: width - 120, height: summaryHeight }, THEME.ink, "none", style.RADIUS.card);
  drawing.lines(summary, width / 2, summaryY + 34, statement.size, THEME.paper, statement.weight, "architecture-summary", 26, true);
  const height = drawing.legend(summaryY + summaryHeight + 22, icons, model, true);
  const quality = visualQuality({ model, cards, drawing, layout, width, height: Math.ceil(height), coverage });
  const svg = drawing.svg(height, `${model.title} - Engineering Architecture`, model.summary);
  // Deployment boundaries are only legible as zones; unzoned layouts of multi-boundary
  // designs remain valid but rank below an equally clean zoned layout.
  const evidencedBoundaries = new Set(cards.filter(card => card.storyRole !== "control")
    .map(card => boundaryOf(card.component)).filter(Boolean));
  const zonePenalty = evidencedBoundaries.size >= 2 && !paintedZones.length ? 8 : 0;
  const conformance = style.styleConformance(svg);
  const styleGate = { name: "style-conformance", actual: conformance.issues, limit: 0,
    passed: conformance.validation === "passed",
    reason: "Every colour, stroke width and font size comes from the shared review style tokens (renderer/style.js)." };
  const gates = [...quality.gates, styleGate];
  const issues = [...quality.issues, ...(styleGate.passed ? [] : [`style-conformance: ${conformance.issues.join("; ")}`])];
  return {
    svg, layout, drawing,
    width, height: Math.ceil(height),
    quality: {
      ...quality, gates, issues, validation: issues.length ? "failed" : "passed",
      score: Math.round(Math.max(0, quality.score - zonePenalty - (styleGate.passed ? 0 : 15)) * 10000) / 10000,
      zones: { evidencedBoundaries: [...evidencedBoundaries], painted: paintedZones.map(zone => ({
        id: zone.id, name: zone.name, componentIds: zone.cardIds })), penalty: zonePenalty },
      componentCodes: Object.fromEntries(componentCodes), relationshipCodes: Object.fromEntries(codes),
      bridgeCount: [...bridges.values()].reduce((sum, list) => sum + list.length, 0),
      textMeasurement: "resvg / bundled Inter",
      composition: {
        strategy: composition.strategy, spine: composition.spine, columns: composition.columns,
        family,
        mainRowCount: composition.mainRowCount, supportRowCount: composition.supportRowCount,
        visibleLayerContainers: 0,
        boundaryScopes: boundaries, presentationHints: model.presentation || {},
        widthHint: composition.widthHint,
      },
    },
  };
}

function architecture(model, icons, typography, profile, output, python = process.env.LISA_PYTHON || "python") {
  if (!PROFILES[profile]) throw new Error(`Unknown layout profile: ${profile}`);
  fs.mkdirSync(output, { recursive: true });
  const reportPath = path.join(output, `composition-candidates-${profile}.json`);
  const families = compositionFamilies(model);
  const report = { profile, selection: "highest passing score; preferred composition only breaks equal-score ties, then deterministic family order",
    familyOrder: families, candidates: [], selected: null, validation: "failed" };
  const passing = [];
  for (const family of families) {
    try {
      const candidate = architectureCandidate(model, icons, typography, profile, output, python, family);
      report.candidates.push({ family, ...candidate.quality,
        layoutInput: `.layout-${profile}-${family}-input.json`, layoutOutput: `.layout-${profile}-${family}-output.json` });
      if (candidate.quality.validation === "passed") passing.push(candidate);
    } catch (error) {
      const diagnosticFile = path.join(output, `.layout-${profile}-${family}-output.json`);
      let routing = null;
      try { if (fs.existsSync(diagnosticFile)) routing = readJson(diagnosticFile); } catch { /* Keep the original failure. */ }
      report.candidates.push({ family, validation: "failed", score: 0, issues: [String(error.message)],
        gates: [{ name: "routing", passed: false, actual: routing?.issues || [String(error.message)],
          limit: 0, reason: "A missing route or unplaceable label blocks this candidate; no relationships may disappear." }],
        routingMetrics: routing?.metrics || null,
        layoutInput: `.layout-${profile}-${family}-input.json`, layoutOutput: `.layout-${profile}-${family}-output.json` });
    }
    fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n");
  }
  passing.sort((a, b) => b.quality.score - a.quality.score);
  if (!passing.length) {
    throw new Error(`No ${profile} composition passed. Diagnostics preserved at ${reportPath}. ` +
      report.candidates.map(candidate => `${candidate.family}: ${candidate.issues.join("; ")}`).join("\n"));
  }
  const best = passing[0];
  report.selected = best.quality.composition.family;
  report.validation = "passed";
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n");
  best.quality.candidateReport = path.basename(reportPath);
  return best;
}

function sequenceParticipants(model) {
  const componentIds = new Set(model.components.map(component => component.id));
  const used = new Set(model.sequence.flatMap(message => [message.from, message.to]));
  const declared = model.sequenceParticipants;
  if (declared != null && !Array.isArray(declared)) throw new Error("sequenceParticipants must be an array");
  const participants = declared == null ? model.components.map(component => component.id).filter(id => used.has(id)) :
    declared.map(item => item && typeof item === "object" ?
      (Object.prototype.hasOwnProperty.call(item, "componentId") ? item.componentId : item.id) : item);
  if (participants.some(id => !componentIds.has(id))) throw new Error("Unknown sequence participant");
  if (new Set(participants).size !== participants.length) throw new Error("Duplicate sequence participants");
  if ([...used].some(id => !participants.includes(id))) throw new Error("Message endpoint missing from sequence participants");
  if (participants.length < 2 || participants.length > 8) throw new Error("Sequence requires 2-8 participants");
  return participants;
}

function sequenceDiagram(model, icons, typography, profile) {
  const sequenceRecords = identified(model.sequence, "sequence");
  const participants = sequenceParticipants(model);
  const byId = new Map(model.components.map(c => [c.id, c]));
  const width = Math.min(2200, Math.max(PROFILES[profile].width, participants.length * 232 + 120));
  const drawing = new Drawing(width, typography);
  const top = drawing.header(model, "Sequence Diagram");
  const codes = style.componentCodes(model);
  const relationshipById = new Map(identified(model.relationships, "relationship").map(({ id, record }) => [id, record]));
  // Evenly spaced lanes leave the left rail free for numbered step markers.
  const railLeft = 84;
  const railRight = width - 40;
  const span = participants.length > 1 ? Math.min(railRight - railLeft - 220, (participants.length - 1) * 400) : 0;
  const pitch = participants.length > 1 ? span / (participants.length - 1) : 0;
  const headerWidth = participants.length > 1 ? Math.min(220, pitch - 28) : 220;
  const firstCenter = (railLeft + railRight) / 2 - span / 2;
  const headers = participants.map((id, index) => {
    const c = byId.get(id);
    const center = firstCenter + index * pitch;
    return {
      component: c, id, x: center - headerWidth / 2, width: headerWidth, center,
      tone: PALETTE[style.componentTone(c)],
      nameLines: typography.wrap(c.name, headerWidth - 28, TYPE.laneTitle.size, TYPE.laneTitle.weight),
      productLines: typography.wrap(productCaption(c, icons.get(c.id)), headerWidth - 28, 12),
      codeLine: `${codes.get(c.id)} · ${c.kind.toUpperCase()}`,
      tag: style.TREATMENT_TAGS[c.implementationStatus] || "",
    };
  });
  const headerHeight = Math.max(...headers.map(h => 58 + h.nameLines.length * 19 + h.productLines.length * 16));
  const xById = new Map(headers.map(h => [h.id, h.center]));
  const phaseGroups = [];
  model.sequence.forEach((message, index) => {
    const phaseName = message.phase || "Interaction";
    if (!phaseGroups.length || phaseGroups.at(-1).name !== phaseName) {
      phaseGroups.push({ name: phaseName, messages: [] });
    }
    phaseGroups.at(-1).messages.push({ message, number: index + 1,
      order: message.order ?? index + 1, id: sequenceRecords[index].id });
  });
  let cursor = top + headerHeight + 42;
  const rows = [];
  phaseGroups.forEach((phase, phaseIndex) => {
    phase.id = `phase-${phaseIndex}`;
    phase.y = cursor;
    phase.compact = phase.messages.length === 1;
    cursor += phase.compact ? 48 : 62;
    let previousFragment = "";
    for (const entry of phase.messages) {
      const { message } = entry;
      const self = message.from === message.to || message.type === "self";
      const fromX = xById.get(message.from);
      const toX = xById.get(message.to);
      const span = Math.abs(toX - fromX);
      const labelWidth = self ? Math.min(300, headerWidth + 40) : Math.min(440, Math.max(150, span - 24));
      const prefix = message.implementationMode === "simulated" && !/simulat/i.test(message.label) ? "Simulated: " : "";
      const fragment = message.fragment || "";
      const condition = message.condition && !fragment.includes(message.condition) ? ` Condition: ${message.condition}` : "";
      const label = `${prefix}${message.label}${condition}`;
      const lines = typography.wrap(label, labelWidth - 22, TYPE.messageCopy.size, TYPE.messageCopy.weight);
      if (fragment && fragment !== previousFragment) cursor += 38;
      const labelHeight = lines.length * 18 + 10;
      let center = self ? fromX + (fromX > width * .75 ? -65 : 65) : (fromX + toX) / 2;
      center = Math.max(82 + labelWidth / 2, Math.min(width - 82 - labelWidth / 2, center));
      const row = {
        ...entry, self, fromX, toX, lines, labelWidth, labelHeight, center,
        labelY: cursor, y: cursor + labelHeight + 14, phase: phase.id,
        fragmentStart: Boolean(fragment && fragment !== previousFragment), fragment,
      };
      rows.push(row);
      cursor = row.y + (self ? 48 : 32);
      previousFragment = fragment;
    }
    phase.height = cursor - phase.y + 10;
    cursor += phase.compact ? 16 : 34;
  });
  rows.forEach((row, index) => {
    if (!row.fragmentStart) return;
    let last = row;
    for (let i = index + 1; i < rows.length; i++) {
      if (rows[i].phase !== row.phase || rows[i].fragment !== row.fragment) break;
      last = rows[i];
    }
    row.fragmentBottom = last.y + (last.self ? 44 : 22);
  });
  const lifelineEnd = cursor - 24;
  const fragmentTone = text => /reject|fail|error|timeout|den(y|ied)|exception|invalid|cancel|abort/i.test(text) ? "red" :
    /approv|accept|success|valid|confirm|complete|allow/i.test(text) ? "green" : /^(opt|loop|par)\b/i.test(text) ? "slate" : "amber";
  const bandTones = [...new Set(rows.filter(row => row.fragmentStart).map(row => fragmentTone(row.fragment)))];
  phaseGroups.forEach((phase, index) => {
    phase.title = `${String(index + 1).padStart(2, "0")}  ${phase.name.toUpperCase()}`;
    phase.headingWidth = Math.min(width - 120,
      typography.measure(phase.title, TYPE.zoneTitle.size, TYPE.zoneTitle.weight).width + 48);
    const box = { x: 60, y: phase.y, width: phase.compact ? phase.headingWidth : width - 120,
      height: phase.compact ? 42 : phase.height };
    drawing.add(`<g data-kind="phase" data-id="${phase.id}" data-message-count="${phase.messages.length}" ` +
      `data-treatment="${phase.compact ? "compact-label" : "multi-message-band"}" ${boxAttrs(box)}>`);
    drawing.rect(box, ZONE.fill, ZONE.stroke, phase.compact ? 21 : ZONE.radius,
      `stroke-width="${STROKE.zone}"${phase.compact ? "" : ` stroke-dasharray="${DASH.zone}"`}`);
    drawing.add("</g>");
  });
  for (const header of headers) {
    const c = header.component;
    const box = { x: header.x, y: top, width: header.width, height: headerHeight };
    drawing.add(`<g id="lifeline-${esc(c.id)}" data-kind="lifeline" data-component-id="${esc(c.id)}" ${boxAttrs(box)}>`);
    drawing.rect(box, header.tone.fill, header.tone.border, style.RADIUS.card, `stroke-width="${STROKE.card}"`);
    drawing.rect({ x: box.x + 12, y: box.y, width: box.width - 24, height: STROKE.accent }, header.tone.line, "none", 2);
    // Participant name is painted first so it carries the >=14px participant heading minimum.
    drawing.lines(header.nameLines, header.center, top + 58, TYPE.laneTitle.size, THEME.ink, TYPE.laneTitle.weight,
      c.id, 19, true, "participant-title");
    drawing.lines(header.productLines, header.center, top + 58 + header.nameLines.length * 19,
      12, THEME.muted, 400, c.id, 16, true, "product-caption");
    drawing.image(icons.get(c.id), box.x + 12, top + 14, 20);
    drawing.text(header.codeLine, box.x + 38, top + 29, TYPE.nodeCode.size, header.tone.line, TYPE.nodeCode.weight, c.id, false, "component-code");
    if (header.tag && typography.measure(header.codeLine, TYPE.nodeCode.size, TYPE.nodeCode.weight).width +
        typography.measure(header.tag, TYPE.nodeCode.size, TYPE.nodeCode.weight).width + 62 < header.width) {
      drawing.text(header.tag, box.x + box.width - 12, top + 29, TYPE.nodeCode.size, THEME.muted, TYPE.nodeCode.weight,
        c.id, false, "treatment", true);
    }
    drawing.add(`<line data-kind="lifeline-line" x1="${number(header.center)}" x2="${number(header.center)}" ` +
      `y1="${top + headerHeight}" y2="${lifelineEnd}" stroke="${PALETTE.slate.border}" stroke-width="${STROKE.card}" ` +
      `stroke-dasharray="${DASH.lifeline}"/>`);
    drawing.add("</g>");
  }
  phaseGroups.forEach(phase => {
    drawing.text(phase.title, 82, phase.y + 27, TYPE.zoneTitle.size, ZONE.title, TYPE.zoneTitle.weight, phase.id, false, "phase-title");
  });
  const sequenceLinks = [];
  for (const row of rows) {
    const relationship = relationshipById.get(row.message.relationshipId) ||
      model.relationships.find(edge => edge.from === row.message.from && edge.to === row.message.to && edge.style === "call") ||
      (row.message.type === "response" ? model.relationships.find(edge => edge.from === row.message.to && edge.to === row.message.from) : null);
    const link = { ...row.message, relationshipType: relationship?.relationshipType,
      style: row.message.type === "response" ? "response" : "call" };
    const color = linkColor(link, byId);
    sequenceLinks.push(link);
    const loop = row.fromX > width * .75 ? -72 : 72;
    const points = row.self ? [
      { x: row.fromX, y: row.y }, { x: row.fromX + loop, y: row.y },
      { x: row.fromX + loop, y: row.y + 26 }, { x: row.fromX, y: row.y + 26 },
    ] : [{ x: row.fromX, y: row.y }, { x: row.toX, y: row.y }];
    if (row.fragmentStart) {
      const tone = PALETTE[fragmentTone(row.fragment)];
      const box = { x: 74, y: row.labelY - 36, width: width - 148, height: row.fragmentBottom - row.labelY + 36 };
      drawing.add(`<g data-kind="fragment" data-id="fragment-${row.number}" data-tone="${fragmentTone(row.fragment)}" ${boxAttrs(box)}>`);
      drawing.rect(box, "none", tone.border, 8, `stroke-width="${STROKE.zone}" stroke-dasharray="${DASH.response}"`);
      drawing.rect({ x: box.x, y: box.y, width: box.width, height: 28 }, tone.fill, "none", 8);
      drawing.rect({ x: box.x, y: box.y + 4, width: STROKE.accent, height: 20 }, tone.line, "none", 2);
      drawing.text(row.fragment.toUpperCase(), 92, row.labelY - 17, TYPE.bandTitle.size, tone.line, TYPE.bandTitle.weight,
        `fragment-${row.number}`, false, "fragment-title");
      drawing.add("</g>");
    }
    drawing.add(`<g data-kind="message" data-from="${esc(row.message.from)}" data-to="${esc(row.message.to)}" ` +
      `data-id="${esc(row.id)}" data-order="${esc(row.order)}" data-occurrence="${row.number}" data-type="${esc(row.message.type)}" ` +
      `data-relationship-id="${esc(row.message.relationshipId || "")}" data-label="${esc(row.message.label)}" ` +
      `data-meaning="${style.linkMeaning(link, byId)}" ` +
      `data-condition="${esc(row.message.condition || "")}" data-action-control="${esc(JSON.stringify(row.message.actionControl || null))}" ` +
      `data-implementation-mode="${row.message.implementationMode}" ` +
      `data-route="${points.map(p => `${number(p.x)},${number(p.y)}`).join(";")}">`);
    drawing.rect({ x: row.toX - 3, y: row.y - 7, width: 6, height: row.self ? 40 : 26 }, color, "none", 2);
    drawing.arrow(points, color, style.linkPattern(link));
    const box = { x: row.center - row.labelWidth / 2, y: row.labelY, width: row.labelWidth, height: row.labelHeight };
    const labelId = `message-label-${row.number}`;
    drawing.add(`<g data-kind="message-label" data-id="${labelId}" ${boxAttrs(box)}>`);
    drawing.rect(box, THEME.paper, "none", style.RADIUS.label);
    drawing.lines(row.lines, row.center, row.labelY + 19, TYPE.messageCopy.size, color, TYPE.messageCopy.weight, labelId, 18, true);
    drawing.add("</g>");
    // Numbered rail: every step is findable from the left edge and in the narrative.
    drawing.add(`<g data-kind="step-marker" data-order="${esc(row.order)}">`);
    drawing.add(`<circle cx="34" cy="${number(row.y)}" r="13" fill="${color}"/>`);
    drawing.text(String(row.order), 34, row.y + 4, TYPE.stepNumber.size, THEME.paper, TYPE.stepNumber.weight,
      `step-${row.number}`, true, "step-number");
    drawing.add("</g></g>");
  }
  const height = drawing.legend(cursor + 8, icons, model, false, bandTones, sequenceLinks);
  const issues = [];
  for (const [index, text] of drawing.texts.entries()) {
    if (text.x < 4 || text.y < 4 || text.x + text.width > width - 4 || text.y + text.height > height - 4)
      issues.push(`Sequence text outside canvas: ${text.text}`);
    for (const other of drawing.texts.slice(index + 1)) {
      if (text.x < other.x + other.width - .1 && text.x + text.width > other.x + .1 &&
          text.y < other.y + other.height - .1 && text.y + text.height > other.y + .1)
        issues.push(`Sequence text overlaps: ${text.text} / ${other.text}`);
    }
  }
  const svg = drawing.svg(height, `${model.title} - Sequence Diagram`,
    "Ordered, evidence-grounded interactions with explicit implementation modes and human handoffs.");
  const conformance = style.styleConformance(svg);
  issues.push(...conformance.issues.map(issue => `Sequence style: ${issue}`));
  return { svg, drawing,
    width, height: Math.ceil(height), quality: { validation: issues.length ? "failed" : "passed", issues,
      styleConformance: conformance.validation,
      participantIds: participants,
      phaseCount: phaseGroups.length, compactPhaseCount: phaseGroups.filter(p => p.compact).length,
      fullWidthSingleMessagePanels: 0, messageCoverage: sequenceRecords.map(({ id, order, record }) => ({
        id, order: record.order ?? order, occurrence: order,
        from: record.from, to: record.to, type: record.type, implementationMode: record.implementationMode,
        relationshipId: record.relationshipId || null, condition: record.condition ?? null,
        actionControl: record.actionControl ?? null,
      })) } };
}

function validateEditableSources(model, modelPath, output, python = process.env.LISA_PYTHON || "python") {
  const names = ["source-report.json", `Design_${model.scenarioSlug}.drawio`,
    `BA_${model.scenarioSlug}.mmd`, `SA_${model.scenarioSlug}.mmd`, `SD_${model.scenarioSlug}.mmd`];
  if (!names.some(name => fs.existsSync(path.join(output, name)))) return { validation: "not-present", sources: false };
  // Reuse the read-only source gate; never regenerate or repair upstream source files here.
  const helper = path.join(__dirname, "..", "scripts", "source_artifacts.py");
  const result = spawnSync(python, [helper, "validate", "--model", modelPath, "--output", output],
    { encoding: "utf8", timeout: 30000, windowsHide: true, maxBuffer: 4 * 1024 * 1024 });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`Editable sources failed validation before presentation: ${result.stdout || ""} ${result.stderr || ""}`.trim());
  }
  let report;
  try { report = JSON.parse(result.stdout); } catch { throw new Error("Editable source validation returned no valid report"); }
  if (report.validation !== "passed") throw new Error("Editable source validation did not pass");
  return { validation: "passed", sources: true, report: "source-report.json" };
}

function main(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) args[argv[i].replace(/^--/, "")] = argv[i + 1];
  for (const required of ["model", "output", "icons", "references", "profile"]) {
    if (!args[required]) throw new Error(`Missing --${required}`);
  }
  if (!PROFILES[args.profile]) throw new Error("Unknown layout profile");
  const output = path.resolve(args.output);
  if (path.basename(output) !== "design") throw new Error("Output must be inside the design directory");
  const model = readJson(args.model);
  if (!/^[A-Za-z0-9_]+$/.test(model.scenarioSlug)) throw new Error("Invalid scenario slug");
  if (model.components.length < 2 || model.components.length > 30 ||
      model.relationships.length > 60 || model.sequence.length < 1 || model.sequence.length > 30)
    throw new Error("Diagram model exceeds supported bounds");
  const ids = new Set(model.components.map(c => c.id));
  if (ids.size !== model.components.length) throw new Error("Duplicate component IDs");
  for (const edge of [...model.relationships, ...model.sequence]) {
    if (!ids.has(edge.from) || !ids.has(edge.to)) throw new Error("Relationship references an unknown component");
  }
  if (!model.referenceKeys.includes("architecture-diagrams")) throw new Error("Missing architecture reference");
  const references = readJson(args.references);
  const sources = model.referenceKeys.map(key => {
    const entry = references.sources.find(source => source.key === key);
    if (!entry) throw new Error(`Unknown reference key: ${key}`);
    return entry.url;
  });
  fs.mkdirSync(output, { recursive: true });
  const sourceGate = validateEditableSources(model, args.model, output, args.python);
  const icons = resolveIcons(model, readJson(args.icons), args.icons);
  const typography = new Typography();
  const sa = architecture(model, icons, typography, args.profile, output, args.python);
  const sd = sequenceDiagram(model, icons, typography, args.profile);
  const ba = businessArchitecture(model, typography);
  sa.quality.sequence = sd.quality;
  sa.quality.business = ba.quality;
  if (sd.quality.validation !== "passed") {
    sa.quality.validation = "failed";
    fs.writeFileSync(path.join(output, `sequence-quality-${args.profile}.json`), JSON.stringify(sd.quality, null, 2));
    throw new Error(`Sequence visual quality failed: ${sd.quality.issues.join("; ")}`);
  }
  if (ba.quality.validation !== "passed") {
    sa.quality.validation = "failed";
    throw new Error(`Business architecture visual quality failed: ${ba.quality.issues.join("; ")}`);
  }
  const baPath = path.join(output, `BA_${model.scenarioSlug}.svg`);
  const saPath = path.join(output, `SA_${model.scenarioSlug}.svg`);
  const sdPath = path.join(output, `SD_${model.scenarioSlug}.svg`);
  const previewPath = path.join(output, "preview.html");
  fs.writeFileSync(baPath, ba.svg);
  fs.writeFileSync(saPath, sa.svg);
  fs.writeFileSync(sdPath, sd.svg);
  fs.writeFileSync(previewPath, createPreview(model, {
    business: { width: ba.width, height: ba.height },
    architecture: { width: sa.width, height: sa.height }, sequence: { width: sd.width, height: sd.height },
    sources: sourceGate.sources, references: sources,
  }));
  const manifest = {
    scenarioSlug: model.scenarioSlug, layoutProfile: args.profile, presentation: "architecture-review",
    layoutEngine: sa.layout.engine, businessArchitecture: baPath, solutionArchitecture: saPath, sequenceDiagram: sdPath,
    htmlPreview: "preview.html",
    editableSources: sourceGate,
    icons: model.components.map(c => ({
      component: c.name, componentId: c.id, icon: path.basename(icons.get(c.id).file),
      source: icons.get(c.id).source, verified: icons.get(c.id).verified,
    })),
    referenceSources: sources, generatedAt: new Date().toISOString(),
    typography: { font: "Inter", measured: true, minimumSize: 11 },
    style: {
      benchmark: "SDM Intelligent Operations Architecture Review",
      tokens: style.TOKENS,
      conformance: {
        business: ba.quality.styleConformance,
        architecture: sa.quality.gates.find(gate => gate.name === "style-conformance").passed ? "passed" : "failed",
        sequence: sd.quality.styleConformance,
      },
    },
    componentCodes: sa.quality.componentCodes, relationshipCodes: sa.quality.relationshipCodes,
    layoutQuality: sa.quality,
  };
  fs.writeFileSync(path.join(output, "diagram-manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  // Candidate diagnostics remain beside the model, even after a passing alternative is selected.
  process.stdout.write(JSON.stringify({
    BusinessArchitecture: baPath, SolutionArchitecture: saPath, SequenceDiagram: sdPath, HtmlPreview: previewPath,
    Manifest: path.join(output, "diagram-manifest.json"),
  }));
}

if (require.main === module) {
  try { main(process.argv.slice(2)); }
  catch (error) { process.stderr.write(`${error.stack || error}\n`); process.exitCode = 2; }
}
module.exports = { Drawing, THEME, PROFILES, prepareCard, architecture, sequenceDiagram, sequenceParticipants, validateEditableSources };
