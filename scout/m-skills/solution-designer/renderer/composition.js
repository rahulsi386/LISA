// Layout follows the evidenced interaction graph; semantic layers are not columns.
const CONTROL_LAYERS = new Set(["governance", "monitoring"]);
const ROLE_NAMES = {
  actor: "REQUESTERS", channel: "EXPERIENCE", agent: "ORCHESTRATION",
  flow: "AUTOMATION", tool: "ACTION", integration: "INTEGRATION",
  external: "BUSINESS SYSTEM", data: "DATA", knowledge: "KNOWLEDGE",
  human: "HUMAN DECISION",
};
const WIDTHS = {
  actor: 220, channel: 250, agent: 350, flow: 300, tool: 300,
  integration: 320, external: 340, data: 300, knowledge: 310, human: 280,
};
const SCORE = { actor: 1, channel: 3, agent: 8, flow: 6, integration: 5, external: 8, tool: 5, human: 3, data: 1, knowledge: 0 };
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const center = card => card.x + card.width / 2;
const median = values => {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted.length ? sorted[Math.floor(sorted.length / 2)] : 0;
};
const visualRole = component => component.visualRole || component.visual_role || "";
const visualGroup = component => component.visualGroup || component.visual_group || "";
const isCrossCutting = component => CONTROL_LAYERS.has(component.layer) || visualRole(component) === "cross-cutting";

function compositionFamilies(model) {
  const families = ["story", "hub", "boundary"];
  const preferred = model.presentation?.preferred_composition || model.presentation?.preferredComposition;
  return families.includes(preferred) ? [preferred, ...families.filter(family => family !== preferred)] : families;
}

function graphFor(model) {
  const components = model.components.filter(c => !isCrossCutting(c)).sort((a, b) => compare(a.id, b.id));
  const byId = new Map(components.map(c => [c.id, c]));
  const edges = model.relationships.filter(e =>
    byId.has(e.from) && byId.has(e.to) && e.from !== e.to && e.style !== "response")
    .sort((a, b) => compare(`${a.from}|${a.to}|${a.label}|${a.id || ""}`, `${b.from}|${b.to}|${b.label}|${b.id || ""}`));
  const outgoing = new Map(components.map(c => [c.id, []]));
  const incoming = new Map(components.map(c => [c.id, []]));
  for (const edge of edges) {
    outgoing.get(edge.from).push(edge);
    incoming.get(edge.to).push(edge);
  }
  return { components, byId, edges, outgoing, incoming };
}

function chooseSpine(model, graph) {
  const { components, byId, incoming, outgoing } = graph;
  if (!components.length) return [];
  const sequenceOrder = [...new Set(model.sequence.flatMap(e => [e.from, e.to]))];
  const sequenceIndex = id => sequenceOrder.includes(id) ? sequenceOrder.indexOf(id) : Number.MAX_SAFE_INTEGER;
  const candidates = components.filter(c => c.kind === "agent");
  const hintedAgent = model.presentation?.primary_agent_id || model.presentation?.primaryAgentId ||
    components.find(c => visualRole(c) === "primary" && c.kind === "agent")?.id;
  candidates.sort((a, b) =>
    Number(b.id === hintedAgent) - Number(a.id === hintedAgent) ||
    sequenceIndex(a.id) - sequenceIndex(b.id) ||
    outgoing.get(b.id).length - outgoing.get(a.id).length ||
    compare(a.id, b.id));
  const primary = candidates[0] ||
    components.find(c => incoming.get(c.id).length === 0 && c.kind !== "knowledge") ||
    components.find(c => c.id === sequenceOrder[0]) ||
    components[0];
  const hintedPath = model.presentation?.primary_path || model.presentation?.primaryPath;
  if (Array.isArray(hintedPath) && hintedPath.length && new Set(hintedPath).size === hintedPath.length &&
      hintedPath.every(id => byId.has(id)) && hintedPath.includes(primary.id) &&
      hintedPath.slice(1).every((id, index) => outgoing.get(hintedPath[index]).some(edge => edge.to === id))) {
    return [...hintedPath];
  }

  // Reverse BFS finds real requester/trigger paths without inventing a channel.
  const queue = [[primary.id]];
  const visited = new Set([`${primary.id}|false`]);
  const upstream = [];
  while (queue.length) {
    const reverse = queue.shift();
    const id = reverse.at(-1);
    const component = byId.get(id);
    if (component.kind === "actor" || component.kind === "channel" ||
        (!incoming.get(id).length && component.kind !== "knowledge")) {
      upstream.push([...reverse].reverse());
    }
    for (const edge of incoming.get(id)) {
      const hasChannel = [...reverse, edge.from].some(key => byId.get(key).kind === "channel");
      const key = `${edge.from}|${hasChannel}`;
      if (!reverse.includes(edge.from) && !visited.has(key)) {
        visited.add(key);
        queue.push([...reverse, edge.from]);
      }
    }
  }
  const upstreamScore = path => {
    const first = byId.get(path[0]);
    return (first.kind === "actor" ? 100 : first.kind === "channel" ? 70 : 20) +
      (path.some(id => byId.get(id).kind === "channel") ? 20 : 0) - path.length;
  };
  upstream.sort((a, b) => upstreamScore(b) - upstreamScore(a) || compare(a.join("|"), b.join("|")));
  const prefix = upstream[0] || [primary.id];
  let budget = 4096;
  const tail = (id, seen, depth) => {
    let best = { ids: [], score: 0 };
    if (depth >= 7 || --budget <= 0 || (depth > 0 && byId.get(id).kind === "external")) return best;
    for (const edge of outgoing.get(id)) {
      const next = byId.get(edge.to);
      if (seen.has(next.id) || ["knowledge", "actor", "channel"].includes(next.kind)) continue;
      if (visualRole(next) === "supporting") continue;
      // Direct agent state and grounding are supporting dependencies, not fake business stages.
      if (byId.get(id).kind === "agent" && next.kind === "data") continue;
      const following = tail(next.id, new Set([...seen, next.id]), depth + 1);
      const score = (SCORE[next.kind] || 1) + following.score -
        (["blocked", "deferred"].includes(edge.implementationMode) ? 2 : 0);
      if (score > best.score) best = { ids: [next.id, ...following.ids], score };
    }
    return best;
  };
  return [...prefix, ...tail(primary.id, new Set(prefix), 0).ids];
}

