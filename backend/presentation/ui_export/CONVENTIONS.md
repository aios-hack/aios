# Конвенции фронтенда (frontend/)

## Стек
- TypeScript + Vite + React (без сторонних i18n/state-библиотек).
- Тесты: vitest + @testing-library/react + jsdom.

## Жёсткие правила
- Любой файл ≤ 250 строк.
- Без комментариев в коде; только named exports.
- Шрифты, цвета, отступы, размеры — только через дизайн-токены:
  CSS-переменные в `src/theme/tokens.css` + ts-модуль `src/theme/tokens.ts`.
  В компонентах и стилях никаких магических значений (hex, px и т.п.) —
  тест `src/theme/tokens.test.ts` проверяет отсутствие hex-цветов вне tokens.css.
- Два языка: русский (по умолчанию) и английский. ВСЕ строки интерфейса —
  в словарях по неймспейсам: `src/i18n/<locale>/<namespace>.json` (`ru/` и `en/`,
  одинаковый набор неймспейсов и ключей, есть тест `src/i18n/i18n.test.ts`).
  Новый вид = новый файл неймспейса `src/i18n/<locale>/<view>.json`
  (один файл на вид на локаль); общие строки (шапка, вкладки, темы, язык) —
  в `common.json`. Внутри файла ключи без префикса неймспейса (`table.well`),
  словарь собирается в `src/i18n/dictionaries.ts`, вызовы остаются полными:
  `t('steps.table.well')`. Доступ через `useT()` из `src/i18n/I18nContext.tsx`,
  переключатель языка в шапке.
- Светлая и тёмная темы: CSS-переменные, `data-theme` на `<html>`,
  переключатель в шапке, обе темы полноценные (`src/theme/ThemeContext.tsx`).
- Интерфейс НИЧЕГО не вычисляет (ни экономику, ни физику) —
  только отображает готовые данные из JSON (`public/data/`, генерируется Python-стороной).
- **Синтетика обязана быть помечена.** Файлы видов (`graph.json`, `npv.json`,
  `timeline.json`, `scenarios.json`) несут в `meta` поля `provenance` и
  `synthetic` (см. `ui/demo.py`): у демо-набора `synthetic: true`, у `wells.json`
  из настоящего дека — `provenance: "deck"`, `synthetic: false`. Плашку
  `SyntheticBanner` интерфейс показывает по ним; `trace.json` и бандлы —
  отображения без обёртки `meta`, флага в них нет. Флаг читается из данных
  (`state/ProvenanceContext.tsx`), а не зашивается в компонент: набор из
  настоящего прогона плашку не покажет. Выдавать синтетическое число за
  результат расчёта запрещено.
- **Компонент — это папка.** Каждый компонент в `src/ui/` и каждый вид в
  `src/views/` живёт в одноимённом каталоге: `Slider/Slider.tsx`,
  `Slider/Slider.css`, `Slider/index.ts` с реэкспортом (`export { Slider } from './Slider'`).
  Импортируется по имени папки (`from '../../ui/Slider'`), поэтому внутреннюю
  структуру можно менять, не трогая места вызова. Стили компонента лежат рядом
  с ним и подключаются его же файлом, а не глобально.
- Состояния загрузки / ошибки / пустоты — только через общий компонент
  `src/ui/ViewStatus/` (`kind="loading" | "error" | "empty"`), у ошибки
  `role="alert"`, у загрузки `aria-busy`. Свои `<p class="...-status">` в видах
  не заводить: состояния во всех видах выглядят одинаково.
- Фокус: глобальное правило `:focus-visible` в `styles.css` через токены
  `--color-focus`, `--focus-ring-width`, `--focus-ring-offset`. Не отключать
  `outline` без замены. Вкладки — `role="tablist"` с навигацией стрелками
  и `tabIndex` только у активной.
- Анимации: длительности и кривые из токенов (`--duration-fast`,
  `--duration-drawer`, `--ease-out-drawer`), у каждой — ветка
  `@media (prefers-reduced-motion: reduce)`.

## Структура
- `src/theme/` — токены и тема; `src/i18n/` — словари и контекст языка.
- `src/api/types.ts` — типы данных (WellPoint, WellsFile).
- `src/data/` — загрузка JSON и состояние ресурса; `src/state/` — контексты
  сценария, таймлайна и provenance; `src/ui/` — переиспользуемые компоненты.
- `src/views/<View>/` — виды, сейчас их шесть: `LambdaGraph` (граф влияния,
  главный), `FieldMap` (2D-карта скважин, оси — индексы сетки I/J, J вниз;
  переключатель пласта Все | Пласт 1 | Пласт 2), `Timeline` (шаги),
  `WellCard` (карточка скважины с Trace), `NpvRank` (вклад в ЧДД),
  `Scenarios` (библиотека артефактов).

## Запуск
Из корня `aios`:

```
.venv/bin/python -m backend.presentation.ui_export.webdata   # только wells.json из дека
.venv/bin/python -m backend.presentation.ui_export.demo      # весь демонстрационный набор
cd frontend
npm ci
npm run dev       # дев-сервер
npm run test      # vitest run
npm run build     # tsc + vite build
```

Node.js — ровно `22.11.0`, как в `Dockerfile`. На Node 24 и новее компонентные
тесты падают целиком: у рантайма появился свой глобальный `localStorage`,
равный `undefined` без `--localstorage-file`, и он перекрывает хранилище jsdom.

`public/data/` в git не кладётся (см. `frontend/.gitignore`) — набор генерируется
Python-стороной (`ui/demo.py` пишет в `frontend/public/data/`). Каталог `src/data/`
— это слой загрузки данных на TypeScript, он в git есть и с `public/data/` не связан.
