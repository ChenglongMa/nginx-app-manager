from __future__ import annotations

from nam.config import default_config
from nam.models import AppConfig
from nam.services.app_service import AppService


def test_add_enable_disable_and_delete_app_in_development_mode(tmp_path) -> None:
    config = default_config(development=True, base_dir=tmp_path)
    service = AppService(config)

    app = AppConfig(domain="app1.example.com", upstream_port=8501, description="Streamlit lab")
    add_result = service.add_app(app, enable=True)

    available = service.generated_config_path("app1.example.com")
    enabled = config.nginx.sites_enabled / "app1.example.com.conf"
    assert add_result.ok
    assert available.exists()
    assert enabled.is_symlink()
    assert "proxy_pass http://127.0.0.1:8501;" in available.read_text(encoding="utf-8")
    assert service.get_app("app1.example.com") is not None

    disable_result = service.disable_app("app1.example.com")
    assert disable_result.ok
    assert not enabled.exists()
    assert service.get_app("app1.example.com").enabled is False  # type: ignore[union-attr]

    delete_result = service.delete_app("app1.example.com", purge=True)
    assert delete_result.ok
    assert not available.exists()
    assert service.get_app("app1.example.com") is None


def test_dry_run_does_not_write_state_or_files(tmp_path) -> None:
    config = default_config(development=True, base_dir=tmp_path)
    service = AppService(config)
    app = AppConfig(domain="demo.example.com", upstream_port=8502)

    result = service.add_app(app, enable=True, dry_run=True)

    assert result.ok
    assert "rendered_config" in result.details
    assert not config.apps_file.exists()
    assert not service.generated_config_path("demo.example.com").exists()
