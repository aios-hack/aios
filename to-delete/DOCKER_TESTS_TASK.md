# Задача: сделать запуск тестов внутри Docker честным и зелёным

## Цель

Команды проверки образа должны завершаться без падений как с аргументами
pytest, так и без них:

```bash
docker run --rm \
  -v /путь/к/docs:/data/docs:ro \
  aios:latest tests

docker run --rm \
  -v /путь/к/docs:/data/docs:ro \
  aios:latest tests -q
```

Если внутри образа нет Docker-клиента или доступа к Docker daemon, тесты,
которым нужен настоящий OPM Flow, должны честно переходить в `skip`. Остальные
тесты из тех же файлов должны продолжать выполняться.

## Подтверждённая проблема

На текущем образе полный запуск тестов внутри контейнера падает в четырёх
местах:

1. `tests/architecture/test_runtime_paths.py::test_runtime_defaults_are_under_project_not_source_package`;
2. `backend/infrastructure/opm/tests/test_runner.py::test_timeout_is_failed_and_does_not_leak_a_container`;
3. `backend/infrastructure/opm/tests/test_submission.py::test_dynamic_gate_rejects_the_real_baseline_over_well_71`;
4. `backend/infrastructure/opm/tests/test_submission.py::test_all_six_identities_are_computed_even_when_the_tract_fails`.

Дополнительно
`backend/infrastructure/opm/tests/test_submission.py::test_strict_mode_lists_every_reason_at_once`
проходит без Docker по неправильной причине. Вместо настоящего отклика он
получает ошибку запуска Docker, но текущая проверка принимает её за ожидаемый
результат, потому что в сообщении всё равно встречается `validate_dynamic`.

Расчёты, ЧДД, λ, эмит расписания и compose-поток эта проблема не затрагивает.
Ломается путь проверки тестов внутри образа.

## Причины

### 1. Тест значений по умолчанию зависит от переменных контейнера

Dockerfile устанавливает:

```text
AIOS_OUT_DIR=/out
```

При этом тест ожидает значение по умолчанию `<project-root>/out`. Он не очищает
переменную среды перед проверкой, поэтому внутри образа получает `/out` и
падает.

Та же скрытая проблема есть у `AIOS_DATA_ROOT`: сейчас Dockerfile её не задаёт,
но тест сломается после её появления.

### 2. Аргументы pytest обходят защиту entrypoint

В `docker/entrypoint.sh` любой аргумент после `tests` немедленно запускает:

```bash
python -m pytest "$@"
```

Из-за этого документированная команда `tests -q` не доходит до обработки
отсутствующего Docker.

### 3. Поиск файлов для `--ignore` всегда пуст

Entrypoint ищет в тестах строку:

```text
shutil.which("docker")
```

Такой строки в OPM-тестах больше нет. Проверка доступности Docker переехала в
`conftest.docker_unavailable_reason()`. Поэтому entrypoint печатает сообщение
об исключённых тестах, но не исключает ни одного файла.

### 4. Часть тестов не имеет точного гейта окружения

Timeout-тест всегда требует настоящий Docker. Submission-тестам нужен либо уже
существующий настоящий кеш отклика, либо доступный Docker для его создания.
Сейчас эти требования не выражены точными pytest-маркерами или фикстурами.

## Что нужно сделать

### Блок 1. Изолировать тест runtime-путей

В тесте значений по умолчанию через `monkeypatch.delenv(..., raising=False)`
очистить:

- `AIOS_PROJECT_ROOT`;
- `AIOS_DATA_ROOT`;
- `AIOS_OUT_DIR`.

Сохранить отдельный тест для `AIOS_OUT_DIR` и добавить такой же тест для
`AIOS_DATA_ROOT`.

### Блок 2. Удалить определение Docker-тестов через grep

Не заменять один текстовый шаблон grep другим. Поиск исходников по имени
функции хрупкий и выбрасывает целые файлы вместе с тестами, которым Docker не
нужен.

