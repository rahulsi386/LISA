"""Regression tests for the solution-blueprint validator and schema (unittest, offline)."""
import copy
import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import validate_blueprint as vb  # noqa: E402

FIXTURES = sorted((HERE / "fixtures").glob("*-blueprint.html"))


def _with_data(html: str, data: dict) -> str:
    block = json.dumps(data, indent=2).replace("</", "<\\/")
    return vb.DATA_BLOCK.sub(
        lambda m: m.group(0).replace(m.group(1), "\n" + block + "\n"), html, count=1
    )


class SchemaFileTests(unittest.TestCase):
    def test_schema_is_valid_json_with_defs(self):
        schema = vb.load_schema()
        self.assertEqual(schema["type"], "object")
        self.assertEqual(len(schema["$defs"]["routeName"]["enum"]), 7)

    def test_route_enum_matches_validator(self):
        self.assertEqual(vb.load_schema()["$defs"]["routeName"]["enum"], vb.ROUTES)


class FixtureTests(unittest.TestCase):
    def test_fixtures_present(self):
        self.assertGreaterEqual(len(FIXTURES), 3)

    def test_fixtures_are_valid(self):
        for path in FIXTURES:
            with self.subTest(fixture=path.name):
                self.assertEqual(vb.validate_file(path), [])


class NegativeTests(unittest.TestCase):
    def setUp(self):
        self.html = FIXTURES[0].read_text(encoding="utf-8")
        self.data = vb.extract_data(self.html)

    def _errors(self, mutate):
        data = copy.deepcopy(self.data)
        mutate(data)
        return vb.validate_html(_with_data(self.html, data))

    def test_missing_route_is_rejected(self):
        errs = self._errors(lambda d: d["routes"].pop())
        self.assertTrue(any("routes" in e for e in errs), errs)

    def test_wrong_total_is_rejected(self):
        def mutate(d):
            d["routes"][0]["total"] = d["routes"][0]["total"] - 1
        self.assertTrue(any("sum of scores" in e for e in self._errors(mutate)))

    def test_score_out_of_range_is_rejected(self):
        def mutate(d):
            d["routes"][0]["scores"]["fit"] = 6
        self.assertTrue(self._errors(mutate))

    def test_bad_status_is_rejected(self):
        self.assertTrue(self._errors(lambda d: d.update(status="Done")))

    def test_bad_date_is_rejected(self):
        self.assertTrue(self._errors(lambda d: d.update(lastUpdated="7 Oct 2026")))

    def test_failed_gate_cannot_be_primary(self):
        def mutate(d):
            name = next(n for n in vb.ROUTES if n in d["recommendedRoute"])
            for r in d["routes"]:
                if r["name"] == name:
                    r["gate"] = "Fail"
            for g in d.get("gates", []):
                g.get("results", {}).pop(name, None)
        self.assertTrue(any("gates beat scores" in e for e in self._errors(mutate)))

    def test_unknown_requirement_id_is_rejected(self):
        def mutate(d):
            d["components"][0]["requirementIds"] = ["ZZ-99"]
        self.assertTrue(any("ZZ-99" in e for e in self._errors(mutate)))

    def test_standalone_must_not_mention_lisa(self):
        html = self.html.replace("<h2>Executive Summary</h2>", "<h2>Executive Summary</h2><p>Built by LISA</p>", 1)
        self.assertTrue(any("LISA" in e for e in vb.validate_html(html)))

    def test_lisa_mode_requires_hashes(self):
        def mutate(d):
            d["mode"] = "lisa"
            d["sourceArtifacts"] = [{"path": "output/classification/x.json", "sha256": "", "role": "classification"}]
        self.assertTrue(any("sha256" in e for e in self._errors(mutate)))

    def test_missing_data_block_is_an_error(self):
        with self.assertRaises(vb.BlueprintError):
            vb.extract_data("<html><body>No data</body></html>")


if __name__ == "__main__":
    unittest.main()
