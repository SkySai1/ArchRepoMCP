"""Explicit provider-independent synchronization through standard Git transport."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from arch_repo_mcp.errors import ArchRepoError, ErrorCode
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
            shutil.rmtree(staging, ignore_errors=True)

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
        diagnostic = f"{result.stdout}\n{result.stderr}".casefold()
        if "non-fast-forward" in diagnostic or "fetch first" in diagnostic:
            raise ArchRepoError(
                ErrorCode.NON_FAST_FORWARD,
                "Remote branch does not accept a fast-forward publication",
                details={"remote": remote, "branch": remote_branch},
            )
        raise ArchRepoError(
            ErrorCode.REMOTE_ERROR,
            "Git publication failed",
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
    environment = os.environ.copy()
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
        code = ErrorCode.REMOTE_ERROR if network else ErrorCode.GIT_ERROR
        raise ArchRepoError(code, f"Git {operation} failed")
    return result
