#!/usr/bin/env bash
# Холодный повтор: чистый клон репозитория, установка зависимостей, повторная
# верификация сохранённого расписания настоящим OPM и сверка ЧДД с пакетом сдачи.
# Ненулевой код возврата означает, что число НЕ воспроизвелось.
set -euo pipefail

readonly PROGRAM_NAME="${0##*/}"
readonly DEFAULT_REPOSITORY="https://github.com/aios-hack/aios"

usage() {
    cat >&2 <<USAGE
Использование: $PROGRAM_NAME --run-id <id> [опции]

Обязательное:
  --run-id <id>            прогон, который повторяется с нуля

Опции:
  --submission <каталог>   пакет сдачи с claimed_npv.json
                           (умолчание: <--runs-root>/<run-id>/submission)
  --runs-root <каталог>    каталог прогонов исходной рабочей копии
                           (умолчание: \$AIOS_OUT_DIR/runs, иначе ./out/runs)
  --docs <каталог>         данные организаторов, монтируются в клон только на чтение
                           (умолчание: \$AIOS_DOCS_ROOT, иначе ../docs рядом с репозиторием)
  --repository <url|путь>  источник клона (умолчание: origin рабочей копии,
                           иначе $DEFAULT_REPOSITORY)
  --ref <ревизия>          ветка/тег/коммит для клона; по умолчанию берётся
                           git_commit из claimed_npv.json, иначе HEAD источника
  --keep                   не удалять временный каталог даже при успехе
  --help                   эта справка

Код возврата:
  0  ЧДД воспроизведён байт в байт, разница равна нулю
  1  расхождение ЧДД или расписания
  2  повтор не выполнен (нет данных, клон/установка/OPM отказали)
 64  ошибка в аргументах
USAGE
}

die() {
    echo "$PROGRAM_NAME: $*" >&2
    exit 2
}

die_usage() {
    echo "$PROGRAM_NAME: $*" >&2
    usage
    exit 64
}

RUN_ID=""
SUBMISSION_DIR=""
RUNS_ROOT=""
DOCS_ROOT=""
REPOSITORY=""
REF=""
KEEP=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --run-id) [ "$#" -ge 2 ] || die_usage "--run-id требует значение"; RUN_ID="$2"; shift 2 ;;
        --submission) [ "$#" -ge 2 ] || die_usage "--submission требует значение"; SUBMISSION_DIR="$2"; shift 2 ;;
        --runs-root) [ "$#" -ge 2 ] || die_usage "--runs-root требует значение"; RUNS_ROOT="$2"; shift 2 ;;
        --docs) [ "$#" -ge 2 ] || die_usage "--docs требует значение"; DOCS_ROOT="$2"; shift 2 ;;
        --repository) [ "$#" -ge 2 ] || die_usage "--repository требует значение"; REPOSITORY="$2"; shift 2 ;;
        --ref) [ "$#" -ge 2 ] || die_usage "--ref требует значение"; REF="$2"; shift 2 ;;
        --keep) KEEP=1; shift ;;
        --help | -h) usage; exit 0 ;;
        *) die_usage "неизвестный аргумент: $1" ;;
    esac
done

[ -n "$RUN_ID" ] || die_usage "--run-id обязателен: без него неизвестно, какое расписание повторять"

SOURCE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if [ -z "$RUNS_ROOT" ]; then
    if [ -n "${AIOS_OUT_DIR:-}" ]; then
        RUNS_ROOT="$AIOS_OUT_DIR/runs"
    else
        RUNS_ROOT="$SOURCE_ROOT/out/runs"
    fi
fi
SOURCE_RUN_DIR="$RUNS_ROOT/$RUN_ID"
[ -d "$SOURCE_RUN_DIR" ] || die "прогон $RUN_ID не найден: $SOURCE_RUN_DIR отсутствует"

[ -n "$SUBMISSION_DIR" ] || SUBMISSION_DIR="$SOURCE_RUN_DIR/submission"
CLAIMED_JSON="$SUBMISSION_DIR/claimed_npv.json"
[ -f "$CLAIMED_JSON" ] || die "пакет сдачи неполон: нет $CLAIMED_JSON. Соберите его командой \`python -m backend.presentation.cli.run submit --run-id $RUN_ID\`"

