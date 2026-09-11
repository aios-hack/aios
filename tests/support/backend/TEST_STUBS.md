# A-07: тестовые заглушки из боевых пакетов — состояние и передача C

Волна 1, агент A, 11.09.2026. Список для C-01/C-02.

## Уже перенесено в волне 1 (боевой код чист)

| Было | Стало | Строк | Кто использует |
|---|---|---|---|
| `backend/presentation/ui_export/fixtures.py` | `tests/support/backend/showcase_fixtures.py` | 299 | 11 тестов витрины и связности |

Шим старого пути **удалён**, а не оставлен: модуль не импортировался ни из одного боевого
модуля — только из тестов, поэтому реэкспорт был бы фикцией. Импорты в 11 тестах переписаны
инструментом по AST на `tests.support.backend.showcase_fixtures`.

## Остаётся в боевом коде осознанно

| Модуль | Строк | Почему остаётся |
|---|---|---|
| `backend/contexts/assistant/application/recording_replay.py` (бывший `jarvis/fixtures.py`) | 114 | Это проигрыватель записей за командой CLI `jarvis --record`, а не фикстура (§6 плана). Боевой код. |
| `backend/contexts/assistant/infrastructure/recordings.py` | 315 | Содержимое записей. В волне 3 (A-16) становится JSON-ресурсами `infrastructure/recordings/*.json`, но и тогда остаётся боевым ресурсом, а не тестовой опорой. |
| `backend/contexts/assistant/infrastructure/llm/fake_chat.py` | 58 | `FakeChatClient` нужен `recording_replay`, то есть боевой команде CLI. Перенос в `tests/support` оборвал бы `jarvis --record`. Кандидат на переезд только вместе с A-16, когда записи станут данными. |

## Что нужно от C

- **C-01**: перенести `tests/support/backend/showcase_fixtures.py` в итоговую раскладку `tests/support/backend/`
  (уже там) и добавить `tests/support/backend/__init__.py` в пакет тестовых опор (уже создан).
- **C-02**: утилиты корневого `conftest.py` (195 строк, ни одной фикстуры) — в `tests/support/backend/`;
  `import conftest` из тестов убрать. A этот файл не трогал: он общий, владеет координатор.
- Ручные списки `SLOW_FILES`/`SLOW_DIRECTORIES` в корневом `conftest.py` сверяют **полный
  относительный путь**. В волне 1 каталоги тестов не переезжали (переносился только боевой код),
  поэтому все 641 deselected остаются deselected и число зелёных не меняется. Но при C-01, когда
  тесты поедут в `tests/backend/**`, эти списки сломаются молча — оба заменяются декораторами
  в C-03, как и записано в плане.

## Проверка

`tests/architecture/backend/test_no_test_code_in_production.py` следит, чтобы новые заглушки
в боевых пакетах не появлялись: список разрешённых исключений — ровно три модуля выше.
