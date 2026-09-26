// Engineering acceptance budgets, not a claim that every graph is planar.
// Ratios normalize complexity; absolute structural defects always block selection.
const THRESHOLDS = Object.freeze({
  previewWidth: 1800,
  crossingRatio: .35, // At most one transverse crossing per ~3 routed relationships.
  sharedLaneRatio: .08, // Small common endpoint stubs are allowed; long ambiguous trunks are not.
  oppositeLaneRatio: .015, // Opposing arrows may share a short boundary stub, not a return lane.
  detourP95: 3.5, detourMaximum: 6, // Manhattan distance plus a one-card clearance floor.
  minimumOccupancy: .16, maximumOccupancy: .72,
  maximumCardTextDensity: .48, maximumCardAspect: 2.8,
  fitTitle: 15, fitBody: 11, fitMetadata: 9,
  agentTitleEmphasis: 1.15,
});
const round = value => Math.round(value * 10000) / 10000;
const overlap = (a, b, tolerance = .1) =>
  a.x < b.x + b.width - tolerance && a.x + a.width > b.x + tolerance &&
  a.y < b.y + b.height - tolerance && a.y + a.height > b.y + tolerance;
const contains = (a, b, margin = 0) => b.x >= a.x + margin && b.y >= a.y + margin &&
  b.x + b.width <= a.x + a.width - margin && b.y + b.height <= a.y + a.height - margin;
const percentile = (values, fraction) => [...values].sort((a, b) => a - b)[Math.max(0, Math.ceil(values.length * fraction) - 1)] || 0;
const distance = (a, b) => Math.abs(a.x - b.x) + Math.abs(a.y - b.y);

function identified(records, prefix) {
  const explicit = records.filter(record => Object.prototype.hasOwnProperty.call(record, "id")).map(record => record.id);
  if (explicit.some(id => typeof id !== "string" || !id)) throw new Error(`Invalid ${prefix} ID`);
  if (new Set(explicit).size !== explicit.length) throw new Error(`Duplicate canonical ${prefix} IDs`);
  const reserved = new Set(explicit);
  return records.map((record, index) => {
    let id = record.id;
    if (id === undefined) {
      id = `${prefix}-${String(index + 1).padStart(4, "0")}`;
      while (reserved.has(id)) id += "-legacy";
    }
    reserved.add(id);
    return { id, order: index + 1, record };
  });
}

function segmentHits(a, b, box, pad = 0) {
  const left = box.x - pad, right = box.x + box.width + pad;
  const top = box.y - pad, bottom = box.y + box.height + pad;
  return Math.abs(a.x - b.x) < .01 ?
    a.x >= left && a.x <= right && Math.max(a.y, b.y) >= top && Math.min(a.y, b.y) <= bottom :
    a.y >= top && a.y <= bottom && Math.max(a.x, b.x) >= left && Math.min(a.x, b.x) <= right;
}

