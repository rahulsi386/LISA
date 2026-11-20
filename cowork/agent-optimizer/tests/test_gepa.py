from __future__ import annotations

import copy
import contextlib
import importlib.util
import io
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from gepa_runtime import (ArtifactError, AwaitingHost, BudgetExhausted, HostBridge,
                          check_candidate, check_edit_scope, content_hash, load_object,
                          read_response, run_search, seal_response, sha256, validate_response, write_json)
from gepa_runtime import advance, abort_search, freeze_evaluation, initialize, verified_session, outcome, text_hash, session_lock
from gepa_runtime import github_copilot_execution, write_outcome
from gepa_runtime import decide_eligibility, derive_budgets, derive_partitions, derive_seed
from gepa_runtime import assess_eligibility
from lisa_path_resolver import resolve_lisa_config
from lifecycle_artifacts import inventory


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        evidence = self.root / "evidence.json"
        evidence.write_text('{"actual": "policy answer"}', encoding="utf-8")
        self.request = {"kind": "evaluation", "payload": {
            "candidateId": "candidate-1", "instructionSha256": "a" * 64,
            "agent": {"agentId": "shadow", "environmentId": "test", "harness": "Standard"},
            "partition": "train", "testIds": ["EVAL-001"], "protectedTestIds": ["EVAL-001"]}}
        self.response = {**self.request["payload"], "requestSha256": content_hash(self.request),
                         "owner": "agent-evaluator", "deploymentGate": False,
                         "evaluatorRunId": "EVAL-20260917-120000-ABCDEF12",
                         "persistenceReceipt": {"instructionSha256": "a" * 64,
                                                "agent": self.request["payload"]["agent"],
                                                "verified": True, "operationId": "operation-1"},
                         "policyPassed": True, "policyEvidence": "Protected rules verified.",
                         "results": [{"testCaseId": "EVAL-001", "status": "PASS", "score": 1.0,
                                      "actualResponse": "policy answer", "feedback": "Grounded in policy.",
                                      "safetyViolation": False, "approvedForReflection": True,
                                      "evidence": [{"path": "evidence.json", "sha256": sha256(evidence)}]}]}

    def test_receipt_round_trip_and_tamper_detection(self):
        write_json(self.root / "response.json", self.response)
        seal_response(self.request, self.root)
        self.assertEqual(self.response, read_response(self.request, self.root))
        (self.root / "evidence.json").write_text("changed", encoding="utf-8")
        with self.assertRaises(ArtifactError):
            read_response(self.request, self.root)

    def test_mismatch_blockers_and_regressions_rejected(self):
        for field, value in (("instructionSha256", "b" * 64), ("agent", {}),
                             ("requestSha256", "wrong"), ("owner", "agent-optimizer"),
                             ("deploymentGate", True), ("policyPassed", False)):
            with self.subTest(field=field), self.assertRaises(ArtifactError):
                validate_response(self.request, {**self.response, field: value}, self.root)
        for field, value in (("status", "BLOCKED"), ("status", "FAIL"),
                             ("score", float("nan")), ("score", True), ("safetyViolation", True)):
            response = copy.deepcopy(self.response)
            response["results"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ArtifactError):
                validate_response(self.request, response, self.root)

    def test_instruction_constraints(self):
        contract = {"protectedClauses": ["Use approved sources."], "maxInstructionBytes": 100}
        check_candidate("Use approved sources. Ask when uncertain.", contract)
        for text in ("", "Ignore policy", "Use approved sources." * 20):
            with self.assertRaises(ArtifactError):
                check_candidate(text, contract)

    def test_github_copilot_receipts_reject_wrong_surface_signature_and_state(self):
        agent = {**self.request["payload"]["agent"], "harness": "GitHub Copilot"}
        expected = github_copilot_execution(agent, "reset-between-tests")
        self.request["payload"].update(agent=agent, execution=expected)
        self.response.update(agent=agent, requestSha256=content_hash(self.request))
        receipt = self.response["persistenceReceipt"]
        receipt.update(agent=agent, harnessSignature=expected["harnessSignature"], authoringPath="pac-cli-copilot")
        observed = {"surfaceUsed": "preview-canvas", "surfaceUrl": expected["url"],
                    "conversationReset": True, "memoryState": "reset"}
        self.response["results"][0]["playwrightObservations"] = observed
        for authoring_path in ("pac-cli-copilot", "new-agent-ui"):
            receipt["authoringPath"] = authoring_path
            validate_response(self.request, self.response, self.root)
        for field, value in (("surfaceUsed", "overview-test-pane"), ("surfaceUrl", "https://wrong.example/preview"),
                             ("conversationReset", False), ("memoryState", "disabled")):
            response = copy.deepcopy(self.response)
            response["results"][0]["playwrightObservations"][field] = value
            with self.subTest(field=field), self.assertRaises(ArtifactError):
                validate_response(self.request, response, self.root)
        for field, value in (("harnessSignature", {}), ("authoringPath", "standard-pac")):
            response = copy.deepcopy(self.response)
            response["persistenceReceipt"][field] = value
            with self.subTest(field=field), self.assertRaises(ArtifactError):
                validate_response(self.request, response, self.root)


