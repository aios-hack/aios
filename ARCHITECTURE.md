# Архитектура AIOS

Один принцип: код, описывающий пласт, разработку и экономику, не знает, как устроены
Docker, OPM, браузер и LLM-клиент. Всё остальное — следствия.

Документ описывает дерево после рефакторинга (DDD-контексты на бэкенде, слайсы на фронте,
единый `tests/`). Спецификация целевой картины — `REFACTOR_PLAN.md` §2–§3, правила для
агентов — §11.

## 1. Верхний уровень

```text
backend/
  shared/          общее ядро; не знает ни одного контекста
  contexts/        13 ограниченных контекстов, в каждом domain/application/infrastructure
  interfaces/      cli/ и http/ — единственные точки входа снаружи
frontend/src/      слайсы app → pages → features → entities → shared + самодостаточный jarvis
tests/             единый корень: architecture, backend, frontend, golden, support, fixtures
```

Бэкенд-кода вне `backend/` нет. Временные пакеты верхнего уровня и слои
`core/ domain/ ml/ infrastructure/ application/ presentation/` удалены полностью.

## 2. Общее ядро (`backend/shared`)

| Модуль | Что внутри |
|---|---|
| `errors.py` | `AiosError` и всё семейство (§5) |
| `settings.py` | `Settings.from_env()` — единственное место, где читается `os.environ` |
| `paths.py` | `project_root`, `data_root`, `out_root`, `docs_root` — одна реализация на репозиторий |
| `clock.py` | `Clock` (Protocol), `SystemClock`, `FrozenClock` — детерминизм меток времени |
| `hashing.py` | JCS-канонизация, `content_hash`, `canonical_hash(payload)` |
| `json_io.py` | `read_json`, `read_optional_json`, `write_json` (атомарно, `sort_keys`) |
| `i18n/` | `Messages.get(key, lang, **params)`, `ru.json` / `en.json` |
| `types.py` | `Lang`, `WellId`, `ControlStep` и прочие типы-обёртки |
| `numeric.py`, `resources.py` | численные помощники и доступ к упакованным ресурсам |

`shared` не импортирует ни `contexts`, ни `interfaces` — это проверяется деревом импортов
и держится на сегодня без единого нарушения.

## 3. Карта контекстов

Тринадцать контекстов в `backend/contexts/`. Колонка «может зависеть от» — разрешённые
направления; всё, чего в ней нет, — нарушение.

| Контекст | Что владеет | Может зависеть от |
|---|---|---|
| `reservoir` | модель Z: сетка, скважины, PVT, плотности, горизонт, разбор дека, геометрия скважин | `shared` |
| `schedule` | агрегат `Schedule`: события, канон, lossless, emit, replay, динамическая валидация | `shared`, `reservoir` |
| `economics` | ЧДД, нормативы, леджер, декомпозиция, базовый случай, паритет | `shared`, `reservoir`, `schedule` |
| `constraints` | кейсы, ограничения, схема, загрузка и выгрузка | `shared`, `reservoir` |
| `connectivity` | λ, измерение, группы, кампания, DOE | `shared`, `reservoir`, `schedule` |
| `policy` | агенты, правила R0–R7, уровни поля / участка / скважины, память, трасса | `shared`, `reservoir`, `schedule`, `economics`, `constraints`, `connectivity` |
| `robustness` | OOD-батарея, regret, возмущения | `shared`, `schedule`, `constraints` |
| `surrogate` | быстрая модель: сеть, признаки, обучение, инференс, калибровка, физпроверки | `shared`, `reservoir`, `schedule`, `economics` |
| `simulation` | OPM: раннер, preflight, кэш, бюджет, загрузка отклика, дизайн возмущений | `shared`, `reservoir`, `schedule` |
| `optimization` | алгоритм поиска, среда оценки, гейты, верификация, сравнение, чемпион | `shared`, доменные контексты выше, `surrogate`, `simulation` |
| `runs` | жизненный цикл прогона: воркфлоу, манифесты, провенанс, пакет сдачи, веб-прогоны | `shared`, `optimization`, `simulation`, `constraints`, `showcase` |
| `assistant` | Джарвис: сессии, инструменты, знания, индекс документов, сторож, голос, LLM | `shared`, `runs`, `constraints`, `policy`, `connectivity`, `showcase` |
| `showcase` | сборка витрины для фронта (бывший `ui_export`) | `shared`, `reservoir`, `schedule`, `economics`, `connectivity`, `policy`, `runs` |

