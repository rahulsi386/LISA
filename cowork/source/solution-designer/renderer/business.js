const { escapeXml: esc } = require("./typography");
const { PALETTE, INK, MUTED, CANVAS, ZONE, STROKE, DASH, TYPE, styleConformance } = require("./style");

const ZONE_ID = "BIZ-CAPABILITIES";
const MARGIN = 60;
const CARD = { entry: 300, capability: 320, decision: 300, outcome: 330, foundation: 340 };
const ZONE_PAD = 24;
const CARD_GAP = 24;

function round(value) { return Math.round(value * 100) / 100; }

class Canvas {
  constructor(typography) {
    this.typography = typography;
    this.parts = [];
    this.texts = [];
    this.tones = new Set();
  }
  add(svg) { this.parts.push(svg); }
  text(value, x, baseline, size, color, weight = 400, owner = "", anchor = "start") {
    if (!String(value).trim()) return;
    const glyph = this.typography.measure(value, size, weight);
    const drawX = x - glyph.x - (anchor === "middle" ? glyph.width / 2 : anchor === "end" ? glyph.width : 0);
    this.texts.push({ x: drawX + glyph.x, y: baseline + glyph.y, width: glyph.width, height: glyph.height, text: value, owner });
    this.add(`<text x="${round(drawX)}" y="${round(baseline)}" font-family="Inter" font-size="${size}" ` +
      `font-weight="${weight}" fill="${color}">${esc(value)}</text>`);
  }
  lines(values, x, y, size, color, weight, leading, owner, anchor = "start") {
    values.forEach((value, index) => this.text(value, x, y + index * leading, size, color, weight, owner, anchor));
  }
  arrow(points, tone, dashed = false) {
    this.tones.add(tone);
    this.add(`<path d="M ${points.map(point => `${round(point[0])} ${round(point[1])}`).join(" L ")}" fill="none" ` +
      `stroke="${PALETTE[tone].line}" stroke-width="${STROKE.edge}" stroke-linejoin="round" ` +
      `${dashed ? `stroke-dasharray="${DASH.response}" ` : ""}marker-end="url(#business-arrow-${tone})"/>`);
  }
}

function measureCard(card, width, typography) {
  const inner = width - 40;
  const tagWidth = card.tag ? typography.measure(card.tag, TYPE.nodeCode.size, TYPE.nodeCode.weight).width + 16 : 0;
  const code = typography.wrap(card.code, inner - tagWidth, TYPE.nodeCode.size, TYPE.nodeCode.weight);
  const title = typography.wrap(card.title, inner, TYPE.nodeTitle.size, TYPE.nodeTitle.weight);
  const lines = card.lines.flatMap((line, index) => typography.wrap(line, inner, TYPE.nodeCopy.size)
    .map((part, offset) => ({ text: part, gap: index > 0 && offset === 0 })));
  const codeHeight = code.length * 16;
  const titleTop = 26 + codeHeight + 12;
  const linesTop = titleTop + title.length * 25 + 8;
  const height = linesTop + lines.reduce((sum, line) => sum + 20 + (line.gap ? 4 : 0), 0) + 16;
  return { ...card, width, code, title, wrapped: lines, titleTop, linesTop, height: Math.max(128, height) };
}

function drawCard(canvas, card) {
  const tone = PALETTE[card.tone];
  canvas.add(`<g data-kind="business-card" data-id="${esc(card.id)}" data-role="${card.role}" ` +
    `data-x="${round(card.x)}" data-y="${round(card.y)}" data-width="${round(card.width)}" data-height="${round(card.height)}">`);
  canvas.add(`<rect x="${round(card.x)}" y="${round(card.y)}" width="${round(card.width)}" height="${round(card.height)}" ` +
    `rx="10" fill="${tone.fill}" stroke="${tone.border}" stroke-width="${STROKE.card}"/>`);
  canvas.add(`<rect x="${round(card.x)}" y="${round(card.y + 11)}" width="${STROKE.accent}" height="${round(card.height - 22)}" rx="2" fill="${tone.line}"/>`);
  canvas.lines(card.code, card.x + 22, card.y + 30, TYPE.nodeCode.size, tone.line, TYPE.nodeCode.weight, 16, card.id);
  if (card.tag) canvas.text(card.tag, card.x + card.width - 18, card.y + 30, TYPE.nodeCode.size, MUTED, TYPE.nodeCode.weight, card.id, "end");
  canvas.lines(card.title, card.x + 22, card.y + card.titleTop + 19, TYPE.nodeTitle.size, INK, TYPE.nodeTitle.weight, 25, card.id);
  let y = card.y + card.linesTop + 17;
  for (const line of card.wrapped) {
    if (line.gap) y += 4;
    canvas.text(line.text, card.x + 22, y, TYPE.nodeCopy.size, MUTED, 400, card.id);
    y += 20;
  }
  canvas.add("</g>");
}

