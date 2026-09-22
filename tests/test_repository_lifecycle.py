from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

from arch_repo_mcp.creation_guide import creation_guide
from arch_repo_mcp.errors import ArchRepoError
from arch_repo_mcp.registry import RepositoryRegistry
from arch_repo_mcp.repository import create_repository
from arch_repo_mcp.server import (
    entity_create,
    entity_list,
    entity_read,
    entity_update,
    mcp,
    repository_clone,
    repository_create,
    repository_describe,
    repository_list,
    repository_open,
    repository_reindex,
    repository_status,
    repository_unindex,
    repository_validate,
)


def bundle(preset: str = "minimal") -> dict:
    example = next(item for item in creation_guide()["examples"] if item["preset"] == preset)
    return {key: example[key] for key in ("architecture_yaml", "templates")}


def created(path: Path, preset: str = "minimal") -> dict:
    response = repository_create(str(path), **bundle(preset))
    assert response["ok"], response
    return response["result"]


def test_guide_is_complete_offline_and_has_no_creation_side_effects(tmp_path: Path) -> None:
    result = repository_create()
    assert result["ok"]
    guide = result["result"]
    assert guide["phase"] == "guide"
    assert "markdown_front_matter" in guide["dsl_reference"]
    assert "architecture_artifact" in guide["relations_table"]
    assert not RepositoryRegistry().path.exists()
    assert not list(tmp_path.glob(".archrepo-*"))
    reference = Path(__file__).parents[1] / "specs/dsl/DSL_V2_TABLES.md"
    assert guide["dsl_reference"] == reference.read_text(encoding="utf-8")


@pytest.mark.parametrize("preset", ["minimal", "default"])
def test_complete_guide_examples_create_valid_indexed_repositories(
    tmp_path: Path, preset: str
) -> None:
    path = tmp_path / preset
    result = created(path, preset)
    identifier = result["repository_id"]
    assert result["phase"] == "created"
    assert repository_validate(identifier)["result"]["valid"]
    assert repository_open(identifier)["result"]["repository_root"] == str(path.resolve())
    assert repository_status(identifier)["result"]["head"] is None
    assert (path / "architecture.yaml").read_text(encoding="utf-8") == bundle(preset)[
        "architecture_yaml"
    ]
    assert (path / "facts").is_dir()
    assert repository_list()["result"]["repositories"] == [
        {"repository_id": identifier, "repository_path": str(path.resolve())}
    ]
    assert RepositoryRegistry().resolve(identifier) == str(path.resolve())
    index = json.loads(RepositoryRegistry().path.read_text())
    assert index == {"version": 1, "repositories": repository_list()["result"]["repositories"]}


def test_agent_can_supply_custom_types_then_operate_by_uuid(tmp_path: Path) -> None:
    content = bundle()
    declaration = yaml.safe_load(content["architecture_yaml"])
    entity = declaration["entities"][0]
    entity.update(name="decision", description="Принятое архитектурное решение")
    entity["files"]["path"]["value"] = "design/decisions"
    entity["files"]["filename"]["value"] = r"^ADR-[0-9]+\.md$"
    entity["files"]["template"] = "templates/decision.md"
    content = {
        "architecture_yaml": yaml.safe_dump(declaration, allow_unicode=True),
        "templates": {"templates/decision.md": "---\ntitle: Решение\n---\n"},
    }
    result = repository_create(str(tmp_path / "custom"), **content)
    assert result["ok"], result
    identifier = result["result"]["repository_id"]
    assert repository_describe(identifier)["result"]["entities"][0]["name"] == "decision"
    assert (tmp_path / "custom/design/decisions").is_dir()
    assert not (tmp_path / "custom/facts").exists()
    assert entity_create(identifier, "decision", "design/decisions/ADR-1.md")["ok"]
    updated = "---\ntitle: Use local storage\n---\nLocal Git is authoritative.\n"
    assert entity_update(identifier, "decision", "design/decisions/ADR-1.md", updated)["ok"]
    assert (
        entity_read(identifier, "decision", "design/decisions/ADR-1.md")["result"]["content"]
        == updated
    )
    other = created(tmp_path / "other")
    assert entity_list(other["repository_id"], "fact")["result"] == []
    assert not entity_list(other["repository_id"], "decision")["ok"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"target_path": "repo"},
        {"architecture_yaml": ""},
        {"templates": {}},
        {"architecture_yaml": "", "templates": {}},
    ],
)
def test_incomplete_creation_never_selects_an_implicit_preset(arguments: dict) -> None:
    assert repository_create(**arguments)["error"]["code"] == "VALIDATION_ERROR"
    assert repository_list()["result"]["repositories"] == []


