from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from build import OUTPUT


def setUpModule():
    global ROOT, classifier
    unittest.enterModuleContext(mock.patch.dict(sys.modules))
    unittest.enterModuleContext(mock.patch.object(sys, "path", sys.path.copy()))
    temp = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(temp.cleanup)
    with zipfile.ZipFile(OUTPUT) as release:
        release.extractall(temp.name)
    ROOT = Path(temp.name) / "skills" / "lisa-complexity-classifier"
    spec = importlib.util.spec_from_file_location("cowork_classifier", ROOT / "scripts" / "complexity_classifier.py")
    classifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(classifier)


class ConnectorTests(unittest.TestCase):
    def ingest(self, root, expected=0):
        run = subprocess.run([sys.executable, "-B", classifier.__file__, "ingest-references", "--run", str(root)],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, expected, run.stderr or run.stdout)
        return json.loads(run.stderr if expected else run.stdout)

    def test_connector_pages_block_on_missing_empty_stale_or_changed_content(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(classifier.urllib.request, "urlopen") as net:
            root = Path(directory)
            pages = root / "references"
            pages.mkdir()
            refs = json.loads(classifier.REFERENCE_MANIFEST_PATH.read_bytes())["references"]
            first, second = refs[:2]
            page = pages / (first["id"] + ".md")
            other = pages / (second["id"] + ".md")
            other.write_bytes(b" \n")
            failed = self.ingest(root, expected=2)
            self.assertIn(first["id"] + ": missing page", failed["error"])
            self.assertIn(second["id"] + ": empty page", failed["error"])
            for ref in refs:
                (pages / (ref["id"] + ".md")).write_bytes(b"# Saved page")
            old = (datetime.now() - timedelta(days=2)).timestamp()
            os.utime(page, (old, old))
            self.ingest(root)
            other.write_bytes(b"# Different page")
            with self.assertRaises(classifier.ClassifierError) as blocked:
                classifier._refresh_references(root / "http-cache", "2026-09-08", False, "copilot", root)
            self.assertIn(first["id"] + ": Fetch and ingest connector page again: saved page is outside", str(blocked.exception))
            self.assertIn(second["id"] + ": Fetch and ingest connector page again: page or manifest changed", str(blocked.exception))
            page.write_bytes(b"# Refetched")
            (pages / "foundry-agent-service.md").unlink()
            self.ingest(root)
            active = classifier._refresh_references(root / "http-cache", "2026-09-08", False, "copilot", root)
            self.assertTrue(all(r["status"] == "connector-retrieved" for r in active))
            with self.assertRaisesRegex(classifier.ClassifierError, "foundry-agent-service:.*missing page"):
                classifier._refresh_references(root / "http-cache", "2026-09-08", False, "foundry", root)
            net.assert_not_called()

    def test_direct_download_preserves_http_provenance(self):
        ref = json.loads(classifier.REFERENCE_MANIFEST_PATH.read_bytes())["references"][0]
        payload = b"<p>Fixture</p>"
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(classifier.urllib.request, "urlopen") as http:
            response = http.return_value.__enter__.return_value
            response.headers.get_content_charset.return_value = "utf-8"
            response.headers.get.side_effect = {"ETag": '"version"'}.get
            response.read.return_value = payload
            result = classifier._refresh_reference(ref, Path(directory), "2026-09-08", False, 24, False)
            self.assertEqual(("retrieved", '"version"', hashlib.sha256(payload).hexdigest(), "Fixture"),
                             (result["status"], result["etag"], result["content_sha256"], result["excerpt"]))
            self.assertNotEqual("ms-learn-mcp", result.get("source"))

    def test_direct_fallback_stops_queued_requests_when_network_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            classifier.urllib.request, "urlopen", side_effect=TimeoutError,
        ) as network:
            with self.assertRaisesRegex(classifier.ClassifierError, "Required Microsoft references"):
                classifier._refresh_references(Path(directory), "2026-09-08", False, "copilot")
            self.assertGreater(network.call_count, 0)
            self.assertLessEqual(network.call_count, 8)
            self.assertTrue(all(call.kwargs["timeout"] <= 2 for call in network.call_args_list))


