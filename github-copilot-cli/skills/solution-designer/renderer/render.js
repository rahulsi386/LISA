const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { Resvg } = require("@resvg/resvg-js");
const { PNG } = require("pngjs");

function fail(message) {
  process.stderr.write(`${message}\n`);
  process.exitCode = 2;
}

function parseViewBox(svg, file) {
  const match = svg.match(/\bviewBox\s*=\s*["']([^"']+)["']/i);
  if (!match) {
    throw new Error(`SVG has no viewBox: ${file}`);
  }
  const values = match[1].trim().split(/[,\s]+/).map(Number);
  if (values.length !== 4 || values.some((value) => !Number.isFinite(value))) {
    throw new Error(`SVG has an invalid viewBox: ${file}`);
  }
  if (values[2] <= 0 || values[3] <= 0) {
    throw new Error(`SVG has a non-positive viewBox: ${file}`);
  }
  return { x: values[0], y: values[1], width: values[2], height: values[3] };
}

function rasterSanity(buffer, expectedWidth, expectedHeight, file) {
  const png = PNG.sync.read(buffer);
  if (png.width !== expectedWidth || png.height !== expectedHeight) {
    throw new Error(
      `PNG dimensions differ from the SVG viewBox for ${file}: ` +
      `${png.width}x${png.height} versus ${expectedWidth}x${expectedHeight}`
    );
  }

  let opaquePixels = 0;
  const colors = new Set();
  const stride = Math.max(1, Math.floor((png.width * png.height) / 25000));
  for (let pixel = 0; pixel < png.width * png.height; pixel += 1) {
    const offset = pixel * 4;
    if (png.data[offset + 3] > 0) {
      opaquePixels += 1;
    }
    if (pixel % stride === 0) {
      colors.add(
        `${png.data[offset]},${png.data[offset + 1]},` +
        `${png.data[offset + 2]},${png.data[offset + 3]}`
      );
    }
  }
  if (opaquePixels < png.width * png.height * 0.95) {
    throw new Error(`PNG contains unexpected transparent regions: ${file}`);
  }
  if (colors.size < 8) {
    throw new Error(`PNG appears blank or visually degenerate: ${file}`);
  }
  return { width: png.width, height: png.height, sampledColors: colors.size };
}

function render(svgPath, fontPath) {
  const svg = fs.readFileSync(svgPath);
  const viewBox = parseViewBox(svg.toString("utf8"), svgPath);
  const width = Math.ceil(viewBox.width);
  const resvg = new Resvg(svg, {
    fitTo: { mode: "width", value: width },
    font: {
      fontFiles: [fontPath],
      loadSystemFonts: false,
      defaultFontFamily: "Inter",
      defaultFontSize: 12,
      serifFamily: "Inter",
      sansSerifFamily: "Inter",
      monospaceFamily: "Inter",
      cursiveFamily: "Inter",
      fantasyFamily: "Inter",
    },
    logLevel: "warn",
  });

  const rendered = resvg.render();
  const buffer = rendered.asPng();
  const pngPath = svgPath.replace(/\.svg$/i, ".png");
  fs.writeFileSync(pngPath, buffer);
  const sanity = rasterSanity(
    buffer,
    Math.ceil(viewBox.width),
    Math.ceil(viewBox.height),
    svgPath
  );
  return {
    svg: svgPath,
    png: pngPath,
    ...sanity,
    bytes: buffer.length,
    sha256: crypto.createHash("sha256").update(buffer).digest("hex"),
  };
}

function selfTest() {
  const svg = Buffer.from(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 60">' +
    '<rect width="100" height="60" fill="#081426"/>' +
    '<text x="10" y="35" fill="#fff" font-family="Inter">test</text></svg>'
  );
  const fontPath = path.join(__dirname, "fonts", "InterVariable.ttf");
  const rendered = new Resvg(svg, {
    fitTo: { mode: "width", value: 100 },
    font: { fontFiles: [fontPath], loadSystemFonts: false, defaultFontFamily: "Inter" },
  }).render().asPng();
  const png = PNG.sync.read(rendered);
  if (png.width !== 100 || png.height !== 60) {
    throw new Error("resvg self-test produced incorrect dimensions.");
  }
  process.stdout.write("resvg self-test passed\n");
}

function main() {
  const args = process.argv.slice(2);
  if (args.length === 1 && args[0] === "--self-test") {
    selfTest();
    return;
  }
  if (args.length < 3 || args[0] !== "--report") {
    throw new Error(
      "Usage: node render.js --report <report.json> <diagram.svg> [diagram.svg ...]"
    );
  }
  const reportPath = path.resolve(args[1]);
  const svgPaths = args.slice(2).map((value) => path.resolve(value));
  const fontPath = path.join(__dirname, "fonts", "InterVariable.ttf");
  const startedAt = new Date().toISOString();
  const started = process.hrtime.bigint();
  const renders = svgPaths.map((svgPath) => render(svgPath, fontPath));
  const elapsedMs = Number(process.hrtime.bigint() - started) / 1_000_000;
  const report = {
    renderer: "@resvg/resvg-js 2.6.2",
    deterministicFonts: true,
    font: fontPath,
    startedAt,
    completedAt: new Date().toISOString(),
    elapsedMs: Math.round(elapsedMs * 1000) / 1000,
    renders,
  };
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);
  process.stdout.write(`${JSON.stringify(report)}\n`);
}

try {
  main();
} catch (error) {
  fail(error && error.stack ? error.stack : String(error));
}