@pytest.mark.parametrize(
    "failure",
    [
        "invalid_yaml",
        "unknown_relation",
        "missing_template",
        "extra_template",
        "bad_format",
        "bad_template_relation",
        "traversal",
        "absolute_template",
        "git_template",
        "git_directory",
        "windows_drive",
        "template_is_entity",
        "file_directory_collision",
    ],
)
def test_invalid_bundles_leave_no_target_or_index_entry(tmp_path: Path, failure: str) -> None:
    content = bundle()
    declaration = yaml.safe_load(content["architecture_yaml"])
    entity = declaration["entities"][0]
    templates = content["templates"]
    if failure == "unknown_relation":
        entity["relations"] = ["absent"]
    elif failure == "missing_template":
        templates.clear()
    elif failure == "extra_template":
        templates["extra.md"] = "extra"
    elif failure == "bad_format":
        templates["templates/fact.md"] = "no front matter"
    elif failure == "bad_template_relation":
        templates["templates/fact.md"] = "---\nrelations:\n- entity: absent\n  files: []\n---\n"
    elif failure in {"traversal", "absolute_template", "git_template", "windows_drive"}:
        path = {
            "traversal": "../escape.md",
            "absolute_template": str(tmp_path / "escape.md"),
            "git_template": ".git/hooks/pre-commit",
            "windows_drive": "C:/escape.md",
        }[failure]
        entity["files"]["template"] = path
        templates = {path: "---\n---\n"}
    elif failure == "git_directory":
        entity["files"]["path"]["value"] = ".git/hooks"
    elif failure == "template_is_entity":
        entity["files"]["template"] = "facts/F-0001.md"
        templates = {"facts/F-0001.md": "---\n---\n"}
    elif failure == "file_directory_collision":
        entity["files"]["path"]["value"] = "templates/fact.md/children"
    result = repository_create(
        str(tmp_path / "target"),
        "[invalid" if failure == "invalid_yaml" else yaml.safe_dump(declaration),
        templates,
    )
    assert not result["ok"], result
    assert result["error"]["message"] != "Unexpected operation failure"
    assert not (tmp_path / "target").exists()
    assert not (tmp_path / "escape.md").exists()
    assert not list(tmp_path.glob(".target.archrepo-*"))
    assert repository_list()["result"]["repositories"] == []


def test_regex_directory_is_not_guessed(tmp_path: Path) -> None:
    content = bundle()
    declaration = yaml.safe_load(content["architecture_yaml"])
    declaration["entities"][0]["files"]["path"] = {
        "match": "regex",
        "value": "systems/[^/]+/facts",
    }
    result = repository_create(
        str(tmp_path / "regex"),
        yaml.safe_dump(declaration),
        content["templates"],
    )
    assert result["ok"], result
    assert not (tmp_path / "regex/systems").exists()
    assert entity_create(result["result"]["repository_id"], "fact", "systems/pay/facts/F-0001.md")[
        "ok"
    ]


def test_unindex_preserves_files_and_reindex_validates_and_assigns_identity(tmp_path: Path) -> None:
    path = tmp_path / "repo"
    original = created(path)
    identifier = original["repository_id"]
    assert repository_reindex(str(path))["result"]["repository_id"] == identifier
    before = {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()}
    assert repository_unindex(identifier)["ok"]
    assert {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()} == before
    assert repository_open(identifier)["error"]["code"] == "NOT_FOUND"
    assert repository_unindex(identifier)["error"]["code"] == "NOT_FOUND"
    new = repository_reindex(str(path))["result"]["repository_id"]
    assert new != identifier
    assert repository_open(new)["ok"]
    assert len(repository_list()["result"]["repositories"]) == 1


