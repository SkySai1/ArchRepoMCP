# ArchRepoMCP — план реализации

Обозначения:

- `[x]` — реализовано и проверено;
- `[ ] [MUST]` — жизненно необходимо для минимального безопасного MCP;
- `[ ] [OPTIONAL]` — полезное расширение, не блокирующее минимальное ядро.

## Уже реализовано

- [x] DSL v2 parser, closed grammar и validation нормативных примеров.
- [x] Создание, открытие и полная локальная validation architecture repository.
- [x] Локальные операции Entity Service: list, read, search, create, update и delete.
- [x] Local Git: status, diff, history, commit, branches и remotes.
- [x] Явные `repository_clone`, `repository_fetch`, безопасный fast-forward
  `repository_pull` и `repository_publish`.
- [x] Защита publish от dirty working tree и non-fast-forward.
- [x] Запрет embedded HTTP credentials в remote URL.
- [x] Базовые unit, repository, entity, Git, remote sync и MCP tests.

## Текущий обязательный этап

- [x] Удалить отдельный управляющий repository: каждый architecture repository содержит
  собственные DSL-декларацию и templates и является атомарным.
- [x] Добавить встроенный default DSL bundle из `specs/dsl/architecture.yaml` для создания
  нового самодостаточного repository без внешней декларации.
- [x] Настроить workspace через stdio-аргумент, process environment или `.env`; все MCP repository paths разрешаются внутри настроенного workspace.
- [x] Добавить MCP-инструмент `repository_describe`, позволяющий AI-агенту получить полное
  описание модели явно выбранного repository из его локальных DSL и templates.
- [x] Для каждой DSL entity возвращать:
  name;
  description;
  семантическое назначение entity;
  relations;
  правила path;
  правила filename;
  format;
  путь к template;
  содержимое template.
- [x] Обеспечить возможность AI-агенту перед обработкой исходных документов получить модель
  выбранного repository через MCP и использовать её как единственный источник правил
  классификации и создания entities.
- [x] Добавить `repository_list`, перечисляющий все атомарные repositories без сравнения их
  моделей и без неявного выбора; entity-tools требуют выбранный `repository_path`.
- [x] Добавить contract tests для нового MCP-инструмента и проверку соответствия возвращаемого описания фактической DSL-декларации и templates.
- [x] Добавить integration test сценария: исходное техническое задание → анализ AI-агентом → классификация информации по entity types → создание файлов через entity_create / entity_update согласно DSL и templates.
- [x] Добавить instance-level связи в front matter (`relations[].entity` + `files[]`) и MCP-инструмент `entity_read_related`; DSL при этом содержит только допустимые entity types, а отсутствующий target возвращается как валидная связь со статусом `missing`.

## Следующий обязательный этап

- [ ] [MUST] Разделять transport failures на `AUTHENTICATION_ERROR`,
  `PERMISSION_DENIED`, `NETWORK_ERROR`, `TLS_ERROR`, `TIMEOUT`, `NOT_FOUND` и
  `PROVIDER_CAPABILITY_GAP` без возврата чувствительного stderr.
- [x] Реализовать явный `repository_pull` только для безопасной fast-forward
  интеграции с validation fetched tree до изменения working tree.
- [x] Отклонять pull при dirty state, divergence и конфликтующем history без
  implicit stash, reset, rebase или conflict resolution.
- [x] Добавить contract tests полного набора MCP tools: имена, аргументы,
  обязательность, defaults и публичные result models.
- [x] Проверить отсутствие implicit fetch, pull, merge и push в локальных и
  однонаправленных remote-операциях.
- [ ] [MUST] Добавить детерминированные tests для authentication, permissions, TLS,
  timeout, unavailable remote, missing repository и provider capability failures.
- [ ] [MUST] Изолировать Forgejo integration tests от offline test suite.
- [ ] [MUST] Проверять совместимость обязательных Forgejo endpoints со Swagger
  целевого test instance.
- [ ] [MUST] Загружать Forgejo-настройки только из environment или локального env-файла,
  не возвращая и не логируя token.
- [ ] [MUST] Нормализовать `specs/contracts/forgejo`: удалить direct remote file API
  из минимального provider scope и согласовать runtime configuration с `AGENTS.md`.
- [ ] [MUST] Реализовать минимальный Forgejo provider: connection/version,
  authentication, repository existence/metadata, optional repository creation и
  remote URL resolution.
- [ ] [MUST] Добавить contract traceability: contract → implementation → test для
  каждой публичной MCP/provider функции.
- [ ] [MUST] Запустить Forgejo integration suite против выделенной test organization.

## Опциональные возможности после стабилизации ядра

- [ ] [OPTIONAL] Semantic diff и определение изменённых DSL entities.
- [ ] [OPTIONAL] Сравнение architecture revisions и история конкретной entity.
- [ ] [OPTIONAL] GitLab, GitHub, Gitea и другие provider adapters.
- [ ] [OPTIONAL] Pull/Merge Request, review и approval workflow.
- [ ] [OPTIONAL] CI validation, Actions и protected branch policies.
- [ ] [OPTIONAL] TLS certificate pinning поверх системной проверки сертификатов.
