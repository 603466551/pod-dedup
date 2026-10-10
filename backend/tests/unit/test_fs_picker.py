from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api import fs
from app.main import app


def test_choose_directory_returns_selected_absolute_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fs, "_show_windows_directory_dialog", lambda _initial: str(tmp_path))

    assert fs.choose_directory(str(tmp_path)) == {"path": str(tmp_path.resolve())}


def test_choose_directory_returns_null_when_user_cancels(monkeypatch) -> None:
    monkeypatch.setattr(fs, "_show_windows_directory_dialog", lambda _initial: "")

    assert fs.choose_directory(None) == {"path": None}


def test_choose_directory_is_exposed_as_an_api_route(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fs, "_show_windows_directory_dialog", lambda _initial: str(tmp_path))

    with TestClient(app) as client:
        response = client.post("/api/v1/fs/choose-directory", json={"initial_path": str(tmp_path)})

    assert response.status_code == 200
    assert response.json() == {"path": str(tmp_path.resolve())}


def test_choose_directory_returns_safe_error_when_dialog_is_unavailable(monkeypatch) -> None:
    def unavailable(_initial: str | None) -> str:
        raise RuntimeError("no desktop session")

    monkeypatch.setattr(fs, "_show_windows_directory_dialog", unavailable)

    with pytest.raises(HTTPException) as error:
        fs.choose_directory(None)

    assert error.value.status_code == 503
    assert error.value.detail["code"] == "NATIVE_DIALOG_UNAVAILABLE"
