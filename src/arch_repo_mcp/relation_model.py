"""Front matter relation references governed by DSL entity relations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml

from arch_repo_mcp.dsl import EntityDefinition, RepositoryDeclaration, ValidationIssue


@dataclass(frozen=True, slots=True)
class RelationGroup:
    """References from one entity instance to files of one related entity type."""

    entity: str
    files: tuple[str, ...]


def parse_relation_groups(
    content: str,
    source_entity: EntityDefinition,
    declaration: RepositoryDeclaration,
    display_path: str,
) -> tuple[tuple[RelationGroup, ...], tuple[ValidationIssue, ...]]:
    """Parse and validate optional relation groups from Markdown front matter."""

    front_matter = _front_matter(content)
    if not isinstance(front_matter, dict) or "relations" not in front_matter:
        return (), ()

    raw_groups = front_matter["relations"]
    base_path = f"{display_path}#front_matter.relations"
    if not isinstance(raw_groups, list):
        return (), (
            ValidationIssue(
                "INVALID_RELATIONS",
                base_path,
                "relations must be a list",
            ),
        )

    groups: list[RelationGroup] = []
    issues: list[ValidationIssue] = []
    seen_entities: set[str] = set()
    allowed_entities = set(source_entity.relations)
    for index, raw_group in enumerate(raw_groups):
        group_path = f"{base_path}[{index}]"
        if not isinstance(raw_group, dict):
            issues.append(
                ValidationIssue(
                    "INVALID_RELATIONS",
                    group_path,
                    "relation group must be a mapping with entity and files",
                )
            )
            continue
        unknown_keys = sorted(
            str(key)
            for key in raw_group
            if not isinstance(key, str) or key not in {"entity", "files"}
        )
        for key in unknown_keys:
            issues.append(
                ValidationIssue(
                    "INVALID_RELATIONS",
                    f"{group_path}.{key}",
                    "unknown relation group key",
                )
            )
        if "entity" not in raw_group:
            issues.append(
                ValidationIssue(
                    "INVALID_RELATIONS",
                    f"{group_path}.entity",
                    "required key is missing",
                )
            )
        if "files" not in raw_group:
            issues.append(
                ValidationIssue(
                    "INVALID_RELATIONS",
                    f"{group_path}.files",
                    "required key is missing",
                )
            )

        raw_entity = raw_group.get("entity")
        if not isinstance(raw_entity, str) or not raw_entity.strip():
            issues.append(
                ValidationIssue(
                    "INVALID_RELATIONS",
                    f"{group_path}.entity",
                    "entity must be a non-empty string",
                )
            )
            continue
        entity_name = raw_entity.strip()
        target_entity = declaration.entity(entity_name)
        if entity_name not in allowed_entities:
            issues.append(
                ValidationIssue(
                    "RELATION_NOT_ALLOWED",
                    f"{group_path}.entity",
                    f"DSL does not allow relation from {source_entity.name} to {entity_name}",
                )
            )
        if entity_name in seen_entities:
            issues.append(
                ValidationIssue(
                    "DUPLICATE_RELATION_GROUP",
                    f"{group_path}.entity",
                    f"relation group is already declared: {entity_name}",
                )
            )
        seen_entities.add(entity_name)

        raw_files = raw_group.get("files")
        if not isinstance(raw_files, list):
            issues.append(
                ValidationIssue(
                    "INVALID_RELATIONS",
                    f"{group_path}.files",
                    "files must be a list of filenames",
                )
            )
            continue
        filenames: list[str] = []
        for file_index, raw_filename in enumerate(raw_files):
            filename_path = f"{group_path}.files[{file_index}]"
            if not isinstance(raw_filename, str) or not raw_filename.strip():
                issues.append(
                    ValidationIssue(
                        "INVALID_RELATION_FILENAME",
                        filename_path,
                        "relation filename must be a non-empty string",
                    )
                )
                continue
            filename = raw_filename.strip()
            pure_filename = PurePosixPath(filename)
            if (
                pure_filename.name != filename
                or filename in {".", ".."}
                or "/" in filename
                or "\\" in filename
            ):
                issues.append(
                    ValidationIssue(
                        "INVALID_RELATION_FILENAME",
                        filename_path,
                        "relation reference must contain a filename, not a path",
                    )
                )
                continue
            if filename in filenames:
                issues.append(
                    ValidationIssue(
                        "DUPLICATE_RELATION_FILE",
                        filename_path,
                        f"relation filename is already listed: {filename}",
                    )
                )
            if target_entity is not None and not target_entity.files.filename.matches(filename):
                issues.append(
                    ValidationIssue(
                        "INVALID_RELATION_FILENAME",
                        filename_path,
                        f"filename does not match entity {entity_name}: {filename}",
                    )
                )
            filenames.append(filename)

        if target_entity is not None:
            groups.append(RelationGroup(entity=entity_name, files=tuple(filenames)))

    return tuple(groups), tuple(issues)


def _front_matter(content: str) -> Any:
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        return None
    try:
        end_index = lines.index("---", 1)
    except ValueError:
        return None
    try:
        return yaml.safe_load("\n".join(lines[1:end_index]))
    except yaml.YAMLError:
        return None
