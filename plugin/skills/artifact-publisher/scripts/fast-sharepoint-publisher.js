async (page) => {
  const job = await page.evaluate(() => {
    const value = sessionStorage.getItem("artifactPublisherFastJob");
    if (!value) throw new Error("Missing artifactPublisherFastJob in sessionStorage.");
    return JSON.parse(value);
  });

  const startedAt = new Date().toISOString();
  const startedMs = Date.now();
  const uploadConcurrency = Math.min(Math.max(job.uploadConcurrency ?? 6, 1), 8);
  const metadataConcurrency = Math.min(Math.max(job.metadataConcurrency ?? 12, 1), 20);
  const actions = [];
  const siteOrigin = await page.evaluate(() => location.origin);

  const encodePath = (value) => encodeURIComponent(value).replace(/%2F/g, "/");
  const fileName = (remotePath) => remotePath.substring(remotePath.lastIndexOf("/") + 1);
  const folderName = (remotePath) => remotePath.substring(0, remotePath.lastIndexOf("/"));
  const webUrl = (remotePath) =>
    `${siteOrigin}${remotePath
      .split("/")
      .map((part, index) => (index === 0 ? "" : encodeURIComponent(part)))
      .join("/")}`;

  const chunks = (values, size) => {
    const result = [];
    for (let index = 0; index < values.length; index += size) {
      result.push(values.slice(index, index + size));
    }
    return result;
  };

  const cachedPreflight = await page.evaluate((options) => {
    const value = sessionStorage.getItem("artifactPublisherSchemaCache");
    if (!value) return null;
    const cache = JSON.parse(value);
    const valid =
      cache.sitePath === options.sitePath &&
      cache.agentLibrary === options.agentLibrary &&
      cache.artifactLibrary === options.artifactLibrary &&
      Date.now() - cache.cachedAt < 15 * 60 * 1000;
    return valid ? cache : null;
  }, job);
  const schemaCacheHit = Boolean(cachedPreflight);
  const preflight = cachedPreflight || await page.evaluate(async (options) => {
    const getJson = async (url) => {
      const response = await fetch(url, {
        headers: { Accept: "application/json;odata=nometadata" },
      });
      const text = await response.text();
      if (!response.ok) throw new Error(`${response.status}: ${text}`);
      return { data: JSON.parse(text), etag: response.headers.get("etag") };
    };

    const listInfo = async (title) => {
      const encodedTitle = encodeURIComponent(title);
      const base = `${options.sitePath}/_api/web/lists/getbytitle('${encodedTitle}')`;
      const [info, fields] = await Promise.all([
        getJson(
          `${base}?$select=Id,Title,BaseTemplate,RootFolder/ServerRelativeUrl&$expand=RootFolder`,
        ),
        getJson(
          `${base}/fields?$select=Title,InternalName,ReadOnlyField,Hidden,TypeAsString`,
        ),
      ]);
      return { info: info.data, fields: fields.data.value };
    };

    const [agent, artifact] = await Promise.all([
      listInfo(options.agentLibrary),
      listInfo(options.artifactLibrary),
    ]);
    if (agent.info.BaseTemplate !== 101 || artifact.info.BaseTemplate !== 101) {
      throw new Error("Configured SharePoint destination is not a document library.");
    }

    const writableText = (field) =>
      field &&
      !field.Hidden &&
      !field.ReadOnlyField &&
      ["Text", "Note"].includes(field.TypeAsString);
    const find = (fields, titles, internalNames) => {
      const matches = fields.filter(
        (field) =>
          titles.some((title) => title.toLowerCase() === field.Title.toLowerCase()) ||
          internalNames.some(
            (name) => name.toLowerCase() === field.InternalName.toLowerCase(),
          ),
      );
      if (matches.length !== 1 || !writableText(matches[0])) {
        throw new Error(`Missing or ambiguous writable metadata field: ${titles[0]}`);
      }
      return matches[0].InternalName;
    };

    const fields = {
      agentLibrary: {
        agentId: find(agent.fields, ["Agent ID", "Agent Id"], ["AgentId"]),
        agentName: find(agent.fields, ["Agent Name"], ["AgentName"]),
        description: find(
          agent.fields,
          ["Agent Description"],
          ["AgentDescription"],
        ),
        customerName: find(
          agent.fields,
          ["Customer Name", "Cx Name"],
          ["CustomerName", "CxName"],
        ),
      },
      artifactLibrary: {
        agentId: find(artifact.fields, ["Agent ID", "Agent Id"], ["AgentId"]),
      },
    };

    sessionStorage.setItem(
      "artifactPublisherSchemaCache",
      JSON.stringify({
        sitePath: options.sitePath,
        agentLibrary: options.agentLibrary,
        artifactLibrary: options.artifactLibrary,
        cachedAt: Date.now(),
        agentLibraryId: agent.info.Id,
        artifactLibraryId: artifact.info.Id,
        fields,
      }),
    );
    return {
      agentLibraryId: agent.info.Id,
      artifactLibraryId: artifact.info.Id,
      fields,
    };
  }, job);

  if (job.dryRun) {
    const result = {
      success: true,
      dryRun: true,
      transport: "authenticated-sharepoint-rest",
      fastPathUsed: true,
      fallbackReason: null,
      schemaCacheHit,
      uploadConcurrency,
      metadataConcurrency,
      manifestCount: job.entries.length,
      uploadBatchCount: Math.ceil(
        Math.max(job.entries.length - 1, 0) / uploadConcurrency,
      ),
      metadataBatchCount: Math.ceil(
        Math.max(job.entries.length - 1, 0) / metadataConcurrency,
      ),
      firstProcessedItem: job.entries[0]?.artifactKey,
      artifactAgentFolder: job.artifactAgentFolder,
      durationMs: Date.now() - startedMs,
    };
    await page.evaluate((value) => {
      sessionStorage.setItem("artifactPublisherFastResult", JSON.stringify(value));
    }, result);
    return result;
  }

  const inspectFile = async (entry) =>
    page.evaluate(
      async ({ sitePath, remotePath }) => {
        const encodePath = (value) => encodeURIComponent(value).replace(/%2F/g, "/");
        const response = await fetch(
          `${sitePath}/_api/web/GetFileByServerRelativePath(decodedurl='${encodePath(
            remotePath,
          )}')?$select=Length,ServerRelativeUrl,UniqueId`,
          { headers: { Accept: "application/json;odata=nometadata" } },
        );
        if (response.status === 404) return { exists: false };
        const text = await response.text();
        if (!response.ok) throw new Error(`${response.status}: ${text}`);
        const result = { exists: true, ...JSON.parse(text) };
        if (remotePath.toLowerCase().endsWith(".html")) {
          const contentResponse = await fetch(
            `${sitePath}/_api/web/GetFileByServerRelativePath(decodedurl='${encodePath(
              remotePath,
            )}')/$value`,
          );
          if (!contentResponse.ok) {
            throw new Error(`${contentResponse.status}: ${await contentResponse.text()}`);
          }
          const normalized = (await contentResponse.text())
            .replace(/\s+xmlns:mso="[^"]*"/gi, "")
            .replace(/\s+xmlns:msdt="[^"]*"/gi, "")
            .replace(
              /\s*<!--\[if gte mso 9\]><xml>[\s\S]*?<\/xml><!\[endif\]-->\s*/gi,
              "\n",
            );
          const digest = await crypto.subtle.digest(
            "SHA-256",
            new TextEncoder().encode(normalized),
          );
          result.sha256 = [...new Uint8Array(digest)]
            .map((value) => value.toString(16).padStart(2, "0"))
            .join("");
        }
        return result;
      },
      { sitePath: job.sitePath, remotePath: entry.remotePath },
    );

  const inspectionMatches = (entry, inspection) =>
    inspection.exists &&
    (
      Number(inspection.Length) === Number(entry.bytes) ||
      (
        entry.remotePath.toLowerCase().endsWith(".html") &&
        inspection.sha256 &&
        inspection.sha256.toLowerCase() === entry.sha256.toLowerCase()
      )
    );

  const ensureFolders = async (remoteFolders) => {
    const ordered = [...new Set(remoteFolders)].sort(
      (left, right) => left.split("/").length - right.split("/").length,
    );
    return page.evaluate(
      async ({ sitePath, folders }) => {
        const encodePath = (value) => encodeURIComponent(value).replace(/%2F/g, "/");
        const context = await fetch(`${sitePath}/_api/contextinfo`, {
          method: "POST",
          headers: { Accept: "application/json;odata=nometadata" },
        });
        if (!context.ok) throw new Error(`${context.status}: ${await context.text()}`);
        const digest = (await context.json()).FormDigestValue;
        const created = [];
        for (const folder of folders) {
          const existing = await fetch(
            `${sitePath}/_api/web/GetFolderByServerRelativePath(decodedurl='${encodePath(
              folder,
            )}')?$select=Exists`,
            { headers: { Accept: "application/json;odata=nometadata" } },
          );
          const exists = existing.ok && (await existing.json()).Exists;
          if (exists) continue;
          const create = await fetch(`${sitePath}/_api/web/folders`, {
            method: "POST",
            headers: {
              Accept: "application/json;odata=nometadata",
              "Content-Type": "application/json;odata=nometadata",
              "X-RequestDigest": digest,
            },
            body: JSON.stringify({ ServerRelativeUrl: folder }),
          });
          if (!create.ok) throw new Error(`${create.status}: ${await create.text()}`);
          created.push(folder);
        }
        return created;
      },
      { sitePath: job.sitePath, folders: ordered },
    );
  };

  const uploadBatch = async (entries, batchIndex) => {
    const inputId = `artifact-publisher-fast-${batchIndex}-${Date.now()}`;
    await page.evaluate((id) => {
      const input = document.createElement("input");
      input.type = "file";
      input.multiple = true;
      input.hidden = true;
      input.id = id;
      document.body.appendChild(input);
    }, inputId);

    const input = page.locator(`#${inputId}`);
    await input.setInputFiles(entries.map((entry) => entry.localPath));
    const uploaded = await input.evaluate(
      async (element, options) => {
        const encodePath = (value) => encodeURIComponent(value).replace(/%2F/g, "/");
        const context = await fetch(`${options.sitePath}/_api/contextinfo`, {
          method: "POST",
          headers: { Accept: "application/json;odata=nometadata" },
        });
        if (!context.ok) throw new Error(`${context.status}: ${await context.text()}`);
        const digest = (await context.json()).FormDigestValue;
        const files = Array.from(element.files);
        return Promise.all(
          files.map(async (file, index) => {
            const entry = options.entries[index];
            const folder = entry.remotePath.substring(
              0,
              entry.remotePath.lastIndexOf("/"),
            );
            const name = entry.remotePath.substring(
              entry.remotePath.lastIndexOf("/") + 1,
            );
            const url = `${options.sitePath}/_api/web/GetFolderByServerRelativePath(decodedurl='${encodePath(
              folder,
            )}')/Files/AddUsingPath(decodedurl='${encodeURIComponent(
              name,
            )}',overwrite=true)?$select=Length,ServerRelativeUrl,UniqueId`;
            const response = await fetch(url, {
              method: "POST",
              headers: {
                Accept: "application/json;odata=nometadata",
                "Content-Type": "application/octet-stream",
                "X-RequestDigest": digest,
              },
              body: file,
            });
            const text = await response.text();
            if (!response.ok) {
              throw new Error(`${response.status}:${entry.remotePath}:${text}`);
            }
            return JSON.parse(text);
          }),
        );
      },
      { sitePath: job.sitePath, entries },
    );
    await input.evaluate((element) => element.remove());
    return uploaded;
  };

  const updateItemMetadata = async ({
    library,
    itemPath,
    values,
    isFolder = false,
  }) =>
    page.evaluate(
      async ({ sitePath, library, itemPath, values, isFolder }) => {
        const encodePath = (value) => encodeURIComponent(value).replace(/%2F/g, "/");
        const target = isFolder
          ? "GetFolderByServerRelativePath"
          : "GetFileByServerRelativePath";
        const itemResponse = await fetch(
          `${sitePath}/_api/web/${target}(decodedurl='${encodePath(
            itemPath,
          )}')/ListItemAllFields?$select=Id`,
          { headers: { Accept: "application/json;odata=nometadata" } },
        );
        const itemText = await itemResponse.text();
        if (!itemResponse.ok) throw new Error(`${itemResponse.status}: ${itemText}`);
        const item = JSON.parse(itemText);
        const context = await fetch(`${sitePath}/_api/contextinfo`, {
          method: "POST",
          headers: { Accept: "application/json;odata=nometadata" },
        });
        if (!context.ok) throw new Error(`${context.status}: ${await context.text()}`);
        const digest = (await context.json()).FormDigestValue;
        const response = await fetch(
          `${sitePath}/_api/web/lists/getbytitle('${encodeURIComponent(
            library,
          )}')/items(${item.Id})`,
          {
            method: "POST",
            headers: {
              Accept: "application/json;odata=nometadata",
              "Content-Type": "application/json;odata=nometadata",
              "X-RequestDigest": digest,
              "X-HTTP-Method": "MERGE",
              "IF-MATCH": itemResponse.headers.get("etag") || "*",
            },
            body: JSON.stringify(values),
          },
        );
        if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
        return item.Id;
      },
      { sitePath: job.sitePath, library, itemPath, values, isFolder },
    );

  const updateArtifactMetadataBatch = async (entries, agentIdField, agentId) =>
    page.evaluate(
      async ({ sitePath, library, entries, agentIdField, agentId }) => {
        const encodePath = (value) => encodeURIComponent(value).replace(/%2F/g, "/");
        const context = await fetch(`${sitePath}/_api/contextinfo`, {
          method: "POST",
          headers: { Accept: "application/json;odata=nometadata" },
        });
        if (!context.ok) throw new Error(`${context.status}: ${await context.text()}`);
        const digest = (await context.json()).FormDigestValue;
        return Promise.all(
          entries.map(async (entry) => {
            const itemResponse = await fetch(
              `${sitePath}/_api/web/GetFileByServerRelativePath(decodedurl='${encodePath(
                entry.remotePath,
              )}')/ListItemAllFields?$select=Id,${agentIdField}`,
              { headers: { Accept: "application/json;odata=nometadata" } },
            );
            const itemText = await itemResponse.text();
            if (!itemResponse.ok) {
              throw new Error(`${itemResponse.status}:${entry.remotePath}:${itemText}`);
            }
            const item = JSON.parse(itemText);
            if (item[agentIdField] === agentId) {
              return { remotePath: entry.remotePath, changed: false };
            }
            const response = await fetch(
              `${sitePath}/_api/web/lists/getbytitle('${encodeURIComponent(
                library,
              )}')/items(${item.Id})`,
              {
                method: "POST",
                headers: {
                  Accept: "application/json;odata=nometadata",
                  "Content-Type": "application/json;odata=nometadata",
                  "X-RequestDigest": digest,
                  "X-HTTP-Method": "MERGE",
                  "IF-MATCH": itemResponse.headers.get("etag") || "*",
                },
                body: JSON.stringify({ [agentIdField]: agentId }),
              },
            );
            if (!response.ok) {
              throw new Error(
                `${response.status}:${entry.remotePath}:${await response.text()}`,
              );
            }
            return { remotePath: entry.remotePath, changed: true };
          }),
        );
      },
      {
        sitePath: job.sitePath,
        library: job.artifactLibrary,
        entries,
        agentIdField,
        agentId,
      },
    );

  const zipEntry = job.entries[0];
  if (
    zipEntry?.artifactKey !== "deployableAgent" ||
    zipEntry?.uploadSequence !== 1
  ) {
    throw new Error("Deployable ZIP is not the first manifest item.");
  }

  const zipBefore = await inspectFile(zipEntry);
  const zipNeedsUpload = !zipBefore.exists || Number(zipBefore.Length) !== zipEntry.bytes;
  if (zipNeedsUpload) {
    await uploadBatch([zipEntry], "zip");
    actions.push({
      uploadSequence: 1,
      artifactKey: zipEntry.artifactKey,
      remotePath: zipEntry.remotePath,
      action: zipBefore.exists ? "replaced" : "uploaded",
    });
  } else {
    actions.push({
      uploadSequence: 1,
      artifactKey: zipEntry.artifactKey,
      remotePath: zipEntry.remotePath,
      action: "alreadyPublished",
    });
  }

  const agentFields = preflight.fields.agentLibrary;
  await updateItemMetadata({
    library: job.agentLibrary,
    itemPath: zipEntry.remotePath,
    values: {
      [agentFields.agentId]: job.agentLibraryMetadata.agentId,
      [agentFields.agentName]: job.agentLibraryMetadata.agentName,
      [agentFields.description]: job.agentLibraryMetadata.agentDescription,
      [agentFields.customerName]: job.agentLibraryMetadata.customerName,
    },
  });

  const verifiedAgentLibraryMetadata = await page.evaluate(
    async ({ sitePath, remotePath, fields }) => {
      const encodePath = (value) => encodeURIComponent(value).replace(/%2F/g, "/");
      const select = Object.values(fields).join(",");
      const response = await fetch(
        `${sitePath}/_api/web/GetFileByServerRelativePath(decodedurl='${encodePath(
          remotePath,
        )}')/ListItemAllFields?$select=${select}`,
        { headers: { Accept: "application/json;odata=nometadata" } },
      );
      const text = await response.text();
      if (!response.ok) throw new Error(`${response.status}: ${text}`);
      const item = JSON.parse(text);
      return {
        agentId: item[fields.agentId],
        agentName: item[fields.agentName],
        agentDescription: item[fields.description],
        customerName: item[fields.customerName],
      };
    },
    {
      sitePath: job.sitePath,
      remotePath: zipEntry.remotePath,
      fields: agentFields,
    },
  );
  const expectedAgentLibraryMetadata = {
    agentId: job.agentLibraryMetadata.agentId,
    agentName: job.agentLibraryMetadata.agentName,
    agentDescription: job.agentLibraryMetadata.agentDescription,
    customerName: job.agentLibraryMetadata.customerName,
  };
  if (
    Object.keys(expectedAgentLibraryMetadata).some(
      (key) =>
        verifiedAgentLibraryMetadata[key] !== expectedAgentLibraryMetadata[key],
    )
  ) {
    throw new Error("Agent Library metadata read-back mismatch.");
  }

  const artifactEntries = job.entries.slice(1);
  const artifactFolderSet = new Set([job.artifactAgentFolder]);
  for (const entry of artifactEntries) {
    let folder = folderName(entry.remotePath);
    while (
      folder === job.artifactAgentFolder ||
      folder.startsWith(`${job.artifactAgentFolder}/`)
    ) {
      artifactFolderSet.add(folder);
      if (folder === job.artifactAgentFolder) break;
      folder = folderName(folder);
    }
  }
  const artifactFolders = [...artifactFolderSet];
  await ensureFolders(artifactFolders);

  const artifactAgentIdField = preflight.fields.artifactLibrary.agentId;
  await updateItemMetadata({
    library: job.artifactLibrary,
    itemPath: job.artifactAgentFolder,
    values: { [artifactAgentIdField]: verifiedAgentLibraryMetadata.agentId },
    isFolder: true,
  });

  const inspections = [];
  for (const batch of chunks(artifactEntries, metadataConcurrency)) {
    inspections.push(...(await Promise.all(batch.map(inspectFile))));
  }
  const uploads = artifactEntries.filter(
    (entry, index) => !inspectionMatches(entry, inspections[index]),
  );
  const alreadyPublished = artifactEntries.filter(
    (entry, index) => inspectionMatches(entry, inspections[index]),
  );

  let batchIndex = 0;
  for (const batch of chunks(uploads, uploadConcurrency)) {
    await uploadBatch(batch, batchIndex++);
  }

  for (const entry of uploads) {
    actions.push({
      uploadSequence: entry.uploadSequence,
      artifactKey: entry.artifactKey,
      remotePath: entry.remotePath,
      action: "uploaded",
    });
  }
  for (const entry of alreadyPublished) {
    actions.push({
      uploadSequence: entry.uploadSequence,
      artifactKey: entry.artifactKey,
      remotePath: entry.remotePath,
      action: "alreadyPublished",
    });
  }
  actions.sort((left, right) => left.uploadSequence - right.uploadSequence);

  for (const batch of chunks(artifactEntries, metadataConcurrency)) {
    await updateArtifactMetadataBatch(
      batch,
      artifactAgentIdField,
      verifiedAgentLibraryMetadata.agentId,
    );
  }

  const rawFiles = await page.evaluate(
    async ({ sitePath, root }) => {
      const encodePath = (value) => encodeURIComponent(value).replace(/%2F/g, "/");
      const getJson = async (url) => {
        const response = await fetch(url, {
          headers: { Accept: "application/json;odata=nometadata" },
        });
        const text = await response.text();
        if (!response.ok) throw new Error(`${response.status}: ${text}`);
        return JSON.parse(text);
      };
      const files = [];
      const walk = async (path) => {
        const base = `${sitePath}/_api/web/GetFolderByServerRelativePath(decodedurl='${encodePath(
          path,
        )}')`;
        const [fileResult, folderResult] = await Promise.all([
          getJson(`${base}/Files?$select=Length,ServerRelativeUrl,UniqueId`),
          getJson(`${base}/Folders?$select=Name,ServerRelativeUrl`),
        ]);
        files.push(...fileResult.value);
        await Promise.all(
          folderResult.value
            .filter((folder) => folder.Name !== "Forms")
            .map((folder) => walk(folder.ServerRelativeUrl)),
        );
      };
      await walk(root);
      return files;
    },
    { sitePath: job.sitePath, root: job.artifactAgentFolder },
  );

  const artifactItems = [];
  for (const batch of chunks(rawFiles, metadataConcurrency)) {
    artifactItems.push(
      ...(await page.evaluate(
        async ({ sitePath, files, agentIdField }) => {
          const encodePath = (value) =>
            encodeURIComponent(value).replace(/%2F/g, "/");
          return Promise.all(
            files.map(async (file) => {
              const response = await fetch(
                `${sitePath}/_api/web/GetFileByServerRelativePath(decodedurl='${encodePath(
                  file.ServerRelativeUrl,
                )}')/ListItemAllFields?$select=${agentIdField}`,
                { headers: { Accept: "application/json;odata=nometadata" } },
              );
              const text = await response.text();
              if (!response.ok) throw new Error(`${response.status}: ${text}`);
              return {
                path: file.ServerRelativeUrl,
                agentId: JSON.parse(text)[agentIdField],
              };
            }),
          );
        },
        {
          sitePath: job.sitePath,
          files: batch,
          agentIdField: artifactAgentIdField,
        },
      )),
    );
  }
  const agentIdByPath = new Map(
    artifactItems.map((item) => [item.path, item.agentId]),
  );
  const comparableHashByPath = new Map();
  for (const entry of artifactEntries.filter((item) =>
    item.remotePath.toLowerCase().endsWith(".html")
  )) {
    const inspection = await inspectFile(entry);
    if (inspection.sha256) {
      comparableHashByPath.set(entry.remotePath, inspection.sha256);
    }
  }

  const [zipFile, artifactFolderMetadata] = await Promise.all([
    inspectFile(zipEntry),
    page.evaluate(
      async ({ sitePath, folder, agentIdField }) => {
        const encodePath = (value) => encodeURIComponent(value).replace(/%2F/g, "/");
        const response = await fetch(
          `${sitePath}/_api/web/GetFolderByServerRelativePath(decodedurl='${encodePath(
            folder,
          )}')/ListItemAllFields?$select=${agentIdField}`,
          { headers: { Accept: "application/json;odata=nometadata" } },
        );
        const text = await response.text();
        if (!response.ok) throw new Error(`${response.status}: ${text}`);
        return { agentId: JSON.parse(text)[agentIdField] };
      },
      {
        sitePath: job.sitePath,
        folder: job.artifactAgentFolder,
        agentIdField: artifactAgentIdField,
      },
    ),
  ]);

  const inventoryItems = rawFiles.map((file) => ({
    library: job.artifactLibrary,
    remotePath: file.ServerRelativeUrl,
    bytes: Number(file.Length),
    sha256: comparableHashByPath.get(file.ServerRelativeUrl) || "",
    remoteItemId: file.UniqueId,
    webUrl: webUrl(file.ServerRelativeUrl),
    agentId: agentIdByPath.get(file.ServerRelativeUrl) || "",
  }));
  inventoryItems.push({
    library: job.agentLibrary,
    remotePath: zipEntry.remotePath,
    bytes: Number(zipFile.Length),
    sha256: "",
    remoteItemId: zipFile.UniqueId,
    webUrl: webUrl(zipEntry.remotePath),
    agentId: "",
  });
  inventoryItems.sort((left, right) =>
    `${left.library}|${left.remotePath}`.localeCompare(
      `${right.library}|${right.remotePath}`,
    ),
  );

  const inventory = {
    executionOrder: actions
      .sort((left, right) => left.uploadSequence - right.uploadSequence)
      .map((action) => action.remotePath),
    items: inventoryItems,
    agentLibraryMetadata: verifiedAgentLibraryMetadata,
    artifactFolderMetadata,
  };
  const durationMs = Date.now() - startedMs;

  const result = {
    success: true,
    dryRun: false,
    transport: "authenticated-sharepoint-rest",
    fastPathUsed: true,
    fallbackReason: null,
    schemaCacheHit,
    uploadConcurrency,
    metadataConcurrency,
    startedAt,
    completedAt: new Date().toISOString(),
    durationMs,
    firstProcessedItem: actions[0]?.artifactKey,
    artifactAgentFolder: job.artifactAgentFolder,
    uploadedCount: actions.filter((action) => action.action === "uploaded").length,
    alreadyPublishedCount: actions.filter(
      (action) => action.action === "alreadyPublished",
    ).length,
    actions,
    inventory,
  };
  await page.evaluate((value) => {
    sessionStorage.setItem("artifactPublisherFastResult", JSON.stringify(value));
  }, result);
  return {
    success: result.success,
    transport: result.transport,
    fastPathUsed: result.fastPathUsed,
    durationMs: result.durationMs,
    firstProcessedItem: result.firstProcessedItem,
    uploadedCount: result.uploadedCount,
    alreadyPublishedCount: result.alreadyPublishedCount,
    inventoryCount: result.inventory.items.length,
  };
}
