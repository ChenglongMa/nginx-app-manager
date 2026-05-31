"""Configuration loading and runtime path helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from nam.models import ManagerConfig, NginxSettings

ENV_DEV_MODE = "NAM_DEV"
ENV_CONFIG = "NAM_CONFIG"


def default_config(*, development: bool = False, base_dir: Path | None = None) -> ManagerConfig:
    """Return a production or development default configuration."""
    if development:
        base = Path(base_dir) if base_dir is not None else Path.cwd() / "mock_nginx"
        data_dir = base / "var/lib/nginx-app-manager"
        return ManagerConfig(
            mode="development",
            data_dir=data_dir,
            backup_dir=base / "var/backups/nginx-app-manager",
            log_dir=base / "var/log/nginx-app-manager",
            apps_file=data_dir / "apps.yaml",
            nginx=NginxSettings(
                nginx_conf=base / "etc/nginx/nginx.conf",
                sites_available=base / "etc/nginx/sites-available",
                sites_enabled=base / "etc/nginx/sites-enabled",
            ),
        )

    return ManagerConfig()


def load_config(config_path: Path | None = None, *, development: bool = False) -> ManagerConfig:
    """Load configuration from YAML, falling back to production/development defaults."""
    env_path = os.environ.get(ENV_CONFIG)
    path = config_path or (Path(env_path) if env_path else None)
    dev_from_env = os.environ.get(ENV_DEV_MODE, "").lower() in {"1", "true", "yes", "on"}

    if path is None:
        return default_config(development=development or dev_from_env)

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    config = ManagerConfig.model_validate(data)
    if development and config.mode != "development":
        # Explicit --dev wins only when no development paths were supplied in the file.
        return default_config(development=True)
    return config


def save_config(config: ManagerConfig, path: Path) -> None:
    """Write a manager configuration file as YAML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = config.model_dump(mode="json")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def ensure_runtime_dirs(config: ManagerConfig, *, include_nginx_dirs: bool = False) -> None:
    """Create data, backup, log, and optionally Nginx mock/managed directories."""
    for directory in (config.data_dir, config.backup_dir, config.log_dir, config.apps_file.parent):
        directory.mkdir(parents=True, exist_ok=True)
    if include_nginx_dirs:
        config.nginx.sites_available.mkdir(parents=True, exist_ok=True)
        config.nginx.sites_enabled.mkdir(parents=True, exist_ok=True)
        config.nginx.nginx_conf.parent.mkdir(parents=True, exist_ok=True)
