"""Validate and zip the editable Cowork release without rewriting its files."""

import argparse
import json
import re
import tempfile
import zipfile
from pathlib import Path

from jsonschema import Draft4Validator


TOOLS = Path(__file__).resolve().parent
COWORK = TOOLS.parents[1] / "cowork"
PROJECT = COWORK / "lisa"
OUTPUT = COWORK / "dist" / "lisa.zip"
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


def declared_skills(manifest, entry_root, *, dev_probe=None):
    schema = json.loads((TOOLS / "MicrosoftTeams-v1.29.schema.json").read_bytes())
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


def companion_paths(skill):
    if skill not in RESOURCES:
        raise ValueError(f"No packaging rules for {skill}")
    paths = {"SKILL.md", "references/workflow.md", f"scripts/{skill.replace('-', '_')}.py"}
    paths.update(f"scripts/{name}" for name in HELPERS)
    paths.update(f"resources/{name}" for name in RESOURCES[skill])
    if skill == "complexity-classifier":
        paths.add("resources/Platform-Decision.md")
    return paths


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


def release_files(project):
    manifest = json.loads((project / "manifest.json").read_bytes())
    expected = {"manifest.json", "LICENSE.txt", "color.png", "outline.png"}
    skills = declared_skills(manifest, project / "skills")
    for name in skills:
        expected.update(f"skills/{name}/{p}" for p in companion_paths(name.removeprefix("lisa-")))
    dirs = {parent.as_posix() for name in expected for parent in Path(name).parents}
    files = {}
    for path in project.rglob("*"):
        rel = path.relative_to(project).as_posix()
        if path.is_symlink() or path.resolve() != path:
            raise ValueError(f"Linked release path: {rel}")
        if path.is_dir() and rel in dirs:
            continue
        if rel not in expected or not path.is_file():
            raise ValueError(f"Unexpected release path: {rel}")
        files[rel] = path.read_bytes()
    if missing := expected - files.keys():
        raise ValueError(f"Missing release files: {sorted(missing)}")
    for name in skills:
        prefix = f"skills/{name}/"
        companions = {p[len(prefix):]: data for p, data in files.items() if p.startswith(prefix)}
        validate_companions(name, companions)
        workflow = companions["references/workflow.md"].decode("utf-8").replace("\\", "/")
        if any(item in workflow for item in ("../", ".ps1", "cad-orchestrator")):
            raise ValueError(f"Review the Cowork workflow adaptation for {name}")
    return files


def build(output=OUTPUT, *, runtime_check=False):
    if output.resolve().is_relative_to(PROJECT):
        raise ValueError("A ZIP must not be written inside the release tree")
    if runtime_check and output.resolve().is_relative_to(OUTPUT.parent.resolve()):
        raise ValueError("A diagnostic build must not be written to dist/")
    files = release_files(PROJECT)
    if runtime_check:
        probe = TOOLS / "dev" / "lisa-runtime-check" / "SKILL.md"
        manifest = json.loads(files["manifest.json"])
        manifest["agentSkills"].append({"folder": "./skills/lisa-runtime-check"})
        declared_skills(manifest, PROJECT / "skills", dev_probe=probe)
        files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
        files["skills/lisa-runtime-check/SKILL.md"] = probe.read_text(encoding="utf-8").encode()
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
