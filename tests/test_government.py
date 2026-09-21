from __future__ import annotations

from pathlib import Path

from arch_repo_mcp.dsl import load_declaration
from arch_repo_mcp.entities import (
    create_entity,
    read_entity,
    read_related_entities,
    update_entity,
)
from arch_repo_mcp.government import (
    describe_government_repository,
    ensure_government_repository,
    list_working_repositories,
)
from arch_repo_mcp.repository import create_repository
from arch_repo_mcp.server import entity_list as mcp_entity_list
from arch_repo_mcp.server import repository_open
from arch_repo_mcp.workspace import (
    GOVERNMENT_REPOSITORY_ENV,
    WORKSPACE_ENV,
    load_workspace_config,
)

PROJECT_ROOT = Path(__file__).parents[1]
NORMATIVE_DSL = PROJECT_ROOT / "specs" / "dsl"
PACKAGED_DSL = PROJECT_ROOT / "src" / "arch_repo_mcp" / "presets" / "government"


def test_packaged_government_preset_matches_normative_dsl() -> None:
    normative = load_declaration(NORMATIVE_DSL / "architecture.yaml")
    packaged = load_declaration(PACKAGED_DSL / "architecture.yaml")

    assert packaged == normative
    for entity in normative.entities:
        relative = Path(*entity.files.template.parts)
        assert (PACKAGED_DSL / relative).read_text(encoding="utf-8") == (
            NORMATIVE_DSL / relative
        ).read_text(encoding="utf-8")


def test_workspace_config_precedence_is_stdio_then_environment_then_dotenv(
    tmp_path: Path,
) -> None:
    file_workspace = tmp_path / "from-file"
    environment_workspace = tmp_path / "from-environment"
    stdio_workspace = tmp_path / "from-stdio"
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"{WORKSPACE_ENV}={file_workspace}\n"
        f"{GOVERNMENT_REPOSITORY_ENV}=from-file-government\n",
        encoding="utf-8",
    )

    file_config = load_workspace_config(
        env_file=env_file,
        environment={},
        create_workspace=True,
    )
    environment_config = load_workspace_config(
        env_file=env_file,
        environment={
            WORKSPACE_ENV: str(environment_workspace),
            GOVERNMENT_REPOSITORY_ENV: "from-environment-government",
        },
        create_workspace=True,
    )

    config = load_workspace_config(
        stdio_workspace,
        "from-stdio-government",
        env_file,
        environment={
            WORKSPACE_ENV: str(environment_workspace),
            GOVERNMENT_REPOSITORY_ENV: "from-environment-government",
        },
        create_workspace=True,
    )

    assert config.root == stdio_workspace.resolve()
    assert config.government_repository == (
        stdio_workspace / "from-stdio-government"
    ).resolve()
    assert file_config.root == file_workspace.resolve()
    assert file_config.government_repository == (
        file_workspace / "from-file-government"
    ).resolve()
    assert environment_config.root == environment_workspace.resolve()
    assert environment_config.government_repository == (
        environment_workspace / "from-environment-government"
    ).resolve()


