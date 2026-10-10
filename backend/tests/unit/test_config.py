from app.core.config import Settings


def test_blank_optional_directory_environment_values_are_unset(tmp_path) -> None:
    env_file = tmp_path / "blank-paths.env"
    env_file.write_text("SOURCE_LIBRARY_DIR=\nPOD_LIBRARY_DIR=   \nPOD_PENDING_DIR=\n", encoding="utf-8")
    configured = Settings(_env_file=env_file)
    assert configured.source_library_dir is None
    assert configured.pod_library_dir is None
    assert configured.pod_pending_dir is None
