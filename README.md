# Lens for Kiro Crew

Lens turns your local Kiro Crew session history into a searchable analytics dashboard and a read-only SQL catalog. It reads the JSONL records already stored on your machine; session contents are not uploaded or copied into a separate service.

## Features

- Totals and a 14-day activity view for sessions, messages, and tool calls
- Most-used tools and most-read skills
- A catalog describing the available SQL views and columns
- A skill viewer with estimated partial-read coverage
- Query-cost diagnostics for finding expensive repeated analyses
- Lens command-line tool (`kc-lens`), a guarded read-only DuckDB CLI for ad-hoc queries

## Requirements

- Kiro Crew on Linux or macOS
- Python 3.10 or newer
- DuckDB for Python, provisioned into an app-local virtual environment during installation
- Node.js 20.19 or newer when building the UI from source

When the backend starts, Kiro Crew creates an isolated `.venv/` inside the installed app and installs the pinned dependency from `requirements.txt`. The `.venv/` shown below serves the same purpose for source development.

The distributable UI bundle is committed with releases. Build it only when changing the frontend:

```bash
cd ui
npm install
npm run typecheck
npm run build
```

Install the app from its source directory:

```bash
kirocrew app install /absolute/path/to/lens-kiro-crew-app
```

Then open the dashboard’s **Apps** page and enable **Lens** there. Dashboard enablement provisions the managed Python environment and starts the backend. Open **Lens** from the dashboard sidebar; on first open, Lens scans the local session records it can access and builds a rebuildable local catalog. The first load may take longer; later loads reuse that catalog.

## Querying sessions

The `kc` prefix in `kc-lens` stands for Kiro Crew.

Run the repository-local CLI directly:

```bash
./bin/kc-lens "SELECT count(*) AS sessions FROM sessions"
```

To make it available on your `PATH`:

```bash
ln -sfn "$PWD/bin/kc-lens" "$HOME/.local/bin/kc-lens"
```

Examples:

```bash
kc-lens "SELECT tool_name, count(*) AS calls FROM tool_calls GROUP BY 1 ORDER BY 2 DESC LIMIT 15"
kc-lens "SELECT session_file, ts, left(content, 100) FROM messages WHERE content ILIKE '%docker%' ORDER BY ts DESC LIMIT 30"
kc-lens "SELECT path, count(*) AS edits FROM file_edits GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
```

`kc-lens` permits one read-only `SELECT`, `WITH`, `SHOW`, `DESCRIBE`, or `EXPLAIN` statement per invocation. Queries run with bounded threads and a timeout. Set `KC_LENS_TIMEOUT` or `KC_LENS_THREADS` to tune those guards.

## Data and privacy

Lens reads session transcripts from the configured Kiro Crew data home and Kiro CLI replay directory. It stores only a rebuildable DuckDB catalog and a bounded query-performance trace under the app's local data directory. The backend binds to `127.0.0.1` and is exposed only through Kiro Crew's authenticated app proxy.

The dashboard shows summaries by default. Raw message, tool, and file-edit content is available through local `kc-lens` queries run by you or by an agent you explicitly ask to use Lens.

Lens does not upload records, but a local agent you instruct to use `kc-lens` can receive matching transcript content, tool inputs and outputs, and file-edit text in its response. Treat queries as access to your local Kiro Crew history.

## Development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
cd ui && npm run typecheck && npm run build
```

Enable UI live reload after installing a development copy:

```bash
kirocrew app dev lens-kiro-crew-app
```

Backend changes take effect after disabling and re-enabling the app.

## Repository layout

```text
app.json                 App manifest
agents/                  Lens analyst agent
skills/lens-sql/         SQL data-model guidance
backend/                 Local HTTP and query services
bin/kc-lens              Read-only query CLI
tests/                   Backend and query tests
ui/                      Dashboard frontend
```
