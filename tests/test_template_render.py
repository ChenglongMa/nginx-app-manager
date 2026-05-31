from __future__ import annotations

from nam.config import default_config
from nam.models import AppConfig
from nam.services.template_service import TemplateService


def test_template_render_streamlit_friendly_proxy() -> None:
    config = default_config(development=True)
    app = AppConfig(domain="app1.example.com", upstream_port=8501)

    rendered = TemplateService().render_server_block(app, config)

    assert "server_name app1.example.com;" in rendered
    assert "listen 8080;" in rendered
    assert "proxy_pass http://127.0.0.1:8501;" in rendered
    assert "proxy_set_header Upgrade $http_upgrade;" in rendered
    assert "proxy_buffering off;" in rendered
    assert "managed_by: nginx-app-manager" in rendered
