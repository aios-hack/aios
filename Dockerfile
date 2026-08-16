# syntax=docker/dockerfile:1.7

# Образ собирается для ПОЛНОГО репозитория (после слияния всех веток).
# Пакеты, отсутствующие в срезе, из которого идёт сборка, пропускаются
# устойчиво: сборка не падает, но печатает, что найдено, а что нет.
#
# Данные организаторов (docs/models: дек Model_Z, CHDD_PYTHON, нормативы)
# в образ НЕ копируются: их запрещено подменять и они не поставляются с
# решением. Монтируются снаружи в /data/docs.

# ---------------------------------------------------------------------------
# Стадия 1: сборка фронта. Пропускается корректно, если ui/web нет в срезе.
# ---------------------------------------------------------------------------
FROM node:22.11.0-bookworm-slim AS frontend

WORKDIR /build

# Копируется весь контекст: наличие ui/web заранее неизвестно, а COPY по
# отсутствующему пути — ошибка сборки. .dockerignore держит контекст малым.
COPY . /build/

RUN set -eux; \
    if [ -f /build/ui/web/package.json ]; then \
        echo "ui/web найден — собираю фронт"; \
        cd /build/ui/web; \
        if [ -f package-lock.json ]; then npm ci; else npm install; fi; \
        npm run build; \
        mkdir -p /frontend; \
        cp -r dist /frontend/dist; \
    else \
        echo "ui/web отсутствует в этом срезе репозитория — стадия фронта пропущена"; \
        mkdir -p /frontend/dist-missing; \
    fi

# ---------------------------------------------------------------------------
# Стадия 2: расчётный образ.
# ---------------------------------------------------------------------------
FROM python:3.12.7-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AIOS_DOCS_ROOT=/data/docs \
    AIOS_OUT_DIR=/out \
    PYTHONHASHSEED=0 \
    AIOS_SEED=20260816

WORKDIR /app

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends tini; \
    rm -rf /var/lib/apt/lists/*

# Зависимости ставятся отдельным слоем от кода: правка кода не пересобирает pip.
COPY pyproject.toml /app/
RUN set -eux; \
    python -m pip install --upgrade "pip==24.3.1" "setuptools==75.6.0" "wheel==0.45.1"; \
    python -m pip install "openpyxl==3.1.5" "pytest==8.3.4" "anthropic==0.40.0"

COPY . /app/

# Пакет ставится редактируемым: пути внутри образа совпадают с исходным деревом.
RUN set -eux; \
    python -m pip install --no-deps -e ".[dev]"

COPY --from=frontend /frontend/ /app/web-build/
RUN set -eux; \
    if [ -d /app/web-build/dist ]; then \
        mkdir -p /app/ui/web; \
        rm -rf /app/ui/web/dist; \
        cp -r /app/web-build/dist /app/ui/web/dist; \
        echo "фронт уложен в /app/ui/web/dist"; \
    else \
        echo "фронта нет — веб-интерфейс в этом образе недоступен"; \
    fi; \
    rm -rf /app/web-build

RUN set -eux; \
    chmod +x /app/docker/entrypoint.sh; \
    mkdir -p /out /data/docs

# Состав образа печатается на сборке: видно, что попало, а что отсутствует.
RUN python -m aios_cli.selfcheck

ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
CMD ["selfcheck"]
