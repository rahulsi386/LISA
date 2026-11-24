"""Validate and build the Lisa plugin from the skills declared in its manifest."""

import argparse
import io
import json
import re
import tempfile
import zipfile
from pathlib import Path

from jsonschema import Draft4Validator
from PIL import Image, ImageOps

PROJECT = Path(__file__).resolve().parent
REPO = PROJECT.parent.parent
SOURCE = PROJECT.parent / "skills"
OUTPUT = PROJECT / "dist" / "lisa.zip"
APP_ID = "dfc936a2-aef5-4f05-834b-5f62f9d39f3c"
SCHEMA_URL = "https://developer.microsoft.com/json-schemas/teams/v1.29/MicrosoftTeams.schema.json"
HELPERS = (
    "analysis_handoff.py", "lisa_path_resolver.py", "review_batches.py",
    "validate_artifact_contracts.py", "artifact-contract.schema.json",
    "design_validation.py", "design-validator.cjs",
)
RESOURCES = {
    "requirement-analyzer": (
        "artifact-contract.json", "controlled-vocabulary.json", "evidence-ledger.schema.json",
        "requirement-analysis.template.md",
    ),
    "complexity-classifier": (
        "artifact-contract.json", "classification-manifest.schema.json",
        "classification-model.schema.json", "classification-output.schema.json",
        "classification-rules.json", "classification.template.md", "completion-contract.json",
        "design-guidance.md", "reference-manifest.json", "research-assessment.schema.json",
    ),
}


def text_bytes(path):
    # Don't let checkout line endings change a skill's content or fingerprints.
    return path.read_text(encoding="utf-8").encode("utf-8")


def declared_skills(manifest, entry_root, *, dev_probe=None):
    schema = json.loads((PROJECT / "MicrosoftTeams-v1.29.schema.json").read_bytes())
    Draft4Validator(schema).validate(manifest)
    if manifest.get("$schema") != SCHEMA_URL or manifest["manifestVersion"] != "1.29":
        raise ValueError("The Lisa manifest must use the pinned Teams 1.29 schema")
    if manifest["id"] != APP_ID or manifest["name"]["short"] != "Lisa":
        raise ValueError("The Lisa app ID and short name must not change")

    names = []
    for entry in manifest.get("agentSkills", []):
        match = re.fullmatch(r"\./skills/(lisa-[a-z0-9]+(?:-[a-z0-9]+)*)", entry["folder"])
        if not match:
            raise ValueError(f"Invalid skill folder: {entry['folder']}")
        names.append(match[1])
    if not names or len(set(names)) != len(names):
        raise ValueError("Expected nonempty, unique agentSkills")
    entries = {path.parent.relative_to(entry_root).as_posix(): path for path in entry_root.rglob("SKILL.md")}
    if dev_probe is not None:
        entries["lisa-runtime-check"] = dev_probe
    present = set(entries)
    if set(names) != present:
        raise ValueError(f"Missing entry points: {sorted(set(names) - present)}; "
                         f"undeclared entry points: {sorted(present - set(names))}")
    for name in names:
        body = entries[name].read_text(encoding="utf-8")
        header = re.match(r"\A---\n(.*?)\n---(?:\n|$)", body, flags=re.S)
        if not header or re.findall(r"^name: (.+)$", header[1], flags=re.M) != [name]:
            raise ValueError(f"SKILL.md frontmatter name must match folder: {name}")
        if re.search(r"\.\.[/\\]", body):
            raise ValueError(f"Parent path in {name}/SKILL.md")
    return names


def portable_markdown(text, skill):
    """Keep the shared workflow; replace CLI paths and invocation conventions."""
    script = skill.replace("-", "_") + ".py"
    text = text.replace("\\", "/")
    text = text.replace("../../Platform-Decision.md", "resources/Platform-Decision.md")
    text = text.replace("../Platform-Decision.md", "resources/Platform-Decision.md")
    text = text.replace("../SKILL.md", "SKILL.md")
    text = re.sub(r'& "<skill-dir>/scripts/Invoke-[\w-]+\.ps1"', f"python scripts/{script}", text)
    text = re.sub(r' ?`\n +(?=--)', " ", text)
    return text.replace('>"`\n', '>"\n').replace("```powershell", "```sh")