if [ -z "$DOCS_ROOT" ]; then
    if [ -n "${AIOS_DOCS_ROOT:-}" ]; then
        DOCS_ROOT="$AIOS_DOCS_ROOT"
    else
        DOCS_ROOT="$(dirname -- "$SOURCE_ROOT")/docs"
    fi
fi
[ -d "$DOCS_ROOT/models" ] || die "данные организаторов не найдены: нет $DOCS_ROOT/models. Укажите каталог через --docs; они не входят в репозиторий"

if [ -z "$REPOSITORY" ]; then
    REPOSITORY="$(git -C "$SOURCE_ROOT" config --get remote.origin.url 2>/dev/null || true)"
    [ -n "$REPOSITORY" ] || REPOSITORY="$DEFAULT_REPOSITORY"
fi

command -v git >/dev/null 2>&1 || die "git не найден в PATH: клонировать нечем"
command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1 || die "python не найден в PATH"
if command -v python3 >/dev/null 2>&1; then
    HOST_PYTHON="python3"
else
    HOST_PYTHON="python"
fi
command -v docker >/dev/null 2>&1 || die "docker не найден в PATH: настоящий прогон OPM Flow невозможен"
docker info --format '{{.ServerVersion}}' >/dev/null 2>&1 || die "docker daemon недоступен: настоящий прогон OPM Flow невозможен"

WORKDIR="$(mktemp -d 2>/dev/null || mktemp -d -t aios-cold-repeat)"
FAILED=1

cleanup() {
    local status=$?
    if [ "$FAILED" -eq 0 ] && [ "$KEEP" -eq 0 ]; then
        rm -rf -- "$WORKDIR"
    else
        echo "Временный каталог сохранён для разбора: $WORKDIR" >&2
    fi
    exit "$status"
}
trap cleanup EXIT

CLONE_DIR="$WORKDIR/repo"
COLD_RUNS_ROOT="$WORKDIR/out/runs"
COLD_RUN_DIR="$COLD_RUNS_ROOT/$RUN_ID"

# Ревизия берётся из пакета: повтор обязан идти на том коммите, для которого
# заявлено число, а не на текущем состоянии ветки.
if [ -z "$REF" ]; then
    REF="$("$HOST_PYTHON" - "$CLAIMED_JSON" <<'PY' || true
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        bundle = json.load(handle)
except (OSError, ValueError):
    raise SystemExit(1)
commit = bundle.get("git_commit")
if isinstance(commit, str) and commit.strip() and commit.strip() != "unknown":
    print(commit.strip())
PY
)"
fi

echo "== холодный повтор прогона $RUN_ID"
echo "   источник клона: $REPOSITORY"
echo "   ревизия:        ${REF:-HEAD источника}"
echo "   данные:         $DOCS_ROOT"
echo "   пакет сдачи:    $SUBMISSION_DIR"
echo "   временный каталог: $WORKDIR"

echo "== клон"
git clone --quiet "$REPOSITORY" "$CLONE_DIR"
if [ -n "$REF" ]; then
    git -C "$CLONE_DIR" checkout --quiet "$REF"
fi
echo "   HEAD клона: $(git -C "$CLONE_DIR" rev-parse HEAD)"

echo "== зависимости"
"$HOST_PYTHON" -m venv "$WORKDIR/venv"
if [ -x "$WORKDIR/venv/bin/python" ]; then
    VENV_PYTHON="$WORKDIR/venv/bin/python"
else
    VENV_PYTHON="$WORKDIR/venv/Scripts/python.exe"
fi
"$VENV_PYTHON" -m pip install --quiet --upgrade pip
"$VENV_PYTHON" -m pip install --quiet -e "$CLONE_DIR"
if [ -f "$CLONE_DIR/requirements-ml.txt" ]; then
    "$VENV_PYTHON" -m pip install --quiet -r "$CLONE_DIR/requirements-ml.txt"
fi

# Клон чист: сохранённое расписание и вход прогона переносятся из исходной
# рабочей копии, потому что out/ вне git. Повторяется именно verify — поиск
# заново не запускается, иначе повторялось бы другое расписание.
echo "== перенос сохранённого расписания"
mkdir -p "$COLD_RUN_DIR"
for item in manifest.json schedule inputs; do
    [ -e "$SOURCE_RUN_DIR/$item" ] || die "в прогоне $RUN_ID нет $item: повторять нечего ($SOURCE_RUN_DIR/$item)"
    cp -R -- "$SOURCE_RUN_DIR/$item" "$COLD_RUN_DIR/"
