from __future__ import annotations

import json
import hashlib
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
GUARD = SKILL_ROOT / "scripts" / "publication-guard.ps1"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class PublicationGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if not shell:
            self.skipTest("PowerShell is unavailable")
        self.shell = shell
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run = self.root / "output" / "run-001"
        self.run.mkdir(parents=True)
        self.config = self.root / "config" / "lisa-config.json"
        self.state = self.root / "output" / "lisa-run-state.json"
        self.deployment = self.run / "build" / "agent-deployment-record.json"
        self.package = self.run / "build" / "packages" / "fixture-agent.zip"
        self.package.parent.mkdir(parents=True)
        with zipfile.ZipFile(self.package, "w") as archive:
            archive.writestr("solution.xml", "<solution />")
        write_json(
            self.config,
            {
                "basePath": "..",
                "custName": "Fixture Customer",
                "agentRegistry": {
                    "sharepoint": {
                        "siteUrl": "https://contoso.sharepoint.com/sites/agents",
                        "deployableAgentLibraryName": "Agent Library",
                        "agentArtifactLibraryName": "Agent Artifact",
                    }
                },
            },
        )
        write_json(
            self.deployment,
            {
                "agentName": "Fixture Agent",
                "agentId": "11111111-1111-1111-1111-111111111111",
                "description": {"text": "Fixture agent for publication tests."},
            },
        )
        write_json(
            self.state,
            {
                "runId": "RUN-001",
                "runFolder": "output/run-001",
                "artifacts": {
                    "agentDeploymentRecord": "output/run-001/build/agent-deployment-record.json",
                    "deployableAgent": "output/run-001/build/packages/fixture-agent.zip",
                },
            },
        )
        evidence = self.run / "evaluation" / "evidence" / "EVAL-001-attempt-01.png"
        evidence.parent.mkdir(parents=True)
        evidence.write_bytes(b"evidence")
        report = self.run / "evaluation" / "evaluation-run-report.md"
        report.write_text("# Evaluation\n", encoding="utf-8")
        self.current_package = self.create_current_lifecycle_layout()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_guard(self, *arguments: str, expected: int = 0) -> dict:
        completed = subprocess.run(
            [
                self.shell,
                "-NoProfile",
                "-File",
                str(GUARD),
                *arguments,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(
            expected,
            completed.returncode,
            completed.stderr or completed.stdout,
        )
        return json.loads(completed.stdout)

    def build_manifest(self) -> dict:
        return self.run_guard(
            "-Mode",
            "BuildManifest",
            "-ConfigPath",
            str(self.config),
        )

    def create_current_lifecycle_layout(self) -> Path:
        self.state.unlink(missing_ok=True)
        output = self.root / "output"
        build = output / "build"
        package = build / "packages" / "current-agent.zip"
        package.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("solution.xml", "<current-solution />")

        def digest(path: Path) -> str:
            return hashlib.sha256(path.read_bytes()).hexdigest()

        report = build / "agent-build-report.md"
        report.write_text("# Current build\n", encoding="utf-8")
        specification = build / "build-specification.json"
        write_json(
            specification,
            {
                "agent": {
                    "description": "Current fixture agent for lifecycle publication tests."
                }
            },
        )
        write_json(
            build / "agent-build-handoff.json",
            {
                "agent": {
                    "name": "Current Fixture Agent",
                    "agentId": "22222222-2222-2222-2222-222222222222",
                },
                "artifacts": {
                    "packages": [
                        {
                            "relativePath": "packages/current-agent.zip",
                            "sha256": digest(package),
                            "bytes": package.stat().st_size,
                        }
                    ]
                },
            },
        )
        write_json(
            build / "build-manifest.json",
            {
                "schemaVersion": "1.0",
                "stage": "build",
                "runId": "BLD-20260824-120000-ABCDEF12",
                "status": "complete",
                "agent": {
                    "name": "Current Fixture Agent",
                    "agentId": "22222222-2222-2222-2222-222222222222",
                },
                "artifacts": [
                    {
                        "relativePath": "agent-build-report.md",
                        "kind": "markdown",
                        "sha256": digest(report),
                        "bytes": report.stat().st_size,
                    },
                    {
                        "relativePath": "packages/current-agent.zip",
                        "kind": "package",
                        "sha256": digest(package),
                        "bytes": package.stat().st_size,
                    },
                ],
            },
        )

        analysis = output / "analysis"
        analysis.mkdir(parents=True)
        (analysis / "requirement-analysis_20260824_110000.md").write_text(
            "# Analysis\n", encoding="utf-8"
        )
        (analysis / "requirement-analysis_20260823_110000.md").write_text(
            "# Old analysis\n", encoding="utf-8"
        )
        classification = output / "classification"
        classification.mkdir(parents=True)
        (classification / "complexity-classification_20260824_113000.md").write_text(
            "# Classification\n", encoding="utf-8"
        )
        (classification / "complexity-classification_20260823_113000.md").write_text(
            "# Old classification\n", encoding="utf-8"
        )

        design_artifacts = output / "design" / "artifacts"
        design_artifacts.mkdir(parents=True)
        architecture = design_artifacts / "SA_Current.svg"
        architecture.write_text("<svg />", encoding="utf-8")
        write_json(
            output / "design" / "current-design.json",
            {
                "validation": "passed",
                "artifact_directory": "output/design/artifacts",
                "artifacts": {"SA_Current.svg": digest(architecture)},
            },
        )

        evaluation = output / "evaluation"
        evidence = evaluation / "evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        evaluation_report = evaluation / "evaluation-run-report.md"
        evaluation_report.write_text("# Evaluation\n", encoding="utf-8")
        screenshot = evidence / "EVAL-001-attempt-01.png"
        screenshot.write_bytes(b"current-evidence")
        write_json(
            evaluation / "evaluation-manifest.json",
            {
                "schemaVersion": "1.0",
                "stage": "evaluation",
                "runId": "EVAL-20260824-123000-ABCDEF12",
                "status": "fail",
                "artifacts": [
                    {
                        "relativePath": "evaluation-run-report.md",
                        "kind": "markdown",
                        "sha256": digest(evaluation_report),
                        "bytes": evaluation_report.stat().st_size,
                    },
                    {
                        "relativePath": "evidence/EVAL-001-attempt-01.png",
                        "kind": "image",
                        "sha256": digest(screenshot),
                        "bytes": screenshot.stat().st_size,
                    },
                ],
            },
        )

        optimization = output / "optimization"
        optimization.mkdir(parents=True)
        optimization_report = optimization / "optimization-run-report.md"
        optimization_report.write_text("# Optimization\n", encoding="utf-8")
        write_json(
            optimization / "optimization-manifest.json",
            {
                "schemaVersion": "1.0",
                "stage": "optimization",
                "runId": "OPT-20260824-130000-ABCDEF12",
                "status": "blocked",
                "artifacts": [
                    {
                        "relativePath": "optimization-run-report.md",
                        "kind": "markdown",
                        "sha256": digest(optimization_report),
                        "bytes": optimization_report.stat().st_size,
                    }
                ],
            },
        )

        final_artifacts = output / "artifacts"
        final_artifacts.mkdir(parents=True)
        (final_artifacts / "solution-document.md").write_text(
            "# Solution\n", encoding="utf-8"
        )
        (final_artifacts / "lisa-execution-tree.html").write_text(
            "<html></html>", encoding="utf-8"
        )
        hidden = output / "classification" / ".cache" / "ignore.json"
        write_json(hidden, {"ignore": True})
        return package

    def valid_inventory(self, manifest: dict) -> dict:
        agent_id = manifest["agentLibraryMetadata"]["agentId"]
        items = [
            {
                "library": entry["library"],
                "remotePath": entry["remotePath"],
                "bytes": entry["bytes"],
                "sha256": entry["sha256"],
                "agentId": (
                    agent_id
                    if entry["library"] == manifest["destinations"]["artifactLibrary"]
                    else ""
                ),
            }
            for entry in manifest["entries"]
        ]
        return {
            "executionOrder": [
                entry["remotePath"]
                for entry in sorted(
                    manifest["entries"], key=lambda item: item["uploadSequence"]
                )
            ],
            "items": items,
            "agentLibraryMetadata": {
                "agentId": agent_id,
                "agentName": manifest["agentLibraryMetadata"]["agentName"],
                "agentDescription": manifest["agentLibraryMetadata"][
                    "agentDescription"
                ],
                "customerName": manifest["agentLibraryMetadata"]["customerName"],
            },
            "artifactFolderMetadata": {"agentId": agent_id},
        }

    def verify(self, manifest: dict, inventory: dict, expected: int = 0) -> dict:
        manifest_path = self.root / "manifest.json"
        inventory_path = self.root / "inventory.json"
        write_json(manifest_path, manifest)
        write_json(inventory_path, inventory)
        return self.run_guard(
            "-Mode",
            "VerifyRemote",
            "-ManifestPath",
            str(manifest_path),
            "-RemoteInventoryPath",
            str(inventory_path),
            expected=expected,
        )

    def test_build_manifest_persists_under_publication_folder(self) -> None:
        manifest = self.build_manifest()
        persisted = self.root / "output" / "publication" / "publication-manifest.json"
        self.assertTrue(persisted.is_file())
        self.assertEqual(manifest, json.loads(persisted.read_text(encoding="utf-8-sig")))
        self.assertEqual("deployableAgent", manifest["entries"][0]["artifactKey"])
        self.assertEqual(1, manifest["entries"][0]["uploadSequence"])
        self.assertEqual(1, manifest["expected"]["categoryCounts"]["deployablePackage"])
        self.assertEqual(1, manifest["expected"]["categoryCounts"]["evaluationEvidence"])
        self.assertGreater(manifest["expected"]["categoryCounts"]["declaredArtifact"], 0)
        self.assertTrue(
            all(len(entry["sha256"]) == 64 for entry in manifest["entries"])
        )
        self.assertFalse(
            any(
                "/publication/" in entry["localPath"].replace("\\", "/")
                for entry in manifest["entries"]
            )
        )

    def test_manifest_rerun_is_deterministic_and_excludes_publication_files(self) -> None:
        first = self.build_manifest()
        second = self.build_manifest()
        self.assertEqual(first, second)
        self.assertFalse(
            any(
                entry["remotePath"].endswith("publication-manifest.json")
                or entry["remotePath"].endswith("publication-record.json")
                for entry in second["entries"]
            )
        )

    def test_lisa_run_state_is_ignored(self) -> None:
        first = self.build_manifest()
        write_json(
            self.state,
            {
                "runId": "LEGACY",
                "runFolder": str(self.run.resolve()),
                "artifacts": {"deployableAgent": "missing.zip"},
            },
        )
        second = self.build_manifest()
        self.assertEqual(first, second)
        self.assertEqual(
            str(self.current_package.resolve()), second["entries"][0]["localPath"]
        )

    def test_remote_verification_passes_with_matching_inventory_and_metadata(self) -> None:
        manifest = self.build_manifest()
        result = self.verify(manifest, self.valid_inventory(manifest))
        self.assertTrue(result["passed"])
        self.assertEqual(
            manifest["expected"]["totalCount"], result["verifiedCount"]
        )
        self.assertTrue(result["agentLibraryMetadataVerified"])
        self.assertTrue(result["artifactFolderAgentIdVerified"])
        self.assertEqual([], result["artifactItemAgentIdMismatches"])

    def test_remote_verification_rejects_metadata_mismatch(self) -> None:
        manifest = self.build_manifest()
        inventory = self.valid_inventory(manifest)
        inventory["artifactFolderMetadata"]["agentId"] = "wrong"
        artifact_item = next(
            item
            for item in inventory["items"]
            if item["library"] == manifest["destinations"]["artifactLibrary"]
        )
        artifact_item["agentId"] = "wrong"
        result = self.verify(manifest, inventory, expected=2)
        self.assertFalse(result["passed"])
        self.assertFalse(result["artifactFolderAgentIdVerified"])
        self.assertIn(
            artifact_item["remotePath"], result["artifactItemAgentIdMismatches"]
        )

    def test_remote_verification_rejects_missing_hash_and_extra_files(self) -> None:
        manifest = self.build_manifest()
        inventory = self.valid_inventory(manifest)
        missing = inventory["items"].pop(1)
        inventory["items"][0]["sha256"] = "0" * 64
        inventory["items"].append(
            {
                "library": manifest["destinations"]["artifactLibrary"],
                "remotePath": (
                    manifest["destinations"]["artifactAgentFolder"] + "/unexpected.txt"
                ),
                "bytes": 1,
                "sha256": "",
                "agentId": manifest["agentLibraryMetadata"]["agentId"],
            }
        )
        result = self.verify(manifest, inventory, expected=2)
        self.assertFalse(result["passed"])
        self.assertIn(missing["remotePath"], result["missing"])
        self.assertTrue(result["hashMismatch"])
        self.assertIn(
            manifest["destinations"]["artifactAgentFolder"] + "/unexpected.txt",
            result["extraArtifactFiles"],
        )

    def test_current_lifecycle_layout_resolves_package_and_manifest_artifacts(self) -> None:
        manifest = self.build_manifest()
        self.assertEqual(manifest, self.build_manifest())
        self.assertEqual("lifecycle-manifests", manifest["discoveryMode"])
        self.assertEqual(
            str(self.current_package.resolve()), manifest["entries"][0]["localPath"]
        )
        self.assertEqual("deployableAgent", manifest["entries"][0]["artifactKey"])
        remote_paths = [entry["remotePath"] for entry in manifest["entries"]]
        self.assertTrue(
            any(path.endswith("/artifacts/solution-document.md") for path in remote_paths)
        )
        self.assertTrue(
            any(
                entry["artifactCategory"] == "evaluationEvidence"
                and entry["remotePath"].endswith(
                    "/evaluation/evidence/EVAL-001-attempt-01.png"
                )
                for entry in manifest["entries"]
            )
        )
        self.assertFalse(any("run-001" in path for path in remote_paths))
        self.assertFalse(any("20260823" in path for path in remote_paths))
        self.assertFalse(any("/.cache/" in path for path in remote_paths))
        self.assertFalse(any("/publication/" in path for path in remote_paths))

    def test_current_lifecycle_layout_rejects_tampered_package(self) -> None:
        self.current_package.write_bytes(b"tampered")
        result = self.run_guard(
            "-Mode",
            "BuildManifest",
            "-ConfigPath",
            str(self.config),
            expected=1,
        )
        self.assertFalse(result["passed"])
        self.assertIn("byte size does not match", result["error"])


if __name__ == "__main__":
    unittest.main()
