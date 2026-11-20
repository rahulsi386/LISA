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
from render_evaluation import render  # noqa: E402
from validate_artifacts import ArtifactError, load_object, validate  # noqa: E402

BUILD_RUN = "BLD-20260818-120000-ABCDEF12"
EVAL_RUN = "EVAL-20260818-130000-ABCDEF12"
PRIOR_RUN = "EVAL-20260817-130000-ABCDEF12"
SHA = hashlib.sha256(b"instructions").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def case(test_id: str, severity: str, prompt: str) -> dict:
    return {
        "id": test_id,
        "scenario": f"Scenario {test_id}",
        "sourceType": "knowledge-source",
        "sourceReferences": [{"source": "policy.pdf", "locator": "page 1"}],
        "userPrompt": prompt,
        "expectedResponse": "Use the approved policy.",
        "expectedBehavior": "Answer from policy.pdf.",
        "responseAssertions": ["Uses the approved policy"],
        "expectedKnowledgeSources": ["policy.pdf"],
        "requiredTools": [],
        "prohibitedBehavior": [],
        "evaluationTypes": ["LLM_AS_JUDGE", "GROUNDEDNESS"],
        "severity": severity,
        "passCriteria": "The approved policy is used.",
        "failCriteria": "The answer is unsupported.",
    }


def result(test_id: str, status: str, score: int) -> dict:
    gate_status = "PASS" if status == "PASS" else "FAIL"
    return {
        "testCaseId": test_id,
        "actualResponse": "Use the approved policy, line one.\nLine two.",
        "status": status,
        "durationMs": 1200,
        "attempts": 1,
        "playwrightObservations": {
            "conversationReset": True,
            "responseCompleted": True,
            "surfaceUsed": "overview-test-pane",
            "citationsObserved": ["policy.pdf"],
            "toolActivityObserved": [],
            "uiErrors": [],
            "sideEffectsObserved": [],
            "evidence": [f"evidence/{test_id}-attempt-01.png"],
            "notes": "Complete response.",
        },
        "gateResults": {
            "llmAsJudge": {"status": gate_status, "score": score, "rationale": "Compared with expected."},
            "groundedness": {"status": gate_status, "score": score, "rationale": "Checked policy.pdf."},
        },
        "assertionResults": [],
        "failureReasons": [] if status == "PASS" else ["Missing citation"],
        "blocker": None,
    }


class RenderEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        output = Path(self.temp.name) / "output"
        self.root = output / "evaluation"
        (self.root / "evidence").mkdir(parents=True)
        for test_id in ("EVAL-001", "EVAL-002"):
            (self.root / "evidence" / f"{test_id}-attempt-01.png").write_bytes(b"png")
        write_json(output / "build" / "agent-build-handoff.json", {
            "runId": BUILD_RUN, "instructions": {"sha256": SHA},
        })
        write_json(self.root / "evaluation-dataset.json", {
            "schemaVersion": "1.0",
            "generatedAt": "2026-08-18T13:00:00Z",
            "testSetId": "fixture-v1",
            "sources": [{"name": "policy.pdf", "type": "knowledge-source",
                         "location": "evalData/policy.pdf", "authority": "authoritative"}],
            "testCases": [case("EVAL-001", "critical", "What is the policy?"),
                          case("EVAL-002", "medium", "Summarize, the policy \"briefly\".")],
        })
        write_json(self.root / "evaluation-rubric.json", {
            "schemaVersion": "1.0",
            "scale": {str(i): f"score {i}" for i in range(5)},
            "gates": {key: {"criteria": ["criterion"], "passThreshold": 3}
                      for key in ("LLM_AS_JUDGE", "TOOL_USE", "GROUNDEDNESS", "REGRESSION")},
            "overall": {"minimumAverage": 3, "criticalTestsMustPass": True,
                        "blockedCriticalTestsFail": True, "notRunCriticalTestsFail": True,
                        "automaticFailures": []},
        })
        self.write_observations([result("EVAL-001", "PASS", 4), result("EVAL-002", "FAIL", 1)], "FAIL")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_observations(self, results: list[dict], decision: str) -> None:
        write_json(self.root / "evaluation-observations.json", {
            "schemaVersion": "1.1",
            "runId": EVAL_RUN,
            "testSetId": "fixture-v1",
            "agent": {"name": "Policy Agent", "agentId": "agent-id", "harness": "Standard",
                      "surface": "overview-test-pane", "environmentId": "env-id"},
            "startedAt": "2026-08-18T13:00:00Z",
            "completedAt": "2026-08-18T13:05:00Z",
            "results": results,
            "optimizerHandoff": {"evaluationDecision": decision, "eligibleForOptimization": True,
                                 "findings": [{"id": "OPT-FINDING-001", "severity": "medium",
                                               "failedGates": ["GROUNDEDNESS"],
                                               "observedSymptom": "No citation.",
                                               "requiredRetestScope": ["EVAL-002"]}]},
        })

    def test_rendered_set_publishes_and_validates(self) -> None:
        outcome = render(self.root)
        self.assertEqual("fail", outcome["manifestStatus"])
        self.assertTrue(outcome["baselineCreated"])
        self.assertEqual([BUILD_RUN], outcome["sourceRuns"])
        observations = load_object(self.root / "evaluation-observations.json")
        self.assertEqual("What is the policy?", observations["results"][0]["userPrompt"])
        self.assertEqual(1, observations["summary"]["failed"])
        self.assertEqual("FAIL", observations["gateSummary"]["groundedness"]["status"])
        csv_text = (self.root / "evaluation-dataset.csv").read_text(encoding="utf-8")
        self.assertTrue(csv_text.startswith("id,scenario,sourceType,sourceReferences,userPrompt"))
        self.assertIn('"Summarize, the policy ""briefly""."', csv_text)
        report = (self.root / "evaluation-run-report.md").read_text(encoding="utf-8")
        for heading in ("## Run Metadata", "## Test Case Observations", "## Overall Decision"):
            self.assertIn(heading, report)
        self.assertIn("> Line two.", report)
        gate = (self.root / "deployment-gate-summary.md").read_text(encoding="utf-8")
        self.assertIn("**Overall decision:** FAIL", gate)
        publish(self.root, outcome["manifestStatus"], "Rendered fixture.", outcome["sourceRuns"])
        self.assertEqual("passed", validate(self.root)["status"])

    def test_unsupported_pass_is_refused(self) -> None:
        self.write_observations([result("EVAL-001", "FAIL", 1), result("EVAL-002", "PASS", 4)], "PASS")
        with self.assertRaisesRegex(ArtifactError, "critical tests not passed"):
            render(self.root)

    def test_pass_with_failed_gate_result_is_refused(self) -> None:
        passing = result("EVAL-001", "PASS", 4)
        passing["gateResults"]["groundedness"]["status"] = "NOT_OBSERVABLE"
        self.write_observations([passing, result("EVAL-002", "FAIL", 1)], "FAIL")
        with self.assertRaisesRegex(ArtifactError, "is PASS but groundedness"):
            render(self.root)

    def test_restated_field_must_match_dataset(self) -> None:
        drifted = result("EVAL-001", "PASS", 4)
        drifted["userPrompt"] = "A different prompt"
        self.write_observations([drifted, result("EVAL-002", "FAIL", 1)], "FAIL")
        with self.assertRaisesRegex(ArtifactError, "differs from the dataset"):
            render(self.root)

    def test_every_dataset_test_needs_a_result(self) -> None:
        self.write_observations([result("EVAL-001", "PASS", 4)], "FAIL")
        with self.assertRaisesRegex(ArtifactError, "missing=\\['EVAL-002'\\]"):
            render(self.root)

    def test_prior_baseline_is_preserved_and_compared(self) -> None:
        prior = {
            "schemaVersion": "1.0", "baselineId": "fixture-v1-approved",
            "approvalStatus": "approved", "createdAt": "2026-08-17T13:05:00Z",
            "sourceRunId": PRIOR_RUN,
            "agent": {"name": "Policy Agent", "agentId": "agent-id", "harness": "Standard",
                      "instructionSha256": SHA},
            "summary": {"passed": 2, "failed": 0},
            "cases": [{"testCaseId": "EVAL-001", "status": "PASS", "scores": {}},
                      {"testCaseId": "EVAL-002", "status": "PASS", "scores": {}}],
        }
        write_json(self.root / "regression-baseline.json", prior)
        before = (self.root / "regression-baseline.json").read_bytes()
        outcome = render(self.root)
        self.assertFalse(outcome["baselineCreated"])
        self.assertEqual([BUILD_RUN, PRIOR_RUN], outcome["sourceRuns"])
        self.assertEqual(before, (self.root / "regression-baseline.json").read_bytes())
        self.assertIn("Regressed tests: EVAL-002.",
                      (self.root / "evaluation-run-report.md").read_text(encoding="utf-8"))
        publish(self.root, outcome["manifestStatus"], "Rendered fixture.", outcome["sourceRuns"])
        self.assertEqual("passed", validate(self.root)["status"])


if __name__ == "__main__":
    unittest.main()