Внутри контекста — три пакета, и только живые: пакет заводится, когда в нём появляется
первый файл. Каталог с одним пустым `__init__.py` — мусор, а не архитектура. Поэтому у
`policy` и `robustness` нет `infrastructure/`, а у `showcase` — `domain/`.

```text
contexts/<name>/
  __init__.py          публичный API контекста: только то, что импортируется снаружи
  domain/              сущности, объекты-значения, доменные сервисы, порты (Protocol), errors.py
  application/         сценарии использования, DTO, оркестрация портов
  infrastructure/      адаптеры портов: файлы, Docker, HTTP-клиенты, torch
```

## 4. Правила слоёв

Сверху вниз, без стрелок вверх и без циклов:

- `shared` не импортирует ни один контекст и ни один интерфейс.
- `contexts/X/domain` импортирует только `shared` и `contexts/Y/domain` для разрешённых `Y`.
  **Никогда** — `application` или `infrastructure` любого контекста, включая свой.
- `contexts/X/application` импортирует `shared`, свой `domain`, свой `infrastructure`
  только через порты, и чужой контекст `Y` — **только через `contexts/<Y>/__init__.py`**.
- `contexts/X/infrastructure` импортирует `shared`, свой `domain` и порты своего `application`.
- `interfaces` импортирует `shared` и `contexts/*/__init__.py`.
- `os.environ` / `getenv` встречается только в `backend/shared/settings.py`.
- `raise SystemExit` встречается только в `backend/interfaces/cli/runner.py`.
- Импорты внутри функций запрещены, кроме необязательных зависимостей
  (`torch`, `edge_tts`, `openpyxl`, `anthropic`) в `infrastructure`.
- Кириллица в `backend/**/*.py` запрещена, кроме `shared/i18n/*.json` и ресурсов промптов.
- Комментариев и докстрингов нет нигде. Выживают только `# type: ignore`, `# noqa`,
  `# pragma: no cover`. Импорты вверху файла, типы обязательны.

Когда прямой импорт в `domain` создал бы цикл, а тип нужен только для аннотации, —
`if TYPE_CHECKING:` плюс `from __future__ import annotations`. Так сделано в
`backend/contexts/connectivity/domain/measure.py` для `DatasetSample`: во время выполнения
`domain` про `simulation.infrastructure` не знает.

Сторож правил — `tests/architecture/backend/`:
`test_context_boundaries.py` (domain не тянет ни application, ни infrastructure;
приватные символы не ходят между контекстами), `test_no_env_outside_settings.py`, `test_no_test_code_in_production.py`.
Фронтовые инварианты — `tests/architecture/frontend/` (паритет i18n, знаний, notice, токенов).

### Состояние правила

Правило смыкается полностью: ни один модуль `domain` не импортирует `application`
или `infrastructure` во время выполнения. Списки исключений в
`tests/architecture/backend/test_context_boundaries.py` пусты. Аннотации под
`if TYPE_CHECKING:` разрешены и сторожем не считаются — он разбирает импорты
времени выполнения.

## 5. Иерархия ошибок

Корень — `AiosError` в `backend/shared/errors.py`: поля `code`, `message`,
`details: Mapping[str, object]` и `as_dict()`.

```text
AiosError
├── DomainError                 нарушение правила предметной области
│   └── ValidationError         входные данные не проходят проверку
├── NotFoundError               прогон, сценарий, скважина, артефакт отсутствуют
├── ConflictError               состояние не позволяет действие
├── ConfigurationError          окружение, настройки, ключи
├── InfrastructureError         файлы, Docker, подпроцессы, сеть
│   └── ExternalServiceError    OpenRouter, Anthropic, edge-tts
└── UnavailableError            функция сознательно недоступна
```

Каждый контекст объявляет свои подклассы в `<context>/domain/errors.py` с фиксированным `code`
(`schedule.parse`, `economics.normatives`, `runs.not_found`, `assistant.no_api_key`, …).
Такие файлы есть у одиннадцати контекстов: `assistant`, `connectivity`, `constraints`,
`economics`, `optimization`, `reservoir`, `robustness`, `runs`, `schedule`, `simulation`,
`surrogate`.

Подмешивание встроенных типов запрещено: класс ошибки наследуется от `AiosError` и только
от него. `ValueError` остаётся ровно для одного случая — программист передал аргумент
неверного типа; нарушение бизнес-правила всегда `DomainError` или `ValidationError`.

