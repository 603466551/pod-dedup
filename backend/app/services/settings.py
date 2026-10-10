"""Persisted settings are applied only while creating a new task."""

from typing import Any
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.tasks import AppSetting
from app.services.ratios import DEFAULT_RATIO_CODES, ratio_codes

SETTINGS_KEY = "system"
SECRET_KEYS = {"vlm_api_key"}
ALLOWED_KEYS = {
    "source_library_dir", "pod_library_dir", "pod_pending_dir", "source_library_locked", "pod_library_locked", "retrieval_top_k",
    "retrieval_candidate_min_similarity", "source_visual_auto_delete", "pod_visual_auto_delete",
    "source_visual_rule_validated", "app_timezone", "ratio_rel_tolerance", "vlm_enabled",
    "vlm_base_url", "vlm_model", "vlm_api_key", "vlm_max_calls_per_task", "production_ratio_codes",
}


def defaults() -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in ALLOWED_KEYS:
        if key == "production_ratio_codes":
            values[key] = DEFAULT_RATIO_CODES
            continue
        value = getattr(settings, key)
        values[key] = str(value) if isinstance(value, Path) else value
    return values


def stored(session: Session) -> dict[str, Any]:
    row = session.get(AppSetting, SETTINGS_KEY)
    return dict(row.value_json) if row else {}


def effective(session: Session) -> dict[str, Any]:
    return {**defaults(), **stored(session)}


def public(session: Session) -> dict[str, Any]:
    values = effective(session)
    for key in SECRET_KEYS:
        if values.get(key):
            values[key] = "***已配置***"
        else:
            values[key] = None
    return values


def update(session: Session, values: dict[str, Any]) -> dict[str, Any]:
    unknown = set(values) - ALLOWED_KEYS
    if unknown:
        raise ValueError(f"不支持的设置项：{', '.join(sorted(unknown))}")
    current = stored(session)
    future = {**defaults(), **current, **values}
    if future.get("source_library_locked") and not future.get("source_library_dir"):
        raise ValueError("锁定历史源图库前，必须先设置其绝对路径")
    if future.get("pod_library_locked") and not future.get("pod_library_dir"):
        raise ValueError("锁定历史POD图库前，必须先设置其绝对路径")
    if future.get("source_visual_auto_delete") and not future.get("source_visual_rule_validated"):
        raise ValueError("启用来源视觉自动删除前，必须先确认该规则已通过实际审核样本验证")
    if "app_timezone" in values:
        try:
            ZoneInfo(values["app_timezone"])
        except (TypeError, ZoneInfoNotFoundError) as error:
            raise ValueError("时区必须是有效的 IANA 时区名称") from error
    if "production_ratio_codes" in values:
        values["production_ratio_codes"] = ratio_codes(values["production_ratio_codes"])
    for key, value in values.items():
        if key in SECRET_KEYS and value in (None, ""):
            continue
        current[key] = value
    row = session.get(AppSetting, SETTINGS_KEY)
    if row is None:
        row = AppSetting(key=SETTINGS_KEY, value_json=current)
        session.add(row)
    else:
        row.value_json = current
    session.commit()
    return public(session)
