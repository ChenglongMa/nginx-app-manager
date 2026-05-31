"""Systemd and apt repair helpers."""

from __future__ import annotations

from pathlib import Path

from nam.models import ManagerConfig, OperationResult
from nam.utils.paths import is_root
from nam.utils.shell import command_exists, run_command


class SystemService:
    """Wrap high-risk operating-system actions."""

    def __init__(self, config: ManagerConfig) -> None:
        self.config = config

    def require_root_for_write(self) -> OperationResult | None:
        """Return a failure result when a production write is attempted without root."""
        if self.config.mode == "production" and not is_root():
            return OperationResult(
                ok=False,
                message="This write operation requires root. Re-run with sudo.",
                details={"suggestion": "sudo nam ..."},
            )
        return None

    def is_debian_like(self) -> bool:
        """Return true on Debian/Ubuntu-like systems."""
        os_release = Path("/etc/os-release")
        if not os_release.exists():
            return False
        content = os_release.read_text(encoding="utf-8", errors="ignore").lower()
        return "id=ubuntu" in content or "id=debian" in content or "id_like=debian" in content

    def install_nginx(self, *, dry_run: bool = False) -> OperationResult:
        """Install Nginx with apt-get on Debian/Ubuntu systems."""
        if not self.is_debian_like():
            return OperationResult(
                ok=False,
                message="Automatic install is only supported on Debian/Ubuntu.",
            )
        root_error = self.require_root_for_write()
        if root_error is not None:
            return root_error
        if dry_run:
            return OperationResult(
                ok=True,
                message="Dry run: apt-get install -y nginx was not executed.",
            )
        result = run_command(["apt-get", "update"], timeout=120)
        if not result.ok:
            return OperationResult(
                ok=False,
                message=result.combined_output or "apt-get update failed.",
            )
        install = run_command(["apt-get", "install", "-y", "nginx"], timeout=300)
        return OperationResult(
            ok=install.ok,
            message=install.combined_output or "apt-get install nginx completed.",
            details={"returncode": install.returncode},
        )

    def start_service(self, *, dry_run: bool = False) -> OperationResult:
        """Start the configured Nginx service."""
        root_error = self.require_root_for_write()
        if root_error is not None:
            return root_error
        if dry_run:
            return OperationResult(ok=True, message="Dry run: systemctl start was not executed.")
        result = run_command(
            [self.config.nginx.systemctl_bin, "start", self.config.nginx.service_name],
            timeout=30,
        )
        return OperationResult(
            ok=result.ok,
            message=result.combined_output or "Service start completed.",
        )

    def enable_service(self, *, dry_run: bool = False) -> OperationResult:
        """Enable the configured Nginx service on boot."""
        root_error = self.require_root_for_write()
        if root_error is not None:
            return root_error
        if dry_run:
            return OperationResult(ok=True, message="Dry run: systemctl enable was not executed.")
        result = run_command(
            [self.config.nginx.systemctl_bin, "enable", self.config.nginx.service_name],
            timeout=30,
        )
        return OperationResult(
            ok=result.ok,
            message=result.combined_output or "Service enable completed.",
        )

    def service_status(self) -> OperationResult:
        """Return service status using systemctl."""
        if not command_exists(self.config.nginx.systemctl_bin):
            return OperationResult(ok=False, message="systemctl command was not found.")
        result = run_command(
            [
                self.config.nginx.systemctl_bin,
                "status",
                self.config.nginx.service_name,
                "--no-pager",
            ],
            timeout=15,
        )
        return OperationResult(
            ok=result.ok,
            message=result.combined_output or "systemctl status completed.",
        )

    def is_active(self) -> OperationResult:
        """Return whether the service is active."""
        result = run_command(
            [self.config.nginx.systemctl_bin, "is-active", self.config.nginx.service_name],
            timeout=15,
        )
        return OperationResult(ok=result.ok, message=result.combined_output or "unknown")

    def is_enabled(self) -> OperationResult:
        """Return whether the service is enabled."""
        result = run_command(
            [self.config.nginx.systemctl_bin, "is-enabled", self.config.nginx.service_name],
            timeout=15,
        )
        return OperationResult(ok=result.ok, message=result.combined_output or "unknown")
