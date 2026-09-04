# Backend architecture

The Python backend is organised around one rule: code that describes the
reservoir business must not know how Docker, OPM, a browser, or an LLM client
works.

## Source tree

Backend code lives in `backend/`.

```text
core/            Shared data types and hashes.
domain/          Schedule, economics, policy, connectivity, robustness, and runtime settings.
ml/              Training and inference for the fast reservoir model.
infrastructure/  OPM, files, caches, datasets, and external LLM clients.
application/     Workflows: build a plan, optimise, verify, submit, export.
presentation/    CLI commands and Python JSON export for the web UI.
```

`frontend/` is a separate React application and is outside this backend
refactor.

## Dependency direction

```text
presentation → application → domain → core
                    ↓
              infrastructure
                    ↓
                   core
```

- `core` imports no higher layer.
- `domain` imports only `core` and other `domain` modules.
- `ml` imports `core`, `domain`, and read-only OPM dataset adapters; it does
  not import application, UI, or CLI code.
- `application` coordinates domain and infrastructure code.
- `infrastructure` implements external details; it does not decide business
  rules.
- `presentation` is the only layer that parses command-line input or writes
  UI-facing files.

Only `backend/` contains backend code. Temporary top-level package
paths were removed after migration.

## Jarvis

Jarvis is the console's visual assistant: a question in natural language turns
into a scene of cards built from the same JSON showcase the frontend reads. It
is a module that crosses every layer under the rules above, not a script bolted
onto the UI. Its design and wire contract live in `JARVIS.md`.

```text
frontend/src/jarvis/          Browser presentation: the second cube face, sphere, scenes, cards.
          │  SSE  /api/jarvis/*
backend/presentation/api/     HTTP boundary: service, handler, SSE framing, proxy into web.py.
backend/application/jarvis/   Orchestrator, tools, knowledge base, number guard, sessions.
backend/domain/*              Policy, economics, connectivity — read, never duplicated.
backend/infrastructure/llm/   Chat providers: OpenRouter (primary), Anthropic (fallback).
backend/core/contracts        Shared types; nothing here is reinvented in the module.
```

The dependency direction is the project's own: `presentation → application →
domain → core` and `application → infrastructure → core`. `application/jarvis`
receives a `ChatClient` from the outside and imports neither `urllib`, `http`,
nor `anthropic`; tools read artifacts through `backend/application/jarvis/artifacts.py`
and reuse `backend/infrastructure/llm/explainer.py` and `diagnostics.py` instead of
copying their logic. A test in `tests/` guards the layering.

### Service

`jarvis` is a separate process and a separate compose service on port 8010, on
the stdlib `ThreadingHTTPServer`, with a chunked `text/event-stream` response
and a `: keep-alive` comment every 15 seconds so idle proxies do not drop a slow
answer. Routes: `GET /api/jarvis/health`, `POST /api/jarvis/ask`,
`POST /api/jarvis/cancel`. CORS is granted only to the dev origins
`http://localhost:5199` and `http://127.0.0.1:5199`. In a container the `web`
service forwards `/api/jarvis/*` to `jarvis:8010`, so the frontend always talks
to a single origin.

Entry points: `python -m backend.presentation.cli.jarvis` locally,
`docker compose up jarvis web` in a container, and the `jarvis` command in
`docker/entrypoint.sh`.

### Environment

| Variable | Default | Meaning |
|---|---|---|
| `JARVIS_PROVIDER` | `openrouter` | `openrouter` or `anthropic` |
| `OPENROUTER_API_KEY` | — | OpenRouter key, the primary path |
| `ANTHROPIC_API_KEY` | — | Anthropic key, the fallback path |
| `JARVIS_MODEL` | `anthropic/claude-sonnet-4.5` | any model with tool calling and streaming |
| `JARVIS_MAX_TOKENS` | `1200` | answer length ceiling |
| `AIOS_UI_DATA` | the showcase in the repository | JSON showcase directory |
| `AIOS_JARVIS_KNOWLEDGE` | `frontend/public/jarvis/knowledge` | curated knowledge base |
| `AIOS_JARVIS_HOST` / `AIOS_JARVIS_PORT` | `0.0.0.0` / `8010` | bind address |
| `AIOS_JARVIS_UPSTREAM` | `http://jarvis:8010` | upstream the `web` proxy forwards to |

Without a key the service still starts and answers `503`
`{"ok": false, "error": "no-api-key"}` with a message naming the variable to
set; the console keeps working and the assistant falls back to the recorded
fixtures.

### Removing the module

The module boundary is hard, and that is a checkable property: it protects the
product if the assistant does not land in time. To switch Jarvis off entirely,
delete

```text
frontend/src/jarvis/
frontend/public/jarvis/
backend/application/jarvis/
backend/presentation/api/
backend/infrastructure/llm/{chat,chat_events,openrouter,anthropic_chat,tools_format,provider,fake_chat}.py
backend/presentation/cli/jarvis.py
```

and drop the four call sites that reference them: the proxy import and the two
`is_jarvis_path` branches in `backend/presentation/cli/web.py`, the `jarvis`
command in `docker/entrypoint.sh`, the `jarvis` service in
`docker-compose.yml`, and the Jarvis mount points in `frontend/src/main.tsx`
and `frontend/src/ui/WorkspaceNav/`. Nothing else in the backend imports the
module: `backend/infrastructure/llm/client.py`, `explainer.py`, and `diagnostics.py`
predate Jarvis and stay.

## Run command

Use `python -m backend.presentation.cli.run search`, `verify`, or `full`. The `full` mode runs
the real fast-model search and then the real OPM verification. It stops if the
first step fails; a prediction is never presented as a verified result. To
verify a previously searched plan without searching again, use
`python -m backend.presentation.cli.run verify --run-id <id>`; it reads that run's saved
schedule, never the global legacy `cmaes.json`.

Every new run is isolated under `out/runs/<run-id>/`:

```text
manifest.json     Status, schedule hash, predicted and verified NPV.
schedule/         Canonical schedule passed through the workflow.
prediction/       Fast-model result.
opm/              OPM work directory for the same schedule.
validation/       Soundness, OPM status, dynamic violations, identities.
economics/        Verified NPV when the tract reached Economics.
inputs/, ui/      Reserved inputs and presentation output for this run.
```

`ready_to_submit` is written only when OPM reports `sound=true`; otherwise the
same evidence is retained but the manifest is `rejected`.
