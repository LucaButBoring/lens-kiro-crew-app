CREATE OR REPLACE VIEW messages AS
SELECT regexp_replace(filename, '^.*/', '') AS session_file,
       role, content,
       TRY_CAST(ts AS TIMESTAMP) AS ts,
       source_user, source_thread, agent, project, model, meta,
       filename AS session_path
FROM read_json(@@SESSIONS@@,
     columns={'role':'VARCHAR','content':'VARCHAR','ts':'VARCHAR',
              'source_user':'VARCHAR','source_thread':'VARCHAR','agent':'VARCHAR',
              'project':'VARCHAR','model':'VARCHAR',
              'meta':'STRUCT(tool_call_id VARCHAR, purpose VARCHAR, "input" VARCHAR, "output" VARCHAR, done BOOLEAN, file_changes STRUCT(path VARCHAR, "before" VARCHAR, "after" VARCHAR)[])'},
     format='newline_delimited', filename=true,
     maximum_object_size=134217728, ignore_errors=true)
WHERE role IS NOT NULL;

CREATE OR REPLACE VIEW sessions AS
SELECT regexp_replace(filename, '^.*/', '') AS session_file,
       title,
       TRY_CAST(created_at AS TIMESTAMP) AS created_at,
       COALESCE(TRY_CAST(updated_at AS TIMESTAMP), TRY_CAST(created_at AS TIMESTAMP)) AS updated_at,
       agent, model, project,
       filename AS session_path
FROM read_json(@@SESSIONS@@,
     columns={'title':'VARCHAR','created_at':'VARCHAR','updated_at':'VARCHAR',
              'agent':'VARCHAR','model':'VARCHAR','project':'VARCHAR','_type':'VARCHAR'},
     format='newline_delimited', filename=true,
     maximum_object_size=134217728, ignore_errors=true)
WHERE _type = 'metadata';

CREATE OR REPLACE VIEW cli_messages AS
SELECT regexp_replace(filename, '^.*/', '') AS session_file,
       CASE kind
           WHEN 'Prompt' THEN 'user'
           WHEN 'AssistantMessage' THEN 'assistant'
           WHEN 'ToolResults' THEN 'tool'
           ELSE kind
       END AS role,
       to_json(data.content) AS content,
       epoch_ms(data.meta."timestamp") AS ts,
       kind AS msg_type,
       data.message_id AS message_id,
       filename AS session_path
FROM read_json(@@CLI@@,
     columns={'kind':'VARCHAR',
              'data':'STRUCT(content JSON, meta STRUCT("timestamp" BIGINT), message_id VARCHAR)'},
     format='newline_delimited', filename=true,
     maximum_object_size=134217728, ignore_errors=true)
WHERE kind IN ('Prompt', 'AssistantMessage', 'ToolResults');

CREATE OR REPLACE VIEW subagents AS
SELECT id AS agent_id,
       session_id,
       agent, status, turns, max_turns, provider,
       parent_session, last_tool, task,
       epoch_ms(TRY_CAST(round(started * 1000) AS BIGINT)) AS started,
       epoch_ms(TRY_CAST(round(updated_at * 1000) AS BIGINT)) AS updated_at,
       filename AS state_path
FROM read_json(@@SUBAGENTS@@,
     columns={'id':'VARCHAR','session_id':'VARCHAR','agent':'VARCHAR','status':'VARCHAR',
              'turns':'BIGINT','max_turns':'BIGINT','provider':'VARCHAR',
              'parent_session':'VARCHAR','last_tool':'VARCHAR','task':'VARCHAR',
              'started':'DOUBLE','updated_at':'DOUBLE'},
     format='newline_delimited', filename=true,
     maximum_object_size=134217728, ignore_errors=true)
WHERE id IS NOT NULL;

CREATE OR REPLACE VIEW cron_runs AS
SELECT run_id, job_id, trigger,
       epoch_ms(TRY_CAST(round(started_at * 1000) AS BIGINT)) AS started_at,
       epoch_ms(TRY_CAST(round(finished_at * 1000) AS BIGINT)) AS finished_at,
       duration_ms, status, summary, error,
       filename AS history_path
