from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from generate_manifest import publish  # noqa: E402
from validate_artifacts import ArtifactError, load_object, validate  # noqa: E402

RUN_IDS = {
    "build": "BLD-20260818-120000-ABCDEF12",
    "evaluation": "EVAL-20260818-130000-ABCDEF12",
    "optimization": "OPT-20260818-140000-ABCDEF12",
}
AGENT = {
    "name": "Fixture Agent",
    "agentId": "fixture-agent-id",
    "schemaName": "fixture_Agent",
    "agenticPlatform": "Microsoft Copilot Studio",
    "harness": "Standard",
    "environmentId": "fixture-environment-id",
    "environmentUrl": "https://example.crm.dynamics.com/",
}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ArtifactContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_object(SKILL_ROOT / "resources" / "artifact-contract.json")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / self.contract["rootFolder"]
        self.root.mkdir()
        getattr(self, f"create_{self.contract['stage']}")()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create_build(self) -> None:
        run_id = RUN_IDS["build"]
        (self.root / "packages").mkdir()
        (self.root / "evidence").mkdir()
        instructions = self.root / "agent-instructions.md"
        instructions.write_text("Use approved sources only.\n", encoding="utf-8")
        package = self.root / "packages" / "fixture-agent.zip"
        package.write_bytes(b"fixture package")
        package_record = {
            "relativePath": "packages/fixture-agent.zip",
            "sha256": digest(package),
            "bytes": package.stat().st_size,
        }
        agent_record = {
            "name": AGENT["name"],
            "agentId": AGENT["agentId"],
            "schemaName": AGENT["schemaName"],
            "agenticPlatform": AGENT["agenticPlatform"],
            "harness": AGENT["harness"],
            "role": "Fixture capability",
            "environmentId": AGENT["environmentId"],
            "state": "Published",
            "projectRelativePath": None,
            "instructionsSha256": digest(instructions),
            "components": [
                {"name": "Agent", "type": "agent", "status": "present"}
            ],
        }
        classification = self.root.parent / "output" / "classification" / "complexity-classification_20260818_120000.json"
        write_json(
            classification,
            {
                "coverage": {
                    "native_build_percent": 100,
                    "poc_demonstration_percent": 100,
                },
                "delivery_assessment": {"capabilities": [{"id": "CAP-001"}]},
                "solution_topology": {"components": [{"id": "fixture-agent"}]},
            },
        )
        write_json(
            self.root / "agent-solution-manifest.json",
            {
                "schemaVersion": "1.0",
                "buildMode": "copilot-studio-package",
                "solutionType": "single-agent",
                "primaryAgentId": AGENT["agentId"],
                "environmentId": AGENT["environmentId"],
                "solutionUniqueName": "FixtureAgentSolution",
                "package": package_record,
                "deploymentOrder": [AGENT["agentId"]],
                "agents": [
                    {
                        "name": AGENT["name"],
                        "agentId": AGENT["agentId"],
                        "schemaName": AGENT["schemaName"],
                        "agenticPlatform": AGENT["agenticPlatform"],
                        "harness": AGENT["harness"],
                        "role": "Fixture capability",
                        "state": "Published",
                        "projectRelativePath": None,
                        "instructionsSha256": digest(instructions),
                        "components": [
                            {
                                "name": "Agent",
                                "type": "agent",
                                "status": "present",
                            }
                        ],
                    }
                ],
                "relationships": [],
            },
        )
        write_json(
            self.root / "agent-build-handoff.json",
            {
                "schemaVersion": "1.0",
                "runId": run_id,
                "generatedAt": "2026-08-18T12:00:00Z",
                "buildMode": "copilot-studio-package",
                "agent": {
                    **AGENT,
                    "recommendedTestSurface": "overview-test-pane",
                    "state": "Published",
                },
                "agents": [agent_record],
                "inputs": {
                    "configRelativePath": "lisa-config.json",
                    "classificationRelativePath": "output/classification/complexity-classification_20260818_120000.json",
                    "designPointerRelativePath": "output/design/current-design.json",
                    "outputRelativePath": "output/build",
                    "knowledgeSources": [],
                },
                "instructions": {
                    "version": "1.0.0",
                    "sha256": digest(instructions),
                    "relativePath": "agent-instructions.md",
                },
                "componentInventory": [
                    {"name": "Agent", "type": "agent", "status": "present"}
                ],
                "classificationPlan": {
                    "nativeBuildPercent": 100,
                    "pocDemonstrationPercent": 100,
                    "capabilityCount": 1,
                },
                "componentDispositions": [
                    {
                        "componentId": "fixture-agent",
                        "capabilityIds": ["CAP-001"],
                        "plannedDisposition": "configure",
                        "actualDisposition": "configured",
                        "expectedImplementation": "Configure the Copilot Studio agent.",
                        "actualImplementation": "Configured and published the Copilot Studio agent.",
                        "verification": "Pulled the live agent and verified its persisted configuration.",
                        "gapIds": [],
                    }
                ],
                "actualCoverage": {
                    "plannedNativePercent": 100,
                    "actualNativePercent": 100,
                    "plannedPocPercent": 100,
                    "actualPocPercent": 100,
                    "varianceReasons": [],
                },
                "simulationRegister": [],
                "manualDemoSteps": [],
                "deferredComponents": [],
                "productionReadinessGaps": ["Complete production capacity and support validation."],
                "demoScript": ["Open the published agent and submit the approved fixture request."],
                "requiredCustomerInputs": [],
                "constructionVerification": {
                    "expected": 1,
                    "present": 1,
                    "mismatched": [],
                    "missing": [],
                },
                "qualityTargets": {},
                "implementedControls": [],
                "recommendations": [],
                "knownBuildRisks": [],
                "automationToolchain": {
                    "pacVersion": "2.12.2",
                    "pacLatestVersion": "2.12.2",
                    "pacLatestSource": "dotnet tool update --global Microsoft.PowerApps.CLI.Tool",
                    "atkVersion": None,
                    "verifiedAt": "2026-08-18T11:55:00Z",
                },
                "automationLedger": [
                    {
                        "componentId": "fixture-agent",
                        "operation": "create-agent",
                        "platform": "Microsoft Copilot Studio",
                        "method": "pac-cli",
                        "tool": "pac copilot init --environment",
                        "evidence": "Agent fixture-agent-id created and cloned.",
                        "programmaticAttempts": [],
                        "fallbackJustification": None,
                        "reconciliation": None,
                    }
                ],
                "artifacts": {
                    "packages": [package_record],
                    "projectRelativePath": None,
                    "solutionManifestRelativePath": "agent-solution-manifest.json",
                    "liveStateRelativePath": "agent-live-state.json",
                    "evidence": [],
                },
            },
        )
        write_json(
            self.root / "agent-live-state.json",
            {
                "schemaVersion": "1.0",
                "runId": run_id,
                "capturedAt": "2026-08-18T12:00:00Z",
                "buildMode": "copilot-studio-package",
                "agent": {**AGENT, "state": "Published"},
                "agents": [
                    {
                        "name": AGENT["name"],
                        "agentId": AGENT["agentId"],
                        "schemaName": AGENT["schemaName"],
                        "agenticPlatform": AGENT["agenticPlatform"],
                        "harness": AGENT["harness"],
                        "environmentId": AGENT["environmentId"],
                        "state": "Published",
                        "instructionsSha256": digest(instructions),
                        "components": [
                            {
                                "name": "Agent",
                                "type": "agent",
                                "status": "present",
                            }
                        ],
                    }
                ],
                "instructionsSha256": digest(instructions),
                "components": [
                    {"name": "Agent", "type": "agent", "status": "present"}
                ],
                "capabilities": {},
                "packages": [package_record],
            },
        )
        (self.root / "agent-build-report.md").write_text("# Build\n", encoding="utf-8")

    def convert_build_to_cowork(self) -> None:
        package = self.root / "packages" / "fixture-agent.zip"
        package.unlink()

        solution_path = self.root / "agent-solution-manifest.json"
        solution = load_object(solution_path)
        solution["buildMode"] = "cowork-configuration"
        solution["package"] = None
        for agent in solution["agents"]:
            agent["schemaName"] = None
            agent["agenticPlatform"] = "Microsoft Cowork"
            agent["harness"] = None
        write_json(solution_path, solution)

        handoff_path = self.root / "agent-build-handoff.json"
        handoff = load_object(handoff_path)
        handoff["buildMode"] = "cowork-configuration"
        handoff["agent"].update(
            {
                "schemaName": None,
                "agenticPlatform": "Microsoft Cowork",
                "harness": None,
                "environmentUrl": None,
            }
        )
        for agent in handoff["agents"]:
            agent["schemaName"] = None
            agent["agenticPlatform"] = "Microsoft Cowork"
            agent["harness"] = None
        handoff["artifacts"]["packages"] = []
        handoff["automationToolchain"].update(
            {"pacVersion": None, "pacLatestVersion": None, "pacLatestSource": None}
        )
        handoff["automationLedger"] = [
            {
                "componentId": "fixture-agent",
                "operation": "set-custom-instructions",
                "platform": "Microsoft Cowork",
                "method": "browser",
                "tool": "Cowork Customize > Preferences",
                "evidence": "evidence/cowork-preferences.png",
                "programmaticAttempts": [],
                "fallbackJustification": "Cowork preferences have no documented programmatic route.",
                "reconciliation": None,
            }
        ]
        write_json(handoff_path, handoff)

        live_path = self.root / "agent-live-state.json"
        live = load_object(live_path)
        live["buildMode"] = "cowork-configuration"
        live["agent"].update(
            {
                "schemaName": None,
                "agenticPlatform": "Microsoft Cowork",
                "harness": None,
            }
        )
        for agent in live["agents"]:
            agent["schemaName"] = None
            agent["agenticPlatform"] = "Microsoft Cowork"
            agent["harness"] = None
        live["packages"] = []
        write_json(live_path, live)

    def create_evaluation(self) -> None:
        run_id = RUN_IDS["evaluation"]
        (self.root / "evidence").mkdir()
        (self.root / "evidence" / "EVAL-001-attempt-01.png").write_bytes(b"png")
        test_case = {
            "id": "EVAL-001",
            "scenario": "Grounded answer",
            "sourceType": "knowledge-source",
            "sourceReferences": [{"source": "policy.pdf", "locator": "page 1"}],
            "userPrompt": "What is the policy?",
            "expectedResponse": "Use the approved policy.",
            "expectedBehavior": "Answer from policy.pdf.",
            "responseAssertions": ["Uses the approved policy"],
            "expectedKnowledgeSources": ["policy.pdf"],
            "requiredTools": [],
            "prohibitedBehavior": [],
            "evaluationTypes": ["LLM_AS_JUDGE", "GROUNDEDNESS"],
            "severity": "critical",
            "passCriteria": "The approved policy is used.",
            "failCriteria": "The answer is unsupported.",
        }
        write_json(
            self.root / "evaluation-dataset.json",
            {
                "schemaVersion": "1.0",
                "generatedAt": "2026-08-18T13:00:00Z",
                "testSetId": "fixture-v1",
                "sources": [
                    {
                        "name": "policy.pdf",
                        "type": "knowledge-source",
                        "location": "C:\\input\\policy.pdf",
                        "authority": "authoritative",
                    }
                ],
                "testCases": [test_case],
            },
        )
        (self.root / "evaluation-dataset.csv").write_text(
            "id,userPrompt\nEVAL-001,What is the policy?\n", encoding="utf-8"
        )
        write_json(
            self.root / "evaluation-rubric.json",
            {
                "schemaVersion": "1.0",
                "scale": {str(i): f"score {i}" for i in range(5)},
                "gates": {
                    key: {"criteria": ["criterion"], "passThreshold": 3}
                    for key in [
                        "LLM_AS_JUDGE",
                        "TOOL_USE",
                        "GROUNDEDNESS",
                        "REGRESSION",
                    ]
                },
                "overall": {
                    "minimumAverage": 3,
                    "criticalTestsMustPass": True,
                    "blockedCriticalTestsFail": True,
                    "notRunCriticalTestsFail": True,
                    "automaticFailures": [],
                },
            },
        )
        result = {
            "testCaseId": "EVAL-001",
            "scenario": "Grounded answer",
            "userPrompt": "What is the policy?",
            "expectedResponse": "Use the approved policy.",
            "actualResponse": "Use the approved policy.",
            "status": "PASS",
            "durationMs": 100,
            "attempts": 1,
            "playwrightObservations": {
                "conversationReset": True,
                "responseCompleted": True,
                "surfaceUsed": "overview-test-pane",
                "citationsObserved": ["policy.pdf"],
                "toolActivityObserved": [],
                "uiErrors": [],
                "sideEffectsObserved": [],
                "evidence": ["evidence/EVAL-001-attempt-01.png"],
                "notes": "Complete response.",
            },
            "gateResults": {},
            "assertionResults": [],
            "failureReasons": [],
            "blocker": None,
        }
        write_json(
            self.root / "evaluation-observations.json",
            {
                "schemaVersion": "1.1",
                "runId": run_id,
                "testSetId": "fixture-v1",
                "agent": {
                    "name": AGENT["name"],
                    "agentId": AGENT["agentId"],
                    "harness": AGENT["harness"],
                    "surface": "overview-test-pane",
                    "environmentId": AGENT["environmentId"],
                },
                "startedAt": "2026-08-18T13:00:00Z",
                "completedAt": "2026-08-18T13:01:00Z",
                "summary": {
                    "total": 1,
                    "passed": 1,
                    "failed": 0,
                    "blocked": 0,
                    "notRun": 0,
                },
                "results": [result],
                "gateSummary": {},
                "optimizerHandoff": {
                    "evaluationDecision": "PASS",
                    "eligibleForOptimization": False,
                    "findings": [],
                },
            },
        )
        write_json(
            self.root / "regression-baseline.json",
            {
                "schemaVersion": "1.0",
                "baselineId": "fixture-baseline",
                "approvalStatus": "candidate-unapproved",
                "createdAt": "2026-08-18T13:01:00Z",
                "sourceRunId": run_id,
                "agent": {
                    "name": AGENT["name"],
                    "agentId": AGENT["agentId"],
                    "harness": AGENT["harness"],
                    "instructionSha256": "a" * 64,
                },
                "summary": {"passed": 1, "failed": 0},
                "cases": [
                    {"testCaseId": "EVAL-001", "status": "PASS", "scores": {}}
                ],
            },
        )
        (self.root / "evaluation-run-report.md").write_text(
            "# Evaluation\n", encoding="utf-8"
        )
        (self.root / "deployment-gate-summary.md").write_text(
            "# Gate\n\nPASS\n", encoding="utf-8"
        )

    def create_optimization(self) -> None:
        run_id = RUN_IDS["optimization"]
        round_id = "round-001"
        before = self.root / "rounds" / round_id / "snapshots" / "before"
        after = self.root / "rounds" / round_id / "snapshots" / "after"
        before.mkdir(parents=True)
        after.mkdir(parents=True)
        before_package = before / "fixture-agent.zip"
        after_package = after / "fixture-agent.zip"
        before_package.write_bytes(b"before")
        after_package.write_bytes(b"after")
        round_value = {
            "roundId": round_id,
            "roundNumber": 1,
            "status": "accepted",
            "findingIds": ["OPT-FINDING-001"],
            "proposedChanges": [
                {
                    "changeId": "CHG-001",
                    "surface": "instructions",
                    "action": "update",
                    "current": "before",
                    "proposed": "after",
                    "expectedMechanism": "Clarify grounding.",
                    "affectedComponents": ["instructions"],
                }
            ],
            "risk": "Instruction regression.",
            "rollback": "Restore the before snapshot.",
            "requiredRetestScope": ["EVAL-001"],
        }
        write_json(
            self.root / "optimization-plan.json",
            {
                "schemaVersion": "1.0",
                "runId": run_id,
                "generatedAt": "2026-08-18T14:00:00Z",
                "agent": AGENT,
                "sourceEvaluation": {
                    "runId": RUN_IDS["evaluation"],
                    "decision": "FAIL",
                    "observationsRelativePath": "evaluation/evaluation-observations.json",
                    "deploymentGateRelativePath": "evaluation/deployment-gate-summary.md",
                },
                "policy": {},
                "rounds": [round_value],
                "deferredFindings": [],
            },
        )
        write_json(
            self.root / "optimization-change-log.json",
            {
                "schemaVersion": "1.0",
                "runId": run_id,
                "generatedAt": "2026-08-18T14:02:00Z",
                "rounds": [
                    {
                        "roundId": round_id,
                        "roundNumber": 1,
                        "confirmedAt": "2026-08-18T14:00:30Z",
                        "findingIds": ["OPT-FINDING-001"],
                        "changes": [
                            {
                                "changeId": "CHG-001",
                                "surface": "instructions",
                                "action": "updated",
                                "before": "before",
                                "after": "after",
                            }
                        ],
                        "constructionVerification": {"persisted": True},
                        "requiredRetestScope": ["EVAL-001"],
                        "evaluatorRunId": RUN_IDS["evaluation"],
                        "outcome": "accepted",
                    }
                ],
            },
        )
        for state, snapshot, package in [
            ("before", before, before_package),
            ("after", after, after_package),
        ]:
            write_json(
                self.root
                / "rounds"
                / round_id
                / f"{state}-state-manifest.json",
                {
                    "schemaVersion": "1.0",
                    "runId": run_id,
                    "roundId": round_id,
                    "state": state,
                    "capturedAt": "2026-08-18T14:01:00Z",
                    "agentId": AGENT["agentId"],
                    "harness": AGENT["harness"],
                    "environmentId": AGENT["environmentId"],
                    "instructionSha256": "a" * 64,
                    "settingsSha256": "b" * 64,
                    "snapshotRelativePath": snapshot.relative_to(self.root).as_posix(),
                    "components": [],
                    "package": {
                        "relativePath": package.relative_to(self.root).as_posix(),
                        "sha256": digest(package),
                        "bytes": package.stat().st_size,
                    },
                },
            )
        (self.root / "rounds" / round_id / "round-report.md").write_text(
            "# Round 1\n", encoding="utf-8"
        )
        (self.root / "optimization-run-report.md").write_text(
            "# Optimization\n", encoding="utf-8"
        )

    def publish_fixture(self) -> None:
        stage = self.contract["stage"]
        status = {"build": "complete", "evaluation": "pass", "optimization": "complete"}[
            stage
        ]
        source_runs = [RUN_IDS["build"]] if stage == "evaluation" else []
        publish(self.root, status, f"Valid {stage} fixture.", source_runs)

    def test_valid_fixture(self) -> None:
        self.publish_fixture()
        self.assertEqual(validate(self.root)["status"], "passed")

    def test_valid_cowork_configuration_fixture(self) -> None:
        self.convert_build_to_cowork()
        self.publish_fixture()
        self.assertEqual(validate(self.root)["status"], "passed")

    def test_cowork_rejects_copilot_studio_harness(self) -> None:
        self.convert_build_to_cowork()
        handoff_path = self.root / "agent-build-handoff.json"
        handoff = load_object(handoff_path)
        handoff["agent"]["harness"] = "Standard"
        write_json(handoff_path, handoff)
        with self.assertRaises(ArtifactError):
            self.publish_fixture()

    def test_copilot_studio_requires_harness(self) -> None:
        handoff_path = self.root / "agent-build-handoff.json"
        handoff = load_object(handoff_path)
        handoff["agent"]["harness"] = None
        write_json(handoff_path, handoff)
        with self.assertRaises(ArtifactError):
            self.publish_fixture()

    def test_cowork_rejects_solution_package(self) -> None:
        self.convert_build_to_cowork()
        handoff_path = self.root / "agent-build-handoff.json"
        handoff = load_object(handoff_path)
        handoff["artifacts"]["packages"] = [
            {
                "relativePath": "packages/fixture-agent.zip",
                "sha256": "0" * 64,
                "bytes": 1,
            }
        ]
        write_json(handoff_path, handoff)
        with self.assertRaises(ArtifactError):
            self.publish_fixture()

    def test_hash_tampering_is_rejected(self) -> None:
        self.publish_fixture()
        report = next(self.root.glob("*-run-report.md"), None)
        if report is None:
            report = self.root / "agent-build-report.md"
        report.write_text("tampered\n", encoding="utf-8")
        with self.assertRaises(ArtifactError):
            validate(self.root)

    def test_unlisted_artifact_is_rejected(self) -> None:
        self.publish_fixture()
        (self.root / "unexpected.txt").write_text("extra\n", encoding="utf-8")
        with self.assertRaises(ArtifactError):
            validate(self.root)

    def test_unsafe_manifest_path_is_rejected(self) -> None:
        self.publish_fixture()
        manifest_path = self.root / self.contract["manifest"]
        manifest = load_object(manifest_path)
        manifest["artifacts"][0]["relativePath"] = "../escape.json"
        write_json(manifest_path, manifest)
        with self.assertRaises(ArtifactError):
            validate(self.root)

    def test_invalid_stage_name_is_rejected(self) -> None:
        if self.contract["stage"] == "build":
            (self.root / "packages" / "Bad Name.zip").write_bytes(b"bad")
        elif self.contract["stage"] == "evaluation":
            (self.root / "evidence" / "EVAL-001.png").write_bytes(b"bad")
        else:
            plan = load_object(self.root / "optimization-plan.json")
            plan["rounds"][0]["roundId"] = "round-002"
            write_json(self.root / "optimization-plan.json", plan)
        with self.assertRaises(ArtifactError):
            self.publish_fixture()

    def test_missing_classifier_component_disposition_is_rejected(self) -> None:
        if self.contract["stage"] != "build":
            self.skipTest("Builder-only reconciliation test")
        handoff_path = self.root / "agent-build-handoff.json"
        handoff = load_object(handoff_path)
        handoff["componentDispositions"] = []
        write_json(handoff_path, handoff)
        with self.assertRaises(ArtifactError):
            self.publish_fixture()

    def test_planned_coverage_drift_is_rejected(self) -> None:
        if self.contract["stage"] != "build":
            self.skipTest("Builder-only reconciliation test")
        handoff_path = self.root / "agent-build-handoff.json"
        handoff = load_object(handoff_path)
        handoff["classificationPlan"]["nativeBuildPercent"] = 99
        write_json(handoff_path, handoff)
        with self.assertRaises(ArtifactError):
            self.publish_fixture()

    def add_foundry_component(self, disposition: str, contract: bool) -> None:
        classification_path = (
            self.root.parent / "output" / "classification"
            / "complexity-classification_20260818_120000.json"
        )
        classification = load_object(classification_path)
        classification["solution_topology"]["components"].append({
            "id": "claims-reasoning-service",
            "product_service": "Microsoft Foundry Agent Service",
            "hosting_runtime": "Azure subscription",
        })
        write_json(classification_path, classification)
        handoff_path = self.root / "agent-build-handoff.json"
        handoff = load_object(handoff_path)
        handoff["componentDispositions"].append({
            "componentId": "claims-reasoning-service",
            "capabilityIds": ["CAP-001"],
            "plannedDisposition": "defer",
            "actualDisposition": disposition,
            "expectedImplementation": "Foundry agent on the LISA roadmap.",
            "actualImplementation": "Recorded as a future-platform integration.",
            "verification": "Integration contract reviewed.",
            "gapIds": [],
        })
        handoff["deferredComponents"] = ["claims-reasoning-service"]
        if contract:
            handoff["futurePlatformContracts"] = [{
                "componentId": "claims-reasoning-service",
                "targetPlatform": "Microsoft Foundry",
                "responsibility": "Score complex claims.",
                "interface": {
                    "kind": "connected-agent",
                    "inputs": "claimId: string",
                    "outputs": "score: number; rationale: string",
                },
                "identity": "Microsoft Entra ID on-behalf-of",
                "dataBoundary": "Claims data stays in the tenant.",
                "owner": "Claims platform team",
                "consumerComponentId": "fixture-agent",
            }]
        write_json(handoff_path, handoff)

    def test_foundry_component_with_contract_is_accepted(self) -> None:
        if self.contract["stage"] != "build":
            self.skipTest("Builder-only reconciliation test")
        self.add_foundry_component("deferred", contract=True)
        self.publish_fixture()
        self.assertEqual(validate(self.root)["status"], "passed")

    def test_foundry_component_without_contract_is_rejected(self) -> None:
        if self.contract["stage"] != "build":
            self.skipTest("Builder-only reconciliation test")
        self.add_foundry_component("deferred", contract=False)
        with self.assertRaisesRegex(ArtifactError, "futurePlatformContracts"):
            self.publish_fixture()

    def test_built_foundry_component_is_rejected(self) -> None:
        if self.contract["stage"] != "build":
            self.skipTest("Builder-only reconciliation test")
        self.add_foundry_component("built", contract=True)
        with self.assertRaisesRegex(ArtifactError, "cannot be built"):
            self.publish_fixture()

    def update_handoff(self, change) -> None:
        handoff_path = self.root / "agent-build-handoff.json"
        handoff = load_object(handoff_path)
        change(handoff)
        write_json(handoff_path, handoff)

    def browser_entry(self, **overrides) -> dict:
        entry = {
            "componentId": "fixture-agent",
            "operation": "set-agent-description",
            "platform": "Microsoft Copilot Studio",
            "method": "browser",
            "tool": "Copilot Studio agent Details page",
            "evidence": "evidence/agent-description.png",
            "programmaticAttempts": [
                {
                    "method": "pac-cli",
                    "tool": "pac copilot pull",
                    "outcome": "unsupported",
                    "evidence": "Pulled agent.mcs.yml exposes no description field.",
                }
            ],
            "fallbackJustification": "No PAC or documented API field persists the description.",
            "reconciliation": "pac copilot pull confirmed the persisted description.",
        }
        entry.update(overrides)
        return entry

    def test_browser_step_after_pac_attempt_is_accepted(self) -> None:
        self.update_handoff(lambda h: h["automationLedger"].append(self.browser_entry()))
        self.publish_fixture()
        self.assertEqual(validate(self.root)["status"], "passed")

    def test_browser_step_without_pac_attempt_is_rejected(self) -> None:
        self.update_handoff(
            lambda h: h["automationLedger"].append(self.browser_entry(programmaticAttempts=[]))
        )
        with self.assertRaisesRegex(ArtifactError, "without a recorded PAC CLI attempt"):
            self.publish_fixture()

    def test_programmatic_step_without_pac_attempt_is_rejected(self) -> None:
        entry = self.browser_entry(
            method="programmatic", tool="Dataverse Web API", programmaticAttempts=[],
            fallbackJustification=None, reconciliation=None,
        )
        self.update_handoff(lambda h: h["automationLedger"].append(entry))
        with self.assertRaisesRegex(ArtifactError, "without a recorded PAC CLI attempt"):
            self.publish_fixture()

    def test_browser_step_without_reconciliation_is_rejected(self) -> None:
        self.update_handoff(
            lambda h: h["automationLedger"].append(self.browser_entry(reconciliation=None))
        )
        with self.assertRaisesRegex(ArtifactError, "reconciliation"):
            self.publish_fixture()

    def test_browser_step_without_justification_is_rejected(self) -> None:
        self.update_handoff(
            lambda h: h["automationLedger"].append(self.browser_entry(fallbackJustification=" "))
        )
        with self.assertRaisesRegex(ArtifactError, "fallbackJustification"):
            self.publish_fixture()

    def test_outdated_pac_is_rejected(self) -> None:
        self.update_handoff(lambda h: h["automationToolchain"].update({"pacVersion": "2.9.10"}))
        with self.assertRaisesRegex(ArtifactError, "older than the latest"):
            self.publish_fixture()

    def test_newer_minor_pac_version_is_compared_numerically(self) -> None:
        self.update_handoff(
            lambda h: h["automationToolchain"].update(
                {"pacVersion": "2.12.10", "pacLatestVersion": "2.12.9"}
            )
        )
        self.publish_fixture()
        self.assertEqual(validate(self.root)["status"], "passed")

    def test_built_component_without_ledger_entry_is_rejected(self) -> None:
        self.update_handoff(lambda h: h.update({"automationLedger": []}))
        with self.assertRaisesRegex(ArtifactError, "without automationLedger entries"):
            self.publish_fixture()

    def test_missing_automation_records_are_rejected(self) -> None:
        self.update_handoff(lambda h: h.pop("automationLedger"))
        with self.assertRaises(ArtifactError):
            self.publish_fixture()

    def test_cowork_browser_fallback_needs_justification(self) -> None:
        self.convert_build_to_cowork()
        self.update_handoff(
            lambda h: h["automationLedger"][0].update({"fallbackJustification": None})
        )
        with self.assertRaisesRegex(ArtifactError, "fallbackJustification"):
            self.publish_fixture()

    def add_cowork_package(self, *, atk_version: str | None, tamper: bool = False) -> None:
        self.convert_build_to_cowork()
        package = self.root / "project" / "claims-intake-plugin" / "appPackage" / "build" / "claims-intake-plugin.zip"
        package.parent.mkdir(parents=True)
        package.write_bytes(b"fixture cowork plugin")
        record = {
            "relativePath": package.relative_to(self.root).as_posix(),
            "sha256": "0" * 64 if tamper else digest(package),
            "bytes": package.stat().st_size,
        }

        def change(handoff: dict) -> None:
            handoff["automationToolchain"]["atkVersion"] = atk_version
            handoff["artifacts"]["coworkPackages"] = [record]
            handoff["automationLedger"].append({
                "componentId": "fixture-agent",
                "operation": "install-plugin-personal",
                "platform": "Microsoft Cowork",
                "method": "programmatic",
                "tool": "atk install --scope Personal",
                "evidence": "TitleId and AppId recorded.",
                "programmaticAttempts": [],
                "fallbackJustification": None,
                "reconciliation": None,
            })

        self.update_handoff(change)

    def test_cowork_plugin_package_is_accepted(self) -> None:
        self.add_cowork_package(atk_version="1.1.12")
        self.publish_fixture()
        self.assertEqual(validate(self.root)["status"], "passed")

    def test_atk_step_requires_toolchain_version(self) -> None:
        self.add_cowork_package(atk_version=None)
        with self.assertRaisesRegex(ArtifactError, "atkVersion"):
            self.publish_fixture()

    def test_cowork_package_hash_mismatch_is_rejected(self) -> None:
        self.add_cowork_package(atk_version="1.1.12", tamper=True)
        with self.assertRaisesRegex(ArtifactError, "Cowork package hash"):
            self.publish_fixture()

    def run_cli(self, script: str, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SKILL_ROOT / "scripts" / script), "--root", str(self.root), *arguments],
            capture_output=True, text=True, timeout=120,
        )

    def test_cli_entry_points_enforce_automation_precedence(self) -> None:
        self.update_handoff(
            lambda h: h["automationLedger"].append(self.browser_entry(programmaticAttempts=[]))
        )
        publish_args = ("--status", "complete", "--summary", "CLI fixture.")
        rejected = self.run_cli("generate_manifest.py", *publish_args)
        self.assertEqual(2, rejected.returncode, rejected.stdout + rejected.stderr)
        self.assertIn("PAC CLI attempt", rejected.stderr)

        self.update_handoff(lambda h: h["automationLedger"].pop())
        published = self.run_cli("generate_manifest.py", *publish_args)
        self.assertEqual(0, published.returncode, published.stdout + published.stderr)
        validated = self.run_cli("validate_artifacts.py")
        self.assertEqual(0, validated.returncode, validated.stdout + validated.stderr)

        self.update_handoff(lambda h: h["automationToolchain"].update({"pacVersion": "1.0.0"}))
        stale = self.run_cli("validate_artifacts.py")
        self.assertEqual(2, stale.returncode, stale.stdout + stale.stderr)


if __name__ == "__main__":
    unittest.main()
