"""Government repository lifecycle, model description, and workspace inventory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arch_repo_mcp.dsl import EntityDefinition
from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.repository import (
    DEFAULT_DECLARATION_PATH,
    RepositoryContext,
    create_repository,
    open_repository,
    validate_repository,
)
from arch_repo_mcp.workspace import WorkspaceConfig, load_workspace_config

_PRESET_DECLARATION = (
    Path(__file__).parent / "presets" / "government" / DEFAULT_DECLARATION_PATH
)


@dataclass(frozen=True, slots=True)
class GovernmentRepository:
    config: WorkspaceConfig
    context: RepositoryContext
    created: bool


def ensure_government_repository(
    workspace_path: str | Path | None = None,
    government_repository_path: str | Path | None = None,
    env_file: str | Path | None = None,
    *,
    initial_branch: str = "main",
) -> GovernmentRepository:
    """Open the configured government repository or create the built-in preset."""

    config = load_workspace_config(
        workspace_path,
        government_repository_path,
        env_file,
        create_workspace=True,
    )
    target = config.government_repository
    if target.exists() or target.is_symlink():
        context = open_repository(target)
        return GovernmentRepository(config=config, context=context, created=False)

    context = create_repository(
        target,
        _PRESET_DECLARATION,
        initial_branch=initial_branch,
    )
    return GovernmentRepository(config=config, context=context, created=True)


def describe_government_repository(
    workspace_path: str | Path | None = None,
    government_repository_path: str | Path | None = None,
    env_file: str | Path | None = None,
) -> dict[str, Any]:
    """Return the complete AI-facing entity model from the government repository."""

    government = ensure_government_repository(
        workspace_path,
        government_repository_path,
        env_file,
    )
    context = government.context
    return {
        "workspace_root": str(government.config.root),
        "government_repository_root": str(context.root),
        "declaration_path": context.declaration_path.as_posix(),
        "declaration_source": str(context.root / context.declaration_path),
        "declaration": {
            "kind": context.declaration.kind,
            "version": context.declaration.version,
        },
        "workflow": {
            "model_source": "repository_describe",
            "repository_selection": {
                "tool": "repository_list",
                "rule": "Select one returned repository_path and pass it explicitly.",
            },
            "working_repository_creation": {
                "tool": "repository_create",
                "rule": "Use declaration_source from this response and a target inside workspace.",
            },
            "create": {
                "tool": "entity_create",
                "next_tool": "entity_update",
                "rule": "Create from the declared template, then replace it with complete content.",
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


def list_working_repositories(
    workspace_path: str | Path | None = None,
    government_repository_path: str | Path | None = None,
    env_file: str | Path | None = None,
) -> dict[str, Any]:
    """List immediate working Git repositories without selecting one implicitly."""

    government = ensure_government_repository(
        workspace_path,
        government_repository_path,
        env_file,
    )
    config = government.config
    repositories: list[dict[str, Any]] = []
    try:
        children = sorted(config.root.iterdir(), key=lambda path: path.name.casefold())
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED,
            "Architecture repository workspace could not be listed",
        ) from exc

    for candidate in children:
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved == government.context.root or not (candidate / ".git").exists():
            continue
        try:
            report = validate_repository(candidate)
            item = {
                "name": candidate.name,
                "repository_path": str(resolved),
                "declaration_path": report.declaration_path,
                "valid": report.valid,
                "model_matches_government": report.valid
                and _model_matches_government(government.context, candidate),
                "entity_counts": report.entity_counts,
                "issues": [issue.as_dict() for issue in report.issues],
            }
        except ArchRepoError as exc:
            item = {
                "name": candidate.name,
                "repository_path": str(resolved),
                "declaration_path": DEFAULT_DECLARATION_PATH,
                "valid": False,
                "model_matches_government": False,
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
        "government_repository_root": str(government.context.root),
        "repositories": repositories,
    }


def _model_matches_government(government: RepositoryContext, candidate: Path) -> bool:
    try:
        working = open_repository(candidate)
        if working.declaration != government.declaration:
            return False
        for entity in government.declaration.entities:
            government_template = government.root.joinpath(*entity.files.template.parts)
            working_template = working.root.joinpath(*entity.files.template.parts)
            if government_template.read_bytes() != working_template.read_bytes():
                return False
    except (ArchRepoError, OSError):
        return False
    return True


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
            "Government repository template could not be read as UTF-8",
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
