from __future__ import annotations

import hashlib
import json
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
        write_json(
            self.root / "agent-build-handoff.json",
            {
                "schemaVersion": "1.0",
                "runId": run_id,
                "generatedAt": "2026-08-18T12:00:00Z",
                "agent": {
                    **AGENT,
                    "recommendedTestSurface": "overview-test-pane",
                    "state": "Published",
                },
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
                "artifacts": {
                    "packages": [package_record],
                    "projectRelativePath": None,
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
                "agent": {**AGENT, "state": "Published"},
                "instructionsSha256": digest(instructions),
                "components": [
                    {"name": "Agent", "type": "agent", "status": "present"}
                ],
                "capabilities": {},
                "packages": [package_record],
            },
        )
        (self.root / "agent-build-report.md").write_text("# Build\n", encoding="utf-8")

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


if __name__ == "__main__":
    unittest.main()