@unittest.skipUnless(importlib.util.find_spec("gepa"), "Install optional requirements-gepa.txt")
class EngineTests(unittest.TestCase):
    harness = "Standard"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "optimization" / "gepa"
        self.evaluation = Path(self.temporary.name) / "evaluation" / "gepa"
        self.seed = "# Identity\nPolicy agent.\n# Objectives\nAnswer questions.\n"
        self.improved = self.seed.replace("Answer questions.", "Retrieve evidence before answering.")
        self.session = {"runId": "OPT-20260917-120000-ABCDEF12", "seedText": self.seed,
                        "startedAt": datetime.now(timezone.utc).isoformat(),
                        "datasetSha256": "d" * 64, "rubricSha256": "e" * 64,
                        "contract": {"maxInstructionBytes": 1000, "protectedClauses": ["Policy agent."],
                                     "editableSections": ["Objectives"]},
                        "policy": {"seed": 7, "searchMetricCalls": 8, "maxMetricCalls": 100,
                                   "maxReflectionCalls": 10, "maxElapsedSeconds": 3600,
                                   "reflectionProvider": "fixture", "reflectionModel": "fixture",
                                   "minimumImprovement": 0.05, "trainIds": ["EVAL-001"],
                                   "validationIds": ["EVAL-002"], "holdoutIds": ["EVAL-003"],
                                   "protectedTestIds": ["EVAL-004"],
                                   "shadowAgent": {"agentId": "shadow", "environmentId": "test", "harness": self.harness}}}
        if self.harness == "GitHub Copilot":
            self.session["policy"]["githubCopilot"] = {"memoryMode": "disabled", "creditsVerified": True}

    def answer_pending(self, holdout_regresses=False):
        pending = load_object(self.root / "pending.json")
        directory = self.root / "requests" / pending["requestId"]
        request = load_object(directory / "request.json")
        response = {"requestSha256": content_hash(request)}
        if request["kind"] == "reflection":
            self.assertNotIn("EVAL-003", str(request))
            response.update(text=self.improved, provider="fixture", model="fixture",
                            costUsd=0.01, approvedForReflection=True)
        else:
            directory = self.evaluation / self.session["runId"] / pending["requestId"]
            directory.mkdir(parents=True, exist_ok=True)
            evidence = directory / "evidence.json"
            evidence.write_text('{"syntheticTestOnly": true}', encoding="utf-8")
            payload = request["payload"]
            candidate = load_object(self.root / "candidates" / (payload["candidateId"] + ".json"))
            score = 0.4 if candidate["text"] == self.seed else 0.9
            if holdout_regresses and payload["partition"] == "holdout" and candidate["text"] != self.seed:
                score = 0.2
            response.update({key: payload[key] for key in ("candidateId", "instructionSha256", "agent", "partition")})
            response.update(owner="agent-evaluator", deploymentGate=False, policyPassed=True,
                            policyEvidence="Fixture policy audit", evaluatorRunId="EVAL-20260917-120000-ABCDEF12",
                            persistenceReceipt={"verified": True, "operationId": pending["requestId"],
                                                "agent": payload["agent"], "instructionSha256": payload["instructionSha256"]},
                            results=[{"testCaseId": test_id, "status": "PASS", "score": score,
                                      "safetyViolation": False, "approvedForReflection": True,
                                      "actualResponse": "Fixture output", "feedback": "Retrieve approved evidence.",
                                      "evidence": [{"path": "evidence.json", "sha256": sha256(evidence)}]}
                                     for test_id in payload["testIds"]])
            if self.harness == "GitHub Copilot":
                expected = payload["execution"]
                self.assertEqual("preview-canvas", expected["surface"])
                self.assertEqual("https://copilotstudio.preview.microsoft.com/environments/test/agents/shadow/preview", expected["url"])
                response["persistenceReceipt"].update(harnessSignature=expected["harnessSignature"], authoringPath="pac-cli-copilot")
                for item in response["results"]:
                    item["playwrightObservations"] = {"surfaceUsed": "preview-canvas", "surfaceUrl": expected["url"],
                                                     "conversationReset": True, "memoryState": "disabled"}
        write_json(directory / "response.json", response)
        seal_response(request, directory)

    def drive(self, holdout_regresses=False):
        for attempt in range(40):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                try:
                    return run_search(HostBridge(self.root, self.evaluation, self.session))
                except AwaitingHost:
                    self.answer_pending(holdout_regresses)
        self.fail("GEPA search did not finish within the test bound")

    def test_real_engine_pause_replay_and_impact(self):
        result = self.drive()
        self.assertEqual("ready-for-promotion", result["status"])
        self.assertAlmostEqual(0.5, result["impact"]["holdout"]["delta"])
        self.assertEqual("not-measured", result["impact"]["targetImpact"])
        self.assertGreater(result["execution"]["metricCalls"], 0)
        self.assertGreater(len(result["candidates"]), 1)
        self.assertEqual(self.harness, result["execution"]["harness"])
        receipts = {path: path.stat().st_mtime_ns for path in self.evaluation.rglob("result.json")}
        self.assertEqual(result, self.drive())
        self.assertEqual(receipts, {path: path.stat().st_mtime_ns for path in receipts})

    def test_holdout_regression_prevents_promotion(self):
        self.assertEqual("holdout-rejected", self.drive(True)["status"])

    def test_final_target_impact_is_separate_and_version_bound(self):
        target = {"agentId": "target", "environmentId": "test", "harness": self.harness}
        self.session["policy"]["enabled"] = True
        self.session["agent"] = target
        canonical = self.evaluation.parent
        write_json(canonical / "evaluation-dataset.json", {"frozen": True})
        write_json(canonical / "evaluation-rubric.json", {"frozen": True})
        write_json(canonical / "regression-baseline.json", {"frozen": True})
        self.session["datasetSha256"] = sha256(canonical / "evaluation-dataset.json")
        self.session["rubricSha256"] = sha256(canonical / "evaluation-rubric.json")
        initial = {"runId": "EVAL-20260917-120000-ABCDEF12", "summary": {"passed": 1},
                   "results": [{"testCaseId": "EVAL-001", "status": "FAIL"}, {"testCaseId": "EVAL-004", "status": "PASS"}]}
        frozen = self.evaluation / self.session["runId"] / "baseline"
        write_json(frozen / "evaluation-observations.json", initial)
        write_json(frozen / "regression-baseline.json", {"frozen": True})
        write_json(frozen / "manifest.json", {"files": {"evaluation-observations.json": sha256(frozen / "evaluation-observations.json"),
                                "regression-baseline.json": sha256(frozen / "regression-baseline.json")}})
        self.session["frozenManifestSha256"] = sha256(frozen / "manifest.json")
        result = self.drive()
        write_json(self.root / "session.json", self.session)
        write_json(self.root.parent / "gepa-run.json", result)
        write_json(self.root / "search-receipt.json", {"sha256": content_hash(result)})
        plan = {"runId": self.session["runId"], "policy": {"gepa": self.session["policy"]},
                "agent": target, "sourceEvaluation": {"runId": initial["runId"]}, "rounds": []}
        write_json(self.root.parent / "optimization-plan.json", plan)
        write_json(self.root.parent / "gepa-eligibility.json",
                   {"schemaVersion": "1.0", "runId": self.session["runId"], "decidedAt": "2026-09-17T12:00:00+00:00",
                    "harness": self.harness, "sourceEvaluationRunId": initial["runId"],
                    "eligible": True, "reason": "eligible", "detail": "Engine fixture decision."})
        self.assertEqual("not-measured", outcome(self.root.parent)["overallImpact"]["status"])
        candidate = load_object(self.root / "candidates" / (result["selectedCandidateId"] + ".json"))
        promoted = {"roundId": "round-001", "status": "accepted", "outcome": "accepted",
                    "gepaCandidateId": result["selectedCandidateId"], "gepaRunSha256": sha256(self.root.parent / "gepa-run.json"),
                    "evaluatorRunId": "EVAL-20260917-130000-ABCDEF12"}
        plan["rounds"] = [promoted]
        write_json(self.root.parent / "optimization-plan.json", plan)
        write_json(self.root.parent / "optimization-change-log.json", {"rounds": [promoted]})
        write_json(self.root.parent / "rounds" / "round-001" / "after-state-manifest.json", {"instructionSha256": candidate["instructionSha256"]})
        final = {"runId": promoted["evaluatorRunId"], "agent": target, "instructionSha256": candidate["instructionSha256"],
                 "summary": {"passed": 2}, "results": [{"testCaseId": item["testCaseId"], "status": "PASS"} for item in initial["results"]],
                 "optimizerHandoff": {"evaluationDecision": "PASS"}}
        if self.harness == "GitHub Copilot":
            expected = github_copilot_execution(target, "disabled")
            final["gepaExecution"] = {"harnessSignature": expected["harnessSignature"], "authoringPath": "new-agent-ui"}
            for item in final["results"]:
                item["playwrightObservations"] = {"surfaceUsed": "preview-canvas", "surfaceUrl": expected["url"],
                                                 "conversationReset": True, "memoryState": "disabled"}
        write_json(canonical / "evaluation-observations.json", final)
        with patch("lifecycle_artifacts.validate"):
            self.assertEqual(0.5, outcome(self.root.parent)["overallImpact"]["passRateDelta"])
            write_outcome(self.root.parent)
            report = (self.root.parent / "optimization-impact.md").read_text(encoding="utf-8")
            self.assertIn(f"Harness: {self.harness}", report)
            if self.harness == "GitHub Copilot":
                self.assertIn("Candidate test surface: preview-canvas", report)
                final["results"][0]["playwrightObservations"]["surfaceUsed"] = "overview-test-pane"
                write_json(canonical / "evaluation-observations.json", final)
                with self.assertRaisesRegex(ArtifactError, "preview surface"):
                    outcome(self.root.parent)
                final["results"][0]["playwrightObservations"]["surfaceUsed"] = "preview-canvas"
            final["instructionSha256"] = "0" * 64
            write_json(canonical / "evaluation-observations.json", final)
            with self.assertRaisesRegex(ArtifactError, "selected GEPA instructions"):
                outcome(self.root.parent)

    def test_budget_and_protected_sections(self):
        self.session["policy"]["maxMetricCalls"] = 1
        with self.assertRaises(BudgetExhausted):
            self.drive()
        with self.assertRaises(ArtifactError):
            check_edit_scope(self.seed, self.improved.replace("Policy agent.", "Other role."), self.session["contract"])