Перевод в ответ — по одному месту на интерфейс, и больше нигде:

| Ошибка | HTTP (`backend/interfaces/http/kit/errors.py`) | Код выхода CLI (`backend/interfaces/cli/runner.py`) |
|---|---|---|
| `ValidationError` | 400 | 2 |
| `NotFoundError` | 404 | 3 |
| `ConflictError` | 409 | 4 |
| `ConfigurationError` | 503 | 5 |
| `UnavailableError` | 503 | 5 |
| `ExternalServiceError` | 502 | 6 |
| `InfrastructureError` | 500 | 6 |
| прочий `AiosError` | 500 | 1 |

Тело HTTP-ответа всегда `{"error": code, "message": message, "details": {...}}`.
Голый `Exception` превращается в 500 с `code="internal"` и записью в лог, без утечки
текста наружу. CLI печатает `error[<code>]: <message>` в stderr.

## 6. Интерфейсы

### CLI

Единая точка входа — `backend/interfaces/cli/main.py`, объявленная в `pyproject.toml`
как консольный скрипт `aios`. `main.py` держит таблицу `COMMANDS: dict[str, str]`
(имя подкоманды → модуль), импортирует модуль лениво и отдаёт его `main` в
`runner.run`, который ловит `AiosError` и превращает в код выхода. Семнадцать подкоманд:

```text
campaign   emit   jarvis   npv   run   selfcheck   showcase   verify-reference   web
surrogate-adapt   surrogate-adapt-audit   surrogate-audit   surrogate-check
surrogate-release   surrogate-screen   surrogate-screen-verify   surrogate-weight-soup
```

Команда — это разбор аргументов, вызов одного сценария использования и печать результата.
Ни загрузчиков, ни бизнес-правил в ней нет. Старая форма `python -m backend.presentation.cli.X`
не поддерживается: шимы сняты, вызовы в `docker/entrypoint.sh`, `docker-compose.yml` и
документации переведены на `aios <подкоманда>`.

### HTTP

```text
interfaces/http/kit/                 JsonResponse, errors.py, sse.py, body.py (лимиты), cors.py
interfaces/http/console/             статика, /api/runs, /api/runs/{id}/comparison, прокси Джарвиса
interfaces/http/assistant/           health, ask, cancel, briefing, sessions*, speak, voices, transcribe
interfaces/http/surrogate_dashboard/ сервер и HTML-шаблон как ресурс
```

В `interfaces/http/assistant/` лежат только маршруты, лимиты тел и CORS; вся логика
ассистента — в контексте `assistant`. Логирование настраивается в
`backend/interfaces/logging_setup.py` — один конфигуратор на процесс.

## 7. Фронт

```text
frontend/src/
  app/         запуск: main.tsx, App.tsx, providers/, router/, hotkeys/, styles/
  pages/       11 экранов, один экран — одна папка: overview, field-projection, field-maps,
               history-matrix, history-wall, history-table, council, rules,
               money-rank, money-comparison, money-constraints
  features/    9 возможностей с состоянием: timeline-player, inspector, command-palette,
               trust-board, scenario-switch, ask-jarvis, header-controls,
               workspace-nav, provenance-banner
  entities/    предметные сущности (types + validate + model + hooks): timeline, wells, npv,
               graph, scenarios, hierarchy, maps, runs, trace, ablation, events
  shared/      lib/, ui/, theme/, i18n/, api/, router/ — ничего не знает о фичах
  jarvis/      самодостаточный слайс: model, transport, cards, scene, screen, sphere,
               voice, markdown, stage, actions, provider
```

Направление зависимостей: `app → pages → features → entities → shared`, без стрелок вверх
и без циклов. `shared` не импортирует никого. `jarvis` импортирует `entities` и `shared`;
обратно в него ходят только `features/ask-jarvis`, `features/workspace-nav` и `app`, и
только через `frontend/src/jarvis/index.ts`.

Слой `widgets` устранён: то, что было виджетом, разошлось по `features` (если у него есть
состояние) и по `shared/ui` (если состояния нет). Каталога `frontend/src/widgets` больше нет.

Файлы фронта ≤ 250 строк, файлы бэкенда ≤ 400 строк. Идентификаторы, aria-строки и
сообщения — через ключи i18n, не литералами.

## 8. Тесты и золотые снимки

Единый корень `tests/`, внутри — по назначению, а не по слою кода:

