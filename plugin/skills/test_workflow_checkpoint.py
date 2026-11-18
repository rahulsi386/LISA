import json
import tempfile
import unittest
from pathlib import Path

from workflow_checkpoint import (
    CheckpointError,
    complete_stage,
    initialize,
    recover,
    start_stage,
    update_checkpoint,
)


class WorkflowCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        (self.base / "requirements").mkdir()
        self.config = self.base / "lisa-config.json"
        self.config.write_text(
            json.dumps({"basePath": str(self.base), "custName": "Example"}),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_recovers_exact_phase_and_unit(self) -> None:
        workflow = initialize(self.config, "WF-20260826-120000-A1B2C3D4")
        self.assertEqual("RUNNING", workflow["status"])
        start_stage(self.config, "evaluation", "EVAL-001", "execute-test", "EVAL-017")
        update_checkpoint(self.config, "execute-test", "EVAL-018", "RUNNING")

        result = recover(self.config)

        self.assertEqual("continue-phase", result["resume"]["action"])
        self.assertEqual("evaluation", result["resume"]["stage"])
        self.assertEqual("execute-test", result["resume"]["phase"])
        self.assertEqual("EVAL-018", result["resume"]["unitId"])

    def test_pending_remote_operation_requires_reconciliation(self) -> None:
        initialize(self.config, "WF-20260826-120001-A1B2C3D4")
        start_stage(self.config, "build", "BLD-001", "publish-agent", "agent-1")
        operation = {
            "operationId": "publish-agent-1",
            "idempotencyKey": "BLD-001:publish-agent-1",
            "target": "agent-1",
        }
        update_checkpoint(
            self.config,
            "publish-agent",
            "agent-1",
            "RECONCILING",
            pending_operation=operation,
        )

        result = recover(self.config)

        self.assertEqual("reconcile-remote-operation", result["resume"]["action"])
        self.assertEqual(operation, result["resume"]["pendingOperation"])

    def test_uses_valid_ab_snapshot_when_pointer_targets_corrupt_slot(self) -> None:
        initialize(self.config, "WF-20260826-120002-A1B2C3D4")
        start_stage(self.config, "analysis", "RA-001", "extract", "SRC-001")
        root = self.base / ".lisa"
        run = root / "runs" / "WF-20260826-120002-A1B2C3D4"
        (run / "workflow.b.json").write_text("{broken", encoding="utf-8")

        result = recover(self.config)

        self.assertEqual("analysis", result["resume"]["stage"])

    def test_blocked_stage_is_not_treated_as_committed(self) -> None:
        initialize(self.config, "WF-20260826-120003-A1B2C3D4")
        start_stage(self.config, "build", "BLD-001", "verify", None)
        marker = self.base / "output" / "build" / "build-manifest.json"
        marker.parent.mkdir(parents=True)
        marker.write_text("{}", encoding="utf-8")
        import hashlib
        marker_hash = hashlib.sha256(marker.read_bytes()).hexdigest()
        result = complete_stage(self.config, "output/build/build-manifest.json", marker_hash, "BLOCKED")

        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("BLOCKED", result["completedStages"]["build"]["status"])
        with self.assertRaises(CheckpointError):
            start_stage(self.config, "evaluation", "EVAL-001", "prepare", None)

    def test_new_workflow_supersedes_higher_generation_blocked_pointer(self) -> None:
        initialize(self.config, "WF-20260826-120006-A1B2C3D4")
        start_stage(self.config, "build", "BLD-001", "verify", None)
        marker = self.base / "output" / "build" / "build-manifest.json"
        marker.parent.mkdir(parents=True)
        marker.write_text("{}", encoding="utf-8")
        import hashlib
        marker_hash = hashlib.sha256(marker.read_bytes()).hexdigest()
        complete_stage(self.config, "output/build/build-manifest.json", marker_hash, "BLOCKED")

        workflow = initialize(self.config, "WF-20260826-120007-A1B2C3D4")
        result = recover(self.config)

        self.assertEqual(workflow["workflowRunId"], result["workflow"]["workflowRunId"])
        self.assertTrue(result["configMatches"])

    def test_recovers_when_primary_pointer_and_stage_file_are_corrupt(self) -> None:
        initialize(self.config, "WF-20260826-120004-A1B2C3D4")
        start_stage(self.config, "evaluation", "EVAL-002", "execute-test", "EVAL-004")
        root = self.base / ".lisa"
        run = root / "runs" / "WF-20260826-120004-A1B2C3D4"
        (root / "current.json").write_text("{broken", encoding="utf-8")
        (run / "active-stage.json").write_text("{broken", encoding="utf-8")

        result = recover(self.config)

        self.assertEqual("EVAL-004", result["resume"]["unitId"])

    def test_committed_stage_is_not_resumed_from_leftover_checkpoint(self) -> None:
        initialize(self.config, "WF-20260826-120005-A1B2C3D4")
        start_stage(self.config, "analysis", "RA-002", "publish", None)
        marker = self.base / "output" / "analysis" / "analysis-manifest.json"
        marker.parent.mkdir(parents=True)
        marker.write_text("{}", encoding="utf-8")
        import hashlib
        marker_hash = hashlib.sha256(marker.read_bytes()).hexdigest()
        complete_stage(
            self.config,
            "output/analysis/analysis-manifest.json",
            marker_hash,
            "COMMITTED",
        )

        result = recover(self.config)

        self.assertIsNone(result["resume"])

    def test_new_stage_supersedes_higher_generation_completed_checkpoint(self) -> None:
        initialize(self.config, "WF-20260826-120008-A1B2C3D4")
        start_stage(self.config, "analysis", "RA-003", "extract", "SRC-001")
        update_checkpoint(self.config, "publish", "analysis-manifest", "RUNNING")
        marker = self.base / "output" / "analysis" / "analysis-manifest.json"
        marker.parent.mkdir(parents=True)
        marker.write_text("{}", encoding="utf-8")
        import hashlib
        marker_hash = hashlib.sha256(marker.read_bytes()).hexdigest()
        complete_stage(
            self.config,
            "output/analysis/analysis-manifest.json",
            marker_hash,
            "COMMITTED",
        )
        start_stage(self.config, "classification", "CC-001", "reference-refresh", "copilot")

        update_checkpoint(self.config, "copilot-assessment", "assessment.json", "RUNNING")
        result = recover(self.config)

        self.assertEqual("classification", result["resume"]["stage"])
        self.assertEqual("copilot-assessment", result["resume"]["phase"])


if __name__ == "__main__":
    unittest.main()