FROM read_json(@@CRON@@,
     columns={'run_id':'VARCHAR','job_id':'VARCHAR','trigger':'VARCHAR',
              'started_at':'DOUBLE','finished_at':'DOUBLE','duration_ms':'BIGINT',
              'status':'VARCHAR','summary':'VARCHAR','error':'VARCHAR'},
     format='newline_delimited', filename=true,
     maximum_object_size=134217728, ignore_errors=true)
WHERE run_id IS NOT NULL;

CREATE OR REPLACE VIEW tool_calls AS
SELECT session_file, ts,
       meta.tool_call_id AS tool_call_id,
       COALESCE(
           NULLIF(regexp_extract(content, '@[A-Za-z0-9_-]+/([A-Za-z0-9_]+)', 1), ''),
           NULLIF(regexp_extract(content, 'mcp__[A-Za-z0-9_-]+__([A-Za-z0-9_]+)', 1), ''),
           NULLIF(json_extract_string(TRY_CAST(meta.input AS JSON), '$.operation'), ''),
           CASE regexp_extract(content, '^[^A-Za-z]*(Reading|Searching|Finding|Writing|Loading|Fetching|Introspecting|Spawning|AWS|glob)', 1)
               WHEN 'Reading' THEN 'read'
               WHEN 'Searching' THEN 'grep'
               WHEN 'Finding' THEN 'glob'
               WHEN 'Writing' THEN 'write'
               WHEN 'Loading' THEN 'tool_search'
               WHEN 'Fetching' THEN 'web_fetch'
               WHEN 'Introspecting' THEN 'introspect'
               WHEN 'Spawning' THEN 'spawn_sub_agents'
               WHEN 'AWS' THEN 'use_aws'
               WHEN 'glob' THEN 'glob'
           END,
           NULLIF(regexp_extract(content, '^(?:Running|Ran|Executing)[:]?[[:space:]]+([A-Za-z0-9_]+)$', 1), ''),
           CASE
               WHEN meta.input LIKE '%"command"%' THEN 'shell'
               WHEN meta.input LIKE '%"operations"%' THEN 'read'
               WHEN meta.input LIKE '%"file_path"%' AND meta.input LIKE '%"old_string"%' THEN 'edit'
               WHEN meta.input LIKE '%"file_path"%' AND meta.input LIKE '%"content"%' THEN 'write'
               WHEN meta.input LIKE '%"file_path"%' THEN 'read'
               WHEN meta.input LIKE '%"output_mode"%' AND meta.input LIKE '%"pattern"%' THEN 'grep'
               ELSE 'tool'
           END
       ) AS tool_name,
       COALESCE(
           NULLIF(regexp_extract(content, '@([A-Za-z0-9_-]+)/[A-Za-z0-9_]+', 1), ''),
           NULLIF(regexp_extract(content, 'mcp__([A-Za-z0-9_-]+)__', 1), '')
       ) AS tool_server,
       meta.purpose AS purpose,
       meta.input AS tool_input,
       meta.output AS tool_output,
       meta.done AS done,
       content,
       session_path,
       'session' AS source
FROM messages
WHERE role = 'tool' OR meta.tool_call_id IS NOT NULL;

CREATE OR REPLACE VIEW file_edits AS
SELECT m.session_file, m.ts, fc.path AS path,
       fc.before AS before, fc.after AS after,
       len(fc.before) AS before_len, len(fc.after) AS after_len,
       m.session_path
FROM messages m, UNNEST(m.meta.file_changes) AS t(fc)
WHERE m.meta.file_changes IS NOT NULL;

CREATE OR REPLACE VIEW all_messages AS
SELECT session_file, role, content, ts, session_path, 'session' AS source FROM messages
UNION ALL
SELECT session_file, role, TRY_CAST(content AS VARCHAR), ts, session_path, 'cli' AS source FROM cli_messages;

CREATE OR REPLACE VIEW query_log AS
SELECT TRY_CAST(ts AS TIMESTAMP) AS ts,
       elapsed_ms, rc, engine, caller, sql_fp, sql_len, sql,
       filename AS trace_path
FROM read_json(@@TRACE@@,
     columns={'ts':'VARCHAR','elapsed_ms':'BIGINT','rc':'BIGINT','engine':'VARCHAR',
              'caller':'VARCHAR','sql_fp':'VARCHAR','sql_len':'BIGINT','sql':'VARCHAR'},
     format='newline_delimited', filename=true,
     maximum_object_size=134217728, ignore_errors=true)
WHERE elapsed_ms IS NOT NULL;
