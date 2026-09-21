from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import arch_repo_mcp.remote_sync as remote_sync_module
from arch_repo_mcp.entities import update_entity
from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.local_git import configure_remote, repository_commit, repository_status
from arch_repo_mcp.remote_sync import (
    clone_repository,
    fetch_repository,
    publish_repository,
    pull_repository,
)
from arch_repo_mcp.repository import create_repository, validate_repository

DECLARATION = """\
declaration:
  kind: architecture_repository
  version: v2
entities:
  - name: fact
    description: A verified architecture fact.
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


def test_pull_fast_forwards_only_after_fetched_tree_validation(tmp_path: Path) -> None:
    source, remote = _make_source_and_remote(tmp_path)
    consumer = _clone_consumer(remote, tmp_path)
    previous_head = repository_status(consumer).head
    update_entity(source, "fact", "facts/F-0001.md", REMOTE_CONTENT)
    remote_head = repository_commit(source, "Remote fast-forward change").commit
    publish_repository(source, "origin", "main")

    result = pull_repository(consumer, "origin", "main")

    assert result.previous_head == previous_head
    assert result.current_head == remote_head
    assert result.outcome == "fast_forward"
    assert repository_status(consumer).head == remote_head
    assert (consumer / "facts" / "F-0001.md").read_text(encoding="utf-8") == REMOTE_CONTENT


def test_pull_rejects_dirty_worktree_before_fetch(tmp_path: Path) -> None:
    _, remote = _make_source_and_remote(tmp_path)
    consumer = _clone_consumer(remote, tmp_path)
    update_entity(consumer, "fact", "facts/F-0001.md", LOCAL_CONTENT)
    fetch_head_before = _git(
        consumer,
        "rev-parse",
        "--verify",
        "FETCH_HEAD",
        check=False,
    ).stdout.strip()

    with pytest.raises(ArchRepoError) as captured:
        pull_repository(consumer, "origin", "main")

    fetch_head_after = _git(
        consumer,
        "rev-parse",
        "--verify",
        "FETCH_HEAD",
        check=False,
    ).stdout.strip()
    assert captured.value.code is ErrorCode.DIRTY_WORKTREE
    assert fetch_head_after == fetch_head_before
    assert (consumer / "facts" / "F-0001.md").read_text(encoding="utf-8") == LOCAL_CONTENT


def test_pull_rejects_divergence_without_conflict_resolution(tmp_path: Path) -> None:
    source, remote = _make_source_and_remote(tmp_path)
    consumer = _clone_consumer(remote, tmp_path)

    update_entity(source, "fact", "facts/F-0001.md", REMOTE_CONTENT)
    repository_commit(source, "Remote conflicting change")
    publish_repository(source, "origin", "main")
    update_entity(consumer, "fact", "facts/F-0001.md", LOCAL_CONTENT)
    local_head = repository_commit(consumer, "Local conflicting change").commit

    with pytest.raises(ArchRepoError) as captured:
        pull_repository(consumer, "origin", "main")

    assert captured.value.code is ErrorCode.CONFLICT
    assert repository_status(consumer).head == local_head
    assert repository_status(consumer).entries == ()
    assert _git(consumer, "diff", "--name-only", "--diff-filter=U").stdout == ""
    assert (consumer / "facts" / "F-0001.md").read_text(encoding="utf-8") == LOCAL_CONTENT


def test_pull_rejects_invalid_fetched_tree_before_integration(tmp_path: Path) -> None:
    source, remote = _make_source_and_remote(tmp_path)
    consumer = _clone_consumer(remote, tmp_path)
    local_head = repository_status(consumer).head
    (source / "facts" / "F-0001.md").write_text("invalid front matter", encoding="utf-8")
    _git(source, "add", "facts/F-0001.md")
    _git(source, "commit", "--quiet", "-m", "Invalid remote architecture")
    _git(source, "push", "--quiet", "origin", "main")

    with pytest.raises(ArchRepoError) as captured:
        pull_repository(consumer, "origin", "main")

    assert captured.value.code is ErrorCode.INVALID_REPOSITORY
    assert repository_status(consumer).head == local_head
    assert repository_status(consumer).entries == ()
    assert (consumer / "facts" / "F-0001.md").read_text(encoding="utf-8") == INITIAL_CONTENT


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


@pytest.mark.parametrize(
    ("diagnostic", "expected"),
    [
        ("fatal: Authentication failed", ErrorCode.AUTHENTICATION_ERROR),
        ("remote: Write access to repository not granted", ErrorCode.PERMISSION_DENIED),
        ("fatal: unable to access: Could not resolve host", ErrorCode.NETWORK_ERROR),
        ("fatal: SSL certificate problem: self-signed certificate", ErrorCode.TLS_ERROR),
        ("fatal: Connection timed out", ErrorCode.TIMEOUT),
        ("remote: Repository not found", ErrorCode.NOT_FOUND),
        ("fatal: server does not support requested capability", ErrorCode.PROVIDER_CAPABILITY_GAP),
        ("! [rejected] main -> main (non-fast-forward)", ErrorCode.NON_FAST_FORWARD),
        ("fatal: unclassified provider response", ErrorCode.REMOTE_ERROR),
    ],
)
def test_remote_diagnostics_map_to_normalized_errors(
    diagnostic: str,
    expected: ErrorCode,
) -> None:
    result = subprocess.CompletedProcess(
        args=["git", "fetch"],
        returncode=1,
        stdout="",
        stderr=diagnostic,
    )

    assert remote_sync_module._classify_remote_failure(result) is expected


def test_remote_error_does_not_expose_transport_diagnostic() -> None:
    result = subprocess.CompletedProcess(
        args=["git", "fetch"],
        returncode=1,
        stdout="",
        stderr="Authentication failed for https://user:TOP-SECRET@example.invalid/repo.git",
    )

    with pytest.raises(ArchRepoError) as captured:
        remote_sync_module._raise_remote_failure(result, operation="fetch")

    assert captured.value.code is ErrorCode.AUTHENTICATION_ERROR
    assert "TOP-SECRET" not in captured.value.message
    assert "TOP-SECRET" not in str(captured.value.details)


def test_network_timeout_is_normalized_without_subprocess_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_timeout(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise subprocess.TimeoutExpired(["git", "fetch"], timeout=120)

    monkeypatch.setattr(remote_sync_module.subprocess, "run", raise_timeout)

    with pytest.raises(ArchRepoError) as captured:
        remote_sync_module._run_git(
            None,
            ["fetch", "origin"],
            operation="fetch",
            network=True,
        )

    assert captured.value.code is ErrorCode.TIMEOUT
    assert captured.value.details == {}


def test_missing_remote_repository_is_normalized_as_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "missing.git"

    with pytest.raises(ArchRepoError) as captured:
        clone_repository(missing.as_uri(), tmp_path / "clone")

    assert captured.value.code is ErrorCode.NOT_FOUND
    assert not (tmp_path / "clone").exists()


def test_remote_operations_do_not_run_implicit_sync_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, remote = _make_source_and_remote(tmp_path)
    consumer = _clone_consumer(remote, tmp_path)
    original_run_git = remote_sync_module._run_git
    commands: list[tuple[str, ...]] = []

    def record_run_git(
        root: Path | None,
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        commands.append(tuple(arguments))
        return original_run_git(root, arguments, **kwargs)

    monkeypatch.setattr(remote_sync_module, "_run_git", record_run_git)
    fetch_repository(consumer, "origin")
    fetch_commands = commands.copy()
    commands.clear()

    update_entity(source, "fact", "facts/F-0001.md", REMOTE_CONTENT)
    repository_commit(source, "Explicit publish command")
    publish_repository(source, "origin", "main")
    publish_commands = commands.copy()

    assert any(command[0] == "fetch" for command in fetch_commands)
    assert all("merge" not in command and "push" not in command for command in fetch_commands)
    assert any(command[0] == "push" for command in publish_commands)
    assert all("fetch" not in command and "merge" not in command for command in publish_commands)
