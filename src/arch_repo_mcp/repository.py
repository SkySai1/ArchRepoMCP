"""Local architecture repository discovery and validation."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from arch_repo_mcp.dsl import (
    EntityDefinition,
    FileFormat,
    RepositoryDeclaration,
    ValidationIssue,
    load_declaration,
)
from arch_repo_mcp.errors import ArchRepoError, ErrorCode

DEFAULT_DECLARATION_PATH = "architecture.yaml"
_GIT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True, slots=True)
class RepositoryContext:
    """A validated local architecture repository."""

    root: Path
    declaration_path: PurePosixPath
    declaration: RepositoryDeclaration


@dataclass(frozen=True, slots=True)
class RepositoryValidationReport:
    """Result of a full local repository validation."""

    valid: bool
    repository_root: str
    declaration_path: str
    entity_counts: dict[str, int]
    issues: tuple[ValidationIssue, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "repository_root": self.repository_root,
            "declaration_path": self.declaration_path,
            "entity_counts": self.entity_counts,
            "issues": [issue.as_dict() for issue in self.issues],
        }


def discover_repository_root(repository_path: str | Path) -> Path:
    """Resolve the containing local Git repository without any network operation."""

    candidate = Path(repository_path).expanduser()
    try:
        candidate = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ArchRepoError(
            ErrorCode.NOT_FOUND,
            "Repository path does not exist",
            details={"path": str(candidate)},
        ) from exc
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Repository path could not be resolved",
            details={"path": str(candidate)},
        ) from exc

    if not candidate.is_dir():
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Repository path is not a directory",
            details={"path": str(candidate)},
        )

    try:
        result = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
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
        raise ArchRepoError(ErrorCode.TIMEOUT, "Git repository discovery timed out") from exc
    except OSError as exc:
        raise ArchRepoError(ErrorCode.GIT_ERROR, "Git repository discovery failed") from exc

    if result.returncode != 0:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Path is not inside a Git repository",
            details={"path": str(candidate)},
        )

    output = result.stdout.strip()
    if not output:
        raise ArchRepoError(ErrorCode.GIT_ERROR, "Git returned an empty repository root")
    try:
        return Path(output).resolve(strict=True)
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY, "Git repository root could not be resolved"
        ) from exc


def open_repository(
    repository_path: str | Path,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
) -> RepositoryContext:
    """Open a repository only when its declaration and complete structure are valid."""

    root = discover_repository_root(repository_path)
    relative_declaration, declaration_file = _resolve_confined_file(
        root, declaration_path, label="declaration"
    )
    declaration = load_declaration(declaration_file)
    report = _validate_loaded_repository(root, relative_declaration, declaration)
    if not report.valid:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "Architecture repository validation failed",
            details=report.as_dict(),
        )
    return RepositoryContext(
        root=root,
        declaration_path=relative_declaration,
        declaration=declaration,
    )


def validate_repository(
    repository_path: str | Path,
    declaration_path: str = DEFAULT_DECLARATION_PATH,
) -> RepositoryValidationReport:
    """Return a deterministic full validation report for a local repository."""

    root = discover_repository_root(repository_path)
    try:
        relative_declaration, declaration_file = _resolve_confined_file(
            root, declaration_path, label="declaration"
        )
    except ArchRepoError as exc:
        issue = ValidationIssue(exc.code.value, declaration_path, exc.message)
        return _report(root, declaration_path, {}, [issue])

    try:
        declaration = load_declaration(declaration_file)
    except ArchRepoError as exc:
        raw_issues = exc.details.get("issues")
        if isinstance(raw_issues, list):
            issues = [
                ValidationIssue(
                    code=str(item.get("code", ErrorCode.VALIDATION_ERROR.value)),
                    path=str(item.get("path", declaration_path)),
                    message=str(item.get("message", exc.message)),
                )
                for item in raw_issues
                if isinstance(item, dict)
            ]
        else:
            issues = [ValidationIssue(exc.code.value, declaration_path, exc.message)]
        return _report(root, relative_declaration.as_posix(), {}, issues)

    return _validate_loaded_repository(root, relative_declaration, declaration)


def _resolve_confined_file(
    root: Path,
    relative_path: str,
    *,
    label: str,
) -> tuple[PurePosixPath, Path]:
    if not relative_path or "\\" in relative_path:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            f"{label.capitalize()} path must be a repository-relative POSIX path",
        )
    pure_path = PurePosixPath(relative_path)
    if pure_path.is_absolute() or ".." in pure_path.parts or pure_path == PurePosixPath("."):
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            f"{label.capitalize()} path escapes the repository",
            details={"path": relative_path},
        )

    candidate = root.joinpath(*pure_path.parts)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ArchRepoError(
            ErrorCode.NOT_FOUND,
            f"{label.capitalize()} file was not found",
            details={"path": relative_path},
        ) from exc
    except OSError as exc:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            f"{label.capitalize()} path could not be resolved",
            details={"path": relative_path},
        ) from exc

    if not resolved.is_relative_to(root) or candidate.is_symlink():
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            f"{label.capitalize()} path is not confined to the repository",
            details={"path": relative_path},
        )
    if not resolved.is_file():
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            f"{label.capitalize()} path is not a file",
            details={"path": relative_path},
        )
    return pure_path, resolved


def _validate_loaded_repository(
    root: Path,
    declaration_path: PurePosixPath,
    declaration: RepositoryDeclaration,
) -> RepositoryValidationReport:
    issues: list[ValidationIssue] = []
    counts = {entity.name: 0 for entity in declaration.entities}
    templates = {entity.files.template for entity in declaration.entities}

    for entity in declaration.entities:
        template_path = entity.files.template.as_posix()
        try:
            _, resolved_template = _resolve_confined_file(root, template_path, label="template")
        except ArchRepoError as exc:
            issues.append(ValidationIssue(exc.code.value, template_path, exc.message))
            continue
        format_issue = _validate_file_format(
            resolved_template, entity.files.format, template_path
        )
        if format_issue is not None:
            issues.append(format_issue)

    for relative_path, absolute_path, symlink in _walk_repository_files(root, issues):
        if relative_path == declaration_path:
            continue

        matching_entities = [
            entity for entity in declaration.entities if entity.matches(relative_path)
        ]
        if len(matching_entities) > 1:
            names = ", ".join(sorted(entity.name for entity in matching_entities))
            issues.append(
                ValidationIssue(
                    "MATCH_CONFLICT",
                    relative_path.as_posix(),
                    f"file matches multiple entities: {names}",
                )
            )
            continue

        if relative_path in templates:
            if matching_entities:
                issues.append(
                    ValidationIssue(
                        "TEMPLATE_MATCHES_ENTITY",
                        relative_path.as_posix(),
                        f"template also matches entity: {matching_entities[0].name}",
                    )
                )
            continue

        if symlink or not matching_entities:
            continue
        entity = matching_entities[0]
        counts[entity.name] += 1
        format_issue = _validate_file_format(
            absolute_path, entity.files.format, relative_path.as_posix()
        )
        if format_issue is not None:
            issues.append(format_issue)

    return _report(root, declaration_path.as_posix(), counts, issues)


def _walk_repository_files(
    root: Path,
    issues: list[ValidationIssue],
) -> list[tuple[PurePosixPath, Path, bool]]:
    files: list[tuple[PurePosixPath, Path, bool]] = []

    def on_error(exc: OSError) -> None:
        issues.append(
            ValidationIssue("PERMISSION_DENIED", ".", "repository directory could not be read")
        )

    for current, directories, filenames in os.walk(root, topdown=True, onerror=on_error):
        current_path = Path(current)
        directories[:] = sorted(name for name in directories if name != ".git")
        for directory_name in list(directories):
            directory = current_path / directory_name
            if directory.is_symlink():
                relative = PurePosixPath(directory.relative_to(root).as_posix())
                issues.append(
                    ValidationIssue(
                        "SYMLINK_FORBIDDEN",
                        relative.as_posix(),
                        "symbolic-link directories are not allowed",
                    )
                )
                directories.remove(directory_name)

        for filename in sorted(filenames):
            absolute = current_path / filename
            relative = PurePosixPath(absolute.relative_to(root).as_posix())
            symlink = absolute.is_symlink()
            if symlink:
                issues.append(
                    ValidationIssue(
                        "SYMLINK_FORBIDDEN",
                        relative.as_posix(),
                        "symbolic-link files are not allowed",
                    )
                )
            files.append((relative, absolute, symlink))
    return files


def _validate_file_format(
    path: Path,
    file_format: FileFormat,
    display_path: str,
) -> ValidationIssue | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ValidationIssue(
            "INVALID_CONTENT", display_path, "file could not be read as UTF-8"
        )

    try:
        if file_format is FileFormat.YAML:
            yaml.safe_load(text)
        elif file_format is FileFormat.JSON:
            json.loads(text)
        elif file_format is FileFormat.MARKDOWN_FRONT_MATTER:
            _parse_front_matter(text)
    except (json.JSONDecodeError, yaml.YAMLError, ValueError) as exc:
        return ValidationIssue(
            "INVALID_CONTENT",
            display_path,
            f"file is not valid {file_format.value}: {exc}",
        )
    return None


def _parse_front_matter(text: str) -> Any:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("opening '---' delimiter is missing")
    try:
        end_index = lines.index("---", 1)
    except ValueError as exc:
        raise ValueError("closing '---' delimiter is missing") from exc
    return yaml.safe_load("\n".join(lines[1:end_index]))


def _report(
    root: Path,
    declaration_path: str,
    counts: dict[str, int],
    issues: list[ValidationIssue],
) -> RepositoryValidationReport:
    ordered_issues = tuple(
        sorted(issues, key=lambda issue: (issue.path, issue.code, issue.message))
    )
    return RepositoryValidationReport(
        valid=not ordered_issues,
        repository_root=str(root),
        declaration_path=declaration_path,
        entity_counts={name: counts[name] for name in sorted(counts)},
        issues=ordered_issues,
    )

