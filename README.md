# AIOS — трек 2

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
- Набор 700 прогонов и checkpoint описаны в `../dataset-700/README.md`.
- Результат расчёта: расписание, отклик симулятора, разложение ЧДД и `RunArtifact` для UI.

История исследований и устаревшие handoff-документы сохранены в теге
`docs-before-minimal-2026-08-23`; рабочей инструкцией они не являются.
