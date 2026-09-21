# ArchRepoMCP

MCP-сервер для локального управления архитектурными Git-репозиториями. Структура
сущностей задаётся декларацией DSL, а удалённые Git-сервисы рассматриваются только как
явный контур синхронизации.

Проект находится на ранней стадии разработки. Текущий вертикальный срез уже позволяет
AI-агенту открыть и проверить локальный repository, получить список DSL-сущностей,
прочитать их и выполнить текстовый поиск. Эти операции не используют сеть и не изменяют
working tree.

## Реализовано

- строгий parser и validator DSL `architecture_repository/v2`;
- закрытая грамматика, проверка presets, relations, regex и duplicate YAML keys;
- обнаружение корня локального Git repository без сетевых операций;
- repository confinement и запрет symbolic-link обходов;
- проверка templates, конфликтов file matching и форматов файлов;
- read-only Entity Service: `list`, `read`, `search`;
- MCP server на официальном Python SDK v2 со stdio transport;
- нормализованная модель ошибок;
- автоматические DSL, repository, entity и MCP contract tests.

Пока не реализованы создание и изменение сущностей, создание repository, local Git
operations, clone/pull/publish и Forgejo provider. Они будут добавляться отдельными слоями
в соответствии с дорожной картой из `AGENTS.md`.

## Архитектура текущего среза

```text
MCP tools
   │
   ├── repository_open / repository_validate
   └── entity_list / entity_read / entity_search
                │
                ▼
       Local Repository Service
                │
                ▼
          DSL v2 Engine
                │
                ▼
     Local Git Repository (read-only)
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
| `repository_open` | Открыть и полностью проверить локальный architecture repository |
| `repository_validate` | Получить детальный validation report без изменения repository |
| `entity_list` | Получить список экземпляров указанного DSL entity |
| `entity_read` | Прочитать один экземпляр по repository-relative path |
| `entity_search` | Найти текст во всех или в указанном типе entity |

Все tools принимают `repository_path`. Необязательный `declaration_path` по умолчанию
равен явно документированному `architecture.yaml`. Ответ имеет единый envelope:

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
