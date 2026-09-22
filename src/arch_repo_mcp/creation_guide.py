"""Offline creation guidance packaged with the server, including complete bundles."""

from pathlib import Path
from typing import Any

from arch_repo_mcp.dsl import load_declaration

PRESETS = Path(__file__).parent / "presets"


def creation_guide() -> dict[str, Any]:
    examples = []
    presets = ["| Preset | Entities |", "| --- | --- |"]
    relations = ["| Preset | Source | Allowed targets |", "| --- | --- | --- |"]
    for name in ("minimal", "default"):
        root = PRESETS / name
        source = root / "architecture.yaml"
        declaration = load_declaration(source)
        examples.append(
            {
                "preset": name,
                "architecture_yaml": source.read_text(encoding="utf-8"),
                "templates": {
                    path: (root / path).read_text(encoding="utf-8")
                    for path in sorted(
                        {entity.files.template.as_posix() for entity in declaration.entities}
                    )
                },
            }
        )
        presets.append(f"| {name} | {', '.join(e.name for e in declaration.entities)} |")
        for entity in declaration.entities:
            relations.append(f"| {name} | {entity.name} | {', '.join(entity.relations) or '—'} |")
    return {
        "phase": "guide",
        "dsl_reference": (PRESETS / "DSL_V2_TABLES.md").read_text(encoding="utf-8"),
        "presets_table": "\n".join(presets),
        "relations_table": "\n".join(relations),
        "instructions": [
            "This guide is for creating a NEW repository. To add an EXISTING directory to "
            "the index, call repository_index with "
            '{"repository_path": "/absolute/path/to/repository"}; no UUID is required. '
            "It validates the contents at that exact Git root and returns repository_id. "
            "Use that UUID in repository_describe; do not recreate the existing directory.",
            "Choose entity types for the user's request. Presets are examples, not fixed types.",
            "Build architecture.yaml with declaration.kind=architecture_repository and version=v2. "
            "Every entity needs unique name, nonempty description and files rules. "
            "Only keys and values in dsl_reference are accepted.",
            "Declare allowed directed relations using entity names. Instance filenames belong "
            "only in markdown_front_matter relations: [{entity: target_type, files: [basename]}]. "
            "When removing a type from an example, update both DSL and template relations.",
            "Supply every declared template as UTF-8 text keyed by its repository-relative "
            "POSIX path. Templates must match files.format; do not send undeclared files. "
            "Templates must not match entity file selectors.",
            "Exact path selectors create directories. Regex selectors are full matches and "
            "do not imply concrete directory names; supply those later to entity_create.",
            "Call repository_create again with an absolute, absent target_path whose parent "
            "exists, architecture_yaml text and templates object. initial_branch defaults "
            "explicitly to main. No source files on the server or shell tools are required.",
            "Use returned repository_id (UUID) for all subsequent repository and entity tools. "
            "Call repository_describe first. Commit and publication are separate explicit steps.",
        ],
        "examples": examples,
    }
