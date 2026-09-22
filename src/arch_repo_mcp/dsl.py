"""Parser and model for the normative architecture repository DSL v2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from yaml.constructor import ConstructorError

from arch_repo_mcp.errors import ArchRepoError, ErrorCode


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: _UniqueKeyLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class MatchMode(StrEnum):
    EXACT = "exact"
    REGEX = "regex"


class FileFormat(StrEnum):
    YAML = "yaml"
    JSON = "json"
    MARKDOWN = "markdown"
    MARKDOWN_FRONT_MATTER = "markdown_front_matter"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One deterministic validation finding."""

    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True, slots=True)
class Selector:
    mode: MatchMode
    value: str

    def matches(self, candidate: str) -> bool:
        if self.mode is MatchMode.EXACT:
            return candidate == self.value
        return re.fullmatch(self.value, candidate) is not None


@dataclass(frozen=True, slots=True)
class FileRule:
    path: Selector
    filename: Selector
    format: FileFormat
    template: PurePosixPath


@dataclass(frozen=True, slots=True)
class EntityDefinition:
    name: str
    description: str
    relations: tuple[str, ...]
    files: FileRule

    def matches(self, repository_path: PurePosixPath) -> bool:
        """Return whether a safe repository-relative file belongs to this entity."""

        parent = repository_path.parent.as_posix()
        return self.files.path.matches(parent) and self.files.filename.matches(
            repository_path.name
        )


@dataclass(frozen=True, slots=True)
class RepositoryDeclaration:
    kind: str
    version: str
    entities: tuple[EntityDefinition, ...]

    def entity(self, name: str) -> EntityDefinition | None:
        return next((entity for entity in self.entities if entity.name == name), None)


def _add_issue(
    issues: list[ValidationIssue],
    code: str,
    path: str,
    message: str,
) -> None:
    issues.append(ValidationIssue(code=code, path=path, message=message))


