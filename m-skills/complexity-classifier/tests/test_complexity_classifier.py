from __future__ import annotations

import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_ROOT / "scripts" / "complexity_classifier.py"
FIXTURE = SKILL_ROOT / "tests" / "fixtures" / "basic"


class ComplexityClassifierTests(unittest.TestCase):
    maxDiff = None

    def run_cli(self, *arguments: str, expected: int = 0) -> dict:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            expected,
            completed.returncode,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        return json.loads(completed.stdout.strip() or completed.stderr.strip())

    def prepare(
        self,
        temporary: Path,
        *,
        local_time: str = "2026-08-13T12:30:00+05:30",
        lisa_config: dict | None = None,
    ) -> tuple[dict, dict]:
        output = temporary / "output"
        if not (output / "analysis").exists():
            shutil.copytree(FIXTURE / "analysis", output / "analysis")
        config = {"basePath": "."}
        if lisa_config is not None:
            config.update(lisa_config)
        config_path = temporary / "lisa-config.json"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        prepared = self.run_cli(
            "prepare",
            "--config",
            str(config_path),
            "--local-time",
            local_time,
            "--offline",
        )
        run = json.loads(Path(prepared["run"]).read_text(encoding="utf-8"))
        self.assertEqual("copilot", prepared["research_stage"])
        self.assertEqual(
            (output / "classification").resolve(),
            Path(run["classification_root"]),
        )
        return prepared, run

    def prepare_delegated(self, temporary: Path) -> tuple[dict, dict]:
        analysis = temporary / "output" / "analysis"
        shutil.copytree(FIXTURE / "analysis", analysis)
        input_path = next(analysis.glob("requirement-analysis_*.json"))
        value = json.loads(input_path.read_text(encoding="utf-8"))
        target = next(
            item
            for item in value["findings"]
            if item["finding_id"] == "REQ-AAAA000001"
        )
        target["statement"] = (
            "Each leader requires a personal digital worker for delegated personal work."
        )
        second = next(
            item
            for item in value["findings"]
            if item["finding_id"] == "REQ-BBBB000002"
        )
        second["statement"] = (
            "Apply the same briefing method consistently across every run and "
            "retrieve current tasks from an external task-management system without manual export."
        )
        input_path.write_text(json.dumps(value, indent=2), encoding="utf-8")
        return self.prepare(temporary)

    @staticmethod
    def item(
        name: str,
        *,
        evidence: list[str] | None = None,
        refs: list[str] | None = None,
        basis: str = "evidenced",
        tier: str | None = None,
        sources: list[str] | None = None,
    ) -> dict:
        value = {
            "name": name,
            "selection_basis": basis,
            "evidence_ids": evidence or [],
            "reference_ids": refs or [],
            "source_refs": sources or [],
        }
        if tier:
            value["implementation_tier"] = tier
        return value

    @classmethod
    def easy_tool(cls, name: str) -> dict:
        return {
            **cls.item(
                name,
                evidence=["REQ-AAAA000001"],
                refs=["copilot-studio-tools"],
                tier="No-code",
            ),
            "integrability": "easily-integrable",
            "implementation": "Use a supported Copilot Studio action.",
            "creation_method": "Native action",
        }

    @classmethod
    def solution_topology(cls, model: dict) -> dict:
        inventory = model["components"]
        agent_name = inventory["agents"][0]["name"]
        channel_names = [
            item["name"] for item in inventory["communication_channels"]
        ]

        def grounded(
            *,
            evidence: list[str] | None = None,
            refs: list[str] | None = None,
        ) -> dict:
            return {
                "evidence_ids": evidence or [],
                "reference_ids": refs or ["copilot-studio-guidance"],
                "source_refs": [],
            }

        def component(
            identifier: str,
            name: str,
            category: str,
            product: str,
            inventory_names: list[str],
            *,
            component_type: str = "configurable",
            boundary: str = "power-platform-environment",
            lifecycle: str = "configure",
            refs: list[str] | None = None,
            evidence: list[str] | None = None,
        ) -> dict:
            return {
                "id": identifier,
                "name": name,
                "category": category,
                "component_type": component_type,
                "product_service": product,
                "role": f"Implements {name} as an explicit architecture component.",
                "hosting_runtime": product,
                "deployment_boundary": boundary,
                "lifecycle": lifecycle,
                "environment_scope": (
                    "external"
                    if component_type == "external"
                    else "user"
                    if component_type == "human"
                    else "dev-test-prod"
                ),
                "inventory_names": inventory_names,
                "reliability": "Use managed-service availability, bounded retries, and observable failures.",
                "scalability": "Use independent managed-service capacity and throttling controls.",
                "security": "Use least privilege, authenticated access, and governed data handling.",
                **grounded(evidence=evidence, refs=refs),
            }

        topology_components = [
            component(
                "procurement-user",
                "Procurement user",
                "actor",
                "Microsoft 365 user",
                [],
                component_type="human",
                boundary="user",
                lifecycle="existing",
                refs=["copilot-studio-teams-channel"],
            ),
            component(
                "copilot-studio-platform",
                "Copilot Studio agent platform",
                "agent-platform",
                "Microsoft Copilot Studio",
                [item["name"] for item in inventory["platform_capabilities"]],
                refs=[
                    "copilot-studio-fundamentals",
                    "copilot-studio-guidance",
                    "power-platform-well-architected",
                ],
            ),
            component(
                "policy-agent",
                agent_name,
                "agent",
                "Microsoft Copilot Studio",
                [item["name"] for item in inventory["agents"]],
                evidence=["REQ-AAAA000001"],
                refs=[
                    "copilot-studio-fundamentals",
                    "copilot-studio-orchestration",
                ],
            ),
        ]
        for index, item in enumerate(inventory["communication_channels"], 1):
            topology_components.append(
                component(
                    f"channel-{index}",
                    item["name"],
                    "channel",
                    item["name"],
                    [item["name"]],
                    component_type="managed-service",
                    boundary="channel",
                    lifecycle="existing",
                    refs=item["reference_ids"],
                )
            )
        topology_components.append(
            component(
                "policy-knowledge",
                "Policy knowledge grounding",
                "knowledge-source",
                "Microsoft Copilot Studio knowledge",
                [item["name"] for item in inventory["knowledge_sources"]],
                refs=["copilot-studio-knowledge"],
                evidence=["REQ-AAAA000001"],
            )
        )
        tool_ids: list[str] = []
        for index, item in enumerate(inventory["tools"], 1):
            identifier = f"tool-{index}"
            tool_ids.append(identifier)
            creation_method = item.get("creation_method", "Other")
            product = {
                "Native action": "Microsoft Copilot Studio native action",
                "Connector": "Microsoft Power Platform connector",
                "Plugin": "Microsoft Cowork plugin",
                "Agent flow": "Microsoft Copilot Studio agent flow",
                "Power Automate workflow": "Microsoft Power Automate",
                "MCP server": "Azure Functions hosted MCP server",
                "Custom connector": "Microsoft Power Platform custom connector",
                "Custom API": "Azure Functions and Azure API Management",
                "Other": "Microsoft Copilot Studio tool",
            }[creation_method]
            topology_components.append(
                component(
                    identifier,
                    item["name"],
                    "tool",
                    product,
                    [item["name"]],
                    component_type=(
                        "deployable"
                        if item["integrability"] == "custom"
                        else "configurable"
                    ),
                    lifecycle=(
                        "build"
                        if item["integrability"] == "custom"
                        else "configure"
                    ),
                    refs=list(
                        dict.fromkeys(
                            item["reference_ids"]
                            + (
                                ["azure-functions", "azure-api-management"]
                                if item["integrability"] == "custom"
                                else []
                            )
                        )
                    ),
                    evidence=item["evidence_ids"],
                )
            )
        for index, item in enumerate(inventory["skills"], 1):
            topology_components.append(
                component(
                    f"skill-{index}",
                    item["name"],
                    "tool",
                    "Microsoft Copilot Studio skill",
                    [item["name"]],
                    refs=item["reference_ids"],
                    evidence=item["evidence_ids"],
                )
            )
        for index, item in enumerate(inventory["connected_agents"], 1):
            topology_components.append(
                component(
                    f"connected-agent-{index}",
                    item["name"],
                    "agent",
                    "Microsoft Copilot Studio connected agent",
                    [item["name"]],
                    refs=item["reference_ids"],
                    evidence=item["evidence_ids"],
                )
            )
        if inventory["triggers"] or inventory["automation"]:
            topology_components.append(
                component(
                    "agent-automation",
                    "Policy agent automation",
                    "automation",
                    "Microsoft Copilot Studio autonomous triggers and Power Automate",
                    [
                        item["name"]
                        for item in inventory["triggers"] + inventory["automation"]
                    ],
                    refs=["copilot-studio-autonomous", "power-automate"],
                    evidence=[
                        identifier
                        for item in inventory["triggers"] + inventory["automation"]
                        for identifier in item["evidence_ids"]
                    ],
                )
            )
        topology_components.append(
            component(
                "m365-integration",
                inventory["integration"][0]["name"],
                "integration",
                "Microsoft 365 and Power Platform standard connectors",
                [item["name"] for item in inventory["integration"]],
                refs=["copilot-studio-tools", "power-automate"],
            )
        )
        topology_components.extend(
            [
                component(
                    "dataverse-store",
                    "Policy solution data store",
                    "data-store",
                    "Microsoft Dataverse",
                    [item["name"] for item in inventory["data"]],
                    component_type="managed-service",
                    refs=["dataverse"],
                ),
                component(
                    "entra-identity",
                    "Agent identity and access",
                    "identity",
                    "Microsoft Entra ID",
                    [
                        inventory["authentication"]["platform"],
                        inventory["authentication"]["tool"],
                        inventory["authorization"]["platform"],
                        inventory["authorization"]["tool"],
                    ],
                    component_type="managed-service",
                    refs=["entra-id", "copilot-studio-authentication"],
                ),
                component(
                    "information-protection",
                    "Agent information protection",
                    "security",
                    "Microsoft Purview and Power Platform data policies",
                    [item["name"] for item in inventory["security_controls"]],
                    component_type="managed-service",
                    refs=["microsoft-purview", "power-platform-dlp"],
                ),
                component(
                    "managed-governance",
                    "Agent platform governance",
                    "governance",
                    "Power Platform Managed Environments",
                    [item["name"] for item in inventory["governance_controls"]],
                    component_type="managed-service",
                    refs=["managed-environments", "power-platform-dlp"],
                ),
                component(
                    "solution-alm",
                    "Agent solution lifecycle",
                    "alm",
                    "Power Platform solutions and deployment pipelines",
                    [item["name"] for item in inventory["alm"]],
                    component_type="managed-service",
                    refs=["power-platform-alm", "power-platform-pipelines"],
                ),
                component(
                    "agent-monitoring",
                    "Agent operational monitoring",
                    "monitoring",
                    "Microsoft Copilot Studio analytics",
                    [],
                    component_type="managed-service",
                    lifecycle="recommended",
                    refs=[
                        "copilot-studio-analytics",
                        "power-platform-well-architected",
                    ],
                ),
            ]
        )

        def relationship(
            identifier: str,
            source: str,
            target: str,
            kind: str,
            interaction: str,
            *,
            refs: list[str],
            direction: str = "unidirectional",
            access: str = "execute",
        ) -> dict:
            return {
                "id": identifier,
                "source_id": source,
                "target_id": target,
                "relationship_type": kind,
                "interaction": interaction,
                "direction": direction,
                "integration_method": "Microsoft managed service interface",
                "protocol": "HTTPS",
                "data_flow": interaction,
                "access": access,
                "authentication": "Microsoft Entra ID OAuth 2.0",
                "synchronous": kind not in {"triggers", "monitors"},
                "failure_behavior": "Apply bounded retries, surface failures, and use human escalation where required.",
                **grounded(refs=refs),
            }

        relationships = [
            relationship(
                "rel-platform-agent",
                "copilot-studio-platform",
                "policy-agent",
                "hosts",
                "Host agent orchestration",
                refs=["copilot-studio-fundamentals"],
            )
        ]
        for index, _ in enumerate(channel_names, 1):
            relationships.extend(
                [
                    relationship(
                        f"rel-user-channel-{index}",
                        "procurement-user",
                        f"channel-{index}",
                        "communicates",
                        "Submit and receive agent conversations",
                        refs=["copilot-studio-teams-channel"],
                    ),
                    relationship(
                        f"rel-channel-agent-{index}",
                        f"channel-{index}",
                        "policy-agent",
                        "publishes-to",
                        "Deliver the request to the published agent",
                        refs=["copilot-studio-channels"],
                    ),
                ]
            )
        relationships.extend(
            [
                relationship(
                    "rel-user-authentication",
                    "procurement-user",
                    "entra-identity",
                    "authenticates",
                    "Authenticate the user",
                    refs=["entra-id", "copilot-studio-authentication"],
                ),
                relationship(
                    "rel-identity-authorization",
                    "entra-identity",
                    "policy-agent",
                    "authorizes",
                    "Authorize the Copilot Studio session",
                    refs=["entra-id", "copilot-studio-authentication"],
                ),
                relationship(
                    "rel-agent-knowledge",
                    "policy-agent",
                    "policy-knowledge",
                    "retrieves",
                    "Retrieve grounded policy knowledge",
                    refs=["copilot-studio-knowledge"],
                    direction="bidirectional",
                    access="read",
                ),
            ]
        )
        for index, identifier in enumerate(tool_ids, 1):
            relationships.append(
                relationship(
                    f"rel-agent-tool-{index}",
                    "policy-agent",
                    identifier,
                    "invokes",
                    f"Invoke {inventory['tools'][index - 1]['name']}",
                    refs=["copilot-studio-tools"],
                    direction="bidirectional",
                )
            )
        for index, _ in enumerate(inventory["skills"], 1):
            relationships.append(
                relationship(
                    f"rel-agent-skill-{index}",
                    "policy-agent",
                    f"skill-{index}",
                    "invokes",
                    "Invoke structured agent skill",
                    refs=["copilot-studio-tools"],
                )
            )
        for index, _ in enumerate(inventory["connected_agents"], 1):
            relationships.append(
                relationship(
                    f"rel-agent-connected-{index}",
                    "policy-agent",
                    f"connected-agent-{index}",
                    "integrates",
                    "Delegate to connected agent",
                    refs=["copilot-studio-connected-agents"],
                    direction="bidirectional",
                )
            )
        relationships.extend(
            [
                relationship(
                    "rel-tool-data",
                    tool_ids[0],
                    "dataverse-store",
                    "reads",
                    "Read governed solution data",
                    refs=["dataverse"],
                    direction="bidirectional",
                    access="read",
                ),
                relationship(
                    "rel-tool-integration",
                    tool_ids[0],
                    "m365-integration",
                    "integrates",
                    "Invoke the standard connector",
                    refs=["copilot-studio-tools", "power-automate"],
                    direction="bidirectional",
                ),
                relationship(
                    "rel-security-agent",
                    "information-protection",
                    "policy-agent",
                    "protects",
                    "Apply DLP and information protection",
                    refs=["power-platform-dlp", "microsoft-purview"],
                ),
                relationship(
                    "rel-governance-agent",
                    "managed-governance",
                    "policy-agent",
                    "governs",
                    "Apply managed environment governance",
                    refs=["managed-environments"],
                ),
                relationship(
                    "rel-alm-agent",
                    "solution-alm",
                    "policy-agent",
                    "deploys",
                    "Promote the managed agent solution",
                    refs=["power-platform-alm", "power-platform-pipelines"],
                ),
                relationship(
                    "rel-monitor-agent",
                    "agent-monitoring",
                    "policy-agent",
                    "monitors",
                    "Collect agent operational telemetry",
                    refs=["copilot-studio-analytics"],
                ),
                relationship(
                    "rel-agent-response",
                    "policy-agent",
                    "procurement-user",
                    "responds",
                    "Return the grounded response",
                    refs=["copilot-studio-orchestration"],
                ),
            ]
        )
        if inventory["triggers"]:
            relationships.append(
                relationship(
                    "rel-automation-agent",
                    "agent-automation",
                    "policy-agent",
                    "triggers",
                    "Start the autonomous agent cycle",
                    refs=["copilot-studio-autonomous"],
                )
            )

        sequence_specs = [
            (
                "seq-authenticate",
                "Authentication",
                "procurement-user",
                "entra-identity",
                "Authenticate the user",
                "call",
                ["entra-id"],
            ),
            (
                "seq-authorize",
                "Authentication",
                "entra-identity",
                "policy-agent",
                "Authorize the agent session",
                "call",
                ["copilot-studio-authentication"],
            ),
            (
                "seq-request-channel",
                "Request",
                "procurement-user",
                "channel-1",
                "Submit the request",
                "call",
                ["copilot-studio-teams-channel"],
            ),
            (
                "seq-channel-agent",
                "Request",
                "channel-1",
                "policy-agent",
                "Deliver the request",
                "call",
                ["copilot-studio-channels"],
            ),
            (
                "seq-orchestrate",
                "Orchestration",
                "policy-agent",
                "policy-agent",
                "Plan the grounded response",
                "self",
                ["copilot-studio-orchestration"],
            ),
            (
                "seq-ground",
                "Grounding",
                "policy-agent",
                "policy-knowledge",
                "Retrieve grounded policy knowledge",
                "call",
                ["copilot-studio-knowledge"],
            ),
            (
                "seq-ground-response",
                "Grounding",
                "policy-knowledge",
                "policy-agent",
                "Return grounded evidence",
                "response",
                ["copilot-studio-knowledge"],
            ),
            (
                "seq-invoke-tool",
                "Action",
                "policy-agent",
                tool_ids[0],
                "Invoke the selected tool",
                "call",
                ["copilot-studio-tools"],
            ),
            (
                "seq-read-data",
                "Action",
                tool_ids[0],
                "dataverse-store",
                "Read governed solution data",
                "call",
                ["dataverse"],
            ),
            (
                "seq-return-data",
                "Action",
                "dataverse-store",
                tool_ids[0],
                "Return the data result",
                "response",
                ["dataverse"],
            ),
            (
                "seq-return-response",
                "Response",
                "policy-agent",
                "procurement-user",
                "Return the grounded response",
                "response",
                ["copilot-studio-orchestration"],
            ),
        ]
        if inventory["triggers"]:
            sequence_specs.insert(
                4,
                (
                    "seq-automation",
                    "Automation",
                    "agent-automation",
                    "policy-agent",
                    "Start the scheduled agent cycle",
                    "call",
                    ["copilot-studio-autonomous"],
                ),
            )
        sequence = [
            {
                "id": identifier,
                "order": index,
                "phase": phase,
                "source_id": source,
                "target_id": target,
                "action": action,
                "message_type": message_type,
                "condition": None,
                **grounded(refs=refs),
            }
            for index, (
                identifier,
                phase,
                source,
                target,
                action,
                message_type,
                refs,
            ) in enumerate(sequence_specs, 1)
        ]

        deployment_ids = [
            item["id"]
            for item in topology_components
            if item["environment_scope"] == "dev-test-prod"
        ]
        return {
            "architecture_summary": "A modular Copilot Studio architecture separates channels, orchestration, tools, data, identity, governance, monitoring, and ALM into explicit boundaries.",
            "architecture_principles": [
                {
                    "dimension": dimension,
                    "decision": f"Apply the {dimension} architecture quality.",
                    "implementation": f"Use explicit Microsoft managed components and controls to keep the solution {dimension}.",
                    "reference_ids": [
                        "copilot-studio-guidance",
                        "power-platform-well-architected",
                    ],
                }
                for dimension in (
                    "reusable",
                    "modular",
                    "reliable",
                    "secure",
                    "scalable",
                )
            ],
            "components": topology_components,
            "relationships": relationships,
            "trust_boundaries": [
                {
                    "id": "trust-power-platform",
                    "name": "Power Platform environment trust boundary",
                    "boundary_type": "environment",
                    "component_ids": deployment_ids,
                    "controls": [
                        "Microsoft Entra ID",
                        "Power Platform data policies",
                        "Managed Environments",
                    ],
                    **grounded(
                        refs=[
                            "entra-id",
                            "power-platform-dlp",
                            "managed-environments",
                        ]
                    ),
                }
            ],
            "environments": [
                {
                    "name": name,
                    "purpose": purpose,
                    "component_ids": deployment_ids,
                    "promotion_via": "Power Platform solutions and deployment pipelines",
                    "reference_ids": [
                        "power-platform-alm",
                        "power-platform-pipelines",
                    ],
                }
                for name, purpose in (
                    ("Development", "Build and component test"),
                    ("Test", "Integrated validation and acceptance"),
                    ("Production", "Managed production operation"),
                )
            ],
            "sequence_flows": sequence,
        }

    @classmethod
    def model(
        cls,
        run_id: str,
        *,
        tools: list[dict] | None = None,
        skills: list[dict] | None = None,
        connected_agents: list[dict] | None = None,
        triggers: list[dict] | None = None,
        code_tier: str = "No-code",
        harness: str | None = "Standard",
        uses_low_code: bool = False,
        requires_custom: bool = False,
        requires_pro_code: bool = False,
    ) -> dict:
        evidence = ["REQ-AAAA000001"]
        if tools is None:
            tools = [cls.easy_tool("Grounded knowledge retrieval")]
        if triggers is None:
            triggers = [
                {
                    **cls.item(
                        "Scheduled compliance trigger",
                        evidence=["REQ-BBBB000002"],
                        refs=["copilot-studio-autonomous"],
                        tier="No-code",
                    ),
                    "trigger_type": "scheduled",
                    "mechanism": "Copilot Studio autonomous scheduled trigger",
                    "agent_names": ["Policy assistant"],
                }
            ]
        model = {
            "schema_version": "3.0",
            "run_id": run_id,
            "research_stage": "copilot",
            "platform_assessment": {
                "copilot_studio_fit": "full",
                "cowork_fit": "not-assessed",
                "foundry_fit": "not-assessed",
                "agent_framework_fit": "not-assessed",
                "unmet_requirements": [],
                "decision_summary": "Copilot Studio and Power Platform satisfy all in-scope requirements.",
            },
            "requirement_assessments": [
                {
                    "finding_id": "REQ-AAAA000001",
                    "status": "satisfied",
                    "platform": "Copilot Studio",
                    "capability": "Generative orchestration and grounded knowledge",
                    "reference_ids": [
                        "copilot-studio-orchestration",
                        "copilot-studio-knowledge",
                    ],
                },
                {
                    "finding_id": "REQ-BBBB000002",
                    "status": "satisfied",
                    "platform": "Copilot Studio",
                    "capability": "Autonomous scheduled trigger",
                    "reference_ids": ["copilot-studio-autonomous"],
                },
            ],
            "agentic_platform": "Copilot Studio",
            "code_tier": code_tier,
            "harness": harness,
            "harness_rationale": "Standard harness supports grounded guidance and scheduled triggers.",
            "billing_implication": "Standard Copilot Studio licensing applies.",
            "delivery_assessment": {
                "allowed_tools": [
                    "Microsoft Copilot Studio",
                    "Microsoft 365 Copilot Chat",
                    "Microsoft Cowork",
                    "Microsoft Teams",
                ],
                "platform_gates": [
                    {
                        "product": "Microsoft Copilot Studio",
                        "gate": gate,
                        "result": "pass",
                        "scope": "Validated for the fixture environment and PoC scope.",
                        "evidence_refs": ["copilot-studio-fundamentals"],
                        "exception_owner": None,
                        "blocker_for_poc": True,
                    }
                    for gate in (
                        "product-availability",
                        "allowed-tool-compliance",
                        "authentication",
                        "least-privilege",
                        "test-data",
                        "action-control",
                        "simulation-disclosure",
                        "auditability",
                        "builder-path",
                    )
                ],
                "candidate_scores": [
                    {
                        "product": "Microsoft Copilot Studio",
                        "categories": [
                            {
                                "category": category,
                                "weight": weight,
                                "score": 4,
                                "evidence_refs": ["copilot-studio-fundamentals"],
                                "confidence": "high",
                            }
                            for category, weight in (
                                ("security-data-control", 20),
                                ("safety-action-control", 15),
                                ("functional-reasoning-fit", 15),
                                ("data-tools-channels-integration", 15),
                                ("reliability-observability-support", 12),
                                ("engineering-alm-portability", 10),
                                ("cost-capacity-effort", 8),
                                ("availability-maturity-risk", 5),
                            )
                        ],
                    }
                ],
                "solution_complexity": "Medium",
                "capabilities": [
                    {
                        "id": "CAP-001",
                        "name": "Provide grounded policy guidance",
                        "requirement_ids": ["REQ-AAAA000001"],
                        "business_priority": "must",
                        "business_weight": 5,
                        "work_type": "knowledge-retrieval",
                        "action_impact": "read-only",
                        "dependencies": [],
                        "component_ids": ["policy-agent", "policy-knowledge"],
                        "implementation_status": "configurable",
                        "coverage_factor": 1,
                        "demonstration_factor": 1,
                        "allowed_product": "Microsoft Copilot Studio",
                        "harness": "Standard",
                        "implementation_method": "Copilot Studio knowledge and generative orchestration",
                        "supported_portion": "Retrieve and answer from the approved policy source.",
                        "unsupported_portion": None,
                        "poc_treatment": "configure",
                        "build_owner": "agent-builder",
                        "build_contract": {
                            "inputs": [{"name": "question", "type": "string", "required": True, "description": "User policy question."}],
                            "outputs": [{"name": "answer", "type": "string", "required": True, "description": "Grounded answer."}],
                            "authentication": "Microsoft Entra ID user authentication",
                            "authorization": "Source permissions of the signed-in user",
                            "approval_required": False,
                            "side_effects": "Read-only retrieval.",
                            "success_result": "Return grounded policy guidance.",
                            "partial_result": "State which evidence is missing.",
                            "error_result": "Report that policy guidance is unavailable.",
                            "timeout_behavior": "Stop and return a safe availability message.",
                            "idempotency": "Read-only operation.",
                            "configuration_refs": ["Policy"],
                            "simulation_disclosure": None,
                        },
                        "verification_method": "Verify the source is attached and ready in the live agent.",
                        "confidence": "high",
                    },
                    {
                        "id": "CAP-002",
                        "name": "Run the scheduled policy check",
                        "requirement_ids": ["REQ-BBBB000002"],
                        "business_priority": "should",
                        "business_weight": 3,
                        "work_type": "deterministic-execution",
                        "action_impact": "read-only",
                        "dependencies": ["CAP-001"],
                        "component_ids": ["agent-automation", "policy-agent"],
                        "implementation_status": "native",
                        "coverage_factor": 1,
                        "demonstration_factor": 1,
                        "allowed_product": "Microsoft Copilot Studio",
                        "harness": "Standard",
                        "implementation_method": "Copilot Studio scheduled autonomous trigger",
                        "supported_portion": "Start the policy check on the configured schedule.",
                        "unsupported_portion": None,
                        "poc_treatment": "build",
                        "build_owner": "agent-builder",
                        "build_contract": {
                            "inputs": [],
                            "outputs": [{"name": "status", "type": "string", "required": True, "description": "Run status."}],
                            "authentication": "Copilot Studio trigger connection",
                            "authorization": "Least-privilege trigger owner connection",
                            "approval_required": False,
                            "side_effects": "Starts a read-only policy check.",
                            "success_result": "Record successful trigger execution.",
                            "partial_result": "Record partial source availability.",
                            "error_result": "Record the trigger failure without claiming completion.",
                            "timeout_behavior": "Stop the run and report timeout.",
                            "idempotency": "Use the scheduled run identifier for duplicate suppression.",
                            "configuration_refs": ["Scheduled compliance trigger"],
                            "simulation_disclosure": None,
                        },
                        "verification_method": "Verify the live trigger exists and targets the policy agent.",
                        "confidence": "high",
                    },
                ],
                "poc_scope": {
                    "objective": "Demonstrate grounded policy guidance and scheduled execution.",
                    "included_capability_ids": ["CAP-001", "CAP-002"],
                    "excluded_capability_ids": [],
                    "test_data_boundary": "Use fixture policy data only.",
                },
                "production_readiness_gaps": [],
            },
            "components": {
                "agents": [
                    {
                        **cls.item("Policy assistant", evidence=evidence),
                        "behaviors": ["Conversational", "Autonomous"],
                    }
                ],
                "platform_capabilities": [
                    cls.item(
                        "Copilot Studio generative orchestration and instructions",
                        refs=[
                            "copilot-studio-fundamentals",
                            "copilot-studio-orchestration",
                            "copilot-studio-harnesses",
                            "copilot-studio-guidance",
                            "power-platform-well-architected",
                        ],
                        basis="recommended",
                        tier="No-code",
                    )
                ],
                "knowledge_sources": [
                    cls.item("Policy", evidence=evidence)
                ],
                "tools": tools,
                "skills": skills or [],
                "connected_agents": connected_agents or [],
                "triggers": triggers,
                "automation": [],
                "integration": [
                    {
                        **cls.item(
                            "Microsoft 365 standard connector",
                            refs=["copilot-studio-tools"],
                            basis="recommended",
                            tier="No-code",
                        ),
                        "method": "Native connector",
                        "integrability": "easily-integrable",
                    }
                ],
                "data": [
                    cls.item(
                        "Microsoft Dataverse solution state",
                        refs=["dataverse"],
                        basis="recommended",
                        tier="No-code",
                    )
                ],
                "authentication": {
                    "platform": "Microsoft Entra ID",
                    "tool": "Copilot Studio user authentication",
                    "configuration": "Authenticate users and use connection references.",
                    "selection_basis": "mandatory-baseline",
                    "evidence_ids": [],
                    "reference_ids": [
                        "entra-id",
                        "copilot-studio-authentication",
                    ],
                    "source_refs": [],
                },
                "authorization": {
                    "platform": "Microsoft Entra ID and source permissions",
                    "tool": "Copilot Studio connector authorization",
                    "configuration": "Use least privilege and human approval.",
                    "selection_basis": "mandatory-baseline",
                    "evidence_ids": [],
                    "reference_ids": [
                        "entra-id",
                        "copilot-studio-authentication",
                    ],
                    "source_refs": [],
                },
                "security_controls": [
                    cls.item(
                        "Power Platform DLP and Microsoft Purview",
                        refs=["power-platform-dlp", "microsoft-purview"],
                        basis="mandatory-baseline",
                        tier="No-code",
                    )
                ],
                "governance_controls": [
                    cls.item(
                        "Managed Environment governance",
                        refs=["managed-environments", "power-platform-dlp"],
                        basis="mandatory-baseline",
                        tier="No-code",
                    )
                ],
                "alm": [
                    cls.item(
                        "Power Platform solution ALM",
                        refs=["power-platform-alm"],
                        basis="mandatory-baseline",
                        tier="No-code",
                    )
                ],
                "communication_channels": [
                    cls.item(
                        "Microsoft Teams",
                        refs=["copilot-studio-teams-channel"],
                        basis="default",
                    ),
                    cls.item(
                        "Microsoft 365 Copilot",
                        refs=["m365-declarative-agents"],
                        basis="default",
                    ),
                ],
            },
            "flags": {
                "requires_pro_code": requires_pro_code,
                "requires_custom_or_gateway": requires_custom,
                "uses_low_code": uses_low_code,
                "autonomous_multistep": False,
                "uses_memory": False,
            },
            "justification_paragraphs": [
                "The solution is grounded in the required user capability [REQ-AAAA000001].",
                "The scheduled trigger is grounded in the autonomous requirement [REQ-BBBB000002].",
            ],
            "gaps": [
                cls.item(
                    "Delivery channel was absent and defaults were applied",
                    evidence=["GAP-CCCC000003"],
                )
            ],
        }
        if not triggers:
            model["delivery_assessment"]["capabilities"][1]["component_ids"] = [
                "policy-agent"
            ]
        model["solution_topology"] = cls.solution_topology(model)
        return model

    @classmethod
    def cowork_model(cls, run_id: str) -> dict:
        model = copy.deepcopy(cls.model(run_id))
        model["platform_assessment"].update(
            {
                "copilot_studio_fit": "partial",
                "cowork_fit": "full",
                "decision_summary": (
                    "Cowork is the full-fit personal delegated-work experience; "
                    "Copilot Studio would change the requirement into a shared application."
                ),
            }
        )
        for assessment in model["requirement_assessments"]:
            assessment.update(
                {
                    "platform": "Microsoft Cowork",
                    "capability": "Cowork delegated work, built-in skills, and scheduled tasks",
                    "reference_ids": ["cowork-overview", "cowork-get-started"],
                }
            )
        model.update(
            {
                "agentic_platform": "Microsoft Cowork",
                "code_tier": "No-code",
                "harness": "Cowork",
                "harness_rationale": (
                    "Cowork performs user-owned delegated work and creates private drafts."
                ),
                "billing_implication": (
                    "Microsoft 365 Copilot access, Cowork enablement, and usage-based billing are required."
                ),
            }
        )
        gate_names = (
            "product-availability",
            "allowed-tool-compliance",
            "authentication",
            "least-privilege",
            "test-data",
            "action-control",
            "simulation-disclosure",
            "auditability",
            "builder-path",
        )
        category_weights = (
            ("security-data-control", 20),
            ("safety-action-control", 15),
            ("functional-reasoning-fit", 15),
            ("data-tools-channels-integration", 15),
            ("reliability-observability-support", 12),
            ("engineering-alm-portability", 10),
            ("cost-capacity-effort", 8),
            ("availability-maturity-risk", 5),
        )
        delivery = model["delivery_assessment"]
        delivery["platform_gates"] = [
            {
                "product": "Microsoft Cowork",
                "gate": gate,
                "result": "pass",
                "scope": "Validated for the work-account Cowork PoC.",
                "evidence_refs": ["cowork-overview", "cowork-get-started"],
                "exception_owner": None,
                "blocker_for_poc": True,
            }
            for gate in gate_names
        ]
        delivery["candidate_scores"] = [
            {
                "product": "Microsoft Cowork",
                "categories": [
                    {
                        "category": category,
                        "weight": weight,
                        "score": 5 if category == "functional-reasoning-fit" else 4,
                        "evidence_refs": ["cowork-overview", "cowork-get-started"],
                        "confidence": "high",
                    }
                    for category, weight in category_weights
                ],
            }
        ]
        for index, capability in enumerate(delivery["capabilities"]):
            capability.update(
                {
                    "allowed_product": "Microsoft Cowork",
                    "harness": "Cowork",
                    "implementation_status": "configurable",
                    "coverage_factor": 1,
                    "demonstration_factor": 1,
                    "poc_treatment": "configure",
                    "implementation_method": (
                        "Configure Cowork built-in and custom skills with user-scoped Microsoft 365 access."
                    ),
                }
            )
            if index == 0:
                capability["work_type"] = "delegated-personal-work"

        components = model["components"]
        components["agents"][0]["name"] = "Personal Weekly Briefing Worker"
        components["agents"][0]["behaviors"] = [
            "Conversational",
            "Autonomous",
            "Human Handoff/oversight",
        ]
        components["platform_capabilities"] = [
            cls.item(
                "Cowork delegated task execution and built-in briefing skills",
                refs=["cowork-overview", "cowork-get-started"],
                basis="recommended",
                tier="No-code",
            )
        ]
        components["tools"] = [
            {
                **cls.item(
                    "Microsoft 365 Work IQ retrieval",
                    evidence=["REQ-AAAA000001"],
                    refs=["cowork-overview"],
                    tier="No-code",
                ),
                "integrability": "easily-integrable",
                "implementation": "Use Cowork organization search and Microsoft 365 access.",
                "creation_method": "Native action",
            },
            {
                **cls.item(
                    "External Task Management Plugin",
                    evidence=["REQ-BBBB000002"],
                    refs=["cowork-overview", "cowork-customize"],
                    tier="No-code",
                ),
                "integrability": "easily-integrable",
                "implementation": (
                    "Configure an approved Cowork plugin for user-scoped current task retrieval."
                ),
                "creation_method": "Plugin",
            },
        ]
        components["skills"] = [
            cls.item(
                "Leadership Briefing Method",
                evidence=["REQ-AAAA000001"],
                refs=["cowork-customize"],
                basis="recommended",
            )
        ]
        components["triggers"][0].update(
            {
                "name": "Weekly Cowork briefing schedule",
                "mechanism": "Cowork scheduled prompt",
                "agent_names": ["Personal Weekly Briefing Worker"],
                "reference_ids": ["cowork-overview", "cowork-get-started"],
            }
        )
        components["integration"] = [
            {
                **cls.item(
                    "Cowork Microsoft 365 service access",
                    refs=["cowork-overview"],
                    basis="recommended",
                    tier="No-code",
                ),
                "method": "Microsoft Graph",
                "integrability": "easily-integrable",
            }
        ]
        components["data"] = [
            cls.item(
                "Cowork task history and OneDrive output files",
                refs=["cowork-overview", "cowork-get-started"],
                basis="recommended",
                tier="No-code",
            )
        ]
        components["authentication"].update(
            {
                "platform": "Microsoft Entra ID",
                "tool": "Cowork user sign-in",
                "configuration": (
                    "Use the signed-in leader identity and Conditional Access."
                ),
                "reference_ids": ["entra-id", "cowork-get-started"],
            }
        )
        components["authorization"].update(
            {
                "platform": "Microsoft 365 source permissions",
                "tool": "Cowork delegated authorization",
                "configuration": (
                    "Use user-scoped Microsoft 365 permissions for every source and action."
                ),
                "reference_ids": ["entra-id", "cowork-get-started"],
            }
        )
        components["security_controls"] = [
            cls.item(
                "Cowork approval controls and Microsoft 365 data protection",
                refs=["cowork-overview", "microsoft-purview"],
                basis="mandatory-baseline",
                tier="No-code",
            )
        ]
        components["governance_controls"] = [
            cls.item(
                "Cowork plugin, skill, and user-access governance",
                refs=["cowork-overview", "cowork-customize"],
                basis="mandatory-baseline",
                tier="No-code",
            )
        ]
        components["alm"] = [
            cls.item(
                "Cowork skill and plugin configuration lifecycle",
                refs=["cowork-customize"],
                basis="mandatory-baseline",
                tier="No-code",
            )
        ]
        components["communication_channels"] = [
            cls.item(
                "Microsoft Cowork experience",
                refs=["cowork-overview", "cowork-get-started"],
                basis="recommended",
            )
        ]
        components["knowledge_sources"] = [
            cls.item(
                "User-authorized Microsoft 365 work context",
                evidence=["REQ-AAAA000001"],
                refs=["cowork-overview"],
            )
        ]
        model["flags"].update(
            {
                "requires_pro_code": False,
                "requires_custom_or_gateway": False,
                "uses_low_code": False,
                "autonomous_multistep": False,
                "uses_memory": False,
            }
        )

        topology = cls.solution_topology(model)
        delivery["capabilities"][1]["component_ids"] = [
            "policy-agent",
            "agent-automation",
            "tool-2",
            "skill-1",
        ]
        category_product = {
            "agent-platform": "Microsoft Cowork",
            "agent": "Microsoft Cowork",
            "channel": "Microsoft Cowork",
            "knowledge-source": "Microsoft Cowork Enterprise Search",
            "tool": "Microsoft Cowork built-in and custom skills",
            "automation": "Microsoft Cowork scheduled prompts",
            "integration": "Microsoft Graph and Microsoft Cowork connectors",
            "data-store": "Microsoft Cowork task history and OneDrive",
            "identity": "Microsoft Entra ID",
            "security": "Microsoft Cowork approval controls and Microsoft Purview",
            "governance": "Microsoft Cowork customization governance",
            "alm": "Microsoft Cowork skill and plugin configuration",
            "monitoring": "Microsoft Cowork task history",
        }
        category_refs = {
            "identity": ["entra-id", "cowork-get-started"],
            "security": ["cowork-overview", "microsoft-purview"],
            "governance": ["cowork-overview", "cowork-customize"],
            "alm": ["cowork-customize"],
            "monitoring": ["cowork-overview"],
            "data-store": ["cowork-overview"],
        }
        for item in topology["components"]:
            if item["category"] in category_product:
                item["product_service"] = category_product[item["category"]]
                item["hosting_runtime"] = category_product[item["category"]]
            item["reference_ids"] = category_refs.get(
                item["category"], ["cowork-overview", "cowork-get-started"]
            )
        for item in topology["relationships"]:
            item["reference_ids"] = ["cowork-overview", "cowork-get-started"]
            item["authentication"] = "Microsoft Entra ID user token"
        for item in topology["trust_boundaries"]:
            item["reference_ids"] = ["cowork-overview", "cowork-get-started"]
            item["name"] = "Cowork user and Microsoft 365 trust boundary"
        for item in topology["environments"]:
            item["promotion_via"] = "Cowork skill and plugin configuration validation"
            item["reference_ids"] = ["cowork-customize"]
        for item in topology["sequence_flows"]:
            item["reference_ids"] = ["cowork-overview", "cowork-get-started"]
        for item in topology["architecture_principles"]:
            item["reference_ids"] = ["cowork-overview", "cowork-customize"]
        model["solution_topology"] = topology
        return model

    def publish_model(
        self, prepared: dict, run: dict, model: dict, name: str
    ) -> dict:
        path = Path(run["run_directory"]) / f"{name}.json"
        path.write_text(json.dumps(model, indent=2), encoding="utf-8")
        return self.run_cli(
            "publish",
            "--run",
            prepared["run"],
            "--model",
            str(path),
        )

    @staticmethod
    def remove_topology_component(model: dict, component_id: str) -> None:
        topology = model["solution_topology"]
        topology["components"] = [
            item for item in topology["components"] if item["id"] != component_id
        ]
        topology["relationships"] = [
            item
            for item in topology["relationships"]
            if component_id not in {item["source_id"], item["target_id"]}
        ]
        topology["sequence_flows"] = [
            item
            for item in topology["sequence_flows"]
            if component_id not in {item["source_id"], item["target_id"]}
        ]
        for boundary in topology["trust_boundaries"]:
            boundary["component_ids"] = [
                item for item in boundary["component_ids"] if item != component_id
            ]
        for environment in topology["environments"]:
            environment["component_ids"] = [
                item for item in environment["component_ids"] if item != component_id
            ]
        for capability in model["delivery_assessment"]["capabilities"]:
            capability["component_ids"] = [
                item for item in capability["component_ids"] if item != component_id
            ]

    def test_prepare_consults_only_copilot_stage_and_defaults_channels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            refs = json.loads(Path(prepared["references"]).read_text(encoding="utf-8"))
            ids = {item["id"] for item in refs}
            self.assertNotIn("foundry-agent-service", ids)
            self.assertNotIn("agent-framework", ids)
            self.assertIn("cowork-overview", ids)
            self.assertIn("cowork-get-started", ids)
            self.assertIn("cowork-customize", ids)
            draft = json.loads(Path(prepared["model_draft"]).read_text(encoding="utf-8"))
            self.assertEqual(
                ["Microsoft Teams", "Microsoft 365 Copilot"],
                [item["name"] for item in draft["components"]["communication_channels"]],
            )
            self.assertEqual("Microsoft Entra ID", draft["components"]["authentication"]["platform"])
            self.assertTrue(draft["components"]["security_controls"])
            self.assertTrue(draft["components"]["governance_controls"])
            self.assertTrue(draft["components"]["alm"])
            self.assertEqual(
                (Path(directory) / "lisa-config.json").resolve(),
                Path(run["lisa_config_path"]),
            )

    def test_lisa_config_channel_overrides_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, _ = self.prepare(
                Path(directory),
                lisa_config={"channels": ["Web"]},
            )
            draft = json.loads(Path(prepared["model_draft"]).read_text(encoding="utf-8"))
            self.assertEqual(
                ["Web"],
                [item["name"] for item in draft["components"]["communication_channels"]],
            )
            self.assertEqual("configured", draft["components"]["communication_channels"][0]["selection_basis"])

    def test_delegated_personal_work_selects_cowork(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare_delegated(Path(directory))
            result = self.publish_model(
                prepared,
                run,
                self.cowork_model(run["run_id"]),
                "cowork-personal-worker",
            )
            self.assertEqual("Microsoft Cowork", result["agentic_platform"])
            self.assertEqual("Cowork", result["harness"])
            output = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
            self.assertEqual("full", output["platform_assessment"]["cowork_fit"])
            self.assertIn(
                "Microsoft Cowork",
                {item["product"] for item in output["platform_scores"]},
            )

    def test_delegated_personal_work_requires_cowork_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare_delegated(Path(directory))
            model = self.model(run["run_id"])
            model["delivery_assessment"]["capabilities"][0]["work_type"] = (
                "delegated-personal-work"
            )
            path = Path(run["run_directory"]) / "missing-cowork-assessment.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish", "--run", prepared["run"], "--model", str(path), expected=2
            )
            self.assertIn("requires a Microsoft Cowork fit assessment", result["error"])

    def test_viable_cowork_cannot_be_silently_replaced_by_copilot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare_delegated(Path(directory))
            model = self.model(run["run_id"])
            cowork = self.cowork_model(run["run_id"])
            model["platform_assessment"]["cowork_fit"] = "full"
            model["delivery_assessment"]["platform_gates"].extend(
                cowork["delivery_assessment"]["platform_gates"]
            )
            model["delivery_assessment"]["candidate_scores"].extend(
                cowork["delivery_assessment"]["candidate_scores"]
            )
            model["delivery_assessment"]["capabilities"][0]["work_type"] = (
                "delegated-personal-work"
            )
            model["components"]["skills"] = [
                self.item(
                    "Leadership Briefing Method",
                    evidence=["REQ-AAAA000001"],
                    refs=["cowork-customize"],
                    basis="recommended",
                )
            ]
            model["components"]["tools"].append(
                {
                    **self.item(
                        "External Task Management Plugin",
                        evidence=["REQ-BBBB000002"],
                        refs=["cowork-customize"],
                        tier="No-code",
                    ),
                    "integrability": "easily-integrable",
                    "implementation": "Configure the Cowork plugin.",
                    "creation_method": "Plugin",
                }
            )
            model["solution_topology"] = self.solution_topology(model)
            path = Path(run["run_directory"]) / "silent-copilot-substitution.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish", "--run", prepared["run"], "--model", str(path), expected=2
            )
            self.assertIn("must select Microsoft Cowork", result["error"])

    def test_reusable_delegated_method_requires_cowork_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare_delegated(Path(directory))
            model = self.cowork_model(run["run_id"])
            model["components"]["skills"] = []
            self.remove_topology_component(model, "skill-1")
            path = Path(run["run_directory"]) / "cowork-without-skill.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish", "--run", prepared["run"], "--model", str(path), expected=2
            )
            self.assertIn("requires an explicit Cowork skill", result["error"])

    def test_live_external_access_requires_cowork_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare_delegated(Path(directory))
            model = self.cowork_model(run["run_id"])
            model["components"]["tools"] = [model["components"]["tools"][0]]
            self.remove_topology_component(model, "tool-2")
            path = Path(run["run_directory"]) / "cowork-without-plugin.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish", "--run", prepared["run"], "--model", str(path), expected=2
            )
            self.assertIn("requires an explicit Cowork plugin", result["error"])

    def test_low_and_medium_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            low = self.publish_model(
                prepared,
                run,
                self.model(run["run_id"], tools=[self.easy_tool("Search")]),
                "low",
            )
            self.assertEqual("Low", low["complexity"])

        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            medium = self.publish_model(
                prepared,
                run,
                self.model(
                    run["run_id"],
                    tools=[self.easy_tool("Search"), self.easy_tool("Notify")],
                ),
                "medium",
            )
            self.assertEqual("Medium", medium["complexity"])

    def test_custom_connector_is_high_but_stays_copilot_platform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            custom = {
                **self.item(
                    "Procurement custom connector",
                    evidence=["REQ-AAAA000001"],
                    refs=["copilot-studio-tools"],
                    tier="Low-code",
                ),
                "integrability": "custom",
                "implementation": "Create a Power Platform custom connector.",
                "creation_method": "Custom connector",
            }
            result = self.publish_model(
                prepared,
                run,
                self.model(
                    run["run_id"],
                    tools=[custom],
                    code_tier="Low-code",
                    uses_low_code=True,
                    requires_custom=True,
                ),
                "custom",
            )
            self.assertEqual("High", result["complexity"])
            self.assertEqual("Copilot Studio", result["agentic_platform"])

    def test_autonomous_agent_requires_explicit_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            model = self.model(run["run_id"], triggers=[])
            path = Path(run["run_directory"]) / "missing-trigger.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish",
                "--run",
                prepared["run"],
                "--model",
                str(path),
                expected=2,
            )
            self.assertIn("require at least one explicit invocation trigger", result["error"])

    def test_tool_requires_explicit_creation_method(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            tool = self.easy_tool("Search")
            del tool["creation_method"]
            model = self.model(run["run_id"], tools=[tool])
            path = Path(run["run_directory"]) / "missing-method.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish",
                "--run",
                prepared["run"],
                "--model",
                str(path),
                expected=2,
            )
            self.assertIn("schema error", result["error"])

    def test_requirement_assessment_requires_documentation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            model = self.model(run["run_id"])
            model["requirement_assessments"][0]["reference_ids"] = []
            path = Path(run["run_directory"]) / "ungrounded-assessment.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish",
                "--run",
                prepared["run"],
                "--model",
                str(path),
                expected=2,
            )
            self.assertIn("schema error", result["error"])

    def test_foundry_and_agent_framework_research_expands_sequentially(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            copilot_assessment = {
                "run_id": run["run_id"],
                "stage": "copilot",
                "fit": "partial",
                "unmet_requirements": [
                    {
                        "name": "Advanced orchestration gap",
                        "evidence_ids": ["REQ-AAAA000001"],
                        "reason": "Copilot Studio capability is insufficient."
                    }
                ],
                "summary": "Foundry research is required."
            }
            copilot_path = Path(run["run_directory"]) / "copilot-assessment.json"
            copilot_path.write_text(
                json.dumps(copilot_assessment, indent=2), encoding="utf-8"
            )
            foundry = self.run_cli(
                "expand-research",
                "--run",
                prepared["run"],
                "--stage",
                "foundry",
                "--assessment",
                str(copilot_path),
            )
            foundry_ids = {
                item["id"]
                for item in json.loads(Path(foundry["references"]).read_text(encoding="utf-8"))
            }
            self.assertIn("foundry-agent-service", foundry_ids)
            self.assertNotIn("agent-framework", foundry_ids)
            foundry_assessment = {
                "run_id": run["run_id"],
                "stage": "foundry",
                "fit": "partial",
                "unmet_requirements": [
                    {
                        "name": "Multi-agent orchestration gap",
                        "evidence_ids": ["REQ-AAAA000001"],
                        "reason": "Agent Framework research is required."
                    }
                ],
                "summary": "Agent Framework research is required."
            }
            foundry_path = Path(run["run_directory"]) / "foundry-assessment.json"
            foundry_path.write_text(
                json.dumps(foundry_assessment, indent=2), encoding="utf-8"
            )
            framework = self.run_cli(
                "expand-research",
                "--run",
                prepared["run"],
                "--stage",
                "agent-framework",
                "--assessment",
                str(foundry_path),
            )
            framework_ids = {
                item["id"]
                for item in json.loads(Path(framework["references"]).read_text(encoding="utf-8"))
            }
            self.assertIn("agent-framework", framework_ids)

    def test_copilot_gap_requires_research_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            model = self.model(run["run_id"])
            model["platform_assessment"]["copilot_studio_fit"] = "partial"
            model["platform_assessment"]["unmet_requirements"] = [
                self.item(
                    "Unmet platform capability",
                    evidence=["REQ-AAAA000001"],
                )
            ]
            path = Path(run["run_directory"]) / "premature.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish",
                "--run",
                prepared["run"],
                "--model",
                str(path),
                expected=2,
            )
            self.assertIn("selected Stage 1 platform must have full fit", result["error"])

    def test_topic_and_gap_component_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            model = self.model(run["run_id"])
            model["components"]["agents"][0]["name"] = "Classic Topic router"
            path = Path(run["run_directory"]) / "topic.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish",
                "--run",
                prepared["run"],
                "--model",
                str(path),
                expected=2,
            )
            self.assertIn("Topics are prohibited", result["error"])

        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            model = self.model(run["run_id"])
            model["components"]["agents"][0]["evidence_ids"] = ["GAP-CCCC000003"]
            path = Path(run["run_directory"]) / "gap.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish",
                "--run",
                prepared["run"],
                "--model",
                str(path),
                expected=2,
            )
            self.assertIn("non-scope", result["error"])

    def test_topology_rejects_generic_product_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            model = self.model(run["run_id"])
            data_store = next(
                item
                for item in model["solution_topology"]["components"]
                if item["category"] == "data-store"
            )
            data_store["product_service"] = "Storage"
            path = Path(run["run_directory"]) / "generic-topology.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish",
                "--run",
                prepared["run"],
                "--model",
                str(path),
                expected=2,
            )
            self.assertIn("exact product/service names", result["error"])

    def test_topology_requires_complete_inventory_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            model = self.model(run["run_id"])
            tool = next(
                item
                for item in model["solution_topology"]["components"]
                if item["category"] == "tool"
            )
            tool["inventory_names"] = []
            path = Path(run["run_directory"]) / "missing-mapping.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish",
                "--run",
                prepared["run"],
                "--model",
                str(path),
                expected=2,
            )
            self.assertIn("Every classified component must map", result["error"])

    def test_published_markdown_contains_design_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            result = self.publish_model(
                prepared,
                run,
                self.model(run["run_id"]),
                "architecture-contract",
            )
            markdown = Path(result["markdown"]).read_text(encoding="utf-8")
            output = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
            self.assertIn(
                "## Architecture and Sequence Design Contract",
                markdown,
            )
            self.assertIn("Microsoft Entra ID", markdown)
            self.assertIn("Microsoft Dataverse", markdown)
            self.assertIn("Microsoft Copilot Studio analytics", markdown)
            self.assertEqual(
                "Microsoft Dataverse",
                next(
                    item
                    for item in output["solution_topology"]["components"]
                    if item["category"] == "data-store"
                )["product_service"],
            )

    def test_delivery_coverage_is_derived_from_weighted_capabilities(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            model = self.model(run["run_id"])
            capability = model["delivery_assessment"]["capabilities"][1]
            capability.update(
                {
                    "implementation_status": "demonstrable-only",
                    "coverage_factor": 0,
                    "demonstration_factor": 0.25,
                    "poc_treatment": "simulate",
                }
            )
            capability["build_contract"]["simulation_disclosure"] = (
                "This scheduled result is simulated and was not executed externally."
            )
            result = self.publish_model(prepared, run, model, "weighted-coverage")
            output = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
            self.assertEqual(62.5, output["coverage"]["native_build_percent"])
            self.assertEqual(71.88, output["coverage"]["poc_demonstration_percent"])
            self.assertEqual(37.5, output["coverage"]["unsupported_percent"])
            self.assertEqual(
                80,
                output["platform_scores"][0]["weighted_score"],
            )

    def test_simulation_requires_disclosure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            model = self.model(run["run_id"])
            capability = model["delivery_assessment"]["capabilities"][1]
            capability.update(
                {
                    "implementation_status": "demonstrable-only",
                    "coverage_factor": 0,
                    "demonstration_factor": 0.25,
                    "poc_treatment": "simulate",
                }
            )
            path = Path(run["run_directory"]) / "simulation-without-disclosure.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish", "--run", prepared["run"], "--model", str(path), expected=2
            )
            self.assertIn("requires an explicit user-visible disclosure", result["error"])

    def test_high_impact_capability_requires_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            model = self.model(run["run_id"])
            capability = model["delivery_assessment"]["capabilities"][1]
            capability["action_impact"] = "high-impact-write"
            path = Path(run["run_directory"]) / "high-impact-without-approval.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish", "--run", prepared["run"], "--model", str(path), expected=2
            )
            self.assertIn("requires explicit approval", result["error"])

    def test_failed_poc_gate_rejects_buildable_product(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            prepared, run = self.prepare(Path(directory))
            model = self.model(run["run_id"])
            availability = next(
                item
                for item in model["delivery_assessment"]["platform_gates"]
                if item["gate"] == "product-availability"
            )
            availability["result"] = "fail"
            path = Path(run["run_directory"]) / "failed-product-gate.json"
            path.write_text(json.dumps(model, indent=2), encoding="utf-8")
            result = self.run_cli(
                "publish", "--run", prepared["run"], "--model", str(path), expected=2
            )
            self.assertIn("failed blocking PoC gates", result["error"])

    def test_cache_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            prepared, run = self.prepare(temporary)
            self.publish_model(
                prepared,
                run,
                self.model(run["run_id"], tools=[self.easy_tool("Search")]),
                "cache-model",
            )
            second, _ = self.prepare(
                temporary,
                local_time="2026-08-13T12:31:00+05:30",
            )
            self.assertTrue(second["classification_cache_hit"])
            result = self.run_cli(
                "publish",
                "--run",
                second["run"],
                "--model",
                second["reused_model"],
            )
            self.assertTrue(result["classification_cache_hit"])
            self.assertLess(result["duration_seconds"], 30)


if __name__ == "__main__":
    unittest.main()
