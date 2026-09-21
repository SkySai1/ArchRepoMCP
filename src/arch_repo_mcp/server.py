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
    read_related_entities,
    search_entities,
    update_entity,
)
from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.government import (
    describe_government_repository,
    ensure_government_repository,
    list_working_repositories,
)
from arch_repo_mcp.local_git import (
    configure_remote,
    create_branch,
    list_branches,
    list_remotes,
    switch_branch,
)
from arch_repo_mcp.local_git import repository_commit as local_repository_commit
from arch_repo_mcp.local_git import (
    repository_diff as local_repository_diff,
)
from arch_repo_mcp.local_git import (
    repository_history as local_repository_history,
)
from arch_repo_mcp.local_git import (
    repository_status as local_repository_status,
)
from arch_repo_mcp.remote_sync import (
    clone_repository,
    fetch_repository,
    publish_repository,
    pull_repository,
)
from arch_repo_mcp.repository import (
    RepositoryContext,
    create_repository,
    open_repository,
    validate_repository,
)
from arch_repo_mcp.workspace import (
    resolve_repository_argument,
    resolve_working_repository_argument,
)

ResultT = TypeVar("ResultT")

mcp = MCPServer(
    "ArchRepoMCP",
    description="Local-first management of DSL-defined architecture Git repositories",
    instructions=(
        "Call repository_describe to obtain the authoritative entity model, then repository_list "
        "and explicitly pass one selected repository_path to every entity operation. Network "
        "access occurs only through the "
        "explicit repository_clone, repository_fetch, repository_pull, and "
        "repository_publish tools; no tool performs an implicit pull, push, or provider API "
        "request. Paths must identify local Git repositories and repository-relative files."
    ),
    version=__version__,
)


def _call(operation: Callable[[], ResultT]) -> dict[str, Any]:
    try:
        return {"ok": True, "result": operation()}
    except ArchRepoError as exc:
        return {"ok": False, "error": exc.as_dict()}
    except Exception:
        error = ArchRepoError(ErrorCode.INVALID_REPOSITORY, "Unexpected operation failure")
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


def _managed_path(path: str) -> str:
    """Resolve relative paths against the configured workspace when one is configured."""

    return str(resolve_repository_argument(path))


def _working_path(path: str) -> str:
    """Resolve an explicitly selected repository and reject the government repository."""

    return str(resolve_working_repository_argument(path))


@mcp.tool()
def government_repository_initialize(
    workspace_path: str | None = None,
    government_repository_path: str | None = None,
    env_file: str | None = None,
    initial_branch: str = "main",
) -> dict[str, Any]:
    """Open or create the government repository from the built-in DSL and templates."""

    def initialize() -> dict[str, Any]:
        government = ensure_government_repository(
            workspace_path,
            government_repository_path,
            env_file,
            initial_branch=initial_branch,
        )
        return {
            "workspace_root": str(government.config.root),
            "government_repository_root": str(government.context.root),
            "created": government.created,
            **{
                key: value
                for key, value in _repository_result(government.context).items()
                if key != "repository_root"
            },
        }

    return _call(initialize)


@mcp.tool()
def repository_describe(
    workspace_path: str | None = None,
    government_repository_path: str | None = None,
    env_file: str | None = None,
) -> dict[str, Any]:
    """Return the authoritative DSL model, templates, and entity-management workflow."""

    return _call(
        lambda: describe_government_repository(
            workspace_path,
            government_repository_path,
            env_file,
        )
    )


@mcp.tool()
def repository_list(
    workspace_path: str | None = None,
    government_repository_path: str | None = None,
    env_file: str | None = None,
) -> dict[str, Any]:
    """List working repositories so an agent can explicitly select a repository_path."""

    return _call(
        lambda: list_working_repositories(
            workspace_path,
            government_repository_path,
            env_file,
        )
    )


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
                _managed_path(target_path),
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
        lambda: _repository_result(
            open_repository(_managed_path(repository_path), declaration_path)
        )
    )


