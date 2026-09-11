import json

from backend.application.runs import RunManifest, WorkflowStatus
from backend.contexts.showcase.application.run_summary import export_run_summary
import pytest

pytestmark = [pytest.mark.slow, pytest.mark.showcase]


def test_run_summary_is_a_ui_readable_copy_of_the_manifest(tmp_path) -> None:
    manifest = RunManifest("r1", WorkflowStatus.REJECTED, "abc", 12.0, 10.0, False)

    path = export_run_summary(manifest, tmp_path / "ui")

    assert json.loads(path.read_text(encoding="utf-8")) == manifest.as_dict()
