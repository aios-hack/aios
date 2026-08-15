# Конвенции фронтенда (ui/web)

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

## Структура
- `src/theme/` — токены и тема; `src/i18n/` — словари и контекст языка.
- `src/api/types.ts` — типы данных (WellPoint, WellsFile).
- `src/views/<View>/` — виды; первый вид: `FieldMap` (2D-карта скважин,
  оси — индексы сетки I/J, J вниз; переключатель пласта Все | Пласт 1 | Пласт 2).

## Запуск
Из корня `aios`:

```
.venv\Scripts\python -m ui.webdata   # генерирует ui/web/public/data/wells.json из дека
cd ui/web
npm install --silent
npm run dev       # дев-сервер
npm run test      # vitest run
npm run build     # tsc + vite build
```

`public/data/` в git не кладётся (см. `ui/web/.gitignore`).
