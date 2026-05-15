# Ubuntu Online Check

FastAPI-based website monitoring tool that polls configured URLs at a regular interval, stores historical response data in SQLite, and provides a web dashboard with status tables and interactive charts.

## Features

- Polls multiple websites at a configurable interval (default: 60 s)
- Organises sites into groups (e.g. per organisation) with collapsible tables and charts
- Displays real-time status table (UP / DOWN) with current, min, max, and average response times
- Historical data stored in SQLite with configurable retention (default: 90 days)
- Interactive charts (response time + uptime %) with hourly, daily, and monthly views
- Toggle individual org chart sections on/off, or collapse per-org chart grids
- Automatically prunes data for removed sites and expired records on startup
- Jinja2 HTML templates for easy layout customisation
- Dark mode with persisted preference
- Admin panel with password protection: database statistics, site/org management (add, delete, **rename** with historical data preservation via stable IDs), status management (degraded/maintenance notices with update history)
- Password stored as salted scrypt hash in the database
- Database schema managed via **Alembic migrations**

## Requirements

- Python 3.10+
- `venv` (usually included with Python)

## Setup

```bash
# Clone or enter the project directory
git clone https://github.com/moon127/site-uptime-monitor
cd site-uptime-monitor

# Create a virtual environment
python3 -m venv venv

# Activate it
source venv/bin/activate       # macOS / Linux
# venv\Scripts\activate        # Windows

# Install dependencies
pip install -r requirements.txt
```

## Configuration

`config.ini` is optional. If it doesn't exist, it will be created automatically
on first run — you can then add all sites and organisations via the admin panel.

Edit `config.ini` in the project root:

```ini
[org:ubuntu]
ubuntu = https://ubuntu.com

[org:misc]
google = https://google.com
github = https://github.com

[settings]
; How long to keep data (days). Data older than this is pruned on restart.
retention_days = 90
; How often to check each site (seconds).
poll_interval = 60
```

Sites can be grouped into organisations using `[org:name]` sections.  
Each site appears under its org in the dashboard table and charts.  
Org chart sections can be toggled on/off or collapsed via their heading.

A plain `[sites]` section is still supported for backward compatibility:
any sites listed there will appear under a single "All Sites" group.

### Adding / removing sites

Use the admin panel (`/admin`) to add or remove sites and orgs at runtime
(no restart needed — the monitoring loop picks up changes automatically).

You can also edit `config.ini` directly and restart the application.  
When a site is removed, all of its historical data is automatically purged
from the database.

### Renaming sites and orgs

The admin panel provides **Rename** buttons for each org and site.
Renaming preserves all historical data because records are stored against
a stable internal ID rather than the display name. Config and DB are kept
in sync automatically.

### Changing retention

Update `retention_days` and restart. Data older than the new value is pruned
on startup.

## Admin Panel

Point your browser to `/admin` on the running server.

**First run:** you will be prompted to create a password (min. 6 characters).  
The password is hashed with scrypt and stored in `sitechecker.db`.

**Login:** enter the password to access the admin dashboard.

The admin page shows:

- **Statistics:** total checks, site count, org count, UP/DOWN counts, and
  per-site breakdown with uptime %
- **Add Organisation:** create a new group with an optional initial site
- **Add Site:** add a site to an existing organisation
- **Current Orgs & Sites:** view all orgs/sites with delete and **rename** buttons
- **Status Management:** set degraded/maintenance status on orgs or sites,
  update messages (with history), clear active statuses, and browse status
  history with expandable update trails

Changes made in the admin panel are written directly to `config.ini`.  
The monitoring loop picks them up automatically (no restart needed).

### Password reset (CLI)

If you lose the admin password, delete the stored hash and recreate it:

```bash
sqlite3 sitechecker.db "DELETE FROM admin_user;"
```

Then visit `/admin` again — you'll be prompted to set a new password.

## Running

