"""Entity operations resolved exclusively through the repository DSL."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from arch_repo_mcp.dsl import EntityDefinition, FileFormat, MatchMode
from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.relation_model import parse_relation_groups
from arch_repo_mcp.repository import (
    DEFAULT_DECLARATION_PATH,
    RepositoryContext,
    RepositoryValidationReport,
    open_repository,
    validate_repository,
)


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


@dataclass(frozen=True, slots=True)
class RelatedEntityRecord:
    source_entity: str
    source_path: str
    entity: str
    filename: str
    relation_valid: bool
    found: bool
    status: str
    path: str | None
    expected_path: str | None
    candidate_paths: tuple[str, ...]
    format: str
    content: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_entity": self.source_entity,
            "source_path": self.source_path,
            "entity": self.entity,
            "filename": self.filename,
            "relation_valid": self.relation_valid,
            "found": self.found,
            "status": self.status,
            "path": self.path,
            "expected_path": self.expected_path,
            "candidate_paths": list(self.candidate_paths),
            "format": self.format,
            "content": self.content,
        }


def read_related_entities(
    repository_path: str | Path,
    entity_name: str,
    entity_path: str,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
) -> dict[str, Any]:
    """Read one-hop file relations declared by DSL and entity front matter."""

    context = open_repository(repository_path, declaration_path)
    source_entity = _require_entity(context, entity_name)
    source_relative, source_path = _resolve_entity_path(
        context,
        source_entity,
        entity_path,
    )
    try:
        source_content = source_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Source entity file could not be read as UTF-8",
            details={"path": source_relative.as_posix()},
        ) from exc

    groups = ()
    if source_entity.files.format is FileFormat.MARKDOWN_FRONT_MATTER:
        groups, issues = parse_relation_groups(
            source_content,
            source_entity,
            context.declaration,
            source_relative.as_posix(),
        )
        if issues:
            raise ArchRepoError(
                ErrorCode.VALIDATION_ERROR,
                "Entity relation references are invalid",
                details={"issues": [issue.as_dict() for issue in issues]},
            )

    relations: list[dict[str, Any]] = []
    for group in groups:
        related_entity = _require_entity(context, group.entity)
        entity_paths = _entity_paths(context, related_entity)
        for filename in group.files:
            candidates = tuple(
                path.relative_to(context.root).as_posix()
                for path in entity_paths
                if path.name == filename
            )
            expected_path = _expected_relation_path(related_entity, filename)
            found_path: str | None = None
            content: str | None = None
            if len(candidates) == 1:
                status = "found"
                found_path = candidates[0]
                try:
                    content = context.root.joinpath(*PurePosixPath(found_path).parts).read_text(
                        encoding="utf-8"
                    )
                except (OSError, UnicodeError) as exc:
                    raise ArchRepoError(
                        ErrorCode.INVALID_REPOSITORY,
                        "Related entity file could not be read as UTF-8",
                        details={"path": found_path},
                    ) from exc
            elif candidates:
                status = "ambiguous"
            else:
                status = "missing"

            relations.append(
                RelatedEntityRecord(
                    source_entity=source_entity.name,
                    source_path=source_relative.as_posix(),
                    entity=related_entity.name,
                    filename=filename,
                    relation_valid=True,
                    found=status == "found",
                    status=status,
                    path=found_path,
                    expected_path=expected_path,
                    candidate_paths=candidates,
                    format=related_entity.files.format.value,
                    content=content,
                ).as_dict()
            )

    return {
        "source": {
            "entity": source_entity.name,
            "path": source_relative.as_posix(),
        },
        "relations": relations,
    }


def create_entity(
    repository_path: str | Path,
    entity_name: str,
    entity_path: str,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
) -> EntityRecord:
    """Create one local entity from its declared template without committing it."""

    context = open_repository(repository_path, declaration_path)
    entity = _require_entity(context, entity_name)
    relative, target = _resolve_new_entity_path(context, entity, entity_path)
    template = context.root.joinpath(*entity.files.template.parts)
    try:
        content = template.read_bytes()
        template_mode = template.stat().st_mode
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Entity template could not be read",
            details={"path": entity.files.template.as_posix()},
        ) from exc

    created_directories = _create_parent_directories(context.root, target.parent)
    try:
        _atomic_write(target, content, mode=template_mode)
        report = validate_repository(context.root, context.declaration_path.as_posix())
        if not report.valid:
            _remove_created_entity(target, created_directories)
            _raise_mutation_validation("creation", report)
    except ArchRepoError:
        _remove_created_entity(target, created_directories)
        raise
    except OSError as exc:
        _remove_created_entity(target, created_directories)
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED,
            "Entity file could not be created",
            details={"path": relative.as_posix()},
        ) from exc
    return _record(context.root, entity, target)


def update_entity(
    repository_path: str | Path,
    entity_name: str,
    entity_path: str,
    content: str,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
) -> EntityRecord:
    """Replace one local entity and roll back if repository validation fails."""

    context = open_repository(repository_path, declaration_path)
    entity = _require_entity(context, entity_name)
    relative, target = _resolve_entity_path(context, entity, entity_path)
    try:
        replacement = content.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR, "Entity content is not valid UTF-8 text"
        ) from exc
    try:
        original = target.read_bytes()
        original_mode = target.stat().st_mode
        _atomic_write(target, replacement, mode=original_mode)
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED,
            "Entity file could not be updated",
            details={"path": relative.as_posix()},
        ) from exc

    try:
        report = validate_repository(context.root, context.declaration_path.as_posix())
    except ArchRepoError:
        _restore_entity(target, original, original_mode, relative)
        raise
    if not report.valid:
        _restore_entity(target, original, original_mode, relative)
        _raise_mutation_validation("update", report)
    return _record(context.root, entity, target)


def delete_entity(
    repository_path: str | Path,
    entity_name: str,
    entity_path: str,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
) -> dict[str, str]:
    """Delete one local entity and roll back if repository validation fails."""

    context = open_repository(repository_path, declaration_path)
    entity = _require_entity(context, entity_name)
    relative, target = _resolve_entity_path(context, entity, entity_path)
    try:
        original = target.read_bytes()
        original_mode = target.stat().st_mode
        target.unlink()
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED,
            "Entity file could not be deleted",
            details={"path": relative.as_posix()},
        ) from exc

    try:
        report = validate_repository(context.root, context.declaration_path.as_posix())
    except ArchRepoError:
        _restore_entity(target, original, original_mode, relative)
        raise
    if not report.valid:
        _restore_entity(target, original, original_mode, relative)
        _raise_mutation_validation("deletion", report)
    return {"entity": entity.name, "path": relative.as_posix()}


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


def _expected_relation_path(entity: EntityDefinition, filename: str) -> str | None:
    if entity.files.path.mode is not MatchMode.EXACT:
        return None
    parent = PurePosixPath(entity.files.path.value)
    relative = PurePosixPath(filename) if parent == PurePosixPath(".") else parent / filename
    return relative.as_posix()


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


def _validate_entity_relative_path(
    context: RepositoryContext,
    entity: EntityDefinition,
    entity_path: str,
) -> PurePosixPath:
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
    return relative


def _resolve_new_entity_path(
    context: RepositoryContext,
    entity: EntityDefinition,
    entity_path: str,
) -> tuple[PurePosixPath, Path]:
    relative = _validate_entity_relative_path(context, entity, entity_path)
    target = context.root.joinpath(*relative.parts)
    if target.exists() or target.is_symlink():
        raise ArchRepoError(
            ErrorCode.CONFLICT,
            "Entity file already exists",
            details={"path": relative.as_posix()},
        )
    return relative, target


def _resolve_entity_path(
    context: RepositoryContext,
    entity: EntityDefinition,
    entity_path: str,
) -> tuple[PurePosixPath, Path]:
    relative = _validate_entity_relative_path(context, entity, entity_path)

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


def _create_parent_directories(root: Path, parent: Path) -> list[Path]:
    missing: list[Path] = []
    current = parent
    while current != root and not current.exists():
        missing.append(current)
        current = current.parent
    if not current.is_relative_to(root) or current.is_symlink():
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED, "Entity parent path is not confined to the repository"
        )
    try:
        parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED, "Entity parent directory could not be created"
        ) from exc
    return missing


def _atomic_write(path: Path, content: bytes, *, mode: int | None = None) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _remove_created_entity(target: Path, created_directories: list[Path]) -> None:
    try:
        if target.exists() or target.is_symlink():
            target.unlink()
        for directory in created_directories:
            if directory.exists():
                directory.rmdir()
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Failed to roll back entity creation",
            details={"path": target.name},
        ) from exc


def _restore_entity(target: Path, content: bytes, mode: int, relative: PurePosixPath) -> None:
    try:
        _atomic_write(target, content, mode=mode)
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Failed to restore entity after validation error",
            details={"path": relative.as_posix()},
        ) from exc


def _raise_mutation_validation(
    operation: str,
    report: RepositoryValidationReport,
) -> None:
    raise ArchRepoError(
        ErrorCode.VALIDATION_ERROR,
        f"Entity {operation} did not pass repository validation",
        details=report.as_dict(),
    )


def _record(root: Path, entity: EntityDefinition, path: Path) -> EntityRecord:
    return EntityRecord(
        entity=entity.name,
        path=path.relative_to(root).as_posix(),
        format=entity.files.format.value,
        size_bytes=path.stat().st_size,
    )