Нужно:

1. удалить сбор файлов `--ignore` из `cmd_tests`;
2. всегда запускать pytest единым путём с переданными аргументами;
3. решение о `skip` оставить самим тестам через точные маркеры и фикстуры.

Ожидаемый основной вызов:

```bash
exec python -m pytest "$@"
```

### Блок 3. Поставить точные гейты на OPM-тесты

1. Пометить `test_timeout_is_failed_and_does_not_leak_a_container` существующим
   гейтом `requires_real_flow`.
2. Для submission-тестов добавить гейт с простым смыслом:
   «доступен настоящий кеш отклика или доступен Docker».
3. Применить его как минимум к:
   - `test_dynamic_gate_rejects_the_real_baseline_over_well_71`;
   - `test_all_six_identities_are_computed_even_when_the_tract_fails`;
   - `test_strict_mode_lists_every_reason_at_once`.
4. Не ставить модульный skip на весь `test_runner.py` или
   `test_submission.py`: тесты без Docker должны продолжить работу.

### Блок 4. Устранить ложнозелёный strict-mode тест

Усилить проверку `test_strict_mode_lists_every_reason_at_once`, чтобы ошибка
«Docker не найден» не считалась правильным результатом. Тест должен
подтверждать именно ожидаемый отчёт настоящего отклика и известные нарушения
динамики, а не просто наличие слова `validate_dynamic`.

### Блок 5. Привести сообщения и документацию в соответствие

Entrypoint не должен писать «полный прогон», если настоящий OPM недоступен.
Сообщение должно явно различать:

- полный прогон с доступным Docker;
- прогон внутри образа, где Docker-зависимые тесты будут пропущены;
- прогон без данных организаторов, где будут дополнительные законные `skip`.

Команды в README должны совпадать с реально работающим поведением.

## Границы задачи

Не менять:

- расчёт ЧДД;
- λ и connectivity;
- правила R0–R7;
- OPM runner и математику симуляции;
- форматы артефактов и JSON;
- frontend;
- обычный поток `webdata -> web`.

Не устанавливать Docker daemon внутрь образа и не подключать Docker socket по
умолчанию. Цель этой задачи — корректно пропускать невозможные внутри образа
проверки, сохраняя максимальное покрытие остальных тестов.

## Проверка результата

### Локально, при доступном Docker

```bash
.venv/bin/python -m pytest -q
```

Ожидание:

- все backend-тесты проходят;
- настоящий OPM Flow выполняется;
- нет новых `skip` относительно доступного локального окружения.

### Внутри образа, без Docker-клиента и daemon

```bash
docker build -t aios:tests .

docker run --rm \
  -v /путь/к/docs:/data/docs:ro \
  aios:tests tests

docker run --rm \
  -v /путь/к/docs:/data/docs:ro \
  aios:tests tests -q
```

Ожидание для обеих команд:

- exit code `0`;
- `0 failed`;
- Docker-зависимые тесты показаны как честные `skipped`;
- unit-тесты из `test_runner.py` и `test_submission.py`, которым Docker не
  нужен, реально выполняются;
- список исключённых файлов через grep отсутствует.

### Точечная регрессия

Проверить отдельно:

```bash
python -m pytest -q \
  tests/architecture/test_runtime_paths.py \
  backend/infrastructure/opm/tests/test_runner.py \
  backend/infrastructure/opm/tests/test_submission.py
```

## Готово, когда

- команды `tests` и `tests -q` внутри образа обе зелёные;
- тесты не определяют требования к окружению через grep исходного кода;
- каждый Docker-зависимый тест имеет явный и точный гейт;
- strict-mode тест больше не может пройти на ошибке отсутствующего Docker;
- проверка дефолтных путей не зависит от переменных Dockerfile;
- рабочее дерево чистое, изменения оформлены отдельными коммитами и проверены
  как локально, так и внутри собранного образа.
