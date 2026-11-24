# Lisa data handling (Release 1)

The Lisa plugin asks Copilot Cowork to process the project you select. The analyzer reads `lisa-config.json` and files under `requirements/`. The classifier reads the validated analysis. The runners write extracted content, review batches, reports, ledgers, caches and manifests under the project's `output/analysis/` and `output/classification/` directories. These files can contain quotations, identifiers and paths from your inputs. Protect the output folder as you would the original requirements.

The package declares one remote connector: the public Microsoft Learn MCP endpoint. It receives documentation queries without connector credentials. Skill instructions direct Cowork to use generic product questions, not customer documents or identifying information. The classifier also retrieves public reference pages; those sites receive ordinary web requests. The analyzer is not instructed to follow links in source documents.

The plugin does not provide a separate hosted data store or deletion service. Project files remain subject to your OneDrive sharing, retention and deletion policies. Copilot Cowork, OneDrive, Microsoft Learn and any official vendor documentation sites are separate services; their applicable terms, tenant controls and privacy practices still apply. Use only inputs that you are authorized to process in those services.
