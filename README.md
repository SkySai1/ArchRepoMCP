# ArchRepoMCP

MCP-сервер для локального управления архитектурными Git-репозиториями. Структура
сущностей задаётся декларацией DSL, а удалённые Git-сервисы рассматриваются только как
явный контур синхронизации.

Текущий MVP позволяет AI-агенту сначала получить из government repository полную модель
сущностей и шаблоны, затем явно выбрать рабочий repository и локально управлять его
содержимым. Доступ к remote выполняется только через отдельные явные операции; остальные
возможности полностью работают offline.

## Реализовано

- строгий parser и validator DSL `architecture_repository/v2`;
- обязательное семантическое `description` для каждого entity type;
- закрытая грамматика, проверка presets, relations, regex и duplicate YAML keys;
- обнаружение корня локального Git repository без сетевых операций;
- repository confinement и запрет symbolic-link обходов;
- проверка templates, конфликтов file matching и форматов файлов;
- безопасное создание repository из декларации и её template bundle;
- автоматически создаваемый government repository со встроенным нормативным preset;
- описание AI-facing модели через `repository_describe` и явный выбор через `repository_list`;
- единый локальный workspace, настраиваемый через stdio, environment или `.env`;
- Entity Service: `list`, `read`, `search`, `create`, `update`, `delete`;
- rollback entity mutations, не прошедших полную repository validation;
- Local Git Service: `status`, `diff`, `history`, `commit`, branches и remotes;
- Remote Sync Service: явные `clone`, `fetch`, безопасный fast-forward `pull` и `publish`;
- MCP server на официальном Python SDK v2 со stdio transport;
- нормализованная модель ошибок;
- автоматические DSL, repository, entity, local Git, remote sync и MCP contract tests.

## Архитектура текущего среза

```text
MCP tools
   │
   ├── Government Model ───── initialize / describe / list repositories
   ├── Repository Service ─── create / open / validate
   ├── Entity Service ────── list / read / search / create / update / delete
   ├── Local Git Service ─── status / diff / history / commit / branches / remotes
   └── Remote Sync Service ── clone / fetch / pull / publish
                │                         │
                ├── DSL v2 Engine         └── explicit Git transport
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

Для MCP host команда настраивается как stdio server. Рекомендуемый пример конфигурации:

```json
{
  "mcpServers": {
    "arch-repo": {
      "command": "arch-repo-mcp",
      "env": {
        "ARCH_REPO_MCP_WORKSPACE": "D:\\ArchitectureRepositories",
        "ARCH_REPO_MCP_GOVERNMENT_REPOSITORY": "government"
      }
    }
  }
}
```

Конкретный формат файла конфигурации зависит от MCP host. Команда должна запускаться в
окружении, где установлен пакет `arch-repo-mcp`.

### Workspace и `.env`

`ARCH_REPO_MCP_WORKSPACE` задаёт локальную директорию, внутри которой находятся government
и все рабочие repositories. `ARCH_REPO_MCP_GOVERNMENT_REPOSITORY` задаёт абсолютный путь
внутри workspace либо относительный путь; значение по умолчанию — `government`.

Те же значения можно сохранить в `.env` текущей директории процесса:

```dotenv
ARCH_REPO_MCP_WORKSPACE=D:/ArchitectureRepositories
ARCH_REPO_MCP_GOVERNMENT_REPOSITORY=government
```

Другой env-файл выбирается через `ARCH_REPO_MCP_ENV_FILE`. Для
`government_repository_initialize`, `repository_describe` и `repository_list` значения
можно передать непосредственно по stdio в аргументах `workspace_path`,
`government_repository_path` и `env_file`. Приоритет: stdio-аргумент, process environment,
`.env`, затем документированное имя government repository по умолчанию.

Если workspace настроен, относительные `repository_path` и `target_path` разрешаются внутри
него, а выход за его границы отклоняется. Entity tools дополнительно запрещают использовать
government repository как рабочий.

## Запуск в Goose на macOS

Goose подключает локальные MCP-серверы как STDIO extensions. Сначала установите нужный клиент
Goose через Homebrew (CLI, Desktop или оба):

```bash
brew install block-goose-cli
brew install --cask block-goose
```

Настройте LLM provider при первом запуске Goose или позднее через `goose configure` в CLI либо
`Settings` → `Models` в Desktop. Затем подготовьте ArchRepoMCP и локальный workspace. Во всех
следующих примерах замените `/Users/you/...` своими абсолютными путями:

```bash
cd /Users/you/src/ArchRepoMCP
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
mkdir -p /Users/you/ArchitectureRepositories
```

Используйте абсолютный путь к `.venv/bin/arch-repo-mcp`: Goose Desktop может не наследовать
`PATH` интерактивной shell. Переменные окружения также лучше передать в настройках extension,
поскольку рабочая директория процесса Goose не обязана совпадать с каталогом проекта.

### Goose CLI

Для постоянного подключения выполните:

```bash
goose configure
```

В интерактивном меню выберите `Add Extension` → `Command-Line Extension` и укажите:

- name: `ArchRepoMCP`;
- command: `/Users/you/src/ArchRepoMCP/.venv/bin/arch-repo-mcp`;
- timeout: `300`;
- environment variable `ARCH_REPO_MCP_WORKSPACE`:
  `/Users/you/ArchitectureRepositories`;
- environment variable `ARCH_REPO_MCP_GOVERNMENT_REPOSITORY`: `government`.

После добавления запустите обычную сессию:

```bash
goose session
```

Для одноразовой сессии без сохранения extension в конфигурации Goose используйте:

```bash
goose session --with-extension \
  "ARCH_REPO_MCP_WORKSPACE=/Users/you/ArchitectureRepositories ARCH_REPO_MCP_GOVERNMENT_REPOSITORY=government /Users/you/src/ArchRepoMCP/.venv/bin/arch-repo-mcp"
