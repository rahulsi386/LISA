import hashlib
import io
import json
import runpy
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from jsonschema import ValidationError
from PIL import Image

from build import OUTPUT, PROJECT, SOURCE, build, declared_skills, validate_companions


class LisaPackageTests(unittest.TestCase):
    def test_diagnostic_is_only_in_private_build(self):
        with self.assertRaisesRegex(ValueError, "dist/"):
            build(OUTPUT, runtime_check=True)
        with tempfile.TemporaryDirectory() as directory:
            with zipfile.ZipFile(build(Path(directory) / "dev.zip", runtime_check=True)) as dev:
                folder = "./skills/lisa-runtime-check"
                self.assertIn({"folder": folder}, json.loads(dev.read("manifest.json"))["agentSkills"])
                self.assertIn(folder[2:] + "/SKILL.md", dev.namelist())

    def test_manifest_and_entry_points_must_agree(self):
        manifest = json.loads((PROJECT / "manifest.json").read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for entry in manifest["agentSkills"]:
                name = entry["folder"].split("/")[-1]
                (root / name).mkdir()
                (root / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
            path = root / "lisa-unreleased" / "SKILL.md"
            path.parent.mkdir()
            path.touch()
            with self.assertRaisesRegex(ValueError, "undeclared entry points.*lisa-unreleased"):
                declared_skills(manifest, root)
            path.unlink()
            skill = root / "lisa-complexity-classifier" / "SKILL.md"
            skill.write_text("---\nname: wrong-name\n---\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frontmatter name"):
                declared_skills(manifest, root)
            skill.unlink()
            with self.assertRaisesRegex(ValueError, "Missing entry points.*lisa-complexity-classifier"):
                declared_skills(manifest, root)

    def test_schema_identity_and_unsafe_declarations_fail(self):
        manifest = json.loads((PROJECT / "manifest.json").read_bytes())
        for overrides, error in (
            ({"unexpectedField": True}, ValidationError),
            ({"manifestVersion": "1.28"}, (ValidationError, ValueError)),
            ({"id": "a86010dd-484d-4cdf-bb81-4b097d78da27"}, ValueError),
            ({"agentSkills": [{"folder": "./skills/../other"}]}, ValueError),
            ({"agentSkills": [manifest["agentSkills"][0]] * 2}, ValueError),
        ):
            with self.subTest(overrides=overrides), self.assertRaises(error):
                declared_skills(manifest | overrides, PROJECT / "skills")

    def test_companion_boundaries(self):
        validate_companions("test", {f"scripts/{i}.py": b"" for i in range(20)})
        full = b"x" * 5_000_000
        validate_companions("test", {"a": full, "b": full})
        for files in ({f"{i}.txt": b"" for i in range(21)}, {"big": full + b"x"},
                      {"a": full, "b": full, "c": b"x"}, {"../escape": b""},
                      {"scripts/.hidden": b""}, {"scripts/AUX.py": b""}):
            with self.assertRaises(ValueError):
                validate_companions("test", files)

    def test_package_and_analysis_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with zipfile.ZipFile(build(root / "lisa.zip")) as archive, zipfile.ZipFile(OUTPUT) as released:
                self.assertEqual(archive.namelist(), released.namelist(), "Rebuild dist/lisa.zip")
                for path in archive.namelist():
                    if path.endswith(".png"):
                        with Image.open(io.BytesIO(archive.read(path))) as a, Image.open(io.BytesIO(released.read(path))) as b:
                            self.assertEqual((a.size, a.mode, a.tobytes()), (b.size, b.mode, b.tobytes()), path)
                    else:
                        self.assertEqual(archive.read(path), released.read(path), path)
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual({p.split("/")[1] for p in archive.namelist() if p.startswith("skills/")},
                                 {"lisa-requirement-analyzer", "lisa-complexity-classifier"})
                connector, = manifest["agentConnectors"]
                self.assertEqual(connector["id"], "ms-learn-mcp")
                self.assertEqual(connector["toolSource"]["remoteMcpServer"], {
                    "mcpServerUrl": "https://learn.microsoft.com/api/mcp", "authorization": {"type": "None"},
                })
                for key, size in (("color", 192), ("outline", 32)):
                    with Image.open(io.BytesIO(archive.read(manifest["icons"][key]))) as icon:
                        self.assertEqual((size, size), icon.size)
                for entry in manifest["agentSkills"]:
                    folder = entry["folder"].removeprefix("./")
                    instructions = archive.read(folder + "/SKILL.md").decode()
                    self.assertIn(f"name: {folder.split('/')[-1]}", instructions.splitlines())
                self.assertFalse(any("/tests/" in p or p.endswith(".ps1") for p in archive.namelist()))
                archive.extractall(root / "app")

            project = root / "OneDrive project"
            requirements = project / "requirements"
            requirements.mkdir(parents=True)
            (requirements / "brief.txt").write_text(
                "Users need conversational answers grounded in policy.\nRun a scheduled compliance check.\n",
                encoding="utf-8")
            config = project / "lisa-config.json"
            config.write_text('{"basePath":"."}', encoding="utf-8")
            skills = root / "app" / "skills"

            def cli(skill, *args, stdin=None, expected=0):
                script = skills / f"lisa-{skill}" / "scripts" / (skill.replace("-", "_") + ".py")
                # Neither site-packages nor runner HTTP access is needed for this handoff.
                command = [sys.executable, "-E", "-P", "-B", "-S", "-c", """
import runpy, sys
def offline(event, args):
    if event == 'urllib.Request':
        raise SystemExit('Unexpected direct download')
sys.addaudithook(offline)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""]
                result = subprocess.run([*command, str(script), *map(str, args)], cwd=project,
                                        input=stdin, capture_output=True, timeout=120)
                self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
                return json.loads(result.stderr if expected else result.stdout)

            when = "2026-11-23T09:00:00+05:30"
            prepared = cli("requirement-analyzer", "prepare", "--config", config, "--local-time", when)
            run = json.loads(Path(prepared["run"]).read_bytes())
            inventory = json.loads(Path(prepared["manifest"]).read_bytes())
            # Only the test's model-authored input comes from the canonical fixture helper.
            fixture = SOURCE / "requirement-analyzer" / "tests" / "test_requirement_analyzer.py"
            ledger = runpy.run_path(str(fixture))["RequirementAnalyzerTests"].make_draft_ledger(run, inventory)
            scheduled = next(f for f in ledger["findings"] if f["kind"] == "Observed fact")
            scheduled.update(kind="Explicit requirement", status="Confirmed", confidence="Confirmed",
                             statement="Run a scheduled compliance check.",
                             evidence=[{"source_id": inventory["sources"][0]["source_id"],
                                        "locator": "line 2", "evidence_type": "explicit"}])
            autonomous = next(b for b in ledger["agentic_behaviors"] if b["behavior"] == "Autonomous")
            ledger["findings"] = [f for f in ledger["findings"] if f["finding_id"] not in autonomous["finding_ids"]]
            autonomous.update(finding_ids=[scheduled["finding_id"]], requirement_status="Confirmed",
                              evidenced_behavior=scheduled["statement"],
                              trigger_decision_handoff="Schedule", gaps="None evidenced")
            draft = Path(run["run_directory"]) / "completed.json"
            draft.write_text(json.dumps(ledger), encoding="utf-8")
            cli("requirement-analyzer", "publish", "--run", prepared["run"], "--ledger", draft)
            reservation = cli("complexity-classifier", "init-references", "--config", config, "--local-time", when)
            run_dir = Path(reservation["run_directory"])
            refs = json.loads(Path(reservation["reference_manifest"]).read_bytes())["references"]
            markdown = "# Synthetic Learn page\r\n\r\nNon-ASCII: \u00e9. " + "x" * 2100
            first = refs[0]["id"]
            save = ("complexity-classifier", "save-reference", "--run", run_dir, "--id")
            for invalid in (b" \r\n", b"\xff", b'{"isError":true,"content":[{"type":"text","text":"Not found"}]}'):
                self.assertIn(first, cli(*save, first, "--stdin", stdin=invalid, expected=2)["error"])
                self.assertEqual([], list((run_dir / "references").iterdir()))
            receipt = cli(*save, first, "--stdin", stdin=markdown.encode())
            self.assertEqual({"status": "saved", "id": first, "bytes": len(markdown.encode()),
                              "sha256": hashlib.sha256(markdown.encode()).hexdigest()}, receipt)
            self.assertEqual("saved", cli(*save, first, "--stdin", stdin=markdown.encode())["status"])
            self.assertIn("refusing to overwrite", cli(*save, first, "--stdin", stdin=b"# Other", expected=2)["error"])
            self.assertEqual(markdown.encode(), (run_dir / "references" / (first + ".md")).read_bytes())
            exported = root / "synthetic-export.md"
            exported.write_bytes(markdown.encode())
            for ref in refs[1:]:
                cli(*save, ref["id"], "--source-file", exported)
            ingested = cli("complexity-classifier", "ingest-references", "--run", run_dir)
            self.assertEqual(len(refs), ingested["retrieved"])
            classified = cli("complexity-classifier", "prepare", "--config", config, "--run", run_dir)
            self.assertEqual(run_dir, Path(classified["run"]).parent)
            active = json.loads(Path(classified["references"]).read_bytes())
            self.assertNotIn("foundry-agent-service", {r["id"] for r in active})
            self.assertTrue(all(r["excerpt"] == markdown[:2000] for r in active))
            model = json.loads(Path(classified["model_draft"]).read_bytes())
            unavailable = {row["server"] for row in model["research_register"]["mcp_usage"]
                           if row["status"] == "unavailable"}
            self.assertEqual({"azure-mcp", "ms-icm-mcp", "ms-eng-hub-mcp"}, unavailable)
            # Supply synthetic model-authored content, not live connector evidence.
            fixture = SOURCE / "complexity-classifier" / "tests" / "test_complexity_classifier.py"
            completed = runpy.run_path(str(fixture))["ComplexityClassifierTests"].model(model["run_id"])
            published_ledger = json.loads(next((project / "output" / "analysis").glob(
                "requirement-analysis_*.md")).with_suffix(".json").read_bytes())
            ids = {f["statement"]: f["finding_id"] for f in published_ledger["findings"]}
            completed = json.loads(json.dumps(completed)
                                   .replace("REQ-AAAA000001", ids["Users interact with the assistant through conversation."])
                                   .replace("REQ-BBBB000002", ids[scheduled["statement"]])
                                   .replace("GAP-CCCC000003", ids["No permitted agent-development platform is evidenced."]))
            register = completed["research_register"]
            register["mcp_usage"] = model["research_register"]["mcp_usage"]
            register["sources"] = [s for s in register["sources"] if s["source_type"] == "ms-learn-mcp"]
            completed["research_plan"] = [
                topic | {"status": "resolved", "source_ids": ["RS-001"],
                         "resolution": "Synthetic Learn evidence covers the documented capability for this fixture."}
                for topic in model["research_plan"]
            ]
            model_path = Path(classified["model_draft"]).with_name("completed-model.json")
            model_path.write_text(json.dumps(completed), encoding="utf-8")
            result = cli("complexity-classifier", "publish", "--run", classified["run"], "--model", model_path)
            output = project.resolve() / "output" / "classification"
            self.assertEqual(output, Path(result["markdown"]).parent)
            self.assertTrue(Path(result["markdown"]).is_file())
            self.assertEqual(output, Path(result["json"]).parent)
            final = json.loads(Path(result["json"]).read_bytes())
            for ref in final["reference_sources"]:
                self.assertEqual(("connector-retrieved", "ms-learn-mcp", hashlib.sha256(markdown.encode()).hexdigest()),
                                 (ref["status"], ref["source"], ref["content_sha256"]))
                self.assertNotIn("etag", ref)
                self.assertNotIn("last_modified", ref)
            self.assertEqual(unavailable, {r["server"] for r in final["research_register"]["mcp_usage"]
                                           if r["status"] == "unavailable"})
            self.assertEqual("validated", json.loads((output / "classification-manifest.json").read_bytes())["status"])


if __name__ == "__main__":
    unittest.main()
