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
- [x] Явные `repository_clone`, `repository_fetch` и `repository_publish`.
- [x] Защита publish от dirty working tree и non-fast-forward.
- [x] Запрет embedded HTTP credentials в remote URL.
- [x] Базовые unit, repository, entity, Git, remote sync и MCP tests.

## Текущий обязательный этап

- [ ] [MUST] Создать MCP tool формирующий goverment репозиторий с описанием dsl структы из dsl/architecture.yaml
- [ ] [MUST] Настроить работу с переменной окружения хранения корневой директории, передаваемой от агента в том числе, внутри которой существуют все репозитории. 
- [ ] [MUST] Разделять transport failures на `AUTHENTICATION_ERROR`,
  `PERMISSION_DENIED`, `NETWORK_ERROR`, `TLS_ERROR`, `TIMEOUT`, `NOT_FOUND` и
  `PROVIDER_CAPABILITY_GAP` без возврата чувствительного stderr.
- [ ] [MUST] Реализовать явный `repository_pull` только для безопасной fast-forward
  интеграции с validation fetched tree до изменения working tree.
- [ ] [MUST] Отклонять pull при dirty state, divergence и конфликтующем history без
  implicit stash, reset, rebase или conflict resolution.
- [ ] [MUST] Добавить contract tests полного набора MCP tools: имена, аргументы,
  обязательность, defaults и публичные result models.
- [ ] [MUST] Проверить отсутствие implicit fetch, pull, merge и push в локальных и
  однонаправленных remote-операциях.
- [ ] [MUST] Добавить детерминированные tests для authentication, permissions, TLS,
  timeout, unavailable remote, missing repository и provider capability failures.
- [ ] [MUST] Изолировать Forgejo integration tests от offline test suite.
- [ ] [MUST] Проверять совместимость обязательных Forgejo endpoints со Swagger
  целевого test instance.
- [ ] [MUST] Загружать Forgejo-настройки только из environment или локального env-файла,
  не возвращая и не логируя token.

## Следующий обязательный этап

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
