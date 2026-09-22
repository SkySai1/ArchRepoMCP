from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from arch_repo_mcp.repository import create_repository
from arch_repo_mcp.server import mcp, repository_open


def test_expected_mcp_tools_are_registered() -> None:
    tools = asyncio.run(mcp.list_tools())

    assert {tool.name for tool in tools} == {
        "branch_create",
        "branch_switch",
        "remote_configure",
        "repository_create",
        "repository_index",
        "repository_reindex",
        "repository_unindex",
        "repository_branches",
        "repository_clone",
        "repository_diff",
        "repository_fetch",
        "repository_history",
        "repository_list",
        "repository_commit",
        "repository_describe",
        "repository_open",
        "repository_publish",
        "repository_pull",
        "repository_remotes",
        "repository_status",
        "repository_validate",
        "entity_create",
        "entity_delete",
        "entity_list",
        "entity_read",
        "entity_read_related",
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
            "code": "VALIDATION_ERROR",
            "message": "repository_id must be a UUID",
            "details": {},
        },
    }


@pytest.mark.parametrize("surface", ["server_instructions", "tool_description", "creation_guide"])
def test_agent_can_follow_exposed_index_example_from_empty_registry(
    tmp_path: Path, surface: str
) -> None:
    root = tmp_path / "existing"
    create_repository(root)

    async def scenario() -> None:
        if surface == "server_instructions":
            guidance = mcp.instructions
        elif surface == "tool_description":
            tool = next(tool for tool in await mcp.list_tools() if tool.name == "repository_index")
            guidance = tool.description
        else:
            guide = await mcp.call_tool("repository_create", {})
            guidance = " ".join(guide.structured_content["result"]["instructions"])
        examples = [
            json.loads(block) for block in re.findall(r'\{"repository_path":.*?\}', guidance)
        ]
        arguments = next(example for example in examples if set(example) == {"repository_path"})
        assert Path(arguments["repository_path"]).is_absolute()
        arguments["repository_path"] = str(root)
        listed = await mcp.call_tool("repository_list", {})
        assert listed.structured_content["result"]["repositories"] == []
        indexed = await mcp.call_tool("repository_index", arguments)
        response = indexed.structured_content
        assert response["ok"], response
        assert response["result"]["repository_path"] == str(root.resolve())
        described = await mcp.call_tool(
            "repository_describe", {"repository_id": response["result"]["repository_id"]}
        )
        assert described.structured_content["ok"], described
        assert described.structured_content["result"]["repository_root"] == str(root.resolve())

    asyncio.run(scenario())
