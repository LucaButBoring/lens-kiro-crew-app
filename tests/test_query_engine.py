from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from query_engine import VIEW_COLUMNS, QueryEngine, QueryError

EXPECTED_VIEW_COLUMNS = {
    "messages": [
        "session_file",
        "role",
        "content",
        "ts",
        "source_user",
        "source_thread",
        "agent",
        "project",
        "model",
        "meta",
        "session_path",
    ],
    "sessions": [
        "session_file",
        "title",
        "created_at",
        "updated_at",
        "agent",
        "model",
        "project",
        "session_path",
    ],
    "cli_messages": [
        "session_file",
        "role",
        "content",
        "ts",
        "msg_type",
        "message_id",
        "session_path",
    ],
    "subagents": [
        "agent_id",
        "session_id",
        "agent",
        "status",
        "turns",
        "max_turns",
        "provider",
        "parent_session",
        "last_tool",
        "task",
        "started",
        "updated_at",
        "state_path",
    ],
    "cron_runs": [
        "run_id",
        "job_id",
        "trigger",
        "started_at",
        "finished_at",
        "duration_ms",
        "status",
        "summary",
        "error",
        "history_path",
    ],
    "tool_calls": [
        "session_file",
        "ts",
        "tool_call_id",
        "tool_name",
        "tool_server",
        "purpose",
        "tool_input",
        "tool_output",
        "done",
        "content",
        "session_path",
        "source",
    ],
    "file_edits": [
        "session_file",
        "ts",
        "path",
        "before",
        "after",
        "before_len",
        "after_len",
        "session_path",
    ],
    "all_messages": ["session_file", "role", "content", "ts", "session_path", "source"],
    "query_log": [
        "ts",
        "elapsed_ms",
        "rc",
        "engine",
        "caller",
        "sql_fp",
        "sql_len",
        "sql",
        "trace_path",
    ],
}


def test_public_view_contract_is_stable() -> None:
    assert VIEW_COLUMNS == EXPECTED_VIEW_COLUMNS


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def engine_with_session(tmp_path: Path) -> QueryEngine:
    crew = tmp_path / "crew"
    kiro = tmp_path / "kiro"
    write_jsonl(
        crew / "sessions" / "dashboard_chat-1.jsonl",
        [
            {
                "_type": "metadata",
                "title": "Test session",
                "created_at": "2026-01-01T00:00:00Z",
                "agent": "default",
                "model": "auto",
                "project": "/tmp/project",
            },
            {
                "role": "user",
                "content": "hello",
                "ts": "2026-01-01T00:00:01Z",
                "meta": {},
            },
            {
                "role": "tool",
                "content": "Running read",
                "ts": "2026-01-01T00:00:02Z",
                "meta": {
                    "tool_call_id": "1",
                    "purpose": "read a file",
                    "input": '{"file_path":"README.md"}',
                    "output": "ok",
                    "done": True,
                },
            },
        ],
    )
    return QueryEngine(crew_home=crew, kiro_home=kiro)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM messages",
        "CREATE TABLE nope(x INT)",
        "SELECT 1; SELECT 2",
        "PRAGMA version",
        "",
    ],
)
def test_rejects_non_read_only_sql(sql: str) -> None:
    with pytest.raises(QueryError):
        QueryEngine.validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "WITH x AS (SELECT 1) SELECT * FROM x",
        "SHOW TABLES",
        "DESCRIBE messages",
        "EXPLAIN SELECT 1",
    ],
)
def test_accepts_read_only_sql(sql: str) -> None:
    assert QueryEngine.validate_sql(sql) == sql


