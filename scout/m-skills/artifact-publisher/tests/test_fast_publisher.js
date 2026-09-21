const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const source = fs.readFileSync(
  path.join(__dirname, "..", "scripts", "fast-sharepoint-publisher.js"),
  "utf8",
);
const runner = eval(source);

class Storage {
  constructor(values = {}) {
    this.values = new Map(Object.entries(values));
  }
  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }
  setItem(key, value) {
    this.values.set(key, String(value));
  }
}

const preflight = {
  sitePath: "/sites/agents",
  agentLibrary: "Agent Library",
  artifactLibrary: "Agent Artifact",
  cachedAt: Date.now(),
  agentLibraryId: "agent-library-id",
  artifactLibraryId: "artifact-library-id",
  fields: {
    agentLibrary: {
      agentId: "AgentId",
      agentName: "AgentName",
      description: "AgentDescription",
      customerName: "CustomerName",
    },
    artifactLibrary: { agentId: "AgentId" },
  },
};

function job(overrides = {}) {
  const entries = [
    {
      uploadSequence: 1,
      artifactKey: "deployableAgent",
      localPath: "package.zip",
      remotePath: "/sites/agents/Agent Library/package.zip",
      bytes: 10,
    },
    ...Array.from({ length: 17 }, (_, index) => ({
      uploadSequence: index + 2,
      artifactKey: `artifact-${index + 1}`,
      localPath: `artifact-${index + 1}.json`,
      remotePath: `/sites/agents/Agent Artifact/Fixture/artifact-${index + 1}.json`,
      bytes: index + 1,
    })),
  ];
  return {
    sitePath: "/sites/agents",
    agentLibrary: "Agent Library",
    artifactLibrary: "Agent Artifact",
    artifactAgentFolder: "/sites/agents/Agent Artifact/Fixture",
    agentLibraryMetadata: {
      agentId: "11111111-1111-1111-1111-111111111111",
      agentName: "Fixture",
      agentDescription: "Fixture agent.",
      customerName: "Fixture Customer",
    },
    entries,
    ...overrides,
  };
}

function nestedJob() {
  const value = job();
  value.entries[1].remotePath =
    "/sites/agents/Agent Artifact/Fixture/build/project/agent/agent.mcs.yml";
  return value;
}

function pageFor(jobValue) {
  global.sessionStorage = new Storage({
    artifactPublisherFastJob: JSON.stringify(jobValue),
    artifactPublisherSchemaCache: JSON.stringify(preflight),
  });
  global.location = { origin: "https://contoso.sharepoint.com" };
  return {
    evaluate: async (callback, argument) => callback(argument),
  };
}

function response(status, value, headers = {}) {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => headers[name.toLowerCase()] || null },
    text: async () => text,
    json: async () => JSON.parse(text),
  };
}

function fullPage(jobValue) {
  const storage = new Storage({
    artifactPublisherFastJob: JSON.stringify(jobValue),
    artifactPublisherSchemaCache: JSON.stringify(preflight),
  });
  global.sessionStorage = storage;
  global.location = { origin: "https://contoso.sharepoint.com" };
  global.document = {
    createElement: () => ({}),
    body: { appendChild: () => {} },
  };
  const files = new Map();
  const folders = new Map([
    [jobValue.artifactAgentFolder, { Id: 900, AgentId: "" }],
  ]);
  const itemById = new Map([[900, folders.get(jobValue.artifactAgentFolder)]]);
  let nextId = 1000;
  let selectedFiles = [];

  const decodedPath = (url) => {
    const match = url.match(/decodedurl='([^']*)'/);
    return match ? decodeURIComponent(match[1]) : "";
  };
  const uploadPath = (url) => {
    const matches = [...url.matchAll(/decodedurl='([^']*)'/g)].map((match) =>
      decodeURIComponent(match[1]),
    );
    return `${matches[0]}/${matches.at(-1)}`;
  };
  global.fetch = async (url, options = {}) => {
    if (url.endsWith("/_api/contextinfo")) {
      return response(200, { FormDigestValue: "digest" });
    }
    if (url.includes("/Files/AddUsingPath")) {
      const remotePath = uploadPath(url);
      const file = selectedFiles.shift();
      const item = {
        Id: nextId++,
        AgentId: "",
        AgentName: "",
        AgentDescription: "",
        CustomerName: "",
      };
      const value = {
        Length: file.size,
        ServerRelativeUrl: remotePath,
        UniqueId: `file-${item.Id}`,
        item,
      };
      files.set(remotePath, value);
      itemById.set(item.Id, item);
      return response(200, value);
    }
    if (url.includes("/ListItemAllFields?$select=")) {
      const remotePath = decodedPath(url);
      const target = files.get(remotePath)?.item || folders.get(remotePath);
      return target ? response(200, target, { etag: "*" }) : response(404, {});
    }
    if (url.includes("/lists/getbytitle(") && options.headers?.["X-HTTP-Method"] === "MERGE") {
      const id = Number(url.match(/\/items\((\d+)\)/)[1]);
      Object.assign(itemById.get(id), JSON.parse(options.body));
      return response(204, "");
    }
    if (url.includes("/GetFileByServerRelativePath") && url.includes("?$select=Length")) {
      const value = files.get(decodedPath(url));
      return value ? response(200, value) : response(404, {});
    }
    if (url.includes("/GetFolderByServerRelativePath") && url.includes("?$select=Exists")) {
      return response(200, { Exists: folders.has(decodedPath(url)) });
    }
    if (url.endsWith("/_api/web/folders") && options.method === "POST") {
      const folder = JSON.parse(options.body).ServerRelativeUrl;
      const parent = folder.substring(0, folder.lastIndexOf("/"));
      if (parent && !folders.has(parent)) {
        return response(500, { error: `Parent folder not found: ${parent}` });
      }
      const item = { Id: nextId++, AgentId: "" };
      folders.set(folder, item);
      itemById.set(item.Id, item);
      return response(200, {});
    }
    if (url.includes("/Files?$select=Length")) {
      const root = decodedPath(url);
      const value = [...files.values()].filter(
        (file) => file.ServerRelativeUrl.substring(
          0,
          file.ServerRelativeUrl.lastIndexOf("/"),
        ) === root,
      );
      return response(200, { value });
    }
    if (url.includes("/Folders?$select=Name")) {
      return response(200, { value: [] });
    }
    throw new Error(`Unhandled mock request: ${options.method || "GET"} ${url}`);
  };

  const page = {
    evaluate: async (callback, argument) => callback(argument),
    locator: () => ({
      setInputFiles: async (paths) => {
        selectedFiles = paths.map((filePath) => {
          const entry = jobValue.entries.find((item) => item.localPath === filePath);
          return { size: entry.bytes };
        });
      },
      evaluate: async (callback, argument) =>
        callback(
          {
            files: selectedFiles,
            remove: () => {},
          },
          argument,
        ),
    }),
  };
  return { page, storage, files, folders };
}