class GitHubCopilotEngineTests(EngineTests):
    harness = "GitHub Copilot"


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        write_json(base / "lisa-config.json", {"basePath": ".", "copilotStudio": {"envId": "test", "envUrl": "https://example.crm.dynamics.com"}})
        self.paths = resolve_lisa_config(base / "lisa-config.json")
        self.seed = "# Identity\nPolicy agent.\n# Objectives\nAnswer questions.\n"
        self.policy = {"reflectionProvider": "fixture", "reflectionModel": "fixture", "reflectionApproved": True,
                       "isolationVerified": True, "isolationEvidence": "Fixture isolation evidence",
                       "shadowAgent": {"agentId": "shadow", "environmentId": "test", "harness": "Standard"}}
        self.plan = {"schemaVersion": "1.0", "runId": "OPT-20260917-120000-ABCDEF12", "generatedAt": "2026-09-17T12:00:00Z",
                     "agent": {"agentId": "target", "environmentId": "test", "harness": "Standard",
                               "name": "Policy Agent", "environmentUrl": "https://example.crm.dynamics.com"},
                     "sourceEvaluation": {"runId": "EVAL-20260917-120000-ABCDEF12", "decision": "FAIL",
                                          "observationsRelativePath": "evaluation/evaluation-observations.json",
                                          "deploymentGateRelativePath": "evaluation/deployment-gate-summary.md"},
                     "policy": {"gepa": self.policy}, "rounds": [], "deferredFindings": []}
        write_json(self.paths.optimization / "optimization-plan.json", self.plan)
        self.eligibility = {"schemaVersion": "1.0", "runId": self.plan["runId"],
                            "decidedAt": "2026-09-17T12:00:00+00:00", "harness": "Standard",
                            "sourceEvaluationRunId": self.plan["sourceEvaluation"]["runId"],
                            "eligible": True, "reason": "eligible", "detail": "Fixture decision."}
        write_json(self.paths.optimization / "gepa-eligibility.json", self.eligibility)
        write_json(self.paths.optimization / "instruction-audit.json", {"instructionSha256": text_hash(self.seed)})
        write_json(self.paths.build / "build-manifest.json", {})
        write_json(self.paths.build / "agent-build-handoff.json", {"agent": self.plan["agent"],
                   "instructionOptimization": {"seedSha256": text_hash(self.seed), "maxInstructionBytes": 1000,
                                               "editableSections": ["Objectives"], "protectedClauses": ["Policy agent."],
                                               "allowedComponentNames": []}})
        (self.paths.build / "agent-instructions.md").write_text(self.seed, encoding="utf-8", newline="\n")
        write_json(self.paths.evaluation / "evaluation-dataset.json", {"testCases": [
            {"id": f"EVAL-{index:03d}", "severity": "critical" if index == 4 else "high"} for index in range(1, 5)]})
        write_json(self.paths.evaluation / "evaluation-rubric.json", {})
        write_json(self.paths.evaluation / "regression-baseline.json", {"agent": {"instructionSha256": text_hash(self.seed)}})
        write_json(self.paths.evaluation / "evaluation-observations.json", {
            "agent": self.plan["agent"],
            "runId": self.plan["sourceEvaluation"]["runId"], "optimizerHandoff": {"eligibleForOptimization": True,
            "findings": [{"suspectedChangeSurface": "instructions", "doNotOptimizeReason": None}]}})

    def prepare(self):
        with patch("lifecycle_artifacts.validate"):
            freeze_evaluation(self.paths)
            return initialize(self.paths)

    def set_harness(self, target, shadow):
        self.plan["agent"]["harness"] = target
        self.policy["shadowAgent"]["harness"] = shadow
        if shadow == "GitHub Copilot":
            self.policy["githubCopilot"] = {"memoryMode": "disabled", "creditsVerified": True}
        else:
            self.policy.pop("githubCopilot", None)
        write_json(self.paths.optimization / "optimization-plan.json", self.plan)
        self.eligibility["harness"] = target
        write_json(self.paths.optimization / "gepa-eligibility.json", self.eligibility)
        for directory, filename in ((self.paths.build, "agent-build-handoff.json"),
                                    (self.paths.evaluation, "evaluation-observations.json")):
            value = load_object(directory / filename)
            value["agent"]["harness"] = target
            if target == "GitHub Copilot" and filename == "evaluation-observations.json":
                expected = github_copilot_execution(value["agent"], "disabled")
                value["gepaExecution"] = {"harnessSignature": expected["harnessSignature"], "authoringPath": "pac-cli-copilot"}
                value["results"] = [{"playwrightObservations": {"surfaceUsed": "preview-canvas", "surfaceUrl": expected["url"],
                                                              "conversationReset": True, "memoryState": "disabled"}}]
            write_json(directory / filename, value)

    def test_github_copilot_session_uses_matching_shadow(self):
        self.set_harness("GitHub Copilot", "GitHub Copilot")
        session = self.prepare()
        self.assertEqual("GitHub Copilot", session["agent"]["harness"])
        self.assertEqual("GitHub Copilot", session["policy"]["shadowAgent"]["harness"])
        self.assertEqual(session, verified_session(self.paths))

    def test_cross_harness_and_unsupported_targets_are_rejected(self):
        for target, shadow in (("GitHub Copilot", "Standard"), ("Standard", "GitHub Copilot"),
                               ("Copilot chat", "Standard"), ("Standard", "Copilot chat")):
            self.set_harness(target, shadow)
            with self.subTest(target=target, shadow=shadow), self.assertRaises(ArtifactError):
                self.prepare()

    def test_copilot_chat_session_uses_matching_shadow(self):
        self.set_harness("Copilot chat", "Copilot chat")
        session = self.prepare()
        self.assertEqual("Copilot chat", session["agent"]["harness"])
        self.assertEqual("Copilot chat", session["policy"]["shadowAgent"]["harness"])
        self.assertNotIn("githubCopilot", session["policy"])

    def test_lisa_derives_partitions_and_budgets_from_the_frozen_dataset(self):
        session = self.prepare()
        policy = session["policy"]
        partitions = [set(policy[key]) for key in ("trainIds", "validationIds", "holdoutIds", "protectedTestIds")]
        self.assertEqual({f"EVAL-{index:03d}" for index in range(1, 5)}, set.union(*partitions))
        self.assertEqual(4, sum(len(item) for item in partitions))
        self.assertEqual({"EVAL-004"}, partitions[3])
        self.assertGreaterEqual(policy["maxMetricCalls"],
                                policy["searchMetricCalls"] + 2 * (len(policy["holdoutIds"]) + len(policy["protectedTestIds"])))
        self.assertEqual(derive_seed(self.plan["runId"]), policy["seed"])
        self.assertEqual(policy, load_object(self.paths.optimization / "optimization-plan.json")["policy"]["gepa"])

    def test_eligibility_reason_codes_are_deterministic(self):
        dataset = self.paths.evaluation / "evaluation-dataset.json"
        cowork = {**self.plan, "agent": {**self.plan["agent"], "harness": None}}
        self.assertEqual("unsupported-harness", decide_eligibility(cowork, self.paths.evaluation)["reason"])
        observations = load_object(self.paths.evaluation / "evaluation-observations.json")
        blocked = copy.deepcopy(observations)
        blocked["optimizerHandoff"]["eligibleForOptimization"] = False
        write_json(self.paths.evaluation / "evaluation-observations.json", blocked)
        self.assertEqual("evaluation-ineligible", decide_eligibility(self.plan, self.paths.evaluation)["reason"])
        tools = copy.deepcopy(observations)
        tools["optimizerHandoff"]["findings"] = [{"suspectedChangeSurface": "tool-schema"}]
        write_json(self.paths.evaluation / "evaluation-observations.json", tools)
        self.assertEqual("no-instruction-finding", decide_eligibility(self.plan, self.paths.evaluation)["reason"])
        write_json(self.paths.evaluation / "evaluation-observations.json", observations)
        write_json(dataset, {"testCases": [{"id": f"EVAL-{index:03d}", "severity": "high"} for index in range(1, 4)]})
        self.assertEqual("dataset-too-small", decide_eligibility(self.plan, self.paths.evaluation)["reason"])

    def test_github_copilot_requires_memory_policy_and_verified_credits(self):
        for policy in (None, {"memoryMode": "shared", "creditsVerified": True},
                       {"memoryMode": "disabled", "creditsVerified": False}):
            self.set_harness("GitHub Copilot", "GitHub Copilot")
            if policy is None:
                del self.policy["githubCopilot"]
            else:
                self.policy["githubCopilot"] = policy
            write_json(self.paths.optimization / "optimization-plan.json", self.plan)
            with self.subTest(policy=policy), self.assertRaises(ArtifactError):
                self.prepare()

    def test_github_copilot_rejects_baseline_without_execution_evidence(self):
        self.set_harness("GitHub Copilot", "GitHub Copilot")
        observations = load_object(self.paths.evaluation / "evaluation-observations.json")
        del observations["gepaExecution"]
        write_json(self.paths.evaluation / "evaluation-observations.json", observations)
        with self.assertRaisesRegex(ArtifactError, "signature mismatch"):
            self.prepare()

    def test_github_copilot_reset_memory_policy_requires_matching_baseline(self):
        self.set_harness("GitHub Copilot", "GitHub Copilot")
        self.policy["githubCopilot"]["memoryMode"] = "reset-between-tests"
        write_json(self.paths.optimization / "optimization-plan.json", self.plan)
        with self.assertRaisesRegex(ArtifactError, "memory isolation"):
            self.prepare()

    def test_freeze_isolation_and_session_drift(self):
        before = inventory(self.paths.evaluation, "evaluation-manifest.json")
        session = self.prepare()
        self.assertEqual(before, inventory(self.paths.evaluation, "evaluation-manifest.json"))
        self.assertEqual(session, verified_session(self.paths))
        frozen = self.paths.evaluation / "gepa" / self.plan["runId"] / "baseline" / "evaluation-rubric.json"
        write_json(frozen, {"changed": True})
        with self.assertRaisesRegex(ArtifactError, "input changed"):
            verified_session(self.paths)

    def test_decision_is_recorded_once_and_reused(self):
        path = self.paths.optimization / "gepa-eligibility.json"
        path.unlink()
        decision = assess_eligibility(self.paths)
        self.assertEqual(self.plan["runId"], decision["runId"])
        self.assertEqual(self.plan["sourceEvaluation"]["runId"], decision["sourceEvaluationRunId"])
        self.assertIn(decision["reason"], ("eligible", "engine-unavailable"))
        self.assertEqual(decision["eligible"], decision["reason"] == "eligible")
        self.assertEqual(decision, load_object(path))
        self.assertEqual(decision, assess_eligibility(self.paths))

    def test_host_supplied_policy_inputs_are_validated(self):
        for mutation in ("target", "isolation", "reflection", "environment"):
            policy = copy.deepcopy(self.policy)
            if mutation == "target":
                policy["shadowAgent"]["agentId"] = "target"
            elif mutation == "isolation":
                policy["isolationVerified"] = False
            elif mutation == "reflection":
                del policy["reflectionProvider"]
            else:
                policy["shadowAgent"]["environmentId"] = "other"
            write_json(self.paths.optimization / "optimization-plan.json", {**self.plan, "policy": {"gepa": policy}})
            with self.subTest(mutation=mutation), self.assertRaises(ArtifactError):
                self.prepare()

    def test_ineligible_run_and_missing_builder_contract(self):
        write_json(self.paths.optimization / "gepa-eligibility.json",
                   {**self.eligibility, "eligible": False, "reason": "no-instruction-finding",
                    "detail": "No instruction finding."})
        with self.assertRaisesRegex(ArtifactError, "not eligible"):
            self.prepare()
        write_json(self.paths.optimization / "gepa-eligibility.json", self.eligibility)
        handoff = load_object(self.paths.build / "agent-build-handoff.json")
        del handoff["instructionOptimization"]
        write_json(self.paths.build / "agent-build-handoff.json", handoff)
        with self.assertRaisesRegex(ArtifactError, "builder instructionOptimization"):
            self.prepare()

    def test_session_lock_prevents_concurrent_writers(self):
        with session_lock(self.paths):
            with self.assertRaisesRegex(ArtifactError, "locked"):
                with session_lock(self.paths):
                    self.fail("Second writer acquired lock")
        self.assertFalse((self.paths.optimization / "gepa" / "execution.lock").exists())

    @unittest.skipUnless(importlib.util.find_spec("gepa"), "Install optional requirements-gepa.txt")
    def test_cli_pause_and_abort_preserve_canonical_evaluation(self):
        self.assert_cli_pause_and_abort()

    @unittest.skipUnless(importlib.util.find_spec("gepa"), "Install optional requirements-gepa.txt")
    def test_github_copilot_cli_pause_and_abort(self):
        self.set_harness("GitHub Copilot", "GitHub Copilot")
        self.assert_cli_pause_and_abort()

    def assert_cli_pause_and_abort(self):
        self.prepare()
        script = Path(__file__).resolve().parents[1] / "scripts" / "gepa_optimize.py"
        before = {path: sha256(path) for path in self.paths.evaluation.glob("*.json")}
        response = subprocess.run([sys.executable, str(script), "advance", "--config", str(self.paths.config_path)],
                                  capture_output=True, text=True, timeout=30)
        self.assertEqual(3, response.returncode, response.stdout + response.stderr)
        self.assertEqual("awaiting-host", load_object(self.paths.optimization / "gepa-run.json")["status"])
        pending = load_object(self.paths.optimization / "gepa" / "pending.json")
        request = load_object(self.paths.optimization / "gepa" / "requests" / pending["requestId"] / "request.json")
        if self.plan["agent"]["harness"] == "GitHub Copilot":
            self.assertEqual("preview-canvas", request["payload"]["execution"]["surface"])
        else:
            self.assertNotIn("execution", request["payload"])
        response = subprocess.run([sys.executable, str(script), "abort", "--config", str(self.paths.config_path),
                                   "--reason", "Fixture host unavailable"], capture_output=True, text=True, timeout=30)
        self.assertEqual(2, response.returncode, response.stdout + response.stderr)
        run = load_object(self.paths.optimization / "gepa-run.json")
        self.assertEqual("blocked", run["status"])
        self.assertEqual(run, advance(self.paths))
        self.assertEqual(before, {path: sha256(path) for path in before})
        with self.assertRaisesRegex(ArtifactError, "Terminal"):
            abort_search(self.paths, "Must not replace")


if __name__ == "__main__":
    unittest.main()