class DesignHandoffTests(unittest.TestCase):
    def topology(self):
        return {
            "components": [
                {"id": "channel", "category": "channel"},
                {"id": "agent", "category": "agent"},
            ],
            "relationships": [{
                "id": "rel-route", "source_id": "channel", "target_id": "agent",
                "relationship_type": "invokes", "direction": "unidirectional",
                "interaction": "Route prompt", "implementation_mode": "real",
            }],
            "sequence_flows": [{
                "id": "seq-route", "source_id": "channel", "target_id": "agent",
                "message_type": "call", "relationship_id": "rel-route",
                "implementation_mode": "real",
            }],
            "presentation": {"primary_agent_id": "agent", "primary_path": ["channel", "agent"]},
        }

    def test_matching_modes_and_existing_path_pass(self):
        classifier._validate_design_handoff(self.topology())

    def test_legacy_contract_remains_accepted(self):
        topology = self.topology()
        topology.pop("presentation")
        topology["sequence_flows"][0].pop("relationship_id")
        topology["sequence_flows"][0].pop("implementation_mode")
        topology["relationships"][0].pop("implementation_mode")
        classifier._validate_design_handoff(topology)

    def test_invented_primary_path_and_nonagent_fail(self):
        for presentation in (
            {"primary_path": ["agent", "channel"]},
            {"primary_path": ["unknown"]},
            {"primary_agent_id": "channel"},
        ):
            with self.subTest(presentation=presentation):
                topology = self.topology()
                topology["presentation"] = presentation
                with self.assertRaises(classifier.ClassifierError):
                    classifier._validate_design_handoff(topology)

    def test_conflicting_mode_and_wrong_relationship_fail(self):
        for change in (
            {"implementation_mode": "simulated"},
            {"relationship_id": "rel-missing"},
            {"source_id": "agent", "target_id": "channel"},
        ):
            with self.subTest(change=change):
                topology = self.topology()
                topology["sequence_flows"][0].update(change)
                with self.assertRaises(classifier.ClassifierError):
                    classifier._validate_design_handoff(topology)

    def test_duplicate_interaction_fails_but_distinct_multiedges_survive(self):
        topology = self.topology()
        duplicate = copy.deepcopy(topology["relationships"][0])
        duplicate["id"] = "rel-duplicate"
        topology["relationships"].append(duplicate)
        with self.assertRaisesRegex(classifier.ClassifierError, "Duplicate"):
            classifier._validate_design_handoff(topology)
        duplicate["relationship_type"] = "publishes-to"
        duplicate["interaction"] = "Publish agent"
        classifier._validate_design_handoff(topology)

    def test_different_protocols_do_not_get_deduplicated(self):
        topology = self.topology()
        duplicate = copy.deepcopy(topology["relationships"][0])
        duplicate.update(id="rel-async", protocol="Managed event", synchronous=False)
        topology["relationships"][0].update(protocol="HTTPS", synchronous=True)
        topology["relationships"].append(duplicate)
        classifier._validate_design_handoff(topology)

    def test_schema_accepts_explicit_modes_and_presentation(self):
        schema = json.loads((ROOT / "resources" / "classification-model.schema.json").read_text())
        presentation = {"$defs": schema["$defs"], "$ref": "#/$defs/presentation"}
        classifier.validate_schema(presentation, self.topology()["presentation"], "presentation", classifier.ClassifierError)
        with self.assertRaisesRegex(classifier.ClassifierError, "primary_path"):
            classifier.validate_schema(presentation, {"primary_path": ["agent", "agent"]}, "presentation", classifier.ClassifierError)

    def test_unknown_capability_reference_is_not_silently_ignored(self):
        topology = self.topology()
        topology["sequence_flows"][0]["capability_id"] = "CAP-999"
        with self.assertRaisesRegex(classifier.ClassifierError, "unknown capability"):
            classifier._validate_design_handoff(topology, {"CAP-001"})


if __name__ == "__main__":
    unittest.main()
