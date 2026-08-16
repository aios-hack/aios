from pathlib import Path
from typing import Iterator

def _expand(fields: list[str]) -> list[str | None]:
    out: list[str | None] = []
    for field in fields:
        if field.endswith("*") and field[:-1].isdigit():
            out.extend([None] * int(field[:-1]))
        else:
            out.append(field.strip("'\""))
    return out

def _iter_records(path: Path, keyword: str) -> Iterator[list[str | None]]:
    active = False
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("--", 1)[0].strip()
        if not line:
            continue
        if not active:
            if line.upper() == keyword:
                active = True
            continue
        if line == "/":
            active = False
            continue
        record = line.rstrip("/").strip()
        if not record:
            active = False
            continue
        yield _expand(record.split())

def _field(record: list[str | None], index: int, keyword: str) -> str:
    value = record[index]
    if value is None:
        raise ValueError(f"{keyword}: required field {index} is defaulted in record {record}")
    return value

def load_wellheads(path: str | Path) -> dict[str, tuple[int, int]]:
    deck = Path(path)
    heads: dict[str, tuple[int, int]] = {}
    for record in _iter_records(deck, "WELSPECS"):
        well = _field(record, 0, "WELSPECS")
        head = (int(_field(record, 2, "WELSPECS")), int(_field(record, 3, "WELSPECS")))
        if well in heads and heads[well] != head:
            raise ValueError(f"WELSPECS: conflicting head for well {well}: {heads[well]} vs {head}")
        heads[well] = head
    return heads

def load_completions(path: str | Path) -> dict[str, list[tuple[int, int, int, int]]]:
    deck = Path(path)
    completions: dict[str, list[tuple[int, int, int, int]]] = {}
    for record in _iter_records(deck, "COMPDAT"):
        well = _field(record, 0, "COMPDAT")
        cell = (
            int(_field(record, 1, "COMPDAT")),
            int(_field(record, 2, "COMPDAT")),
            int(_field(record, 3, "COMPDAT")),
            int(_field(record, 4, "COMPDAT")),
        )
        completions.setdefault(well, []).append(cell)
    return completions
