# Third-party notices

- Microsoft Automatic Graph Layout (MSAGL) 1.1.6 - MIT License  
  https://github.com/microsoft/automatic-graph-layout
- `@resvg/resvg-js` 2.6.2 - Mozilla Public License 2.0  
  https://github.com/thx/resvg-js
- resvg/usvg - Apache License 2.0 or MIT License  
  https://github.com/linebender/resvg
- pngjs 7.0.0 - MIT License  
  https://github.com/pngjs/pngjs
- Inter 4.1 - SIL Open Font License 1.1  
  https://github.com/rsms/inter

## Microsoft product artwork

The offline product registry in `resources/icon-manifest.json` records source URLs,
retrieval dates, original SHA-256 hashes, media types, and product identities for
the added Teams, SharePoint, Microsoft 365 Copilot, Fabric, Power BI, and Azure
Service Bus assets. Dynamics 365 Finance uses its existing official product icon,
not the suite icon. These assets are packaged for architecture documentation;
Microsoft retains its artwork and trademark rights.

- Teams and SharePoint SVGs are the original Microsoft Office/Fluent CDN files.
- Microsoft 365 Copilot is the original Microsoft Learn PNG. Its bytes are embedded
  as `image/png`, without conversion, recoloring, cropping, or substitution with
  Agent 365, Copilot Studio, or Fabric Copilot artwork.
- Fabric and Power BI SVGs come from Microsoft's `fabric-samples` icon pack.
- Service Bus comes from the Azure Public Service Icons V24 pack.

The supplied Microsoft icon license is retained at
`resources/icons/licenses/Microsoft-icon-license.pdf`. The supplied Fabric
repository license is retained at `resources/icons/licenses/Fabric-icon-license.txt`.
These are source-specific notices, not a claim that the repository MIT license or
the Power Platform icon license licenses all Microsoft artwork or trademarks.
Consult the respective source pages and applicable terms before redistribution.
No icon download occurs during preparation, generation, repair, or publication.
