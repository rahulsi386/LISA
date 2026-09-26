const fs = require("fs");
const path = require("path");
const { Resvg } = require("@resvg/resvg-js");

const fontPath = path.join(__dirname, "fonts", "InterVariable.ttf");
const fontOptions = {
  fontFiles: [fontPath], loadSystemFonts: false, defaultFontFamily: "Inter",
  defaultFontSize: 14, sansSerifFamily: "Inter",
};

function escapeXml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&apos;",
  })[char]);
}

class Typography {
  constructor() {
    this.cache = new Map();
  }

  measure(text, size = 14, weight = 400) {
    if (!text.trim()) return { x: 0, y: -size, width: 0, height: size };
    const key = JSON.stringify([text, size, weight]);
    if (!this.cache.has(key)) {
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="16384" height="256">` +
        `<text x="16" y="128" font-family="Inter" font-size="${size}" font-weight="${weight}">` +
        `${escapeXml(text)}</text></svg>`;
      const bounds = new Resvg(svg, { font: fontOptions, logLevel: "error" }).getBBox();
      if (!bounds || !Number.isFinite(bounds.width)) throw new Error(`Cannot measure text: ${text}`);
      this.cache.set(key, {
        x: bounds.x - 16, y: bounds.y - 128, width: bounds.width, height: bounds.height,
      });
    }
    return this.cache.get(key);
  }

  wrap(text, width, size = 14, weight = 400) {
    if (!(width > size)) throw new Error(`Invalid text width: ${width}`);
    const lines = [];
    let current = "";
    for (const word of String(text).trim().split(/\s+/).filter(Boolean)) {
      const combined = current ? `${current} ${word}` : word;
      if (this.measure(combined, size, weight).width <= width - 3) {
        current = combined;
        continue;
      }
      if (current) lines.push(current);
      current = "";
      for (const character of word) {
        const next = current + character;
        if (current && this.measure(next, size, weight).width > width - 3) {
          lines.push(current);
          current = character;
        } else current = next;
      }
    }
    if (current) lines.push(current);
    return lines;
  }

  fontFace() {
    return `<style>@font-face{font-family:Inter;src:url(data:font/ttf;base64,` +
      `${fs.readFileSync(fontPath).toString("base64")}) format("truetype");font-weight:100 900;}</style>`;
  }
}

module.exports = { Typography, escapeXml, fontOptions };
