from __future__ import annotations

import asyncio
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from arch_repo_mcp.creation_guide import creation_guide
from arch_repo_mcp.dsl import ValidationIssue, load_declaration
from arch_repo_mcp.entities import EntityRecord, EntitySearchMatch, RelatedEntityRecord
from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.local_git import (
    GitBranch,
    GitCommit,
    GitCommitResult,
    GitRemote,
    GitStatus,
    GitStatusEntry,
)
from arch_repo_mcp.remote_sync import CloneResult, FetchResult, PublishResult, PullResult
from arch_repo_mcp.repository import RepositoryContext, RepositoryValidationReport
from arch_repo_mcp.server import _call, _repository_result, mcp

PROJECT_ROOT = Path(__file__).parents[1]
CONTRACT_PATH = PROJECT_ROOT / "specs" / "contracts" / "mcp" / "MCP_TOOLS.yaml"
EXAMPLE_DECLARATION = PROJECT_ROOT / "specs" / "examples" / "declarations" / "minimal.yaml"


def _contract() -> dict[str, Any]:
    loaded = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _schema_type(schema: dict[str, Any]) -> str:
    if schema.get("type") == "string":
        return "string"
    if schema.get("type") == "boolean":
        return "boolean"
    if schema.get("type") == "integer":
        return "integer"
    variants = schema.get("anyOf")
    if isinstance(variants, list) and {item.get("type") for item in variants} == {
        "string",
        "null",
    }:
        return "nullable_string"
    if isinstance(variants, list) and {item.get("type") for item in variants} == {
        "object",
        "null",
    }:
        mapping = next(item for item in variants if item.get("type") == "object")
        assert mapping["additionalProperties"] == {"type": "string"}
        return "nullable_string_map"
    raise AssertionError(f"Unsupported generated MCP schema: {schema}")


def _result_samples() -> dict[str, object]:
    declaration = load_declaration(EXAMPLE_DECLARATION)
    context = RepositoryContext(
        root=Path("repository"),
        declaration_path=PurePosixPath("architecture.yaml"),
        declaration=declaration,
    )
    issue = ValidationIssue("INVALID_CONTENT", "facts/F-0001.md", "invalid")
    validation = RepositoryValidationReport(
        valid=False,
        repository_root="repository",
        declaration_path="architecture.yaml",
        entity_counts={"fact": 1},
        issues=(issue,),
    ).as_dict()
    status_entry = GitStatusEntry("facts/F-0001.md", "M", " ")
    status = GitStatus("main", False, "a" * 40, (status_entry,)).as_dict()
    branch = GitBranch("main", True, "a" * 40).as_dict()
    commit = GitCommit(
        commit="a" * 40,
        parents=("b" * 40,),
        author_name="Architecture Bot",
        author_email="bot@example.invalid",
        authored_at="2026-01-01T00:00:00Z",
        subject="Architecture update",
    ).as_dict()
    commit_result = GitCommitResult(
        commit="a" * 40,
        branch="main",
        message="Architecture update",
        paths=("facts/F-0001.md",),
    ).as_dict()
    remote = GitRemote("origin", ("https://example.invalid/repo.git",), ()).as_dict()
    entity = EntityRecord("fact", "facts/F-0001.md", "markdown", 10).as_dict()
    read_entity = {**entity, "content": "content"}
    search = EntitySearchMatch("fact", "facts/F-0001.md", (1,)).as_dict()
    relation = RelatedEntityRecord(
        source_entity="fact",
        source_path="facts/F-0001.md",
        entity="category",
        filename="C-0001.md",
        relation_valid=True,
        found=False,
        status="missing",
        path=None,
        expected_path="categories/C-0001.md",
        candidate_paths=(),
        format="markdown_front_matter",
        content=None,
    ).as_dict()

    repository = _repository_result(context)
    described_entity = {
        "name": "fact",
        "description": "A verified architecture fact.",
        "semantic_purpose": "A verified architecture fact.",
        "relations": [],
        "path_rule": {"match": "exact", "value": "facts"},
        "filename_rule": {"match": "regex", "value": r"^F-[0-9]{4}\.md$"},
        "format": "markdown_front_matter",
        "template_path": "templates/fact.md",
        "template_content": "---\ntitle: Example\n---\n",
    }
    return {
        "repository_describe": {
            "repository_root": "workspace/repository",
            "declaration_path": "architecture.yaml",
            "declaration": {"kind": "architecture_repository", "version": "v2"},
            "workflow": {},
            "entities": [described_entity],
        },
        "repository_list": {
            "index_path": "config/repositories.json",
            "repositories": [],
        },
        "repository_create": {"phase": "created", "repository_id": "uuid", **repository},
        "repository_index": {"repository_id": "uuid", "repository_path": "/repo"},
        "repository_reindex": {"repository_id": "uuid", "repository_path": "/repo"},
        "repository_unindex": {"repository_id": "uuid", "repository_path": "/repo"},
        "repository_open": repository,
        "repository_validate": validation,
        "repository_status": status,
        "repository_diff": {"diff": ""},
        "repository_branches": [branch],
        "branch_create": branch,
        "branch_switch": branch,
        "repository_commit": commit_result,
        "repository_history": [commit],
        "repository_remotes": [remote],
        "remote_configure": remote,
        "repository_clone": {
            "repository_id": "uuid",
            **CloneResult("repository", "main", "a" * 40, "architecture.yaml").as_dict(),
        },
        "repository_fetch": FetchResult("origin", "a" * 40, "b" * 40, False, False).as_dict(),
        "repository_pull": PullResult(
            "origin", "main", "main", "a" * 40, "b" * 40, "fast_forward"
        ).as_dict(),
        "repository_publish": PublishResult("origin", "main", "main", "a" * 40).as_dict(),
        "entity_list": [entity],
        "entity_create": entity,
        "entity_read": read_entity,
        "entity_read_related": {
            "source": {"entity": "fact", "path": "facts/F-0001.md"},
            "relations": [relation],
        },
        "entity_update": entity,
        "entity_delete": {"entity": "fact", "path": "facts/F-0001.md"},
        "entity_search": [search],
    }


