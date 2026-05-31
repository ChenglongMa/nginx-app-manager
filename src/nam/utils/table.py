"""Rich table helpers."""

from __future__ import annotations

from rich.table import Table

from nam.models import AppConfig, HealthReport


def health_table(report: HealthReport) -> Table:
    """Build a Rich health report table."""
    table = Table(title="nginx-app-manager doctor")
    table.add_column("Status", style="bold")
    table.add_column("Check")
    table.add_column("Message")
    table.add_column("Suggestion")
    styles = {"OK": "green", "WARN": "yellow", "FAIL": "red"}
    for item in report.items:
        table.add_row(
            f"[{styles[item.status]}]{item.status}[/{styles[item.status]}]",
            item.name,
            item.message,
            item.suggestion or "",
        )
    return table


def apps_table(apps: list[AppConfig], config_paths: dict[str, str]) -> Table:
    """Build a Rich app list table."""
    table = Table(title="Managed apps")
    table.add_column("Domain")
    table.add_column("Listen")
    table.add_column("Upstream")
    table.add_column("Enabled")
    table.add_column("Config file")
    table.add_column("Last updated")
    for app in apps:
        table.add_row(
            app.domain,
            str(app.listen_port),
            app.upstream,
            "yes" if app.enabled else "no",
            config_paths.get(app.domain, ""),
            app.updated_at.isoformat(),
        )
    return table
