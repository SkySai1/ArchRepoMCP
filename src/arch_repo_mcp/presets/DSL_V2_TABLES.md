# Таблица пресетов используемых в декларации

| Класс   | Группа / элемент      | Допустимые значения / структура                             | Назначение                                 |
| ------- | --------------------- | ----------------------------------------------------------- | ------------------------------------------ |
| Grammar | root                  | `declaration`, `entities`                                   | Корень декларации                          |
| Grammar | `declaration`         | `kind`, `version`                                           | Самоописание DSL                           |
| Grammar | `entities`            | sequence                                                    | Список сущностей                           |
| Grammar | entity                | `name`, `description`, `relations`, `files`                 | Логическая сущность                        |
| Grammar | `entity.name`         | произвольная строка                                         | Уникальное имя сущности                    |
| Grammar | `entity.description`  | произвольный текст                                          | Семантическое описание назначения сущности |
| Grammar | `entity.relations`    | sequence из `entity.name`                                   | Сущности, логически связанные с данной     |
| Grammar | `files`               | `path`, `filename`, `format`, `template`                    | Правила хранения экземпляров               |
| Grammar | `path`                | `match`, `value`                                            | Правило сопоставления родительского пути   |
| Grammar | `filename`            | `match`, `value`                                            | Правило сопоставления имени файла          |
| Grammar | `template`            | repository-relative path                                    | Путь к файлу-шаблону                       |
| Preset  | `declaration.kind`    | `architecture_repository`                                   | Тип декларации                             |
| Preset  | `declaration.version` | `v2`                                                        | Версия DSL                                 |
| Preset  | `description`         | произвольный текст                                          | Описание семантического назначения entity  |
| Preset  | `match`               | `exact`, `regex`                                            | Способ сопоставления                       |
| Preset  | `format`              | `yaml`, `json`, `markdown`, `markdown_front_matter`, `text` | Формат экземпляра и template               |

# Таблица контрактов определяющих структуру пресетов