```

### Goose Desktop (GUI)

1. Откройте боковую панель Goose Desktop и перейдите в `Extensions`.
2. Нажмите `Add custom extension`.
3. Выберите type `Standard IO`, задайте ID `arch-repo-mcp`, name `ArchRepoMCP` и command
   `/Users/you/src/ArchRepoMCP/.venv/bin/arch-repo-mcp`.
4. Добавьте через отдельную кнопку `Add` обе переменные окружения из CLI-инструкции выше и
   установите timeout `300`.
5. Нажмите `Add`, убедитесь, что extension включён, и начните новую сессию.

Для проверки подключения попросите Goose: `Вызови repository_describe, затем repository_list`.
Первый вызов автоматически создаст government repository со встроенными DSL-декларацией и
шаблонами, если его ещё нет. Конфигурация CLI и Desktop общая и хранится Goose в
`~/.config/goose/config.yaml`.

Актуальные названия пунктов интерфейса и варианты установки приведены в официальной
[инструкции по установке Goose](https://goose-docs.ai/docs/getting-started/installation/) и
[документации по extensions](https://goose-docs.ai/docs/getting-started/using-extensions/).

## MCP tools

| Tool | Назначение |
| --- | --- |
| `government_repository_initialize` | Открыть или создать government repository из встроенного DSL preset |
| `repository_describe` | Получить entity semantics, relations, file rules и полное содержимое templates |
| `repository_list` | Получить рабочие repositories для явного выбора `repository_path` |
| `repository_create` | Создать локальный Git repository из DSL declaration bundle |
| `repository_open` | Открыть и полностью проверить локальный architecture repository |
| `repository_validate` | Получить детальный validation report без изменения repository |
| `repository_status` | Получить структурированный локальный Git status |
| `repository_diff` | Получить working-tree, staged или revision diff |
| `repository_history` | Получить ограниченную локальную commit history |
| `repository_commit` | Валидировать и закоммитить только DSL-controlled paths |
| `repository_branches` | Получить список локальных веток |
| `branch_create` | Создать локальную ветку без автоматического switch |
| `branch_switch` | Переключиться на валидную локальную ветку из clean state |
| `repository_remotes` | Получить remotes с очищенными URL |
| `remote_configure` | Добавить или явно заменить remote без сетевого запроса |
| `repository_clone` | Явно клонировать remote и создать target только после validation |
| `repository_fetch` | Явно получить refs без изменения index и working tree |
| `repository_pull` | Выполнить только валидированный fast-forward из clean state |
| `repository_publish` | Валидировать и явно отправить текущий `HEAD` без force push |
| `entity_create` | Создать entity из объявленного template |
| `entity_list` | Получить список экземпляров указанного DSL entity |
| `entity_read` | Прочитать один экземпляр по repository-relative path |
| `entity_read_related` | Прочитать связанные файлы по DSL и front matter исходной entity |
| `entity_search` | Найти текст во всех или в указанном типе entity |
| `entity_update` | Локально заменить entity с validation и rollback |
| `entity_delete` | Локально удалить entity с validation и rollback |

Все операции над существующим repository принимают `repository_path`; `repository_create`
и `repository_clone` вместо него принимают новый `target_path`. Repository и Entity tools,
которым требуется декларация, также принимают необязательный `declaration_path` с явно
документированным значением по умолчанию `architecture.yaml`. Git inspection отделён от
DSL validation и остаётся доступен для диагностики невалидного working tree. Ответ имеет
единый envelope:

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

### Сценарий AI-агента

1. Вызвать `repository_describe`; отсутствующий government repository будет создан из
   встроенных `architecture.yaml` и templates без commit или remote.
2. Использовать возвращённые `description`, `relations`, `path_rule`, `filename_rule`,
   `format` и `template_content` как источник правил классификации исходного текста.
3. Вызвать `repository_list`, выбрать только валидный repository с
   `model_matches_government=true` и явно передавать его `repository_path` во все entity tools.
4. Для каждого результата классификации вызвать `entity_create`, затем `entity_update` с
   полным UTF-8 содержимым по шаблону.
5. Отдельно проверить изменения и при необходимости явно выполнить commit/publish.

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

DSL `relations` содержит только имена допустимых связанных entity types. Ссылки на экземпляры
хранятся исключительно во front matter конкретного файла:

```yaml
relations:
  - entity: category
    files:
      - C-0001.md
