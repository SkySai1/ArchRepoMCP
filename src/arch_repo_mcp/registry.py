"""Persistent per-user repository identities, independent of repository contents."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.repository import discover_repository_root, open_repository


def absolute_repository_path(value: str) -> Path:
    """Require an explicit absolute path; never consult environment or cwd."""

    path = Path(value)
    if not value or not path.is_absolute() or ".." in path.parts:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "An absolute repository path is required")
    if path.is_symlink():
        raise ArchRepoError(ErrorCode.INVALID_REPOSITORY, "Repository root must not be a symlink")
    return path.resolve()


def _uuid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ArchRepoError(ErrorCode.VALIDATION_ERROR, "repository_id must be a UUID") from exc


def _unique_mapping(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate index key")
        result[key] = value
    return result


class RepositoryRegistry:
    """Serialize index updates across processes and replace complete JSON atomically."""

    def __init__(self) -> None:
        self.path = Path.home() / ".config" / "arch-repo-mcp" / "repositories.json"

    @contextmanager
    def _locked(self) -> Iterator[None]:
        try:
            if self.path.parent.is_symlink() or self.path.is_symlink():
                raise ArchRepoError(ErrorCode.PERMISSION_DENIED, "Index must not be a symlink")
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            lock_path = self.path.with_suffix(".lock")
            if lock_path.is_symlink():
                raise ArchRepoError(ErrorCode.PERMISSION_DENIED, "Index lock must not be a symlink")
            with lock_path.open("a+b") as lock:
                if os.name == "nt":
                    import msvcrt

                    # Lock a stable byte, including on an initially empty lock file.
                    lock.seek(0, os.SEEK_END)
                    if lock.tell() == 0:
                        lock.write(b"\0")
                        lock.flush()
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl

                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if os.name == "nt":
                        lock.seek(0)
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        except OSError as exc:
            raise ArchRepoError(
                ErrorCode.PERMISSION_DENIED, "Repository index could not be accessed"
            ) from exc

    def _read(self) -> list[dict[str, str]]:
        if not self.path.exists():
            self._write([])
            return []
        try:
            data = json.loads(
                self.path.read_text(encoding="utf-8"), object_pairs_hook=_unique_mapping
            )
            if (
                not isinstance(data, dict)
                or set(data) != {"version", "repositories"}
                or type(data["version"]) is not int
                or data["version"] != 1
                or not isinstance(data["repositories"], list)
            ):
                raise ValueError
            ids: set[str] = set()
            paths: set[str] = set()
            for entry in data["repositories"]:
                if not isinstance(entry, dict) or set(entry) != {
                    "repository_id",
                    "repository_path",
                }:
                    raise ValueError
                identifier, path = entry["repository_id"], entry["repository_path"]
                if (
                    not isinstance(identifier, str)
                    or str(UUID(identifier)) != identifier
                    or not isinstance(path, str)
                    or not Path(path).is_absolute()
                    or ".." in Path(path).parts
                    or "\0" in path
                    or str(Path(path)) != path
                    or identifier in ids
                    or path in paths
                ):
                    raise ValueError
                ids.add(identifier)
                paths.add(path)
            return data["repositories"]
        except (ValueError, TypeError, UnicodeError) as exc:
            raise ArchRepoError(
                ErrorCode.INVALID_REPOSITORY,
                "Repository index is invalid; restore it before retrying",
            ) from exc

    def _write(self, entries: list[dict[str, str]]) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".repositories-",
                suffix=".json",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump(
                    {"version": 1, "repositories": entries}, stream, ensure_ascii=False, indent=2
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def list(self) -> dict[str, Any]:
        with self._locked():
            return {"index_path": str(self.path), "repositories": self._read()}

    def reindex(
        self, repository_path: str, declaration_path: str = "architecture.yaml"
    ) -> dict[str, str]:
        path = absolute_repository_path(repository_path)
        context = open_repository(path, declaration_path)
        if context.root != path:
            raise ArchRepoError(ErrorCode.INVALID_REPOSITORY, "Path must identify the Git root")
        with self._locked():
            entries = self._read()
            for entry in entries:
                if entry["repository_path"] == str(path):
                    return entry
            entry = {"repository_id": str(uuid4()), "repository_path": str(path)}
            entries.append(entry)
            self._write(entries)
            return entry

    def resolve(self, repository_id: str) -> str:
        identifier = _uuid(repository_id)
        with self._locked():
            entry = self._find(self._read(), identifier)
        path = Path(entry["repository_path"])
        if path.is_symlink() or path.resolve() != path:
            raise ArchRepoError(ErrorCode.INVALID_REPOSITORY, "Indexed repository path has changed")
        if discover_repository_root(path) != path:
            raise ArchRepoError(
                ErrorCode.INVALID_REPOSITORY, "Indexed path is no longer a Git root"
            )
        return str(path)

    def unindex(self, repository_id: str) -> dict[str, str]:
        identifier = _uuid(repository_id)
        with self._locked():
            entries = self._read()
            entry = self._find(entries, identifier)
            self._write([item for item in entries if item != entry])
            return entry

    @staticmethod
    def _find(entries: list[dict[str, str]], identifier: str) -> dict[str, str]:
        for entry in entries:
            if entry["repository_id"] == identifier:
                return entry
        raise ArchRepoError(ErrorCode.NOT_FOUND, "Repository UUID is not indexed")