def test_government_repository_is_created_and_described_from_defaults(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repositories"

    description = describe_government_repository(workspace)
    government = ensure_government_repository(workspace)

    assert Path(description["government_repository_root"]) == workspace / "government"
    assert government.created is False
    assert (workspace / "government" / ".git").is_dir()
    assert {entity["name"] for entity in description["entities"]} == {
        "fact",
        "requirement",
        "architecture_artifact",
        "category",
    }
    normative = load_declaration(NORMATIVE_DSL / "architecture.yaml")
    returned = {entity["name"]: entity for entity in description["entities"]}
    for declared in normative.entities:
        entity = returned[declared.name]
        assert entity["description"] == declared.description
        assert entity["semantic_purpose"] == declared.description
        assert entity["relations"] == list(declared.relations)
        assert entity["path_rule"] == {
            "match": declared.files.path.mode.value,
            "value": declared.files.path.value,
        }
        assert entity["filename_rule"] == {
            "match": declared.files.filename.mode.value,
            "value": declared.files.filename.value,
        }
        assert entity["format"] == declared.files.format.value
        assert entity["template_path"] == declared.files.template.as_posix()
        assert entity["template_content"] == (
            NORMATIVE_DSL / Path(*declared.files.template.parts)
        ).read_text(encoding="utf-8")


def test_repository_list_excludes_government_and_requires_explicit_selection(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "repositories"
    government = ensure_government_repository(workspace)
    working = workspace / "payments"
    create_repository(working, government.context.root / "architecture.yaml")

    result = list_working_repositories(workspace)

    assert result["government_repository_root"] == str(government.context.root)
    assert result["repositories"] == [
        {
            "name": "payments",
            "repository_path": str(working.resolve()),
            "declaration_path": "architecture.yaml",
            "valid": True,
            "model_matches_government": True,
            "entity_counts": {
                "architecture_artifact": 0,
                "category": 0,
                "fact": 0,
                "requirement": 0,
            },
            "issues": [],
        }
    ]


def test_agent_scenario_classifies_source_and_materializes_entities(
    tmp_path: Path,
) -> None:
    source_document = (
        "Система обязана хранить аудит 365 дней. "
        "События аудита уже передаются в локальный PostgreSQL."
    )
    workspace = tmp_path / "repositories"
    model = describe_government_repository(workspace)
    working = workspace / "audit-platform"
    create_repository(working, model["declaration_source"])

    entity_names = {entity["name"] for entity in model["entities"]}
    assert {"requirement", "fact"} <= entity_names
    assert "обязана" in source_document
    assert "уже" in source_document

    create_entity(working, "requirement", "requirements/R-0001.md")
    update_entity(
        working,
        "requirement",
        "requirements/R-0001.md",
        """---
id: R-0001
title: Хранение аудита
status: draft
priority: medium
source: Техническое задание
relations:
  - entity: category
    files: []
  - entity: architecture_artifact
    files: []
---

# Хранение аудита

Система обязана хранить аудит 365 дней.
""",
    )
    create_entity(working, "fact", "facts/F-0001.md")
    update_entity(
        working,
        "fact",
        "facts/F-0001.md",
        """---
id: F-0001
title: Хранилище аудита
status: draft
source: Техническое задание
relations:
  - entity: requirement
    files: [R-0001.md]
  - entity: category
    files: [C-9999.md]
  - entity: architecture_artifact
    files: []
---

# Хранилище аудита

События аудита передаются в локальный PostgreSQL.
""",
    )

    listed = list_working_repositories(workspace)["repositories"]
    selected_repository = listed[0]["repository_path"]
    assert read_entity(
        selected_repository, "requirement", "requirements/R-0001.md"
    )["content"].endswith("Система обязана хранить аудит 365 дней.\n")
    assert read_entity(selected_repository, "fact", "facts/F-0001.md")[
        "content"
    ].endswith("События аудита передаются в локальный PostgreSQL.\n")
    related = read_related_entities(
        selected_repository,
        "fact",
        "facts/F-0001.md",
    )["relations"]
    assert related[0]["entity"] == "requirement"
    assert related[0]["status"] == "found"
    assert related[0]["content"].endswith("Система обязана хранить аудит 365 дней.\n")
    assert related[1] == {
        "source_entity": "fact",
        "source_path": "facts/F-0001.md",
        "entity": "category",
        "filename": "C-9999.md",
        "relation_valid": True,
        "found": False,
        "status": "missing",
        "path": None,
        "expected_path": "categories/C-9999.md",
        "candidate_paths": [],
        "format": "markdown_front_matter",
        "content": None,
    }


def test_stdio_tools_resolve_relative_repository_from_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "repositories"
    government = ensure_government_repository(workspace)
    create_repository(workspace / "selected", government.context.root / "architecture.yaml")
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))

    result = repository_open("selected")

    assert result["ok"] is True
    assert result["result"]["repository_root"] == str((workspace / "selected").resolve())


def test_entity_tools_reject_government_repository_when_workspace_is_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "repositories"
    ensure_government_repository(workspace)
    monkeypatch.setenv(WORKSPACE_ENV, str(workspace))

    result = mcp_entity_list("government", "fact")

    assert result["ok"] is False
    assert result["error"]["code"] == "PERMISSION_DENIED"
