"""MCP exposure layer for local architecture repository operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from mcp.server import MCPServer

from arch_repo_mcp import __version__
from arch_repo_mcp.catalog import describe_repository
from arch_repo_mcp.creation_guide import creation_guide
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
from arch_repo_mcp.registry import RepositoryRegistry, absolute_repository_path
from arch_repo_mcp.remote_sync import (
    clone_repository,
    fetch_repository,
    publish_repository,
    pull_repository,
)
from arch_repo_mcp.repository import (
    RepositoryContext,
    create_repository_from_content,
    open_repository,
    validate_repository,
)

ResultT = TypeVar("ResultT")

mcp = MCPServer(
    "ArchRepoMCP",
    description="Local-first management of DSL-defined architecture Git repositories",
    instructions=(
        "Call repository_create without arguments for DSL presets, relations and examples. "
        "Submit target_path, architecture_yaml and templates to repository_create to create. "
        "Call repository_list, select one repository_id UUID, and call repository_describe to "
        "obtain that repository's authoritative DSL and templates before entity operations. "
        "Every repository is self-contained. Network access occurs only through the "
        "explicit repository_clone, repository_fetch, repository_pull, and "
        "repository_publish tools; no tool performs an implicit pull, push, or provider API "
        "request. Existing repository operations require UUID, never a filesystem path. "
        "Use repository_reindex to validate and register existing repositories, and "
        "repository_unindex to remove only an index entry."
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


def _repository_path(repository_id: str) -> str:
    return RepositoryRegistry().resolve(repository_id)


def _index_new_repository(operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    registry = RepositoryRegistry()
    registry.list()  # Check index access and integrity before creating a repository.
    result = operation()
    try:
        entry = registry.reindex(result["repository_root"], result["declaration_path"])
    except ArchRepoError as exc:
        raise ArchRepoError(
            exc.code,
            "Repository was created but indexing failed; call repository_reindex to recover",
            details={"repository_path": result["repository_root"]},
        ) from exc
    return {**result, "repository_id": entry["repository_id"]}


@mcp.tool()
def repository_describe(
    repository_id: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Return the selected repository's authoritative DSL, templates, and workflow."""

    return _call(
        lambda: describe_repository(
            _repository_path(repository_id),
            declaration_path,
        )
    )


@mcp.tool()
def repository_list() -> dict[str, Any]:
    """List persistent repository UUIDs and absolute paths, including stale entries."""

    return _call(lambda: RepositoryRegistry().list())


@mcp.tool()
def repository_unindex(repository_id: str) -> dict[str, Any]:
    """Remove a UUID from the index without deleting or changing repository files."""

    return _call(lambda: RepositoryRegistry().unindex(repository_id))


