from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from arch_repo_mcp.entities import update_entity
from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.local_git import configure_remote, repository_commit, repository_status
from arch_repo_mcp.remote_sync import clone_repository, fetch_repository, publish_repository
from arch_repo_mcp.repository import create_repository, validate_repository

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

REMOTE_CONTENT = """\
---
title: Remote fact
---

Content published by the remote author.
"""

LOCAL_CONTENT = """\
---
title: Local fact
---

Content committed by the local author.
"""


def _git(
    repository: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _configure_identity(repository: Path) -> None:
    _git(repository, "config", "user.name", "ArchRepo Sync Test")
    _git(repository, "config", "user.email", "sync@example.invalid")


def _make_source_and_remote(tmp_path: Path) -> tuple[Path, Path]:
    bundle = tmp_path / "bundle"
    (bundle / "templates").mkdir(parents=True)
    declaration = bundle / "minimal.yaml"
    declaration.write_text(DECLARATION, encoding="utf-8")
    (bundle / "templates" / "fact.md").write_text(INITIAL_CONTENT, encoding="utf-8")

    source = tmp_path / "source"
    create_repository(source, declaration)
    (source / "facts" / "F-0001.md").write_text(INITIAL_CONTENT, encoding="utf-8")
    _configure_identity(source)
    repository_commit(source, "Initial architecture")

    remote = tmp_path / "remote.git"
    _git(tmp_path, "clone", "--quiet", "--bare", source.as_uri(), str(remote))
    configure_remote(source, "origin", remote.as_uri())
    return source, remote


def _clone_consumer(remote: Path, tmp_path: Path) -> Path:
    consumer = tmp_path / "consumer"
    clone_repository(remote.as_uri(), consumer)
    _configure_identity(consumer)
    return consumer


def test_clone_creates_valid_local_repository(tmp_path: Path) -> None:
    source, remote = _make_source_and_remote(tmp_path)
    target = tmp_path / "clone"

    result = clone_repository(remote.as_uri(), target)

    assert result.repository_root == str(target.resolve())
    assert result.branch == "main"
    assert result.head == repository_status(source).head
    assert validate_repository(target).valid
    assert (target / "facts" / "F-0001.md").read_text(encoding="utf-8") == INITIAL_CONTENT


def test_clone_rolls_back_invalid_architecture_repository(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    _git(plain, "init", "--quiet", "--initial-branch", "main")
    _configure_identity(plain)
    (plain / "README.md").write_text("not an architecture repository", encoding="utf-8")
    _git(plain, "add", "README.md")
    _git(plain, "commit", "--quiet", "-m", "Plain repository")
    remote = tmp_path / "plain.git"
    _git(tmp_path, "clone", "--quiet", "--bare", plain.as_uri(), str(remote))
    target = tmp_path / "invalid-clone"

    with pytest.raises(ArchRepoError) as captured:
        clone_repository(remote.as_uri(), target)

    assert captured.value.code is ErrorCode.INVALID_REPOSITORY
    assert not target.exists()
    assert not list(tmp_path.glob(".invalid-clone.clone-*"))


def test_fetch_updates_remote_state_without_integrating_worktree(tmp_path: Path) -> None:
    source, remote = _make_source_and_remote(tmp_path)
    consumer = _clone_consumer(remote, tmp_path)
    local_head = repository_status(consumer).head

    update_entity(source, "fact", "facts/F-0001.md", REMOTE_CONTENT)
    published_commit = repository_commit(source, "Publish remote change").commit
    publish_repository(source, "origin", "main")

    result = fetch_repository(consumer, "origin")

    assert result.local_head == local_head
    assert result.fetched_head == published_commit
    assert repository_status(consumer).head == local_head
    assert (consumer / "facts" / "F-0001.md").read_text(encoding="utf-8") == INITIAL_CONTENT


def test_fetch_preserves_dirty_worktree(tmp_path: Path) -> None:
    source, remote = _make_source_and_remote(tmp_path)
    consumer = _clone_consumer(remote, tmp_path)
    update_entity(consumer, "fact", "facts/F-0001.md", LOCAL_CONTENT)

    result = fetch_repository(consumer, "origin")

    assert result.remote == "origin"
    assert (consumer / "facts" / "F-0001.md").read_text(encoding="utf-8") == LOCAL_CONTENT
    assert repository_status(consumer).entries


def test_publish_pushes_current_commit_without_setting_upstream(tmp_path: Path) -> None:
    _, remote = _make_source_and_remote(tmp_path)
    consumer = _clone_consumer(remote, tmp_path)
    update_entity(consumer, "fact", "facts/F-0001.md", LOCAL_CONTENT)
    commit = repository_commit(consumer, "Publish local architecture change").commit
    upstream_before = _git(
        consumer,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    ).stdout.strip()

    result = publish_repository(consumer, "origin", "main")

    remote_head = _git(remote, "rev-parse", "refs/heads/main").stdout.strip()
    upstream_after = _git(
        consumer,
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{upstream}",
    ).stdout.strip()
    assert result.commit == commit
    assert remote_head == commit
    assert upstream_after == upstream_before


def test_publish_rejects_dirty_worktree(tmp_path: Path) -> None:
    _, remote = _make_source_and_remote(tmp_path)
    consumer = _clone_consumer(remote, tmp_path)
    remote_head = _git(remote, "rev-parse", "refs/heads/main").stdout.strip()
    update_entity(consumer, "fact", "facts/F-0001.md", LOCAL_CONTENT)

    with pytest.raises(ArchRepoError) as captured:
        publish_repository(consumer, "origin", "main")

    assert captured.value.code is ErrorCode.DIRTY_WORKTREE
    assert _git(remote, "rev-parse", "refs/heads/main").stdout.strip() == remote_head


def test_publish_maps_non_fast_forward_without_force(tmp_path: Path) -> None:
    source, remote = _make_source_and_remote(tmp_path)
    consumer = _clone_consumer(remote, tmp_path)

    update_entity(source, "fact", "facts/F-0001.md", REMOTE_CONTENT)
    remote_commit = repository_commit(source, "Remote change").commit
    publish_repository(source, "origin", "main")

    update_entity(consumer, "fact", "facts/F-0001.md", LOCAL_CONTENT)
    repository_commit(consumer, "Divergent local change")
    with pytest.raises(ArchRepoError) as captured:
        publish_repository(consumer, "origin", "main")

    assert captured.value.code is ErrorCode.NON_FAST_FORWARD
    assert _git(remote, "rev-parse", "refs/heads/main").stdout.strip() == remote_commit


def test_sync_rejects_embedded_http_credentials_before_transport(tmp_path: Path) -> None:
    _, remote = _make_source_and_remote(tmp_path)
    consumer = _clone_consumer(remote, tmp_path)
    _git(consumer, "remote", "set-url", "origin", "https://user:token@example.invalid/repo.git")

    with pytest.raises(ArchRepoError) as fetch_error:
        fetch_repository(consumer, "origin")
    with pytest.raises(ArchRepoError) as clone_error:
        clone_repository(
            "https://user:token@example.invalid/repo.git",
            tmp_path / "credential-clone",
        )

    assert fetch_error.value.code is ErrorCode.AUTHENTICATION_ERROR
    assert clone_error.value.code is ErrorCode.AUTHENTICATION_ERROR
    assert not (tmp_path / "credential-clone").exists()
