"""Pydantic models used by nginx-app-manager."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nam.utils.validators import (
    normalize_domain,
    validate_port_number,
    validate_upstream_host,
)


def utc_now() -> datetime:
    """Return the current UTC time without microseconds for stable YAML output."""
    return datetime.now(UTC).replace(microsecond=0)


class NginxSettings(BaseModel):
    """Configurable Nginx and systemd paths."""

    nginx_conf: Path = Path("/etc/nginx/nginx.conf")
    sites_available: Path = Path("/etc/nginx/sites-available")
    sites_enabled: Path = Path("/etc/nginx/sites-enabled")
    nginx_bin: str = "nginx"
    systemctl_bin: str = "systemctl"
    service_name: str = "nginx"


class ManagerConfig(BaseModel):
    """Global configuration for the tool."""

    model_config = ConfigDict(validate_assignment=True)

    mode: Literal["production", "development"] = "production"
    data_dir: Path = Path("/var/lib/nginx-app-manager")
    backup_dir: Path = Path("/var/backups/nginx-app-manager")
    log_dir: Path = Path("/var/log/nginx-app-manager")
    apps_file: Path = Path("/var/lib/nginx-app-manager/apps.yaml")
    nginx: NginxSettings = Field(default_factory=NginxSettings)


class AppConfig(BaseModel):
    """Metadata and reverse proxy settings for a managed app/domain."""

    model_config = ConfigDict(validate_assignment=True)

    domain: str
    listen_port: int = 8080
    upstream_host: str = "127.0.0.1"
    upstream_port: int
    protocol: Literal["http", "https"] = "http"
    enabled: bool = False
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    client_max_body_size: str = "100M"
    security_headers: bool = False
    access_log: bool = True
    error_log: bool = True
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    managed_by_tool: bool = True

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, value: str) -> str:
        """Normalize and validate a fully qualified domain name."""
        return normalize_domain(value)

    @field_validator("listen_port", "upstream_port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        """Validate TCP port values."""
        return validate_port_number(value)

    @field_validator("upstream_host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        """Validate a host value used in proxy_pass."""
        return validate_upstream_host(value)

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: list[str] | str | None) -> list[str]:
        """Accept a comma-separated string or a list for tags."""
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [str(item).strip() for item in value if str(item).strip()]

    def touch(self) -> None:
        """Update the modified timestamp."""
        self.updated_at = utc_now()

    @property
    def upstream(self) -> str:
        """Return the upstream address in host:port form."""
        return f"{self.upstream_host}:{self.upstream_port}"


class AppState(BaseModel):
    """On-disk state file containing managed apps."""

    version: int = 1
    apps: dict[str, AppConfig] = Field(default_factory=dict)


HealthStatus = Literal["OK", "WARN", "FAIL"]


class HealthCheckItem(BaseModel):
    """One row in a health check report."""

    name: str
    status: HealthStatus
    message: str
    suggestion: str | None = None


class HealthReport(BaseModel):
    """Full health check report."""

    items: list[HealthCheckItem]

    @property
    def ok(self) -> bool:
        """Return true when no check failed."""
        return all(item.status != "FAIL" for item in self.items)


class OperationResult(BaseModel):
    """Standard service operation result."""

    ok: bool
    message: str
    details: dict[str, object] = Field(default_factory=dict)