def shared_workflow(skill):
    source = (SOURCE / skill / "SKILL.md").read_text(encoding="utf-8")
    _, body = source.split("\n---\n", 1)
    body = re.sub(r"(?m)^When invoked by `cad-orchestrator`,[^\n]*(?:\n[^\n]+)*\n", "", body)
    body = re.sub(r"(?ms)^## Packaged resources\n.*?(?=^## )", "", body)
    if skill == "complexity-classifier":
        start = body.index("Use all\nMCP servers")
        end = body.index("Non-Microsoft products", start)
        body = body[:start] + "Use the connector policy in `SKILL.md` for `mcp_usage`.\n\n" + body[end:]
    body = portable_markdown(body.strip(), skill)
    if any(item in body for item in ("../", ".ps1", "cad-orchestrator")):
        raise ValueError(f"Review the Cowork workflow adaptation for {skill}")
    return body


def skill_files(skill):
    if skill not in RESOURCES:
        raise ValueError(f"No packaging rules for {skill}")
    root = SOURCE / skill
    script = skill.replace("-", "_") + ".py"
    files = {"SKILL.md": text_bytes(PROJECT / "skills" / f"lisa-{skill}" / "SKILL.md"),
             "references/workflow.md": shared_workflow(skill).encode(),
             f"scripts/{script}": text_bytes(root / "scripts" / script)}
    for name in HELPERS:
        files[f"scripts/{name}"] = text_bytes(SOURCE / name)
    for name in RESOURCES[skill]:
        file = root / "resources" / name
        files[f"resources/{name}"] = (portable_markdown(file.read_text(encoding="utf-8"), skill).encode()
                                      if name == "design-guidance.md" else text_bytes(file))
    if skill == "complexity-classifier":
        files["resources/Platform-Decision.md"] = text_bytes(SOURCE / "Platform-Decision.md")
    return files


def validate_companions(skill, files):
    sizes = [len(data) for name, data in files.items() if name != "SKILL.md"]
    if len(sizes) > 20 or max(sizes, default=0) > 5_000_000 or sum(sizes) > 10_000_000:
        raise ValueError(f"{skill} exceeds Cowork companion limits")
    for name in files:
        if any(not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._! -]*", part)
               or part.endswith((" ", "."))
               or re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])", part.split(".")[0])
               for part in name.split("/")):
            raise ValueError(f"Invalid companion path: {name}")


def png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def build(output=OUTPUT, *, runtime_check=False):
    manifest = json.loads((PROJECT / "manifest.json").read_bytes())
    probe = None
    if runtime_check:
        if output.resolve().is_relative_to(OUTPUT.parent.resolve()):
            raise ValueError("A diagnostic build must not be written to dist/")
        probe = SOURCE / "dev" / "lisa-runtime-check" / "SKILL.md"
        manifest["agentSkills"].append({"folder": "./skills/lisa-runtime-check"})
    names = declared_skills(manifest, PROJECT / "skills", dev_probe=probe)
    files = {"manifest.json": (json.dumps(manifest, indent=2) + "\n").encode(),
             "LICENSE.txt": text_bytes(REPO / "LICENSE")}
    with Image.open(PROJECT / "lisa-logo.png") as logo:
        files["color.png"] = png(logo.convert("RGB").resize((192, 192), Image.Resampling.LANCZOS))
        # Isolate the light graph mark from its navy background for the compact icon.
        mark = logo.convert("L").point(lambda luminance: 255 if luminance > 150 else 0)
    mask = ImageOps.pad(mark.crop(mark.getbbox()), (28, 28), method=Image.Resampling.LANCZOS)
    alpha = Image.new("L", (32, 32))
    alpha.paste(mask, (2, 2))
    outline = Image.new("RGBA", (32, 32), "white")
    outline.putalpha(alpha)
    files["outline.png"] = png(outline)
    for name in names:
        companions = ({"SKILL.md": text_bytes(probe)} if probe and name == "lisa-runtime-check"
                      else skill_files(name.removeprefix("lisa-")))
        validate_companions(name, companions)
        files.update({f"skills/{name}/{path}": data for path, data in companions.items()})
    output.parent.mkdir(parents=True, exist_ok=True)
    # Sorted entries and fixed ZIP timestamps avoid changes on every rebuild.
    with zipfile.ZipFile(output, "w") as archive:
        for path, data in sorted(files.items()):
            archive.writestr(zipfile.ZipInfo(path), data, compress_type=zipfile.ZIP_DEFLATED)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dev-runtime-check", action="store_true",
                        help="Build a private diagnostic ZIP in a new temporary directory, never in dist/")
    if parser.parse_args().dev_runtime_check:
        print(build(Path(tempfile.mkdtemp(prefix="lisa-dev-")) / "lisa-runtime-check.zip", runtime_check=True))
    else:
        print(build())
