from __future__ import annotations

import argparse
from pathlib import Path

from backend.shared.hashing import content_hash
from backend.contexts.schedule.application.emit import emit_from_deck

from backend.interfaces.cli.paths import model_z_schedule, require
from backend.interfaces.cli.runner import run as run_cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aios emit",
        description="Emit well_schedule.inc from the organizer deck via emit_lossless.",
    )
    parser.add_argument("--out", type=Path, default=Path("/out"))
    parser.add_argument("--deck", type=Path, default=None)
    parser.add_argument("--sparse", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    deck = args.deck if args.deck is not None else model_z_schedule()
    deck = require(deck, "Model_Z_sch.inc deck")

    args.out.mkdir(parents=True, exist_ok=True)
    path, emitted, report = emit_from_deck(deck, args.out, sparse=args.sparse)

    stats = emitted.stats
    print(f"deck:            {deck}")
    print(f"mode:            {'sparse' if args.sparse else 'full (lossless)'}")
    print(f"round-trip:      {report.format()}")
    print(f"dates:           {stats.n_dates}")
    print(f"WCONPROD blocks: {stats.n_wconprod_blocks}")
    print(f"WCONINJE blocks: {stats.n_wconinje_blocks}")
    print(f"COMPDAT blocks:  {stats.n_compdat_blocks}")
    print(f"WPIMULT blocks:  {stats.n_wpimult_blocks}")
    print(f"bytes:           {stats.n_bytes}")
    print(f"file:            {path}")
    print(f"content_hash:    {content_hash(path.read_bytes())}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
