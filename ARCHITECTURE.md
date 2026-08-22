# Backend architecture

The Python backend is organised around one rule: code that describes the
reservoir business must not know how Docker, OPM, a browser, or an LLM client
works.

## Source tree

New backend code lives in `src/aios_backend/`.

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

The temporary top-level packages (`contracts`, `bridge`, `optimizer`, and so
on) stay as compatibility entry points while callers migrate. New production
code must be added under `src/aios_backend/`.

## Run command

Use `python -m aios_cli.run search`, `verify`, or `full`. The `full` mode runs
the real fast-model search and then the real OPM verification. It stops if the
first step fails; a prediction is never presented as a verified result. To
verify a previously searched plan without searching again, use
`python -m aios_cli.run verify --run-id <id>`; it reads that run's saved
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
same evidence is retained but the manifest is `rejected`. Existing commands
such as `python -m optimizer.search_run` and `python -m bridge.submission_run`
remain available as compatibility entry points.
