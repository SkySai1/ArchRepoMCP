"""Description and discovery of self-contained architecture repositories."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from arch_repo_mcp.dsl import EntityDefinition
from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.repository import (
    DEFAULT_DECLARATION_PATH,
    RepositoryContext,
    open_repository,
    validate_repository,
)
from arch_repo_mcp.workspace import load_workspace_config


def describe_repository(
    repository_path: str | Path,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
) -> dict[str, Any]:
    """Return the AI-facing DSL model stored in one selected repository."""

    context = open_repository(repository_path, declaration_path)
    return {
        "repository_root": str(context.root),
        "declaration_path": context.declaration_path.as_posix(),
        "declaration": {
            "kind": context.declaration.kind,
            "version": context.declaration.version,
        },
        "workflow": {
            "model_source": "selected_repository",
            "repository_selection": {
                "tool": "repository_list",
                "rule": (
                    "Select one repository_path, call repository_describe for it, and use "
                    "only that repository's DSL and templates."
                ),
            },
            "repository_creation": {
                "tool": "repository_create",
                "rule": (
                    "Create an atomic repository from the built-in default bundle or an "
                    "explicit declaration bundle."
                ),
            },
            "create": {
                "tool": "entity_create",
                "next_tool": "entity_update",
                "rule": "Create from the local template, then replace it with complete content.",
            },
            "read": {
                "tools": [
                    "entity_list",
                    "entity_read",
                    "entity_read_related",
                    "entity_search",
                ]
            },
            "update": {"tool": "entity_update"},
            "delete": {"tool": "entity_delete"},
            "persistence": {
                "tools": ["repository_commit", "repository_publish"],
                "rule": "Entity changes remain local until an explicit commit and publish.",
            },
        },
        "entities": [_describe_entity(context, entity) for entity in context.declaration.entities],
    }


def list_repositories(
    workspace_path: str | Path | None = None,
    env_file: str | Path | None = None,
) -> dict[str, Any]:
    """List immediate atomic Git repositories without selecting one implicitly."""

    config = load_workspace_config(
        workspace_path,
        env_file,
        create_workspace=True,
    )
    repositories: list[dict[str, Any]] = []
    try:
        children = sorted(config.root.iterdir(), key=lambda path: path.name.casefold())
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED,
            "Architecture repository workspace could not be listed",
        ) from exc

    for candidate in children:
        if candidate.is_symlink() or not candidate.is_dir() or not (candidate / ".git").exists():
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        try:
            report = validate_repository(candidate)
            item = {
                "name": candidate.name,
                "repository_path": str(resolved),
                "declaration_path": report.declaration_path,
                "valid": report.valid,
                "entity_counts": report.entity_counts,
                "issues": [issue.as_dict() for issue in report.issues],
            }
        except ArchRepoError as exc:
            item = {
                "name": candidate.name,
                "repository_path": str(resolved),
                "declaration_path": DEFAULT_DECLARATION_PATH,
                "valid": False,
                "entity_counts": {},
                "issues": [
                    {
                        "code": exc.code.value,
                        "path": DEFAULT_DECLARATION_PATH,
                        "message": exc.message,
                    }
                ],
            }
        repositories.append(item)

    return {
        "workspace_root": str(config.root),
        "repositories": repositories,
    }


def _describe_entity(
    context: RepositoryContext,
    entity: EntityDefinition,
) -> dict[str, Any]:
    template_path = context.root.joinpath(*entity.files.template.parts)
    try:
        template_content = template_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Repository template could not be read as UTF-8",
            details={"path": entity.files.template.as_posix()},
        ) from exc
    return {
        "name": entity.name,
        "description": entity.description,
        "semantic_purpose": entity.description,
        "relations": list(entity.relations),
        "path_rule": {
            "match": entity.files.path.mode.value,
            "value": entity.files.path.value,
        },
        "filename_rule": {
            "match": entity.files.filename.mode.value,
            "value": entity.files.filename.value,
        },
        "format": entity.files.format.value,
        "template_path": entity.files.template.as_posix(),
        "template_content": template_content,
    }
