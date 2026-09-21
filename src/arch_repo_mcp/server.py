"""MCP exposure layer for local architecture repository operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from mcp.server import MCPServer

from arch_repo_mcp import __version__
from arch_repo_mcp.entities import list_entities, read_entity, search_entities
from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.repository import open_repository, validate_repository

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


@mcp.tool()
def repository_open(
    repository_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Open and fully validate a local architecture Git repository without network access."""

    def operation() -> dict[str, Any]:
        context = open_repository(repository_path, declaration_path)
        return {
            "repository_root": str(context.root),
            "declaration_path": context.declaration_path.as_posix(),
            "declaration": {
                "kind": context.declaration.kind,
                "version": context.declaration.version,
            },
            "entities": [entity.name for entity in context.declaration.entities],
        }

    return _call(operation)


@mcp.tool()
def repository_validate(
    repository_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Validate the DSL, templates, paths, matching rules, and local entity files."""

    return _call(lambda: validate_repository(repository_path, declaration_path).as_dict())


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