def test_builds_views_over_kiro_crew_records(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    engine = engine_with_session(tmp_path)
    assert engine.query("SELECT count(*) AS n FROM sessions")[0]["n"] == 1
    assert engine.query("SELECT count(*) AS n FROM messages")[0]["n"] == 2
    tool = engine.query("SELECT tool_name, purpose FROM tool_calls")[0]
    assert tool["tool_name"] == "read"
    assert tool["purpose"] == "read a file"


def test_empty_sources_build_and_later_population_rebuilds(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    crew = tmp_path / "crew"
    engine = QueryEngine(crew_home=crew, kiro_home=tmp_path / "kiro")
    assert engine.query("SELECT count(*) AS n FROM sessions")[0]["n"] == 0
    write_jsonl(
        crew / "sessions" / "new.jsonl",
        [{"_type": "metadata", "title": "new", "created_at": "2026-01-01T00:00:00Z"}],
    )
    assert engine.query("SELECT count(*) AS n FROM sessions")[0]["n"] == 1


def test_query_trace_is_visible_on_next_query(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    engine = engine_with_session(tmp_path)
    engine.query("SELECT 1 AS ok")
    rows = engine.query("SELECT count(*) AS n FROM query_log")
    assert rows[0]["n"] >= 1


def complete_engine(tmp_path: Path) -> QueryEngine:
    crew = tmp_path / "crew"
    kiro = tmp_path / "kiro"
    write_jsonl(
        crew / "sessions" / "dashboard_chat-complete.jsonl",
        [
            {
                "_type": "metadata",
                "title": "Complete fixture",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T01:00:00Z",
                "agent": "fixture-agent",
                "model": "fixture-model",
                "project": "/tmp/fixture-project",
            },
            {
                "role": "user",
                "content": "fixture message",
                "ts": "2026-01-01T00:00:01Z",
                "source_user": "user-1",
                "source_thread": "thread-1",
                "agent": "fixture-agent",
                "project": "/tmp/fixture-project",
                "model": "fixture-model",
                "meta": {},
            },
            {
                "role": "tool",
                "content": "Running @files/read",
                "ts": "2026-01-01T00:00:02Z",
                "meta": {
                    "tool_call_id": "tool-1",
                    "purpose": "read fixture",
                    "input": '{"file_path":"fixture.txt"}',
                    "output": "fixture output",
                    "done": True,
                    "file_changes": [
                        {"path": "fixture.txt", "before": "old", "after": "new"}
                    ],
                },
            },
        ],
    )
    write_jsonl(
        kiro / "sessions" / "cli" / "cli-session.jsonl",
        [
            {
                "kind": "Prompt",
                "data": {
                    "content": "cli fixture",
                    "meta": {"timestamp": 1767225603000},
                    "message_id": "cli-message-1",
                },
            }
        ],
    )
    write_jsonl(
        crew / "subagents" / "agent-1" / "state.json",
        [
            {
                "id": "agent-1",
                "session_id": "subagent-session-1",
                "agent": "reviewer",
                "status": "done",
                "turns": 3,
                "max_turns": 10,
                "provider": "fixture-provider",
                "parent_session": "dashboard_chat-complete",
                "last_tool": "read",
                "task": "review fixture",
                "started": 1767225604.0,
                "updated_at": 1767225605.0,
            }
        ],
    )
    write_jsonl(
        crew / "cron-history" / "cron.jsonl",
        [
            {
                "run_id": "run-1",
                "job_id": "job-1",
                "trigger": "schedule",
                "started_at": 1767225606.0,
                "finished_at": 1767225607.0,
                "duration_ms": 1000,
                "status": "success",
                "summary": "fixture complete",
                "error": None,
            }
        ],
    )
    engine = QueryEngine(crew_home=crew, kiro_home=kiro)
    engine.query("SELECT 1 AS ready", caller="fixture-setup")
    return engine


@pytest.mark.parametrize("view", EXPECTED_VIEW_COLUMNS)
def test_every_view_has_exact_columns_and_fixture_rows(
    tmp_path: Path, view: str
) -> None:
    pytest.importorskip("duckdb")
    engine = complete_engine(tmp_path)
    described = engine.query(f'DESCRIBE "{view}"')
    assert [row["column_name"] for row in described] == EXPECTED_VIEW_COLUMNS[view]
    rows = engine.query(f'SELECT * FROM "{view}" LIMIT 1')
    assert rows, f"fixture produced no rows for {view}"
    assert list(rows[0]) == EXPECTED_VIEW_COLUMNS[view]


def test_all_source_and_derived_views_preserve_representative_values(
    tmp_path: Path,
) -> None:
    pytest.importorskip("duckdb")
    engine = complete_engine(tmp_path)

    assert engine.query("SELECT title, agent, model, project FROM sessions") == [
        {
            "title": "Complete fixture",
            "agent": "fixture-agent",
            "model": "fixture-model",
            "project": "/tmp/fixture-project",
        }
    ]
    assert engine.query(
        "SELECT content, source_user, source_thread FROM messages WHERE role = 'user'"
    ) == [
        {
            "content": "fixture message",
            "source_user": "user-1",
            "source_thread": "thread-1",
        }
    ]
    assert engine.query(
        "SELECT tool_call_id, tool_name, tool_server, purpose, tool_input, "
        "tool_output, done, source FROM tool_calls"
    ) == [
        {
            "tool_call_id": "tool-1",
            "tool_name": "read",
            "tool_server": "files",
            "purpose": "read fixture",
            "tool_input": '{"file_path":"fixture.txt"}',
            "tool_output": "fixture output",
            "done": True,
            "source": "session",
        }
    ]
    assert engine.query(
        'SELECT path, "before", "after", before_len, after_len FROM file_edits'
    ) == [
        {
            "path": "fixture.txt",
            "before": "old",
            "after": "new",
            "before_len": 3,
            "after_len": 3,
        }
    ]
    assert engine.query("SELECT role, msg_type, message_id FROM cli_messages") == [
        {"role": "user", "msg_type": "Prompt", "message_id": "cli-message-1"}
    ]
    assert engine.query(
        "SELECT agent_id, status, turns, max_turns, last_tool, task FROM subagents"
    ) == [
        {
            "agent_id": "agent-1",
            "status": "done",
            "turns": 3,
            "max_turns": 10,
            "last_tool": "read",
            "task": "review fixture",
        }
    ]
    assert engine.query(
        "SELECT run_id, job_id, duration_ms, status, summary, error FROM cron_runs"
    ) == [
        {
            "run_id": "run-1",
            "job_id": "job-1",
            "duration_ms": 1000,
            "status": "success",
            "summary": "fixture complete",
            "error": None,
        }
    ]
    assert {
        row["source"]
        for row in engine.query("SELECT DISTINCT source FROM all_messages")
    } == {
        "session",
        "cli",
    }
    assert engine.query("SELECT count(*) AS n FROM query_log")[0]["n"] >= 1


@pytest.mark.parametrize("view,columns", EXPECTED_VIEW_COLUMNS.items())
def test_kc_lens_json_smoke_for_every_view(
    tmp_path: Path, view: str, columns: list[str]
) -> None:
    pytest.importorskip("duckdb")
    engine = complete_engine(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "KIROCREW_HOME": str(engine.crew_home),
            "KIRO_HOME": str(engine.kiro_home),
            "KC_LENS_JSON": "1",
        }
    )
    completed = subprocess.run(
        [str(ROOT / "bin" / "kc-lens"), f'SELECT * FROM "{view}" LIMIT 1'],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    rows = json.loads(completed.stdout)
    assert rows, f"kc-lens produced no rows for {view}"
    assert list(rows[0]) == columns


def test_kc_lens_table_output_and_write_rejection(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    engine = complete_engine(tmp_path)
    env = os.environ.copy()
    env.update(
        {"KIROCREW_HOME": str(engine.crew_home), "KIRO_HOME": str(engine.kiro_home)}
    )

    table = subprocess.run(
        [str(ROOT / "bin" / "kc-lens"), "SELECT title FROM sessions"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert table.returncode == 0
    assert "title" in table.stdout
    assert "Complete fixture" in table.stdout

    rejected = subprocess.run(
        [str(ROOT / "bin" / "kc-lens"), "DELETE FROM messages"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert rejected.returncode == 1
    assert "only read-only" in rejected.stderr


def test_kc_lens_stdin_empty_results_usage_and_query_errors(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    engine = complete_engine(tmp_path)
    env = os.environ.copy()
    env.update(
        {"KIROCREW_HOME": str(engine.crew_home), "KIRO_HOME": str(engine.kiro_home)}
    )
    command = [str(ROOT / "bin" / "kc-lens")]

    stdin_query = subprocess.run(
        command,
        input="SELECT count(*) AS sessions FROM sessions",
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert stdin_query.returncode == 0
    assert "sessions" in stdin_query.stdout
    assert "1" in stdin_query.stdout

    no_rows = subprocess.run(
        [*command, "SELECT * FROM sessions WHERE false"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert no_rows.returncode == 0
    assert no_rows.stdout.strip() == "(no rows)"

    usage = subprocess.run(
        command,
        input="",
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert usage.returncode == 2
    assert 'usage: kc-lens "SELECT ..."' in usage.stderr

    query_error = subprocess.run(
        [*command, "SELECT missing_column FROM sessions"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert query_error.returncode == 1
    assert query_error.stderr.startswith("kc-lens:")


def test_extracts_current_tool_display_names(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    crew = tmp_path / "crew"
    kiro = tmp_path / "kiro"
    write_jsonl(
        crew / "sessions" / "dashboard_chat-tools.jsonl",
        [
            {
                "_type": "metadata",
                "title": "Tool formats",
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "role": "tool",
                "content": "🔧 Reading schema.sql:1-80",
                "ts": "2026-01-01T00:00:01Z",
                "meta": {
                    "tool_call_id": "read-1",
                    "input": json.dumps(
                        {"operations": [{"mode": "Line", "path": "/tmp/schema.sql"}]}
                    ),
                },
            },
            {
                "role": "tool",
                "content": "🔧 Searching for 'Reading|Writing' in tests",
                "ts": "2026-01-01T00:00:02Z",
                "meta": {
                    "tool_call_id": "grep-1",
                    "input": json.dumps(
                        {
                            "pattern": "Reading|Writing",
                            "path": "/tmp",
                            "output_mode": "content",
                        }
                    ),
                },
            },
            {
                "role": "tool",
                "content": "🔧 Running: @github/issue_read",
                "ts": "2026-01-01T00:00:03Z",
                "meta": {
                    "tool_call_id": "mcp-1",
                    "input": json.dumps({"issue_number": 1}),
                },
            },
            {
                "role": "tool",
                "content": "🔧 Running a command",
                "ts": "2026-01-01T00:00:04Z",
                "meta": {
                    "tool_call_id": "shell-1",
                    "input": json.dumps({"command": "true"}),
                },
            },
        ],
    )

    rows = QueryEngine(crew_home=crew, kiro_home=kiro).query(
        "SELECT tool_call_id, tool_name, tool_server FROM tool_calls ORDER BY ts"
    )
    assert rows == [
        {"tool_call_id": "read-1", "tool_name": "read", "tool_server": None},
        {"tool_call_id": "grep-1", "tool_name": "grep", "tool_server": None},
        {"tool_call_id": "mcp-1", "tool_name": "issue_read", "tool_server": "github"},
        {"tool_call_id": "shell-1", "tool_name": "shell", "tool_server": None},
    ]


def test_extracts_structured_and_legacy_builtin_tool_names(tmp_path: Path) -> None:
    pytest.importorskip("duckdb")
    crew = tmp_path / "crew"
    write_jsonl(
        crew / "sessions" / "dashboard_chat-builtins.jsonl",
        [
            {
                "_type": "metadata",
                "title": "Built-in formats",
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "role": "tool",
                "content": "🔧 Generating codebase overview",
                "ts": "2026-01-01T00:00:01Z",
                "meta": {
                    "tool_call_id": "code-1",
                    "input": json.dumps(
                        {"operation": "generate_codebase_overview", "path": "/tmp"}
                    ),
                },
            },
            {
                "role": "tool",
                "content": "🔧 Loading tool: github::list_issues",
                "ts": "2026-01-01T00:00:02Z",
                "meta": {
                    "tool_call_id": "search-1",
                    "input": json.dumps({"tool_id": "github::list_issues"}),
                },
            },
            {
                "role": "tool",
                "content": "🔧 Fetching web content",
                "ts": "2026-01-01T00:00:03Z",
                "meta": {
                    "tool_call_id": "fetch-1",
                    "input": json.dumps({"url": "https://example.com"}),
                },
            },
            {
                "role": "tool",
                "content": "🚫 glob",
                "ts": "2026-01-01T00:00:04Z",
                "meta": {
                    "tool_call_id": "glob-1",
                    "input": json.dumps({"pattern": "**/*.py", "path": "/tmp"}),
                },
            },
        ],
    )

    rows = QueryEngine(crew_home=crew, kiro_home=tmp_path / "kiro").query(
        "SELECT tool_call_id, tool_name FROM tool_calls ORDER BY ts"
    )
    assert rows == [
        {"tool_call_id": "code-1", "tool_name": "generate_codebase_overview"},
        {"tool_call_id": "search-1", "tool_name": "tool_search"},
        {"tool_call_id": "fetch-1", "tool_name": "web_fetch"},
        {"tool_call_id": "glob-1", "tool_name": "glob"},
    ]
