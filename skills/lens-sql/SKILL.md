---
name: lens-sql
description: Query local Kiro Crew session history with kc-lens and DuckDB. Use when analyzing previous sessions, tool usage, file edits, scheduled runs, or the Lens dashboard catalog.
---

# Lens SQL

`kc-lens "SELECT ..."` executes one guarded, read-only DuckDB statement over local Kiro Crew records.

## Views

- `messages`: local Kiro Crew conversation records, including dashboard and channel messages; `content` may contain private conversation text. Columns: `session_file`, `role`, `content`, `ts`, `source_user`, `source_thread`, `agent`, `project`, `model`, `meta`, `session_path`.
- `sessions`: one metadata row per Kiro Crew session. Columns: `session_file`, `title`, `created_at`, `updated_at`, `agent`, `model`, `project`, `session_path`.
- `cli_messages`: Kiro CLI replay messages. Columns: `session_file`, `role`, `content`, `ts`, `msg_type`, `message_id`, `session_path`.
- `subagents`: spawned-agent state and task metadata. Columns: `agent_id`, `session_id`, `agent`, `status`, `turns`, `max_turns`, `provider`, `parent_session`, `last_tool`, `task`, `started`, `updated_at`, `state_path`.
- `cron_runs`: scheduled-job execution history. Columns: `run_id`, `job_id`, `trigger`, `started_at`, `finished_at`, `duration_ms`, `status`, `summary`, `error`, `history_path`.
- `tool_calls`: tool activity extracted from session records; `tool_input` and `tool_output` may contain sensitive command or response text. Columns: `session_file`, `ts`, `tool_call_id`, `tool_name`, `tool_server`, `purpose`, `tool_input`, `tool_output`, `done`, `content`, `session_path`, `source`.
- `file_edits`: changed files recorded by tools; `before` and `after` may contain file contents, so select them only when necessary. Columns: `session_file`, `ts`, `path`, `before`, `after`, `before_len`, `after_len`, `session_path`.
- `all_messages`: `messages` plus `cli_messages`. Columns: `session_file`, `role`, `content`, `ts`, `session_path`, `source`.
- `query_log`: bounded local performance records for prior `kc-lens` queries. Columns: `ts`, `elapsed_ms`, `rc`, `engine`, `caller`, `sql_fp`, `sql_len`, `sql`, `trace_path`.

## Query rules

1. Default to `messages`; use `all_messages` only when CLI replay records are explicitly relevant.
2. Parenthesize every `OR` group so date and session bounds apply to every branch.
3. Scope leading-wildcard searches with a timestamp or session filter.
4. Query by `session_file`, not an unrelated runtime identifier.
5. Select only the content needed for the answer and avoid reproducing unrelated private text.

## Examples

```sql
SELECT session_file, ts, left(content, 120)
FROM messages
WHERE ts >= current_timestamp - INTERVAL 7 DAY
  AND content ILIKE '%deployment%'
ORDER BY ts DESC
LIMIT 40;
```

```sql
SELECT tool_name, count(*) AS calls
FROM tool_calls
WHERE ts >= current_timestamp - INTERVAL 30 DAY
GROUP BY 1
ORDER BY calls DESC;
```

```sql
SELECT ts, purpose, tool_name
FROM tool_calls
WHERE purpose ILIKE '%authentication%'
ORDER BY ts DESC
LIMIT 30;
```
