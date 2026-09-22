# ArchRepoMCP

MCP-сервер для локального управления архитектурными Git-репозиториями. Структура
сущностей задаётся декларацией DSL, а удалённые Git-сервисы рассматриваются только как
явный контур синхронизации.

Текущий MVP позволяет AI-агенту получить список локальных repositories, явно выбрать один из
них и прочитать его собственные DSL-декларацию и шаблоны перед работой с сущностями. Каждый
repository атомарен и не зависит от отдельного управляющего repository. Доступ к remote
выполняется только через отдельные явные операции; остальные возможности полностью работают
offline.

## Реализовано

- строгий parser и validator DSL `architecture_repository/v2`;
- обязательное семантическое `description` для каждого entity type;
- закрытая грамматика, проверка presets, relations, regex и duplicate YAML keys;
- обнаружение корня локального Git repository без сетевых операций;
- repository confinement и запрет symbolic-link обходов;
- проверка templates, конфликтов file matching и форматов файлов;
- безопасное создание repository из декларации и её template bundle;
- атомарный repository, содержащий собственные `architecture.yaml` и templates;
- справка по DSL, таблицы пресетов и связей, полные примеры до создания repository;
- описание модели выбранного repository через `repository_describe` и явный выбор через
  `repository_list`;
- постоянный JSON-индекс в `~/.config/arch-repo-mcp/` и выбор repository по UUID;
- индексация существующего repository по пути с проверкой содержимого через `repository_index`;
- удаление записи из индекса без удаления файлов и повторная индексация после validation;
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
   ├── Repository Registry ── UUID / list / index / reindex / unindex
   ├── Repository Catalog ─── creation guide / describe
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
      "command": "arch-repo-mcp"
    }
  }
}
```

Конкретный формат файла конфигурации зависит от MCP host. Команда должна запускаться в
окружении, где установлен пакет `arch-repo-mcp`.

### Индекс и пути репозиториев

Сервер создаёт `~/.config/arch-repo-mcp/repositories.json` при запуске или первом обращении
к индексу. В нём хранятся UUID и канонические абсолютные пути:

```json
{
  "version": 1,
  "repositories": [
    {
      "repository_id": "9ac62b0d-1dbd-4e78-b02f-b9c34a1d2e70",
      "repository_path": "/Users/you/ArchitectureRepositories/payments"
    }
  ]
}
```

Репозитории могут находиться в разных каталогах. Конечный абсолютный `target_path` передаёт
агент при создании или клонировании. Родительская директория должна существовать, target —
отсутствовать. Относительные пути и `~` в аргументе не принимаются: агент передаёт полный путь.
Во всех дальнейших операциях агент передаёт `repository_id` из ответа или `repository_list`.

При обновлении удалите `ARCH_REPO_MCP_WORKSPACE`, `ARCH_REPO_MCP_ENV_FILE` и старую переменную
`ARCH_REPO_MCP_GOVERNMENT_REPOSITORY` из настроек MCP host. Путь repository больше не читается
из переменных окружения или `.env`. Существующие файлы не перемещаются; каждый прежний repository
нужно явно зарегистрировать через `repository_index(repository_path="/absolute/path")`.
Вызовы старого API с `repository_path` вместо UUID необходимо обновить.

## Запуск в Goose на macOS

Goose подключает локальные MCP-серверы как STDIO extensions. Сначала установите нужный клиент
Goose через Homebrew (CLI, Desktop или оба):

```bash
brew install block-goose-cli
brew install --cask block-goose
```

Настройте LLM provider при первом запуске Goose или позднее через `goose configure` в CLI либо
`Settings` → `Models` в Desktop. Затем подготовьте ArchRepoMCP и родительскую директорию для репозиториев. Во всех
следующих примерах замените `/Users/you/...` своими абсолютными путями:

```bash
cd /Users/you/src/ArchRepoMCP
python3 -m venv .venv
./.venv/bin/python -m pip install -e .
mkdir -p /Users/you/ArchitectureRepositories
```

Используйте абсолютный путь к `.venv/bin/arch-repo-mcp`: Goose Desktop может не наследовать
`PATH` интерактивной shell. Путь к repository в настройках extension не требуется.

### Goose CLI

Для постоянного подключения выполните:

```bash
goose configure
```

В интерактивном меню выберите `Add Extension` → `Command-Line Extension` и укажите:

- name: `ArchRepoMCP`;
- command: `/Users/you/src/ArchRepoMCP/.venv/bin/arch-repo-mcp`;
- timeout: `300`.

После добавления запустите обычную сессию:

```bash
goose session
```

Для одноразовой сессии без сохранения extension в конфигурации Goose используйте:

```bash
goose session --with-extension \
  "/Users/you/src/ArchRepoMCP/.venv/bin/arch-repo-mcp"