@mcp.tool()
def repository_validate(
    repository_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Validate the DSL, templates, paths, matching rules, and local entity files."""

    return _call(
        lambda: validate_repository(_managed_path(repository_path), declaration_path).as_dict()
    )


@mcp.tool()
def repository_status(
    repository_path: str,
) -> dict[str, Any]:
    """Return local Git status without fetch, pull, or other network operations."""

    return _call(lambda: local_repository_status(_managed_path(repository_path)).as_dict())


@mcp.tool()
def repository_diff(
    repository_path: str,
    staged: bool = False,
    base_revision: str | None = None,
    target_revision: str | None = None,
) -> dict[str, Any]:
    """Return working-tree, staged, or revision-to-revision local Git diff."""

    return _call(
        lambda: {
            "diff": local_repository_diff(
                _managed_path(repository_path),
                staged=staged,
                base_revision=base_revision,
                target_revision=target_revision,
            )
        }
    )


@mcp.tool()
def repository_branches(
    repository_path: str,
) -> dict[str, Any]:
    """List local branches without contacting a remote."""

    return _call(
        lambda: [
            branch.as_dict() for branch in list_branches(_managed_path(repository_path))
        ]
    )


@mcp.tool()
def branch_create(
    repository_path: str,
    branch_name: str,
    start_point: str = "HEAD",
) -> dict[str, Any]:
    """Create a local branch without switching the repository to it."""

    return _call(
        lambda: create_branch(
            _managed_path(repository_path),
            branch_name,
            start_point,
        ).as_dict()
    )


@mcp.tool()
def branch_switch(
    repository_path: str,
    branch_name: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Switch to a valid local branch only when the worktree and index are clean."""

    return _call(
        lambda: switch_branch(
            _managed_path(repository_path),
            branch_name,
            declaration_path,
        ).as_dict()
    )


@mcp.tool()
def repository_commit(
    repository_path: str,
    message: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Validate and commit only changed DSL-controlled paths without push."""

    return _call(
        lambda: local_repository_commit(
            _managed_path(repository_path),
            message,
            declaration_path,
        ).as_dict()
    )


@mcp.tool()
def repository_history(
    repository_path: str,
    max_count: int = 20,
    revision: str = "HEAD",
) -> dict[str, Any]:
    """Return bounded local commit history without contacting a remote."""

    return _call(
        lambda: [
            commit.as_dict()
            for commit in local_repository_history(
                _managed_path(repository_path),
                max_count=max_count,
                revision=revision,
            )
        ]
    )


@mcp.tool()
def repository_remotes(repository_path: str) -> dict[str, Any]:
    """List local Git remotes while redacting credential-bearing URL components."""

    return _call(
        lambda: [remote.as_dict() for remote in list_remotes(_managed_path(repository_path))]
    )


@mcp.tool()
def remote_configure(
    repository_path: str,
    name: str,
    url: str,
    replace: bool = False,
) -> dict[str, Any]:
    """Add or explicitly replace local remote configuration without network access."""

    return _call(
        lambda: configure_remote(
            _managed_path(repository_path),
            name,
            url,
            replace=replace,
        ).as_dict()
    )


@mcp.tool()
def repository_clone(
    remote_url: str,
    target_path: str,
    declaration_path: str = "architecture.yaml",
    branch: str | None = None,
    include_tags: bool = False,
) -> dict[str, Any]:
    """Explicitly clone and validate a remote Git architecture repository."""

    return _call(
        lambda: clone_repository(
            remote_url,
            _managed_path(target_path),
            declaration_path,
            branch=branch,
            include_tags=include_tags,
        ).as_dict()
    )


@mcp.tool()
def repository_fetch(
    repository_path: str,
    remote: str,
    include_tags: bool = False,
    prune: bool = False,
) -> dict[str, Any]:
    """Explicitly fetch a configured remote without changing the working tree."""

    return _call(
        lambda: fetch_repository(
            _managed_path(repository_path),
            remote,
            include_tags=include_tags,
            prune=prune,
        ).as_dict()
    )


@mcp.tool()
def repository_pull(
    repository_path: str,
    remote: str,
    remote_branch: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Fetch and integrate only a validated fast-forward into a clean local branch."""

    return _call(
        lambda: pull_repository(
            _managed_path(repository_path),
            remote,
            remote_branch,
            declaration_path,
        ).as_dict()
    )


@mcp.tool()
def repository_publish(
    repository_path: str,
    remote: str,
    remote_branch: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Validate and explicitly push current HEAD without force or implicit upstream."""

    return _call(
        lambda: publish_repository(
            _managed_path(repository_path),
            remote,
            remote_branch,
            declaration_path,
        ).as_dict()
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
            for item in list_entities(_working_path(repository_path), entity_name, declaration_path)
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
            _working_path(repository_path),
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
            _working_path(repository_path),
            entity_name,
            entity_path,
            declaration_path,
        )
    )


@mcp.tool()
def entity_read_related(
    repository_path: str,
    entity_name: str,
    entity_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Read files referenced by an entity's DSL-governed front matter relations."""

    return _call(
        lambda: read_related_entities(
            _working_path(repository_path),
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
            _working_path(repository_path),
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
            _working_path(repository_path),
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
                _working_path(repository_path),
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
