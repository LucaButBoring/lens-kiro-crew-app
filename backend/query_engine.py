"""Local, read-only analytics over Kiro Crew JSONL records."""
from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

APP_NAME = "lens-kiro-crew-app"
ALLOWED_START = re.compile(r"^\s*(?:SELECT|WITH|SHOW|DESCRIBE|EXPLAIN)\b", re.IGNORECASE)
WRITE_KEYWORDS = re.compile(
    r"\b(?:ATTACH|COPY|CREATE|DELETE|DETACH|DROP|EXPORT|IMPORT|INSERT|INSTALL|LOAD|PRAGMA|"
    r"REPLACE|SET|TRUNCATE|UPDATE|VACUUM)\b",
    re.IGNORECASE,
)
QUOTED_LITERAL = re.compile(r"'(?:''|[^'])*'")

VIEW_COLUMNS: dict[str, list[str]] = {
    "messages": ["session_file", "role", "content", "ts", "source_user", "source_thread", "agent", "project", "model", "meta", "session_path"],
    "sessions": ["session_file", "title", "created_at", "updated_at", "agent", "model", "project", "session_path"],
    "cli_messages": ["session_file", "role", "content", "ts", "msg_type", "message_id", "session_path"],
    "subagents": ["agent_id", "session_id", "agent", "status", "turns", "max_turns", "provider", "parent_session", "last_tool", "task", "started", "updated_at", "state_path"],
    "cron_runs": ["run_id", "job_id", "trigger", "started_at", "finished_at", "duration_ms", "status", "summary", "error", "history_path"],
    "tool_calls": ["session_file", "ts", "tool_call_id", "tool_name", "tool_server", "purpose", "tool_input", "tool_output", "done", "content", "session_path", "source"],
    "file_edits": ["session_file", "ts", "path", "before", "after", "before_len", "after_len", "session_path"],
    "all_messages": ["session_file", "role", "content", "ts", "session_path", "source"],
    "query_log": ["ts", "elapsed_ms", "rc", "engine", "caller", "sql_fp", "sql_len", "sql", "trace_path"],
}


class QueryError(RuntimeError):
    """A safe, user-facing query failure."""


