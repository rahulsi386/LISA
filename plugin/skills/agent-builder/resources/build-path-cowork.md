# Build path D — Microsoft Cowork configuration

Read this file only when the validated platform is Microsoft Cowork, or for the Cowork portion of
a mixed build. The shared gates in `SKILL.md` Sections 1–8 still apply.

Microsoft Cowork is an independent agentic platform/tool, not a Copilot Studio harness. Use Cowork only when the classifier marks the capability buildable and current tenant evidence confirms a reproducible configuration path, required plugins or skills, identity behavior, governance, and user availability. Persist `agenticPlatform: Microsoft Cowork` and `harness: null`.

1. Verify browser identity, tenant, licensing, and product availability before saving configuration.
2. Configure only the classified skills, plugins, data access, and delegated-work boundaries.
3. Store screenshots or exported configuration evidence beneath `build\evidence`.
4. Verify user-visible simulation disclosures, permissions, and the actual delegated result without claiming shared-application behavior.
5. When no supported package mechanism exists, use `buildMode: cowork-configuration`, emit no ZIP, and record portability as a production-readiness gap.
6. If Cowork is unavailable or differs from the classification, mark the component blocked or deferred and recalculate coverage. Do not substitute Copilot Studio without classifier review.
