# Таблица пресетов используемых в декларации
| Класс   | Группа / элемент      | Допустимые значения / структура                             | Назначение                               |
| ------- | --------------------- | ----------------------------------------------------------- | ---------------------------------------- |
| Grammar | root                  | `declaration`, `entities`                                   | Корень декларации                        |
| Grammar | `declaration`         | `kind`, `version`                                           | Самоописание DSL                         |
| Grammar | `entities`            | sequence                                                    | Список сущностей                         |
| Grammar | entity                | `name`, `relations`, `files`                                | Логическая сущность                      |
| Grammar | `entity.name`         | произвольная строка                                         | Уникальное имя сущности                  |
| Grammar | `entity.relations`    | sequence из `entity.name`                                   | Сущности, логически связанные с данной   |
| Grammar | `files`               | `path`, `filename`, `format`, `template`                    | Правила хранения экземпляров             |
| Grammar | `path`                | `match`, `value`                                            | Правило сопоставления родительского пути |
| Grammar | `filename`            | `match`, `value`                                            | Правило сопоставления имени файла        |
| Grammar | `template`            | repository-relative path                                    | Путь к файлу-шаблону                     |
| Preset  | `declaration.kind`    | `architecture_repository`                                   | Тип декларации                           |
| Preset  | `declaration.version` | `v2`                                                        | Версия DSL                               |
| Preset  | `match`               | `exact`, `regex`                                            | Способ сопоставления                     |
| Preset  | `format`              | `yaml`, `json`, `markdown`, `markdown_front_matter`, `text` | Формат экземпляра и template             |

# Таблица контрактов определяющих структуру пресетов
| ID  | Элемент            | Контракт                       | Семантика                                                                                       |
| --- | ------------------ | ------------------------------ | ----------------------------------------------------------------------------------------------- |
| C01 | DSL                | Closed grammar                 | Неизвестный structural key запрещён                                                             |
| C02 | preset value       | Registered value               | Значение preset-поля обязано существовать в таблице presets                                     |
| C03 | arbitrary literals | Explicit exceptions            | Произвольные значения разрешены только для entity name/reference и файловых путей/шаблонов      |
| C04 | `declaration`      | Self declaration               | `kind` и `version` обязательны                                                                  |
| C05 | `version`          | Semantic boundary              | Версия определяет семантику всей декларации                                                     |
| C06 | `entity.name`      | User defined                   | Имя сущности не является preset и задаётся пользователем                                        |
| C07 | `entity.name`      | Non-empty                      | Имя сущности не может быть пустым                                                               |
| C08 | `entity.name`      | Unique                         | Имя сущности уникально в пределах декларации                                                    |
| C09 | `relations`        | Entity references              | Каждый элемент должен ссылаться на существующий `entity.name`                                   |
| C10 | `relations`        | Unique references              | Одна сущность не должна дважды содержать одну и ту же связь                                     |
| C11 | `relations`        | Optional                       | Отсутствие `relations` означает отсутствие объявленных связей                                   |
| C12 | relation           | Entity-level semantic relation | Связь объявляется между типами сущностей, а не между конкретными экземплярами                   |
| C13 | relation           | No instance inference          | Наличие связи не означает, что каждый экземпляр source связан с каждым экземпляром target       |
| C14 | relation           | Traversable                    | MCP может использовать связь для определения типов сущностей, которые следует изучить совместно |
| C15 | relation           | No content schema              | DSL не определяет, где внутри файла хранится ссылка на конкретный экземпляр                     |
| C16 | relation           | No cardinality                 | `one/many` отсутствуют; фактическая множественность определяется содержимым экземпляров         |
| C17 | entity instance    | One file = one instance        | Каждый matched-файл является одним экземпляром сущности                                         |
| C18 | `path`             | Parent path selector           | Сопоставляется repository-relative parent path                                                  |
| C19 | `filename`         | Basename selector              | Сопоставляется только basename                                                                  |
| C20 | `match=exact`      | Exact comparison               | Требуется полное совпадение                                                                     |
| C21 | `match=regex`      | Full regex match               | Regex применяется к полному значению                                                            |
| C22 | file matching      | AND                            | Для принадлежности entity должны совпасть path и filename                                       |
| C23 | `format`           | Shared format                  | Target и template используют один формат                                                        |
| C24 | target file        | Parseable                      | Файл должен быть корректен согласно `format`                                                    |
| C25 | template           | Concrete file                  | Template указывает на один конкретный файл                                                      |
| C26 | template           | Same format                    | Template обязан соответствовать `files.format`                                                  |
| C27 | template           | Arbitrary content              | Template не содержит обязательной DSL-грамматики или placeholders                               |
| C28 | template           | Creation scaffold              | Template используется как стартовый файл при создании экземпляра                                |
| C29 | target vs template | Independent after creation     | После создания экземпляр может свободно изменяться                                              |
| C30 | file editing       | Allowed                        | Отдельных permissions/write-policy нет                                                          |
| C31 | matching overlap   | Forbidden                      | Один файл не должен одновременно принадлежать двум сущностям                                    |
| C32 | template isolation | Not instance                   | Template не должен одновременно материализоваться как экземпляр                                 |
| C33 | create             | Valid target                   | Новый файл должен соответствовать path + filename правилам сущности                             |
| C34 | path safety        | Repository confined            | Абсолютные пути, `..` и выход за repository запрещены                                           |
| C35 | DSL                | No implicit logic              | Нет variables, computed values, inferred entities или автоматически создаваемых relations       |
