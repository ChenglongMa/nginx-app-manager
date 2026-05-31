# nginx-app-manager

`nginx-app-manager` is a Python CLI and Textual TUI for managing Nginx reverse
proxy server blocks on Ubuntu 24.04+ with systemd.

It is designed for servers where only an external port such as `8080` is
reachable, while multiple local apps run on different ports:

- `app1.example.com` -> `127.0.0.1:8501`
- `demo.example.com` -> `127.0.0.1:8502`

The tool manages one generated config file per domain under `sites-available`,
links enabled apps into `sites-enabled`, runs `nginx -t`, reloads Nginx, and
rolls back file/link changes on failure.

## Status

Implemented:

- Typer CLI: `doctor`, `fix`, `tui`, and `app` CRUD commands
- Textual TUI: dashboard, health, app list, add/edit form, preview, logs, delete confirmation
- Configurable production and development paths
- YAML state file for managed app metadata
- Jinja2 Nginx template with Streamlit/FastAPI/Gradio websocket-friendly defaults
- Backup metadata and rollback for generated Nginx config changes
- `--dry-run` on mutating app commands
- `--json` for automation-friendly CLI output
- pytest coverage for validators, template rendering, and development-mode app operations

Simplified or future work:

- Development mode simulates `nginx -t` and reload instead of invoking a mock Nginx binary.
- Port conflict checks are warnings based on managed app state, not full OS socket inspection.
- `fix --repair-config` restores the latest manager backup; it does not parse arbitrary Nginx errors to identify unmanaged broken files.
- HTTPS/certbot management is intentionally out of scope for the first version.

## Architecture

```text
src/nam/
  cli.py                      # Typer command surface
  tui.py                      # Textual terminal UI
  config.py                   # production/development config loading
  models.py                   # Pydantic models
  services/
    app_service.py            # app CRUD and state orchestration
    nginx_service.py          # safe write/test/reload/rollback flow
    backup_service.py         # backups and restore metadata
    health_service.py         # doctor checks
    system_service.py         # apt/systemd repair actions
    template_service.py       # Jinja rendering
  templates/nginx_server.conf.j2
```

CLI code only handles arguments and display. System-changing behavior lives in
the service layer so it can be tested and extended.

## Install

This project targets Python 3.11 and uses `uv`.

```bash
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
```

Check the CLI:

```bash
nam --help
nam app --help
```

## Production Usage

Production defaults:

- `/etc/nginx/nginx.conf`
- `/etc/nginx/sites-available/`
- `/etc/nginx/sites-enabled/`
- `/var/lib/nginx-app-manager/apps.yaml`
- `/var/backups/nginx-app-manager/`
- `/var/log/nginx-app-manager/`

Run health checks:

```bash
nam doctor
```

Create runtime directories:

```bash
sudo nam fix --create-dirs
```

Install/start/enable Nginx on Ubuntu/Debian:

```bash
sudo nam fix --install-nginx --start-service --enable-service
```

Add and enable the default Streamlit-style examples:

```bash
sudo nam app add app1.example.com --upstream-port 8501 --listen-port 8080 --enable
sudo nam app add demo.example.com --upstream-port 8502 --listen-port 8080 --enable
```

List and inspect:

```bash
nam app list
nam app show app1.example.com
nam --json app list
```

Update, disable, enable, and delete:

```bash
sudo nam app update app1.example.com --upstream-port 8510
sudo nam app disable app1.example.com
sudo nam app enable app1.example.com
sudo nam app delete app1.example.com --yes
sudo nam app delete app1.example.com --purge --yes
```

`delete` removes manager state and disables the Nginx site. It does not stop or
delete the upstream application process. Add `--purge` to remove the generated
`sites-available` config file after a backup.

Preview before writing:

```bash
nam app add app1.example.com --upstream-port 8501 --enable --dry-run
```

Launch the TUI:

```bash
sudo nam tui
```

## Development Mode

Development mode writes into `./mock_nginx` and simulates Nginx validation and
reloads. This is useful on a laptop or in tests.

```bash
nam --dev doctor
nam --dev fix --create-dirs
nam --dev app add app1.example.com --upstream-port 8501 --enable
nam --dev app list
nam --dev tui
```

You can also pass a config file:

```bash
nam --config examples/config.dev.yaml app list
```

## Permission Model

Read-only commands such as `doctor`, `app list`, and `app show` can run as a
normal user where permissions allow. Production write operations usually need
root because they touch `/etc/nginx`, `/var/lib`, `/var/backups`, and systemd.

The tool does not sprinkle `sudo` inside subprocess calls. Run mutating
production commands with `sudo nam ...`.

## Generated Nginx Config

The template is optimized for reverse proxying local HTTP apps on subdomains.
It includes:

- `listen 8080`
- `server_name <domain>`
- `proxy_pass http://127.0.0.1:<port>`
- common forwarded headers
- websocket upgrade headers
- long read/send timeouts
- `proxy_buffering off` for Streamlit-style apps

See `examples/app1.example.com.conf`.

## Tests

```bash
uv pip install -e ".[dev]"
pytest
```

## Safety Notes

- Generated files include `managed_by: nginx-app-manager`.
- Existing unmanaged config files are not overwritten unless the service layer is explicitly forced.
- Before replacing a managed config, the old file is backed up under the configured backup directory.
- Enable/update flow writes a temp file, replaces `sites-available`, updates the symlink, runs `nginx -t`, reloads, and restores the previous file/link snapshot if validation or reload fails.
- `fix --repair-config` can restore the latest backup when a manager-generated change broke Nginx.
