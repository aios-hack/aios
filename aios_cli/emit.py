from __future__ import annotations

import argparse
from pathlib import Path

from contracts import content_hash
from schedule import emit_from_deck

from .paths import model_z_schedule, require


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aios emit",
        description="Эмит wells_schedule.inc из дека организаторов через LosslessEmitter.",
    )
    parser.add_argument("--out", type=Path, default=Path("/out"))
    parser.add_argument("--deck", type=Path, default=None)
    parser.add_argument("--sparse", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    deck = args.deck if args.deck is not None else model_z_schedule()
    deck = require(deck, "дек Model_Z_sch.inc")

    args.out.mkdir(parents=True, exist_ok=True)
    path, emitted, report = emit_from_deck(deck, args.out, sparse=args.sparse)

    stats = emitted.stats
    print(f"дек:             {deck}")
    print(f"режим:           {'разреженный' if args.sparse else 'полный (lossless)'}")
    print(f"round-trip:      {report.format()}")
    print(f"дат:             {stats.n_dates}")
    print(f"блоков WCONPROD: {stats.n_wconprod_blocks}")
    print(f"блоков WCONINJE: {stats.n_wconinje_blocks}")
    print(f"блоков COMPDAT:  {stats.n_compdat_blocks}")
    print(f"блоков WPIMULT:  {stats.n_wpimult_blocks}")
    print(f"байт:            {stats.n_bytes}")
    print(f"файл:            {path}")
    print(f"content_hash:    {content_hash(path.read_bytes())}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