```

`entity_read_related` проверяет направление связи по DSL и filename по правилу целевой
entity. Найденный файл возвращается вместе с содержимым. Для корректной ссылки на
отсутствующий файл возвращаются `relation_valid=true`, `found=false`, `status=missing` и,
когда path selector точный, ожидаемый `expected_path`. Отсутствие target не делает repository
невалидным. При нескольких подходящих файлах возвращается `status=ambiguous` и
`candidate_paths`; неявный выбор не выполняется.

### Local Git operations

`repository_commit` сначала выполняет полную repository validation, затем включает в
commit только изменённые declaration, templates и файлы, однозначно принадлежащие DSL
entities. Посторонние staged-файлы не попадают в commit и остаются в index. Push не
выполняется.

`branch_switch` разрешён только при полностью чистых index и working tree. Remote branch
guessing, stash, reset и автоматическое разрешение конфликтов не используются. Если target
branch не проходит validation, MCP возвращается на исходную ветку и сообщает ошибку.

`remote_configure` изменяет только локальный `.git/config`. Замена существующего remote
требует явного `replace=true`. HTTP(S) URL со встроенными credentials, query или fragment
отклоняются; `repository_remotes` удаляет credential-bearing части из возвращаемых URL.

### Remote synchronization

Remote-операции никогда не запускаются другими tools неявно и не запрашивают credentials
интерактивно. `repository_clone` клонирует во временный каталог рядом с `target_path`,
отключает рекурсивное получение submodules, выполняет полную DSL/repository validation и
только после успеха перемещает результат в target. Невалидный clone не оставляет частично
созданный repository по целевому пути.

`repository_fetch` требует явное имя настроенного remote и только обновляет remote-tracking
refs. Операция не выполняет merge, rebase, switch, stash или reset и не меняет index и
working tree. Получение tags и prune отключены по умолчанию и включаются отдельными
параметрами.

`repository_publish` требует clean index и working tree, повторно валидирует repository и
публикует текущий `HEAD` в явно указанные remote и branch. Операция не настраивает upstream,
не отправляет tags, не использует force push и сообщает о non-fast-forward как об ошибке.
HTTP(S) URL со встроенными credentials, query или fragment запрещены также для clone;
секреты следует передавать средствами окружения и Git credential helper вне MCP-ответов.

`repository_pull` доступен только для clean working tree и fast-forward history. Fetched tree
валидируется до изменения текущей ветки; divergence, invalid tree и конфликты отклоняются без
implicit stash, reset, rebase или автоматического разрешения конфликтов.

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

Тесты создают временные локальные Git repositories. Remote sync проверяется через локальные
bare repositories и `file://` transport, поэтому Forgejo и доступ к сети не требуются.

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
