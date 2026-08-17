from __future__ import annotations

from pathlib import Path

from bridge.dataset import DatasetGenerator
from bridge.opm_deck import EmittedOpmDeck
from contracts import RunResult, RunStatus


def test_compaction_keeps_reloadable_summary_pair_and_rewrites_cache(
    tmp_path: Path,
) -> None:
    dataset_root = tmp_path / "dataset"
    run_root = dataset_root / "runs" / "run-1"
    output = run_root / "output"
    output.mkdir(parents=True)
    smspec = output / "MODEL_Z.SMSPEC"
    unsmry = output / "MODEL_Z.UNSMRY"
    heavy = output / "MODEL_Z.EGRID"
    log = run_root / "flow.log"
    for path, content in (
        (smspec, b"spec"),
        (unsmry, b"summary"),
        (heavy, b"heavy"),
        (log, b"log"),
    ):
        path.write_bytes(content)

    deck_root = dataset_root / "decks" / "scenario-1"
    deck_root.mkdir(parents=True)
    data_file = deck_root / "Model_Z.data"
    schedule_file = deck_root / "Model_Z_sch.inc"
    summary_file = deck_root / "Model_Z_summary.inc"
    for path in (data_file, schedule_file, summary_file):
        path.write_bytes(b"deck")

    generator = DatasetGenerator(
        tmp_path / "model",
        dataset_root,
        emitter=object(),  # type: ignore[arg-type]
    )
    result = RunResult(
        run_id="run-1",
        status=RunStatus.OK,
        deck_hash="deck",
        canonical_schedule_hash="schedule",
        summary_hash="summary",
        artifacts=tuple(str(path) for path in (smspec, unsmry, heavy, log)),
        wallclock_seconds=1.0,
        message="OK",
    )
    deck = EmittedOpmDeck(
        data_file=data_file,
        schedule_file=schedule_file,
        summary_file=summary_file,
        summary_plan=None,  # type: ignore[arg-type]
        input_files=(data_file, schedule_file, summary_file),
        content_hash_opm="content",
    )

    compacted = generator._compact_verified_response(
        result, deck, response_hash="a" * 64
    )

    assert set(compacted.artifacts) == {str(smspec), str(unsmry)}
    assert smspec.is_file()
    assert unsmry.is_file()
    assert not heavy.exists()
    assert not log.exists()
    assert not deck_root.exists()
    assert generator.cache.lookup("deck", "schedule", "summary") == compacted
