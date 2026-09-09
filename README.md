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

Первая команда, которую стоит выполнить после установки, — проверка окружения:

```bash
.venv/bin/python -m backend.presentation.cli.selfcheck
```

Она печатает, что нашлось на этой машине: каталог данных организаторов, дек `Model_Z_sch.inc`,
эталонный расчётчик `CHDD_PYTHON`, нормативы, собранный фронт, доступность Docker и наличие
`numpy` с `torch`. По её выводу сразу видно, какие из команд ниже запустятся.

> **Windows.** Вывод русскоязычный, а консоль по умолчанию в cp1252 — команды падают с
> `UnicodeEncodeError` до того, как что-то напечатают. Ставьте `PYTHONIOENCODING=utf-8` перед
> вызовом. Интерпретатор здесь — `.venv/Scripts/python.exe`, не `.venv/bin/python`.

Для интерфейса:

```bash
cd frontend
npm install
npm run build
```

Docker-сборка и состав сервисов описаны в `Dockerfile` и `docker-compose.yml`.

## Что работает из коробки, а что требует внешних артефактов

Ни веса, ни датасеты, ни выгрузки прогонов, ни данные организаторов в git не хранятся. Поэтому
свежий клон **неполон по замыслу**, и команды делятся на три группы. Проверить состояние —
`ls data/` и `python -m backend.presentation.cli.selfcheck`.

### Работает сразу после `pip install -e '.[dev]'`

| Команда | Что даёт |
|---|---|
| `pytest -q` | весь набор тестов; те, что требуют данных организаторов и Docker, помечаются skip, а не падают |
| `python -m backend.presentation.cli.selfcheck` | состояние окружения |
| `python -m backend.presentation.cli.selfcheck --submission <каталог>` | сверка готового пакета сдачи с заявленными хешами |
| `python -m backend.presentation.cli.web` | веб-интерфейс на готовой витрине |
| `python -m backend.presentation.cli.jarvis` | сервис Джарвиса (без ключа — демо-режим на фикстурах) |

Витрина `frontend/public/data/` собрана заранее и лежит в git — интерфейс и Джарвис работают
без единого прогона OPM.

### Требует данных организаторов (`docs/models/`)

Каталог указывается переменной `AIOS_DOCS_ROOT`; без неё автопоиск смотрит в `../docs` и
`../docs-src` рядом с репозиторием.

| Команда | Что даёт |
|---|---|
| `python -m backend.presentation.cli.npv` | расчёт ЧДД по методике и сверка с эталонным расчётчиком |
| `python -m backend.presentation.cli.emit` | эмит `wells_schedule.inc` из дека |
| `run verify --run-id <id>` | верификация сохранённого расписания настоящим OPM (нужен ещё Docker) |
| `run submit --run-id <id>` | сборка пакета сдачи из верифицированного прогона |
| `scripts/cold_repeat.sh --run-id <id>` | холодный повтор из чистого клона |

### Требует ещё и production-весов суррогата

| Команда | Что нужно дополнительно |
|---|---|
| `run search --run-id <id>` | веса, отклик базового прогона (по умолчанию data/base_case/response.json) и матрица λ (data/lambda-window-2007/lambda.json) |
| `run compare --run-id <id>` | веса: по ним строится оценщик отбора для проекции базы |
| `python -m backend.presentation.cli.surrogate_check` | веса |

Веса разрешаются `backend/application/optimization/runtime_artifacts.py`: по умолчанию
берётся указатель data/surrogate-production.json либо каталог `data/model-production/`;
пути переопределяются переменными `AIOS_SURROGATE_MANIFEST`, `AIOS_SURROGATE_BUNDLE`,
`AIOS_CHECKPOINT_PATH`. Состав и хеши зафиксированного пакета —
в [RELEASE_SURROGATE_20260906.md](RELEASE_SURROGATE_20260906.md).

> Пути в этом разделе намеренно написаны без обратных кавычек: этих файлов на машине
> разработки нет, а тест `tests/architecture/test_markdown_links.py` требует, чтобы
> каждый путь в кавычках существовал на диске.

### Состояние машины разработки на 09.09

Проверено командой `ls data/`:

- в `data/` лежит **только `base_run/`**;
- **нет** отклика базового прогона (data/base_case/response.json) — значит, `run search`
  и `run compare` здесь не запускаются;
- **нет** каталога data/lambda-window-2007/ — значит, артефакта lambda.json на диске нет;
  числа λ в документах измерены раньше и приведены по витрине;
- **нет** production-весов: ни указателя data/surrogate-production.json, ни каталога
  data/model-production/, ни data/releases/;
- `numpy` и `torch` не установлены (ставятся отдельно: `pip install -e '.[ml]'` или
  `pip install -r requirements-ml.txt`);