class QueryEngine:
    def __init__(self, crew_home: Path | None = None, kiro_home: Path | None = None) -> None:
        self.crew_home = crew_home or Path(os.environ.get("KIROCREW_HOME", Path.home() / ".kiro" / "crew"))
        self.kiro_home = kiro_home or Path(os.environ.get("KIRO_HOME", Path.home() / ".kiro"))
        self.app_root = Path(__file__).resolve().parent.parent
        self.data_dir = self.crew_home / "apps" / APP_NAME / "data"
        self.db_path = self.data_dir / "lens.duckdb"
        self.meta_path = self.data_dir / "lens.meta.json"
        self.trace_path = self.data_dir / "query-trace.jsonl"
        self.schema_path = Path(__file__).with_name("schema.sql")
        self.seed_path = Path(__file__).with_name("seed.jsonl")
        self._lock = threading.RLock()

    @staticmethod
    def dependency_status() -> dict[str, Any]:
        try:
            import duckdb
            return {"available": True, "version": duckdb.__version__}
        except ImportError:
            return {"available": False, "version": None}

    def sources(self) -> dict[str, str]:
        return {
            "SESSIONS": str(self.crew_home / "sessions" / "*.jsonl"),
            "CLI": str(self.kiro_home / "sessions" / "cli" / "*.jsonl"),
            "SUBAGENTS": str(self.crew_home / "subagents" / "*" / "state.json"),
            "CRON": str(self.crew_home / "cron-history" / "*.jsonl"),
            "TRACE": str(self.trace_path),
        }

    def source_counts(self) -> dict[str, int]:
        return {name.lower(): len(glob.glob(pattern)) for name, pattern in self.sources().items()}

    @staticmethod
    def validate_sql(sql: str) -> str:
        statement = sql.strip()
        if not statement:
            raise QueryError("query is empty")
        without_trailing = statement[:-1].rstrip() if statement.endswith(";") else statement
        if ";" in without_trailing:
            raise QueryError("only one statement is allowed")
        scrubbed = QUOTED_LITERAL.sub("''", without_trailing)
        if not ALLOWED_START.match(scrubbed) or WRITE_KEYWORDS.search(scrubbed):
            raise QueryError("only read-only SELECT, WITH, SHOW, DESCRIBE, or EXPLAIN queries are allowed")
        return statement

    def _render_schema(self) -> tuple[str, dict[str, bool]]:
        template = self.schema_path.read_text(encoding="utf-8")
        present: dict[str, bool] = {}
        for name, pattern in self.sources().items():
            exists = bool(glob.glob(pattern))
            present[name] = exists
            selected = pattern if exists else str(self.seed_path)
            template = template.replace(f"@@{name}@@", "'" + selected.replace("'", "''") + "'")
        return template, present

    def _schema_key(self, present: dict[str, bool]) -> str:
        digest = hashlib.sha256()
        digest.update(self.schema_path.read_bytes())
        digest.update(self.seed_path.read_bytes())
        digest.update(json.dumps(self.sources(), sort_keys=True).encode())
        digest.update(json.dumps(present, sort_keys=True).encode())
        return digest.hexdigest()

    def ensure_database(self) -> None:
        try:
            import duckdb
        except ImportError as exc:
            raise QueryError("DuckDB is not installed; run: python3 -m pip install -r requirements.txt") from exc

        with self._lock:
            schema, present = self._render_schema()
            key = self._schema_key(present)
            try:
                current = json.loads(self.meta_path.read_text(encoding="utf-8")).get("schema_key")
            except (OSError, ValueError, AttributeError):
                current = None
            if self.db_path.exists() and current == key:
                return

            self.data_dir.mkdir(parents=True, exist_ok=True)
            temp = self.data_dir / f"lens.{os.getpid()}.building.duckdb"
            temp.unlink(missing_ok=True)
            connection = duckdb.connect(str(temp))
            try:
                connection.execute(schema)
                actual_views = {
                    row[0]
                    for row in connection.execute(
                        "SELECT view_name FROM duckdb_views() WHERE NOT internal"
                    ).fetchall()
                }
                missing_views = set(VIEW_COLUMNS) - actual_views
                if missing_views:
                    raise QueryError(
                        "catalog initialization is missing views: "
                        + ", ".join(sorted(missing_views))
                    )
                for view, expected_columns in VIEW_COLUMNS.items():
                    actual_columns = [
                        row[0] for row in connection.execute(f'DESCRIBE "{view}"').fetchall()
                    ]
                    if actual_columns != expected_columns:
                        raise QueryError(
                            f"catalog view {view!r} has columns {actual_columns!r}; "
                            f"expected {expected_columns!r}"
                        )
            finally:
                connection.close()
            os.replace(temp, self.db_path)
            meta_temp = self.meta_path.with_suffix(".tmp")
            meta_temp.write_text(json.dumps({"schema_key": key}) + "\n", encoding="utf-8")
            os.replace(meta_temp, self.meta_path)

    def query(self, sql: str, *, timeout: int | None = None, caller: str = "kc-lens") -> list[dict[str, Any]]:
        statement = self.validate_sql(sql)
        self.ensure_database()
        try:
            import duckdb
        except ImportError as exc:  # pragma: no cover - guarded above
            raise QueryError("DuckDB is unavailable") from exc

        timeout = timeout if timeout is not None else int(os.environ.get("KC_LENS_TIMEOUT", "120"))
        threads = max(1, min(16, int(os.environ.get("KC_LENS_THREADS", "6"))))
        started = time.monotonic()
        result: dict[str, Any] = {}
        failure: list[BaseException] = []
        connection_holder: dict[str, Any] = {}

        def run() -> None:
            connection = duckdb.connect(str(self.db_path), read_only=True)
            connection_holder["connection"] = connection
            try:
                connection.execute(f"SET threads={threads}")
                cursor = connection.execute(statement)
                columns = [column[0] for column in cursor.description] if cursor.description else []
                result["rows"] = [dict(zip(columns, row)) for row in cursor.fetchall()]
            except BaseException as exc:  # surfaced on the caller thread
                failure.append(exc)
            finally:
                connection_holder.pop("connection", None)
                connection.close()

        worker = threading.Thread(target=run, daemon=True, name="kc-lens-query")
        worker.start()
        worker.join(timeout=max(1, timeout))
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if worker.is_alive():
            connection = connection_holder.get("connection")
            if connection is not None:
                connection.interrupt()
            worker.join(timeout=5)
            self._trace(statement, elapsed_ms, 124, caller)
            raise QueryError(f"query exceeded KC_LENS_TIMEOUT={timeout}s")
        if failure:
            self._trace(statement, elapsed_ms, 1, caller)
            raise QueryError(str(failure[0])[:500])
        self._trace(statement, elapsed_ms, 0, caller)
        return result.get("rows", [])

    def _trace(self, sql: str, elapsed_ms: int, rc: int, caller: str) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            fingerprint = hashlib.sha256(QUOTED_LITERAL.sub("'?'", sql).encode()).hexdigest()[:16]
            row = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "elapsed_ms": elapsed_ms,
                "rc": rc,
                "engine": "duckdb-python",
                "caller": caller[:80],
                "sql_fp": fingerprint,
                "sql_len": len(sql),
                "sql": sql[:4000],
            }
            with self.trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
            if self.trace_path.stat().st_size > 8 * 1024 * 1024:
                lines = self.trace_path.read_text(encoding="utf-8", errors="ignore").splitlines()
                self.trace_path.write_text("\n".join(lines[-5000:]) + "\n", encoding="utf-8")
        except OSError:
            pass
