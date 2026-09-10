"use strict";

const fs = require("node:fs/promises");
const path = require("node:path");
const crypto = require("node:crypto");
const { pathToFileURL } = require("node:url");

const sha256 = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const readJson = async file => JSON.parse(await fs.readFile(file, "utf8"));

async function assertLocal(file, root) {
  const relative = path.relative(root, file);
  if (relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("Evidence path escapes design");
  let current = path.resolve(file);
  for (;;) {
    const info = await fs.lstat(current);
    if (info.isSymbolicLink()) throw new Error(`Evidence path contains a link: ${current}`);
    const parent = path.dirname(current);
    if (current === parent) break;
    current = parent;
  }
}

async function validateLicenseProvenance(resourceRoot = path.resolve(__dirname, "..", "resources"), expectedManifestHash) {
  const manifestPath = path.join(resourceRoot, "icon-manifest.json");
  await assertLocal(manifestPath, resourceRoot);
  const bytes = await fs.readFile(manifestPath);
  if (expectedManifestHash && sha256(bytes) !== expectedManifestHash) throw new Error("Packaged icon manifest changed after preparation");
  const manifest = JSON.parse(bytes.toString("utf8"));
  if (!manifest.packs || typeof manifest.packs !== "object" || Array.isArray(manifest.packs)) {
    throw new Error("Packaged license provenance metadata is missing");
  }
  for (const [pack, metadata] of Object.entries(manifest.packs)) {
    for (const prefix of ["license", "repositoryLicense"]) {
      const filename = metadata[prefix + "File"], expected = metadata[prefix + "Sha256"];
      if (filename === undefined && expected === undefined) continue;
      if (typeof filename !== "string" || !filename || typeof expected !== "string" || !/^[a-fA-F0-9]{64}$/.test(expected)) {
        throw new Error(`Packaged license provenance metadata is incomplete: ${pack}`);
      }
      const file = path.resolve(resourceRoot, filename);
      await assertLocal(file, resourceRoot);
      const actual = sha256(await fs.readFile(file));
      if (actual !== expected.toLowerCase()) throw new Error(`Packaged license provenance hash mismatch: ${pack} (${filename}); expected ${expected.toLowerCase()}, got ${actual}`);
    }
  }
  return manifestPath;
}

async function imageMetrics(locator) {
  return locator.evaluate(async image => {
    await image.decode();
    const bounds = image.getBoundingClientRect();
    return { decoded: image.complete && image.naturalWidth > 0, natural_width: image.naturalWidth,
      natural_height: image.naturalHeight, display_width: bounds.width, display_height: bounds.height };
  });
}

// The caller supplies an existing Playwright page with permission to read local files.
// This receipt records observed browser conditions; it does not attest a trusted browser
// and never decides the human/vision composition checks.
async function collectBrowserEvidence(page, args) {
  if (!args || !path.isAbsolute(args.runPath)) throw new Error("runPath must be an absolute run.json path");
  const run = await readJson(args.runPath);
  const expectedManifestHash = run.resource_hashes?.["icon-manifest.json"];
  if (!expectedManifestHash) throw new Error("Collector requires a prepared resource-manifest binding");
  await validateLicenseProvenance(undefined, expectedManifestHash);
  const root = path.resolve(run.stage_design);
  const design = path.resolve(run.design_root);
  await assertLocal(args.runPath, design);
  await assertLocal(root, design);
  if (run.status !== "awaiting_inspection") throw new Error("Run is not awaiting inspection");
  const generation = await readJson(path.join(root, "run-report.json"));
  const context = generation.inspectionContext;
  if (!context || context.run_id !== run.run_id || context.revision !== run.revision) {
    throw new Error("Run lacks matching sealed generation context");
  }
  const model = await readJson(path.join(root, "design-model.json"));
  const slug = model.scenarioSlug;
  if (!/^[A-Za-z0-9_]+$/.test(slug)) throw new Error("Unsafe scenario slug");
  const names = ["design-model.json", "preview.html",
    ...["SA", "SD"].flatMap(prefix => ["svg", "png"].map(ext => `${prefix}_${slug}.${ext}`))];
  const artifact_sha256 = {};
  for (const name of names) {
    await assertLocal(path.join(root, name), root);
    artifact_sha256[name] = sha256(await fs.readFile(path.join(root, name)));
    if (artifact_sha256[name] !== run.staged_artifacts?.[name]) throw new Error(`Staged artifact changed: ${name}`);
  }
  if (artifact_sha256["design-model.json"] !== context.model_sha256) throw new Error("Canonical model changed");
  const viewport = args.viewport || { width: 1600, height: 1000 };
  if (!Number.isInteger(viewport.width) || viewport.width < 320 ||
      !Number.isInteger(viewport.height) || viewport.height < 240) throw new Error("Invalid viewport");
  await page.setViewportSize(viewport);
  const previewUrl = pathToFileURL(path.join(root, "preview.html")).href;
  await page.goto(previewUrl);
  const diagrams = {};
  for (const [key, prefix] of [["architecture", "SA"], ["sequence", "SD"]]) {
    const image = page.locator(`#${key} img`);
    const checkbox = page.locator(`#${key}-native`);
    await checkbox.uncheck();
    await image.scrollIntoViewIfNeeded();
    const metrics = await imageMetrics(image);
    const src = await image.getAttribute("src");
    if (src !== `${prefix}_${slug}.png`) throw new Error(`Preview displays wrong ${key} image`);
    await checkbox.check();
    const actual = await imageMetrics(image);
    const checked = await checkbox.isChecked();
    await checkbox.uncheck();
    const restored = await imageMetrics(image);
    diagrams[key] = { src, ...metrics, actual_width: actual.display_width,
      actual_height: actual.display_height, actual_size_checked: checked,
      fit_width_restored: !(await checkbox.isChecked()) &&
        Math.abs(restored.display_width - metrics.display_width) < 1 };
  }
  const downloadHrefs = await page.locator(".downloads a").evaluateAll(links => links.map(link => link.getAttribute("href")));
  const expectedLinks = names.filter(name => /\.(svg|png)$/.test(name));
  const sourceLinks = [`SA_${slug}.mmd`, `SD_${slug}.mmd`];
  const hrefs = downloadHrefs.filter(href => expectedLinks.includes(href));
  if (hrefs.length !== 4 || new Set(hrefs).size !== 4 ||
      downloadHrefs.some(href => !expectedLinks.includes(href) && !sourceLinks.includes(href))) {
    throw new Error("Expected four distinct sibling diagram links and optional sibling Mermaid links");
  }
  const screenshots = {};
  async function capture(key, asset) {
    const name = `inspection-${key}.png`;
    const file = path.join(root, name);
    try { await assertLocal(file, root); }
    catch (error) { if (error.code !== "ENOENT") throw error; }
    const bytes = await page.screenshot({ path: file, fullPage: true });
    screenshots[key] = { path: name, sha256: sha256(bytes), width: bytes.readUInt32BE(16),
      height: bytes.readUInt32BE(20), viewed_asset: asset };
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await capture("preview", "preview.html");
  const links = [];
  for (const href of hrefs) {
    await page.goto(pathToFileURL(path.join(root, href)).href);
    const decoded = await page.evaluate(async () => {
      if (document.documentElement.localName === "svg") {
        const svg = document.documentElement;
        return svg.getBoundingClientRect().width > 0 && svg.querySelector("*") !== null;
      }
      const image = document.querySelector("img");
      if (!image) return false;
      await image.decode();
      return image.complete && image.naturalWidth > 0;
    });
    if (!decoded) throw new Error(`Diagram link could not be decoded: ${href}`);
    links.push({ href, sha256: artifact_sha256[href], opened: true, decoded });
    if (href.endsWith(".png")) await capture(href.startsWith("SA_") ? "architecture" : "sequence", href);
  }
  for (const name of names) {
    if (sha256(await fs.readFile(path.join(root, name))) !== artifact_sha256[name]) {
      throw new Error(`Artifact changed during browser inspection: ${name}`);
    }
  }
  await validateLicenseProvenance(undefined, expectedManifestHash);
  const elapsed = Math.max(0, Date.now() / 1000 - run.started_epoch);
  const captured_at = new Date(Date.parse(run.started_at_local) + elapsed * 1000).toISOString();
  const evidence = { schema_version: "1.0", collector: "playwright",
    assurance: "browser-observations-not-attestation", ...context, captured_at, artifact_sha256,
    viewport: { ...viewport, device_scale_factor: await page.evaluate(() => window.devicePixelRatio) },
    screenshots, diagrams, links };
  const evidencePath = path.join(root, "browser-evidence.json");
  try { await assertLocal(evidencePath, root); }
  catch (error) { if (error.code !== "ENOENT") throw error; }
  await fs.writeFile(evidencePath, JSON.stringify(evidence, null, 2) + "\n");
  await page.goto(previewUrl);
  return { browser_evidence: evidencePath, captured_at, human_vision_judgment_required: true,
    attach_command: ["python", path.join(__dirname, "solution_designer.py"), "attach-browser-evidence",
      "--run", args.runPath, "--evidence", evidencePath, "--inspection", "<completed-inspection.json>"] };
}

// Self-contained entry point for Playwright MCP's page-only VM. File/WebCrypto
// APIs and Playwright's upload/download/screenshot methods avoid require/import
// or any attempt to escape the VM. Emit only after host-side path preflight.
async function collectBrowserEvidenceInPage(page, args) {
  function absolute(value) {
    if (typeof value !== "string" || !/^[A-Za-z]:\\/.test(value) ||
        value.split("\\").some(part => part === "." || part === "..")) throw new Error("Unsafe absolute evidence path");
    return value.replace(/\\+$/, "");
  }
  const runPath = absolute(args.runPath);
  const fileUrl = file => "file:///" + file.split("\\").map(encodeURIComponent).join("/").replace(/^([A-Za-z])%3A/, "$1:");
  await page.goto(fileUrl(runPath));
  async function readFile(file, json = false) {
    await page.evaluate(() => {
      document.getElementById("lisa-evidence-file")?.remove();
      const input = document.createElement("input");
      input.id = "lisa-evidence-file";
      input.type = "file";
      input.style.display = "none";
      document.body.append(input);
    });
    await page.locator("#lisa-evidence-file").setInputFiles(file);
    return page.locator("#lisa-evidence-file").evaluate(async (input, parseJson) => {
      const file = input.files[0];
      const bytes = await file.arrayBuffer();
      const digest = await crypto.subtle.digest("SHA-256", bytes);
      const sha256 = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
      const data = new DataView(bytes);
      return { sha256, value: parseJson ? JSON.parse(new TextDecoder().decode(bytes)) : null,
        width: bytes.byteLength >= 24 ? data.getUint32(16) : null,
        height: bytes.byteLength >= 24 ? data.getUint32(20) : null };
    }, json);
  }
  const run = (await readFile(runPath, true)).value;
  async function verifyLicenses() {
    const manifestPath = absolute(args.resourceManifestPath);
    if (!manifestPath.endsWith("\\icon-manifest.json")) throw new Error("Collector requires a packaged resource manifest");
    const resourceRoot = manifestPath.slice(0, -"\\icon-manifest.json".length);
    const manifestFile = await readFile(manifestPath, true);
    if (!run.resource_hashes?.["icon-manifest.json"] ||
        manifestFile.sha256 !== run.resource_hashes["icon-manifest.json"]) {
      throw new Error("Packaged icon manifest changed or is not bound to the prepared run");
    }
    const packs = manifestFile.value.packs;
    if (!packs || typeof packs !== "object" || Array.isArray(packs)) throw new Error("Packaged license provenance metadata is missing");
    for (const [pack, metadata] of Object.entries(packs)) {
      for (const prefix of ["license", "repositoryLicense"]) {
        const filename = metadata[prefix + "File"], expected = metadata[prefix + "Sha256"];
        if (filename === undefined && expected === undefined) continue;
        if (typeof filename !== "string" || !filename || /^[\\/]/.test(filename) || filename.includes(":") ||
            typeof expected !== "string" || !/^[a-fA-F0-9]{64}$/.test(expected)) {
          throw new Error("Packaged license provenance metadata is incomplete");
        }
        const file = absolute(resourceRoot + "\\" + filename.replace(/\//g, "\\"));
        const actual = (await readFile(file)).sha256;
        if (actual !== expected.toLowerCase()) throw new Error(`Packaged license provenance hash mismatch: ${pack} (${filename})`);
      }
    }
  }
  await verifyLicenses();
  const root = absolute(run.stage_design);
  const design = absolute(run.design_root);
  if (!root.toLowerCase().startsWith(design.toLowerCase() + "\\") ||
      !runPath.toLowerCase().startsWith(design.toLowerCase() + "\\")) throw new Error("Evidence paths escape design");
  if (run.status !== "awaiting_inspection") throw new Error("Run is not awaiting inspection");
  const context = (await readFile(root + "\\run-report.json", true)).value.inspectionContext;
  if (!context || context.run_id !== run.run_id || context.revision !== run.revision) throw new Error("Stale run context");
  const model = (await readFile(root + "\\design-model.json", true)).value;
  const slug = model.scenarioSlug;
  if (!/^[A-Za-z0-9_]+$/.test(slug)) throw new Error("Unsafe scenario slug");
  const names = ["design-model.json", "preview.html",
    ...["SA", "SD"].flatMap(prefix => ["svg", "png"].map(ext => `${prefix}_${slug}.${ext}`))];
  const artifact_sha256 = {};
  for (const name of names) {
    artifact_sha256[name] = (await readFile(root + "\\" + name)).sha256;
    if (artifact_sha256[name] !== run.staged_artifacts?.[name]) throw new Error("Staged artifacts changed before browser inspection");
  }
  if (artifact_sha256["design-model.json"] !== context.model_sha256) throw new Error("Canonical model changed");
  const viewport = args.viewport || { width: 1600, height: 1000 };
  await page.setViewportSize(viewport);
  const previewUrl = fileUrl(root + "\\preview.html");
  await page.goto(previewUrl);
  async function metrics(image) {
    return image.evaluate(async element => {
      await element.decode();
      const rect = element.getBoundingClientRect();
      return { decoded: element.complete && element.naturalWidth > 0,
        natural_width: element.naturalWidth, natural_height: element.naturalHeight,
        display_width: rect.width, display_height: rect.height };
    });
  }
  const diagrams = {};
  for (const [key, prefix] of [["architecture", "SA"], ["sequence", "SD"]]) {
    const image = page.locator(`#${key} img`);
    const checkbox = page.locator(`#${key}-native`);
    await checkbox.uncheck();
    await image.scrollIntoViewIfNeeded();
    const fit = await metrics(image);
    const src = await image.getAttribute("src");
    if (src !== `${prefix}_${slug}.png`) throw new Error("Wrong preview image");
    await checkbox.check();
    const actual = await metrics(image);
    const checked = await checkbox.isChecked();
    await checkbox.uncheck();
    const restored = await metrics(image);
    diagrams[key] = { src, ...fit, actual_width: actual.display_width, actual_height: actual.display_height,
      actual_size_checked: checked, fit_width_restored: !(await checkbox.isChecked()) &&
        Math.abs(restored.display_width - fit.display_width) < 1 };
  }
  const downloadHrefs = await page.locator(".downloads a").evaluateAll(links => links.map(link => link.getAttribute("href")));
  const expectedLinks = names.filter(name => /\.(svg|png)$/.test(name));
  const sourceLinks = [`SA_${slug}.mmd`, `SD_${slug}.mmd`];
  const hrefs = downloadHrefs.filter(href => expectedLinks.includes(href));
  if (hrefs.length !== 4 || new Set(hrefs).size !== 4 ||
      downloadHrefs.some(href => !expectedLinks.includes(href) && !sourceLinks.includes(href))) {
    throw new Error("Expected four distinct sibling diagram links and optional sibling Mermaid links");
  }
  const screenshots = {};
  async function screenshot(key, viewed_asset) {
    const name = `inspection-${key}.png`;
    await page.screenshot({ path: root + "\\" + name, fullPage: true });
    const file = await readFile(root + "\\" + name);
    screenshots[key] = { path: name, sha256: file.sha256, width: file.width, height: file.height, viewed_asset };
  }
  await page.evaluate(() => window.scrollTo(0, 0));
  await screenshot("preview", "preview.html");
  const links = [];
  for (const href of hrefs) {
    await page.goto(fileUrl(root + "\\" + href));
    const decoded = await page.evaluate(async () => {
      if (document.documentElement.localName === "svg") {
        return document.documentElement.getBoundingClientRect().width > 0 &&
          document.documentElement.querySelector("*") !== null;
      }
      const image = document.querySelector("img");
      if (!image) return false;
      await image.decode();
      return image.complete && image.naturalWidth > 0;
    });
    if (!decoded) throw new Error("Diagram link could not decode");
    links.push({ href, sha256: artifact_sha256[href], opened: true, decoded });
    if (href.endsWith(".png")) await screenshot(href.startsWith("SA_") ? "architecture" : "sequence", href);
  }
  for (const name of names) {
    if ((await readFile(root + "\\" + name)).sha256 !== artifact_sha256[name]) throw new Error("Artifacts changed while inspecting");
  }
  await verifyLicenses();
  const elapsed = Math.max(0, Date.now() / 1000 - run.started_epoch);
  const captured_at = new Date(Date.parse(run.started_at_local) + elapsed * 1000).toISOString();
  const receipt = { schema_version: "1.0", collector: "playwright",
    assurance: "browser-observations-not-attestation", ...context, captured_at, artifact_sha256,
    viewport: { ...viewport, device_scale_factor: await page.evaluate(() => window.devicePixelRatio) },
    screenshots, diagrams, links };
  const pending = page.waitForEvent("download");
  await page.evaluate(value => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + "\n"], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "browser-evidence.json";
    document.body.append(link);
    link.click();
  }, receipt);
  const download = await pending;
  const evidencePath = root + "\\browser-evidence.json";
  await download.saveAs(evidencePath);
  await download.delete();
  await page.goto(previewUrl);
  return { browser_evidence: evidencePath, captured_at, human_vision_judgment_required: true };
}

function makeMcpInvocation(runPath, viewport) {
  const args = JSON.stringify({ runPath, viewport, resourceManifestPath: path.resolve(__dirname, "..", "resources", "icon-manifest.json") });
  return `async (page) => { const collect = ${collectBrowserEvidenceInPage.toString()}; const inspectionPage = await page.context().newPage(); try { return await collect(inspectionPage, ${args}); } finally { await inspectionPage.close(); } }\n`;
}

async function emitMcpInvocation(runPath, outputPath) {
  const run = await readJson(runPath);
  const expectedManifestHash = run.resource_hashes?.["icon-manifest.json"];
  if (!expectedManifestHash) throw new Error("Collector requires a prepared resource-manifest binding");
  await validateLicenseProvenance(undefined, expectedManifestHash);
  const design = path.resolve(run.design_root);
  const root = path.resolve(run.stage_design);
  await assertLocal(runPath, design);
  await assertLocal(root, design);
  await assertLocal(path.dirname(outputPath), design);
  if (run.status !== "awaiting_inspection") throw new Error("Run is not awaiting inspection");
  if (!run.staged_artifacts || typeof run.staged_artifacts !== "object") throw new Error("Run has no staged artifact seal");
  for (const [name, expected] of Object.entries(run.staged_artifacts)) {
    if (path.basename(name) !== name || /[\\/:]/.test(name)) throw new Error("Unsafe sealed artifact name");
    const file = path.join(root, name);
    await assertLocal(file, root);
    if (sha256(await fs.readFile(file)) !== expected) throw new Error(`Staged artifact changed: ${name}`);
  }
  for (const name of ["browser-evidence.json", "inspection-architecture.png", "inspection-sequence.png", "inspection-preview.png"]) {
    try { await assertLocal(path.join(root, name), root); }
    catch (error) { if (error.code !== "ENOENT") throw error; }
  }
  try { await assertLocal(outputPath, design); }
  catch (error) { if (error.code !== "ENOENT") throw error; }
  if (path.dirname(outputPath) !== path.resolve(run.run_directory)) throw new Error("Invocation must live in the run directory");
  await fs.writeFile(outputPath, makeMcpInvocation(runPath));
  return { collector_script: outputPath, run: runPath };
}

module.exports = { collectBrowserEvidence, collectBrowserEvidenceInPage, makeMcpInvocation, emitMcpInvocation, validateLicenseProvenance };
if (require.main === module) {
  const [operation, runPath, outputPath] = process.argv.slice(2);
  if (operation !== "--emit-mcp" || !runPath || !outputPath) {
    console.error("Usage: node inspect_preview.js --emit-mcp <absolute-run.json> <absolute-run-directory\\browser-collector.js>");
    process.exitCode = 2;
  } else {
    emitMcpInvocation(runPath, outputPath).then(value => console.log(JSON.stringify(value))).catch(error => {
      console.error(error.message);
      process.exitCode = 2;
    });
  }
}
