"""Path regressions for specs/contracts/mcp/REPOSITORY_LIFECYCLE.md.

Exercise real Git repositories and the persisted index through the public MCP tools.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest
import yaml

from arch_repo_mcp.registry import RepositoryRegistry
from arch_repo_mcp.repository import create_repository
from arch_repo_mcp.server import (
    mcp,
    repository_index,
    repository_list,
    repository_open,
    repository_reindex,
    repository_unindex,
)

MINIMAL_DECLARATION = (
    Path(__file__).parents[1] / "src/arch_repo_mcp/presets/minimal/architecture.yaml"
)
PATH_CASES = [
    pytest.param("My projects/Architecture repository", id="english-spaces"),
    pytest.param("Мои проекты/Архитектура системы", id="russian-spaces"),
    pytest.param("Mes projets/Architecture été", id="french-accents"),
    pytest.param("Meine Projekte/Änderungen groß", id="german-umlauts"),
    pytest.param("我的项目/系统 架构", id="chinese"),
    pytest.param("私のプロジェクト/システム 設計", id="japanese"),
    pytest.param("내 프로젝트/시스템 설계", id="korean"),
    pytest.param("مشاريعي/بنية النظام", id="arabic"),
    pytest.param("मेरी परियोजनाएं/प्रणाली संरचना", id="hindi"),
    pytest.param("Проекты projects 项目/Система système システム", id="mixed-scripts"),
    pytest.param("Mes projets/Cafe\u0301 architecture", id="combining-accent"),
    pytest.param("Мои  проекты/Архитектура   системы", id="repeated-spaces"),
    pytest.param(" Мои проекты/ Архитектура", id="leading-spaces"),
    pytest.param("Мои проекты /Архитектура  ", id="trailing-spaces"),
]


@pytest.fixture
def localized_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "Пользователи 用户" / "Élodie Иванова"
    home.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def existing_repository(tmp_path: Path, relative_path: str) -> Path:
    # Build elsewhere so path handling failures are observed during indexing,
    # independently of repository creation's own path handling.
    source = tmp_path / "staging-repository"
    create_repository(source, MINIMAL_DECLARATION)
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)
    return target


def file_snapshot(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_index_through_mcp_assigns_uuid_for_existing_repository(tmp_path: Path) -> None:
    root = existing_repository(tmp_path, "existing")
    before = file_snapshot(root)

    async def scenario() -> None:
        indexed = await mcp.call_tool("repository_index", {"repository_path": str(root)})
        response = indexed.structured_content
        assert response["ok"], response
        identifier = response["result"]["repository_id"]
        assert str(UUID(identifier)) == identifier
        assert response["result"]["repository_path"] == str(root.resolve())
        opened = await mcp.call_tool("repository_open", {"repository_id": identifier})
        assert opened.structured_content["ok"], opened
        repeated = await mcp.call_tool("repository_index", {"repository_path": str(root)})
        assert repeated.structured_content == response

    asyncio.run(scenario())
    assert file_snapshot(root) == before


@pytest.mark.parametrize("already_indexed", [False, True])
@pytest.mark.parametrize(
    "failure", ["dsl", "template", "entity", "relation", "matching", "symlink"]
)
def test_index_validates_contents_before_changing_registry(
    tmp_path: Path, already_indexed: bool, failure: str
) -> None:
    root = existing_repository(tmp_path, "existing")
    repository_list()
    if already_indexed:
        assert repository_index(str(root))["ok"]
    index_before = RepositoryRegistry().path.read_bytes()
    declaration = root / "architecture.yaml"
    if failure == "dsl":
        declaration.write_text("invalid", encoding="utf-8")
    elif failure == "template":
        (root / "templates/fact.md").unlink()
    elif failure == "entity":
        (root / "facts/F-0001.md").write_text("no front matter", encoding="utf-8")
    elif failure == "relation":
        (root / "facts/F-0001.md").write_text(
            "---\nrelations:\n- entity: absent\n  files: [X-0001.md]\n---\n",
            encoding="utf-8",
        )
    elif failure == "matching":
        data = yaml.safe_load(declaration.read_text(encoding="utf-8"))
        data["entities"].append({**data["entities"][0], "name": "duplicate"})
        declaration.write_text(yaml.safe_dump(data), encoding="utf-8")
        (root / "facts/F-0001.md").write_text("---\ntitle: Fact\n---\n", encoding="utf-8")
    else:
        external = tmp_path / "external.md"
        external.write_text("---\ntitle: External\n---\n", encoding="utf-8")
        (root / "facts/F-0001.md").symlink_to(external)
    files_before = file_snapshot(root)

    rejected = repository_index(str(root))

    assert not rejected["ok"], rejected
    assert rejected["error"]["code"] in {"INVALID_REPOSITORY", "VALIDATION_ERROR"}
    assert rejected["error"]["message"] != "Unexpected operation failure"
    assert RepositoryRegistry().path.read_bytes() == index_before
    assert file_snapshot(root) == files_before


@pytest.mark.parametrize("relative_path", PATH_CASES)
def test_index_round_trip_preserves_localized_paths_and_files(
    tmp_path: Path, localized_home: Path, relative_path: str
) -> None:
    root = existing_repository(tmp_path, relative_path)
    canonical_path = str(root.resolve())
    before = file_snapshot(root)

    response = repository_index(str(root))
    assert response["ok"], response
    entry = response["result"]
    identifier = entry["repository_id"]
    assert str(UUID(identifier)) == identifier
    assert entry == {"repository_id": identifier, "repository_path": canonical_path}

    # Equivalent spellings must not create duplicate identities.
    for spelling in (str(root), f"{root}/", f"{root}/."):
        assert repository_index(spelling) == response
        assert repository_reindex(spelling) == response

    index_path = localized_home / ".config/arch-repo-mcp/repositories.json"
    assert repository_list() == {
        "ok": True,
        "result": {"index_path": str(index_path), "repositories": [entry]},
    }
    assert json.loads(index_path.read_text(encoding="utf-8")) == {
        "version": 1,
        "repositories": [entry],
    }
    assert RepositoryRegistry().resolve(identifier) == canonical_path
    opened = repository_open(identifier)
    assert opened["ok"], opened
    assert opened["result"]["repository_root"] == canonical_path
    assert file_snapshot(root) == before

    assert repository_unindex(identifier) == response
    assert repository_list()["result"]["repositories"] == []
    assert repository_open(identifier)["error"]["code"] == "NOT_FOUND"
    assert file_snapshot(root) == before
    reindexed = repository_reindex(str(root))
    assert reindexed["ok"], reindexed
    assert reindexed["result"]["repository_id"] != identifier
    assert reindexed["result"]["repository_path"] == canonical_path


def test_localized_index_survives_a_fresh_process(
    tmp_path: Path, localized_home: Path
) -> None:
    root = existing_repository(tmp_path, "Проекты 项目/Архитектура été システム")
    response = repository_index(str(root))
    assert response["ok"], response
    entry = response["result"]
    code = """
