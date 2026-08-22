from __future__ import annotations

from backend.presentation.cli import selfcheck


def test_selfcheck_reports_current_backend_commands(capsys) -> None:
    assert selfcheck.main([]) == 0
    output = capsys.readouterr().out
    assert "backend.presentation.cli.npv" in output
    assert "Команды backend" in output
    assert "contracts" not in output
