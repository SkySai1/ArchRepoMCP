# ArchRepoMCP

MCP-сервер для локального управления архитектурными Git-репозиториями. Структура
сущностей задаётся декларацией DSL, а удалённые Git-сервисы рассматриваются только как
явный контур синхронизации.

Проект находится на ранней стадии разработки. Текущий вертикальный срез уже позволяет
AI-агенту создать, открыть и проверить локальный repository, управлять DSL-сущностями и
исследовать локальное Git-состояние. Ни одна из реализованных операций не использует сеть
или автоматически создаёт commit.

## Реализовано

- строгий parser и validator DSL `architecture_repository/v2`;
- закрытая грамматика, проверка presets, relations, regex и duplicate YAML keys;
- обнаружение корня локального Git repository без сетевых операций;
- repository confinement и запрет symbolic-link обходов;
- проверка templates, конфликтов file matching и форматов файлов;
- безопасное создание repository из декларации и её template bundle;
- Entity Service: `list`, `read`, `search`, `create`, `update`, `delete`;
- rollback entity mutations, не прошедших полную repository validation;
- Local Git Service: `status`, `diff`, `history`, `list/create branch`;
- MCP server на официальном Python SDK v2 со stdio transport;
- нормализованная модель ошибок;
- автоматические DSL, repository, entity и MCP contract tests.

Пока не реализованы commit, branch switch, remotes, clone/pull/publish и Forgejo provider.
Они будут добавляться отдельными слоями в соответствии с дорожной картой из `AGENTS.md`.

## Архитектура текущего среза

```text
MCP tools
   │
   ├── Repository Service ── create / open / validate
   ├── Entity Service ────── list / read / search / create / update / delete
   └── Local Git Service ─── status / diff / history / branches
                │
                ├── DSL v2 Engine
                │
                ▼
          Local Git Repository
```

Нормативные документы расположены в `specs/`, реализация — в `src/`, а проверки
соответствия — в `tests/`.

## Требования

- Python 3.11 или новее;
- Git, доступный через `PATH`;
- Windows, Linux или macOS.

## Установка для разработки

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Linux/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Запуск MCP

После установки пакет предоставляет stdio-команду:

```text
arch-repo-mcp
```

Эквивалентный запуск через Python:

```text
python -m arch_repo_mcp.server
```

Для MCP host команда настраивается как stdio server. Минимальный пример конфигурации:

```json
{
  "mcpServers": {
    "arch-repo": {
      "command": "arch-repo-mcp"
    }
  }
}
```

Конкретный формат файла конфигурации зависит от MCP host. Команда должна запускаться в
окружении, где установлен пакет `arch-repo-mcp`.

## MCP tools

| Tool | Назначение |
| --- | --- |
| `repository_create` | Создать локальный Git repository из DSL declaration bundle |
| `repository_open` | Открыть и полностью проверить локальный architecture repository |
| `repository_validate` | Получить детальный validation report без изменения repository |
| `repository_status` | Получить структурированный локальный Git status |
| `repository_diff` | Получить working-tree, staged или revision diff |
| `repository_history` | Получить ограниченную локальную commit history |
| `repository_branches` | Получить список локальных веток |
| `branch_create` | Создать локальную ветку без автоматического switch |
| `entity_create` | Создать entity из объявленного template |
| `entity_list` | Получить список экземпляров указанного DSL entity |
| `entity_read` | Прочитать один экземпляр по repository-relative path |
| `entity_search` | Найти текст во всех или в указанном типе entity |
| `entity_update` | Локально заменить entity с validation и rollback |
| `entity_delete` | Локально удалить entity с validation и rollback |

Все tools кроме `repository_create` принимают `repository_path`. Repository и Entity tools
также принимают необязательный `declaration_path` с явно документированным значением по
умолчанию `architecture.yaml`. Git inspection отделён от DSL validation и остаётся доступен
для диагностики невалидного working tree. Ответ имеет единый envelope:

```json
{
  "ok": true,
  "result": {}
}
```

или:

```json
{
  "ok": false,
  "error": {
    "code": "INVALID_REPOSITORY",
    "message": "Architecture repository validation failed",
    "details": {}
  }
}
```

### Создание repository

`repository_create` принимает отсутствующий `target_path` и путь к исходной DSL-декларации
`declaration_source`. Все указанные декларацией templates должны находиться рядом с ней по
repository-relative путям. Сначала bundle полностью проверяется, затем во временном
staging-каталоге выполняется `git init`, и только валидный результат переносится в target.

Начальная ветка задаётся параметром `initial_branch` с документированным значением по
умолчанию `main`. Операция не создаёт commit и не настраивает remote.

### Изменение entities

`entity_create` всегда использует объявленный DSL template как стартовое содержимое.
`entity_update` принимает полное новое UTF-8 содержимое. Все три mutation tools оставляют
изменения только в working tree, выполняют полную validation и восстанавливают исходное
состояние при ошибке. Commit или push автоматически не выполняются.

## Минимальная DSL-декларация

```yaml
declaration:
  kind: architecture_repository
  version: v2

entities:
  - name: fact
    files:
      path:
        match: exact
        value: facts
      filename:
        match: regex
        value: '^F-[0-9]{4}\.md$'
      format: markdown_front_matter
      template: templates/fact.md
```

Для каждого entity один matched-файл считается одним экземпляром. `path` сопоставляется
с repository-relative parent path, `filename` — только с basename. Regex применяется как
full match. Один файл не может одновременно принадлежать нескольким entities.

Поддерживаемые форматы: `yaml`, `json`, `markdown`, `markdown_front_matter`, `text`.
Полный нормативный контракт находится в `specs/dsl/DSL_V2_TABLES.md`, валидные примеры —
в `specs/examples/declarations/`.

## Проверки

```text
python -m pytest
python -m ruff check .
```

Тесты создают временные локальные Git repositories и не требуют Forgejo или доступа к
сети.

## Forgejo и credentials

Интеграция с Forgejo ещё не включена в runtime. Для будущих integration tests параметры
берутся только из локального `.forgejo.env` или переменных окружения:

```text
FORGEJO_URL
FORGEJO_API_URL
FORGEJO_TOKEN
FORGEJO_USERNAME
FORGEJO_ORGANIZATION
FORGEJO_DEFAULT_BRANCH
FORGEJO_DEFAULT_PRIVATE
FORGEJO_TLS_VERIFY
```

Локальные файлы `.forgejo.env`, `forgejo.env` и `forgego.env` исключены из Git. Tokens и
другие credentials нельзя помещать в DSL, source code, test data, logs или исключения.

## Основные принципы

- local repository first;
- contract-driven API;
- DSL-driven file model без hardcoded `facts/requirements/categories`;
- никаких implicit commit, push, pull, merge, rebase, stash или reset;
- публикация только после validation и только явной командой;
- provider independence и полноценная offline-работа локальных функций.

Проект распространяется по лицензии MIT.
