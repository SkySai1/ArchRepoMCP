"""Explicit provider-independent synchronization through standard Git transport."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.git_environment import git_environment
from arch_repo_mcp.local_git import list_remotes, repository_status
from arch_repo_mcp.repository import (
    DEFAULT_DECLARATION_PATH,
    discover_repository_root,
    open_repository,
    validate_repository,
)

_NETWORK_TIMEOUT_SECONDS = 120
_LOCAL_GIT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True, slots=True)
class CloneResult:
    repository_root: str
    branch: str | None
    head: str | None
    declaration_path: str

    def as_dict(self) -> dict[str, str | None]:
        return {
            "repository_root": self.repository_root,
            "branch": self.branch,
            "head": self.head,
            "declaration_path": self.declaration_path,
        }


@dataclass(frozen=True, slots=True)
class FetchResult:
    remote: str
    local_head: str | None
    fetched_head: str | None
    tags_included: bool
    pruned: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "remote": self.remote,
            "local_head": self.local_head,
            "fetched_head": self.fetched_head,
            "tags_included": self.tags_included,
            "pruned": self.pruned,
        }


@dataclass(frozen=True, slots=True)
class PullResult:
    remote: str
    remote_branch: str
    local_branch: str
    previous_head: str
    current_head: str
    outcome: str

    def as_dict(self) -> dict[str, str]:
        return {
            "remote": self.remote,
            "remote_branch": self.remote_branch,
            "local_branch": self.local_branch,
            "previous_head": self.previous_head,
            "current_head": self.current_head,
            "outcome": self.outcome,
        }


@dataclass(frozen=True, slots=True)
class PublishResult:
    remote: str
    local_branch: str
    remote_branch: str
    commit: str

    def as_dict(self) -> dict[str, str]:
        return {
            "remote": self.remote,
            "local_branch": self.local_branch,
            "remote_branch": self.remote_branch,
            "commit": self.commit,
        }


def clone_repository(
    remote_url: str,
    target_path: str | Path,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
    *,
    branch: str | None = None,
    include_tags: bool = False,
) -> CloneResult:
    """Clone into a new local path and expose it only after repository validation."""

    _validate_transport_url(remote_url)
    if branch is not None:
        _validate_branch_argument(branch)
    target = _resolve_new_target(target_path)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.clone-", dir=str(target.parent))
    ).resolve()
    try:
        arguments = [
            "clone",
            "--no-recurse-submodules",
            "--tags" if include_tags else "--no-tags",
        ]
        if branch is not None:
            arguments.extend(["--branch", branch])
        arguments.extend(["--", remote_url, str(staging)])
        _run_git(None, arguments, operation="clone", network=True)
        report = validate_repository(staging, declaration_path)
        if not report.valid:
            raise ArchRepoError(
                ErrorCode.INVALID_REPOSITORY,
                "Cloned repository did not pass validation",
                details=report.as_dict(),
            )
        status = repository_status(staging)
        staging.replace(target)
    except ArchRepoError:
        raise
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Cloned repository could not be finalized",
            details={"path": str(target)},
        ) from exc
    finally:
        if staging.exists():
            _remove_tree(staging)

    return CloneResult(
        repository_root=str(target),
        branch=status.branch,
        head=status.head,
        declaration_path=declaration_path,
    )


def fetch_repository(
    repository_path: str | Path,
    remote: str,
    *,
    include_tags: bool = False,
    prune: bool = False,
) -> FetchResult:
    """Fetch explicitly from one configured remote without integrating changes."""

    root = discover_repository_root(repository_path)
    _require_safe_remote(root, remote)
    before = repository_status(root)
    arguments = [
        "fetch",
        "--recurse-submodules=no",
        "--tags" if include_tags else "--no-tags",
        "--prune" if prune else "--no-prune",
        "--",
        remote,
    ]
    _run_git(root, arguments, operation="fetch", network=True)
    fetched_head = _optional_revision(root, "FETCH_HEAD")
    return FetchResult(
        remote=remote,
        local_head=before.head,
        fetched_head=fetched_head,
        tags_included=include_tags,
        pruned=prune,
    )


def pull_repository(
    repository_path: str | Path,
    remote: str,
    remote_branch: str,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
) -> PullResult:
    """Fetch and integrate only a validated fast-forward into a clean local branch."""

    context = open_repository(repository_path, declaration_path)
    before = repository_status(context.root)
    if before.entries:
        raise ArchRepoError(
            ErrorCode.DIRTY_WORKTREE,
            "Pull requires a clean working tree and index",
            details={"changed_paths": [entry.path for entry in before.entries]},
        )
    if before.branch is None or before.head is None:
        raise ArchRepoError(
            ErrorCode.CONFLICT,
            "Pull requires a local branch with at least one commit",
        )
    _validate_branch_argument(remote_branch)
    _require_safe_remote(context.root, remote)

    _run_git(
        context.root,
        [
            "fetch",
            "--recurse-submodules=no",
            "--no-tags",
            "--no-prune",
            "--",
            remote,
            f"refs/heads/{remote_branch}",
        ],
        operation="pull fetch",
        network=True,
    )
    fetched_head = _optional_revision(context.root, "FETCH_HEAD")
    if fetched_head is None:
        raise ArchRepoError(
            ErrorCode.NOT_FOUND,
            "Remote branch did not produce a fetched commit",
            details={"remote": remote, "branch": remote_branch},
        )

    if fetched_head == before.head:
        return PullResult(
            remote=remote,
            remote_branch=remote_branch,
            local_branch=before.branch,
            previous_head=before.head,
            current_head=before.head,
            outcome="up_to_date",
        )
    if _is_ancestor(context.root, fetched_head, before.head):
        return PullResult(
            remote=remote,
            remote_branch=remote_branch,
            local_branch=before.branch,
            previous_head=before.head,
            current_head=before.head,
            outcome="local_ahead",
        )
    if not _is_ancestor(context.root, before.head, fetched_head):
        raise ArchRepoError(
            ErrorCode.CONFLICT,
            "Local and remote branches have diverged; automatic integration is forbidden",
            details={
                "remote": remote,
                "branch": remote_branch,
                "local_head": before.head,
                "fetched_head": fetched_head,
            },
        )

    _validate_fetched_repository(context.root, fetched_head, declaration_path)
    unchanged = repository_status(context.root)
    if unchanged.head != before.head or unchanged.branch != before.branch or unchanged.entries:
        raise ArchRepoError(
            ErrorCode.CONFLICT,
            "Repository changed while pull was being prepared",
        )

    merge = _run_git(
        context.root,
        [
            "-c",
            f"core.hooksPath={os.devnull}",
            "merge",
            "--ff-only",
            "--no-edit",
            fetched_head,
        ],
        operation="fast-forward integration",
        allowed_return_codes={1, 128},
    )
    if merge.returncode != 0:
        raise ArchRepoError(
            ErrorCode.CONFLICT,
            "Fast-forward integration could not be completed safely",
        )
    after = repository_status(context.root)
    if after.head != fetched_head or after.entries:
        raise ArchRepoError(
            ErrorCode.GIT_ERROR,
            "Fast-forward integration produced an unexpected repository state",
        )
    open_repository(context.root, declaration_path)
    return PullResult(
        remote=remote,
        remote_branch=remote_branch,
        local_branch=before.branch,
        previous_head=before.head,
        current_head=fetched_head,
        outcome="fast_forward",
    )


def publish_repository(
    repository_path: str | Path,
    remote: str,
    remote_branch: str,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
) -> PublishResult:
    """Validate and push current HEAD without force, tags, or upstream mutation."""

    context = open_repository(repository_path, declaration_path)
    status = repository_status(context.root)
    if status.entries:
        raise ArchRepoError(
            ErrorCode.DIRTY_WORKTREE,
            "Publication requires a clean working tree and index",
            details={"changed_paths": [entry.path for entry in status.entries]},
        )
    if status.branch is None or status.head is None:
        raise ArchRepoError(
            ErrorCode.CONFLICT, "Publication requires a local branch with at least one commit"
        )
    _validate_branch_argument(remote_branch)
    _require_safe_remote(context.root, remote)

    result = _run_git(
        context.root,
        [
            "push",
            "--porcelain",
            "--",
            remote,
            f"HEAD:refs/heads/{remote_branch}",
        ],
        operation="publish",
        network=True,
        allowed_return_codes={1},
    )
    if result.returncode != 0:
        _raise_remote_failure(
            result,
            operation="publish",
            details={"remote": remote, "branch": remote_branch},
        )
    return PublishResult(
        remote=remote,
        local_branch=status.branch,
        remote_branch=remote_branch,
        commit=status.head,
    )


def _resolve_new_target(target_path: str | Path) -> Path:
    target = Path(target_path).expanduser()
    if target.exists() or target.is_symlink():
        raise ArchRepoError(
            ErrorCode.CONFLICT,
            "Clone target path already exists",
            details={"path": str(target)},
        )
    if not target.name:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "Clone target path is empty")
    try:
        parent = target.parent.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ArchRepoError(
            ErrorCode.NOT_FOUND,
            "Clone target parent directory does not exist",
            details={"path": str(target.parent)},
        ) from exc
    if not parent.is_dir():
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY, "Clone target parent is not a directory"
        )
    resolved = parent / target.name
    if resolved.exists() or resolved.is_symlink():
        raise ArchRepoError(ErrorCode.CONFLICT, "Clone target path already exists")
    return resolved


def _remove_tree(path: Path) -> None:
    def remove_read_only(
        function: Any,
        failing_path: str,
        error: tuple[type[BaseException], BaseException, Any],
    ) -> None:
        del error
        os.chmod(failing_path, stat.S_IWRITE)
        function(failing_path)

    shutil.rmtree(path, onerror=remove_read_only)


def _require_safe_remote(root: Path, remote: str) -> None:
    if not remote or remote.startswith("-") or "\0" in remote:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "Remote name is not valid")
    configured = next((item for item in list_remotes(root) if item.name == remote), None)
    if configured is None:
        raise ArchRepoError(
            ErrorCode.NOT_FOUND,
            "Configured remote was not found",
            details={"remote": remote},
        )
    raw_urls = _run_git(
        root,
        ["remote", "get-url", "--all", "--", remote],
        operation="read remote URL",
    ).stdout.splitlines()
    for url in raw_urls:
        _validate_transport_url(url)


def _validate_transport_url(url: str) -> None:
    if not url or "\0" in url or "\n" in url or "\r" in url:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "Remote URL is not valid")
    try:
        parsed = urlsplit(url)
        _ = parsed.port
    except ValueError as exc:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "Remote URL is not valid") from exc
    if parsed.query or parsed.fragment:
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            "Remote URL query and fragment components are not allowed",
        )
    if parsed.scheme.casefold() in {"http", "https"} and (
        parsed.username is not None or parsed.password is not None
    ):
        raise ArchRepoError(
            ErrorCode.AUTHENTICATION_ERROR,
            "Remote URL must not contain embedded HTTP credentials",
        )


def _validate_branch_argument(branch: str) -> None:
    if not branch or branch.startswith("-") or "\0" in branch:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "Branch name is not valid")
    result = _run_git(
        None,
        ["check-ref-format", f"refs/heads/{branch}"],
        operation="validate branch name",
        allowed_return_codes={1, 128},
    )
    if result.returncode != 0:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "Branch name is not valid")


def _optional_revision(root: Path, revision: str) -> str | None:
    result = _run_git(
        root,
        ["rev-parse", "--verify", revision],
        operation="resolve fetched revision",
        allowed_return_codes={128},
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = _run_git(
        root,
        ["merge-base", "--is-ancestor", ancestor, descendant],
        operation="compare repository histories",
        allowed_return_codes={1},
    )
    return result.returncode == 0


def _validate_fetched_repository(
    root: Path,
    fetched_head: str,
    declaration_path: str,
) -> None:
    staging_parent = Path(tempfile.mkdtemp(prefix=".arch-repo-pull-"))
    staging = staging_parent / "checkout"
    worktree_added = False
    try:
        _run_git(
            root,
            [
                "-c",
                "submodule.recurse=false",
                "worktree",
                "add",
                "--detach",
                "--",
                str(staging),
                fetched_head,
            ],
            operation="prepare fetched repository validation",
        )
        worktree_added = True
        report = validate_repository(staging, declaration_path)
        if not report.valid:
            raise ArchRepoError(
                ErrorCode.INVALID_REPOSITORY,
                "Fetched repository did not pass validation",
                details=report.as_dict(),
            )
    finally:
        if worktree_added:
            _run_git(
                root,
                ["worktree", "remove", "--force", "--", str(staging)],
                operation="remove fetched validation worktree",
                allowed_return_codes={1, 128},
            )
        if staging_parent.exists():
            _remove_tree(staging_parent)


def _classify_remote_failure(result: subprocess.CompletedProcess[str]) -> ErrorCode:
    diagnostic = f"{result.stdout}\n{result.stderr}".casefold()
    patterns: tuple[tuple[ErrorCode, tuple[str, ...]], ...] = (
        (
            ErrorCode.NON_FAST_FORWARD,
            ("non-fast-forward", "fetch first"),
        ),
        (
            ErrorCode.TIMEOUT,
            ("operation timed out", "connection timed out", "timed out"),
        ),
        (
            ErrorCode.TLS_ERROR,
            (
                "ssl certificate problem",
                "certificate verify failed",
                "certificate verification failed",
                "tls certificate",
                "x509:",
                "sec_e_untrusted_root",
            ),
        ),
        (
            ErrorCode.AUTHENTICATION_ERROR,
            (
                "authentication failed",
                "invalid credentials",
                "could not read username",
                "could not read password",
                "terminal prompts disabled",
                "permission denied (publickey",
                "returned error: 401",
                "http 401",
            ),
        ),
        (
            ErrorCode.PERMISSION_DENIED,
            (
                "write access to repository not granted",
                "insufficient permission",
                "permission to ",
                "access denied",
                "returned error: 403",
                "http 403",
            ),
        ),
        (
            ErrorCode.NOT_FOUND,
            (
                "repository not found",
                "remote ref does not exist",
                "couldn't find remote ref",
                "does not appear to be a git repository",
                "returned error: 404",
                "http 404",
            ),
        ),
        (
            ErrorCode.NETWORK_ERROR,
            (
                "could not resolve host",
                "could not resolve hostname",
                "failed to connect",
                "connection refused",
                "network is unreachable",
                "no route to host",
                "connection reset",
            ),
        ),
        (
            ErrorCode.PROVIDER_CAPABILITY_GAP,
            (
                "does not support",
                "not supported",
                "unsupported protocol",
                "remote helper for",
                "requested capability is not available",
            ),
        ),
    )
    for code, candidates in patterns:
        if any(candidate in diagnostic for candidate in candidates):
            return code
    return ErrorCode.REMOTE_ERROR


def _raise_remote_failure(
    result: subprocess.CompletedProcess[str],
    *,
    operation: str,
    details: dict[str, Any] | None = None,
) -> None:
    code = _classify_remote_failure(result)
    messages = {
        ErrorCode.AUTHENTICATION_ERROR: "Git remote authentication failed",
        ErrorCode.PERMISSION_DENIED: "Git remote permission was denied",
        ErrorCode.NETWORK_ERROR: "Git remote is unavailable",
        ErrorCode.TLS_ERROR: "Git remote TLS validation failed",
        ErrorCode.TIMEOUT: "Git remote operation timed out",
        ErrorCode.NOT_FOUND: "Git remote repository or reference was not found",
        ErrorCode.PROVIDER_CAPABILITY_GAP: (
            "Git remote does not support the requested capability"
        ),
        ErrorCode.NON_FAST_FORWARD: (
            "Remote branch does not accept a fast-forward publication"
        ),
        ErrorCode.REMOTE_ERROR: f"Git {operation} failed",
    }
    raise ArchRepoError(code, messages[code], details=details)


def _run_git(
    root: Path | None,
    arguments: list[str],
    *,
    operation: str,
    network: bool = False,
    allowed_return_codes: set[int] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = ["git"]
    if root is not None:
        command.extend(["-C", str(root)])
    command.extend(arguments)
    environment = git_environment()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["GCM_INTERACTIVE"] = "Never"
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_NETWORK_TIMEOUT_SECONDS if network else _LOCAL_GIT_TIMEOUT_SECONDS,
            env=environment,
        )
    except FileNotFoundError as exc:
        raise ArchRepoError(ErrorCode.GIT_ERROR, "Git executable was not found") from exc
    except subprocess.TimeoutExpired as exc:
        code = ErrorCode.TIMEOUT if network else ErrorCode.GIT_ERROR
        raise ArchRepoError(code, f"Git {operation} timed out") from exc
    except OSError as exc:
        code = ErrorCode.NETWORK_ERROR if network else ErrorCode.GIT_ERROR
        raise ArchRepoError(code, f"Git {operation} failed") from exc
    allowed = allowed_return_codes or set()
    if result.returncode != 0 and result.returncode not in allowed:
        if network:
            _raise_remote_failure(result, operation=operation)
        raise ArchRepoError(ErrorCode.GIT_ERROR, f"Git {operation} failed")
    return result