| ID  | Элемент            | Контракт                       | Семантика                                                                                                                         |
| --- | ------------------ | ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| C01 | DSL                | Closed grammar                 | Неизвестный structural key запрещён                                                                                               |
| C02 | preset value       | Registered value               | Значение закрытого preset-поля обязано существовать в таблице presets; `description` является явно определённым free-text preset  |
| C03 | arbitrary literals | Explicit exceptions            | Произвольные значения разрешены только для entity name/reference, `description` и файловых путей/шаблонов                         |
| C04 | `declaration`      | Self declaration               | `kind` и `version` обязательны                                                                                                    |
| C05 | `version`          | Semantic boundary              | Версия определяет семантику всей декларации                                                                                       |
| C06 | `entity.name`      | User defined                   | Имя сущности не является preset и задаётся пользователем                                                                          |
| C07 | `entity.name`      | Non-empty                      | Имя сущности не может быть пустым                                                                                                 |
| C08 | `entity.name`      | Unique                         | Имя сущности уникально в пределах декларации                                                                                      |
| C09 | `relations`        | Entity references              | Каждый элемент должен ссылаться на существующий `entity.name`                                                                     |
| C10 | `relations`        | Unique references              | Одна сущность не должна дважды содержать одну и ту же связь                                                                       |
| C11 | `relations`        | Optional                       | Отсутствие `relations` означает отсутствие объявленных связей                                                                     |
| C12 | relation           | Entity-level semantic relation | Связь объявляется между типами сущностей, а не между конкретными экземплярами                                                     |
| C13 | relation           | No instance inference          | Наличие связи не означает, что каждый экземпляр source связан с каждым экземпляром target                                         |
| C14 | relation           | Traversable                    | MCP может использовать связь для определения типов сущностей, которые следует изучить совместно                                   |
| C15 | relation           | Type-level declaration         | DSL содержит только имена допустимых связанных entity types и не содержит имён файлов                                             |
| C16 | relation           | No cardinality                 | `one/many` отсутствуют; фактическая множественность определяется содержимым экземпляров                                           |
| C17 | entity instance    | One file = one instance        | Каждый matched-файл является одним экземпляром сущности                                                                           |
| C18 | `path`             | Parent path selector           | Сопоставляется repository-relative parent path                                                                                    |
| C19 | `filename`         | Basename selector              | Сопоставляется только basename                                                                                                    |
| C20 | `match=exact`      | Exact comparison               | Требуется полное совпадение                                                                                                       |
| C21 | `match=regex`      | Full regex match               | Regex применяется к полному значению                                                                                              |
| C22 | file matching      | AND                            | Для принадлежности entity должны совпасть path и filename                                                                         |
| C23 | `format`           | Shared format                  | Target и template используют один формат                                                                                          |
| C24 | target file        | Parseable                      | Файл должен быть корректен согласно `format`                                                                                      |
| C25 | template           | Concrete file                  | Template указывает на один конкретный файл                                                                                        |
| C26 | template           | Same format                    | Template обязан соответствовать `files.format`                                                                                    |
| C27 | template           | Arbitrary content              | Template не содержит обязательной DSL-грамматики или placeholders                                                                 |
| C28 | template           | Creation scaffold              | Template используется как стартовый файл при создании экземпляра                                                                  |
| C29 | target vs template | Independent after creation     | После создания экземпляр может свободно изменяться                                                                                |
| C30 | file editing       | Allowed                        | Отдельных permissions/write-policy нет                                                                                            |
| C31 | matching overlap   | Forbidden                      | Один файл не должен одновременно принадлежать двум сущностям                                                                      |
| C32 | template isolation | Not instance                   | Template не должен одновременно материализоваться как экземпляр                                                                   |
| C33 | create             | Valid target                   | Новый файл должен соответствовать path + filename правилам сущности                                                               |
| C34 | path safety        | Repository confined            | Абсолютные пути, `..` и выход за repository запрещены                                                                             |
| C35 | DSL                | No implicit logic              | Нет variables, computed values, inferred entities или автоматически создаваемых relations                                         |
| C36 | `description`      | Required                       | Каждая entity обязана содержать `description`                                                                                     |
| C37 | `description`      | Arbitrary text                 | Значение является произвольным текстом и не ограничивается реестром фиксированных значений                                        |
| C38 | `description`      | Entity semantics               | Описание определяет смысл и назначение типа сущности для человека и AI-агента; оно не изменяет правила file matching или хранения |
| C39 | instance relation  | Front matter only              | Ссылки на конкретные файлы задаются только в `relations` front matter экземпляра `markdown_front_matter`                          |
| C40 | relation group     | `entity`, `files`              | Каждый элемент `relations` содержит имя одного связанного entity type и массив имён файлов                                        |
| C41 | relation entity    | DSL-governed                   | `relations[].entity` обязан присутствовать в `entity.relations` исходного типа                                                     |
| C42 | relation filename  | Basename only                  | `relations[].files[]` содержит filename без directory path                                                                        |
| C43 | relation filename  | Target selector                | Filename обязан соответствовать `files.filename` связанного entity type                                                           |
| C44 | missing target     | Valid dangling relation        | Отсутствующий файл не делает repository невалидным; чтение связи возвращает `relation_valid=true`, `found=false`, `status=missing` |
| C45 | relation groups    | Optional                       | Отсутствующий `relations` означает отсутствие instance-level ссылок                                                               |
| C46 | empty group        | Allowed                        | Пустой `files` означает, что связь с типом разрешена DSL, но ссылки на экземпляры не установлены                                  |
| C47 | duplicate entries  | Forbidden                      | Entity groups и filenames внутри одной group должны быть уникальны                                                                |

# Безопасность файловых путей

Точные пути каталогов и пути шаблонов являются repository-relative POSIX paths.
Компоненты `.git` (без учёта регистра), `..`, обратные слеши, NUL и двоеточия
(в том числе Windows drive prefixes) недопустимы. MCP не создаёт содержимое в Git metadata.
Regex-селекторы описывают сопоставление и не используются как имена создаваемых каталогов.

# Ссылки между экземплярами

DSL-декларация определяет только допустимые направления связей:

```yaml
- name: fact
  relations:
    - requirement
    - category
```

Имена конкретных файлов в DSL не указываются. Они находятся во front matter экземпляра:

```yaml
relations:
  - entity: requirement
    files:
      - R-0001.md
  - entity: category
    files:
      - C-0001.md
      - C-0002.md
```

Наличие файла проверяется во время чтения связей, а не при repository validation. Поэтому
корректно типизированная ссылка может временно указывать на отсутствующий файл. Если path
selector связанного entity допускает несколько файлов с одинаковым basename, инструмент
чтения не выбирает один неявно и возвращает состояние `ambiguous` со списком кандидатов.
