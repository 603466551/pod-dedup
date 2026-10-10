from pathlib import Path
import sys

from fastapi import APIRouter, Body, HTTPException, Query

from app.core.config import settings
from app.storage.paths import PathValidationError, canonical_path, is_same_or_child

router = APIRouter(prefix="/fs", tags=["filesystem"])


def allowed_roots() -> list[Path]:
    return [path for path in [settings.source_library_dir, settings.pod_library_dir, settings.pod_pending_dir] if path]


def _show_windows_directory_dialog(initial_path: str | None) -> str:
    """Open the native dialog on the same Windows desktop as the API process."""
    import tkinter as tk
    from tkinter import filedialog

    initial_directory = ""
    if initial_path:
        try:
            candidate = canonical_path(initial_path)
            if candidate.is_dir():
                initial_directory = str(candidate)
        except PathValidationError:
            pass
    root = tk.Tk()
    try:
        root.withdraw()
        root.attributes("-topmost", True)
        return filedialog.askdirectory(parent=root, initialdir=initial_directory, mustexist=True)
    finally:
        root.destroy()


@router.post("/choose-directory")
def choose_directory(initial_path: str | None = Body(default=None, embed=True)):
    """Return a directory selected through the local Windows shell dialog."""
    if sys.platform != "win32":
        raise HTTPException(status_code=501, detail={"code": "NATIVE_DIALOG_UNAVAILABLE", "message": "原生文件夹选择仅支持 Windows 本机运行", "details": {}})
    try:
        selected = _show_windows_directory_dialog(initial_path)
    except Exception as error:
        raise HTTPException(status_code=503, detail={"code": "NATIVE_DIALOG_UNAVAILABLE", "message": "无法打开 Windows 文件夹选择器，请改为手动输入路径", "details": {}}) from error
    if not selected:
        return {"path": None}
    try:
        return {"path": str(canonical_path(selected))}
    except PathValidationError as error:
        raise HTTPException(status_code=422, detail={"code": "PATH_RISK", "message": str(error), "details": {}}) from error


@router.get("/directories")
def directories(parent: str = Query(...)):
    try:
        requested = canonical_path(parent)
    except PathValidationError as error:
        raise HTTPException(status_code=422, detail={"code": "PATH_RISK", "message": str(error), "details": {}}) from error
    roots = allowed_roots()
    if not roots or not any(is_same_or_child(requested, root.resolve(strict=False)) for root in roots):
        raise HTTPException(status_code=403, detail={"code": "PATH_NOT_ALLOWED", "message": "目录不在已配置的允许根路径内", "details": {}})
    if not requested.is_dir():
        raise HTTPException(status_code=404, detail={"code": "DIRECTORY_NOT_FOUND", "message": "目录不存在或不可访问", "details": {}})
    return {"path": str(requested), "directories": [entry.name for entry in requested.iterdir() if entry.is_dir()]}
