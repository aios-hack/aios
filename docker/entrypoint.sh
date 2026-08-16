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

cmd_tests() {
    if have_docs; then
        echo "== тесты: данные организаторов найдены в $DOCS_ROOT, полный прогон"
    else
        warn_no_docs
        echo "== тесты: прогон без данных, тесты на данных будут пропущены (skip)"
    fi
    if [ "$#" -gt 0 ]; then
        exec python -m pytest "$@"
    fi
    if command -v docker >/dev/null 2>&1; then
        exec python -m pytest
    fi
    local ignores=()
    local path
    for path in $(grep -rlE 'shutil\.which\("docker"\)' bridge/tests 2>/dev/null | sort); do
        ignores+=("--ignore=$path")
    done
    echo "== в образе нет docker: исключены тесты, требующие настоящий OPM Flow"
    printf '   %s\n' "${ignores[@]#--ignore=}"
    exec python -m pytest "${ignores[@]}"
}

cmd_npv() {
    if ! have_docs; then
        warn_no_docs
        echo "Расчёт ЧДД невозможен без данных организаторов." >&2
        exit 2
    fi
    mkdir -p "$OUT_DIR"
    exec python -m aios_cli.npv --out "$OUT_DIR" "$@"
}

cmd_emit() {
    if ! have_docs; then
        warn_no_docs
        echo "Эмит wells_schedule.inc невозможен без дека организаторов." >&2
        exit 2
    fi
    mkdir -p "$OUT_DIR"
    exec python -m aios_cli.emit --out "$OUT_DIR" "$@"
}

cmd_web() {
    if [ ! -d /app/ui/web/dist ]; then
        echo "ВНИМАНИЕ: собранный фронт /app/ui/web/dist отсутствует в этом образе." >&2
        echo "Каталог ui/web принадлежит пакету Михаила и в текущем срезе репозитория" >&2
        echo "не присутствует — веб-интерфейс не собран. Соберите образ на ветке," >&2
        echo "где ui/web уже влит." >&2
        exit 3
    fi
    exec python -m aios_cli.web --host "${AIOS_HOST:-0.0.0.0}" --port "${AIOS_PORT:-8000}" "$@"
}

cmd_selfcheck() {
    python -m aios_cli.selfcheck
}

usage() {
    cat >&2 <<'USAGE'
Использование: docker run ... aios <команда> [аргументы]

Команды:
  tests [аргументы pytest]   прогон тестов пакета
  npv [аргументы]            расчёт ЧДД и сверка с эталонным расчётчиком
  emit [аргументы]           эмит wells_schedule.inc из дека организаторов
  web [аргументы]            веб-интерфейс (требует собранного ui/web)
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
        selfcheck) cmd_selfcheck "$@" ;;
        shell) exec /bin/bash "$@" ;;
        help | --help | -h) usage ;;
        *) exec "$command" "$@" ;;
    esac
}

main "$@"