```text
tests/architecture/   инварианты структуры: границы контекстов, env, слои, ссылки в .md
tests/backend/        contexts/, contracts/, interfaces/, shared/
tests/frontend/       app, design, entities, features, jarvis, knowledge, pages, shared
tests/golden/         снимки поведения до рефакторинга + MANIFEST.json с правилами сверки
tests/support/        помощники и моки для обоих стеков (backend/, frontend/)
tests/fixtures/       входные данные (decks/)
```

Золотые снимки лежат в `tests/golden/backend/` и описаны в `tests/golden/MANIFEST.json`,
где зафиксированы дата снятия, коммит и — главное — правило сверки для каждого файла.

| Файл | Что гарантирует |
|---|---|
| `showcase.json` | sha256 каждого из 1284 JSON витрины; байт-в-байт, **кроме** полей `notice` (они сверяются отдельно как пара ключ + текст) |
| `recordings.json` | sha256 одиннадцати записей Джарвиса; байт-в-байт для `ru` |
| `knowledge.json` | sha256 трёх файлов базы знаний |
| `behaviour.json` | ЧДД, пакет чемпиона, сценарии, сетка, статистика таймлайна; точно, вещественные до 1e-6 |
| `api_surface.json` | публичные классы и функции каждого модуля (226 модулей, 1964 символа); ни один публичный символ не исчезает молча, переименования перечисляются в отчёте волны |
| `errors.json` | имена всех 80 пользовательских классов ошибок; каждое имя выживает либо отображается в задокументированную замену |
| `cli.json` | коды выхода и сообщения показательных вызовов CLI; коды могут меняться с 1 на коды из §5, сообщения становятся английскими |
| `tests.json` | количество тестов по стекам |

Чего снимки **не** гарантируют: это не проверка правильности, а проверка неизменности.
Они ловят регресс рефакторинга — «было одно, стало другое», — но молчат, если поведение
было неверным до снятия. Снимок можно обновлять осознанно: каждое обновление пишется в
`MANIFEST.json` в раздел `refreshed` с датой, списком файлов и причиной. Два таких
обновления уже записаны — после волны 2 и после волны 4 (Z-04a).

## 9. Как добавить новый контекст

1. Решить, чем контекст **владеет** — какими понятиями и правилами. Если ответ звучит как
   «он помогает другому контексту», это не контекст, а слой внутри существующего.
2. Завести `backend/contexts/<name>/` с `__init__.py` и пакетом `domain/`. `application/`
   и `infrastructure/` создаются, когда в них появится первый файл, не раньше.
3. Объявить `<context>/domain/errors.py`: подклассы `DomainError` / `NotFoundError` / … с фиксированными
   `code` вида `<name>.<что произошло>`.
4. Описать вход и выход как порты (`Protocol`) в `domain/`. Реализации — в `infrastructure/`.
5. Публичный API — в `__init__.py` контекста. Наружу видно только то, что там перечислено;
   чужой `application` обязан ходить именно через него.
6. Дописать строку в таблицу §3 — контекст и его разрешённые зависимости.
7. Прогнать `tests/architecture/backend/`.

## 10. Как добавить новый экран

1. `frontend/src/pages/<kebab-case>/` — одна папка на экран.
2. Данные экрана — из `entities/*`; если сущности нет, завести её там, а не в странице.
3. Состояние и взаимодействие — в `features/*`; страница их только собирает.
4. Общие кирпичи — из `shared/ui`; если компонент знает про фичу, ему место в `features`.
5. Все тексты и aria-строки — ключами через `shared/i18n`, в `locales/{ru,en}`.
6. Зарегистрировать маршрут в `app/router/`.
7. Тесты — в `tests/frontend/pages/<kebab-case>/`.

Правило, которое решает большинство споров о том, куда класть файл: **вниз по стрелке
можно, вверх нельзя**. Если компоненту нужно знать о слое выше, он лежит не там.

## 11. Джарвис

Джарвис — визуальный ассистент консоли: вопрос на естественном языке превращается в сцену
карточек, собранную из той же JSON-витрины, которую читает фронт. Это модуль, пересекающий
все слои по правилам выше, а не скрипт, прикрученный к UI.

```text
frontend/src/jarvis/                       браузер: сфера, сцены, карточки
          │  SSE  /api/jarvis/*
backend/interfaces/http/assistant/         маршруты, лимиты тел, CORS
backend/contexts/assistant/application/    оркестратор, инструменты, брифинг, подсказки
backend/contexts/assistant/domain/         сессия, сцена, сторож, порты инструментов
backend/contexts/assistant/infrastructure/ LLM-провайдеры, индекс документов, знания, диск, TTS, STT
```

