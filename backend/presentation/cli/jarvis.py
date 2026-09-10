from __future__ import annotations

import argparse
import os
from pathlib import Path

from backend.application.jarvis.artifacts import ArtifactStore
from backend.application.jarvis.docs_index import DocsIndex, DocsIndexError, load_index
from backend.application.jarvis.fixtures import FIXTURE_DIR, write
from backend.application.jarvis.knowledge import Knowledge
from backend.application.jarvis.recordings import RECORDINGS
from backend.application.jarvis.system_map import SystemMap, SystemMapError
from backend.presentation.api.jarvis_server import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    JarvisService,
    serve,
)

HOST_ENV_VAR = "AIOS_JARVIS_HOST"
PORT_ENV_VAR = "AIOS_JARVIS_PORT"
KNOWLEDGE_ENV_VAR = "AIOS_JARVIS_KNOWLEDGE"
DATA_ENV_VAR = "AIOS_UI_DATA"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aios jarvis",
        description=(
            "Jarvis service: HTTP with Server-Sent Events over the JSON data "
            "showcase and the curated knowledge base."
        ),
    )
    parser.add_argument(
        "--host",
        default=os.environ.get(HOST_ENV_VAR, DEFAULT_HOST),
        help="interface to bind",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get(PORT_ENV_VAR, DEFAULT_PORT)),
        help="port to listen on",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help=f"data showcase directory; defaults to {DATA_ENV_VAR}",
    )
    parser.add_argument(
        "--knowledge",
        type=Path,
        default=None,
        help=f"knowledge base directory; defaults to {KNOWLEDGE_ENV_VAR}",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report health and exit without serving",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help=(
            "regenerate the local jsonl recordings used by the tests and by the "
            "frontend development mode, then exit"
        ),
    )
    return parser


def _optional_docs() -> DocsIndex | None:
    try:
        return load_index()
    except (DocsIndexError, OSError):
        return None


def _optional_system() -> SystemMap | None:
    try:
        return SystemMap()
    except SystemMapError:
        return None


def record(store: ArtifactStore, knowledge: Knowledge, root: Path) -> int:
    written = write(
        RECORDINGS,
        store,
        knowledge,
        root,
        docs=_optional_docs(),
        system=_optional_system(),
    )
    for path in written:
        print(path)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = ArtifactStore(args.data) if args.data is not None else ArtifactStore()
    knowledge = (
        Knowledge(args.knowledge) if args.knowledge is not None else Knowledge()
    )
    if args.record:
        return record(store, knowledge, Path(FIXTURE_DIR))
    service = JarvisService(store=store, knowledge=knowledge)
    if args.check:
        status, body = service.health()
        print(
            f"health={status} provider={body.get('provider', 'none')} "
            f"model={body.get('model', 'none')} data={body['data']} "
            f"terms={body['knowledge']['terms']} screens={body['knowledge']['screens']} "
            f"nodes={body['knowledge']['system_nodes']} docs={body['docs']} "
            f"sessions={body['sessions']}"
        )
        return 0 if status == 200 else 1
    serve(host=args.host, port=args.port, service=service)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
