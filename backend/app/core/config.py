from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    # All PowerShell entry points run from backend/, while credentials are kept
    # in the repository-root .env (which is ignored by Git).
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_timezone: str = "Asia/Shanghai"
    database_url: str = "mysql+pymysql://pod_user:CHANGE_ME@127.0.0.1:3306/pod_dedup?charset=utf8mb4"
    data_dir: Path = PROJECT_ROOT / "data"
    source_library_dir: Path | None = None
    pod_library_dir: Path | None = None
    pod_pending_dir: Path | None = None
    source_library_locked: bool = False
    pod_library_locked: bool = False
    worker_concurrency: int = Field(default=1, ge=1, le=4)
    source_visual_auto_delete: bool = False
    pod_visual_auto_delete: bool = False
    source_exact_auto_delete: bool = True
    pod_exact_auto_delete: bool = True
    vlm_enabled: bool = False
    vlm_base_url: str | None = None
    vlm_model: str | None = None
    vlm_api_key: str | None = None
    vlm_max_calls_per_task: int = Field(default=100, ge=0, le=10000)
    source_visual_rule_validated: bool = False
    default_ratio: str = "3x4"
    embed_model_id: str = "facebook/dinov2_vits14"
    retrieval_top_k: int = Field(default=20, ge=1, le=100)
    # This only limits review-candidate volume.  It is never a duplicate or
    # deletion threshold; a returned candidate still requires human review.
    retrieval_candidate_min_similarity: float = Field(default=0.85, ge=-1, le=1)
    ratio_rel_tolerance: float = Field(default=0.02, ge=0, le=0.2)

    @field_validator("source_library_dir", "pod_library_dir", "pod_pending_dir", mode="before")
    @classmethod
    def blank_paths_are_unset(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


settings = Settings()
