"""Jinja2 template rendering for managed Nginx server blocks."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from nam.models import AppConfig, ManagerConfig


class TemplateService:
    """Render Nginx configuration files from packaged templates."""

    def __init__(self) -> None:
        template_dir = Path(__file__).resolve().parents[1] / "templates"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(default=False),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render_server_block(self, app: AppConfig, config: ManagerConfig) -> str:
        """Render the Nginx server block for one app/domain."""
        template = self.env.get_template("nginx_server.conf.j2")
        return template.render(
            app=app,
            access_log_path=config.log_dir / f"{app.domain}.access.log",
            error_log_path=config.log_dir / f"{app.domain}.error.log",
        )
