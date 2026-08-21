# Схема JSON-бандла `RunArtifact`

Файл на диске, который читает интерфейс. Пишет `ui/artifact_io.dump_bundle`, читает `ui/artifact_io.load_bundle`. Интерфейс ничего не вычисляет — всё берёт отсюда (contracts/README.md §9). Имена полей — ровно как в `contracts/`, включая `lambda_` (с подчёркиванием) и `canonical_schedule_hash`.

## Кодирование

| Что | Как |
|---|---|
| Файл | JSON, UTF-8, `ensure_ascii=False`, `sort_keys=True` |
| Даты | строка `YYYY-MM-DD` |
| Enum | по имени: `"PROD"`, `"SET_LRAT"`, `"RATE_TARGET"`, `"R1"` |
| Числовые ключи словарей (год → лимит, `control_step` → строка NPV) | в JSON строки, при чтении обратно `int` |
| Отсутствующее значение | `null` — только у `final_npv` и `control_events[].value`; `NaN` запрещён (§1.5) |
| Кортежи / последовательности | JSON-массивы |

## Две шкалы времени (§1.2) — оси и их длины

| Шкала | Ось | Кто на ней живёт | Откуда длина |
|---|---|---|---|
| Дек | `deck_date_index`, 0…N−1 | `state_at_date` | из массива: число различных `deck_date_index` |
| Управление | `control_step`, 0…K−1 | `interval_response`, `schedule.control_events`, `trace`, `npv_table.by_month` | из массива: число различных `control_step`; K = `schedule.meta.n_intervals` = `n_control_dates − 1` |

Длины осей и число скважин схема не фиксирует числами: они читаются из самого бандла (`schedule.meta.wells`, `schedule.meta.n_control_dates`, длины массивов). Конкретные размеры боевого дека — свойство данных, не схемы.

## Корень — `RunArtifact`

| Поле | JSON-тип | Смысл |
|---|---|---|
| `config_hash` | строка, 64 hex | хеш конфига прогона (§1.6) |
| `schedule` | объект | расписание, **оба слоя** — см. ниже |
| `state_at_date` | массив объектов | мгновенные величины, ось дека |
| `interval_response` | массив объектов | помесячные объёмы, ось управления |
| `npv_table` | объект | три разложения ЧДД |
| `trace` | массив объектов | записи сработавших правил |
| `groups` | объект | нарезка фонда на участки |
| `lambda_` | объект | оконная матрица влияния с окном применимости |
| `constraints` | объект | условия кейса |
| `converged` | булево | сошёлся ли прогон |
| `self_consistent` | булево | самосогласованность артефакта |
| `final_npv` | объект или `null` | не `null` только у реально сданного варианта (§9) |

## `schedule` — оба слоя событий

| Поле | JSON-тип | Смысл |
|---|---|---|
| `meta` | объект | см. ниже |
| `initial_state` | объект: скважина → `WellState` | состояние на `t0` |
| `fixed_deck_events` | массив | слой 1: неуправляемые операторы дека |
| `control_events` | массив | слой 2: управляющие решения |

`meta`: `model` (строка), `t0` (дата), `n_control_dates` (целое), `n_intervals` (целое, = `n_control_dates − 1`), `wells` (массив строк, лексикографический порядок — каноническая ось скважин для всего бандла), `history_prefix_hash` / `fixed_events_hash` / `control_events_hash` (строки, три части `canonical_schedule_hash` §1.6), `provenance` (строка; `"synthetic-fixture"` — синтетика для проверки формы).

`WellState`: `availability` (`NOT_COMMISSIONED`/`AVAILABLE`), `role` (`NONE`/`PROD`/`INJ`), `operating_status` (`OPEN`/`SHUT`), `setpoint` (м³/сут). При `NOT_COMMISSIONED` — строго `NONE`/`SHUT`/`0.0`.

`fixed_deck_events[]`: `control_step` (целое), `well` (строка), `operator` (строка, `"COMPDAT"` и т.п.), `raw_args` (массив строк).

`control_events[]`: `control_step` (целое, 0…`n_intervals − 1`), `well` (строка), `kind` (`SET_LRAT`/`SET_RATE`/`OPEN`/`SHUT`/`CONVERT_INJ`), `value` (м³/сут или `null` — только у `SET_LRAT`/`SET_RATE` не `null`).

## `state_at_date[]` — ось дека

| Поле | Единица (§1.4) |
|---|---|
| `deck_date_index` | целое, индекс даты дека |
| `well` | строка |
| `liquid_rate` | м³/сут (WLPR, факт) |
| `oil_rate` | т/сут (WOMR) |
| `injection_rate` | м³/сут (WWIR, факт) |
| `thp` | бар (WTHP) |
| `bhp` | бар (WBHP) |
| `well_efficiency` | доля (WEFF) |
| `active_control_mode` | `RATE_TARGET`/`BHP_LIMITED`/`SHUT`/`NOT_COMMISSIONED`/`UNKNOWN` |

## `interval_response[]` — ось управления

| Поле | Единица |
|---|---|
| `control_step` | целое, 0…`n_intervals − 1` |
| `well` | строка |
| `oil_mass_delta` | **тонны** |
| `liquid_volume_delta` | м³ |
| `injection_volume_delta` | м³ |

## `npv_table`

| Поле | JSON-тип | Ключ |
|---|---|---|
| `by_year` | объект: строка-год → `LineItems` | год, `int` после чтения |
| `by_month` | объект: строка-`control_step` → `LineItems` | `control_step`, `int` после чтения |
| `by_well` | объект: скважина → `LineItems` | строка |
| `npv_methodology` | число | **рубли**, единственная сдаваемая величина |

`LineItems` — все статьи в рублях, `df` — доля: `revenue`, `deductions`, `opex_oil`, `opex_liquid`, `opex_injection`, `opex_wellstock`, `property_tax`, `event_costs`, `capex_esp`, `ebitda`, `income_tax`, `fcf`, `df`, `discounted_fcf`.

## `trace[]`

`control_step` (целое), `well` (строка), `rule` (`R0`…`R7`), `inputs` (объект имя → число), `decision` (строка).

## `groups`

`groups` (объект: id группы → массив скважин, покрытие всего фонда), `lambda_hash` (строка), `group_hash` (строка).

## `lambda_` — окно применимости

| Поле | JSON-тип |
|---|---|
| `window_start`, `window_end` | даты `YYYY-MM-DD` — область применимости матрицы |
| `producers`, `injectors` | массивы строк — оси матрицы, размер по активному фонду окна |
| `matrix` | массив массивов чисел, `len(producers) × len(injectors)` |
| `lag_months` | целое |
| `amplitude`, `stability`, `condition_number` | числа |
| `rank` | целое |
| `achievability_ok` | объект: нагнетательная → булево |

## `constraints`

`injection_limits` (год → м³/сут), `liquid_limits` (год → м³/сут), `production_floors` (год → т/сут), `watercut_limits` (год → доля 0…1), `well_outages` (массив: `well`, `control_step_from`, `control_step_to`), `infrastructure` (свободные пары). Ключи-годы — строки в JSON, `int` после чтения. Пустой документ — отсутствие ограничений, не отсутствие данных.

## `final_npv` — `FinalNpvArtifact | null`

`null` у всех сценариев «что если». Не `null` — только у прошедшего финальную сдачу: `npv_table` (как выше), `npv_methodology` (рубли, равно `npv_table.npv_methodology`), `source_run_id`, `source_response_hash`, `economics_config_hash`, `methodology_version_hash` (строки).
