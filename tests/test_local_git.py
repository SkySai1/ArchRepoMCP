from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.local_git import (
    configure_remote,
    create_branch,
    list_branches,
    list_remotes,
    repository_commit,
    repository_diff,
    repository_history,
    repository_status,
    switch_branch,
)
from arch_repo_mcp.repository import create_repository

DECLARATION = """\
declaration:
  kind: architecture_repository
  version: v2
entities:
  - name: fact
    files:
      path: {match: exact, value: facts}
      filename: {match: regex, value: '^F-[0-9]{4}\\.md$'}
      format: markdown_front_matter
      template: templates/fact.md
"""

INITIAL_CONTENT = """\
---
title: Initial fact
---

Initial architecture content.
"""

UPDATED_CONTENT = """\
---
title: Updated fact
---

Updated architecture content.
"""


def _git(repository: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _make_repository(tmp_path: Path, *, commit: bool = True) -> Path:
    bundle = tmp_path / "bundle"
    (bundle / "templates").mkdir(parents=True)
    declaration = bundle / "minimal.yaml"
    declaration.write_text(DECLARATION, encoding="utf-8")
    (bundle / "templates" / "fact.md").write_text(INITIAL_CONTENT, encoding="utf-8")
    repository = tmp_path / "repository"
    create_repository(repository, declaration)
    (repository / "facts" / "F-0001.md").write_text(INITIAL_CONTENT, encoding="utf-8")
    if commit:
        _git(repository, "config", "user.name", "ArchRepo Test")
        _git(repository, "config", "user.email", "archrepo@example.invalid")
        _git(repository, "add", "--", "architecture.yaml", "templates/fact.md", "facts/F-0001.md")
        _git(repository, "commit", "--quiet", "-m", "Initial architecture")
    return repository


def test_status_reports_clean_branch_and_head(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    status = repository_status(repository)

    assert status.branch == "main"
    assert not status.detached
    assert status.head is not None
    assert status.entries == ()
    assert status.as_dict()["clean"] is True


def test_status_distinguishes_worktree_and_index_changes(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    fact = repository / "facts" / "F-0001.md"
    fact.write_text(UPDATED_CONTENT, encoding="utf-8")

    worktree_status = repository_status(repository)
    _git(repository, "add", "--", "facts/F-0001.md")
    index_status = repository_status(repository)

    assert worktree_status.entries[0].path == "facts/F-0001.md"
    assert worktree_status.entries[0].index_status == " "
    assert worktree_status.entries[0].worktree_status == "M"
    assert index_status.entries[0].index_status == "M"
    assert index_status.entries[0].worktree_status == " "


def test_git_inspection_remains_available_when_dsl_content_is_invalid(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    (repository / "facts" / "F-0001.md").write_text(
        "invalid front matter", encoding="utf-8"
    )

    status = repository_status(repository)
    diff = repository_diff(repository)

    assert status.entries[0].path == "facts/F-0001.md"
    assert "+invalid front matter" in diff


def test_diff_returns_worktree_and_staged_patches(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    (repository / "facts" / "F-0001.md").write_text(UPDATED_CONTENT, encoding="utf-8")

    worktree_diff = repository_diff(repository)
    _git(repository, "add", "--", "facts/F-0001.md")
    staged_diff = repository_diff(repository, staged=True)

    assert "-Initial architecture content." in worktree_diff
    assert "+Updated architecture content." in worktree_diff
    assert "-Initial architecture content." in staged_diff
    assert "+Updated architecture content." in staged_diff


def test_diff_rejects_incompatible_arguments(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    with pytest.raises(ArchRepoError) as captured:
        repository_diff(repository, staged=True, base_revision="HEAD")

    assert captured.value.code is ErrorCode.VALIDATION_ERROR


def test_history_returns_local_commit_metadata(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    (repository / "facts" / "F-0001.md").write_text(UPDATED_CONTENT, encoding="utf-8")
    _git(repository, "add", "--", "facts/F-0001.md")
    _git(repository, "commit", "--quiet", "-m", "Update architecture fact")

    history = repository_history(repository)

    assert [item.subject for item in history] == [
        "Update architecture fact",
        "Initial architecture",
    ]
    assert history[0].parents == (history[1].commit,)
    assert history[0].author_name == "ArchRepo Test"
    assert history[0].author_email == "archrepo@example.invalid"


def test_history_is_empty_for_unborn_branch(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path, commit=False)

    assert repository_history(repository) == []


def test_branch_creation_does_not_switch_current_branch(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    created = create_branch(repository, "architecture-review")
    branches = list_branches(repository)

    assert created.name == "architecture-review"
    assert not created.current
    assert [(branch.name, branch.current) for branch in branches] == [
        ("architecture-review", False),
        ("main", True),
    ]
    assert repository_status(repository).branch == "main"


def test_branch_creation_rejects_invalid_or_duplicate_name(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    with pytest.raises(ArchRepoError) as invalid:
        create_branch(repository, "invalid branch")
    assert invalid.value.code is ErrorCode.VALIDATION_ERROR

    create_branch(repository, "architecture-review")
    with pytest.raises(ArchRepoError) as duplicate:
        create_branch(repository, "architecture-review")
    assert duplicate.value.code is ErrorCode.CONFLICT


def test_commit_creates_initial_commit_from_controlled_paths(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path, commit=False)
    _git(repository, "config", "user.name", "ArchRepo Test")
    _git(repository, "config", "user.email", "archrepo@example.invalid")

    result = repository_commit(repository, "Create architecture repository")

    assert result.branch == "main"
    assert result.message == "Create architecture repository"
    assert result.paths == (
        "architecture.yaml",
        "facts/F-0001.md",
        "templates/fact.md",
    )
    assert repository_status(repository).entries == ()
    assert repository_history(repository)[0].commit == result.commit


def test_commit_excludes_uncontrolled_staged_files(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    (repository / "facts" / "F-0001.md").write_text(UPDATED_CONTENT, encoding="utf-8")
    (repository / "notes.txt").write_text("not controlled by DSL", encoding="utf-8")
    _git(repository, "add", "--", "notes.txt")

    result = repository_commit(repository, "Update controlled architecture fact")
    status = repository_status(repository)

    assert result.paths == ("facts/F-0001.md",)
    notes = next(entry for entry in status.entries if entry.path == "notes.txt")
    assert notes.index_status == "A"
    committed_files = _git(repository, "show", "--format=", "--name-only", "HEAD").stdout
    assert "facts/F-0001.md" in committed_files
    assert "notes.txt" not in committed_files


def test_commit_requires_valid_repository_and_controlled_changes(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    with pytest.raises(ArchRepoError) as unchanged:
        repository_commit(repository, "No changes")
    assert unchanged.value.code is ErrorCode.CONFLICT

    (repository / "facts" / "F-0001.md").write_text("invalid", encoding="utf-8")
    with pytest.raises(ArchRepoError) as invalid:
        repository_commit(repository, "Invalid change")
    assert invalid.value.code is ErrorCode.INVALID_REPOSITORY
    assert repository_history(repository)[0].subject == "Initial architecture"


def test_branch_switch_rejects_dirty_worktree(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    create_branch(repository, "architecture-review")
    (repository / "facts" / "F-0001.md").write_text(UPDATED_CONTENT, encoding="utf-8")

    with pytest.raises(ArchRepoError) as captured:
        switch_branch(repository, "architecture-review")

    assert captured.value.code is ErrorCode.DIRTY_WORKTREE
    assert repository_status(repository).branch == "main"


def test_branch_switch_validates_target_and_restores_invalid_branch(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    create_branch(repository, "invalid-architecture")
    _git(repository, "switch", "--quiet", "invalid-architecture")
    (repository / "facts" / "F-0001.md").write_text("invalid", encoding="utf-8")
    _git(repository, "add", "--", "facts/F-0001.md")
    _git(repository, "commit", "--quiet", "-m", "Break architecture content")
    _git(repository, "switch", "--quiet", "main")

    with pytest.raises(ArchRepoError) as captured:
        switch_branch(repository, "invalid-architecture")

    assert captured.value.code is ErrorCode.INVALID_REPOSITORY
    assert repository_status(repository).branch == "main"
    assert (repository / "facts" / "F-0001.md").read_text(encoding="utf-8") == INITIAL_CONTENT


def test_branch_switch_moves_to_valid_local_branch(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    create_branch(repository, "architecture-review")

    switched = switch_branch(repository, "architecture-review")

    assert switched.current
    assert switched.name == "architecture-review"
    assert repository_status(repository).branch == "architecture-review"


def test_remote_configuration_is_local_and_explicitly_replaceable(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    created = configure_remote(repository, "origin", "https://example.com/team/architecture.git")

    assert created.fetch_urls == ("https://example.com/team/architecture.git",)
    with pytest.raises(ArchRepoError) as duplicate:
        configure_remote(repository, "origin", "https://example.com/team/replacement.git")
    assert duplicate.value.code is ErrorCode.CONFLICT

    replaced = configure_remote(
        repository,
        "origin",
        "ssh://git@example.com/team/architecture.git",
        replace=True,
    )
    assert replaced.fetch_urls == ("ssh://example.com/team/architecture.git",)
    assert [remote.name for remote in list_remotes(repository)] == ["origin"]


def test_remote_configuration_rejects_embedded_http_credentials(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    with pytest.raises(ArchRepoError) as captured:
        configure_remote(repository, "origin", "https://user:token@example.com/repository.git")

    assert captured.value.code is ErrorCode.VALIDATION_ERROR
    assert list_remotes(repository) == []


def test_remote_listing_redacts_credentials_from_existing_configuration(
    tmp_path: Path,
) -> None:
    repository = _make_repository(tmp_path)
    _git(
        repository,
        "remote",
        "add",
        "legacy",
        "https://user:secret-token@example.com/repository.git?signature=secret",
    )

    remote = list_remotes(repository)[0]

    assert remote.fetch_urls == ("https://example.com/repository.git",)
    assert "secret" not in str(remote.as_dict())
    assert "user" not in str(remote.as_dict())