def test_reindex_rejects_invalid_dsl_non_git_and_nested_paths(tmp_path: Path) -> None:
    path = tmp_path / "repo"
    create_repository(path)
    assert not repository_reindex(str(path / "facts"))["ok"]
    assert not repository_reindex(str(tmp_path))["ok"]
    (path / "architecture.yaml").write_text("invalid")
    assert not repository_reindex(str(path))["ok"]
    assert repository_list()["result"]["repositories"] == []


def test_stale_entries_can_be_listed_and_removed_without_accessing_files(tmp_path: Path) -> None:
    path = tmp_path / "repo"
    identifier = created(path)["repository_id"]
    moved = tmp_path / "moved"
    path.rename(moved)
    assert repository_status(identifier)["error"]["code"] == "NOT_FOUND"
    assert repository_list()["result"]["repositories"][0]["repository_id"] == identifier
    new = repository_reindex(str(moved))["result"]["repository_id"]
    assert new != identifier
    assert repository_unindex(identifier)["ok"]
    (moved / "architecture.yaml").write_text("invalid")
    assert not repository_validate(new)["result"]["valid"]
    assert repository_status(new)["ok"]  # Git diagnostics do not require valid DSL.
    assert repository_unindex(new)["ok"]


def test_symlink_substitution_and_lost_git_root_do_not_redirect_uuid(tmp_path: Path) -> None:
    parent = tmp_path / "parent"
    create_repository(parent)
    path = parent / "child"
    identifier = created(path)["repository_id"]
    moved = tmp_path / "moved"
    path.rename(moved)
    path.symlink_to(moved, target_is_directory=True)
    assert repository_status(identifier)["error"]["code"] == "INVALID_REPOSITORY"
    assert repository_reindex(str(path))["error"]["code"] == "INVALID_REPOSITORY"
    path.unlink()
    moved.rename(path)
    shutil.rmtree(path / ".git")
    assert repository_status(identifier)["error"]["code"] == "INVALID_REPOSITORY"


def test_all_existing_repository_tools_require_uuid() -> None:
    exceptions = {
        "repository_create", "repository_clone", "repository_list",
        "repository_index", "repository_reindex",
    }
    for tool in asyncio.run(mcp.list_tools()):
        if tool.name in exceptions:
            continue
        assert "repository_id" in tool.input_schema["required"], tool.name
        assert "repository_path" not in tool.input_schema["properties"], tool.name
    assert repository_status(str(uuid4()))["error"]["code"] == "NOT_FOUND"
    assert repository_status("/some/path")["error"]["code"] == "VALIDATION_ERROR"


def test_absolute_targets_and_existing_target_protection(tmp_path: Path) -> None:
    assert repository_create("relative", **bundle())["error"]["code"] == "VALIDATION_ERROR"
    assert repository_reindex("relative")["error"]["code"] == "VALIDATION_ERROR"
    path = tmp_path / "existing"
    path.mkdir()
    marker = path / "keep.txt"
    marker.write_text("keep")
    assert repository_create(str(path), **bundle())["error"]["code"] == "CONFLICT"
    assert marker.read_text() == "keep"


@pytest.mark.parametrize(
    "raw",
    ["{bad json", '{"version": 2, "repositories": []}', '{"version": 1, "repositories": [{}]}'],
)
def test_corrupted_registry_is_not_overwritten_and_blocks_creation(
    tmp_path: Path, raw: str
) -> None:
    registry = RepositoryRegistry()
    registry.list()
    registry.path.write_text(raw)
    assert repository_list()["error"]["code"] == "INVALID_REPOSITORY"
    assert not repository_create(str(tmp_path / "repo"), **bundle())["ok"]
    assert not (tmp_path / "repo").exists()
    assert registry.path.read_text() == raw


