from __future__ import annotations

from pathlib import Path, PurePosixPath

import pytest

from arch_repo_mcp.dsl import load_declaration, parse_declaration
from arch_repo_mcp.errors import ArchRepoError, ErrorCode

PROJECT_ROOT = Path(__file__).parents[1]
EXAMPLES = PROJECT_ROOT / "specs" / "examples" / "declarations"


@pytest.mark.parametrize(
    "filename, expected_entities",
    [
        ("minimal.yaml", {"fact"}),
        ("standard.yaml", {"fact", "requirement", "architecture_artifact", "category"}),
        ("relations.yaml", {"fact", "requirement", "architecture_artifact", "category"}),
        ("regex-paths.yaml", {"network_fact", "regulatory_requirement"}),
    ],
)
def test_normative_examples_are_valid(filename: str, expected_entities: set[str]) -> None:
    declaration = load_declaration(EXAMPLES / filename)

    assert declaration.kind == "architecture_repository"
    assert declaration.version == "v2"
    assert {entity.name for entity in declaration.entities} == expected_entities


def test_regex_selectors_use_full_match() -> None:
    declaration = load_declaration(EXAMPLES / "regex-paths.yaml")
    network_fact = declaration.entity("network_fact")

    assert network_fact is not None
    assert network_fact.matches(PurePosixPath("systems/payments/network-facts/NF-12.md"))
    assert not network_fact.matches(PurePosixPath("x/systems/payments/network-facts/NF-12.md"))
    assert not network_fact.matches(PurePosixPath("systems/payments/network-facts/NF-12.md.bak"))


def test_closed_grammar_rejects_unknown_structural_key() -> None:
    text = """
declaration:
  kind: architecture_repository
  version: v2
  undocumented: true
entities: []
"""

    with pytest.raises(ArchRepoError) as captured:
        parse_declaration(text)

    assert captured.value.code is ErrorCode.VALIDATION_ERROR
    assert captured.value.details["issues"] == [
        {
            "code": "UNKNOWN_KEY",
            "path": "$.declaration.undocumented",
            "message": "unknown structural key",
        }
    ]


def test_duplicate_yaml_keys_are_rejected() -> None:
    text = """
declaration:
  kind: architecture_repository
  kind: architecture_repository
  version: v2
entities: []
"""

    with pytest.raises(ArchRepoError) as captured:
        parse_declaration(text)

    assert captured.value.details["issues"][0]["code"] == "INVALID_YAML"


def test_unknown_and_duplicate_relations_are_rejected() -> None:
    text = """
declaration:
  kind: architecture_repository
  version: v2
entities:
  - name: fact
    description: A verified architecture fact.
    relations: [missing, missing]
    files:
      path: {match: exact, value: facts}
      filename: {match: regex, value: '^F-[0-9]+\\.md$'}
      format: markdown
      template: templates/fact.md
"""

    with pytest.raises(ArchRepoError) as captured:
        parse_declaration(text)

    issue_codes = [issue["code"] for issue in captured.value.details["issues"]]
    assert issue_codes == ["UNKNOWN_RELATION", "DUPLICATE_RELATION", "UNKNOWN_RELATION"]


@pytest.mark.parametrize(
    "template",
    ["../outside.md", "/absolute.md", "templates\\windows.md", "."],
)
def test_unsafe_template_paths_are_rejected(template: str) -> None:
    text = f"""
declaration:
  kind: architecture_repository
  version: v2
entities:
  - name: fact
    description: A verified architecture fact.
    files:
      path: {{match: exact, value: facts}}
      filename: {{match: exact, value: F-0001.md}}
      format: markdown
      template: {template!r}
"""

    with pytest.raises(ArchRepoError) as captured:
        parse_declaration(text)

    assert any(
        issue["code"] == "UNSAFE_PATH" for issue in captured.value.details["issues"]
    )


def test_duplicate_entity_names_are_rejected() -> None:
    text = """
declaration:
  kind: architecture_repository
  version: v2
entities:
  - &entity
    name: fact
    files:
      path: {match: exact, value: facts}
      filename: {match: exact, value: F-0001.md}
      format: markdown
      template: templates/fact.md
  - *entity
"""

    with pytest.raises(ArchRepoError) as captured:
        parse_declaration(text)

    assert any(
        issue["code"] == "DUPLICATE_ENTITY" for issue in captured.value.details["issues"]
    )
