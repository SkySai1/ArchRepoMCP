"""Read-only entity operations resolved exclusively through the repository DSL."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from arch_repo_mcp.dsl import EntityDefinition
from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.repository import DEFAULT_DECLARATION_PATH, RepositoryContext, open_repository


@dataclass(frozen=True, slots=True)
class EntityRecord:
    entity: str
    path: str
    format: str
    size_bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "path": self.path,
            "format": self.format,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True, slots=True)
class EntitySearchMatch:
    entity: str
    path: str
    matching_lines: tuple[int, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity,
            "path": self.path,
            "matching_lines": list(self.matching_lines),
        }


def list_entities(
    repository_path: str | Path,
    entity_name: str,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
) -> list[EntityRecord]:
    """List all local files that the DSL maps to one entity type."""

    context = open_repository(repository_path, declaration_path)
    entity = _require_entity(context, entity_name)
    return [_record(context.root, entity, path) for path in _entity_paths(context, entity)]


def read_entity(
    repository_path: str | Path,
    entity_name: str,
    entity_path: str,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
) -> dict[str, Any]:
    """Read one UTF-8 entity file after validating its DSL membership."""

    context = open_repository(repository_path, declaration_path)
    entity = _require_entity(context, entity_name)
    relative, absolute = _resolve_entity_path(context, entity, entity_path)
    try:
        content = absolute.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Entity file could not be read as UTF-8",
            details={"path": relative.as_posix()},
        ) from exc
    result = _record(context.root, entity, absolute).as_dict()
    result["content"] = content
    return result


def search_entities(
    repository_path: str | Path,
    query: str,
    entity_name: str | None = None,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
    *,
    case_sensitive: bool = False,
) -> list[EntitySearchMatch]:
    """Search local entity text and return deterministic file and line references."""

    if not query:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "Search query must not be empty")

    context = open_repository(repository_path, declaration_path)
    if entity_name is None:
        entities = context.declaration.entities
    else:
        entities = (_require_entity(context, entity_name),)

    needle = query if case_sensitive else query.casefold()
    matches: list[EntitySearchMatch] = []
    for entity in entities:
        for path in _entity_paths(context, entity):
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                relative = path.relative_to(context.root).as_posix()
                raise ArchRepoError(
                    ErrorCode.INVALID_REPOSITORY,
                    "Entity file could not be read as UTF-8",
                    details={"path": relative},
                ) from exc
            matching_lines = tuple(
                line_number
                for line_number, line in enumerate(content.splitlines(), start=1)
                if needle in (line if case_sensitive else line.casefold())
            )
            if matching_lines:
                matches.append(
                    EntitySearchMatch(
                        entity=entity.name,
                        path=path.relative_to(context.root).as_posix(),
                        matching_lines=matching_lines,
                    )
                )
    return sorted(matches, key=lambda item: (item.entity, item.path))


def _require_entity(context: RepositoryContext, entity_name: str) -> EntityDefinition:
    entity = context.declaration.entity(entity_name)
    if entity is None:
        raise ArchRepoError(
            ErrorCode.NOT_FOUND,
            "Entity type is not declared by the repository DSL",
            details={"entity": entity_name},
        )
    return entity


def _entity_paths(context: RepositoryContext, entity: EntityDefinition) -> list[Path]:
    paths: list[Path] = []
    template_paths = {item.files.template for item in context.declaration.entities}
    for current, directories, filenames in os.walk(context.root, topdown=True):
        directories[:] = sorted(name for name in directories if name != ".git")
        current_path = Path(current)
        for filename in sorted(filenames):
            absolute = current_path / filename
            relative = PurePosixPath(absolute.relative_to(context.root).as_posix())
            if relative == context.declaration_path or relative in template_paths:
                continue
            if entity.matches(relative):
                paths.append(absolute)
    return sorted(paths, key=lambda item: item.relative_to(context.root).as_posix())


def _resolve_entity_path(
    context: RepositoryContext,
    entity: EntityDefinition,
    entity_path: str,
) -> tuple[PurePosixPath, Path]:
    if not entity_path or "\\" in entity_path:
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            "Entity path must be a repository-relative POSIX path",
        )
    relative = PurePosixPath(entity_path)
    if relative.is_absolute() or ".." in relative.parts or relative == PurePosixPath("."):
        raise ArchRepoError(ErrorCode.PERMISSION_DENIED, "Entity path escapes the repository")
    if not entity.matches(relative):
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            "Entity path does not match the declared entity file rule",
            details={"entity": entity.name, "path": entity_path},
        )
    if relative == context.declaration_path or relative in {
        item.files.template for item in context.declaration.entities
    }:
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            "Path is reserved for repository metadata or a template",
            details={"path": entity_path},
        )

    candidate = context.root.joinpath(*relative.parts)
    try:
        absolute = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ArchRepoError(
            ErrorCode.NOT_FOUND, "Entity file was not found", details={"path": entity_path}
        ) from exc
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Entity path could not be resolved",
            details={"path": entity_path},
        ) from exc
    if (
        candidate.is_symlink()
        or not absolute.is_relative_to(context.root)
        or not absolute.is_file()
    ):
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED,
            "Entity path is not a confined regular file",
            details={"path": entity_path},
        )
    return relative, absolute


def _record(root: Path, entity: EntityDefinition, path: Path) -> EntityRecord:
    return EntityRecord(
        entity=entity.name,
        path=path.relative_to(root).as_posix(),
        format=entity.files.format.value,
        size_bytes=path.stat().st_size,
    )
