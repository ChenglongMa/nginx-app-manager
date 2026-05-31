"""A small Textual TUI for nginx-app-manager."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError as PydanticValidationError
from textual.app import App, ComposeResult
from textual.containers import Container, Grid, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Static,
)

from nam.models import AppConfig, ManagerConfig
from nam.services.app_service import AppService
from nam.services.health_service import HealthService


class ConfirmDeleteScreen(ModalScreen[bool]):
    """Confirmation modal for deleting an app."""

    CSS = """
    ConfirmDeleteScreen {
        align: center middle;
    }

    #delete-dialog {
        width: 62;
        height: 9;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }

    #delete-actions {
        height: 3;
        align: right middle;
    }
    """

    def __init__(self, domain: str) -> None:
        super().__init__()
        self.domain = domain

    def compose(self) -> ComposeResult:
        with Container(id="delete-dialog"):
            yield Label(f"Delete {self.domain} from manager state?")
            yield Static(
                "The upstream app process will not be stopped. "
                "Use purge in the CLI to remove files."
            )
            with Horizontal(id="delete-actions"):
                yield Button("Cancel", id="cancel")
                yield Button("Delete", id="confirm", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")


class ManagerTui(App[None]):
    """Interactive terminal UI."""

    TITLE = "nginx-app-manager"
    SUB_TITLE = "Nginx reverse proxy manager"

    BINDINGS = [
        ("d", "dashboard", "Dashboard"),
        ("h", "health", "Health"),
        ("a", "apps", "Apps"),
        ("n", "new_app", "New"),
        ("l", "logs", "Logs"),
        ("q", "quit", "Quit"),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }

    #nav {
        height: 3;
        padding: 0 1;
        background: $panel;
        align: left middle;
    }

    #status {
        height: 1;
        padding: 0 2;
        background: $boost;
    }

    #main {
        height: 1fr;
        padding: 1 2;
    }

    .section-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .form-grid {
        grid-size: 2;
        grid-columns: 22 1fr;
        grid-gutter: 1 2;
        height: auto;
        margin-bottom: 1;
    }

    .actions {
        height: 3;
        margin-top: 1;
    }

    #form-output, #log-output, #dashboard-output {
        border: solid $primary;
        padding: 1;
        margin-top: 1;
    }
    """

    def __init__(self, config: ManagerConfig) -> None:
        super().__init__()
        self.config = config
        self.app_service = AppService(config)
        self.selected_domain: str | None = None
        self.editing_domain: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="nav"):
            yield Button("Dashboard", id="nav-dashboard")
            yield Button("Health", id="nav-health")
            yield Button("Apps", id="nav-apps")
            yield Button("Add", id="nav-add")
            yield Button("Logs", id="nav-logs")
        yield Static("", id="status")
        yield VerticalScroll(id="main")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_status()
        await self.show_dashboard()

    async def refresh_status(self) -> None:
        report = HealthService(self.config).run()
        failures = sum(1 for item in report.items if item.status == "FAIL")
        warnings = sum(1 for item in report.items if item.status == "WARN")
        mode = self.config.mode
        text = f"mode={mode} | nginx checks: {failures} fail, {warnings} warn"
        self.query_one("#status", Static).update(text)

    async def set_main(self, *widgets: Widget) -> None:
        main = self.query_one("#main", VerticalScroll)
        await main.remove_children()
        await main.mount(*widgets)

    async def show_dashboard(self) -> None:
        apps = self.app_service.list_apps()
        enabled = sum(1 for managed_app in apps if managed_app.enabled)
        text = (
            f"Managed apps: {len(apps)}\n"
            f"Enabled apps: {enabled}\n"
            f"Listen default: 8080\n"
            f"State file: {self.config.apps_file}\n"
            f"sites-available: {self.config.nginx.sites_available}\n"
            f"sites-enabled: {self.config.nginx.sites_enabled}"
        )
        await self.set_main(
            Static("Dashboard", classes="section-title"),
            Static(text, id="dashboard-output"),
        )

    async def show_health(self) -> None:
        table = DataTable(zebra_stripes=True)
        table.add_columns("Status", "Check", "Message", "Suggestion")
        for item in HealthService(self.config).run().items:
            table.add_row(item.status, item.name, item.message, item.suggestion or "")
        await self.set_main(Static("Health Check", classes="section-title"), table)

    async def show_apps(self) -> None:
        table = DataTable(id="apps-table", zebra_stripes=True)
        table.add_columns("Domain", "Listen", "Upstream", "Enabled", "Updated")
        for managed_app in self.app_service.list_apps():
            table.add_row(
                managed_app.domain,
                str(managed_app.listen_port),
                managed_app.upstream,
                "yes" if managed_app.enabled else "no",
                managed_app.updated_at.isoformat(),
                key=managed_app.domain,
            )
        actions = Horizontal(
            Button("Add", id="app-add"),
            Button("Edit", id="app-edit"),
            Button("Enable", id="app-enable"),
            Button("Disable", id="app-disable"),
            Button("Delete", id="app-delete", variant="error"),
            classes="actions",
        )
        await self.set_main(Static("Apps", classes="section-title"), table, actions)

    async def show_form(self, existing: AppConfig | None = None) -> None:
        self.editing_domain = existing.domain if existing else None
        title = "Edit App" if existing else "Add App"
        domain = existing.domain if existing else ""
        upstream_host = existing.upstream_host if existing else "127.0.0.1"
        upstream_port = str(existing.upstream_port) if existing else ""
        listen_port = str(existing.listen_port) if existing else "8080"
        description = existing.description or "" if existing else ""
        tags = ",".join(existing.tags) if existing else ""
        enabled = existing.enabled if existing else False

        form = Grid(
            Label("Domain"),
            Input(value=domain, id="form-domain", placeholder="app1.example.com"),
            Label("Listen port"),
            Input(value=listen_port, id="form-listen-port"),
            Label("Upstream host"),
            Input(value=upstream_host, id="form-upstream-host"),
            Label("Upstream port"),
            Input(value=upstream_port, id="form-upstream-port"),
            Label("Description"),
            Input(value=description, id="form-description"),
            Label("Tags"),
            Input(value=tags, id="form-tags"),
            Label("Enabled"),
            Checkbox(value=enabled, id="form-enabled"),
            classes="form-grid",
        )

        actions = Horizontal(
            Button("Preview", id="form-preview"),
            Button("Save", id="form-save", variant="success"),
            Button("Cancel", id="form-cancel"),
            classes="actions",
        )

        await self.set_main(
            Static(title, classes="section-title"),
            form,
            actions,
            Static("", id="form-output"),
        )

    async def show_logs(self) -> None:
        log_file = Path(self.config.log_dir) / "nam.log"
        if log_file.exists():
            lines = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()[-200:]
            content = "\n".join(lines)
        else:
            content = f"No log file found yet: {log_file}"
        await self.set_main(
            Static("Logs", classes="section-title"),
            Static(content, id="log-output"),
        )

    def form_to_app(self) -> AppConfig:
        domain = self.query_one("#form-domain", Input).value
        listen_port = int(self.query_one("#form-listen-port", Input).value)
        upstream_host = self.query_one("#form-upstream-host", Input).value
        upstream_port = int(self.query_one("#form-upstream-port", Input).value)
        description = self.query_one("#form-description", Input).value or None
        tags = self.query_one("#form-tags", Input).value
        enabled = self.query_one("#form-enabled", Checkbox).value
        existing = self.app_service.get_app(self.editing_domain) if self.editing_domain else None
        created_at = existing.created_at if existing else None
        data = {
            "domain": domain,
            "listen_port": listen_port,
            "upstream_host": upstream_host,
            "upstream_port": upstream_port,
            "description": description,
            "tags": tags,
            "enabled": enabled,
        }
        if created_at is not None:
            data["created_at"] = created_at
        return AppConfig.model_validate(data)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "nav-dashboard":
            await self.show_dashboard()
        elif button_id == "nav-health":
            await self.show_health()
        elif button_id in {"nav-apps", "form-cancel"}:
            await self.show_apps()
        elif button_id in {"nav-add", "app-add"}:
            await self.show_form()
        elif button_id == "nav-logs":
            await self.show_logs()
        elif button_id == "app-edit":
            await self.edit_selected()
        elif button_id == "app-enable" and self.selected_domain:
            self.app_service.enable_app(self.selected_domain)
            await self.refresh_status()
            await self.show_apps()
        elif button_id == "app-disable" and self.selected_domain:
            self.app_service.disable_app(self.selected_domain)
            await self.refresh_status()
            await self.show_apps()
        elif button_id == "app-delete" and self.selected_domain:
            self.push_screen(ConfirmDeleteScreen(self.selected_domain), self.delete_selected)
        elif button_id == "form-preview":
            self.preview_form()
        elif button_id == "form-save":
            await self.save_form()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.selected_domain = str(event.row_key.value)

    async def edit_selected(self) -> None:
        if not self.selected_domain:
            return
        managed_app = self.app_service.get_app(self.selected_domain)
        if managed_app is not None:
            await self.show_form(managed_app)

    def preview_form(self) -> None:
        output = self.query_one("#form-output", Static)
        try:
            managed_app = self.form_to_app()
            output.update(self.app_service.preview_config(managed_app))
        except (PydanticValidationError, ValueError) as exc:
            output.update(f"Invalid form: {exc}")

    async def save_form(self) -> None:
        output = self.query_one("#form-output", Static)
        try:
            managed_app = self.form_to_app()
            if self.editing_domain:
                result = self.app_service.update_app(
                    self.editing_domain,
                    domain=managed_app.domain,
                    listen_port=managed_app.listen_port,
                    upstream_host=managed_app.upstream_host,
                    upstream_port=managed_app.upstream_port,
                    description=managed_app.description,
                    tags=managed_app.tags,
                )
                if managed_app.enabled and result.ok:
                    result = self.app_service.enable_app(managed_app.domain)
                elif result.ok:
                    result = self.app_service.disable_app(managed_app.domain)
            else:
                result = self.app_service.add_app(managed_app, enable=managed_app.enabled)
            output.update(result.message)
            await self.refresh_status()
            if result.ok:
                await self.show_apps()
        except (PydanticValidationError, ValueError) as exc:
            output.update(f"Invalid form: {exc}")

    async def delete_selected(self, confirmed: bool) -> None:
        if confirmed and self.selected_domain:
            self.app_service.delete_app(self.selected_domain)
            self.selected_domain = None
            await self.refresh_status()
            await self.show_apps()

    async def action_dashboard(self) -> None:
        await self.show_dashboard()

    async def action_health(self) -> None:
        await self.show_health()

    async def action_apps(self) -> None:
        await self.show_apps()

    async def action_new_app(self) -> None:
        await self.show_form()

    async def action_logs(self) -> None:
        await self.show_logs()
