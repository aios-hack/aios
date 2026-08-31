#!/usr/bin/env bash
set -euo pipefail

DOCS_ROOT="${AIOS_DOCS_ROOT:-/data/docs}"
export AIOS_DOCS_ROOT="$DOCS_ROOT"
OUT_DIR="${AIOS_OUT_DIR:-/out}"

have_docs() {
    [ -d "$DOCS_ROOT/models" ]
}

warn_no_docs() {
    echo "ВНИМАНИЕ: данные организаторов не смонтированы в $DOCS_ROOT." >&2
    echo "Они не поставляются с образом (запрет подмены исходных данных)." >&2
    echo "Смонтируйте каталог docs: -v /путь/к/aios/docs:/data/docs:ro" >&2
}

have_docker_flow() {
    command -v docker >/dev/null 2>&1 \
        && docker info --format '{{.ServerVersion}}' >/dev/null 2>&1
}

cmd_tests() {
    if have_docs; then
        if have_docker_flow; then
            echo "== тесты: данные организаторов и Docker daemon доступны, полный прогон"
        else
            echo "== тесты: данные организаторов найдены, Docker daemon недоступен"
            echo "   тесты настоящего OPM Flow будут пропущены через pytest skip"
        fi
    else
        warn_no_docs
        echo "== тесты: тесты на данных организаторов будут пропущены через pytest skip"
        if ! have_docker_flow; then
            echo "   Docker daemon недоступен: тесты настоящего OPM Flow тоже будут пропущены"
        fi
    fi
    exec python -m pytest "$@"
}

cmd_npv() {
    if ! have_docs; then
        warn_no_docs
        echo "Расчёт ЧДД невозможен без данных организаторов." >&2
        exit 2
    fi
    mkdir -p "$OUT_DIR"
    exec python -m backend.presentation.cli.npv --out "$OUT_DIR" "$@"
}

cmd_emit() {
    if ! have_docs; then
        warn_no_docs
        echo "Эмит wells_schedule.inc невозможен без дека организаторов." >&2
        exit 2
    fi
    mkdir -p "$OUT_DIR"
    exec python -m backend.presentation.cli.emit --out "$OUT_DIR" "$@"
}

cmd_web() {
    if [ ! -d /app/frontend/dist ]; then
        echo "ВНИМАНИЕ: собранный фронт /app/frontend/dist отсутствует в этом образе." >&2
        echo "Стадия сборки фронта не отработала: проверьте, что каталог frontend/" >&2
        echo "попал в контекст сборки и npm run build прошёл без ошибок." >&2
        exit 3
    fi
    for path in wells.json graph.json hierarchy.json npv.json timeline.json scenarios.json; do
        if [ ! -f "/app/frontend/dist/data/$path" ]; then
            echo "ВНИМАНИЕ: нет /app/frontend/dist/data/$path." >&2
            echo "Через compose этот набор автоматически готовит сервис webdata." >&2
            exit 4
        fi
    done
    exec python -m backend.presentation.cli.web --host "${AIOS_HOST:-0.0.0.0}" --port "${AIOS_PORT:-8000}" "$@"
}

cmd_webdata() {
    if ! have_docs; then
        warn_no_docs
        echo "Сборка данных интерфейса невозможна без дека организаторов." >&2
        exit 2
    fi
    if [ ! -f /app/data/base_case/response.json ]; then
        # Репозиторий содержит проверенный snapshot витрины для срочного
        # воспроизводимого запуска. Реальный OPM response нужен только для
        # регенерации; отсутствие локального data/ не должно блокировать web.
        for path in wells.json graph.json hierarchy.json npv.json timeline.json scenarios.json; do
            if [ ! -f "/app/frontend/public/data/$path" ]; then
                echo "Нет ни /app/data/base_case/response.json, ни готового /app/frontend/public/data/$path." >&2
                exit 2
            fi
        done
        echo "Локального OPM response нет — используется проверенный snapshot витрины из репозитория."
        return 0
    fi
    mkdir -p /app/frontend/public/data
    if [ -f /app/data/lambda-window-2007/lambda.json ]; then
        export AIOS_LAMBDA_PATH=/app/data/lambda-window-2007/lambda.json
    fi
    python -m backend.presentation.ui_export.demo
    for path in wells.json graph.json hierarchy.json npv.json timeline.json scenarios.json; do
        test -f "/app/frontend/public/data/$path"
    done
    echo "Данные интерфейса собраны в /app/frontend/public/data"
}

cmd_selfcheck() {
    python -m backend.presentation.cli.selfcheck
}

usage() {
    cat >&2 <<'USAGE'
Использование: docker run ... aios <команда> [аргументы]

Команды:
  tests [аргументы pytest]   прогон тестов пакета
  npv [аргументы]            расчёт ЧДД и сверка с эталонным расчётчиком
  emit [аргументы]           эмит wells_schedule.inc из дека организаторов
  web [аргументы]            веб-интерфейс (требует собранного frontend)
  webdata                    собрать полный JSON-набор для интерфейса
  selfcheck                  что найдено в образе и в смонтированных данных
  shell                      интерактивная оболочка

Данные организаторов монтируются снаружи:
  -v /путь/к/aios/docs:/data/docs:ro
Результаты пишутся в /out:
  -v /путь/к/выходу:/out
USAGE
    exit 64
}

main() {
    if [ "$#" -eq 0 ]; then
        usage
    fi
    local command="$1"
    shift
    case "$command" in
        tests) cmd_tests "$@" ;;
        npv) cmd_npv "$@" ;;
        emit) cmd_emit "$@" ;;
        web) cmd_web "$@" ;;
        webdata) cmd_webdata "$@" ;;
        selfcheck) cmd_selfcheck "$@" ;;
        shell) exec /bin/bash "$@" ;;
        help | --help | -h) usage ;;
        *) exec "$command" "$@" ;;
    esac
}

main "$@"
