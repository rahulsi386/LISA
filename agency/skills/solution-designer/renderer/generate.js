const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const { Typography, escapeXml: esc } = require("./typography");
const { composeArchitecture, CONTROL_LAYERS } = require("./composition");
const { createPreview } = require("./preview");

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
    this.texts.push({ ...bounds, owner, text });
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

function prepareCard(component, width, typography, hero = false, compact = false, icon) {
  const titleSize = hero ? 23 : 19;
  const iconSize = hero ? 56 : 44;
  const titleWidth = width - iconSize - 56;
  const title = typography.wrap(component.name, titleWidth, titleSize, 600);
  const titleLeading = hero ? 29 : 25;
  const product = productCaption(component, icon);
  const productLines = typography.wrap(product, titleWidth, 14);
  const titleHeight = Math.max(iconSize, title.length * titleLeading + productLines.length * 20);
  const description = typography.wrap(component.description || "", width - 48, 14);
  const members = (component.members || []).map(name => ({
    name, lines: typography.wrap(name, width - 58, 14),
  }));
  let nextY = 22 + titleHeight + 24;
  const descriptionY = nextY;
  nextY += Math.max(0, description.length - 1) * 20;
  const membersY = nextY + (members.length ? 28 : 0);
  if (members.length) nextY = membersY + 23 +
    members.reduce((sum, member) => sum + member.lines.length * 20 + 7, 0) - 20;
  nextY += 30;
  const owner = `${STATUS[component.implementationStatus]} | ${OWNERS[component.buildOwner] || component.buildOwner} | PoC ${component.pocScope}`;
  const metadata = [
    ...typography.wrap(owner, width - 48, 11),
    ...typography.wrap(PRODUCTION[component.productionStatus] || component.productionStatus, width - 48, 11),
  ];
  const metadataY = nextY;
  nextY += Math.max(0, metadata.length - 1) * 16 + 20;
  if (!icon.verified) nextY += 16;
  return {
    id: component.id, component, width, height: Math.max(hero ? 190 : compact ? 110 : 130, nextY),
    title, titleSize, titleLeading, titleHeight, productLines, description, members, descriptionY,
    membersY, metadataY, metadata, iconSize, hero, icon, x: 0, y: 0,
  };
}

function productCaption(component, icon) {
  if (!icon.displayName) return "";
  const normalize = text => text.toLowerCase().replace(/[^a-z0-9]/g, "");
  const product = normalize(icon.displayName);
  return [component.name, ...(component.members || [])].some(value => normalize(value).includes(product))
    ? "" : icon.displayName;
}

