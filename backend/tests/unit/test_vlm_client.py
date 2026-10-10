import json
import uuid

from PIL import Image

from app.core.config import settings
from app.vlm.client import compare


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None


def test_vlm_sends_two_images_and_validates_json(tmp_path, monkeypatch) -> None:
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    Image.new("RGB", (20, 20), "red").save(first)
    Image.new("RGB", (20, 20), "blue").save(second)
    monkeypatch.setattr(settings, "vlm_enabled", True)
    monkeypatch.setattr(settings, "vlm_base_url", "https://example.invalid/v1")
    monkeypatch.setattr(settings, "vlm_model", "test-vision")
    monkeypatch.setattr(settings, "vlm_api_key", "not-logged")
    seen: dict = {}

    def transport(request, timeout):
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"choices": [{"message": {"content": json.dumps({"verdict": "different", "print_region_valid": True, "same_design_confidence": 0.2, "new_important_details": True, "quality_delta": "none", "rationale": "文字不同"})}}]})

    class Session:
        def get(self, _model, _key): return None
        def add(self, _value): pass
        def commit(self): pass
        def scalar(self, _value): return 0

    result = compare(Session(), task_id=1, pair_id=2, pair_type="POD_POD", new_path=first, match_path=second, transport=transport)
    assert result.verdict == "different"
    content = seen["body"]["messages"][0]["content"]
    assert len([part for part in content if part["type"] == "image_url"]) == 2


def test_vlm_uses_nonsecret_settings_frozen_on_its_task(tmp_path, monkeypatch) -> None:
    first, second = tmp_path / "first.png", tmp_path / "second.png"
    Image.new("RGB", (20, 20), "red").save(first)
    Image.new("RGB", (20, 20), "blue").save(second)
    from app.models.tasks import Task

    class Session:
        def __init__(self):
            self.task = Task(id=1, type="SOURCE_DEDUP", status="SCANNING", idempotency_key=str(uuid.uuid4()), settings_snapshot={"vlm_enabled": True, "vlm_base_url": "https://frozen.invalid/v1", "vlm_model": "frozen-vision"}, counters={}, warnings=[])
        def get(self, model, key): return self.task if model is Task and key == 1 else None
        def scalar(self, _value): return 0
        def add(self, _value): pass
        def commit(self): pass

    seen: dict = {}
    def transport(request, timeout):
        seen["url"] = request.full_url
        seen["model"] = json.loads(request.data.decode("utf-8"))["model"]
        return FakeResponse({"choices": [{"message": {"content": json.dumps({"verdict": "different", "print_region_valid": True, "same_design_confidence": 0.1, "new_important_details": True, "quality_delta": "none", "rationale": "different"})}}]})

    monkeypatch.setattr("app.vlm.client.effective", lambda _session: {"vlm_enabled": False, "vlm_base_url": "https://changed.invalid/v1", "vlm_model": "changed-vision", "vlm_api_key": "test-key"})
    result = compare(Session(), task_id=1, pair_type="SOURCE_SOURCE", new_path=first, match_path=second, transport=transport)
    assert result.verdict == "different"
    assert seen == {"url": "https://frozen.invalid/v1/chat/completions", "model": "frozen-vision"}