def test_failed_atomic_write_preserves_index_and_repository_can_be_recovered(
    tmp_path: Path,
    monkeypatch,
) -> None:
    registry = RepositoryRegistry()
    registry.list()
    before = registry.path.read_bytes()
    replace = Path.replace

    def fail_index(source, target):
        if target == registry.path:
            raise PermissionError("simulated index write failure")
        return replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_index)
        result = repository_create(str(tmp_path / "repo"), **bundle())
    assert result["error"]["code"] == "PERMISSION_DENIED"
    assert result["error"]["details"]["repository_path"] == str((tmp_path / "repo").resolve())
    assert "repository_reindex" in result["error"]["message"]
    assert registry.path.read_bytes() == before
    assert not list(registry.path.parent.glob(".repositories-*"))
    assert repository_reindex(str(tmp_path / "repo"))["ok"]


def test_concurrent_index_updates_do_not_lose_entries_or_duplicate_uuid(tmp_path: Path) -> None:
    paths = [tmp_path / f"repo-{index}" for index in range(5)]
    for path in paths:
        create_repository(path)
    with ThreadPoolExecutor(max_workers=5) as workers:
        results = list(workers.map(lambda p: RepositoryRegistry().reindex(str(p)), paths * 2))
    assert len({entry["repository_id"] for entry in results}) == 5
    assert len(RepositoryRegistry().list()["repositories"]) == 5


def test_clone_registers_uuid_using_local_git_transport(tmp_path: Path) -> None:
    source = tmp_path / "source"
    create_repository(source)
    subprocess.run(["git", "-C", str(source), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "initial",
        ],
        check=True,
    )
    result = repository_clone(source.as_uri(), str(tmp_path / "clone"))
    assert result["ok"], result
    assert repository_open(result["result"]["repository_id"])["ok"]


def test_registry_permissions_are_normalized(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise PermissionError("not exposed")

    monkeypatch.setattr(Path, "mkdir", fail)
    with pytest.raises(ArchRepoError) as error:
        RepositoryRegistry().list()
    assert error.value.code == "PERMISSION_DENIED"


def test_readme_creation_example_through_mcp_dispatcher(tmp_path: Path) -> None:
    readme = (Path(__file__).parents[1] / "README.md").read_text(encoding="utf-8")
    examples = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", readme, re.S)]
    arguments = next(example for example in examples if "architecture_yaml" in example)
    arguments["target_path"] = str(tmp_path / "documented-example")

    async def scenario() -> None:
        guide = await mcp.call_tool("repository_create", {})
        assert guide.structured_content["result"]["phase"] == "guide"
        created = await mcp.call_tool("repository_create", arguments)
        assert created.structured_content["ok"], created
        identifier = created.structured_content["result"]["repository_id"]
        validation = await mcp.call_tool("repository_validate", {"repository_id": identifier})
        assert validation.structured_content["result"]["valid"]
        mutation = await mcp.call_tool(
            "entity_create",
            {
                "repository_id": identifier,
                "entity_name": "note",
                "entity_path": "notes/N-1.md",
            },
        )
        assert mutation.structured_content["ok"], mutation

    asyncio.run(scenario())


def test_duplicate_keys_and_duplicate_identities_are_invalid(tmp_path: Path) -> None:
    identifier = created(tmp_path / "repo")["repository_id"]
    registry = RepositoryRegistry()
    original = json.loads(registry.path.read_text())
    entry = original["repositories"][0]
    invalid_entries = [
        [entry, entry],
        [entry, {**entry, "repository_id": str(uuid4())}],
        [entry, {**entry, "repository_path": str(tmp_path / "other")}],
    ]
    for entries in invalid_entries:
        registry.path.write_text(json.dumps({"version": 1, "repositories": entries}))
        assert repository_list()["error"]["code"] == "INVALID_REPOSITORY"
    registry.path.write_text('{"version": 1, "repositories": [], "repositories": []}')
    assert repository_status(identifier)["error"]["code"] == "INVALID_REPOSITORY"


def test_identity_persists_in_a_fresh_process(tmp_path: Path) -> None:
    identifier = created(tmp_path / "repo")["repository_id"]
    code = (
        "import sys; from pathlib import Path; "
        "Path.home = classmethod(lambda cls: Path(sys.argv[1])); "
        "from arch_repo_mcp.registry import RepositoryRegistry; "
        "print(RepositoryRegistry().resolve(sys.argv[2]))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(Path.home()), identifier],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == str((tmp_path / "repo").resolve())
