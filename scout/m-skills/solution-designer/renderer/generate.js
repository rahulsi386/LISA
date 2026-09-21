const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { Typography, escapeXml: esc } = require("./typography");
const { composeArchitecture, boundaryOf, compositionFamilies, isCrossCutting, visualRole, visualGroup } = require("./composition");
const { createPreview } = require("./preview");
const { visualQuality, identified } = require("./quality");

const THEME = Object.freeze({
  background: "#F6F8FC", paper: "#FFFFFF", ink: "#16263F", muted: "#53647D",
  border: "#D4DDEB", blue: "#5365CD", green: "#0D776B", cyan: "#08788F",
  amber: "#9C620C", gray: "#606E82", red: "#B93848", purple: "#7651B5",
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

function number(value) { return Math.round(value * 100) / 100; }
function boxAttrs(box) {
  return `data-x="${number(box.x)}" data-y="${number(box.y)}" ` +
    `data-width="${number(box.width)}" data-height="${number(box.height)}"`;
}
function modeColor(mode, type = "call") {
  return ({ simulated: THEME.cyan, manual: THEME.amber, deferred: THEME.gray, blocked: THEME.red })[mode] ||
    (type === "approval" ? THEME.green : type === "self" ? THEME.purple : THEME.blue);
}
function componentColor(component) {
  const mode = {
    simulate: "simulated", "static-sample-data": "simulated",
    "manual-handoff": "manual", defer: "deferred", block: "blocked",
  }[component.implementationStatus];
  if (mode) return modeColor(mode);
  return component.kind === "agent" ? THEME.blue :
    component.kind === "human" ? THEME.green : THEME.border;
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
  rect(box, fill, stroke = "none", radius = 14, extras = "") {
    this.add(`<rect x="${number(box.x)}" y="${number(box.y)}" width="${number(box.width)}" ` +
      `height="${number(box.height)}" rx="${radius}" fill="${fill}" stroke="${stroke}" ${extras}/>`);
  }
  text(text, x, baseline, size = 14, color = THEME.muted, weight = 400, owner = "", center = false, role = "body") {
    if (!String(text).trim()) return;
    const glyph = this.typography.measure(text, size, weight);
    // Position the glyph extent rather than approximating character advance.
    const drawX = x - glyph.x - (center ? glyph.width / 2 : 0);
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
    this.add(`<image href="${icon.uri}" xlink:href="${icon.uri}" x="${number(x)}" y="${number(y)}" ` +
      `width="${size}" height="${size}" preserveAspectRatio="xMidYMid meet"/>`);
  }
  arrow(points, color, dashed = false, attributes = "") {
    if (!this.markers.has(color)) this.markers.set(color, `arrow-${this.markers.size}`);
    const marker = this.markers.get(color);
    this.add(`<path d="M ${points.map(p => `${number(p.x)} ${number(p.y)}`).join(" L ")}" ` +
      `fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" ` +
      `${dashed ? 'stroke-dasharray="7 5"' : ""} marker-end="url(#${marker})" ${attributes}/>`);
  }
  header(model, kind, includeSummary = true) {
    const title = this.typography.wrap(model.title, this.width - 180, 36, 600);
    const subtitleY = 124 + (title.length - 1) * 44;
    const summary = this.typography.wrap(includeSummary ? model.summary || "" : "", this.width - 120, 14);
    const headerHeight = subtitleY + 26 + summary.length * 20;
    this.rect({ x: 0, y: 0, width: this.width, height: headerHeight }, THEME.paper, "none", 0);
    this.text(`SOLUTION DESIGN / ${kind.toUpperCase()}`, 60, 39, 12, THEME.blue, 600, "header");
    this.lines(title, 60, 90, 36, THEME.ink, 600, "header", 44, false, "title");
    this.text(`${kind} | ${model.complexity} complexity | Native ${model.coverage.nativeBuildPercent}% | PoC ${model.coverage.pocDemonstrationPercent}%`,
      60, subtitleY, 15, THEME.muted, 400, "header");
    this.lines(summary, 60, subtitleY + 26, 14, THEME.muted, 400, "header", 20);
    return headerHeight + 28;
  }
  legend(y, icons, model, architecture = false) {
    const legendId = "legend";
    const entries = [
      { text: "Official Microsoft icon", icon: [...icons.values()].find(icon => icon.verified && icon.displayName) ||
        [...icons.values()].find(icon => icon.verified) },
      { text: "Generic component (not a product icon)", icon: [...icons.values()].find(icon => !icon.verified) },
      { text: architecture ? "Main flow" : "Call / dependency", color: THEME.blue },
      ...(architecture ? [{ text: "Supporting dependency", color: THEME.muted }] : []),
      { text: architecture ? "Response / optional" : "Response", color: THEME.blue, dash: true },
    ].filter(entry => entry.color || entry.icon || !architecture && entry.text.startsWith("Generic"));
    const modes = new Set([
      ...model.relationships.map(edge => edge.implementationMode),
      ...model.sequence.map(message => message.implementationMode),
    ]);
    if (model.sequence.some(message => message.type === "approval")) entries.push({ text: "Human approval", color: THEME.green });
    for (const mode of ["simulated", "manual", "deferred", "blocked"]) {
      if (modes.has(mode)) entries.push({
        text: mode[0].toUpperCase() + mode.slice(1), color: modeColor(mode), dash: true,
      });
    }
    let x = 82;
    let row = 0;
    const slots = entries.map(entry => {
      const width = 70 + this.typography.measure(entry.text, 12).width;
      if (x + width > this.width - 82) { row++; x = 82; }
      const slot = { ...entry, x, y: y + (architecture ? 38 : 66) + row * 36 };
      x += width + 28;
      return slot;
    });
    const height = (architecture ? 60 : 90) + row * 36;
    this.add(`<g data-kind="legend" data-id="${legendId}" ${boxAttrs({ x: 60, y, width: this.width - 120, height })}>`);
    if (!architecture) {
      this.rect({ x: 60, y, width: this.width - 120, height }, THEME.paper, THEME.border);
      this.text("Reading this diagram", 82, y + 29, 15, THEME.ink, 600, legendId);
    }
    for (const slot of slots) {
      if (slot.icon) this.image(slot.icon, slot.x, slot.y - 22, 28);
      else if (slot.color) this.arrow([{ x: slot.x, y: slot.y - 6 }, { x: slot.x + 38, y: slot.y - 6 }], slot.color, slot.dash);
      else this.rect({ x: slot.x, y: slot.y - 20, width: 26, height: 26 }, THEME.background, THEME.border, 6);
      this.text(slot.text, slot.x + 48, slot.y, 12, THEME.muted, 400, legendId);
    }
    this.add("</g>");
    return y + height + 36;
  }
  svg(height, title, description) {
    const defs = [...this.markers.entries()].map(([color, id]) =>
      `<marker id="${id}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" ` +
      `markerUnits="userSpaceOnUse" orient="auto"><path d="M 1 1 L 9 5 L 1 9 Z" fill="${color}"/></marker>`).join("");
    return `<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" ` +
      `viewBox="0 0 ${this.width} ${Math.ceil(height)}" role="img" aria-labelledby="title desc">` +
      `<title id="title">${esc(title)}</title><desc id="desc">${esc(description)}</desc>` +
      `<defs>${defs}<filter id="card-shadow" x="-10%" y="-10%" width="120%" height="130%">` +
      `<feDropShadow dx="0" dy="3" stdDeviation="5" flood-color="#20395D" flood-opacity=".055"/>` +
      `</filter>${this.typography.fontFace()}</defs>` +
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

function prepareCard(component, width, typography, hero = false, compact = false, icon = {}, annotations = []) {
  const titleSize = hero ? 23 : 19;
  const iconSize = hero ? 56 : 44;
  const titleWidth = width - iconSize - 56;
  const title = typography.wrap(component.name, titleWidth, titleSize, 600);
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
  let nextY = 22 + titleHeight + (description.length ? 22 : 4);
  const descriptionY = nextY;
  nextY += Math.max(0, description.length - 1) * 20;
  const membersY = nextY + (members.length ? 23 : 0);
  if (members.length) nextY = membersY +
    members.reduce((sum, member) => sum + member.lines.length * 20 + 3, 0) - 20;
  const details = [
    ...(component.productService && ![component.name, product].includes(component.productService) ?
      [{ label: "Service", value: component.productService }] : []),
    ...(runtime ? [{ label: "Runtime", value: runtime }] : []),
    ...(boundary ? [{ label: "Boundary", value: boundary }] : []),
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
    const text = `${annotation.id} · ${annotation.from} → ${annotation.to} · ${annotation.style} / ${annotation.implementationMode}`;
    const lines = typography.wrap(text, width - 48, 11);
    const labelLines = typography.wrap(annotation.label, width - 48, 13);
    const scope = { ...annotation, y: nextY + 10, lines, labelLines };
    nextY += 10 + lines.length * 16 + labelLines.length * 18 + 12;
    return scope;
  });
  if (!icon.verified) nextY += 16;
  return {
    id: component.id, component, width, height: Math.max(hero ? 190 : compact ? 110 : 130, nextY),
    title, titleSize, titleLeading, titleHeight, productLines, description, members, descriptionY,
    membersY, representedMembers, canonicalMembers, details, detailsY, scopes,
    metadataY, metadata, iconSize, hero, icon, x: 0, y: 0,
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
  const color = componentColor(c);
  drawing.rect(card, card.hero ? "#F2F5FF" : THEME.paper, color, 16,
    `stroke-width="${card.hero ? 2.2 : 1.4}" filter="url(#card-shadow)"`);
  if (card.hero) drawing.add(`<path d="M ${card.x + 20} ${card.y} H ${card.x + card.width - 20}" stroke="${THEME.blue}" stroke-width="3"/>`);
  drawing.image(card.icon, card.x + 22, card.y + 22, card.iconSize);
  membership([c.name], () => drawing.lines(card.title, card.x + card.iconSize + 36, card.y + 42, card.titleSize,
    THEME.ink, 600, c.id, card.titleLeading, false, "card-title"));
  membership([productCaption(c, card.icon)], () => drawing.lines(card.productLines, card.x + card.iconSize + 36,
    card.y + 42 + card.title.length * card.titleLeading, 14, THEME.muted, 400,
    c.id, 20, false, "product-title"));
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
    const color = modeColor(scope.implementationMode);
    drawing.add(`<g data-kind="control-annotation" data-id="${esc(scope.id)}" ` +
      `data-from="${esc(scope.from)}" data-to="${esc(scope.to)}" data-style="${esc(scope.style)}" ` +
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

function architectureCandidate(model, icons, typography, profile, output, python, family) {
  const controlIds = new Set(model.components.filter(isCrossCutting).map(c => c.id));
  const relationships = identified(model.relationships, "relationship").map(({ id, record }) => ({ ...record, id }));
  const scopes = new Map([...controlIds].map(id => [id, []]));
  const coverage = relationships.map(edge => {
    const control = controlIds.has(edge.from) ? edge.from : controlIds.has(edge.to) ? edge.to : null;
    const item = { ...edge, representation: control ? "scoped-control-annotation" : "routed", ...(control ? { owner: control } : {}) };
    if (control) scopes.get(control).push(item);
    return item;
  });
  const labelMeasures = new Map(model.relationships.map(edge => {
    const lines = typography.wrap(edge.label, 140, 13);
    return [edge, {
      lines, labelWidth: Math.max(...lines.map(line => typography.measure(line, 13).width), 70) + 20,
      labelHeight: lines.length * 19 + 12,
    }];
  }));
  const composition = composeArchitecture(model, PROFILES[profile],
    (c, width, hero, compact) => prepareCard(c, width, typography, hero, compact, icons.get(c.id), scopes.get(c.id) || []), 0,
    edge => ({ width: labelMeasures.get(edge).labelWidth, height: labelMeasures.get(edge).labelHeight }), family);
  const { width, cards } = composition;
  const drawing = new Drawing(width, typography);
  const top = drawing.header(model, "Solution Architecture", false);
  for (const item of [...cards, ...composition.regions, ...composition.headings]) item.y += top;
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
  for (const [index, heading] of composition.headings.entries()) {
    drawing.text(heading.text, heading.x, heading.y, 15, THEME.blue, 600, `heading-${index}`, false, "section-title");
  }
  const input = {
    canvasWidth: width, canvasHeight: bottom + 180, routePadding: 12,
    nodes: cards.map(({ id, x, y, width, height }) => ({ id, x, y, width, height })),
    edges: edgeInputs.map(({ lines, edge, ...item }) => item),
    labelExclusions: [
      { x: 0, y: 0, width, height: top - 8 },
      ...drawing.texts.map(text => ({ x: text.x - 6, y: text.y - 6, width: text.width + 12, height: text.height + 12 })),
      { x: 0, y: bottom, width, height: 180 },
    ],
    routingExclusions: [
      { x: 0, y: 0, width, height: top - 8 },
      { x: 0, y: bottom, width, height: 180 },
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
    const supporting = [edge.from, edge.to].some(id => cardById.get(id).storyRole === "supporting");
    const color = supporting && edge.implementationMode === "real" ? THEME.muted : modeColor(edge.implementationMode);
    drawing.add(`<g data-kind="connector" data-id="${esc(item.id)}" data-from="${esc(edge.from)}" data-to="${esc(edge.to)}" ` +
      `data-label="${esc(edge.label)}" data-style="${esc(edge.style)}" ` +
      `data-relationship-type="${esc(edge.relationshipType || "")}" ` +
      `data-implementation-mode="${edge.implementationMode}" data-route="${route.points.map(p => `${p.x},${p.y}`).join(";")}">`);
    drawing.arrow(route.points, color, edge.style !== "call" || edge.implementationMode !== "real");
    for (const bridge of bridges.get(route.id) || []) {
      drawing.add(`<g data-kind="connector-bridge" data-x="${number(bridge.x)}" data-y="${number(bridge.y)}">`);
      drawing.add(`<circle cx="${number(bridge.x)}" cy="${number(bridge.y)}" r="6" fill="${THEME.background}"/>`);
      const arc = bridge.vertical ?
        `M ${bridge.x} ${bridge.y - 7} Q ${bridge.x + 10} ${bridge.y} ${bridge.x} ${bridge.y + 7}` :
        `M ${bridge.x - 7} ${bridge.y} Q ${bridge.x} ${bridge.y - 10} ${bridge.x + 7} ${bridge.y}`;
      drawing.add(`<path d="${arc}" fill="none" stroke="${color}" stroke-width="2"/>`);
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
    drawing.rect(box, THEME.background, "none", 6);
    drawing.lines(item.lines, route.labelX, box.y + 20, 13, color, 400, id, 19, true);
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
    drawing.text("EVIDENCED BOUNDARY SCOPES", 72, summaryY + 18, 15, THEME.blue, 600, "boundary-heading");
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
  const summary = typography.wrap(model.summary, width - 192, 18, 600);
  const summaryHeight = summary.length * 26 + 38;
  drawing.rect({ x: 60, y: summaryY, width: width - 120, height: summaryHeight }, THEME.ink, "none", 12);
  drawing.lines(summary, width / 2, summaryY + 34, 18, THEME.paper, 600, "architecture-summary", 26, true);
  const height = drawing.legend(summaryY + summaryHeight + 22, icons, model, true);
  const quality = visualQuality({ model, cards, drawing, layout, width, height: Math.ceil(height), coverage });
  return {
    svg: drawing.svg(height, `${model.title} - Solution Architecture`, model.summary), layout, drawing,
    width, height: Math.ceil(height),
    quality: {
      ...quality,
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
  const gap = 28;
  const headerWidth = Math.min(260, (width - 120 - gap * (participants.length - 1)) / participants.length);
  const rowWidth = headerWidth * participants.length + gap * (participants.length - 1);
  const firstX = (width - rowWidth) / 2;
  const headers = participants.map((id, index) => {
    const c = byId.get(id);
    return {
      component: c, id, x: firstX + index * (headerWidth + gap), width: headerWidth,
      center: firstX + index * (headerWidth + gap) + headerWidth / 2,
      nameLines: typography.wrap(c.name, headerWidth - 32, 16, 600),
      productLines: typography.wrap(productCaption(c, icons.get(c.id)), headerWidth - 32, 14),
      statusLines: typography.wrap(`${c.kind.toUpperCase()} / ${STATUS[c.implementationStatus]}`, headerWidth - 32, 11),
    };
  });
  const headerHeight = Math.max(...headers.map(h =>
    110 + h.nameLines.length * 22 + h.productLines.length * 20 + h.statusLines.length * 17));
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
      const label = `${entry.order}. ${prefix}${message.label}${condition}`;
      const lines = typography.wrap(label, labelWidth - 22, 14);
      if (fragment && fragment !== previousFragment) cursor += 38;
      const labelHeight = lines.length * 20 + 12;
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
  phaseGroups.forEach((phase, index) => {
    phase.headingWidth = Math.min(width - 120,
      typography.measure(`${String(index + 1).padStart(2, "0")}  ${phase.name}`, 15, 600).width + 48);
    const box = { x: 60, y: phase.y, width: phase.compact ? phase.headingWidth : width - 120,
      height: phase.compact ? 42 : phase.height };
    phase.fill = index % 2 ? "#F0F3FA" : "#EEF5F8";
    drawing.add(`<g data-kind="phase" data-id="${phase.id}" data-message-count="${phase.messages.length}" ` +
      `data-treatment="${phase.compact ? "compact-label" : "multi-message-band"}" ${boxAttrs(box)}>`);
    drawing.rect(box, phase.fill, phase.compact ? "none" : THEME.border, 10, 'stroke-width=".7"');
    drawing.add("</g>");
  });
  for (const header of headers) {
    const c = header.component;
    const box = { x: header.x, y: top, width: header.width, height: headerHeight };
    const accent = c.kind === "agent" ? THEME.blue : c.kind === "human" ? THEME.green : THEME.border;
    drawing.add(`<g id="lifeline-${esc(c.id)}" data-kind="lifeline" data-component-id="${esc(c.id)}" ${boxAttrs(box)}>`);
    drawing.rect(box, THEME.paper, accent, 15, 'stroke-width="1.4"');
    drawing.image(icons.get(c.id), header.center - 24, top + 18, 48);
    drawing.lines(header.nameLines, header.center, top + 92, 16, THEME.ink, 600, c.id, 22, true, "participant-title");
    drawing.lines(header.productLines, header.center, top + 96 + header.nameLines.length * 22,
      14, THEME.muted, 400, c.id, 20, true, "product-title");
    drawing.lines(header.statusLines, header.center,
      top + 106 + header.nameLines.length * 22 + header.productLines.length * 20,
      11, THEME.muted, 400, c.id, 17, true);
    drawing.add(`<line data-kind="lifeline-line" x1="${number(header.center)}" x2="${number(header.center)}" ` +
      `y1="${top + headerHeight}" y2="${lifelineEnd}" stroke="#9CAFC8" stroke-width="1.4" stroke-dasharray="5 7"/>`);
    drawing.add("</g>");
  }
  phaseGroups.forEach((phase, index) => {
    drawing.rect({ x: 61, y: phase.y + 1, width: phase.compact ? phase.headingWidth - 2 : width - 122,
      height: phase.compact ? 40 : 44 }, phase.fill, "none", 10);
    drawing.text(`${String(index + 1).padStart(2, "0")}  ${phase.name}`, 82, phase.y + 30,
      15, THEME.ink, 600, phase.id, false, "phase-title");
  });
  for (const row of rows) {
    const color = modeColor(row.message.implementationMode, row.message.type);
    const loop = row.fromX > width * .75 ? -72 : 72;
    const points = row.self ? [
      { x: row.fromX, y: row.y }, { x: row.fromX + loop, y: row.y },
      { x: row.fromX + loop, y: row.y + 26 }, { x: row.fromX, y: row.y + 26 },
    ] : [{ x: row.fromX, y: row.y }, { x: row.toX, y: row.y }];
    if (row.fragmentStart) {
      const box = { x: 74, y: row.labelY - 36, width: width - 148, height: row.fragmentBottom - row.labelY + 36 };
      drawing.add(`<g data-kind="fragment" data-id="fragment-${row.number}" ${boxAttrs(box)}>`);
      drawing.rect(box, "none", THEME.amber, 8, 'stroke-dasharray="6 5" stroke-width="1"');
      drawing.rect({
        x: 84, y: row.labelY - 31, width: typography.measure(row.fragment, 12, 600).width + 16, height: 25,
      }, THEME.paper, "none", 6);
      drawing.text(row.fragment, 90, row.labelY - 13, 12, THEME.amber, 600, `fragment-${row.number}`);
      drawing.add("</g>");
    }
    drawing.add(`<g data-kind="message" data-from="${esc(row.message.from)}" data-to="${esc(row.message.to)}" ` +
      `data-id="${esc(row.id)}" data-order="${esc(row.order)}" data-occurrence="${row.number}" data-type="${esc(row.message.type)}" ` +
      `data-relationship-id="${esc(row.message.relationshipId || "")}" data-label="${esc(row.message.label)}" ` +
      `data-condition="${esc(row.message.condition || "")}" data-action-control="${esc(JSON.stringify(row.message.actionControl || null))}" ` +
      `data-implementation-mode="${row.message.implementationMode}" ` +
      `data-route="${points.map(p => `${number(p.x)},${number(p.y)}`).join(";")}">`);
    drawing.rect({ x: row.toX - 4, y: row.y - 7, width: 8, height: row.self ? 40 : 26 }, color, "none", 3);
    drawing.arrow(points, color, row.message.type === "response" || row.message.implementationMode !== "real");
    const box = { x: row.center - row.labelWidth / 2, y: row.labelY, width: row.labelWidth, height: row.labelHeight };
    const labelId = `message-label-${row.number}`;
    drawing.add(`<g data-kind="message-label" data-id="${labelId}" ${boxAttrs(box)}>`);
    drawing.rect(box, THEME.paper, "none", 7);
    drawing.lines(row.lines, row.center, row.labelY + 21, 14, THEME.ink, 400, labelId, 20, true);
    drawing.add("</g></g>");
  }
  const height = drawing.legend(cursor + 8, icons, model);
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
  return { svg: drawing.svg(height, `${model.title} - Sequence Diagram`,
    "Ordered, evidence-grounded interactions with explicit implementation modes and human handoffs."), drawing,
    width, height: Math.ceil(height), quality: { validation: issues.length ? "failed" : "passed", issues,
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
    `SA_${model.scenarioSlug}.mmd`, `SD_${model.scenarioSlug}.mmd`];
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
  sa.quality.sequence = sd.quality;
  if (sd.quality.validation !== "passed") {
    sa.quality.validation = "failed";
    fs.writeFileSync(path.join(output, `sequence-quality-${args.profile}.json`), JSON.stringify(sd.quality, null, 2));
    throw new Error(`Sequence visual quality failed: ${sd.quality.issues.join("; ")}`);
  }
  const saPath = path.join(output, `SA_${model.scenarioSlug}.svg`);
  const sdPath = path.join(output, `SD_${model.scenarioSlug}.svg`);
  const previewPath = path.join(output, "preview.html");
  fs.writeFileSync(saPath, sa.svg);
  fs.writeFileSync(sdPath, sd.svg);
  fs.writeFileSync(previewPath, createPreview(model, {
    architecture: { width: sa.width, height: sa.height }, sequence: { width: sd.width, height: sd.height },
    sources: sourceGate.sources,
  }));
  const manifest = {
    scenarioSlug: model.scenarioSlug, layoutProfile: args.profile, presentation: "professional-light",
    layoutEngine: sa.layout.engine, solutionArchitecture: saPath, sequenceDiagram: sdPath,
    htmlPreview: "preview.html",
    editableSources: sourceGate,
    icons: model.components.map(c => ({
      component: c.name, componentId: c.id, icon: path.basename(icons.get(c.id).file),
      source: icons.get(c.id).source, verified: icons.get(c.id).verified,
    })),
    referenceSources: sources, generatedAt: new Date().toISOString(),
    typography: { font: "Inter", measured: true, minimumSize: 11 },
    layoutQuality: sa.quality,
  };
  fs.writeFileSync(path.join(output, "diagram-manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  // Candidate diagnostics remain beside the model, even after a passing alternative is selected.
  process.stdout.write(JSON.stringify({
    SolutionArchitecture: saPath, SequenceDiagram: sdPath, HtmlPreview: previewPath,
    Manifest: path.join(output, "diagram-manifest.json"),
  }));
}

if (require.main === module) {
  try { main(process.argv.slice(2)); }
  catch (error) { process.stderr.write(`${error.stack || error}\n`); process.exitCode = 2; }
}
module.exports = { Drawing, THEME, PROFILES, prepareCard, architecture, sequenceDiagram, sequenceParticipants, validateEditableSources };
