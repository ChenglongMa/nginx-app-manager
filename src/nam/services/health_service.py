"""Health checks for Nginx, systemd, permissions, and manager paths."""

from __future__ import annotations

from nam.models import HealthCheckItem, HealthReport, ManagerConfig
from nam.services.nginx_service import NginxService
from nam.services.system_service import SystemService
from nam.utils.paths import can_write_path, is_root
from nam.utils.shell import command_exists


class HealthService:
    """Run the doctor checks."""

    def __init__(self, config: ManagerConfig) -> None:
        self.config = config
        self.nginx = NginxService(config)
        self.system = SystemService(config)

    def run(self) -> HealthReport:
        """Run all health checks and return a structured report."""
        items: list[HealthCheckItem] = []

        nginx_exists = command_exists(self.config.nginx.nginx_bin)
        items.append(
            HealthCheckItem(
                name="nginx command",
                status="OK" if nginx_exists or self.config.mode == "development" else "FAIL",
                message=(
                    "nginx command found."
                    if nginx_exists
                    else "Development mode uses simulated nginx checks."
                    if self.config.mode == "development"
                    else "nginx command was not found."
                ),
                suggestion=None if nginx_exists else "Run: sudo nam fix --install-nginx",
            )
        )

        systemctl_exists = command_exists(self.config.nginx.systemctl_bin)
        items.append(
            HealthCheckItem(
                name="systemctl command",
                status="OK" if systemctl_exists or self.config.mode == "development" else "FAIL",
                message=(
                    "systemctl command found."
                    if systemctl_exists
                    else "Development mode does not require systemctl."
                    if self.config.mode == "development"
                    else "systemctl command was not found."
                ),
                suggestion=(
                    "Use Ubuntu/systemd or development mode." if not systemctl_exists else None
                ),
            )
        )

        if self.config.mode == "production" and systemctl_exists:
            status = self.system.service_status()
            items.append(
                HealthCheckItem(
                    name="nginx service",
                    status="OK" if status.ok else "FAIL",
                    message="nginx service exists." if status.ok else status.message,
                    suggestion="Install nginx or check service name." if not status.ok else None,
                )
            )

            active = self.system.is_active()
            items.append(
                HealthCheckItem(
                    name="nginx active",
                    status="OK" if active.ok else "WARN",
                    message=active.message,
                    suggestion="Run: sudo nam fix --start-service" if not active.ok else None,
                )
            )

            enabled = self.system.is_enabled()
            items.append(
                HealthCheckItem(
                    name="nginx enabled",
                    status="OK" if enabled.ok else "WARN",
                    message=enabled.message,
                    suggestion="Run: sudo nam fix --enable-service" if not enabled.ok else None,
                )
            )
        else:
            items.append(
                HealthCheckItem(
                    name="nginx service",
                    status="OK" if self.config.mode == "development" else "WARN",
                    message="Development mode: systemd checks are simulated."
                    if self.config.mode == "development"
                    else "systemctl unavailable; service status cannot be checked.",
                )
            )

        nginx_test = self.nginx.test_config()
        items.append(
            HealthCheckItem(
                name="nginx syntax",
                status="OK" if nginx_test.ok else "FAIL",
                message=nginx_test.message,
                suggestion="Run: nam fix --repair-config" if not nginx_test.ok else None,
            )
        )

        for label, path in (
            ("sites-available directory", self.config.nginx.sites_available),
            ("sites-enabled directory", self.config.nginx.sites_enabled),
            ("data directory", self.config.data_dir),
            ("backup directory", self.config.backup_dir),
            ("log directory", self.config.log_dir),
        ):
            exists = path.exists()
            items.append(
                HealthCheckItem(
                    name=label,
                    status="OK" if exists else "WARN",
                    message=str(path) if exists else f"Missing: {path}",
                    suggestion="Run: nam fix --create-dirs" if not exists else None,
                )
            )

        write_targets = [
            self.config.apps_file,
            self.config.nginx.sites_available,
            self.config.nginx.sites_enabled,
        ]
        can_write = all(can_write_path(path) for path in write_targets)
        if self.config.mode == "production" and not is_root():
            items.append(
                HealthCheckItem(
                    name="write permissions",
                    status="WARN",
                    message="Read-only commands can run, but writes usually need sudo.",
                    suggestion="Use sudo for add/update/delete/enable/disable/fix.",
                )
            )
        else:
            items.append(
                HealthCheckItem(
                    name="write permissions",
                    status="OK" if can_write else "WARN",
                    message=(
                        "Writable paths look OK."
                        if can_write
                        else "Some target paths are not writable."
                    ),
                    suggestion=(
                        "Run with sudo or adjust development paths." if not can_write else None
                    ),
                )
            )

        return HealthReport(items=items)
