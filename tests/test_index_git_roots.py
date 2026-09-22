"""Index identity follows the selected filesystem directory, including macOS aliases."""

import json
import subprocess
import unicodedata
from pathlib import Path

import pytest

from arch_repo_mcp.creation_guide import creation_guide
from arch_repo_mcp.registry import RepositoryRegistry
from arch_repo_mcp.repository import create_repository
from arch_repo_mcp.server import (
    repository_clone,
    repository_create,
    repository_index,
    repository_list,
    repository_open,
    repository_reindex,
    repository_status,
)

LOCALIZED_PATH = (
    "Ростелеком/Проекты/Технологическая платформа МО АП/Вторая очередь/"
    "Репозиторий/Архитектура СЗ"
)


def git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *arguments], check=True, capture_output=True, timeout=30
    )


def create_with_index(path: Path) -> dict:
    example = creation_guide()["examples"][0]
    response = repository_create(
        str(path), example["architecture_yaml"], example["templates"]
    )
    assert response["ok"], response
    return response["result"]


@pytest.mark.parametrize("parent_git", [False, True])
@pytest.mark.parametrize(
    "own_git", ["directory", "worktree", "missing", "invalid", "empty", "symlink"]
)
def test_localized_final_directory_controls_indexing(
    tmp_path: Path, parent_git: bool, own_git: str
) -> None:
    parent = tmp_path / "Родительский каталог"
    parent.mkdir()
    if parent_git:
        git(parent, "init", "--quiet")
    target = parent / LOCALIZED_PATH
    target.parent.mkdir(parents=True)
    if own_git == "directory":
        created = create_with_index(target)
    elif own_git == "worktree":
        source = tmp_path / "Исходный репозиторий"
        create_repository(source)
        git(source, "add", ".")
        git(source, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-qm", "initial")
        git(source, "worktree", "add", "--detach", str(target))
        assert (target / ".git").is_file()
    else:
        target.mkdir()
        if own_git == "invalid":
            (target / ".git").write_text("not a Git worktree", encoding="utf-8")
        elif own_git == "empty":
            (target / ".git").mkdir()
        elif own_git == "symlink":
            source = tmp_path / "Другой репозиторий"
            create_repository(source)
            (target / ".git").symlink_to(source / ".git", target_is_directory=True)

    for tool in (repository_index, repository_reindex):
        response = tool(str(target))
        if own_git in {"missing", "invalid", "empty", "symlink"}:
            assert response["error"]["code"] == "INVALID_REPOSITORY", response
            assert repository_list()["result"]["repositories"] == []
        else:
            assert response["ok"], response
            entry = response["result"]
            assert Path(entry["repository_path"]).samefile(target)
            if own_git == "directory":
                assert entry["repository_id"] == created["repository_id"]
            assert repository_open(entry["repository_id"])["ok"]
            assert repository_status(entry["repository_id"])["ok"]
            assert repository_list()["result"]["repositories"] == [entry]


@pytest.mark.parametrize("variant", ["NFD", "case"])
def test_index_reindex_and_legacy_entries_preserve_identity_for_same_directory(
    tmp_path: Path, variant: str
) -> None:
    target = tmp_path / LOCALIZED_PATH
    target.parent.mkdir(parents=True)
    created = create_with_index(target)
    alias = Path(
        unicodedata.normalize("NFD", str(target)) if variant == "NFD"
        else str(target).replace("Архитектура СЗ", "архитектура сз")
    )
    if not alias.exists() or not alias.samefile(target):
        pytest.skip("This filesystem treats these spellings as different directories")
    for tool in (repository_index, repository_reindex):
        assert tool(str(alias))["result"]["repository_id"] == created["repository_id"]
    registry = RepositoryRegistry()
    # Existing indexes may have stored an alternate spelling before this fix.
    data = json.loads(registry.path.read_text(encoding="utf-8"))
    data["repositories"][0]["repository_path"] = str(alias)
    registry.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert RepositoryRegistry().resolve(created["repository_id"]) == str(alias)
    assert repository_open(created["repository_id"])["ok"]
    for spelling in (target, alias):
        assert repository_reindex(str(spelling))["result"]["repository_id"] == created[
            "repository_id"
        ]
    assert len(repository_list()["result"]["repositories"]) == 1


@pytest.mark.parametrize("variant", ["NFD", "case"])
def test_distinct_directories_are_not_merged_by_text_normalization(
    tmp_path: Path, variant: str
) -> None:
    target = tmp_path / "Репозиторий"
    create_repository(target)
    other = Path(unicodedata.normalize("NFD", str(target))) if variant == "NFD" else (
        tmp_path / "репозиторий"
    )
    if other.exists():
        pytest.skip("This filesystem treats these spellings as the same directory")
    create_repository(other)
    first = repository_index(str(target))
    second = repository_index(str(other))
    assert first["ok"] and second["ok"]
    assert first["result"]["repository_id"] != second["result"]["repository_id"]


def test_inherited_git_paths_do_not_redirect_creation_indexing_or_uuid_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = tmp_path / "Другой репозиторий"
    create_repository(other)
    target = tmp_path / LOCALIZED_PATH
    target.parent.mkdir(parents=True)
    create_repository(target)
    (target / "facts/F-0999.md").write_text("---\ntitle: Target only\n---\n", encoding="utf-8")
    git(target, "add", ".")
    git(target, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "target commit")
    before = {p.relative_to(other): p.read_bytes() for p in other.rglob("*") if p.is_file()}
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_COMMON_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git/index"))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(other / ".git/objects"))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(target))
    indexed = repository_index(str(target))
    assert indexed["ok"], indexed
    assert repository_reindex(str(target)) == indexed
    status = repository_status(indexed["result"]["repository_id"])
    assert status["result"]["head"] is not None  # The unrelated repository has no commits.
    assert status["result"]["clean"]
    cloned = repository_clone(target.as_uri(), str(tmp_path / "Копия репозитория"))
    assert cloned["ok"], cloned
    for identifier in (
        indexed["result"]["repository_id"],
        create_with_index(tmp_path / "Новый репозиторий")["repository_id"],
        cloned["result"]["repository_id"],
    ):
        assert repository_open(identifier)["ok"]
        assert repository_status(identifier)["ok"]
    assert {p.relative_to(other): p.read_bytes() for p in other.rglob("*") if p.is_file()} == before


def test_genuine_git_root_mismatch_reports_both_paths(tmp_path: Path) -> None:
    target = tmp_path / "Запрошенный репозиторий"
    create_repository(target)
    other = tmp_path / "Другой каталог"
    other.mkdir()
    git(target, "config", "core.worktree", str(other))
    response = repository_index(str(target))
    assert response["error"]["code"] == "INVALID_REPOSITORY", response
    assert response["error"]["details"] == {
        "repository_path": str(target.resolve()), "git_root": str(other.resolve())
    }
    assert repository_list()["result"]["repositories"] == []