def test_registered_tool_arguments_match_normative_contract() -> None:
    contract_tools = _contract()["tools"]
    registered = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}

    assert registered.keys() == contract_tools.keys()
    for name, expected_tool in contract_tools.items():
        schema = registered[name].input_schema
        properties = schema["properties"]
        expected_arguments = expected_tool["arguments"]
        assert properties.keys() == expected_arguments.keys(), name
        assert set(schema.get("required", [])) == {
            argument
            for argument, definition in expected_arguments.items()
            if definition["required"]
        }, name
        for argument, definition in expected_arguments.items():
            assert _schema_type(properties[argument]) == definition["type"], (
                name,
                argument,
            )
            if not definition["required"]:
                assert properties[argument].get("default") == definition["default"], (
                    name,
                    argument,
                )
        assert registered[name].output_schema["type"] == "object"


def test_public_result_models_match_normative_contract() -> None:
    contract_tools = _contract()["tools"]
    samples = _result_samples()

    assert samples.keys() == contract_tools.keys()
    for name, expected_tool in contract_tools.items():
        expected_result = expected_tool["result"]
        sample = samples[name]
        if expected_result["kind"] == "object":
            assert isinstance(sample, dict), name
            assert sample.keys() == set(expected_result["fields"]), name
        else:
            assert isinstance(sample, list) and sample, name
            assert isinstance(sample[0], dict), name
            assert sample[0].keys() == set(expected_result["item_fields"]), name


def test_response_envelope_matches_normative_contract() -> None:
    envelope = _contract()["response_envelope"]
    success = _call(lambda: {"value": 1})

    def fail() -> None:
        raise ArchRepoError(ErrorCode.NOT_FOUND, "Missing")

    error = _call(fail)

    assert success.keys() == set(envelope["success_fields"])
    assert error.keys() == set(envelope["error_fields"])
    assert error["error"].keys() == set(envelope["normalized_error_fields"])


def test_creation_guide_result_matches_contract() -> None:
    expected = _contract()["tools"]["repository_create"]["result"]
    result = creation_guide()
    assert result.keys() == set(expected["guide_fields"])
    assert result["phase"] == "guide"
    for example in result["examples"]:
        assert example.keys() == set(expected["example_fields"])