function parallelPeers(id, remaining, graph) {
  const component = graph.byId.get(id);
  if (!["actor", "channel"].includes(component.kind)) return [];
  const neighbours = key => [...new Set([
    ...graph.incoming.get(key).map(e => `in:${e.from}`),
    ...graph.outgoing.get(key).map(e => `out:${e.to}`),
  ])].sort().join("|");
  return remaining.filter(c => c.kind === component.kind && neighbours(c.id) === neighbours(id));
}

function splitRows(items, available, gap, getWidth = item => item.width) {
  const rows = [];
  let row = [];
  let used = 0;
  for (const item of items) {
    const width = getWidth(item);
    if (row.length && used + gap + width > available) {
      rows.push(row);
      row = [];
      used = 0;
    }
    row.push(item);
    used += (row.length > 1 ? gap : 0) + width;
  }
  if (row.length) rows.push(row);
  return rows;
}

function supportClusters(remaining, graph) {
  const hintedGroups = new Map();
  for (const component of remaining) {
    const group = visualGroup(component);
    if (!group) continue;
    if (!hintedGroups.has(group)) hintedGroups.set(group, []);
    hintedGroups.get(group).push(component.id);
  }
  const unseen = new Set(remaining.filter(c => !visualGroup(c)).map(c => c.id));
  const clusters = [];
  const order = ids => {
    const pending = new Set(ids);
    const ordered = [];
    while (pending.size) {
      const next = [...pending].find(id => !graph.incoming.get(id).some(e => pending.has(e.from))) ||
        pending.values().next().value;
      ordered.push(graph.byId.get(next));
      pending.delete(next);
    }
    return ordered;
  };
  for (const group of [...hintedGroups.keys()].sort(compare)) clusters.push(order(hintedGroups.get(group)));
  while (unseen.size) {
    const ids = [];
    const queue = [unseen.values().next().value];
    unseen.delete(queue[0]);
    while (queue.length) {
      const id = queue.shift();
      ids.push(id);
      const neighbours = [...graph.incoming.get(id).map(e => e.from), ...graph.outgoing.get(id).map(e => e.to)];
      for (const next of neighbours) {
        if (unseen.delete(next)) queue.push(next);
      }
    }
    // A stable dependency order puts analytics and integration chains in reading order.
    clusters.push(order(ids));
  }
  return clusters;
}

function freePosition(row, width, desired, canvasWidth, margin, gap) {
  const occupied = [...row.blocks].sort((a, b) => a.x - b.x);
  let left = margin;
  const options = [];
  for (const block of [...occupied, { x: canvasWidth - margin + gap, width: 0 }]) {
    const right = block.x - gap;
    if (right - left >= width) {
      const x = Math.max(left, Math.min(desired, right - width));
      options.push({ x, distance: Math.abs(x - desired) });
    }
    left = block.x + block.width + gap;
  }
  options.sort((a, b) => a.distance - b.distance || a.x - b.x);
  return options[0]?.x;
}

