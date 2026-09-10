const { escapeXml: esc } = require("./typography");

function createPreview(model, options = {}) {
  if (!/^[A-Za-z0-9_]+$/.test(model.scenarioSlug)) throw new Error("Invalid preview scenario slug");
  const sourceCandidate = options.sources === false ? null :
    options.sources || options.sourceReport || model.sources || model.sourceReport;
  const sourceMetadata = sourceCandidate?.sources || sourceCandidate;
  const hasSources = options.sources === true || Boolean(
    sourceMetadata?.drawio && sourceMetadata?.architectureMermaid && sourceMetadata?.sequenceMermaid
  );
  const diagrams = [
    { id: "architecture", prefix: "SA", title: "Solution architecture",
      description: "Components, relationships, ownership, and implementation scope." },
    { id: "sequence", prefix: "SD", title: "Sequence diagram",
      description: "Ordered interactions, decision points, and implementation modes." },
  ];
  const sections = diagrams.map(diagram => {
    const file = `${diagram.prefix}_${model.scenarioSlug}`;
    const dimensions = options[diagram.id];
    const hasDimensions = Number.isSafeInteger(dimensions?.width) && dimensions.width > 0 &&
      Number.isSafeInteger(dimensions?.height) && dimensions.height > 0;
    const imageDimensions = hasDimensions ? ` width="${dimensions.width}" height="${dimensions.height}"` : "";
    const sourceLink = hasSources ? `\n          <a href="${file}.mmd" download>Download Mermaid</a>` : "";
    return `
    <section id="${diagram.id}" aria-labelledby="${diagram.id}-title">
      <div class="section-heading">
        <div><h2 id="${diagram.id}-title">${diagram.title}</h2><p>${diagram.description}</p></div>
        <div class="downloads" aria-label="${diagram.title} files">
          <a href="${file}.svg">Open SVG</a>
          <a href="${file}.png" download>Download PNG</a>${sourceLink}
        </div>
      </div>
      <input class="native-size" type="checkbox" id="${diagram.id}-native">
      <label for="${diagram.id}-native">Actual size (scroll to explore)</label>
      <p class="image-guidance" id="${diagram.id}-guidance">The image loads directly from this folder; no JavaScript is required.
        If it is blank or unavailable, open the SVG or PNG link above and check that the sibling files were copied with this preview.</p>
      <div class="viewport" tabindex="0" role="region" aria-label="${diagram.title} image" aria-describedby="${diagram.id}-guidance">
        <img src="${file}.png" alt="${esc(model.title)} - ${diagram.title}"${imageDimensions} loading="eager" decoding="sync">
      </div>
    </section>`;
  }).join("\n");
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file: data:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; object-src 'none'">
  <title>${esc(model.title)} - Diagram preview</title>
  <style>
    :root { color-scheme: light; font-family: "Segoe UI", Arial, sans-serif; color: #16263f; background: #f6f8fc; }
    * { box-sizing: border-box; }
    body { margin: 0; }
    header, main, footer { width: min(1800px, calc(100% - 48px)); margin: auto; }
    header { padding: 36px 0 28px; }
    .eyebrow { color: #5365cd; font-size: 12px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; }
    h1 { margin: 12px 0; font-size: clamp(26px, 3vw, 38px); overflow-wrap: anywhere; }
    p { color: #53647d; line-height: 1.6; overflow-wrap: anywhere; }
    .metadata { font-size: 14px; }
    nav, .downloads { display: flex; flex-wrap: wrap; gap: 12px; }
    a { color: #4356b5; text-underline-offset: 3px; }
    nav a { padding: 10px 16px; border: 1px solid #d4ddeb; border-radius: 8px; background: white; text-decoration: none; }
    a:focus-visible, input:focus-visible, .viewport:focus-visible { outline: 3px solid #5365cd; outline-offset: 3px; }
    section { margin-bottom: 28px; padding: 24px; background: white; border: 1px solid #d4ddeb; border-radius: 16px; }
    .section-heading { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: baseline; gap: 12px 24px; }
    h2 { margin: 0; font-size: 22px; }
    .section-heading p { margin: 8px 0 16px; }
    label { font-size: 14px; color: #53647d; cursor: pointer; }
    .image-guidance { font-size: 13px; margin: 10px 0 0; }
    .viewport { margin-top: 18px; max-width: 100%; overflow: auto; background: #f6f8fc; border-radius: 8px; }
    .viewport img { display: block; width: auto; max-width: 100%; height: auto; margin: 0 auto; }
    .native-size:checked ~ .viewport img { max-width: none; margin: 0; }
    footer { padding: 0 0 28px; font-size: 13px; color: #53647d; line-height: 1.6; }
    @media (max-width: 600px) {
      header, main, footer { width: calc(100% - 24px); }
      section { padding: 16px; }
    }
    @media print {
      header, main, footer { width: 100%; }
      nav, .downloads, .native-size, label { display: none; }
      section { padding: 12px 0; border: 0; }
      section + section { break-before: page; }
      .native-size:checked ~ .viewport img { max-width: 100%; }
      .viewport { overflow: visible; }
    }
  </style>
</head>
<body>
  <header>
    <div class="eyebrow">Solution designer / diagram preview</div>
    <h1>${esc(model.title)}</h1>
    <p>${esc(model.summary)}</p>
    <p class="metadata">${esc(model.complexity)} complexity | Native ${esc(model.coverage.nativeBuildPercent)}% | PoC ${esc(model.coverage.pocDemonstrationPercent)}%</p>
    <nav aria-label="Diagrams">
      <a href="#architecture">Solution architecture</a>
      <a href="#sequence">Sequence diagram</a>
    </nav>
    ${hasSources ? `<p class="metadata"><a href="Design_${model.scenarioSlug}.drawio" download>Download editable Draw.io (both diagrams)</a>
      | Source order: Draw.io → Mermaid → presentation diagrams. The sources describe the same two diagrams.</p>` : ""}
  </header>
  <main>${sections}
  </main>
  <footer>Offline preview. Keep this file beside its four SVG and PNG diagram files${hasSources ? " and three editable Draw.io/Mermaid source files" : ""} when moving or sharing the artifact folder.
    Implementation status and ownership are shown in the diagrams. A preview is not evidence of deployment or approval.</footer>
</body>
</html>
`;
}

module.exports = { createPreview };