```bash
# Make sure the virtual environment is active
source venv/bin/activate

# Start the dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000 in your browser.

### Options

- `--host 0.0.0.0` — listen on all interfaces (omit for localhost only)
- `--port <PORT>` — change the port (default: 8000)
- `--reload` — auto-restart on file changes (useful during development)

### Running with Docker

```bash
# Create a data directory for persistent config and database
mkdir data

# Pull and run from Docker Hub
docker run -d \
  --name site-uptime-monitor \
  -p 8000:8000 \
  -v ./data:/data \
  --restart unless-stopped \
  garethwoolridge/site-uptime-monitor
```

Or build and run locally with Compose:

```bash
docker compose up -d
```

The container stores `config.ini` and `sitechecker.db` in `/data` inside the
container, which maps to the `./data` directory on your host. You can place
an existing `config.ini` there before starting, or configure everything via
the admin panel after first run.

To rebuild after updating:

```bash
docker compose build --pull
docker compose up -d
```

### Running in production

```bash
pip install gunicorn
gunicorn -w 1 -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:8000
```

The background monitor uses `asyncio` and expects a **single worker process**.
Do not use multiple workers (`-w 1` is required).

#### Systemd service example

```ini
[Unit]
Description=Site Monitor
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/site-uptime-monitor
ExecStart=/opt/site-uptime-monitor/venv/bin/gunicorn -w 1 -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Database migrations

Schema changes are tracked with Alembic. On startup the app automatically
runs `alembic upgrade head` to bring the database up to date.

### Creating a new migration

After modifying `app/models.py`:

```bash
source venv/bin/activate
alembic revision --autogenerate -m "describe your change"
```

Review the generated file in `alembic/versions/`, then apply it:

```bash
alembic upgrade head
```

(The app also runs this automatically on next restart.)

### Rolling back

```bash
alembic downgrade -1      # undo last migration
alembic downgrade <rev>   # go to a specific revision
```

## Updating

```bash
git pull
source venv/bin/activate
pip install -r requirements.txt
# The app will apply any pending migrations on next start.
# Restart the service / process.
```

## Testing

```bash
make test          # run tests with coverage
make test-quick    # run tests without coverage
make lint          # check code style with ruff
make lint-fix      # auto-fix lint issues
```

## Project structure

```
site-uptime-monitor/
├── alembic/
│   ├── versions/         # Migration scripts
│   ├── env.py            # Alembic environment config
│   └── script.py.mako    # Migration template
├── app/
│   ├── __init__.py
│   ├── main.py           # FastAPI application and routes
│   ├── config.py         # Config file parser + DB sync
│   ├── database.py       # SQLAlchemy engine and session
│   ├── models.py         # Database models
│   ├── monitor.py        # Background polling loop
│   └── templates/
│       ├── index.html         # Main dashboard
│       ├── admin.html         # Admin panel
│       ├── admin_login.html   # Admin login
│       └── admin_setup.html   # First-run password setup
├── tests/
│   ├── conftest.py       # Test fixtures (temp DB, client, cleanup)
│   ├── test_config.py    # Config loading and DB sync tests
│   ├── test_main.py      # Dashboard, admin, rename, status tests
│   └── test_migrations.py # Alembic migration tests
├── alembic.ini           # Alembic configuration
├── config.ini            # Site list and settings
├── docker-compose.yml    # Docker Compose configuration
├── Dockerfile            # OCI image build
├── Makefile              # Convenience targets (test, lint, clean)
├── pyproject.toml        # Test / lint tool configuration
├── requirements.txt
├── README.md
└── sitechecker.db        # SQLite database (created at runtime)
```

## Dashboard

| Period    | Time window | Data aggregation |
|-----------|-------------|-----------------|
| Hourly    | Last 1 hour | Per-minute      |
| Daily     | Last 24 h   | Per-hour        |
| Monthly   | Last 30 d   | Per-day         |

- The table always reflects the selected time period for min/max/avg columns.  
- The "Current (ms)" column always shows the most recent check.  
- Charts display response time (left axis, ms) and uptime % (right axis) side by side.
