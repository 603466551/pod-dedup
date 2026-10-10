"""OpenAI Chat Completions-compatible, auditable image comparison client."""

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.images import VlmCall
from app.models.tasks import Task
from app.services.settings import effective


class VlmUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ComparisonResult:
    verdict: str
    print_region_valid: bool
    same_design_confidence: float
    new_important_details: bool
    quality_delta: str
    rationale: str

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _image_part(path: Path) -> dict:
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower())
    if not mime or not path.is_file():
        raise VlmUnavailableError("VLM图片不存在或格式不受支持")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}


def _parse(payload: dict) -> ComparisonResult:
    try:
        content = payload["choices"][0]["message"]["content"]
        parsed = json.loads(content) if isinstance(content, str) else content
        result = ComparisonResult(
            verdict=str(parsed["verdict"]), print_region_valid=bool(parsed["print_region_valid"]),
            same_design_confidence=float(parsed["same_design_confidence"]), new_important_details=bool(parsed["new_important_details"]),
            quality_delta=str(parsed["quality_delta"]), rationale=str(parsed["rationale"]),
        )
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise VlmUnavailableError("VLM未返回可校验的结构化比较结果") from error
    if result.verdict not in {"same", "different", "same_with_new_details", "uncertain"} or not 0 <= result.same_design_confidence <= 1:
        raise VlmUnavailableError("VLM结构化比较结果字段不合法")
    return result


def _task_vlm_config(session: Session, task_id: int) -> dict:
    """Freeze non-secret VLM choices at task creation time.

    The API key deliberately remains outside task snapshots and is read only
    from protected current settings while issuing the request.
    """
    config = effective(session)
    task = session.get(Task, task_id)
    if task is not None:
        for name in ("vlm_enabled", "vlm_base_url", "vlm_model", "vlm_max_calls_per_task"):
            if name in task.settings_snapshot:
                config[name] = task.settings_snapshot[name]
    return config


def compare(session: Session, *, task_id: int, pair_type: str, new_path: Path, match_path: Path, pair_id: int | None = None, transport=urlopen) -> ComparisonResult:
    config = _task_vlm_config(session, task_id)
    if not config["vlm_enabled"] or not config["vlm_base_url"] or not config["vlm_model"] or not config["vlm_api_key"]:
        raise VlmUnavailableError("VLM未配置或未启用")
    used = session.scalar(select(func.count(VlmCall.id)).where(VlmCall.task_id == task_id, VlmCall.status == "SUCCEEDED")) or 0
    if used >= config.get("vlm_max_calls_per_task", settings.vlm_max_calls_per_task):
        raise VlmUnavailableError("VLM任务调用预算已耗尽")
    audit = VlmCall(task_id=task_id, pair_id=pair_id, provider="openai-compatible", model=config["vlm_model"], status="STARTED", request_metadata={"pair_type": pair_type, "new_filename": new_path.name, "match_filename": match_path.name})
    session.add(audit); session.commit()
    prompt = "比较两张POD图片的可印刷设计。严格输出JSON，字段为 verdict(same|different|same_with_new_details|uncertain)、print_region_valid(boolean)、same_design_confidence(0到1)、new_important_details(boolean)、quality_delta(string)、rationale(string)。不要把相似主题当同一设计；文字、关键元素或布局不同应说明。"
    body = {"model": config["vlm_model"], "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}, _image_part(new_path), _image_part(match_path)]}], "response_format": {"type": "json_object"}, "temperature": 0}
    request = Request(config["vlm_base_url"].rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"), headers={"Authorization": f"Bearer {config['vlm_api_key']}", "Content-Type": "application/json"}, method="POST")
    try:
        with transport(request, timeout=60) as response:
            result = _parse(json.loads(response.read().decode("utf-8")))
        audit.status = "SUCCEEDED"; audit.response_json = result.as_dict(); session.commit()
        return result
    except (HTTPError, URLError, OSError, json.JSONDecodeError, VlmUnavailableError) as error:
        audit.status = "FAILED"; audit.error_code = "VLM_REQUEST_FAILED"; audit.error_message = str(error)[:2000]; session.commit()
        raise VlmUnavailableError("VLM调用失败，已保守降级") from error
