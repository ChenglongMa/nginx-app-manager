"""Managed app state and orchestration around NginxService."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from nam.config import ensure_runtime_dirs
from nam.models import AppConfig, AppState, ManagerConfig, OperationResult
from nam.services.backup_service import BackupService
from nam.services.nginx_service import NginxService
from nam.utils.paths import can_write_path


class AppService:
    """CRUD service for app metadata and generated Nginx configs."""

    def __init__(
        self,
        config: ManagerConfig,
        *,
        nginx_service: NginxService | None = None,
        backup_service: BackupService | None = None,
    ) -> None:
        self.config = config
        self.backup_service = backup_service or BackupService(config)
        self.nginx = nginx_service or NginxService(config, backup_service=self.backup_service)

    def load_state(self) -> AppState:
        """Load app state from disk."""
        if not self.config.apps_file.exists():
            return AppState()
        raw = yaml.safe_load(self.config.apps_file.read_text(encoding="utf-8")) or {}
        return AppState.model_validate(raw)

    def save_state(self, state: AppState) -> None:
        """Persist app state to disk."""
        ensure_runtime_dirs(self.config)
        data = state.model_dump(mode="json")
        self.config.apps_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def list_apps(self) -> list[AppConfig]:
        """Return managed apps sorted by domain."""
        return sorted(self.load_state().apps.values(), key=lambda app: app.domain)

    def get_app(self, domain: str) -> AppConfig | None:
        """Return one app by domain, if present."""
        normalized = AppConfig(domain=domain, upstream_port=1).domain
        return self.load_state().apps.get(normalized)

    def config_paths(self) -> dict[str, str]:
        """Return sites-available paths keyed by domain for the current state."""
        return {app.domain: str(self.nginx.available_path(app.domain)) for app in self.list_apps()}

    def state_permission_error(self) -> OperationResult | None:
        """Return a friendly error if the state file cannot be written."""
        if self.config.mode == "development" or can_write_path(self.config.apps_file):
            return None
        return OperationResult(
            ok=False,
            message="State file write permission required. Re-run this command with sudo.",
            details={"path": str(self.config.apps_file)},
        )

    def find_warnings(self, app: AppConfig, *, ignore_domain: str | None = None) -> list[str]:
        """Return non-fatal warnings such as duplicate upstream targets."""
        warnings: list[str] = []
        for existing in self.list_apps():
            if ignore_domain and existing.domain == ignore_domain:
                continue
            if (
                existing.upstream_host == app.upstream_host
                and existing.upstream_port == app.upstream_port
            ):
                warnings.append(
                    f"{existing.domain} already proxies to {app.upstream_host}:{app.upstream_port}."
                )
            if existing.domain == app.domain:
                warnings.append(f"{app.domain} already exists.")
        return warnings

    def add_app(
        self,
        app: AppConfig,
        *,
        enable: bool = False,
        dry_run: bool = False,
    ) -> OperationResult:
        """Add a new app, write its config, and optionally enable it."""
        state = self.load_state()
        if app.domain in state.apps:
            return OperationResult(ok=False, message=f"App already exists: {app.domain}")
        permission_error = self.state_permission_error()
        if permission_error is not None and not dry_run:
            return permission_error
        app.enabled = enable
        app.touch()
        warnings = self.find_warnings(app)
        result = self.nginx.write_server_block(app, enable=enable, dry_run=dry_run)
        result.details["warnings"] = warnings
        if result.ok and not dry_run:
            state.apps[app.domain] = app
            self.save_state(state)
            logger.info("Added app {}", app.domain)
        return result

    def update_app(
        self,
        domain: str,
        *,
        dry_run: bool = False,
        **updates: Any,
    ) -> OperationResult:
        """Update an app and re-apply its Nginx config."""
        state = self.load_state()
        current = state.apps.get(AppConfig(domain=domain, upstream_port=1).domain)
        if current is None:
            return OperationResult(ok=False, message=f"Unknown app: {domain}")
        permission_error = self.state_permission_error()
        if permission_error is not None and not dry_run:
            return permission_error

        data = current.model_dump()
        data.update({key: value for key, value in updates.items() if value is not None})
        updated = AppConfig.model_validate(data)
        updated.touch()
        warnings = self.find_warnings(updated, ignore_domain=current.domain)
        result = self.nginx.write_server_block(updated, enable=updated.enabled, dry_run=dry_run)
        result.details["warnings"] = warnings
        if result.ok and not dry_run:
            if updated.domain != current.domain:
                del state.apps[current.domain]
            state.apps[updated.domain] = updated
            self.save_state(state)
            logger.info("Updated app {}", updated.domain)
        return result

    def enable_app(self, domain: str, *, dry_run: bool = False) -> OperationResult:
        """Enable an app by linking it into sites-enabled."""
        state = self.load_state()
        normalized = AppConfig(domain=domain, upstream_port=1).domain
        app = state.apps.get(normalized)
        if app is None:
            return OperationResult(ok=False, message=f"Unknown app: {domain}")
        permission_error = self.state_permission_error()
        if permission_error is not None and not dry_run:
            return permission_error
        app.enabled = True
        app.touch()
        result = self.nginx.write_server_block(app, enable=True, dry_run=dry_run)
        if result.ok and not dry_run:
            state.apps[app.domain] = app
            self.save_state(state)
            logger.info("Enabled app {}", app.domain)
        return result

    def disable_app(self, domain: str, *, dry_run: bool = False) -> OperationResult:
        """Disable an app by removing its sites-enabled symlink."""
        state = self.load_state()
        normalized = AppConfig(domain=domain, upstream_port=1).domain
        app = state.apps.get(normalized)
        if app is None:
            return OperationResult(ok=False, message=f"Unknown app: {domain}")
        permission_error = self.state_permission_error()
        if permission_error is not None and not dry_run:
            return permission_error
        result = self.nginx.disable(app.domain, dry_run=dry_run)
        if result.ok and not dry_run:
            app.enabled = False
            app.touch()
            state.apps[app.domain] = app
            self.save_state(state)
            logger.info("Disabled app {}", app.domain)
        return result

    def delete_app(
        self,
        domain: str,
        *,
        purge: bool = False,
        dry_run: bool = False,
    ) -> OperationResult:
        """Disable and remove app metadata. With purge, also delete generated config."""
        state = self.load_state()
        normalized = AppConfig(domain=domain, upstream_port=1).domain
        app = state.apps.get(normalized)
        if app is None:
            return OperationResult(ok=False, message=f"Unknown app: {domain}")
        permission_error = self.state_permission_error()
        if permission_error is not None and not dry_run:
            return permission_error

        disable_result = self.nginx.disable(app.domain, dry_run=dry_run)
        details: dict[str, object] = {"disable": disable_result.model_dump(mode="json")}
        if not disable_result.ok:
            return OperationResult(ok=False, message=disable_result.message, details=details)

        if purge:
            purge_result = self.nginx.remove_available(app.domain, dry_run=dry_run)
            details["purge"] = purge_result.model_dump(mode="json")
            if not purge_result.ok:
                return OperationResult(ok=False, message=purge_result.message, details=details)

        if not dry_run:
            del state.apps[app.domain]
            self.save_state(state)
            logger.info("Deleted app {} (purge={})", app.domain, purge)
        return OperationResult(ok=True, message="App deleted from manager state.", details=details)

    def describe_app(self, domain: str) -> dict[str, object] | None:
        """Return detailed app information for CLI/TUI display."""
        app = self.get_app(domain)
        if app is None:
            return None
        available = self.nginx.available_path(app.domain)
        enabled = self.nginx.enabled_path(app.domain)
        latest_backup = self.backup_service.latest_backup(domain=app.domain)
        test = self.nginx.test_config()
        risks: list[str] = []
        if available.exists() and not self.nginx.is_managed_config(available):
            risks.append("sites-available file exists but is not managed by this tool.")
        if enabled.exists() and not enabled.is_symlink():
            risks.append("sites-enabled path exists but is not a symlink.")
        return {
            "app": app.model_dump(mode="json"),
            "available_path": str(available),
            "enabled_path": str(enabled),
            "available_exists": available.exists(),
            "enabled_exists": enabled.exists() or enabled.is_symlink(),
            "managed_config": self.nginx.is_managed_config(available),
            "latest_backup": str(latest_backup.backup_path) if latest_backup else None,
            "nginx_test": test.model_dump(mode="json"),
            "risks": risks,
        }

    def preview_config(self, app: AppConfig) -> str:
        """Render an app config without writing files."""
        return self.nginx.render(app)

    def generated_config_path(self, domain: str) -> Path:
        """Return generated config path for a domain."""
        return self.nginx.available_path(domain)
