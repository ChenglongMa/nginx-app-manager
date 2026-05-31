"""Typer CLI for nginx-app-manager."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import click
import typer
from pydantic import ValidationError as PydanticValidationError
from rich.console import Console
from rich.pretty import Pretty

from nam.config import load_config
from nam.models import AppConfig, ManagerConfig, OperationResult
from nam.services.app_service import AppService
from nam.services.backup_service import BackupService
from nam.services.health_service import HealthService
from nam.services.nginx_service import NginxService
from nam.services.system_service import SystemService
from nam.utils.logging_utils import setup_logging
from nam.utils.table import apps_table, health_table

console = Console()


@dataclass
class CliContext:
    """Typer context object."""

    config: ManagerConfig
    json_output: bool
    verbose: bool


app = typer.Typer(
    name="nam",
    help="Manage Nginx reverse proxy server blocks for local web apps.",
    no_args_is_help=True,
)
app_commands = typer.Typer(help="CRUD operations for managed reverse proxy apps.")
app.add_typer(app_commands, name="app")
_ACTIVE_CONTEXT: CliContext | None = None


def current_context() -> CliContext:
    """Return the active CLI context."""
    if _ACTIVE_CONTEXT is not None:
        return _ACTIVE_CONTEXT
    ctx = click.get_current_context(silent=True)
    if ctx is not None and isinstance(ctx.obj, CliContext):
        return ctx.obj
    raise RuntimeError("CLI context has not been initialized.")


def emit_json(payload: object) -> None:
    """Print JSON with consistent serialization."""
    console.print_json(json.dumps(payload, indent=2, default=str))


def emit_result(result: OperationResult, *, include_rendered: bool = False) -> None:
    """Print an OperationResult and exit non-zero on failure."""
    ctx = current_context()
    if ctx.json_output:
        emit_json(result.model_dump(mode="json"))
    else:
        style = "green" if result.ok else "red"
        console.print(f"[{style}]{result.message}[/{style}]")
        warnings = result.details.get("warnings")
        if isinstance(warnings, list) and warnings:
            for warning in warnings:
                console.print(f"[yellow]WARN[/yellow] {warning}")
        if include_rendered and isinstance(result.details.get("rendered_config"), str):
            console.print()
            console.file.write(str(result.details["rendered_config"]))
            console.file.write("\n")
    if not result.ok:
        raise typer.Exit(1)


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to a YAML manager config file."),
    ] = None,
    dev: Annotated[
        bool,
        typer.Option("--dev", help="Use project-local mock_nginx paths for development."),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Output machine-readable JSON where supported."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Enable debug logging."),
    ] = False,
) -> None:
    """Configure shared CLI state."""
    global _ACTIVE_CONTEXT
    manager_config = load_config(config, development=dev)
    setup_logging(manager_config.log_dir, verbose=verbose)
    _ACTIVE_CONTEXT = CliContext(config=manager_config, json_output=json_output, verbose=verbose)
    ctx.obj = _ACTIVE_CONTEXT


@app.command()
def doctor() -> None:
    """Run health checks for nginx, systemd, permissions, and manager paths."""
    ctx = current_context()
    report = HealthService(ctx.config).run()
    if ctx.json_output:
        emit_json(report.model_dump(mode="json"))
    else:
        console.print(health_table(report))
    if not report.ok:
        raise typer.Exit(1)


@app.command()
def fix(
    install_nginx: Annotated[
        bool,
        typer.Option("--install-nginx", help="Install nginx using apt-get."),
    ] = False,
    start_service: Annotated[
        bool,
        typer.Option("--start-service", help="Start the nginx systemd service."),
    ] = False,
    enable_service: Annotated[
        bool,
        typer.Option("--enable-service", help="Enable nginx on boot."),
    ] = False,
    repair_config: Annotated[
        bool,
        typer.Option(
            "--repair-config",
            help="Restore the latest manager backup if nginx -t fails.",
        ),
    ] = False,
    create_dirs: Annotated[
        bool,
        typer.Option("--create-dirs/--no-create-dirs", help="Create missing manager/nginx dirs."),
    ] = True,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would happen without changing files/services."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation for high-risk operations."),
    ] = False,
) -> None:
    """Repair common install, service, path, and config problems."""
    ctx = current_context()
    nginx = NginxService(ctx.config)
    system = SystemService(ctx.config)
    results: list[OperationResult] = []

    risky = install_nginx or start_service or enable_service or repair_config
    if risky and not yes:
        typer.confirm(
            "This may change system packages/services/config files. Continue?",
            abort=True,
        )

    if create_dirs:
        results.append(nginx.ensure_directories(create=not dry_run))
    if install_nginx:
        results.append(system.install_nginx(dry_run=dry_run))
    if start_service:
        results.append(system.start_service(dry_run=dry_run))
    if enable_service:
        results.append(system.enable_service(dry_run=dry_run))
    if repair_config:
        results.append(_repair_config(ctx.config, dry_run=dry_run))

    if ctx.json_output:
        emit_json([result.model_dump(mode="json") for result in results])
    else:
        for result in results:
            style = "green" if result.ok else "red"
            console.print(f"[{style}]{result.message}[/{style}]")
    if any(not result.ok for result in results):
        raise typer.Exit(1)


def _repair_config(config: ManagerConfig, *, dry_run: bool) -> OperationResult:
    """Restore the latest backup when nginx -t currently fails."""
    nginx = NginxService(config)
    current_test = nginx.test_config()
    if current_test.ok:
        return OperationResult(ok=True, message="nginx -t already passes; no repair needed.")
    backup = BackupService(config).latest_backup()
    if backup is None:
        return OperationResult(
            ok=False,
            message="nginx -t fails and no manager backup is available.",
        )
    if dry_run:
        return OperationResult(
            ok=True,
            message="Dry run: latest backup would be restored.",
            details={
                "backup_path": str(backup.backup_path),
                "original_path": str(backup.original_path),
            },
        )
    restored = BackupService(config).restore_backup(backup)
    post_test = nginx.test_config()
    if not post_test.ok:
        return OperationResult(
            ok=False,
            message=f"Restored {restored}, but nginx -t still fails: {post_test.message}",
        )
    reload_result = nginx.reload()
    if not reload_result.ok:
        return OperationResult(
            ok=False,
            message=f"Restored {restored}, but nginx reload failed: {reload_result.message}",
        )
    return OperationResult(
        ok=True,
        message=f"Restored latest backup and reloaded nginx: {restored}",
    )


@app.command()
def tui() -> None:
    """Launch the interactive Textual terminal UI."""
    ctx = current_context()
    from nam.tui import ManagerTui

    ManagerTui(ctx.config).run()


@app_commands.command("list")
def list_apps() -> None:
    """List apps currently managed by this tool."""
    ctx = current_context()
    service = AppService(ctx.config)
    managed_apps = service.list_apps()
    if ctx.json_output:
        emit_json([managed_app.model_dump(mode="json") for managed_app in managed_apps])
    else:
        console.print(apps_table(managed_apps, service.config_paths()))


@app_commands.command("add")
def add_app(
    domain: Annotated[str, typer.Argument(help="Domain/subdomain to proxy, e.g. app.example.com.")],
    upstream_port: Annotated[int, typer.Option("--upstream-port", "-p", help="Local app port.")],
    upstream_host: Annotated[
        str,
        typer.Option("--upstream-host", help="Local app host/IP."),
    ] = "127.0.0.1",
    listen_port: Annotated[
        int,
        typer.Option("--listen-port", "-l", help="External Nginx listen port."),
    ] = 8080,
    protocol: Annotated[
        str,
        typer.Option("--protocol", help="Upstream protocol: http or https."),
    ] = "http",
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="Optional description."),
    ] = None,
    tags: Annotated[
        str | None,
        typer.Option("--tags", help="Comma-separated tags."),
    ] = None,
    enable: Annotated[
        bool,
        typer.Option("--enable", help="Enable the Nginx site immediately."),
    ] = False,
    security_headers: Annotated[
        bool,
        typer.Option("--security-headers", help="Emit conservative security headers."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview generated config without writing."),
    ] = False,
) -> None:
    """Create a managed reverse proxy app."""
    try:
        managed_app = AppConfig(
            domain=domain,
            upstream_port=upstream_port,
            upstream_host=upstream_host,
            listen_port=listen_port,
            protocol=protocol,  # type: ignore[arg-type]
            description=description,
            tags=tags,
            enabled=enable,
            security_headers=security_headers,
        )
    except PydanticValidationError as exc:
        console.print(f"[red]Invalid app config:[/red] {exc}")
        raise typer.Exit(2) from exc
    result = AppService(current_context().config).add_app(
        managed_app,
        enable=enable,
        dry_run=dry_run,
    )
    emit_result(result, include_rendered=dry_run)


@app_commands.command("show")
def show_app(
    domain: Annotated[str, typer.Argument(help="Managed domain to inspect.")],
) -> None:
    """Show one managed app and its Nginx config state."""
    ctx = current_context()
    description = AppService(ctx.config).describe_app(domain)
    if description is None:
        console.print(f"[red]Unknown app:[/red] {domain}")
        raise typer.Exit(1)
    if ctx.json_output:
        emit_json(description)
    else:
        console.print(Pretty(description, expand_all=False))


@app_commands.command("update")
def update_app(
    domain: Annotated[str, typer.Argument(help="Managed domain to update.")],
    new_domain: Annotated[
        str | None,
        typer.Option("--domain", help="Rename the managed domain."),
    ] = None,
    upstream_port: Annotated[
        int | None,
        typer.Option("--upstream-port", "-p", help="New local app port."),
    ] = None,
    upstream_host: Annotated[
        str | None,
        typer.Option("--upstream-host", help="New local app host/IP."),
    ] = None,
    listen_port: Annotated[
        int | None,
        typer.Option("--listen-port", "-l", help="New external Nginx listen port."),
    ] = None,
    protocol: Annotated[
        str | None,
        typer.Option("--protocol", help="New upstream protocol."),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option("--description", "-d", help="New description."),
    ] = None,
    tags: Annotated[
        str | None,
        typer.Option("--tags", help="Replace tags with comma-separated values."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview generated config without writing."),
    ] = False,
) -> None:
    """Update an app and safely re-apply its generated Nginx config."""
    updates = {
        "domain": new_domain,
        "upstream_port": upstream_port,
        "upstream_host": upstream_host,
        "listen_port": listen_port,
        "protocol": protocol,
        "description": description,
        "tags": tags,
    }
    if not any(value is not None for value in updates.values()):
        console.print("[yellow]No updates supplied.[/yellow]")
        raise typer.Exit(0)
    result = AppService(current_context().config).update_app(domain, dry_run=dry_run, **updates)
    emit_result(result, include_rendered=dry_run)


@app_commands.command("enable")
def enable_app(
    domain: Annotated[str, typer.Argument(help="Managed domain to enable.")],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview without changing files/services."),
    ] = False,
) -> None:
    """Enable a managed app in sites-enabled."""
    result = AppService(current_context().config).enable_app(domain, dry_run=dry_run)
    emit_result(result)


@app_commands.command("disable")
def disable_app(
    domain: Annotated[str, typer.Argument(help="Managed domain to disable.")],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview without changing files/services."),
    ] = False,
) -> None:
    """Disable a managed app in sites-enabled."""
    result = AppService(current_context().config).disable_app(domain, dry_run=dry_run)
    emit_result(result)


@app_commands.command("delete")
def delete_app(
    domain: Annotated[str, typer.Argument(help="Managed domain to remove from manager state.")],
    purge: Annotated[
        bool,
        typer.Option("--purge", help="Also delete the generated sites-available config file."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Preview without changing files/services."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation."),
    ] = False,
) -> None:
    """Disable and delete an app from manager state. Does not stop the upstream app."""
    if not yes:
        action = (
            "disable, purge config, and delete metadata"
            if purge
            else "disable and delete metadata"
        )
        typer.confirm(f"Really {action} for {domain}?", abort=True)
    result = AppService(current_context().config).delete_app(domain, purge=purge, dry_run=dry_run)
    emit_result(result)