async function testConcurrencyAndBatchPolicy() {
  const result = await runner(
    pageFor(
      job({
        dryRun: true,
        uploadConcurrency: 999,
        metadataConcurrency: 999,
      }),
    ),
  );
  assert.equal(result.uploadConcurrency, 8);
  assert.equal(result.metadataConcurrency, 20);
  assert.equal(result.uploadBatchCount, 3);
  assert.equal(result.metadataBatchCount, 1);
  assert.equal(result.firstProcessedItem, "deployableAgent");
  const persisted = JSON.parse(
    global.sessionStorage.getItem("artifactPublisherFastResult"),
  );
  assert.deepEqual(persisted, result);
}

async function testNoBudgetInstrumentation() {
  const result = await runner(pageFor(job({ dryRun: true })));
  assert.equal(result.success, true);
  for (const banned of [
    "budgetOverruns",
    "budgetSignal",
    "maxDurationMs",
    "suggestedExtensionMinutes",
  ]) {
    assert.equal(
      Object.prototype.hasOwnProperty.call(result, banned),
      false,
      `result must not expose ${banned}`,
    );
  }
  assert.ok(result.durationMs >= 0);
}

async function testDeployableFirstEnforcement() {
  const invalid = job({ dryRun: false });
  invalid.entries[0] = {
    ...invalid.entries[0],
    artifactKey: "wrong",
  };
  await assert.rejects(
    runner(pageFor(invalid)),
    /Deployable ZIP is not the first manifest item/,
  );
}

async function testMetadataPropagationAndIdempotentRerun() {
  const smallJob = job({
    entries: job().entries.slice(0, 2),
    uploadConcurrency: 2,
    metadataConcurrency: 2,
  });
  const harness = fullPage(smallJob);
  const first = await runner(harness.page);
  assert.equal(first.uploadedCount, 2);
  assert.equal(first.alreadyPublishedCount, 0);
  const agentId = smallJob.agentLibraryMetadata.agentId;
  for (const file of harness.files.values()) {
    if (file.ServerRelativeUrl.includes("Agent Artifact")) {
      assert.equal(file.item.AgentId, agentId);
    }

  }
  assert.equal(harness.folders.get(smallJob.artifactAgentFolder).AgentId, agentId);

  harness.storage.setItem("artifactPublisherFastJob", JSON.stringify(smallJob));
  global.sessionStorage = harness.storage;
  const second = await runner(harness.page);
  assert.equal(second.uploadedCount, 0);
  assert.equal(second.alreadyPublishedCount, 2);
}

async function testNestedFoldersAreCreatedParentFirst() {
  const value = nestedJob();
  value.entries = value.entries.slice(0, 2);
  const harness = fullPage(value);
  const result = await runner(harness.page);
  assert.equal(result.uploadedCount, 2);
  for (const folder of [
    `${value.artifactAgentFolder}/build`,
    `${value.artifactAgentFolder}/build/project`,
    `${value.artifactAgentFolder}/build/project/agent`,
  ]) {
    assert.ok(harness.folders.has(folder), `missing folder ${folder}`);
  }
}

(async () => {
  await testConcurrencyAndBatchPolicy();
  await testNoBudgetInstrumentation();
  await testDeployableFirstEnforcement();
  await testMetadataPropagationAndIdempotentRerun();
  await testNestedFoldersAreCreatedParentFirst();
  process.stdout.write("fast publisher tests passed\n");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
