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

## Входы и результаты

- Организаторские модели и эталонный расчётчик находятся в `../docs/models/`.
- Набор 700 прогонов и checkpoint описаны в `../dataset-700/README.md`.
- Результат расчёта: расписание, отклик симулятора, разложение ЧДД и `RunArtifact` для UI.

История исследований и устаревшие handoff-документы сохранены в теге
`docs-before-minimal-2026-08-23`; рабочей инструкцией они не являются.
