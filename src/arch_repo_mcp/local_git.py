"""Provider-independent local Git operations for architecture repositories."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.git_environment import git_environment
from arch_repo_mcp.repository import (
    DEFAULT_DECLARATION_PATH,
    RepositoryContext,
    discover_repository_root,
    open_repository,
    validate_repository,
)

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


@dataclass(frozen=True, slots=True)
class GitCommitResult:
    commit: str
    branch: str
    message: str
    paths: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "branch": self.branch,
            "message": self.message,
            "paths": list(self.paths),
        }


@dataclass(frozen=True, slots=True)
class GitRemote:
    name: str
    fetch_urls: tuple[str, ...]
    push_urls: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "fetch_urls": list(self.fetch_urls),
            "push_urls": list(self.push_urls),
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


def switch_branch(
    repository_path: str | Path,
    branch_name: str,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
) -> GitBranch:
    """Switch to an existing local branch only from a clean, valid repository."""

    context = open_repository(repository_path, declaration_path)
    status = repository_status(context.root)
    if status.entries:
        raise ArchRepoError(
            ErrorCode.DIRTY_WORKTREE,
            "Branch switch requires a clean working tree and index",
            details={"changed_paths": [entry.path for entry in status.entries]},
        )
    if status.branch is None:
        raise ArchRepoError(
            ErrorCode.CONFLICT, "Branch switch from detached or unresolved HEAD is not supported"
        )

    branches = list_branches(context.root)
    target = next((branch for branch in branches if branch.name == branch_name), None)
    if target is None:
        raise ArchRepoError(
            ErrorCode.NOT_FOUND,
            "Local branch was not found",
            details={"branch": branch_name},
        )
    if target.current:
        return target

    previous_branch = status.branch
    _run_git(
        context.root,
        ["switch", "--no-guess", branch_name],
        operation="switch branch",
        conflict_on_failure=True,
    )
    try:
        report = validate_repository(context.root, declaration_path)
    except ArchRepoError:
        _restore_branch(context.root, previous_branch)
        raise
    if not report.valid:
        _restore_branch(context.root, previous_branch)
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Target branch is not a valid architecture repository",
            details={
                "target_branch": branch_name,
                "restored_branch": previous_branch,
                "validation": report.as_dict(),
            },
        )

    switched = next(
        (branch for branch in list_branches(context.root) if branch.name == branch_name),
        None,
    )
    if switched is None or not switched.current:
        raise ArchRepoError(ErrorCode.GIT_ERROR, "Switched branch could not be resolved")
    return switched


def repository_commit(
    repository_path: str | Path,
    message: str,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
) -> GitCommitResult:
    """Validate and commit only changed paths controlled by the repository DSL."""

    if not message.strip() or "\0" in message:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "Commit message must not be empty")
    context = open_repository(repository_path, declaration_path)
    status = repository_status(context.root)
    if status.branch is None:
        raise ArchRepoError(ErrorCode.CONFLICT, "Commit on detached HEAD is not supported")
    paths = _permitted_changed_paths(context, status)
    if not paths:
        raise ArchRepoError(
            ErrorCode.CONFLICT, "No changed architecture repository paths to commit"
        )

    _run_git(
        context.root,
        ["add", "-A", "--", *paths],
        operation="stage architecture changes",
    )
    staged = _run_git(
        context.root,
        ["diff", "--cached", "--quiet", "--", *paths],
        operation="inspect staged architecture changes",
        allowed_return_codes={1},
    )
    if staged.returncode == 0:
        raise ArchRepoError(
            ErrorCode.CONFLICT, "Selected architecture paths contain no staged changes"
        )
    _run_git(
        context.root,
        ["commit", "--quiet", "--only", "-m", message, "--", *paths],
        operation="commit architecture changes",
        conflict_on_failure=True,
    )
    commit = _run_git(
        context.root,
        ["rev-parse", "--verify", "HEAD"],
        operation="resolve created commit",
    ).stdout.strip()
    return GitCommitResult(
        commit=commit,
        branch=status.branch,
        message=message,
        paths=tuple(paths),
    )


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


def list_remotes(repository_path: str | Path) -> list[GitRemote]:
    """List local remote configuration with credential-bearing URL parts removed."""

    root = discover_repository_root(repository_path)
    names_result = _run_git(root, ["remote"], operation="list remotes")
    remotes: list[GitRemote] = []
    for name in sorted(line for line in names_result.stdout.splitlines() if line):
        fetch = _run_git(
            root,
            ["remote", "get-url", "--all", "--", name],
            operation="read remote fetch URLs",
        )
        push = _run_git(
            root,
            ["remote", "get-url", "--push", "--all", "--", name],
            operation="read remote push URLs",
        )
        remotes.append(
            GitRemote(
                name=name,
                fetch_urls=tuple(_sanitize_remote_url(url) for url in fetch.stdout.splitlines()),
                push_urls=tuple(_sanitize_remote_url(url) for url in push.stdout.splitlines()),
            )
        )
    return remotes


def configure_remote(
    repository_path: str | Path,
    name: str,
    url: str,
    *,
    replace: bool = False,
) -> GitRemote:
    """Add or explicitly replace one local remote URL without network access."""

    root = discover_repository_root(repository_path)
    _validate_remote_name(root, name)
    _validate_remote_url(url)
    existing = {remote.name for remote in list_remotes(root)}
    if name in existing and not replace:
        raise ArchRepoError(
            ErrorCode.CONFLICT,
            "Remote already exists; set replace=true to change it",
            details={"remote": name},
        )
    if name in existing:
        _run_git(
            root,
            ["remote", "set-url", "--", name, url],
            operation="replace remote URL",
        )
    else:
        _run_git(
            root,
            ["remote", "add", "--", name, url],
            operation="add remote",
        )
    configured = next((remote for remote in list_remotes(root) if remote.name == name), None)
    if configured is None:
        raise ArchRepoError(ErrorCode.GIT_ERROR, "Configured remote could not be resolved")
    return configured


def _restore_branch(root: Path, branch_name: str) -> None:
    try:
        _run_git(
            root,
            ["switch", "--no-guess", branch_name],
            operation="restore previous branch",
        )
    except ArchRepoError as exc:
        raise ArchRepoError(
            ErrorCode.GIT_ERROR,
            "Target branch validation failed and the previous branch could not be restored",
            details={"previous_branch": branch_name},
        ) from exc


def _permitted_changed_paths(
    context: RepositoryContext,
    status: GitStatus,
) -> list[str]:
    paths: set[str] = set()
    for entry in status.entries:
        entry_paths = [entry.path]
        if entry.original_path is not None:
            entry_paths.append(entry.original_path)
        controlled = [_is_controlled_path(context, path) for path in entry_paths]
        if any(controlled) and not all(controlled):
            raise ArchRepoError(
                ErrorCode.CONFLICT,
                "Rename or copy crosses the DSL-controlled repository boundary",
                details={"paths": entry_paths},
            )
        if all(controlled):
            paths.update(entry_paths)
    return sorted(paths)


def _is_controlled_path(context: RepositoryContext, path: str) -> bool:
    if not path or "\\" in path:
        return False
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts or relative == PurePosixPath("."):
        return False
    if relative == context.declaration_path:
        return True
    if relative in {entity.files.template for entity in context.declaration.entities}:
        return True
    return sum(entity.matches(relative) for entity in context.declaration.entities) == 1


def _validate_remote_name(root: Path, name: str) -> None:
    if not name or name.startswith("-") or "\0" in name or "\n" in name or "\r" in name:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "Remote name is not valid")
    result = _run_git(
        root,
        ["check-ref-format", f"refs/remotes/{name}/validation"],
        operation="validate remote name",
        allowed_return_codes={1, 128},
    )
    if result.returncode != 0:
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            "Remote name is not valid",
            details={"remote": name},
        )


def _validate_remote_url(url: str) -> None:
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
    if parsed.scheme.lower() in {"http", "https"} and (
        parsed.username is not None or parsed.password is not None
    ):
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            "HTTP remote URL must not contain embedded credentials",
        )


def _sanitize_remote_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if parsed.scheme:
            hostname = parsed.hostname or ""
            if ":" in hostname and not hostname.startswith("["):
                hostname = f"[{hostname}]"
            port = f":{parsed.port}" if parsed.port is not None else ""
            return urlunsplit((parsed.scheme, f"{hostname}{port}", parsed.path, "", ""))
    except ValueError:
        return "<redacted-invalid-url>"
    if "@" in url:
        return url.rsplit("@", maxsplit=1)[1]
    return url


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
            env=git_environment(),
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