done

echo "== verify на чистом клоне (настоящий OPM Flow, 10-20 минут)"
(
    cd "$CLONE_DIR"
    AIOS_PROJECT_ROOT="$CLONE_DIR" \
    AIOS_DOCS_ROOT="$DOCS_ROOT" \
    AIOS_OUT_DIR="$WORKDIR/out" \
    AIOS_RUN_INITIATOR="cli" \
    "$VENV_PYTHON" -m backend.presentation.cli.run verify \
        --run-id "$RUN_ID" \
        --runs-root "$COLD_RUNS_ROOT"
)

echo "== сверка ЧДД"
set +e
PYTHONIOENCODING="utf-8" "$VENV_PYTHON" - "$CLAIMED_JSON" "$COLD_RUN_DIR" <<'PY'
import json
import sys
from pathlib import Path

claimed_path = Path(sys.argv[1])
cold_run_dir = Path(sys.argv[2])

try:
    bundle = json.loads(claimed_path.read_text(encoding="utf-8"))
except (OSError, ValueError) as error:
    print(f"ОТКАЗ: {claimed_path} не прочитан: {error}")
    raise SystemExit(2)

claimed = bundle.get("claimed_npv_rub")
if not isinstance(claimed, (int, float)) or isinstance(claimed, bool):
    print(f"ОТКАЗ: в пакете нет числового claimed_npv_rub (получено {claimed!r})")
    raise SystemExit(2)

manifest_path = cold_run_dir / "manifest.json"
try:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
except (OSError, ValueError) as error:
    print(f"ОТКАЗ: манифест холодного прогона не прочитан: {error}")
    raise SystemExit(2)

repeated = manifest.get("verified_npv")
if not isinstance(repeated, (int, float)) or isinstance(repeated, bool):
    print(
        "ОТКАЗ: холодный прогон не дал проверенного ЧДД "
        f"(verified_npv={repeated!r}, sound={manifest.get('sound')!r}). "
        "Повтор не состоялся, сверять нечего."
    )
    raise SystemExit(2)

claimed_hash = bundle.get("canonical_schedule_hash")
repeated_hash = manifest.get("schedule_hash")
difference = float(repeated) - float(claimed)

print(f"заявленный ЧДД, руб:      {float(claimed):.6f}")
print(f"воспроизведённый ЧДД, руб: {float(repeated):.6f}")
print(f"РАЗНИЦА, руб:              {difference:.6f}")
print(f"заявленный хеш расписания:      {claimed_hash}")
print(f"воспроизведённый хеш расписания: {repeated_hash}")

problems = []
if claimed_hash != repeated_hash:
    problems.append("хеш расписания разошёлся: повторено не то расписание")
if difference != 0.0:
    problems.append(f"ЧДД разошёлся на {difference:.6f} руб")

if problems:
    for problem in problems:
        print(f"РАСХОЖДЕНИЕ: {problem}")
    raise SystemExit(1)

print("Число воспроизведено с нуля: разница ноль, расписание то же.")
PY
COMPARE_STATUS=$?
set -e

echo "== сверка пакета сдачи с заявленными хешами"
set +e
(
    cd "$CLONE_DIR"
    AIOS_PROJECT_ROOT="$CLONE_DIR" \
    AIOS_DOCS_ROOT="$DOCS_ROOT" \
    "$VENV_PYTHON" -m backend.presentation.cli.selfcheck --submission "$SUBMISSION_DIR"
)
SELFCHECK_STATUS=$?
set -e

if [ "$COMPARE_STATUS" -ne 0 ]; then
    echo "ХОЛОДНЫЙ ПОВТОР НЕ ПРОЙДЕН: сверка ЧДД вернула $COMPARE_STATUS" >&2
    exit "$COMPARE_STATUS"
fi
if [ "$SELFCHECK_STATUS" -ne 0 ]; then
    echo "ХОЛОДНЫЙ ПОВТОР НЕ ПРОЙДЕН: selfcheck пакета вернул $SELFCHECK_STATUS" >&2
    exit "$SELFCHECK_STATUS"
fi

FAILED=0
echo "ХОЛОДНЫЙ ПОВТОР ПРОЙДЕН: разница ЧДД 0, пакет соответствует заявленным хешам."
