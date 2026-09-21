from __future__ import annotations

import asyncio
from pathlib import Path

from arch_repo_mcp.server import mcp, repository_open


def test_expected_mcp_tools_are_registered() -> None:
    tools = asyncio.run(mcp.list_tools())

    assert {tool.name for tool in tools} == {
        "branch_create",
        "branch_switch",
        "remote_configure",
        "repository_create",
        "repository_branches",
        "repository_clone",
        "repository_diff",
        "repository_fetch",
        "repository_history",
        "repository_commit",
        "repository_open",
        "repository_publish",
        "repository_remotes",
        "repository_status",
        "repository_validate",
        "entity_create",
        "entity_delete",
        "entity_list",
        "entity_read",
        "entity_search",
        "entity_update",
    }
    assert all(tool.description for tool in tools)
    assert all(tool.input_schema["type"] == "object" for tool in tools)


def test_mcp_tool_returns_normalized_domain_error(tmp_path: Path) -> None:
    result = repository_open(str(tmp_path))

    assert result == {
        "ok": False,
        "error": {
            "code": "INVALID_REPOSITORY",
            "message": "Path is not inside a Git repository",
            "details": {"path": str(tmp_path.resolve())},
        },
    }