function semanticRegions(cards) {
  const layers = [...new Set(cards.map(card => card.component.layer))];
  return layers.map(id => {
    const members = cards.filter(card => card.component.layer === id);
    const x = Math.floor(Math.min(...members.map(c => c.x))) - 25;
    const y = Math.floor(Math.min(...members.map(c => c.y))) - 25;
    return {
      id, x, y,
      width: Math.ceil(Math.max(...members.map(c => c.x + c.width))) - x + 25,
      height: Math.ceil(Math.max(...members.map(c => c.y + c.height))) - y + 25,
    };
  });
}

function boundaryOf(component) {
  return component.deploymentBoundary || component.description?.match(/Boundary:\s*([^]*?)\.?$/)?.[1]?.replace(/\.$/, "") || "";
}

function composeArchitecture(model, profile, prepare, top, measureLabel = () => ({ width: 140 }), family = "story") {
  if (!["story", "hub", "boundary"].includes(family)) throw new Error(`Unknown composition family: ${family}`);
  const margin = 72;
  const graph = graphFor(model);
  let spine = chooseSpine(model, graph);
  const hintedPrimary = model.presentation?.primary_agent_id || model.presentation?.primaryAgentId ||
    graph.components.find(c => visualRole(c) === "primary" && c.kind === "agent")?.id;
  const heroId = spine.includes(hintedPrimary) && graph.byId.get(hintedPrimary)?.kind === "agent" ? hintedPrimary :
    spine.find(id => graph.byId.get(id).kind === "agent");
  if (family === "hub" && heroId) spine = spine.slice(0, spine.indexOf(heroId) + 1);
  const placed = new Set(spine);
  const columns = spine.map((id, index) => {
    const c = graph.byId.get(id);
    const peers = parallelPeers(id, graph.components.filter(item => !placed.has(item.id)), graph);
    peers.forEach(item => placed.add(item.id));
    const cards = [c, ...peers].map(component => prepare(component,
      WIDTHS[component.kind] || 300, component.id === heroId, ["actor", "channel"].includes(component.kind)));
    return {
      id, number: index + 1, caption: ROLE_NAMES[c.kind] || "COMPONENT", cards,
      width: Math.max(...cards.map(card => card.width)),
      height: cards.reduce((sum, card) => sum + card.height, 0) + Math.max(0, cards.length - 1) * 24,
    };
  });
  const mainGap = Math.max(profile.mainGap, ...graph.edges
    .filter(edge => placed.has(edge.from) && placed.has(edge.to))
    .map(edge => measureLabel(edge).width + 28));
  const requestedWidth = model.presentation?.target_width ?? model.presentation?.targetWidth;
  const hasWidthHint = typeof requestedWidth === "number" && Number.isFinite(requestedWidth) && requestedWidth > 0;
  const maximumWidth = hasWidthHint ? Math.max(1280, Math.min(2200, requestedWidth)) :
    Math.min(2200, profile.width * 1.25);
  const mainRows = splitRows(columns, maximumWidth - 2 * margin, mainGap);
  const naturalWidth = Math.max(0, ...mainRows.map(row =>
    row.reduce((sum, column) => sum + column.width, 0) + Math.max(0, row.length - 1) * mainGap));
  const remaining = graph.components.filter(c => !placed.has(c.id));
  const supportCards = new Map(remaining.map(c => [c.id, prepare(c, WIDTHS[c.kind] || 310, false, false)]));
  const supportGap = Math.max(profile.supportGap, ...graph.edges
    .filter(edge => !placed.has(edge.from) && !placed.has(edge.to))
    .map(edge => measureLabel(edge).width + 28));
  const supportArea = [...supportCards.values()].reduce((sum, card) =>
    sum + (card.width + supportGap) * (card.height + profile.rowGap), 0);
  const controls = model.components.filter(isCrossCutting);
  // A short spine must not force a dense hub or its controls into a narrow, very tall canvas.
  const contentWidth = Math.max(naturalWidth, Math.sqrt(supportArea * 2.4),
    Math.min(profile.width - 2 * margin, controls.length * 362 - 32));
  const width = Math.ceil(Math.max(1280, Math.min(maximumWidth, contentWidth + 2 * margin)));
  const cards = [];
  const headings = [];
  let y = top + 86;
  mainRows.forEach((row, rowIndex) => {
    const used = row.reduce((sum, column) => sum + column.width, 0);
    const gap = row.length > 1 ? Math.min(mainGap, (width - 2 * margin - used) / (row.length - 1)) : 0;
    const height = Math.max(...row.map(column => column.height));
    const offsets = new Map();
    for (const column of row) {
      let offset = (height - column.height) / 2;
      for (const card of column.cards) {
        offsets.set(card.id, { offset, number: column.number });
        offset += card.height + 24;
      }
    }
    const returnClearance = Math.max(0, ...model.relationships.filter(edge =>
      edge.style !== "call" && offsets.has(edge.from) && offsets.has(edge.to) &&
      offsets.get(edge.from).number > offsets.get(edge.to).number
    ).map(edge => (measureLabel(edge).height || 31) + 36 -
      Math.min(offsets.get(edge.from).offset, offsets.get(edge.to).offset)));
    const rowWidth = used + gap * (row.length - 1);
    let x = (width - rowWidth) / 2;
    const visualOrder = rowIndex % 2 ? [...row].reverse() : row;
    for (const column of visualOrder) {
      column.x = x;
      column.y = y;
      headings.push({ x, y: y - 24, text: `${String(column.number).padStart(2, "0")}  ${column.caption}` });
      let cardY = y + returnClearance + (height - column.height) / 2;
      for (const card of column.cards) {
        card.x = x + (column.width - card.width) / 2;
        card.y = cardY;
        card.storyRole = "main-flow";
        cards.push(card);
        cardY += card.height + 24;
      }
      x += column.width + gap;
    }
    y += height + returnClearance + profile.rowGap;
  });
  const mainById = new Map(cards.map(card => [card.id, card]));
  const clusters = supportClusters(remaining, graph).map(components => {
    const neighbours = components.flatMap(c => [
      ...graph.incoming.get(c.id).map(e => e.from), ...graph.outgoing.get(c.id).map(e => e.to),
    ]).filter(id => mainById.has(id));
    return { components, anchor: neighbours.length ? median(neighbours.map(id => center(mainById.get(id)))) : width / 2 };
  }).sort((a, b) => a.anchor - b.anchor);
  const supportRows = [];
  for (const cluster of clusters) {
    const clusterCards = cluster.components.map(c => supportCards.get(c.id));
    for (const chunk of splitRows(clusterCards, width - 2 * margin, supportGap)) {
      const blockWidth = chunk.reduce((sum, card) => sum + card.width, 0) + (chunk.length - 1) * supportGap;
      const desired = cluster.anchor - blockWidth / 2;
      let row = supportRows.find(candidate => freePosition(candidate, blockWidth, desired, width, margin, supportGap) !== undefined);
      if (!row) {
        row = { blocks: [], height: 0 };
        supportRows.push(row);
      }
      const x = freePosition(row, blockWidth, desired, width, margin, supportGap);
      row.blocks.push({ x, width: blockWidth, cards: chunk });
      row.height = Math.max(row.height, ...chunk.map(card => card.height));
    }
  }
  if (supportRows.length) {
    if (!mainRows.length) y = top + 74;
    headings.push({ x: margin, y: y - 30, text: "SUPPORTING CAPABILITIES" });
    for (const row of supportRows) {
      for (const block of row.blocks) {
        let x = block.x;
        for (const card of block.cards) {
          card.x = x;
          card.y = y + (row.height - card.height) / 2;
          card.storyRole = "supporting";
          cards.push(card);
          x += card.width + supportGap;
        }
      }
      y += row.height + profile.rowGap;
    }
  }
  if (controls.length) {
    if (!cards.length) y = top + 74;
    else y -= profile.rowGap - 82;
    headings.push({ x: margin, y: y - 28, text: "CROSS-CUTTING CONTROLS / SOURCE ID → TARGET ID" });
    const count = Math.min(controls.length, Math.max(1, Math.floor((width - 2 * margin + 32) / 362)));
    const controlWidth = count > 1 ? Math.min(460, (width - 2 * margin - (count - 1) * 32) / count) : 330;
    for (const row of splitRows(controls.map(c => prepare(c, controlWidth, false, true)), width - 2 * margin, 32)) {
      const height = Math.max(...row.map(card => card.height));
      const gap = row.length > 1 ? Math.min(110, (width - 2 * margin - row.length * controlWidth) / (row.length - 1)) : 0;
      let x = margin;
      for (const card of row) {
        card.x = x;
        card.y = y;
        card.storyRole = "control";
        cards.push(card);
        x += card.width + gap;
      }
      y += height + 40;
    }
  }
  if (family === "hub" && supportRows.length > 1 && mainRows.length) {
    // Put the orchestration hub between inbound/grounding and action satellites.
    // This changes graph geometry, rather than just stretching the story template.
    const split = Math.ceil(supportRows.length / 2);
    const before = supportRows.slice(0, split);
    const beforeIds = new Set(before.flatMap(row => row.blocks.flatMap(block => block.cards.map(card => card.id))));
    const mainCards = cards.filter(card => card.storyRole === "main-flow");
    const mainTop = Math.min(...mainCards.map(card => card.y));
    const mainBottom = Math.max(...mainCards.map(card => card.y + card.height));
    const mainHeight = mainBottom - mainTop + profile.rowGap;
    const firstSupport = Math.min(...cards.filter(card => card.storyRole === "supporting").map(card => card.y));
    const beforeBottom = Math.max(...cards.filter(card => beforeIds.has(card.id)).map(card => card.y + card.height));
    const shift = beforeBottom - firstSupport + profile.rowGap;
    for (const card of cards) {
      if (card.storyRole === "main-flow") card.y += shift;
      else if (beforeIds.has(card.id)) card.y -= mainHeight;
    }
    for (const heading of headings) {
      if (/^\d/.test(heading.text)) heading.y += shift;
      if (heading.text === "SUPPORTING CAPABILITIES") heading.y = mainTop - 28;
    }
  }
  if (family === "boundary") {
    // Evidenced boundaries group deployment responsibility, never semantic layers.
    // Without boundaries this is a dependency-cluster composition, not invented trust geometry.
    const operational = cards.filter(card => card.storyRole !== "control");
    const groups = new Map();
    const hasBoundaries = operational.some(card => boundaryOf(card.component));
    const dependencyGroups = supportClusters(graph.components, graph);
    for (const card of operational) {
      const group = visualGroup(card.component);
      const key = hasBoundaries ? [boundaryOf(card.component) || "Boundary not specified", group].filter(Boolean).join(" / ") :
        group || `Dependency cluster ${dependencyGroups.findIndex(items => items.some(c => c.id === card.id)) + 1}`;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(card);
    }
    headings.length = 0;
    let groupY = top + 86;
    for (const [key, members] of groups) {
      headings.push({ x: margin, y: groupY - 28, text: key });
      // Connection barycentres keep related components nearby without altering their identities.
      members.sort((a, b) => (spine.includes(a.id) ? spine.indexOf(a.id) : 100) -
        (spine.includes(b.id) ? spine.indexOf(b.id) : 100) || compare(a.id, b.id));
      const boundaryGap = Math.max(profile.supportGap, supportGap, mainGap);
      for (const row of splitRows(members, width - 2 * margin, boundaryGap)) {
        const height = Math.max(...row.map(card => card.height));
        let x = margin;
        for (const card of row) {
          card.x = x;
          card.y = groupY + (height - card.height) / 2;
          x += card.width + boundaryGap;
        }
        groupY += height + profile.rowGap;
      }
    }
    const controlCards = cards.filter(card => card.storyRole === "control");
    if (controlCards.length) {
      headings.push({ x: margin, y: groupY - 28, text: "CROSS-CUTTING CONTROLS / SCOPED RELATIONSHIPS" });
      for (const row of splitRows(controlCards, width - 2 * margin, 40)) {
        let x = margin;
        for (const card of row) {
          card.x = x;
          card.y = groupY;
          x += card.width + 40;
        }
        groupY += Math.max(...row.map(card => card.height)) + 40;
      }
    }
  }
  const bottom = Math.max(top + 74, ...cards.map(card => card.y + card.height)) + 52;
  return {
    width, cards, headings, bottom, spine,
    regions: semanticRegions(cards),
    strategy: `relationship-driven-${family}`, family,
    widthHint: { requested: requestedWidth ?? null, effectiveMaximum: maximumWidth,
      applied: hasWidthHint, clamped: hasWidthHint && maximumWidth !== requestedWidth,
      reason: "Target width is an advisory canvas ceiling, bounded to 1280–2200px to retain native card and 1800px fit-width readability." },
    mainRowCount: mainRows.length, supportRowCount: supportRows.length,
    columns: columns.map(column => column.cards.map(card => card.id)),
  };
}

module.exports = { composeArchitecture, graphFor, chooseSpine, CONTROL_LAYERS, boundaryOf,
  compositionFamilies, isCrossCutting, visualRole, visualGroup };
