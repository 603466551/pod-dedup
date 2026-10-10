from fastapi import APIRouter
from sqlalchemy import text

from app.core.db import SessionLocal
from app.core.app_logging import runtime_log_path
from app.core.config import settings
from app.core.runtime import worker_health
from app.indexing.catalog import SOURCE_FULL, SOURCE_PRINT, index_path, pod_index_path
from pathlib import Path
import torch
from app.services.settings import effective

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    database = "unavailable"
    config = None
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
            config = effective(session)
        database = "ready"
    except Exception:
        pass
    hub = Path(torch.hub.get_dir())
    visual = "READY" if (hub / "facebookresearch_dinov2_main").is_dir() and (hub / "checkpoints" / "dinov2_vits14_pretrain.pth").is_file() else "VISUAL_UNAVAILABLE"
    vlm = "READY" if config and config["vlm_enabled"] and config["vlm_base_url"] and config["vlm_model"] and config["vlm_api_key"] else "VLM_UNAVAILABLE"
    configured_directories = {
        name: ("NOT_CONFIGURED" if not raw else "READY" if Path(raw).is_dir() else "UNAVAILABLE")
        for name, raw in {
            "source_library": config.get("source_library_dir") if config else None,
            "pod_pending": config.get("pod_pending_dir") if config else None,
            "pod_library": config.get("pod_library_dir") if config else None,
        }.items()
    }
    faiss = {
        "SOURCE_FULL": "READY" if index_path(SOURCE_FULL).is_file() else "NOT_BUILT",
        "SOURCE_PRINT": "READY" if index_path(SOURCE_PRINT).is_file() else "NOT_BUILT",
        "POD_FULL": "READY" if pod_index_path().is_file() else "NOT_BUILT",
    }
    worker = worker_health()
    return {
        "api": "READY",
        "database": database,
        "worker": worker["status"],
        "worker_last_seen": worker["last_seen"],
        "visual": visual,
        "vlm": vlm,
        "faiss": faiss,
        "directories": configured_directories,
        "runtime_log": "READY" if runtime_log_path().is_file() else "PENDING",
        "log_retention_days": 14,
        "message": "视觉候选已就绪；复杂视觉自动删除默认关闭。",
    }
