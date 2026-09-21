from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from arch_repo_mcp.entities import (
    create_entity,
    delete_entity,
    list_entities,
    read_entity,
    search_entities,
    update_entity,
)
from arch_repo_mcp.errors import ArchRepoError, ErrorCode
from arch_repo_mcp.repository import (
    create_repository,
    discover_repository_root,
    open_repository,
    validate_repository,
)

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

VALID_MARKDOWN = """\
---
title: Local-first repository
---

The current architecture state is local.
"""


def _git(*arguments: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _make_repository(tmp_path: Path) -> Path:
    repository = tmp_path / "architecture-repository"
    (repository / "facts").mkdir(parents=True)
    (repository / "templates").mkdir()
    (repository / "architecture.yaml").write_text(DECLARATION, encoding="utf-8")
    (repository / "templates" / "fact.md").write_text(VALID_MARKDOWN, encoding="utf-8")
    (repository / "facts" / "F-0001.md").write_text(VALID_MARKDOWN, encoding="utf-8")
    _git("init", "--quiet", cwd=repository)
    return repository


def _make_declaration_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "declaration-bundle"
    (bundle / "templates").mkdir(parents=True)
    declaration = bundle / "minimal.yaml"
    declaration.write_text(DECLARATION, encoding="utf-8")
    (bundle / "templates" / "fact.md").write_text(VALID_MARKDOWN, encoding="utf-8")
    return declaration


def test_repository_create_initializes_valid_uncommitted_repository(tmp_path: Path) -> None:
    declaration = _make_declaration_bundle(tmp_path)
    target = tmp_path / "created-repository"

    context = create_repository(target, declaration, initial_branch="architecture")

    assert context.root == target.resolve()
    assert (target / ".git").is_dir()
    assert (target / "architecture.yaml").read_text(encoding="utf-8") == DECLARATION
    assert (target / "templates" / "fact.md").read_text(encoding="utf-8") == VALID_MARKDOWN
    assert (target / "facts").is_dir()
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert branch == "architecture"
    assert "architecture.yaml" in status
    assert "templates/" in status


def test_repository_create_rejects_existing_target(tmp_path: Path) -> None:
    declaration = _make_declaration_bundle(tmp_path)
    target = tmp_path / "existing"
    target.mkdir()

    with pytest.raises(ArchRepoError) as captured:
        create_repository(target, declaration)

    assert captured.value.code is ErrorCode.CONFLICT
    assert list(target.iterdir()) == []


def test_repository_create_rolls_back_when_template_is_missing(tmp_path: Path) -> None:
    declaration = _make_declaration_bundle(tmp_path)
    (declaration.parent / "templates" / "fact.md").unlink()
    target = tmp_path / "not-created"

    with pytest.raises(ArchRepoError) as captured:
        create_repository(target, declaration)

    assert captured.value.code is ErrorCode.NOT_FOUND
    assert not target.exists()
    assert not list(tmp_path.glob(".not-created.archrepo-*"))


def test_repository_create_rejects_invalid_initial_branch(tmp_path: Path) -> None:
    declaration = _make_declaration_bundle(tmp_path)
    target = tmp_path / "not-created"

    with pytest.raises(ArchRepoError) as captured:
        create_repository(target, declaration, initial_branch="invalid branch")

    assert captured.value.code is ErrorCode.VALIDATION_ERROR
    assert not target.exists()


def test_valid_repository_opens_and_counts_entities(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    report = validate_repository(repository)
    context = open_repository(repository)

    assert report.valid
    assert report.entity_counts == {"fact": 1}
    assert report.issues == ()
    assert context.root == repository.resolve()
    assert context.declaration.entity("fact") is not None


def test_repository_root_is_discovered_from_subdirectory(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    assert discover_repository_root(repository / "facts") == repository.resolve()


def test_non_git_directory_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ArchRepoError) as captured:
        discover_repository_root(tmp_path)

    assert captured.value.code is ErrorCode.INVALID_REPOSITORY


def test_missing_template_is_reported(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    (repository / "templates" / "fact.md").unlink()

    report = validate_repository(repository)

    assert not report.valid
    assert [issue.code for issue in report.issues] == ["NOT_FOUND"]
    assert report.issues[0].path == "templates/fact.md"


def test_invalid_front_matter_is_reported(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    (repository / "facts" / "F-0001.md").write_text("no front matter", encoding="utf-8")

    report = validate_repository(repository)

    assert not report.valid
    assert report.issues[0].code == "INVALID_CONTENT"
    assert report.issues[0].path == "facts/F-0001.md"


def test_matching_overlap_is_reported(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    overlap = DECLARATION + """\
  - name: duplicate_fact
    files:
      path: {match: exact, value: facts}
      filename: {match: regex, value: '^F-[0-9]{4}\\.md$'}
      format: markdown_front_matter
      template: templates/duplicate-fact.md
"""
    (repository / "architecture.yaml").write_text(overlap, encoding="utf-8")
    (repository / "templates" / "duplicate-fact.md").write_text(
        VALID_MARKDOWN, encoding="utf-8"
    )

    report = validate_repository(repository)

    assert not report.valid
    assert any(issue.code == "MATCH_CONFLICT" for issue in report.issues)


def test_declaration_path_cannot_escape_repository(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    report = validate_repository(repository, "../architecture.yaml")

    assert not report.valid
    assert report.issues[0].code == "INVALID_REPOSITORY"


def test_entity_list_read_and_search_use_dsl_membership(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    listed = list_entities(repository, "fact")
    read = read_entity(repository, "fact", "facts/F-0001.md")
    searched = search_entities(repository, "CURRENT ARCHITECTURE", "fact")

    assert [item.path for item in listed] == ["facts/F-0001.md"]
    assert read["entity"] == "fact"
    assert read["content"] == VALID_MARKDOWN
    assert [item.path for item in searched] == ["facts/F-0001.md"]
    assert searched[0].matching_lines == (5,)


def test_entity_create_copies_template_without_committing(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    created = create_entity(repository, "fact", "facts/F-0002.md")

    assert created.path == "facts/F-0002.md"
    assert (repository / created.path).read_text(encoding="utf-8") == VALID_MARKDOWN
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    assert "facts/" in status
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert head.returncode != 0


def test_entity_create_recreates_valid_missing_parent_directory(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    (repository / "facts" / "F-0001.md").unlink()
    (repository / "facts").rmdir()

    created = create_entity(repository, "fact", "facts/F-0002.md")

    assert created.path == "facts/F-0002.md"
    assert (repository / "facts").is_dir()


def test_entity_create_rejects_existing_file(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    with pytest.raises(ArchRepoError) as captured:
        create_entity(repository, "fact", "facts/F-0001.md")

    assert captured.value.code is ErrorCode.CONFLICT


def test_entity_update_replaces_valid_content(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    updated_content = VALID_MARKDOWN.replace("local.", "validated locally.")

    updated = update_entity(repository, "fact", "facts/F-0001.md", updated_content)

    assert updated.path == "facts/F-0001.md"
    assert (repository / updated.path).read_text(encoding="utf-8") == updated_content


def test_entity_update_rolls_back_invalid_content(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)
    entity_path = repository / "facts" / "F-0001.md"

    with pytest.raises(ArchRepoError) as captured:
        update_entity(repository, "fact", "facts/F-0001.md", "missing front matter")

    assert captured.value.code is ErrorCode.VALIDATION_ERROR
    assert entity_path.read_text(encoding="utf-8") == VALID_MARKDOWN
    assert validate_repository(repository).valid


def test_entity_delete_removes_only_local_file(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    deleted = delete_entity(repository, "fact", "facts/F-0001.md")

    assert deleted == {"entity": "fact", "path": "facts/F-0001.md"}
    assert not (repository / "facts" / "F-0001.md").exists()
    assert (repository / "facts").is_dir()
    assert validate_repository(repository).valid


def test_entity_read_rejects_path_traversal(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    with pytest.raises(ArchRepoError) as captured:
        read_entity(repository, "fact", "../F-0001.md")

    assert captured.value.code is ErrorCode.PERMISSION_DENIED


def test_unknown_entity_type_is_not_found(tmp_path: Path) -> None:
    repository = _make_repository(tmp_path)

    with pytest.raises(ArchRepoError) as captured:
        list_entities(repository, "requirement")

    assert captured.value.code is ErrorCode.NOT_FOUND