def _as_mapping(
    value: Any,
    *,
    path: str,
    allowed: set[str],
    required: set[str],
    issues: list[ValidationIssue],
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        _add_issue(issues, "TYPE_ERROR", path, "expected a mapping")
        return None

    string_keys = {key for key in value if isinstance(key, str)}
    if len(string_keys) != len(value):
        _add_issue(issues, "UNKNOWN_KEY", path, "all structural keys must be strings")

    for key in sorted(string_keys - allowed):
        _add_issue(issues, "UNKNOWN_KEY", f"{path}.{key}", "unknown structural key")
    for key in sorted(required - string_keys):
        _add_issue(issues, "REQUIRED", f"{path}.{key}", "required key is missing")
    return value


def _as_string(
    value: Any,
    *,
    path: str,
    issues: list[ValidationIssue],
    non_empty: bool = False,
) -> str | None:
    if not isinstance(value, str):
        _add_issue(issues, "TYPE_ERROR", path, "expected a string")
        return None
    if non_empty and not value.strip():
        _add_issue(issues, "EMPTY_VALUE", path, "value must not be empty")
        return None
    return value


def _is_safe_relative_path(value: str, *, allow_root: bool) -> bool:
    if not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    if (
        path.is_absolute() or ".." in path.parts or "\0" in value
        or any(part.casefold() == ".git" or ":" in part for part in path.parts)
    ):
        return False
    return allow_root or path != PurePosixPath(".")


def _parse_selector(
    value: Any,
    *,
    path: str,
    selector_kind: str,
    issues: list[ValidationIssue],
) -> Selector | None:
    mapping = _as_mapping(
        value,
        path=path,
        allowed={"match", "value"},
        required={"match", "value"},
        issues=issues,
    )
    if mapping is None:
        return None

    raw_mode = _as_string(mapping.get("match"), path=f"{path}.match", issues=issues)
    raw_value = _as_string(mapping.get("value"), path=f"{path}.value", issues=issues)
    mode: MatchMode | None = None
    if raw_mode is not None:
        try:
            mode = MatchMode(raw_mode)
        except ValueError:
            _add_issue(
                issues,
                "INVALID_PRESET",
                f"{path}.match",
                "expected one of: exact, regex",
            )

    if raw_value is not None and mode is MatchMode.REGEX:
        try:
            re.compile(raw_value)
        except re.error as exc:
            _add_issue(issues, "INVALID_REGEX", f"{path}.value", str(exc))

    if raw_value is not None and mode is MatchMode.EXACT:
        if selector_kind == "path" and not _is_safe_relative_path(raw_value, allow_root=True):
            _add_issue(
                issues,
                "UNSAFE_PATH",
                f"{path}.value",
                "exact path must be repository-relative and must not contain '..' or backslashes",
            )
        if selector_kind == "filename" and (
            raw_value in {"", ".", ".."} or "/" in raw_value or "\\" in raw_value
        ):
            _add_issue(
                issues,
                "INVALID_FILENAME",
                f"{path}.value",
                "exact filename must be a basename",
            )

    if mode is None or raw_value is None:
        return None
    return Selector(mode=mode, value=raw_value)


def _parse_file_rule(
    value: Any,
    *,
    path: str,
    issues: list[ValidationIssue],
) -> FileRule | None:
    mapping = _as_mapping(
        value,
        path=path,
        allowed={"path", "filename", "format", "template"},
        required={"path", "filename", "format", "template"},
        issues=issues,
    )
    if mapping is None:
        return None

    path_selector = _parse_selector(
        mapping.get("path"), path=f"{path}.path", selector_kind="path", issues=issues
    )
    filename_selector = _parse_selector(
        mapping.get("filename"),
        path=f"{path}.filename",
        selector_kind="filename",
        issues=issues,
    )

    raw_format = _as_string(mapping.get("format"), path=f"{path}.format", issues=issues)
    file_format: FileFormat | None = None
    if raw_format is not None:
        try:
            file_format = FileFormat(raw_format)
        except ValueError:
            allowed_formats = ", ".join(item.value for item in FileFormat)
            _add_issue(
                issues,
                "INVALID_PRESET",
                f"{path}.format",
                f"expected one of: {allowed_formats}",
            )

    raw_template = _as_string(
        mapping.get("template"), path=f"{path}.template", issues=issues
    )
    template: PurePosixPath | None = None
    if raw_template is not None:
        if _is_safe_relative_path(raw_template, allow_root=False):
            template = PurePosixPath(raw_template)
        else:
            _add_issue(
                issues,
                "UNSAFE_PATH",
                f"{path}.template",
                "template must be a repository-relative file path",
            )

    if None in {path_selector, filename_selector, file_format, template}:
        return None
    return FileRule(
        path=path_selector,
        filename=filename_selector,
        format=file_format,
        template=template,
    )


def parse_declaration(text: str, *, source: str = "<memory>") -> RepositoryDeclaration:
    """Parse and strictly validate one DSL v2 YAML declaration."""

    try:
        raw = yaml.load(text, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        issue = ValidationIssue("INVALID_YAML", "$", str(exc))
        raise ArchRepoError(
            ErrorCode.VALIDATION_ERROR,
            f"DSL declaration is not valid YAML: {source}",
            details={"issues": [issue.as_dict()]},
        ) from exc

    issues: list[ValidationIssue] = []
    root = _as_mapping(
        raw,
        path="$",
        allowed={"declaration", "entities"},
        required={"declaration", "entities"},
        issues=issues,
    )
    if root is None:
        _raise_dsl_error(source, issues)

    declaration = _as_mapping(
        root.get("declaration"),
        path="$.declaration",
        allowed={"kind", "version"},
        required={"kind", "version"},
        issues=issues,
    )
    kind: str | None = None
    version: str | None = None
    if declaration is not None:
        kind = _as_string(
            declaration.get("kind"), path="$.declaration.kind", issues=issues
        )
        version = _as_string(
            declaration.get("version"), path="$.declaration.version", issues=issues
        )
        if kind is not None and kind != "architecture_repository":
            _add_issue(
                issues,
                "INVALID_PRESET",
                "$.declaration.kind",
                "expected: architecture_repository",
            )
        if version is not None and version != "v2":
            _add_issue(issues, "UNSUPPORTED_VERSION", "$.declaration.version", "expected: v2")

    entities_value = root.get("entities")
    entities: list[EntityDefinition] = []
    declared_names: list[str] = []
    relation_paths: list[tuple[str, str]] = []
    if not isinstance(entities_value, list):
        _add_issue(issues, "TYPE_ERROR", "$.entities", "expected a sequence")
    else:
        for index, entity_value in enumerate(entities_value):
            entity_path = f"$.entities[{index}]"
            entity_mapping = _as_mapping(
                entity_value,
                path=entity_path,
                allowed={"name", "description", "relations", "files"},
                required={"name", "description", "files"},
                issues=issues,
            )
            if entity_mapping is None:
                continue

            name = _as_string(
                entity_mapping.get("name"),
                path=f"{entity_path}.name",
                issues=issues,
                non_empty=True,
            )
            if name is not None:
                if name in declared_names:
                    _add_issue(
                        issues,
                        "DUPLICATE_ENTITY",
                        f"{entity_path}.name",
                        f"entity name is already declared: {name}",
                    )
                declared_names.append(name)

            description = _as_string(
                entity_mapping.get("description"),
                path=f"{entity_path}.description",
                issues=issues,
                non_empty=True,
            )

            relations: list[str] = []
            relations_value = entity_mapping.get("relations", [])
            if not isinstance(relations_value, list):
                _add_issue(
                    issues, "TYPE_ERROR", f"{entity_path}.relations", "expected a sequence"
                )
            else:
                for relation_index, relation_value in enumerate(relations_value):
                    relation_path = f"{entity_path}.relations[{relation_index}]"
                    relation = _as_string(
                        relation_value,
                        path=relation_path,
                        issues=issues,
                        non_empty=True,
                    )
                    if relation is None:
                        continue
                    if relation in relations:
                        _add_issue(
                            issues,
                            "DUPLICATE_RELATION",
                            relation_path,
                            f"relation is already declared: {relation}",
                        )
                    relations.append(relation)
                    relation_paths.append((relation_path, relation))

            file_rule = _parse_file_rule(
                entity_mapping.get("files"), path=f"{entity_path}.files", issues=issues
            )
            if name is not None and description is not None and file_rule is not None:
                entities.append(
                    EntityDefinition(
                        name=name,
                        description=description.strip(),
                        relations=tuple(relations),
                        files=file_rule,
                    )
                )

    known_names = set(declared_names)
    for relation_path, relation in relation_paths:
        if relation not in known_names:
            _add_issue(
                issues,
                "UNKNOWN_RELATION",
                relation_path,
                f"relation references an unknown entity: {relation}",
            )

    if issues or kind is None or version is None:
        _raise_dsl_error(source, issues)
    return RepositoryDeclaration(kind=kind, version=version, entities=tuple(entities))


def load_declaration(path: Path) -> RepositoryDeclaration:
    """Read a UTF-8 declaration from disk and parse it."""

    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ArchRepoError(
            ErrorCode.NOT_FOUND,
            "DSL declaration was not found",
            details={"path": path.name},
        ) from exc
    except (OSError, UnicodeError) as exc:
        raise ArchRepoError(
            ErrorCode.INVALID_REPOSITORY,
            "DSL declaration could not be read as UTF-8",
            details={"path": path.name},
        ) from exc
    return parse_declaration(text, source=path.name)


def _raise_dsl_error(source: str, issues: list[ValidationIssue]) -> None:
    ordered_issues = sorted(issues, key=lambda issue: (issue.path, issue.code, issue.message))
    raise ArchRepoError(
        ErrorCode.VALIDATION_ERROR,
        f"DSL declaration is invalid: {source}",
        details={"issues": [issue.as_dict() for issue in ordered_issues]},
    )