function visualQuality({ model, cards, drawing, layout, width, height, coverage }) {
  const gates = [];
  const gate = (name, actual, limit, passed, reason) =>
    gates.push({ name, actual, limit, passed, reason });
  const routes = layout.routes || [];
  const stats = layout.metrics || {};
  const routeLength = routes.reduce((total, r) => total + r.points.slice(1)
    .reduce((sum, point, index) => sum + distance(point, r.points[index]), 0), 0);
  const cardById = new Map(cards.map(c => [c.id, c]));
  const detours = routes.map(route => {
    const source = cardById.get(route.sourceId), target = cardById.get(route.targetId);
    const length = route.points.slice(1).reduce((sum, p, i) => sum + distance(p, route.points[i]), 0);
    const baseline = Math.max(distance(route.points[0], route.points.at(-1)),
      Math.min(source.width + source.height, target.width + target.height));
    return { id: route.id, ratio: round(length / baseline), length: round(length) };
  });
  const crossingCount = stats.crossings || 0;
  const crossingRatio = crossingCount / Math.max(1, routes.length);
  const sharedLaneRatio = (stats.sharedLaneLength || 0) / Math.max(1, routeLength);
  const oppositeLaneRatio = (stats.oppositeLaneLength || 0) / Math.max(1, routeLength);
  gate("crossings", round(crossingRatio), THRESHOLDS.crossingRatio, crossingRatio <= THRESHOLDS.crossingRatio,
    `${crossingCount} transverse crossings / ${routes.length} routed relationships; bridges do not excuse excessive crossings.`);
  gate("shared-lanes", round(sharedLaneRatio), THRESHOLDS.sharedLaneRatio, sharedLaneRatio <= THRESHOLDS.sharedLaneRatio,
    "Common endpoint stubs are tolerated; long superimposed paths obscure relationship identity.");
  gate("opposite-lanes", round(oppositeLaneRatio), THRESHOLDS.oppositeLaneRatio, oppositeLaneRatio <= THRESHOLDS.oppositeLaneRatio,
    "Opposite-direction shared length must remain below 1.5% of total routing length.");
  const p95 = percentile(detours.map(d => d.ratio), .95), maxDetour = Math.max(0, ...detours.map(d => d.ratio));
  gate("route-detour", { p95, maximum: maxDetour }, { p95: THRESHOLDS.detourP95, maximum: THRESHOLDS.detourMaximum },
    p95 <= THRESHOLDS.detourP95 && maxDetour <= THRESHOLDS.detourMaximum,
    "Detour uses endpoint Manhattan distance with a one-card perimeter clearance floor, including short return routes.");
  const densities = cards.map(card => ({
    id: card.id, density: round(drawing.texts.filter(t => t.owner === card.id)
      .reduce((sum, t) => sum + t.width * t.height, 0) / (card.width * card.height)),
    aspect: round(card.height / card.width),
  }));
  const occupancy = cards.reduce((sum, card) => sum + card.width * card.height, 0) / (width * height);
  gate("content-density", { occupancy: round(occupancy), maximumCard: Math.max(0, ...densities.map(d => d.density)),
    maximumCardAspect: Math.max(0, ...densities.map(d => d.aspect)) },
  { occupancy: [THRESHOLDS.minimumOccupancy, THRESHOLDS.maximumOccupancy], card: THRESHOLDS.maximumCardTextDensity, aspect: THRESHOLDS.maximumCardAspect },
  occupancy >= THRESHOLDS.minimumOccupancy && occupancy <= THRESHOLDS.maximumOccupancy &&
    densities.every(d => d.density <= THRESHOLDS.maximumCardTextDensity && d.aspect <= THRESHOLDS.maximumCardAspect),
  "Measured glyph area detects dense cards; occupancy detects empty posters without requiring a fixed grid.");
  const scale = Math.min(1, THRESHOLDS.previewWidth / width);
  const fit = {
    title: Math.min(...cards.map(c => c.titleSize)) * scale,
    body: 14 * scale, metadata: 11 * scale, scale,
  };
  gate("fit-width-readability", Object.fromEntries(Object.entries(fit).map(([k, v]) => [k, round(v)])),
    { width: 1800, title: 15, body: 11, metadata: 9 },
    fit.title >= THRESHOLDS.fitTitle && fit.body >= THRESHOLDS.fitBody && fit.metadata >= THRESHOLDS.fitMetadata,
    "At 1800px fit-width, names remain >=15px, body >=11px, quiet metadata >=9px; native text is never shrunk.");
  const agents = cards.filter(c => c.component.kind === "agent");
  const hero = cards.find(c => c.hero);
  const titleEmphasis = hero ? hero.titleSize / Math.max(1, ...cards.filter(c => !c.hero).map(c => c.titleSize)) : 1;
  gate("agent-emphasis", round(titleEmphasis), THRESHOLDS.agentTitleEmphasis,
    !agents.length || Boolean(hero && titleEmphasis >= THRESHOLDS.agentTitleEmphasis),
    "When evidenced, the primary agent needs both a distinct hero treatment and a larger title; no invented agent is required.");
  const defects = [];
  const canvas = { x: 0, y: 0, width, height };
  for (const [i, card] of cards.entries()) {
    if (!contains(canvas, card, 24)) defects.push(`Card ${card.id} exceeds canvas margins`);
    for (const other of cards.slice(i + 1)) if (overlap(card, other)) defects.push(`Cards ${card.id}/${other.id} overlap`);
  }
  for (const [i, text] of drawing.texts.entries()) {
    if (!contains(canvas, text, 4)) defects.push(`Text outside canvas: ${text.text}`);
    if (cardById.has(text.owner) && !contains(cardById.get(text.owner), text)) defects.push(`Text outside own card ${text.owner}: ${text.text}`);
    for (const card of cards) if (card.id !== text.owner && overlap(text, card)) defects.push(`Text overlaps card ${card.id}: ${text.text}`);
    for (const other of drawing.texts.slice(i + 1)) if (overlap(text, other)) defects.push(`Text overlap: ${text.text} / ${other.text}`);
    for (const route of routes) for (let j = 1; j < route.points.length; j++) {
      if (segmentHits(route.points[j - 1], route.points[j], text, 2)) defects.push(`Route ${route.id} crosses text ${text.text}`);
    }
  }
  for (const route of routes) for (let i = 1; i < route.points.length; i++) {
    const a = route.points[i - 1], b = route.points[i];
    if (!contains(canvas, { ...a, width: .01, height: .01 }, 4) ||
        !contains(canvas, { ...b, width: .01, height: .01 }, 4)) defects.push(`Route ${route.id} exceeds canvas`);
    for (const card of cards) if (segmentHits(a, b, card, [route.sourceId, route.targetId].includes(card.id) ? -.1 : 1)) defects.push(`Route ${route.id} crosses card ${card.id}`);
  }
  gate("geometry-bounds-overlap", defects, 0, defects.length === 0, "Any overlap, clipping, route/card collision, or off-canvas text is an identifiable defect.");
  const expected = identified(model.relationships, "relationship").map(item => item.id);
  const covered = coverage.map(edge => edge.id);
  const coverageValid = expected.length === covered.length && new Set(covered).size === covered.length &&
    expected.every(id => covered.includes(id)) && coverage.every(item => {
      const edge = model.relationships[expected.indexOf(item.id)];
      return edge && edge.from === item.from && edge.to === item.to && edge.style === item.style &&
        edge.implementationMode === item.implementationMode && edge.label === item.label &&
        (edge.direction || "unidirectional") === (item.direction || "unidirectional") &&
        (edge.relationshipType ?? null) === (item.relationshipType ?? null);
    });
  gate("relationship-coverage", { expected: expected.length, represented: covered.length }, expected.length, coverageValid,
    "Every canonical relationship, direction, label, style and implementation mode is routed or visibly scoped, exactly once.");
  const issues = gates.filter(g => !g.passed).map(g => `${g.name}: ${JSON.stringify(g.actual)}; limit ${JSON.stringify(g.limit)}. ${g.reason}`);
  const score = round(Math.max(0, 100 - crossingRatio * 24 - sharedLaneRatio * 40 - oppositeLaneRatio * 200 -
    Math.max(0, p95 - 1) * 3 - Math.abs(occupancy - .38) * 18 -
    Math.max(0, width / 1800 - 1) * 8 - issues.length * 15));
  return { validation: issues.length ? "failed" : "passed", score, gates, issues,
    crossingCount, crossingRatio: round(crossingRatio), sharedLaneRatio: round(sharedLaneRatio),
    oppositeLaneRatio: round(oppositeLaneRatio), bendCount: stats.bends || 0,
    occupancy: round(occupancy), detours, cardDensities: densities,
    dimensions: { width, height }, relationshipCoverage: coverage, thresholds: THRESHOLDS };
}

module.exports = { visualQuality, THRESHOLDS, segmentHits, identified };