function flowLabel(canvas, label, x, y, tone, owner) {
  const measure = canvas.typography.measure(label, TYPE.edgeLabel.size, TYPE.edgeLabel.weight);
  const width = measure.width + 16;
  canvas.add(`<rect x="${round(x - width / 2)}" y="${round(y - 15)}" width="${round(width)}" height="22" rx="4" fill="${CANVAS}"/>`);
  canvas.text(label, x, y, TYPE.edgeLabel.size, PALETTE[tone].line, TYPE.edgeLabel.weight, owner, "middle");
}

function validateBusiness(model) {
  const business = model.businessArchitecture;
  if (!business || !Array.isArray(business.cards) || !Array.isArray(business.flows)) {
    throw new Error("Design model has no business architecture view");
  }
  const ids = new Set(business.cards.map(card => card.id));
  if (ids.size !== business.cards.length) throw new Error("Duplicate business card IDs");
  for (const card of business.cards) {
    if (!PALETTE[card.tone]) throw new Error(`Unknown business tone: ${card.tone}`);
  }
  const roles = business.cards.map(card => card.role);
  if (roles.filter(role => role === "entry").length !== 1 || roles.filter(role => role === "outcome").length !== 1 ||
      !roles.includes("capability")) throw new Error("Business view needs one entry, capabilities, and one outcome");
  for (const flow of business.flows) {
    for (const end of [flow.from, flow.to]) {
      if (end !== ZONE_ID && !ids.has(end)) throw new Error(`Unknown business flow endpoint: ${end}`);
    }
  }
  return business;
}

