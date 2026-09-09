from __future__ import annotations

import json
from pathlib import Path

from backend.application.runs import RunProvenance, RunRequest, RunWorkflow
from backend.core.contracts import Schedule
from backend.domain.schedule import parse_schedule
from backend.domain.schedule.build import build_schedule
from backend.presentation.cli import selfcheck

MONTHS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)
SYNTHETIC_STEPS = 4
CLAIMED_NPV = 11_873_122_324.91


def test_selfcheck_reports_current_backend_commands(capsys) -> None:
    assert selfcheck.main([]) == 0
    output = capsys.readouterr().out
    assert "backend.presentation.cli.npv" in output
    assert "Команды backend" in output
    assert "contracts" not in output


def synthetic_schedule_include() -> bytes:
    parts = [
        b"RPTSCHED\n 'WELLS=1' 'SUMMARY=1' 'RESTART=0' /\n\n"
        b"WELSPECS\n 'W1' 'GROUP' 23 17 1* 'OIL' /\n"
        b" 'W2' 'GROUP' 47 40 1* 'OIL' /\n/\n\n"
    ]
    for step in range(SYNTHETIC_STEPS + 1):
        month = MONTHS[step % 12]
        year = 2007 + step // 12
        parts.append(f"DATES\n 01 {month} {year} /\n/\n\n".encode())
        if step < SYNTHETIC_STEPS:
            parts.append(
                f"WCONPROD\n 'W1' 'OPEN' 'LRAT' 1* 1* 1* {100.0 + step} 1* 50 1* 1* /\n/\n\n"
                f"WCONINJE\n 'W2' 'WATER' 'OPEN' 'RATE' {200.0 + step} 1* 300 1* 1* /\n/\n\n".encode()
            )
    return b"".join(parts)


def synthetic_model_dir(root: Path) -> Path:
    model_dir = root / "Model_Z"
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "Model_Z_sch.inc").write_bytes(synthetic_schedule_include())
    (model_dir / "Model_Z.data").write_bytes(
        b"RUNSPEC\nDIMENS\n 10 10 3 /\nSCHEDULE\nINCLUDE\n 'Model_Z_sch.inc' /\n"
    )
    return model_dir


def emittable_schedule() -> Schedule:
    raw = synthetic_schedule_include()
    return build_schedule(
        parse_schedule(raw), raw, model="Model_Z", provenance="synthetic"
    )


class FakeFinalNpv:
    npv_methodology = CLAIMED_NPV
    source_run_id = "opm-run-1"
    source_response_hash = "1" * 64
    economics_config_hash = "2" * 64
    methodology_version_hash = "3" * 64


class FakeOpmRun:
    deck_hash = "4" * 64


class FakeVerification:
    sound = True
    npv_methodology = CLAIMED_NPV
    final_npv = FakeFinalNpv()
    opm_run = FakeOpmRun()


def build_submission(tmp_path: Path) -> Path:
    workflow = RunWorkflow(tmp_path / "runs")
    workflow.verify(
        RunRequest(
            "submittable",
            emittable_schedule(),
            predicted_npv=12.0,
            provenance=RunProvenance(
                constraints_hash="b" * 64,
                deck_hash="c" * 64,
                opm_image="openporousmedia/opmreleases:latest",
                git_commit="e" * 40,
            ),
        ),
        lambda _schedule, _opm: FakeVerification(),
    )
    report = workflow.submit("submittable", synthetic_model_dir(tmp_path / "model"))
    return report.directory


def test_a_genuine_submission_package_passes(tmp_path, capsys) -> None:
    directory = build_submission(tmp_path)

    assert selfcheck.main(["--submission", str(directory)]) == 0

    output = capsys.readouterr().out
    assert "канонический хеш расписания" in output
    assert "хеш содержимого файла" in output
    assert "ПРОВАЛ" not in output


def test_one_flipped_byte_in_the_include_fails(tmp_path, capsys) -> None:
    directory = build_submission(tmp_path)
    schedule_path = directory / "wells_schedule.inc"
    raw = bytearray(schedule_path.read_bytes())
    position = raw.index(b"100.0") + 4
    raw[position] = raw[position] + 1
    schedule_path.write_bytes(bytes(raw))

    assert selfcheck.main(["--submission", str(directory)]) != 0

    output = capsys.readouterr().out
    assert "ПРОВАЛ" in output
    assert "Сдавать нельзя" in output


def test_a_single_whitespace_byte_appended_to_the_include_fails(tmp_path) -> None:
    directory = build_submission(tmp_path)
    schedule_path = directory / "wells_schedule.inc"
    schedule_path.write_bytes(schedule_path.read_bytes() + b" ")

    assert selfcheck.main(["--submission", str(directory)]) != 0


def test_a_tampered_claimed_hash_fails(tmp_path, capsys) -> None:
    directory = build_submission(tmp_path)
    claimed_path = directory / "claimed_npv.json"
    document = json.loads(claimed_path.read_text(encoding="utf-8"))
    document["canonical_schedule_hash"] = "0" * 64
    claimed_path.write_text(json.dumps(document, indent=2), encoding="utf-8")

    assert selfcheck.main(["--submission", str(directory)]) != 0

    output = capsys.readouterr().out
    assert "ПРОВАЛ" in output
    assert "0" * 64 in output


def test_a_missing_claimed_npv_is_a_refusal_not_a_skip(tmp_path, capsys) -> None:
    directory = build_submission(tmp_path)
    (directory / "claimed_npv.json").unlink()

    assert selfcheck.main(["--submission", str(directory)]) != 0

    output = capsys.readouterr().out
    assert "ОТКАЗ" in output
    assert "claimed_npv.json" in output
    assert "ОК" not in output


def test_an_invalid_claimed_npv_is_a_refusal(tmp_path, capsys) -> None:
    directory = build_submission(tmp_path)
    (directory / "claimed_npv.json").write_text("{not json", encoding="utf-8")

    assert selfcheck.main(["--submission", str(directory)]) != 0

    output = capsys.readouterr().out
    assert "ОТКАЗ" in output


def test_a_claimed_npv_without_the_hash_fields_is_a_refusal(tmp_path, capsys) -> None:
    directory = build_submission(tmp_path)
    (directory / "claimed_npv.json").write_text(
        json.dumps({"claimed_npv_rub": CLAIMED_NPV}), encoding="utf-8"
    )

    assert selfcheck.main(["--submission", str(directory)]) != 0

    output = capsys.readouterr().out
    assert "ОТКАЗ" in output
    assert "canonical_schedule_hash" in output


def test_a_missing_include_is_a_refusal(tmp_path, capsys) -> None:
    directory = build_submission(tmp_path)
    (directory / "wells_schedule.inc").unlink()

    assert selfcheck.main(["--submission", str(directory)]) != 0

    output = capsys.readouterr().out
    assert "ОТКАЗ" in output


def test_a_missing_submission_directory_is_a_refusal(tmp_path, capsys) -> None:
    assert selfcheck.main(["--submission", str(tmp_path / "absent")]) != 0

    assert "ОТКАЗ" in capsys.readouterr().out
