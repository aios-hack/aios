# AIOS — трек 2


Документ для защиты: [суррогат, обучение, технологии, метрики и запуск](SURROGATE_DEFENSE.md). Статус исправлений: [релиз 06.09.2026](RELEASE_SURROGATE_20260906.md).
Мультиагентная система управления фондом скважин Model_Z. Она строит расписание
`wells_schedule.inc`, проверяет его на ограничениях и считает ЧДД по эталонной методике
организаторов.

## Быстрый старт

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q
```

Для интерфейса:

```bash
cd frontend
npm install
npm run build
```

Docker-сборка и состав сервисов описаны в `Dockerfile` и `docker-compose.yml`.

## Расчёт и сдача

```bash
.venv/bin/python -m backend.presentation.cli.run search  --run-id <id>
.venv/bin/python -m backend.presentation.cli.run verify  --run-id <id>
.venv/bin/python -m backend.presentation.cli.run submit  --run-id <id>
.venv/bin/python -m backend.presentation.cli.selfcheck --submission out/runs/<id>/submission
```

Статусы прогона идут строго по цепочке `searched` → `verified` (либо `rejected`, если проверка
показала `sound = false`) → `ready_to_submit`. Последний статус ставит **только** `submit`, и
только после того, как собран пакет: `wells_schedule.inc` плюс `claimed_npv.json` с заявленным ЧДД
и хешами расписания, отклика, дека, ограничений и методики. Пакет не соберётся, если прогон не
верифицирован или если в экономике нет ЧДД от OPM: прогноз суррогата в заявляемую величину не
подставляется.

`selfcheck --submission` пересчитывает хеши лежащего в каталоге файла и сверяет их с заявленными —
проверка того же рода, что сделает организатор.

Подробности и границы применимости — в [FAQ.md](FAQ.md) §10.

## Структура

| Каталог | Назначение |
|---|---|
| `backend/core` | общие типы, хеширование и границы слоёв |
| `backend/domain` | расписания, экономика, правила управления, устойчивость и связность |
| `backend/ml` | суррогатная модель |
| `backend/infrastructure` | OPM Flow, файловые и внешние адаптеры |
| `backend/application` | сценарии поиска и верификации |
| `backend/presentation` | CLI и экспорт данных для интерфейса |
| `frontend` | React-интерфейс |
| `tests` | архитектурные и сквозные проверки |

Подробности — в [ARCHITECTURE.md](ARCHITECTURE.md). Точная форма данных — в
[backend/core/contracts/README.md](backend/core/contracts/README.md); исполняемым источником
истины остаются типы Python рядом с ним.

## Джарвис

Визуальный ассистент консоли: вопрос на естественном языке — сцена из карточек с настоящими
числами из витрины. Отдельный процесс и отдельный сервис compose, порт 8010, HTTP и SSE на
stdlib. Замысел и контракт — в [JARVIS.md](JARVIS.md).

Локально:

```bash
export OPENROUTER_API_KEY=sk-or-...
python -m backend.presentation.cli.jarvis --port 8010
curl -s http://localhost:8010/api/jarvis/health
```

Дев-фронт на 5199 ходит на `/api/jarvis/*` через прокси Vite; этот origin разрешён в CORS
сервиса напрямую, поэтому запрос с `http://localhost:5199` проходит и без прокси. Флаг
`--check` печатает health и выходит, не поднимая сервер.

В compose:

```bash
OPENROUTER_API_KEY=sk-or-... docker compose up jarvis web
```

Сервис `web` проксирует `/api/jarvis/*` на `jarvis:8010`, поэтому фронт в контейнере ходит на
тот же origin. Адрес апстрима меняется через `AIOS_JARVIS_UPSTREAM`.

Переменные окружения:

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `JARVIS_PROVIDER` | `openrouter` | `openrouter` или `anthropic` |
| `OPENROUTER_API_KEY` | — | ключ OpenRouter, основной путь |
| `ANTHROPIC_API_KEY` | — | ключ Anthropic, запасной путь |
| `JARVIS_MODEL` | `anthropic/claude-sonnet-4.5` | любая модель с tool calling и стримом |
| `JARVIS_MAX_TOKENS` | `1200` | потолок ответа модели |
| `AIOS_UI_DATA` | витрина в репозитории | каталог JSON-витрины |
| `AIOS_JARVIS_KNOWLEDGE` | `frontend/public/jarvis/knowledge` | база знаний |
| `AIOS_JARVIS_HOST` / `AIOS_JARVIS_PORT` | `0.0.0.0` / `8010` | адрес сервиса |

Без ключа сервис всё равно поднимается: `/api/jarvis/health` и `/api/jarvis/ask` отвечают
`503` с телом `{"ok": false, "error": "no-api-key", ...}`, где в `message` сказано, какую
переменную задать. Консоль при этом работает, а Джарвис переходит в демо-режим на фикстурах
`frontend/public/jarvis/fixtures/*.jsonl` с честной плашкой — сцены те же, подписи записанные.

## Входы и результаты

- Организаторские модели и эталонный расчётчик находятся в `../docs/models/`.
- Датасет прогонов лежит в `../data/dataset-main/`: `manifest.jsonl` — строка на прогон,
  `runs/` — рабочие каталоги, `decks/` — деки для симулятора, `cache/` — кэш ответов,
  `plan.json` — план генерации набора.
- Результат расчёта: расписание, отклик симулятора, разложение ЧДД и `RunArtifact` для UI.

### Что из этого есть на конкретной машине

Веса, датасеты и выгрузки прогонов в git не хранятся и адресуются хешами, поэтому свежий клон почти
всегда неполон. Это нормально, но об этом надо знать заранее:

- каталог `data/` внутри репозитория содержит только то, что положил владелец машины. Проверять —
  командой `ls data/`;
- пакет production-весов `data/releases/surrogate-20260906/` и датасет из 700 прогонов ставятся
  отдельно; состав и хеши перечислены в [RELEASE_SURROGATE_20260906.md](RELEASE_SURROGATE_20260906.md);
- витрина в `frontend/public/data/` собрана заранее и лежит в git — интерфейс и Джарвис работают
  без прогонов OPM.

## Документы

| Документ | Что в нём | Статус |
|---|---|---|
| [SURROGATE_DEFENSE.md](SURROGATE_DEFENSE.md) | устройство суррогата, метрики, область применимости, инструкция запуска | **живой**, источник истины по модели |
| [RELEASE_SURROGATE_20260906.md](RELEASE_SURROGATE_20260906.md) | состав релиза, версии и хеши зафиксированных весов, результаты прогонов тестов | живой |
| [FAQ.md](FAQ.md) | ответы на технические вопросы защиты с путями к коду | живой |
| [ARCHITECTURE.md](ARCHITECTURE.md) | слои `backend/`, границы и правила зависимостей | живой |
| [JARVIS.md](JARVIS.md) | замысел и контракт визуального ассистента | живой |
| [UNSEEN_CASE_2017.md](UNSEEN_CASE_2017.md) | прогон на закрытом кейсе | живой |
| [SURROGATE_HANDOFF.md](SURROGATE_HANDOFF.md) | журнал первого обучения 20.08: замеры генерации датасета, разбор упавших запусков, базовая линия CRM | **исторический**, текущее состояние модели описывает `SURROGATE_DEFENSE.md` |

История исследований и устаревшие handoff-документы сохранены в теге
`docs-before-minimal-2026-08-23`; рабочей инструкцией они не являются.
