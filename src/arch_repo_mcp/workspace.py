"""Configuration and path confinement for the local repository workspace."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from arch_repo_mcp.errors import ArchRepoError, ErrorCode

WORKSPACE_ENV = "ARCH_REPO_MCP_WORKSPACE"
ENV_FILE_ENV = "ARCH_REPO_MCP_ENV_FILE"


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    """Resolved local locations used by MCP repository discovery."""

    root: Path


def load_workspace_config(
    workspace_path: str | Path | None = None,
    env_file: str | Path | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    create_workspace: bool = False,
) -> WorkspaceConfig:
    """Resolve stdio arguments, process environment, and an optional .env file."""

    source = os.environ if environment is None else environment
    file_values, file_base = _workspace_env_values(env_file, source)

    raw_workspace = _first_value(
        workspace_path,
        source.get(WORKSPACE_ENV),
        file_values.get(WORKSPACE_ENV),
    )
    if raw_workspace is None:
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            "Architecture repository workspace is not configured",
            details={"environment_variable": WORKSPACE_ENV},
        )

    workspace_from_file = (
        workspace_path is None
        and not _non_empty(source.get(WORKSPACE_ENV))
        and _non_empty(file_values.get(WORKSPACE_ENV))
    )
    root = _resolve_workspace_root(
        raw_workspace,
        base=file_base if workspace_from_file else Path.cwd(),
        create=create_workspace,
    )

    return WorkspaceConfig(root=root)


def configured_workspace_root(
    *,
    environment: Mapping[str, str] | None = None,
) -> Path | None:
    """Return the configured workspace, or None when no workspace setting exists."""

    source = os.environ if environment is None else environment
    file_values, _ = _workspace_env_values(None, source)
    if not _non_empty(source.get(WORKSPACE_ENV)) and not _non_empty(
        file_values.get(WORKSPACE_ENV)
    ):
        return None
    return load_workspace_config(environment=source).root


def resolve_repository_argument(path: str | Path) -> Path:
    """Resolve an MCP repository argument and confine it to a configured workspace."""

    root = configured_workspace_root()
    raw = Path(path).expanduser()
    if root is None:
        return raw

    candidate = raw if raw.is_absolute() else root / raw
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Repository path could not be resolved",
            details={"path": str(path)},
        ) from exc
    if not resolved.is_relative_to(root):
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED,
            "Repository path is outside the configured workspace",
            details={"path": str(path), "workspace_root": str(root)},
        )
    return resolved


def _workspace_env_values(
    env_file: str | Path | None,
    environment: Mapping[str, str],
) -> tuple[dict[str, str], Path]:
    explicit_file = env_file is not None
    configured_file = _non_empty(environment.get(ENV_FILE_ENV))
    raw_file = env_file if explicit_file else configured_file or ".env"
    path = Path(raw_file).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    if path.is_symlink():
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED,
            "Workspace environment file must not be a symbolic link",
            details={"path": str(path)},
        )
    try:
        path = path.resolve(strict=True)
    except FileNotFoundError as exc:
        if explicit_file or configured_file:
            raise ArchRepoError(
                ErrorCode.NOT_FOUND,
                "Workspace environment file was not found",
                details={"path": str(path)},
            ) from exc
        return {}, Path.cwd()
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED,
            "Workspace environment file could not be resolved",
        ) from exc
    if not path.is_file():
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED,
            "Workspace environment file must be a regular non-symlink file",
            details={"path": str(path)},
        )
    return _read_env_file(path), path.parent


def _read_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED,
            "Workspace environment file could not be read as UTF-8",
        ) from exc

    values: dict[str, str] = {}
    for number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ArchRepoError(
                ErrorCode.VALIDATION_ERROR,
                "Workspace environment file contains an invalid line",
                details={"line": number},
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] == value[-1:] and value[:1] in {'"', "'"}:
            value = value[1:-1]
        if key in values:
            raise ArchRepoError(
                ErrorCode.VALIDATION_ERROR,
                "Workspace environment file contains a duplicate key",
                details={"key": key},
            )
        values[key] = value
    return values


def _resolve_workspace_root(value: str, *, base: Path, create: bool) -> Path:
    raw = Path(value).expanduser()
    candidate = raw if raw.is_absolute() else base / raw
    if create:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ArchRepoError(
                ErrorCode.PERMISSION_DENIED,
                "Architecture repository workspace could not be created",
                details={"path": str(candidate)},
            ) from exc
    try:
        root = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ArchRepoError(
            ErrorCode.NOT_FOUND,
            "Architecture repository workspace does not exist",
            details={"path": str(candidate)},
        ) from exc
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.PERMISSION_DENIED,
            "Architecture repository workspace could not be resolved",
        ) from exc
    if candidate.is_symlink() or not root.is_dir():
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Architecture repository workspace must be a non-symlink directory",
            details={"path": str(root)},
        )
    return root


def _first_value(*values: str | Path | None) -> str | None:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _non_empty(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value.strip()