```

### Goose Desktop (GUI)

1. Откройте боковую панель Goose Desktop и перейдите в `Extensions`.
2. Нажмите `Add custom extension`.
3. Выберите type `Standard IO`, задайте ID `arch-repo-mcp`, name `ArchRepoMCP` и command
   `/Users/you/src/ArchRepoMCP/.venv/bin/arch-repo-mcp`.
4. Установите timeout `300`. Путь repository будет передан самим агентом в MCP-вызове.
5. Нажмите `Add`, убедитесь, что extension включён, и начните новую сессию.

Для проверки подключения попросите Goose: `Вызови repository_create без аргументов и покажи
доступные пресеты и связи`. Затем попросите составить DSL и templates под задачу и создать
repository по полному пути `/Users/you/ArchitectureRepositories/example`. Агент передаст тексты
в MCP, получит UUID и вызовет `repository_describe(repository_id="полученный UUID")`.
Конфигурация CLI и Desktop общая и хранится Goose в `~/.config/goose/config.yaml`.

Актуальные названия пунктов интерфейса и варианты установки приведены в официальной
[инструкции по установке Goose](https://goose-docs.ai/docs/getting-started/installation/) и
[документации по extensions](https://goose-docs.ai/docs/getting-started/using-extensions/).

## MCP tools

| Tool | Назначение |
| --- | --- |
| `repository_describe` | Получить DSL, entity semantics и содержимое templates выбранного repository |
| `repository_list` | Получить индексированные repositories для явного выбора UUID |
| `repository_index` | Проверить содержимое repository по абсолютному пути и присвоить UUID |
| `repository_reindex` | Совместимый аналог `repository_index` для повторной индексации |
| `repository_unindex` | Удалить UUID из индекса, сохранив физический repository |
| `repository_create` | Получить справку или создать repository из явно переданных DSL и templates |
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

Все операции над индексированным repository принимают обязательный `repository_id` (UUID).
`repository_index` и `repository_reindex` принимают абсолютный `repository_path` для регистрации существующего
каталога; `repository_create` и `repository_clone` принимают новый абсолютный `target_path`. Repository и Entity tools,
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

1. Для нового repository вызвать `repository_create()` без аргументов. Ответ `phase=guide`
   содержит нормативные таблицы DSL, таблицы пресетов и направлений связей, инструкции,
   полные примеры `minimal` и `default` с содержимым каждого шаблона.
2. Составить `architecture.yaml` и templates под запрос пользователя. Пресеты служат примерами:
   имена сущностей, семантические описания, пути и связи задаёт агент согласно DSL.
3. Передать комплект через тот же `repository_create` с `target_path`, `architecture_yaml`,
   `templates`. Читать или создавать исходные файлы на диске сервера агенту не требуется.
4. Получить `repository_id`. Для существующих repositories взять UUID через `repository_list`,
   а для ещё не индексированного каталога — через `repository_index`.
5. Вызвать `repository_describe(repository_id=...)`. Использовать именно его `description`,
   `relations`, `path_rule`, `filename_rule`, `format`, `template_content` при классификации текста.
6. Передавать этот UUID в `entity_create`, затем в `entity_update` с полным UTF-8 содержимым.
7. Проверить изменения. Commit и publish выполняются отдельными явными командами.

### Создание repository

Первый MCP-вызов: `repository_create` с аргументами `{}`. Второй вызов передаёт **содержимое**
файлов. Например, для минимальной модели записей:

```json
{
  "target_path": "/Users/you/ArchitectureRepositories/notes",
  "architecture_yaml": "declaration:\n  kind: architecture_repository\n  version: v2\nentities:\n  - name: note\n    description: Архитектурная заметка\n    files:\n      path: {match: exact, value: notes}\n      filename: {match: regex, value: '^N-[0-9]+\\.md$'}\n      format: markdown\n      template: templates/note.md\n",
  "templates": {
    "templates/note.md": "# Заметка\n\nОписание решения.\n"
  },
  "initial_branch": "main"
}
```

Пример ответа:

```json
{
  "ok": true,
  "result": {
    "phase": "created",
    "repository_id": "9ac62b0d-1dbd-4e78-b02f-b9c34a1d2e70",
    "repository_root": "/Users/you/ArchitectureRepositories/notes",
    "declaration_path": "architecture.yaml",
    "declaration": {"kind": "architecture_repository", "version": "v2"},
    "entities": ["note"]
  }
}
```

Все три аргумента `target_path`, `architecture_yaml`, `templates` передаются вместе. Неполный
комплект вызывает `VALIDATION_ERROR`; неявного выбора default preset нет. `templates` должен
содержать ровно объявленные шаблоны. При исключении типа из примера обновляются и DSL relations,
и ссылки в шаблонах. Содержимое и направления связей проверяются до установки результата в target.

MCP создаёт `architecture.yaml`, templates и каталоги точных `path`-селекторов. Для regex
невозможно однозначно вывести конкретное имя каталога: такой путь позже указывает агент в
`entity_create`. Невалидный bundle не оставляет target или запись индекса. Существующий target
не заменяется. Начальная ветка — `main`, если явно не передан другой `initial_branch`.
Commit и remote автоматически не создаются. Каждый repository хранит собственную модель.

### Индексация существующего repository

Для добавления **уже существующего каталога** вызовите MCP-инструмент `repository_index`
напрямую, даже если `repository_list` пуст. UUID для этого вызова не нужен. Аргументы:

```json
{"repository_path": "/Users/you/ArchitectureRepositories/notes"}
```

Передайте абсолютный путь каталога на файловой системе MCP-сервера. Каталог должен быть
корнем Git repository. MCP сначала проверяет точное совпадение Git root с указанным путём,
затем читает `/Users/you/ArchitectureRepositories/notes/architecture.yaml`, templates и
сущности внутри **этого же каталога**. Текущий рабочий каталог сервера не влияет на выбор.
При указании вложенного каталога MCP вернёт ошибку до чтения содержимого родительского repository.

Собственный `.git` нужен только в конечном каталоге: как каталог metadata или файл Git worktree.
Наличие либо отсутствие `.git` у родителей не мешает индексации самостоятельного repository.
Корень проверяется по идентичности каталога на файловой системе. Русские буквы, пробелы и
эквивалентные на данной файловой системе Unicode-представления пути поддерживаются; повторная
индексация того же каталога сохраняет UUID. Переменные расположения Git из окружения запуска
сервера не перенаправляют операции на другой repository.

Для нестандартного имени декларации передайте `declaration_path` относительно `repository_path`,
например `"declaration_path": "model/custom.yaml"`. Пути templates и entities остаются
относительными к корню repository, а не к каталогу декларации.

После полной проверки Git root, DSL, templates и содержимого сущностей он вернёт:

```json
{
  "ok": true,
  "result": {
    "repository_id": "9ac62b0d-1dbd-4e78-b02f-b9c34a1d2e70",
    "repository_path": "/Users/you/ArchitectureRepositories/notes"
  }
}
```

UUID хранится в пользовательском индексе и используется в дальнейших вызовах MCP.
Возьмите `result.repository_id` и передайте его в `repository_describe`, затем в инструменты
работы с сущностями. `repository_open` открывает уже индексированный repository по UUID.
Создавать или клонировать repository для добавления существующего каталога не требуется.
Файлы repository не изменяются. При ошибках содержимого запись не добавляется; для уже
индексированного пути проверка выполняется заново, а UUID при успехе сохраняется.

### Удаление из индекса и повторная индексация

`repository_unindex(repository_id=...)` удаляет только запись, сохраняя все файлы и Git history.
Это работает и для отсутствующего или невалидного каталога. Старый UUID после удаления даёт
`NOT_FOUND`.

`repository_index(repository_path="/absolute/path")` проверяет, что путь — точный Git root,
а DSL, templates и сущности валидны. Для уже индексированного пути сохраняет UUID, иначе
создаёт новый. Нестандартный путь декларации можно передать через `declaration_path`; его
нужно затем явно передавать в соответствующие операции, поскольку индекс хранит только UUID
и путь repository. При переносе каталога зарегистрируйте новый путь и явно удалите старую запись.
`repository_reindex` сохранён как совместимый аналог `repository_index`.

`repository_list` возвращает сохранённые записи, включая устаревшие; каталогов не сканирует.
UUID сохраняется между запусками сервера. Записи индекса обновляются атомарно под блокировкой;
повреждённый JSON вызывает ошибку без перезаписи. Если после создания/клонирования не удалось
записать индекс, каталог сохраняется, а ошибка содержит его путь для `repository_reindex`.
Git inspection доступен по UUID даже при ошибке DSL для диагностики.

Нормативные аргументы и результаты: `specs/contracts/mcp/MCP_TOOLS.yaml`.
Правила жизненного цикла: `specs/contracts/mcp/REPOSITORY_LIFECYCLE.md`.

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
только после успеха перемещает результат в target и индексирует его с UUID. Невалидный clone не оставляет частично
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
    description: Проверенный архитектурный факт
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

Тесты создают временные локальные Git repositories и изолируют пользовательский JSON-индекс.
Проверяются двухэтапное создание, пользовательские DSL, UUID, unindex/reindex, повреждённый
индекс, параллельные записи, опасные пути, ошибки шаблонов и безопасное восстановление. Remote sync проверяется через локальные
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