@mcp.tool()
def repository_reindex(
    repository_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Validate an existing absolute Git root and register it, preserving an existing UUID."""

    return _call(lambda: RepositoryRegistry().reindex(repository_path, declaration_path))


@mcp.tool()
def repository_create(
    target_path: str | None = None,
    architecture_yaml: str | None = None,
    templates: dict[str, str] | None = None,
    initial_branch: str = "main",
) -> dict[str, Any]:
    """Without arguments return DSL tables, relations, instructions and complete examples.

    To create, explicitly submit all of target_path (absolute), architecture_yaml (text)
    and templates (relative path to content). Validate and return the indexed repository UUID.
    No implicit preset, commit or push.
    """

    def execute() -> dict[str, Any]:
        if target_path is None and architecture_yaml is None and templates is None:
            return creation_guide()
        if target_path is None or architecture_yaml is None or templates is None:
            raise ArchRepoError(
                ErrorCode.VALIDATION_ERROR,
                "Supply target_path, architecture_yaml and templates together; "
                "call repository_create without arguments for guidance",
            )
        path = absolute_repository_path(target_path)
        result = _index_new_repository(
            lambda: _repository_result(
                create_repository_from_content(
                    path,
                    architecture_yaml,
                    templates,
                    initial_branch=initial_branch,
                )
            )
        )
        return {"phase": "created", **result}

    return _call(execute)


@mcp.tool()
def repository_open(
    repository_id: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Open and fully validate a local architecture Git repository without network access."""

    return _call(
        lambda: _repository_result(
            open_repository(_repository_path(repository_id), declaration_path)
        )
    )


@mcp.tool()
def repository_validate(
    repository_id: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Validate the DSL, templates, paths, matching rules, and local entity files."""

    return _call(
        lambda: validate_repository(_repository_path(repository_id), declaration_path).as_dict()
    )


@mcp.tool()
def repository_status(
    repository_id: str,
) -> dict[str, Any]:
    """Return local Git status without fetch, pull, or other network operations."""

    return _call(lambda: local_repository_status(_repository_path(repository_id)).as_dict())


@mcp.tool()
def repository_diff(
    repository_id: str,
    staged: bool = False,
    base_revision: str | None = None,
    target_revision: str | None = None,
) -> dict[str, Any]:
    """Return working-tree, staged, or revision-to-revision local Git diff."""

    return _call(
        lambda: {
            "diff": local_repository_diff(
                _repository_path(repository_id),
                staged=staged,
                base_revision=base_revision,
                target_revision=target_revision,
            )
        }
    )


@mcp.tool()
def repository_branches(
    repository_id: str,
) -> dict[str, Any]:
    """List local branches without contacting a remote."""

    return _call(
        lambda: [branch.as_dict() for branch in list_branches(_repository_path(repository_id))]
    )


@mcp.tool()
def branch_create(
    repository_id: str,
    branch_name: str,
    start_point: str = "HEAD",
) -> dict[str, Any]:
    """Create a local branch without switching the repository to it."""

    return _call(
        lambda: create_branch(
            _repository_path(repository_id),
            branch_name,
            start_point,
        ).as_dict()
    )


@mcp.tool()
def branch_switch(
    repository_id: str,
    branch_name: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Switch to a valid local branch only when the worktree and index are clean."""

    return _call(
        lambda: switch_branch(
            _repository_path(repository_id),
            branch_name,
            declaration_path,
        ).as_dict()
    )


@mcp.tool()
def repository_commit(
    repository_id: str,
    message: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Validate and commit only changed DSL-controlled paths without push."""

    return _call(
        lambda: local_repository_commit(
            _repository_path(repository_id),
            message,
            declaration_path,
        ).as_dict()
    )


@mcp.tool()
def repository_history(
    repository_id: str,
    max_count: int = 20,
    revision: str = "HEAD",
) -> dict[str, Any]:
    """Return bounded local commit history without contacting a remote."""

    return _call(
        lambda: [
            commit.as_dict()
            for commit in local_repository_history(
                _repository_path(repository_id),
                max_count=max_count,
                revision=revision,
            )
        ]
    )


@mcp.tool()
def repository_remotes(repository_id: str) -> dict[str, Any]:
    """List local Git remotes while redacting credential-bearing URL components."""

    return _call(
        lambda: [remote.as_dict() for remote in list_remotes(_repository_path(repository_id))]
    )


@mcp.tool()
def remote_configure(
    repository_id: str,
    name: str,
    url: str,
    replace: bool = False,
) -> dict[str, Any]:
    """Add or explicitly replace local remote configuration without network access."""

    return _call(
        lambda: configure_remote(
            _repository_path(repository_id),
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
        lambda: _index_new_repository(
            lambda: clone_repository(
                remote_url,
                str(absolute_repository_path(target_path)),
                declaration_path,
                branch=branch,
                include_tags=include_tags,
            ).as_dict()
        )
    )


@mcp.tool()
def repository_fetch(
    repository_id: str,
    remote: str,
    include_tags: bool = False,
    prune: bool = False,
) -> dict[str, Any]:
    """Explicitly fetch a configured remote without changing the working tree."""

    return _call(
        lambda: fetch_repository(
            _repository_path(repository_id),
            remote,
            include_tags=include_tags,
            prune=prune,
        ).as_dict()
    )


@mcp.tool()
def repository_pull(
    repository_id: str,
    remote: str,
    remote_branch: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Fetch and integrate only a validated fast-forward into a clean local branch."""

    return _call(
        lambda: pull_repository(
            _repository_path(repository_id),
            remote,
            remote_branch,
            declaration_path,
        ).as_dict()
    )


@mcp.tool()
def repository_publish(
    repository_id: str,
    remote: str,
    remote_branch: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Validate and explicitly push current HEAD without force or implicit upstream."""

    return _call(
        lambda: publish_repository(
            _repository_path(repository_id),
            remote,
            remote_branch,
            declaration_path,
        ).as_dict()
    )


@mcp.tool()
def entity_list(
    repository_id: str,
    entity_name: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """List instances of a DSL-declared entity type from the local repository."""

    return _call(
        lambda: [
            item.as_dict()
            for item in list_entities(
                _repository_path(repository_id), entity_name, declaration_path
            )
        ]
    )


@mcp.tool()
def entity_create(
    repository_id: str,
    entity_name: str,
    entity_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Create a local entity from its DSL template without commit or publication."""

    return _call(
        lambda: create_entity(
            _repository_path(repository_id),
            entity_name,
            entity_path,
            declaration_path,
        ).as_dict()
    )


@mcp.tool()
def entity_read(
    repository_id: str,
    entity_name: str,
    entity_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Read one local entity selected by type and repository-relative path."""

    return _call(
        lambda: read_entity(
            _repository_path(repository_id),
            entity_name,
            entity_path,
            declaration_path,
        )
    )


@mcp.tool()
def entity_read_related(
    repository_id: str,
    entity_name: str,
    entity_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Read files referenced by an entity's DSL-governed front matter relations."""

    return _call(
        lambda: read_related_entities(
            _repository_path(repository_id),
            entity_name,
            entity_path,
            declaration_path,
        )
    )


@mcp.tool()
def entity_update(
    repository_id: str,
    entity_name: str,
    entity_path: str,
    content: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Replace a local entity and roll back when validation fails."""

    return _call(
        lambda: update_entity(
            _repository_path(repository_id),
            entity_name,
            entity_path,
            content,
            declaration_path,
        ).as_dict()
    )


@mcp.tool()
def entity_delete(
    repository_id: str,
    entity_name: str,
    entity_path: str,
    declaration_path: str = "architecture.yaml",
) -> dict[str, Any]:
    """Delete one local entity without commit or publication."""

    return _call(
        lambda: delete_entity(
            _repository_path(repository_id),
            entity_name,
            entity_path,
            declaration_path,
        )
    )


@mcp.tool()
def entity_search(
    repository_id: str,
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
                _repository_path(repository_id),
                query,
                entity_name,
                declaration_path,
                case_sensitive=case_sensitive,
            )
        ]
    )


def main() -> None:
    """Run the MCP server over stdio."""

    RepositoryRegistry().list()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