`assistant/application` получает `ChatClient` снаружи и не импортирует ни `urllib`, ни
`http`, ни `anthropic`. Инструменты читают артефакты через порты и переиспользуют
существующие объяснялку и диагностику, а не копируют их логику.

Сервис поднимается отдельным процессом и отдельным сервисом compose на порту 8010, на
`ThreadingHTTPServer`, с chunked `text/event-stream` и комментарием `: keep-alive` каждые
15 секунд, чтобы ленивые прокси не рвали долгий ответ. Маршруты: `GET /api/jarvis/health`,
`POST /api/jarvis/ask`, `POST /api/jarvis/cancel`. CORS открыт только dev-origin
`http://localhost:5199` и `http://127.0.0.1:5199`. В контейнере сервис `web` проксирует
`/api/jarvis/*` на `jarvis:8010`, поэтому фронт всегда говорит с одним origin.

Запуск: `aios jarvis` локально, `docker compose up jarvis web` в контейнере, команда
`jarvis` в `docker/entrypoint.sh`.

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `JARVIS_PROVIDER` | `openrouter` | `openrouter` или `anthropic` |
| `OPENROUTER_API_KEY` | — | ключ OpenRouter, основной путь |
| `ANTHROPIC_API_KEY` | — | ключ Anthropic, запасной путь |
| `JARVIS_MODEL` | `anthropic/claude-sonnet-4.5` | любая модель с вызовом инструментов и стримингом |
| `JARVIS_MAX_TOKENS` | `1200` | потолок длины ответа |
| `AIOS_UI_DATA` | витрина в репозитории | каталог JSON-витрины |
| `AIOS_JARVIS_KNOWLEDGE` | `frontend/public/jarvis/knowledge` | база знаний |
| `AIOS_JARVIS_HOST` / `AIOS_JARVIS_PORT` | `0.0.0.0` / `8010` | адрес привязки |
| `AIOS_JARVIS_UPSTREAM` | `http://jarvis:8010` | upstream для прокси `web` |

Без ключа сервис всё равно стартует и отвечает `503`
`{"ok": false, "error": "no-api-key"}` с именем переменной, которую надо задать; консоль
продолжает работать, а ассистент откатывается на записанные ответы.

Граница модуля жёсткая, и это проверяемое свойство: оно защищает продукт, если ассистент
не успеет к сроку. Чтобы выключить Джарвиса целиком, достаточно удалить
`frontend/src/jarvis/`, `frontend/public/jarvis/`, `backend/contexts/assistant/`,
`backend/interfaces/http/assistant/` и `backend/interfaces/cli/jarvis.py`, после чего снять
четыре точки вызова: прокси и ветки `is_jarvis_path` в `backend/interfaces/cli/web.py`,
команду `jarvis` в `docker/entrypoint.sh`, сервис `jarvis` в `docker-compose.yml` и точки
монтирования в `frontend/src/app/` и `features/workspace-nav/`.

## 12. Прогон

```bash
aios run search --run-id <id>
aios run verify --run-id <id>
aios run submit --run-id <id>
```

Режим `full` выполняет поиск быстрой моделью, затем реальную проверку OPM, и
останавливается, если первый шаг не прошёл: прогноз никогда не выдаётся за проверенный
результат. Чтобы проверить ранее найденный план, не ища заново, — `aios run verify
--run-id <id>`; читается расписание именно этого прогона.

Каждый прогон изолирован в `out/runs/<run-id>/`:

```text
manifest.json     статус, хеш расписания, предсказанный и проверенный ЧДД
schedule/         каноническое расписание, прошедшее через воркфлоу
prediction/       результат быстрой модели
opm/              рабочий каталог OPM для того же расписания
validation/       корректность, статус OPM, динамические нарушения, тождества
economics/        проверенный ЧДД, когда участок дошёл до экономики
inputs/, ui/      зарезервированные входы и выход для витрины
```

Статусы идут строго по цепочке `searched` → `verified` (либо `rejected`, если проверка
дала `sound = false`) → `ready_to_submit`. Последний ставит **только** `submit` и только
после того, как пакет собран и его круговая проверка сошлась: статус обещает существующий
пакет, а не просто корректный прогон.
