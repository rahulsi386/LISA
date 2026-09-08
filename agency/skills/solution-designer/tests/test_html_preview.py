from __future__ import annotations

import json
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PreviewParser(HTMLParser):
    def __init__(self, source: str):
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.feed(source)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag, dict(attrs)))

    def resources(self) -> set[str]:
        return {
            value for _, attrs in self.elements
            for key, value in attrs.items()
            if key in {"href", "src"} and value and not value.startswith("#")
        }


class HtmlPreviewTests(unittest.TestCase):
    def render(self, model: dict) -> str:
        result = subprocess.run(
            ["node", "-e", "const {createPreview}=require('./preview');"
             f"process.stdout.write(createPreview({json.dumps(model)}));"],
            cwd=ROOT / "renderer", capture_output=True, text=True, encoding="utf-8",
            timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def model(self) -> dict:
        return {
            "scenarioSlug": "Procurement_Test", "title": "Procurement",
            "summary": "Grounded guidance and controlled actions.", "complexity": "High",
            "coverage": {"nativeBuildPercent": 70, "pocDemonstrationPercent": 90},
        }

    def test_preview_has_two_images_four_portable_files_and_no_scripts(self):
        html = self.render(self.model())
        parsed = PreviewParser(html)
        self.assertEqual(parsed.resources(), {
            f"{kind}_Procurement_Test.{extension}"
            for kind in ("SA", "SD") for extension in ("svg", "png")
        })
        images = [attrs for tag, attrs in parsed.elements if tag == "img"]
        self.assertEqual([image["src"] for image in images], [
            "SA_Procurement_Test.png", "SD_Procurement_Test.png",
        ])
        self.assertTrue(all(image.get("alt") for image in images))
        self.assertFalse(any(tag in {"script", "iframe", "object", "base"} for tag, _ in parsed.elements))
        self.assertIn("default-src 'none'", html)
        self.assertEqual(html, self.render(self.model()))

    def test_model_text_is_escaped_in_text_and_image_attributes(self):
        model = self.model()
        model["title"] = 'Buying <script>alert("x")</script> & "quotes" \u00e9'
        model["summary"] = '<img src="https://example.invalid/x" onerror="alert(1)">'
        html = self.render(model)
        parsed = PreviewParser(html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;", html)
        self.assertIn("\u00e9", html)
        self.assertEqual(sum(tag == "img" for tag, _ in parsed.elements), 2)
        self.assertFalse(any(tag == "script" for tag, _ in parsed.elements))
        self.assertFalse(any(key.startswith("on") for _, attrs in parsed.elements for key in attrs))
        self.assertTrue(all(not value.startswith("http") for value in parsed.resources()))
        self.assertEqual(
            next(attrs["alt"] for tag, attrs in parsed.elements if tag == "img"),
            model["title"] + " - Solution architecture",
        )

    def test_view_controls_are_independent_and_accessible_without_javascript(self):
        parsed = PreviewParser(self.render(self.model()))
        checkboxes = [attrs for tag, attrs in parsed.elements if tag == "input"]
        labels = [attrs.get("for") for tag, attrs in parsed.elements if tag == "label"]
        self.assertEqual({box["id"] for box in checkboxes}, {"architecture-native", "sequence-native"})
        self.assertEqual({box["id"] for box in checkboxes}, set(labels))
        self.assertTrue(all(box["type"] == "checkbox" for box in checkboxes))
        regions = [attrs for _, attrs in parsed.elements if attrs.get("class") == "viewport"]
        self.assertEqual(len(regions), 2)
        self.assertTrue(all(region.get("tabindex") == "0" and region.get("aria-label") for region in regions))

    def test_unsafe_scenario_filenames_are_rejected(self):
        result = subprocess.run(
            ["node", "-e", "const {createPreview}=require('./preview');"
             "const invalid=['../escape','bad/name','bad\\\\name','x\\\" onclick=\\\"x'];"
             "console.log(JSON.stringify(invalid.map(scenarioSlug=>{"
             "try {createPreview({scenarioSlug});return false;} catch(error) {"
             "return error.message==='Invalid preview scenario slug';}})));"],
            cwd=ROOT / "renderer", capture_output=True, text=True, timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(all(json.loads(result.stdout)))


if __name__ == "__main__":
    unittest.main()
