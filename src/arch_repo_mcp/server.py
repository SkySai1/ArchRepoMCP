"""MCP exposure layer for local architecture repository operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from mcp.server import MCPServer

from arch_repo_mcp import __version__
from arch_repo_mcp.entities import (
    create_entity,
    delete_entity,
    list_entities,
    read_entity,
    search_entities,
    update_entity,
)
from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.local_git import (
    create_branch,
    list_branches,
)
from arch_repo_mcp.local_git import (
    repository_diff as local_repository_diff,
)
from arch_repo_mcp.local_git import (
    repository_history as local_repository_history,
)
from arch_repo_mcp.local_git import (
    repository_status as local_repository_status,
)
from arch_repo_mcp.repository import (
    RepositoryContext,
    create_repository,
    open_repository,
    validate_repository,
)

ResultT = TypeVar("ResultT")

mcp = MCPServer(
    "ArchRepoMCP",
    description="Local-first management of DSL-defined architecture Git repositories",
    instructions=(
        "Use repository_open before entity operations. All exposed operations are local and "
        "perform no fetch, pull, push, or provider API requests. Paths must identify local Git "
        "repositories and repository-relative files."
    ),
    version=__version__,
)


def _call(operation: Callable[[], ResultT]) -> dict[str, Any]:
    try:
        return {"ok": True, "result": operation()}
    except ArchRepoError as exc:
        return {"ok": False, "error": exc.as_dict()}
    except Exception:
        error = ArchRepoError(ErrorCode.INVALID_REPOSITORY, "Unexpected local operation failure")
        return {"ok": False, "error": error.as_dict()}


def _repository_result(context: RepositoryContext) -> dict[str, Any]:
    return {
        "repository_root": str(context.root),
        "declaration_path": context.declaration_path.as_posix(),
        "declaration": {
            "kind": context.declaration.kind,
            "version": context.declaration.version,
        },
        "entities": [entity.name for entity in context.declaration.entities],
    }


@mcp.tool()
def repository_create(
    target_path: str,
    declaration_source: str,
    declaration_path: str = "architecture.yaml",
    initial_branch: str = "main",
) -> dict[str, Any]:
    """Create a validated local Git repository without creating a commit."""

    return _call(
        lambda: _repository_result(
            create_repository(
                target_path,
                declaration_source,
                declaration_path,
                initial_branch,
            )
        )
    )


@mcp.tool()
def repository_open(
    repository_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Open and fully validate a local architecture Git repository without network access."""

    return _call(
        lambda: _repository_result(open_repository(repository_path, declaration_path))
    )


@mcp.tool()
def repository_validate(
    repository_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Validate the DSL, templates, paths, matching rules, and local entity files."""

    return _call(lambda: validate_repository(repository_path, declaration_path).as_dict())


@mcp.tool()
def repository_status(
    repository_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Return local Git status without fetch, pull, or other network operations."""

    return _call(
        lambda: local_repository_status(repository_path, declaration_path).as_dict()
    )


@mcp.tool()
def repository_diff(
    repository_path: str,
    declaration_path: str = "architecture.yaml",
    staged: bool = False,
    base_revision: str | None = None,
    target_revision: str | None = None,
) -> dict[str, Any]:
    """Return working-tree, staged, or revision-to-revision local Git diff."""

    return _call(
        lambda: {
            "diff": local_repository_diff(
                repository_path,
                declaration_path,
                staged=staged,
                base_revision=base_revision,
                target_revision=target_revision,
            )
        }
    )


@mcp.tool()
def repository_branches(
    repository_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """List local branches without contacting a remote."""

    return _call(
        lambda: [
            branch.as_dict() for branch in list_branches(repository_path, declaration_path)
        ]
    )


@mcp.tool()
def branch_create(
    repository_path: str,
    branch_name: str,
    start_point: str = "HEAD",
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Create a local branch without switching the repository to it."""

    return _call(
        lambda: create_branch(
            repository_path,
            branch_name,
            start_point,
            declaration_path,
        ).as_dict()
    )


@mcp.tool()
def repository_history(
    repository_path: str,
    declaration_path: str = "architecture.yaml",
    max_count: int = 20,
    revision: str = "HEAD",
) -> dict[str, Any]:
    """Return bounded local commit history without contacting a remote."""

    return _call(
        lambda: [
            commit.as_dict()
            for commit in local_repository_history(
                repository_path,
                declaration_path,
                max_count=max_count,
                revision=revision,
            )
        ]
    )


@mcp.tool()
def entity_list(
    repository_path: str,
    entity_name: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """List instances of a DSL-declared entity type from the local repository."""

    return _call(
        lambda: [
            item.as_dict()
            for item in list_entities(repository_path, entity_name, declaration_path)
        ]
    )


@mcp.tool()
def entity_create(
    repository_path: str,
    entity_name: str,
    entity_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Create a local entity from its DSL template without commit or publication."""

    return _call(
        lambda: create_entity(
            repository_path,
            entity_name,
            entity_path,
            declaration_path,
        ).as_dict()
    )


@mcp.tool()
def entity_read(
    repository_path: str,
    entity_name: str,
    entity_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Read one local entity selected by type and repository-relative path."""

    return _call(
        lambda: read_entity(
            repository_path,
            entity_name,
            entity_path,
            declaration_path,
        )
    )


@mcp.tool()
def entity_update(
    repository_path: str,
    entity_name: str,
    entity_path: str,
    content: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Replace a local entity and roll back when validation fails."""

    return _call(
        lambda: update_entity(
            repository_path,
            entity_name,
            entity_path,
            content,
            declaration_path,
        ).as_dict()
    )


@mcp.tool()
def entity_delete(
    repository_path: str,
    entity_name: str,
    entity_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Delete one local entity without commit or publication."""

    return _call(
        lambda: delete_entity(
            repository_path,
            entity_name,
            entity_path,
            declaration_path,
        )
    )


@mcp.tool()
def entity_search(
    repository_path: str,
    query: str,
    entity_name: str | None = None,
    declaration_path: str = "architecture.yaml",
    case_sensitive: bool = False,
) -> dict[str, Any]:
    """Search text in all or one type of local DSL-resolved entity."""

    return _call(
        lambda: [
            item.as_dict()
            for item in search_entities(
                repository_path,
                query,
                entity_name,
                declaration_path,
                case_sensitive=case_sensitive,
            )
        ]
    )


def main() -> None:
    """Run the MCP server over stdio."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
