#!/bin/zsh
# Статус-бар долгих прогонов: G7, кампания λ, CMA-ES.
# Запуск: ./status.sh [интервал в секундах, по умолчанию 5]
# Выход: Ctrl+C.

set -u
setopt null_glob 2>/dev/null
ROOT="${0:A:h}"
INTERVAL="${1:-5}"

bar() {  # bar <сделано> <всего> <ширина>
  local done=$1 total=$2 width=$3
  (( total <= 0 )) && total=1
  local filled=$(( done * width / total ))
  (( filled > width )) && filled=$width
  local empty=$(( width - filled ))
  printf '['
  printf '%.0s#' {1..$filled} 2>/dev/null
  (( empty > 0 )) && printf '%.0s.' {1..$empty}
  printf '] %d/%d' "$done" "$total"
}

alive() { kill -0 "$1" 2>/dev/null && echo "идёт" || echo "нет"; }

typeset g7pid g7stage g7log flowlog steps containers manifest runs flowlogs

while true; do
  printf '\033[2J\033[H'
  print -r -- "AIOS — статус прогонов, $(date '+%d.%m %H:%M:%S')"
  print -r -- "--------------------------------------------------------------"

  # --- G7 -----------------------------------------------------------------
  g7log="$ROOT/data/g7.log"
  g7pid=$(pgrep -f "run_g7.py" | head -1)
  if [[ -n "$g7pid" ]]; then
    if grep -q "звено А:" "$g7log" 2>/dev/null; then
      g7stage="звено А: эмит, Flow, отклик, гейт"
    elif grep -q "хеш совпал" "$g7log" 2>/dev/null; then
      g7stage="θ* восстановлена, готовит дек"
    else
      g7stage="воспроизводит θ* поиском (~19 мин)"
    fi
    print -r -- "G7   [идёт]  $g7stage"
  elif [[ -f "$ROOT/data/g7-result.json" ]]; then
    print -r -- "G7   [готово] $(python3 -c "
import json;d=json.load(open('$ROOT/data/g7-result.json'))
opm=d.get('npv_opm'); sur=d.get('npv_surrogate')
print(('ЧДД OPM %.3f млрд' % (opm/1e9)) if opm else 'ЧДД не посчитан', '| суррогат %.3f млрд' % (sur/1e9),
      '| годен к сдаче:', d.get('sound'))" 2>/dev/null)"
  else
    print -r -- "G7   [нет]"
  fi

  # прогресс самого Flow по репортным шагам, если контейнер работает
  flowlogs=("$ROOT"/data/g7-submission/runs/*/flow.log(N.om))
  if (( ${#flowlogs} > 0 )); then
    flowlog="${flowlogs[1]}"
    steps=$(grep -c "^Report step" "$flowlog" 2>/dev/null | head -1)
    printf '     Flow: '
    bar "${steps:-0}" 371 40
    printf ' репортных шагов\n'
  fi

  # --- контейнеры OPM ------------------------------------------------------
  containers=$(pgrep -fc "docker run.*opm-run" 2>/dev/null || echo 0)
  print -r -- "OPM  контейнеров запущено: ${containers}"

  # --- CMA-ES -------------------------------------------------------------
  if pgrep -f "optimizer.search_run" >/dev/null 2>&1; then
    print -r -- "CMA  [идёт]  $(grep 'новый максимум' "$ROOT/data/cmaes2.log" 2>/dev/null | tail -1)"
  elif [[ -f "$ROOT/data/lambda-window-2007/cmaes.json" ]]; then
    print -r -- "CMA  [готово] $(python3 -c "
import json;d=json.load(open('$ROOT/data/lambda-window-2007/cmaes.json'))
print('ЧДД %.3f млрд, оценок %d, нарушений %d' % (d['npv_predicted']/1e9, d['evaluations'], d['static_violations']))" 2>/dev/null)"
  fi

  # --- кампания λ ---------------------------------------------------------
  manifest="$ROOT/data/lambda-window-2007/manifest.jsonl"
  if [[ -f "$manifest" ]]; then
    runs=$(grep -o '"scenario_id": "lambda-b[0-9]*-[0-9]*"' "$manifest" 2>/dev/null | sort -u | wc -l | tr -d ' ')
    printf 'λ    прогонов в манифесте: '
    bar "$runs" 108 40
    printf '\n'
  fi

  print -r -- "--------------------------------------------------------------"
  print -r -- "последние строки G7:"
  tail -3 "$g7log" 2>/dev/null | sed 's/^/  /'
  print -r -- ""
  print -r -- "обновление каждые ${INTERVAL} с, выход Ctrl+C"
  sleep "$INTERVAL"
done
