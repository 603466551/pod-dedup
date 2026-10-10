from pathlib import Path

import pytest

from app.models.tasks import AppSetting
from app.services.settings import update


class FakeSession:
    def __init__(self) -> None:
        self.row: AppSetting | None = None

    def get(self, _model, _key):
        return self.row

    def add(self, row: AppSetting) -> None:
        self.row = row

    def commit(self) -> None:
        pass


def test_locked_library_requires_path_and_persists_lock_state(tmp_path: Path) -> None:
    session = FakeSession()
    with pytest.raises(ValueError, match="历史源图库"):
        update(session, {"source_library_dir": None, "source_library_locked": True})

    source = str(tmp_path / "source-library")
    pod = str(tmp_path / "pod-library")
    saved = update(session, {
        "source_library_dir": source,
        "pod_library_dir": pod,
        "source_library_locked": True,
        "pod_library_locked": True,
    })

    assert saved["source_library_dir"] == source
    assert saved["pod_library_dir"] == pod
    assert saved["source_library_locked"] is True
    assert saved["pod_library_locked"] is True
