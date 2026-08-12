"""Loopback HTTP backend for the Lens Kiro Crew app."""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

_APP_ROOT = Path(__file__).resolve().parent.parent
_VENV_PYTHON = _APP_ROOT / ".venv" / "bin" / "python"
if _VENV_PYTHON.is_file() and Path(sys.executable) != _VENV_PYTHON:
    os.execv(str(_VENV_PYTHON), [str(_VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

from query_engine import APP_NAME, VIEW_COLUMNS, QueryEngine, QueryError

PORT = int(os.environ.get("PORT", "9100"))
VERSION = "0.1.3"
API = "/api"
ENGINE = QueryEngine()
QUERY_SLOTS = threading.BoundedSemaphore(6)
SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SKILL_LIMIT = 200_000
SKILL_PATHS_CTE = """
WITH skill_paths AS (
    SELECT tc.ts, tc.tool_input, json_extract_string(j.value, '$') AS path
    FROM tool_calls AS tc, json_tree(TRY_CAST(tc.tool_input AS JSON)) AS j
    WHERE tc.tool_name = 'read'
      AND j.key IN ('path', 'file_path')
)
"""

CATALOG_ABOUT = {
    "messages": "One row per Kiro Crew session message.",
    "sessions": "One metadata row per Kiro Crew session.",
    "cli_messages": "Kiro CLI replay messages.",
    "subagents": "Spawned-agent state and task metadata.",
    "cron_runs": "Scheduled-job execution history.",
    "tool_calls": "Tool invocations with searchable purpose, input, and output fields.",
    "file_edits": "Files changed during sessions, including before and after text when recorded.",
    "all_messages": "Session and Kiro CLI messages combined with a source label.",
    "query_log": "Bounded local performance records for kc-lens queries.",
}
CATALOG = [
    {"view": view, "about": CATALOG_ABOUT[view], "columns": columns}
    for view, columns in VIEW_COLUMNS.items()
]


def run_query(sql: str, *, timeout: int = 90, caller: str = "lens-backend") -> list[dict[str, Any]]:
    with QUERY_SLOTS:
        return ENGINE.query(sql, timeout=timeout, caller=caller)


def skill_roots() -> list[Path]:
    crew_home = ENGINE.crew_home
    roots = [crew_home / "skills"]
    apps = crew_home / "apps"
    if apps.is_dir():
        roots.extend(path / "skills" for path in apps.iterdir() if (path / "skills").is_dir())
    return roots


def resolve_skill(name: str) -> Path | None:
    if not SKILL_NAME.fullmatch(name):
        return None
    for root in skill_roots():
        candidates = [root / name / "SKILL.md"]
        if root.is_dir():
            candidates.extend(root.glob(f"*/{name}/SKILL.md"))
        root_real = root.resolve()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                resolved.relative_to(root_real)
            except (OSError, ValueError):
                continue
            if resolved.is_file() and resolved.name == "SKILL.md":
                return resolved
    return None


def overview() -> dict[str, Any]:
    totals_rows = run_query(
        "SELECT (SELECT count(*) FROM sessions) AS sessions, "
        "(SELECT count(*) FROM messages) AS messages, "
        "(SELECT count(*) FROM tool_calls) AS tool_calls"
    )
    days = run_query(
        "SELECT CAST(ts AS DATE) AS day, count(DISTINCT session_file) AS sessions "
        "FROM messages WHERE ts >= current_date - INTERVAL 14 DAY "
        "GROUP BY 1 ORDER BY 1"
    )
    tools = run_query(
        "SELECT tool_name, tool_server, count(*) AS calls FROM tool_calls "
        "WHERE tool_name IS NOT NULL GROUP BY 1,2 ORDER BY calls DESC LIMIT 10"
    )
    skills = run_query(
        SKILL_PATHS_CTE
        + "SELECT regexp_extract(path, '/([^/]+)/SKILL\\.md$', 1) AS skill, "
        "count(*) AS reads, CAST(max(ts) AS DATE) AS last_read FROM skill_paths "
        "WHERE regexp_matches(path, '/[^/]+/SKILL\\.md$') GROUP BY 1 "
        "ORDER BY reads DESC LIMIT 10"
    )
    return {
        "totals": totals_rows[0] if totals_rows else {},
        "sessions_by_day": days,
        "top_tools": tools,
        "skill_reads": skills,
    }


def query_cost() -> dict[str, Any]:
    where = "caller IS DISTINCT FROM 'lens-slow-queries'"
    summary = run_query(
        "SELECT count(*) AS calls, count(DISTINCT sql_fp) AS shapes, "
        "CAST(sum(elapsed_ms) AS BIGINT) AS total_ms, min(elapsed_ms) AS floor_ms, "
        "CAST(round(median(elapsed_ms)) AS BIGINT) AS median_ms, "
        "CAST(round(quantile_cont(elapsed_ms, 0.95)) AS BIGINT) AS p95_ms, "
        "max(elapsed_ms) AS max_ms, count(*) FILTER (WHERE rc != 0) AS errors, "
        f"CAST(min(ts) AS VARCHAR) AS since, string_agg(DISTINCT engine, ', ') AS engines FROM query_log WHERE {where}",
        timeout=30,
        caller="lens-slow-queries",
    )
    top = run_query(
        "SELECT sql_fp, count(*) AS calls, CAST(sum(elapsed_ms) AS BIGINT) AS total_ms, "
        "CAST(round(median(elapsed_ms)) AS BIGINT) AS median_ms, max(elapsed_ms) AS max_ms, "
        "count(*) FILTER (WHERE rc != 0) AS errors, CAST(max(ts) AS VARCHAR) AS last_seen, "
        "string_agg(DISTINCT caller, ', ') AS callers, arg_max(sql, elapsed_ms) AS slowest_sql "
        f"FROM query_log WHERE {where} GROUP BY sql_fp ORDER BY total_ms DESC LIMIT 12",
        timeout=30,
        caller="lens-slow-queries",
    )
    return {"summary": summary[0] if summary else {}, "top": top}


def skill_document(name: str) -> tuple[int, dict[str, Any]]:
    path = resolve_skill(name)
    if path is None:
        return 404, {"error": f"skill {name!r} not found"}
    raw = path.read_text(encoding="utf-8", errors="replace")
    total = raw.count("\n") + 1
    coverage = [0] * total
    events = whole = partial = excluded = 0
    try:
        safe_name = name.replace("'", "''")
        rows = run_query(
            SKILL_PATHS_CTE
            + "SELECT DISTINCT tool_input FROM skill_paths "
            f"WHERE regexp_matches(path, '/{safe_name}/SKILL\\.md$')",
            timeout=60,
            caller="lens-skill-coverage",
        )
    except QueryError:
        rows = []
    # Parameter placeholders are unavailable through the guarded single-statement API;
    # collect coverage conservatively from already-filtered records when supported.
    for row in rows:
        text = str(row.get("tool_input") or "")
        if f"{name}/SKILL.md" not in text:
            continue
        events += 1
        match = re.search(r"(?:head\s+(?:-n\s*|-)|limit[\"']?\s*[:=]\s*)(\d+)", text, re.I)
        if match:
            end = min(total, int(match.group(1)))
            partial += 1
            for index in range(end):
                coverage[index] += 1
        else:
            whole += 1
    return 200, {
        "name": name,
        "path": str(path),
        "content": raw[:SKILL_LIMIT],
        "truncated": len(raw) > SKILL_LIMIT,
        "total_lines": total,
        "coverage": coverage,
        "read_events": events,
        "excluded_events": excluded,
        "whole_reads": whole,
        "partial_reads": partial,
        "pre_edit_excluded": 0,
        "since": time.strftime("%Y-%m-%d", time.gmtime(path.stat().st_mtime)),
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "Lens/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/health":
                state = ENGINE.dependency_status()
                code = 200 if state["available"] else 503
                self.send_json(code, {"status": "ok" if code == 200 else "degraded", "app": APP_NAME, "engine": state})
            elif parsed.path == f"{API}/status":
                self.send_json(200, {"app": APP_NAME, "version": VERSION})
            elif parsed.path == f"{API}/catalog":
                self.send_json(200, {"views": CATALOG})
            elif parsed.path == f"{API}/overview":
                self.send_json(200, overview())
            elif parsed.path == f"{API}/slow-queries":
                self.send_json(200, query_cost())
            elif parsed.path == f"{API}/setup":
                engine = ENGINE.dependency_status()
                sources = ENGINE.source_counts()
                query_ok = False
                query_error = None
                if engine["available"]:
                    try:
                        run_query("SELECT 1 AS ok", timeout=20, caller="lens-setup")
                        query_ok = True
                    except QueryError as exc:
                        query_error = str(exc)
                self.send_json(200, {"ok": engine["available"] and query_ok, "engine": engine, "sources": sources, "query": {"ok": query_ok, "error": query_error}})
            elif parsed.path == f"{API}/skill":
                name = parse_qs(parsed.query).get("name", [""])[0].strip()
                code, payload = skill_document(name)
                self.send_json(code, payload)
            else:
                self.send_json(404, {"error": "not found"})
        except (QueryError, OSError, ValueError) as exc:
            self.send_json(500, {"error": str(exc)[:500]})

    def send_json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


if __name__ == "__main__":
    print(f"Lens backend listening on 127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
