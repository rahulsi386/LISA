const fs = require("node:fs");
const Ajv2020 = require("ajv/dist/2020").default;

try {
  const { schema, value } = JSON.parse(fs.readFileSync(0, "utf8"));
  // Match the existing Draft 2020-12 behavior: formats are annotations, not assertions.
  const ajv = new Ajv2020({ strictTypes: false, validateFormats: false, ownProperties: true });
  const validate = ajv.compile(schema);
  if (!validate(value)) {
    const { instancePath, message } = validate.errors[0];
    const path = instancePath.slice(1).split("/").map(s => s.replace(/~1/g, "/").replace(/~0/g, "~")).join(".");
    process.stderr.write(`at ${path || "<root>"}: ${message}\n`);
    process.exitCode = 1;
  }
} catch (error) {
  process.stderr.write(`Ajv could not validate the input: ${error.message}\n`);
  process.exitCode = 2;
}