import json
import sys
from pathlib import Path

Path.home = classmethod(lambda cls: Path(sys.argv[1]))
from arch_repo_mcp.registry import RepositoryRegistry

registry = RepositoryRegistry()
print(json.dumps({
    "index": registry.list(),
    "resolved": registry.resolve(sys.argv[2]),
    "reindexed": registry.reindex(sys.argv[3]),
}, ensure_ascii=False))
"""
    completed = subprocess.run(
        [
            sys.executable, "-X", "utf8", "-c", code,
            str(localized_home), entry["repository_id"], str(root),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert json.loads(completed.stdout) == {
        "index": {
            "index_path": str(RepositoryRegistry().path),
            "repositories": [entry],
        },
        "resolved": str(root.resolve()),
        "reindexed": entry,
    }


def test_index_keeps_distinct_localized_paths_separate(tmp_path: Path) -> None:
    entries = []
    for name in (
        "Архитектура системы", "Архитектура  системы", "Архитектура системы ", "系统 架构",
    ):
        root = existing_repository(tmp_path, f"Общие проекты/{name}")
        response = repository_index(str(root))
        assert response["ok"], response
        entries.append(response["result"])

    assert len({entry["repository_id"] for entry in entries}) == len(entries)
    assert repository_list()["result"]["repositories"] == entries
    for entry in entries:
        assert RepositoryRegistry().resolve(entry["repository_id"]) == entry["repository_path"]
    assert repository_unindex(entries[1]["repository_id"])["ok"]
    assert repository_list()["result"]["repositories"] == [entries[0], *entries[2:]]


def test_reindex_accepts_localized_declaration_path(tmp_path: Path) -> None:
    root = existing_repository(tmp_path, "Мои проекты/系统 架构")
    declaration_path = "Описание модели/架构 déclaration.yaml"
    target = root / declaration_path
    target.parent.mkdir()
    (root / "architecture.yaml").rename(target)

    response = repository_index(str(root), declaration_path)
    assert response["ok"], response
    assert repository_reindex(str(root), declaration_path) == response
    opened = repository_open(response["result"]["repository_id"], declaration_path)
    assert opened["ok"], opened
    assert opened["result"]["repository_root"] == str(root.resolve())


@pytest.mark.parametrize(
    ("invalid_kind", "error_code"),
    [
        ("missing", "NOT_FOUND"),
        ("non-git", "INVALID_REPOSITORY"),
        ("nested", "INVALID_REPOSITORY"),
        ("relative", "VALIDATION_ERROR"),
        ("traversal", "VALIDATION_ERROR"),
    ],
)
def test_invalid_localized_paths_do_not_change_index(
    tmp_path: Path, invalid_kind: str, error_code: str
) -> None:
    root = existing_repository(tmp_path, "Мои проекты/系统 架构")
    response = repository_index(str(root))
    assert response["ok"], response
    before = RepositoryRegistry().path.read_bytes()
    candidates = {
        "missing": str(tmp_path / "Нет такого репозитория 不存在"),
        "non-git": str(root.parent),
        "nested": str(root / "facts"),
        "relative": "Мои проекты/系统 架构",
        "traversal": f"{root}/../{root.name}",
    }

    rejected = repository_index(candidates[invalid_kind])
    assert not rejected["ok"], rejected
    assert rejected["error"]["code"] == error_code
    assert RepositoryRegistry().path.read_bytes() == before
