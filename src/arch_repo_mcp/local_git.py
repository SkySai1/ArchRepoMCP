"""Provider-independent local Git operations for architecture repositories."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.repository import discover_repository_root

_GIT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True, slots=True)
class GitStatusEntry:
    path: str
    index_status: str
    worktree_status: str
    original_path: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "path": self.path,
            "index_status": self.index_status,
            "worktree_status": self.worktree_status,
            "original_path": self.original_path,
        }


@dataclass(frozen=True, slots=True)
class GitStatus:
    branch: str | None
    detached: bool
    head: str | None
    entries: tuple[GitStatusEntry, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "branch": self.branch,
            "detached": self.detached,
            "head": self.head,
            "clean": not self.entries,
            "entries": [entry.as_dict() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class GitBranch:
    name: str
    current: bool
    commit: str

    def as_dict(self) -> dict[str, str | bool]:
        return {"name": self.name, "current": self.current, "commit": self.commit}


@dataclass(frozen=True, slots=True)
class GitCommit:
    commit: str
    parents: tuple[str, ...]
    author_name: str
    author_email: str
    authored_at: str
    subject: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "parents": list(self.parents),
            "author_name": self.author_name,
            "author_email": self.author_email,
            "authored_at": self.authored_at,
            "subject": self.subject,
        }


def repository_status(
    repository_path: str | Path,
) -> GitStatus:
    """Return deterministic porcelain status for a valid local repository."""

    root = discover_repository_root(repository_path)
    result = _run_git(
        root,
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        operation="status",
    )
    tokens = result.stdout.split("\0")
    entries: list[GitStatusEntry] = []
    index = 0
    while index < len(tokens):
        record = tokens[index]
        index += 1
        if not record:
            continue
        if len(record) < 3:
            raise ArchRepoError(ErrorCode.GIT_ERROR, "Git returned malformed status data")
        index_status = record[0]
        worktree_status = record[1]
        path = record[3:]
        original_path: str | None = None
        if index_status in {"R", "C"}:
            if index >= len(tokens) or not tokens[index]:
                raise ArchRepoError(ErrorCode.GIT_ERROR, "Git returned malformed rename data")
            original_path = tokens[index]
            index += 1
        entries.append(
            GitStatusEntry(
                path=path,
                index_status=index_status,
                worktree_status=worktree_status,
                original_path=original_path,
            )
        )

    branch_result = _run_git(
        root,
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        operation="resolve current branch",
        allowed_return_codes={1},
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else None
    head = _resolve_optional_head(root)
    return GitStatus(
        branch=branch,
        detached=branch is None and head is not None,
        head=head,
        entries=tuple(sorted(entries, key=lambda item: (item.path, item.original_path or ""))),
    )


def repository_diff(
    repository_path: str | Path,
    *,
    staged: bool = False,
    base_revision: str | None = None,
    target_revision: str | None = None,
) -> str:
    """Return a no-color local diff for the working tree, index, or explicit revisions."""

    root = discover_repository_root(repository_path)
    if staged and (base_revision is not None or target_revision is not None):
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            "Staged diff cannot be combined with explicit revisions",
        )
    if target_revision is not None and base_revision is None:
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            "Target revision requires a base revision",
        )

    arguments = ["diff", "--no-ext-diff", "--no-color"]
    if staged:
        arguments.append("--cached")
    if base_revision is not None:
        _validate_revision_argument(base_revision)
        arguments.append(base_revision)
    if target_revision is not None:
        _validate_revision_argument(target_revision)
        arguments.append(target_revision)
    arguments.append("--")
    return _run_git(root, arguments, operation="diff").stdout


def list_branches(
    repository_path: str | Path,
) -> list[GitBranch]:
    """List local branches without contacting remotes."""

    root = discover_repository_root(repository_path)
    result = _run_git(
        root,
        ["for-each-ref", "--format=%(refname:short)%00%(HEAD)%00%(objectname)", "refs/heads"],
        operation="list branches",
    )
    branches: list[GitBranch] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        fields = line.split("\0")
        if len(fields) != 3:
            raise ArchRepoError(ErrorCode.GIT_ERROR, "Git returned malformed branch data")
        name, head_marker, commit = fields
        branches.append(GitBranch(name=name, current=head_marker == "*", commit=commit))
    return sorted(branches, key=lambda branch: branch.name)


def create_branch(
    repository_path: str | Path,
    branch_name: str,
    start_point: str = "HEAD",
) -> GitBranch:
    """Create a local branch at an explicit start point without switching to it."""

    root = discover_repository_root(repository_path)
    _validate_branch_name(root, branch_name)
    _validate_revision_argument(start_point)
    _run_git(
        root,
        ["rev-parse", "--verify", f"{start_point}^{{commit}}"],
        operation="resolve branch start point",
    )
    _run_git(
        root,
        ["branch", branch_name, start_point],
        operation="create branch",
        conflict_on_failure=True,
    )
    branch = next(
        (
            item
            for item in list_branches(root)
            if item.name == branch_name
        ),
        None,
    )
    if branch is None:
        raise ArchRepoError(ErrorCode.GIT_ERROR, "Created branch could not be resolved")
    return branch


def repository_history(
    repository_path: str | Path,
    *,
    max_count: int = 20,
    revision: str = "HEAD",
) -> list[GitCommit]:
    """Read bounded local commit history without contacting remotes."""

    if not 1 <= max_count <= 1000:
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR, "History max_count must be between 1 and 1000"
        )
    _validate_revision_argument(revision)
    root = discover_repository_root(repository_path)
    if revision == "HEAD" and _resolve_optional_head(root) is None:
        return []
    _run_git(
        root,
        ["rev-parse", "--verify", f"{revision}^{{commit}}"],
        operation="resolve history revision",
    )
    result = _run_git(
        root,
        [
            "log",
            "--no-decorate",
            f"--max-count={max_count}",
            "--format=%H%x1f%P%x1f%an%x1f%ae%x1f%aI%x1f%s%x1e",
            revision,
            "--",
        ],
        operation="history",
    )
    commits: list[GitCommit] = []
    for record in result.stdout.split("\x1e"):
        record = record.strip("\r\n")
        if not record:
            continue
        fields = record.split("\x1f")
        if len(fields) != 6:
            raise ArchRepoError(ErrorCode.GIT_ERROR, "Git returned malformed history data")
        commit, parents, author_name, author_email, authored_at, subject = fields
        commits.append(
            GitCommit(
                commit=commit,
                parents=tuple(parents.split()) if parents else (),
                author_name=author_name,
                author_email=author_email,
                authored_at=authored_at,
                subject=subject,
            )
        )
    return commits


def _validate_branch_name(root: Path, branch_name: str) -> None:
    if not branch_name:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "Branch name must not be empty")
    result = _run_git(
        root,
        ["check-ref-format", "--branch", branch_name],
        operation="validate branch name",
        allowed_return_codes={1, 128},
    )
    if result.returncode != 0:
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            "Branch name is not valid",
            details={"branch": branch_name},
        )


def _validate_revision_argument(revision: str) -> None:
    if not revision or revision.startswith("-") or "\0" in revision:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "Git revision is not valid")


def _resolve_optional_head(root: Path) -> str | None:
    result = _run_git(
        root,
        ["rev-parse", "--verify", "HEAD"],
        operation="resolve HEAD",
        allowed_return_codes={128},
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _run_git(
    root: Path,
    arguments: list[str],
    *,
    operation: str,
    allowed_return_codes: set[int] | None = None,
    conflict_on_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    allowed = allowed_return_codes or set()
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise ArchRepoError(ErrorCode.GIT_ERROR, "Git executable was not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise ArchRepoError(ErrorCode.TIMEOUT, f"Git {operation} timed out") from exc
    except OSError as exc:
        raise ArchRepoError(ErrorCode.GIT_ERROR, f"Git {operation} failed") from exc
    if result.returncode != 0 and result.returncode not in allowed:
        code = ErrorCode.CONFLICT if conflict_on_failure else ErrorCode.GIT_ERROR
        raise ArchRepoError(code, f"Git {operation} failed")
    return result