function renderCard(drawing, card) {
  const c = card.component;
  drawing.add(`<g id="node-${esc(c.id)}" data-kind="node" data-component-id="${esc(c.id)}" ` +
    `data-component-kind="${c.kind}" data-parent="${c.layer}" data-implementation-status="${c.implementationStatus}" ` +
    `data-story-role="${esc(card.storyRole || "component")}" ` +
    `data-members-count="${card.members.length}" ${boxAttrs(card)}>`);
  const color = componentColor(c);
  drawing.rect(card, THEME.paper, color, 16, 'stroke-width="1.4" filter="url(#card-shadow)"');
  if (card.hero) drawing.add(`<path d="M ${card.x + 20} ${card.y} H ${card.x + card.width - 20}" stroke="${THEME.blue}" stroke-width="3"/>`);
  drawing.image(card.icon, card.x + 22, card.y + 22, card.iconSize);
  drawing.lines(card.title, card.x + card.iconSize + 36, card.y + 42, card.titleSize,
    THEME.ink, 600, c.id, card.titleLeading, false, "card-title");
  drawing.lines(card.productLines, card.x + card.iconSize + 36,
    card.y + 42 + card.title.length * card.titleLeading, 14, THEME.muted, 400,
    c.id, 20, false, "product-title");
  drawing.lines(card.description, card.x + 24, card.y + card.descriptionY, 14,
    THEME.muted, 400, c.id, 20);
  if (card.members.length) {
    drawing.text("CAPABILITIES / SERVICES", card.x + 24, card.y + card.membersY, 11,
      THEME.blue, 600, c.id);
    let y = card.y + card.membersY + 23;
    for (const member of card.members) {
      drawing.add(`<g data-kind="member" data-name="${esc(member.name)}">`);
      drawing.lines(member.lines, card.x + 30, y, 14, THEME.muted, 400, c.id, 20);
      drawing.add("</g>");
      y += member.lines.length * 20 + 7;
    }
  }
  drawing.add(`<path d="M ${card.x + 24} ${card.y + card.metadataY - 17} H ${card.x + card.width - 24}" ` +
    `stroke="${THEME.border}" stroke-width=".7"/>`);
  drawing.lines(card.metadata, card.x + 24, card.y + card.metadataY, 11,
    THEME.muted, 400, c.id, 16);
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

function architecture(model, icons, typography, profile, output) {
  const labelMeasures = new Map(model.relationships.map(edge => {
    const lines = typography.wrap(edge.label, 140, 13);
    return [edge, {
      lines, labelWidth: Math.max(...lines.map(line => typography.measure(line, 13).width), 70) + 20,
      labelHeight: lines.length * 19 + 12,
    }];
  }));
  const composition = composeArchitecture(model, PROFILES[profile],
    (c, width, hero, compact) => prepareCard(c, width, typography, hero, compact, icons.get(c.id)), 0,
    edge => ({ width: labelMeasures.get(edge).labelWidth, height: labelMeasures.get(edge).labelHeight }));
  const { width, cards } = composition;
  const drawing = new Drawing(width, typography);
  const top = drawing.header(model, "Solution Architecture", false);
  for (const item of [...cards, ...composition.regions, ...composition.headings]) item.y += top;
  const bottom = composition.bottom + top;
  const cardById = new Map(cards.map(card => [card.id, card]));
  const activeEdges = model.relationships.filter(edge =>
    !CONTROL_LAYERS.has(cardById.get(edge.from).component.layer) &&
    !CONTROL_LAYERS.has(cardById.get(edge.to).component.layer));
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
      id: `edge-${String(index).padStart(3, "0")}`, sourceId: edge.from, targetId: edge.to,
      label: edge.label, ...labelMeasures.get(edge), edge,
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
  const inputFile = path.join(output, ".msagl-input.json");
  const outputFile = path.join(output, ".msagl-output.json");
  fs.writeFileSync(inputFile, JSON.stringify(input));
  const helper = path.join(__dirname, "..", "resources", "layout-engine", "SolutionDesigner.LayoutEngine.exe");
  const process = spawnSync(helper, [inputFile, outputFile], { encoding: "utf8", timeout: 120000, windowsHide: true });
  if (process.error) throw process.error;
  if (!fs.existsSync(outputFile)) throw new Error(`MSAGL produced no result: ${process.stderr}`);
  const layout = readJson(outputFile);
  if (process.status !== 0 || layout.issues?.length) {
    throw new Error(`MSAGL routing failed: ${(layout.issues || []).join("; ")} ${process.stderr || ""}`.trim());
  }
  const routeById = new Map(layout.routes.map(route => [route.id, route]));
  const bridges = crossingBridges(layout.routes);
  const edgeLabels = [];
  for (const item of edgeInputs) {
    const route = routeById.get(item.id);
    if (!route || route.points.length < 2) throw new Error(`Missing MSAGL route: ${item.id}`);
    const { edge } = item;
    const supporting = [edge.from, edge.to].some(id => cardById.get(id).storyRole === "supporting");
    const color = supporting && edge.implementationMode === "real" ? THEME.muted : modeColor(edge.implementationMode);
    drawing.add(`<g data-kind="connector" data-id="${item.id}" data-from="${esc(edge.from)}" data-to="${esc(edge.to)}" ` +
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
  const summary = typography.wrap(model.summary, width - 192, 18, 600);
  const summaryHeight = summary.length * 26 + 38;
  drawing.rect({ x: 60, y: bottom, width: width - 120, height: summaryHeight }, THEME.ink, "none", 12);
  drawing.lines(summary, width / 2, bottom + 34, 18, THEME.paper, 600, "architecture-summary", 26, true);
  const height = drawing.legend(bottom + summaryHeight + 22, icons, model, true);
  return {
    svg: drawing.svg(height, `${model.title} - Solution Architecture`, model.summary), layout, drawing,
    quality: {
      crossingCount: [...bridges.values()].reduce((sum, list) => sum + list.length, 0),
      bendCount: layout.routes.reduce((sum, route) => sum + Math.max(0, route.points.length - 2), 0),
      textMeasurement: "resvg / bundled Inter",
      composition: {
        strategy: composition.strategy, spine: composition.spine, columns: composition.columns,
        mainRowCount: composition.mainRowCount, supportRowCount: composition.supportRowCount,
        visibleLayerContainers: 0,
      },
    },
  };
}

function sequenceDiagram(model, icons, typography, profile) {
  const participants = [...new Set(model.sequence.flatMap(message => [message.from, message.to]))];
  if (participants.length < 2 || participants.length > 8) throw new Error("Sequence requires 2-8 participants");
  const byId = new Map(model.components.map(c => [c.id, c]));
  const width = Math.max(PROFILES[profile].width, participants.length * 232 + 120);
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
    phaseGroups.at(-1).messages.push({ message, number: index + 1 });
  });
  let cursor = top + headerHeight + 42;
  const rows = [];
  phaseGroups.forEach((phase, phaseIndex) => {
    phase.id = `phase-${phaseIndex}`;
    phase.y = cursor;
    cursor += 62;
    let previousFragment = "";
    for (const entry of phase.messages) {
      const { message } = entry;
      const self = message.from === message.to || message.type === "self";
      const fromX = xById.get(message.from);
      const toX = xById.get(message.to);
      const span = Math.abs(toX - fromX);
      const labelWidth = self ? Math.min(300, headerWidth + 40) : Math.min(440, Math.max(150, span - 24));
      const prefix = message.implementationMode === "simulated" && !/simulat/i.test(message.label) ? "Simulated: " : "";
      const label = `${entry.number}. ${prefix}${message.label}`;
      const lines = typography.wrap(label, labelWidth - 22, 14);
      const fragment = message.fragment || "";
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
    cursor += 34;
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
    const box = { x: 60, y: phase.y, width: width - 120, height: phase.height };
    phase.fill = index % 2 ? "#F0F3FA" : "#EEF5F8";
    drawing.add(`<g data-kind="phase" data-id="${phase.id}" ${boxAttrs(box)}>`);
    drawing.rect(box, phase.fill, THEME.border, 14, 'stroke-width=".7"');
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
    drawing.rect({ x: 61, y: phase.y + 1, width: width - 122, height: 44 }, phase.fill, "none", 13);
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
  return { svg: drawing.svg(height, `${model.title} - Sequence Diagram`,
    "Ordered, evidence-grounded interactions with explicit implementation modes and human handoffs."), drawing };
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
  const icons = resolveIcons(model, readJson(args.icons), args.icons);
  const typography = new Typography();
  const sa = architecture(model, icons, typography, args.profile, output);
  const sd = sequenceDiagram(model, icons, typography, args.profile);
  const saPath = path.join(output, `SA_${model.scenarioSlug}.svg`);
  const sdPath = path.join(output, `SD_${model.scenarioSlug}.svg`);
  const previewPath = path.join(output, "preview.html");
  fs.writeFileSync(saPath, sa.svg);
  fs.writeFileSync(sdPath, sd.svg);
  fs.writeFileSync(previewPath, createPreview(model));
  const manifest = {
    scenarioSlug: model.scenarioSlug, layoutProfile: args.profile, presentation: "professional-light",
    layoutEngine: sa.layout.engine, solutionArchitecture: saPath, sequenceDiagram: sdPath,
    htmlPreview: "preview.html",
    icons: model.components.map(c => ({
      component: c.name, componentId: c.id, icon: path.basename(icons.get(c.id).file),
      source: icons.get(c.id).source, verified: icons.get(c.id).verified,
    })),
    referenceSources: sources, generatedAt: new Date().toISOString(),
    typography: { font: "Inter", measured: true, minimumSize: 11 },
    layoutQuality: sa.quality,
  };
  fs.writeFileSync(path.join(output, "diagram-manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  if (process.env.SOLUTION_DESIGNER_KEEP_LAYOUT_DEBUG !== "1") {
    for (const name of [".msagl-input.json", ".msagl-output.json"]) fs.unlinkSync(path.join(output, name));
  }
  process.stdout.write(JSON.stringify({
    SolutionArchitecture: saPath, SequenceDiagram: sdPath, HtmlPreview: previewPath,
    Manifest: path.join(output, "diagram-manifest.json"),
  }));
}

if (require.main === module) {
  try { main(process.argv.slice(2)); }
  catch (error) { process.stderr.write(`${error.stack || error}\n`); process.exitCode = 2; }
}
module.exports = { Drawing, THEME, PROFILES, prepareCard, architecture, sequenceDiagram };
