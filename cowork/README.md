# Lisa for Copilot Cowork

**Release 1 (v0.2.1)** of Lisa includes `lisa-requirement-analyzer`, `lisa-complexity-classifier`, and the public Microsoft Learn connector. It writes reports to the attached project folder; it does not deploy or publish to the tenant. Future releases update this same plugin.

[lisa/](lisa/) is the installable plugin project. Its [manifest](lisa/manifest.json) lists what ships. [skills/](skills/README.md) holds the full implementations, shared helpers and tests, including skills that are not in the ZIP.

## Upload Lisa to Cowork

1. [Download lisa.zip](lisa/dist/lisa.zip?raw=1). Upload it as-is; do not zip the whole `cowork` folder or upload an individual `SKILL.md`.
2. In Copilot Cowork, select **+ > Customize > Plugins > Upload plugin** and choose the ZIP.
3. In **Share**, choose **Only you** for a personal test or **Specific users in your organization** for a pilot. Add the pilot users by name or email, then select **Apply**.

**Administrator-managed installation:** If self-service upload is unavailable or the plugin needs organizational distribution, give the ZIP to your Microsoft 365 administrator. In the admin center, select **Agents > Tools > Registry > Upload**, choose the package, review its skills and connectors, select **Next**, choose the intended users or groups, then select **Install**.

Microsoft Learn: [Upload your own plugin package](https://learn.microsoft.com/copilot/cowork/cowork-plugins#upload-your-own-plugin-package) · [Upload plugins in the admin center](https://learn.microsoft.com/microsoft-agent-365/admin/manage-plugins-skills-mcp-servers#upload-plugins-or-skills).

## Try a plugin in a project folder

Follow the [OneDrive walkthrough](lisa/README.md#try-it-with-a-onedrive-project) to run analysis, then classify its validated output in a new task. Before sharing the plugin with pilot users, complete the [release checks](lisa/README.md#pilot-release-checks).