- данные организаторов **есть** — в `../docs`;
- фронт собран, `frontend/dist/` на месте.

Отсюда прямое следствие: **собранного пакета сдачи на этой машине нет**, и `out/runs/` пуст.
Механизм пакета есть и покрыт тестами, но заявленного числа без весов и `base_case` не получить.

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

Ещё две команды рядом:

```bash
.venv/bin/python -m backend.presentation.cli.run compare --run-id <id>   # comparison.json: база против кандидата
bash scripts/cold_repeat.sh --run-id <id>                                 # холодный повтор из чистого клона
```

Пошаговая инструкция со всеми аргументами и разбором отказов —
в [SUBMISSION.md](SUBMISSION.md). Одностраничная карточка ответов — в [ANSWERS.md](ANSWERS.md).
Подробности и границы применимости — в [FAQ.md](FAQ.md) §10.

## Переменные окружения

Ключевые для запуска расчёта:

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `AIOS_DOCS_ROOT` | автопоиск `../docs`, `../docs-src` | каталог данных организаторов |
| `AIOS_PROJECT_ROOT` | каталог с `pyproject.toml` | корень репозитория |
| `AIOS_DATA_ROOT` | `data/` | входы OPM, кэш и артефакты |
| `AIOS_OUT_DIR` | `out/` | результаты; `run --runs-root` по умолчанию `<AIOS_OUT_DIR>/runs` |
| `AIOS_CONSTRAINTS_PATH` | `config/competition-constraints.json` | файл кейса |
| `AIOS_LAMBDA_PATH` | data/lambda-window-2007/lambda.json | матрица связности λ |
| `AIOS_OOD_THRESHOLD` | `0.0` | порог отсечения по области применимости |
| `AIOS_OPM_BUDGET_JOURNAL` | `<AIOS_OUT_DIR>/opm-budget.jsonl` | журнал прогонов Flow |
| `AIOS_RUN_INITIATOR` | определяется по среде | кто запустил: `cli`, `ui`, `test` |
| `AIOS_SURROGATE_MANIFEST` | data/surrogate-production.json | указатель на production-веса |
| `AIOS_SURROGATE_BUNDLE` | — | каталог весов вместо указателя |
| `AIOS_HOST` / `AIOS_PORT` | `0.0.0.0` / `8000` | адрес веб-интерфейса |
| `AIOS_UI_DATA` | витрина в репозитории | каталог JSON-витрины |

Переменные Джарвиса — в его разделе ниже.

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

Что из этого есть на конкретной машине — см. раздел
[«Что работает из коробки»](#что-работает-из-коробки-а-что-требует-внешних-артефактов) выше.
Датасет из 700 прогонов и пакет production-весов ставятся отдельно; состав и хеши перечислены
в [RELEASE_SURROGATE_20260906.md](RELEASE_SURROGATE_20260906.md).

## Документы

| Документ | Что в нём | Статус |
|---|---|---|
| [SUBMISSION.md](SUBMISSION.md) | пакет сдачи: состав, сборка, проверка, что делать при расхождении | живой |
| [ANSWERS.md](ANSWERS.md) | одностраничная карточка ответов жюри со ссылками на код | живой |
| [SURROGATE_DEFENSE.md](SURROGATE_DEFENSE.md) | устройство суррогата, метрики, область применимости, инструкция запуска | **живой**, источник истины по модели |
| [RELEASE_SURROGATE_20260906.md](RELEASE_SURROGATE_20260906.md) | состав релиза, версии и хеши зафиксированных весов, результаты прогонов тестов | живой |
| [FAQ.md](FAQ.md) | ответы на технические вопросы защиты с путями к коду | живой |
| [ARCHITECTURE.md](ARCHITECTURE.md) | слои `backend/`, границы и правила зависимостей | живой |
| [JARVIS.md](JARVIS.md) | замысел и контракт визуального ассистента | живой |
| [UNSEEN_CASE_2017.md](UNSEEN_CASE_2017.md) | прогон на закрытом кейсе | живой |
| [SURROGATE_HANDOFF.md](SURROGATE_HANDOFF.md) | журнал первого обучения 20.08: замеры генерации датасета, разбор упавших запусков, базовая линия CRM | **исторический**, текущее состояние модели описывает `SURROGATE_DEFENSE.md` |

История исследований и устаревшие handoff-документы сохранены в теге
`docs-before-minimal-2026-08-23`; рабочей инструкцией они не являются.

### Веса и сохранённые расчёты

Для локального поиска и экрана расчёта установите опубликованный пакет:

```bash
python3 scripts/install_surrogate_runtime.py
```

Состав, зависимости и запуск: [инструкция](artifacts/surrogate-20260906/README.md).