function businessArchitecture(model, typography) {
  const business = validateBusiness(model);
  const byRole = role => business.cards.filter(card => card.role === role);
  const entry = measureCard(byRole("entry")[0], CARD.entry, typography);
  const capabilities = byRole("capability").map(card => measureCard(card, CARD.capability, typography));
  const decision = byRole("decision").map(card => measureCard(card, CARD.decision, typography))[0] || null;
  const outcome = measureCard(byRole("outcome")[0], CARD.outcome, typography);
  const foundations = byRole("foundation");
  const control = byRole("control")[0] || null;
  const labelWidth = Math.max(...business.flows.map(flow => typography.measure(flow.label, TYPE.edgeLabel.size, TYPE.edgeLabel.weight).width + 16));
  const gap = Math.max(150, labelWidth + 44);
  const zoneWidth = ZONE_PAD * 2 + capabilities.length * CARD.capability + (capabilities.length - 1) * CARD_GAP;
  const mainColumns = [entry, "zone", ...(decision ? [decision] : []), outcome];
  const contentWidth = mainColumns.reduce((sum, item) => sum + (item === "zone" ? zoneWidth : item.width), 0) +
    gap * (mainColumns.length - 1);

  let width = Math.ceil(Math.max(1600, contentWidth + MARGIN * 2));
  const headline = typography.wrap(business.headline, width - MARGIN * 2, TYPE.diagramTitle.size, TYPE.diagramTitle.weight);
  const summary = typography.wrap(model.summary, width - MARGIN * 2, TYPE.subtitle.size);
  const headerHeight = 44 + headline.length * 34 + 10 + summary.length * 20 + 26;
  const zoneTop = headerHeight + 20;
  const cardsTop = zoneTop + 52;
  let x = (width - contentWidth) / 2;
  const zone = { x: 0, y: zoneTop, width: zoneWidth, height: 0 };
  for (const item of mainColumns) {
    if (item === "zone") {
      zone.x = x;
      capabilities.forEach((card, index) => {
        card.x = x + ZONE_PAD + index * (CARD.capability + CARD_GAP);
        card.y = cardsTop;
      });
      x += zoneWidth + gap;
    } else {
      item.x = x;
      item.y = cardsTop;
      x += item.width + gap;
    }
  }
  const mainCards = [entry, ...capabilities, ...(decision ? [decision] : []), outcome];
  zone.height = Math.max(...capabilities.map(card => card.height)) + (cardsTop - zoneTop) + ZONE_PAD;
  const flowY = cardsTop + Math.min(...mainCards.map(card => card.height)) / 2;
  const zoneBottom = zone.y + zone.height;
  const mainBottom = Math.max(zoneBottom, ...mainCards.map(card => card.y + card.height));

  let cursor = mainBottom;
  const foundationCards = [];
  if (foundations.length) {
    const top = zoneBottom + 120;
    const rowWidth = Math.max(zoneWidth, foundations.length * CARD.foundation + (foundations.length - 1) * CARD_GAP);
    const cardWidth = (rowWidth - (foundations.length - 1) * CARD_GAP) / foundations.length;
    const rowX = Math.max(MARGIN, zone.x + zoneWidth / 2 - rowWidth / 2);
    foundations.forEach((card, index) => {
      const measured = measureCard(card, cardWidth, typography);
      measured.x = rowX + index * (cardWidth + CARD_GAP);
      measured.y = Math.max(top, mainBottom + 48);
      foundationCards.push(measured);
    });
    width = Math.ceil(Math.max(width, rowX + rowWidth + MARGIN));
    cursor = Math.max(...foundationCards.map(card => card.y + card.height));
  }
  let controlCard = null;
  if (control) {
    controlCard = measureCard({ ...control, lines: [control.lines.join("  |  ")] }, width - MARGIN * 2, typography);
    controlCard.x = MARGIN;
    controlCard.y = cursor + 48;
    cursor = controlCard.y + controlCard.height;
  }
  const statement = typography.wrap(business.statement.toUpperCase(), width - MARGIN * 2, TYPE.zoneTitle.size, TYPE.zoneTitle.weight);
  const statementY = cursor + 46;
  const legendY = statementY + statement.length * 20 + 30;
  const height = Math.ceil(legendY + 58);

  const canvas = new Canvas(typography);
  canvas.add(`<rect width="${width}" height="${height}" fill="${CANVAS}"/>`);
  canvas.text("SOLUTION DESIGN / BUSINESS ARCHITECTURE", MARGIN, 44, TYPE.kicker.size, PALETTE.teal.line, TYPE.kicker.weight, "header");
  canvas.lines(headline, MARGIN, 44 + 36, TYPE.diagramTitle.size, INK, TYPE.diagramTitle.weight, 34, "header");
  canvas.lines(summary, MARGIN, 44 + headline.length * 34 + 28, TYPE.subtitle.size, MUTED, 400, 20, "header");
  canvas.add(`<g data-kind="business-zone" data-id="${ZONE_ID}" data-x="${round(zone.x)}" data-y="${round(zone.y)}" ` +
    `data-width="${round(zone.width)}" data-height="${round(zone.height)}">`);
  canvas.add(`<rect x="${round(zone.x)}" y="${round(zone.y)}" width="${round(zone.width)}" height="${round(zone.height)}" ` +
    `rx="${ZONE.radius}" fill="${ZONE.fill}" stroke="${ZONE.stroke}" stroke-width="${STROKE.zone}" stroke-dasharray="${DASH.zone}"/>`);
  canvas.text("WHAT THE SOLUTION DOES", zone.x + ZONE_PAD, zone.y + 32, TYPE.zoneTitle.size, ZONE.title, TYPE.zoneTitle.weight, ZONE_ID);
  canvas.add("</g>");

  const cardById = new Map([...mainCards, ...foundationCards].map(card => [card.id, card]));
  const labels = [];
  for (const flow of business.flows) {
    const source = flow.from === ZONE_ID ? zone : cardById.get(flow.from);
    const target = flow.to === ZONE_ID ? zone : cardById.get(flow.to);
    let points;
    let labelAt;
    if (source.y === target.y || (source === zone || target === zone) && Math.abs(source.y - target.y) < 60) {
      const forward = source.x < target.x;
      const x1 = forward ? source.x + source.width : source.x;
      const x2 = forward ? target.x : target.x + target.width;
      points = [[x1, flowY], [x2, flowY]];
      labelAt = [(x1 + x2) / 2, flowY - 14];
    } else {
      const lower = source.y > target.y ? source : target;
      const upper = lower === source ? target : source;
      const center = lower.x + lower.width / 2;
      const xLine = Math.max(upper.x + 34, Math.min(upper.x + upper.width - 34, center));
      const from = lower === source ? lower.y : upper.y + upper.height;
      const to = lower === source ? upper.y + upper.height : lower.y;
      points = [[xLine, from], [xLine, to]];
      const labelWidth = typography.measure(flow.label, TYPE.edgeLabel.size, TYPE.edgeLabel.weight).width + 16;
      labelAt = [xLine + 12 + labelWidth / 2, (from + to) / 2 + 5];
    }
    canvas.add(`<g data-kind="business-flow" data-from="${esc(flow.from)}" data-to="${esc(flow.to)}" data-label="${esc(flow.label)}">`);
    canvas.arrow(points, flow.tone, Boolean(flow.dashed));
    canvas.add("</g>");
    labels.push({ flow, labelAt });
  }
  [...mainCards, ...foundationCards].forEach(card => drawCard(canvas, card));
  if (controlCard) drawCard(canvas, controlCard);
  for (const { flow, labelAt } of labels) flowLabel(canvas, flow.label, labelAt[0], labelAt[1], flow.tone, `flow-${flow.from}-${flow.to}`);
  canvas.lines(statement, MARGIN, statementY, TYPE.zoneTitle.size, PALETTE.teal.line, TYPE.zoneTitle.weight, 20, "statement");

  const usedTones = new Set(business.flows.map(flow => flow.tone));
  const legend = [
    ["blue", false, "Request and delivery"], ["amber", true, "Proposed action awaiting approval"],
    ["teal", false, "Information and evidence"], ["green", false, "Outcome"],
  ].filter(([tone]) => usedTones.has(tone));
  let legendX = MARGIN;
  canvas.add(`<g data-kind="legend" data-y="${round(legendY)}">`);
  for (const [tone, dashed, text] of legend) {
    canvas.arrow([[legendX, legendY], [legendX + 34, legendY]], tone, dashed);
    canvas.text(text, legendX + 44, legendY + 5, TYPE.legend.size, MUTED, TYPE.legend.weight, "legend");
    legendX += 44 + typography.measure(text, TYPE.legend.size, TYPE.legend.weight).width + 30;
  }
  canvas.text("Card tags show the PoC treatment of each capability group.", legendX, legendY + 5, TYPE.legend.size, MUTED, TYPE.legend.weight, "legend");
  canvas.add("</g>");

  const issues = [];
  canvas.texts.forEach((text, index) => {
    if (text.x < 4 || text.y < 4 || text.x + text.width > width - 4 || text.y + text.height > height - 4) {
      issues.push(`Business text outside canvas: ${text.text}`);
    }
    for (const other of canvas.texts.slice(index + 1)) {
      if (text.x < other.x + other.width - .1 && text.x + text.width > other.x + .1 &&
          text.y < other.y + other.height - .1 && text.y + text.height > other.y + .1) {
        issues.push(`Business text overlaps: ${text.text} / ${other.text}`);
      }
    }
  });
  const markers = [...canvas.tones].map(tone =>
    `<marker id="business-arrow-${tone}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="9" markerHeight="9" ` +
    `markerUnits="userSpaceOnUse" orient="auto"><path d="M 1 1 L 9 5 L 1 9 Z" fill="${PALETTE[tone].line}"/></marker>`).join("");
  const title = `${model.title} - Business Architecture`;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="title desc">` +
    `<title id="title">${esc(title)}</title><desc id="desc">${esc(business.statement)}</desc>` +
    `<defs>${markers}${typography.fontFace(title + business.statement + canvas.parts.join(""))}</defs>\n${canvas.parts.join("\n")}</svg>\n`;
  const conformance = styleConformance(svg);
  issues.push(...conformance.issues.map(issue => `Business style: ${issue}`));
  return {
    svg, width, height,
    quality: {
      validation: issues.length ? "failed" : "passed", issues, styleConformance: conformance.validation,
      cardCount: mainCards.length + foundationCards.length + (controlCard ? 1 : 0),
      flowCount: business.flows.length,
    },
  };
}

module.exports = { businessArchitecture, PALETTE };
