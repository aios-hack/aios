#!/bin/zsh
# G10, фаза 2: ждём пул и гоняем кандидатов настоящим OPM по трое за раз.
# Троих, а не больше: каждый воркер держит свой контейнер Flow плюс копию
# суррогата, а на машине уже занято 23 из 24 ГБ чужими процессами.
set -u
cd /Users/kaifarikman/hackathons/aios-hack/aios
POOL=data/g10-verification/pool.json
PAR=${1:-3}

while [ ! -s "$POOL" ]; do sleep 20; done
N=$(.venv/bin/python -c "import json;print(len(json.load(open('$POOL'))['candidates']))")
echo "пул готов: кандидатов $N, параллельно $PAR"
seq 0 $((N-1)) | xargs -P "$PAR" -I{} env PYTHONPATH=. .venv/bin/python tools/g10_run.py {}
echo "все кандидаты посчитаны, собираю таблицу"
PYTHONPATH=. .venv/bin/python tools/g10_table.py
