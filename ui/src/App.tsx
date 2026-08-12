import { useState, useEffect, useRef } from 'react'
import { useAppApi } from '@kirocrew/app-sdk'
import { PageHeader, StatCard, Card, CardTitle, Badge, EmptyState, Skeleton } from '@kirocrew/app-sdk/ui'
import { ChevronRight, Check, AlertTriangle, Search } from 'lucide-react'
import { format as sqlFormat } from 'sql-formatter'

const API = '/apps/lens-kiro-crew-app/api'

interface Overview {
  totals: { sessions?: number; messages?: number; tool_calls?: number }
  sessions_by_day: { day: string; sessions: number }[]
  top_tools: { tool_name: string; tool_server: string | null; calls: number }[]
  skill_reads: { skill: string; reads: number; last_read: string }[]
}
interface CatalogView { view: string; about: string; columns: string[] }

/**
 * Narrow-viewport detector via matchMedia (not Tailwind breakpoints: classes that
 * appear only in app dist are absent from the dashboard's compiled CSS).
 */
function useNarrow(maxWidth = 560) {
  const [narrow, setNarrow] = useState(() => window.matchMedia(`(max-width: ${maxWidth}px)`).matches)
  useEffect(() => {
    const mq = window.matchMedia(`(max-width: ${maxWidth}px)`)
    const onChange = (e: MediaQueryListEvent) => setNarrow(e.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [maxWidth])
  return narrow
}

/**
 * Ranked bar row. Bars are linear (length ∝ count): sqrt was tried to make the
 * outlier-dominated mid-range legible, but unlabeled non-linear bars read as
 * broken — proportionality is the viewer's default assumption, and exact values
 * sit in the count column anyway. On narrow viewports the row wraps to two lines
 * (label/badge/count above a full-width track) — one line cannot fit label +
 * badge + a meaningful track, so any single-line reallocation is zero-sum.
 */
function BarRow({ label, sub, value, max, narrow, onLabelClick }: { label: string; sub?: string | null; value: number; max: number; narrow: boolean; onLabelClick?: () => void }) {
  const badge = sub
    ? <span className="text-[10px] px-1.5 py-0.5 rounded bg-border text-muted whitespace-nowrap truncate">{sub}</span>
    : <span className="text-[10px] px-1.5 py-0.5 whitespace-nowrap" style={{ color: 'var(--muted)', opacity: 0.55 }}>built-in</span>
  const bar = (
    <div className="h-2 rounded" style={{ width: `${(value / max) * 100}%`, minWidth: '4px', background: 'var(--accent)' }} />
  )
  const labelEl = onLabelClick
    ? <button type="button" onClick={onLabelClick} title={label}
        className="flex-1 min-w-0 truncate text-left hover:underline"
        style={{ color: 'var(--accent)', background: 'none', border: 'none', padding: 0, cursor: 'pointer', font: 'inherit' }}>{label}</button>
    : <span className="flex-1 min-w-0 truncate" title={label}>{label}</span>
  if (narrow) {
    return (
      <div className="flex flex-col gap-1 text-sm">
        <div className="flex items-center gap-2">
          {labelEl}
          {badge}
          <span className="shrink-0 text-right text-[11px] text-muted whitespace-nowrap">{value.toLocaleString()}</span>
        </div>
        {bar}
      </div>
    )
  }
  return (
    <div className="flex items-center gap-2 text-sm">
      {labelEl}
      <span className="w-24 shrink-0 flex justify-end">{badge}</span>
      <div className="shrink-0 flex items-center gap-2 min-w-0" style={{ flexBasis: 'clamp(120px, 30%, 320px)' }}>
        <div className="flex-1 min-w-0">{bar}</div>
        <span className="w-12 shrink-0 text-right text-[11px] text-muted whitespace-nowrap">{value.toLocaleString()}</span>
      </div>
    </div>
  )
}

/** Skeleton mirroring BarRow's shape — label, badge, bar of varied width. */
function BarRowSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-2">
          <div className="flex-1 min-w-0"><Skeleton className="h-4 w-3/4" /></div>
          <div className="w-24 shrink-0 flex justify-end"><Skeleton className="h-4 w-16" /></div>
          <div className="shrink-0 flex items-center gap-2" style={{ flexBasis: 'clamp(120px, 30%, 320px)' }}>
            <div className="flex-1 min-w-0"><Skeleton className="h-2" style={{ width: `${75 - (i * 23) % 55}%` }} /></div>
            <div className="w-12 shrink-0 flex justify-end"><Skeleton className="h-3 w-8" /></div>
          </div>
        </div>
      ))}
    </div>
  )
}

/** Zero-fill a sparse day series into 14 consecutive days ending at the data's
 * max day (anchoring on the data avoids client-clock / timezone mismatch). */
function fillDays(byDay: { day: string; sessions: number }[]): { day: string; sessions: number }[] {
  if (byDay.length === 0) return []
  const counts = new Map(byDay.map(d => [d.day.slice(0, 10), d.sessions]))
  const end = new Date(`${byDay[byDay.length - 1].day.slice(0, 10)}T00:00:00Z`)
  return Array.from({ length: 14 }).map((_, i) => {
    const d = new Date(end); d.setUTCDate(end.getUTCDate() - (13 - i))
    const key = d.toISOString().slice(0, 10)
    return { day: key, sessions: counts.get(key) ?? 0 }
  })
}

/** Vertical histogram — one column per day, height scaled to the series max.
 * Labels: localized numeric month/day, every fifth column anchored on the most
 * recent day. Hover: a two-line popover (full date small, count normal). */
function DayHistogram({ days }: { days: { day: string; sessions: number }[] }) {
  const max = Math.max(1, ...days.map(d => d.sessions))
  const fmtShort = new Intl.DateTimeFormat(undefined, { month: '2-digit', day: '2-digit' })
  const fmtFull = new Intl.DateTimeFormat(undefined, { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' })
  return (
    <div className="flex items-end gap-1.5" style={{ height: '112px' }}>
      {days.map((d, i) => {
        const date = new Date(`${d.day}T00:00:00`)
        const labeled = (days.length - 1 - i) % 5 === 0
        // Edge columns clamp the popover to the card side instead of centering.
        const pos = i < 2 ? 'left-0' : i > days.length - 3 ? 'right-0' : 'left-1/2 -translate-x-1/2'
        return (
          <div key={d.day} className="relative flex-1 flex flex-col items-center gap-1 min-w-0 group">
            <div
              className={`absolute bottom-full mb-1.5 ${pos} px-2.5 py-1.5 rounded-md border border-border bg-card shadow-md whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none z-10`}
              role="tooltip"
            >
              <div className="text-[10px] text-muted leading-tight">{fmtFull.format(date)}</div>
              <div className="text-sm leading-tight">{d.sessions} session{d.sessions === 1 ? '' : 's'}</div>
            </div>
            <div
              className="w-full rounded-t"
              style={{
                height: `${(d.sessions / max) * 72}px`,
                minHeight: d.sessions > 0 ? '3px' : '1px',
                background: d.sessions > 0 ? 'var(--accent)' : 'var(--border)',
              }}
            />
            <span className="text-[10px] text-muted leading-none h-2.5 whitespace-nowrap">
              {labeled ? fmtShort.format(date) : ''}
            </span>
          </div>
        )
      })}
    </div>
  )
}

/** Loading placeholder matching DayHistogram's column geometry. */
function DayHistogramSkeleton() {
  return (
    <div className="flex items-end gap-1.5" style={{ height: '112px' }}>
      {Array.from({ length: 14 }).map((_, i) => (
        <div key={i} className="flex-1 flex flex-col items-center gap-1">
          <Skeleton className="w-full rounded-t" style={{ height: `${16 + (i * 29) % 56}px` }} />
          <div className="h-2.5">{(13 - i) % 5 === 0 && <Skeleton className="h-2.5 w-7" />}</div>
        </div>
      ))}
    </div>
  )
}

interface SetupState {
  ok: boolean
  engine: { available: boolean; version: string | null }
  sources: Record<string, number>
  query: { ok: boolean; error?: string | null }
}

/** Max characters of server-supplied error text rendered in the UI. */
const ERROR_TEXT_LIMIT = 200

function friendlyError(e: unknown): string {
  const raw = String((e as { message?: string } | null)?.message ?? e ?? '').replace(/\s+/g, ' ').trim()
  if (!raw) return 'Request failed'
  const [, status = '', rest = raw] = /^API (\d{3}):\s*([\s\S]*)$/.exec(raw) ?? []
  let detail = rest.trim()
  if (/<!doctype|<html/i.test(detail)) detail = /<title[^>]*>([^<]+)<\/title>/i.exec(detail)?.[1]?.trim() || 'server returned an HTML error page'
  if (detail.length > ERROR_TEXT_LIMIT) detail = `${detail.slice(0, ERROR_TEXT_LIMIT - 1)}…`
  return [status && `API ${status}`, detail || 'request failed'].filter(Boolean).join(': ')
}

function SetupCard() {
  const api = useAppApi()
  const [state, setState] = useState<SetupState | null>(null)
  useEffect(() => {
    let alive = true
    api.get<SetupState>(`${API}/setup`).then(s => { if (alive) setState(s) }).catch(() => {})
    return () => { alive = false }
  }, [])
  if (!state) return null
  if (state.ok && (state.sources.sessions ?? 0) === 0) {
    return (
      <Card className="mt-6">
        <CardTitle>No session records found</CardTitle>
        <div className="flex gap-2 text-sm items-start mt-2">
          <span style={{ color: 'var(--warn)', display: 'inline-flex', marginTop: '1px' }}><AlertTriangle size={14} /></span>
          <p className="m-0 text-muted">Lens could not find local Kiro Crew session records. Confirm that this account has existing sessions and restart Lens.</p>
        </div>
      </Card>
    )
  }
  if (state.ok) {
    return (
      <div className="text-[11px] mt-3" style={{ color: 'var(--muted)', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}><Check size={12} style={{ color: 'var(--ok)' }} /> query service ready</span>
        <span style={{ opacity: 0.7 }}>DuckDB {state.engine.version} · {state.sources.sessions ?? 0} session files</span>
      </div>
    )
  }
  const code = (s: string) => <code className="text-[11px] px-1 py-0.5 rounded" style={{ background: 'var(--bg)', border: '1px solid var(--border)' }}>{s}</code>
  return (
    <Card className="mt-6">
      <CardTitle>Setup needed</CardTitle>
      <div className="flex gap-2 text-sm items-start mt-2">
        <span style={{ color: 'var(--warn)', display: 'inline-flex', marginTop: '1px' }}><AlertTriangle size={14} /></span>
        <div>
          <div>{state.engine.available ? 'The query service could not initialize.' : 'DuckDB is not installed.'}</div>
          <div className="text-[12px] mt-0.5" style={{ color: 'var(--muted)' }}>
            Reinstall Lens from its source directory with {code('kirocrew app install /absolute/path/to/lens-kiro-crew-app')}, then restart the app.
            {state.query.error ? ` ${friendlyError(state.query.error)}` : ''}
          </div>
        </div>
      </div>
    </Card>
  )
}

interface SkillDoc { name: string; path: string; content: string; truncated?: boolean; total_lines?: number; coverage?: number[]; read_events?: number; excluded_events?: number; whole_reads?: number; partial_reads?: number; pre_edit_excluded?: number; since?: string }

interface SlowSummary {
  calls: number; shapes: number
  total_ms: number | null; floor_ms: number | null; median_ms: number | null
  p95_ms: number | null; max_ms: number | null; errors: number
  since: string | null; engines: string | null
}
interface SlowShape {
  sql_fp: string; calls: number; total_ms: number; median_ms: number; max_ms: number
  errors: number; last_seen: string | null; callers: string | null; slowest_sql: string | null
}
interface QueryCost { summary: SlowSummary; top: SlowShape[] }

/** Compact duration: sub-second stays in ms, above that seconds with one decimal. */
function fmtMs(ms: number | null | undefined): string {
  if (ms == null || !isFinite(ms)) return '—'
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`
}

/**
 * Lightweight SQL pretty-printer for the trace's whitespace-collapsed queries:
 * breaks before top-level clauses and boolean connectors, indents subqueries by
 * paren depth, and keeps string literals verbatim. Not a real parser -- returns
 * the original text unchanged if anything unexpected comes up. A dependency
 * (sql-formatter) is the better tool, but npm install cannot run in this
 * workspace: it resolves the whole tree, and the host-provided @kirocrew/app-sdk
 * is not published to the public registry, so every install 404s.
 */
function formatSql(raw: string): string {
  const sql = (raw || '').trim()
  if (!sql) return sql
  // DuckDB SQL tracks the PostgreSQL dialect closely; fall back to the raw
  // (whitespace-collapsed) text if the formatter throws on anything exotic.
  try {
    return sqlFormat(sql, { language: 'postgresql', keywordCase: 'upper' })
  } catch {
    return sql
  }
}

/**
 * Query cost card — ranks recorded kc-lens queries by TOTAL time (calls × duration),
 * because a 300ms query on every prompt costs more than a one-off 2s scan and only
 * the former repays optimizing. Rows expand to the slowest observed SQL for that shape.
 *
 * Self-contained fetch (like SetupCard): hidden entirely on a fetch error, so an
 * installed backend that predates this route degrades to absence, not a false alarm.
 */
function QueryCostCard({ narrow }: { narrow: boolean }) {
  const api = useAppApi()
  const [data, setData] = useState<QueryCost | null>(null)
  const [open, setOpen] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    api.get<QueryCost>(`${API}/slow-queries`)
      .then((d: QueryCost) => { if (alive) setData(d) }).catch(() => {})
    return () => { alive = false }
  }, [])
  if (!data) return null
  const { summary: s, top } = data
  if (!s.calls) {
    return (
      <Card className="mt-3">
        <CardTitle>Query cost</CardTitle>
        <p className="text-sm text-muted mt-1 mb-0">
          No queries traced yet. Every <code>kc-lens</code> query records one bounded local timing row.
        </p>
      </Card>
    )
  }
  const max = Math.max(1, ...top.map(r => r.total_ms))
  const cols = 'minmax(0,1fr) 130px 46px 66px clamp(150px, 26%, 300px)'
  return (
    <Card className="mt-3">
      <CardTitle>Query cost</CardTitle>
      <p className="text-[11px] text-muted mt-1 mb-2">Ranked by total time (calls × duration).</p>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted mb-3">
        <span><span className="text-accent">{s.calls.toLocaleString()}</span> queries</span>
        <span><span className="text-accent">{s.shapes}</span> shapes</span>
        <span>median <span className="text-accent">{fmtMs(s.median_ms)}</span></span>
        <span>p95 <span className="text-accent">{fmtMs(s.p95_ms)}</span></span>
        <span title="Wall-clock timing: every figure includes query-engine startup.">floor <span className="text-accent">{fmtMs(s.floor_ms)}</span></span>
        {s.errors > 0 && <span style={{ color: 'var(--warn)' }}>{s.errors} failed</span>}
        {s.since && <span>since {s.since.slice(0, 16)}</span>}
      </div>
      {!narrow && (
        <div className="text-[10px] text-muted" style={{ display: 'grid', gridTemplateColumns: cols, gap: '12px', padding: '0 0 4px', borderBottom: '1px solid var(--border)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          <span>query shape</span><span>caller</span><span style={{ textAlign: 'right' }}>calls</span><span style={{ textAlign: 'right' }}>median</span><span style={{ textAlign: 'right' }}>total</span>
        </div>
      )}
      <div className="flex flex-col">
        {top.map(r => {
          const expanded = open === r.sql_fp
          const head = (r.slowest_sql || '').replace(/\s+/g, ' ').trim()
          return (
            <div key={r.sql_fp} className="border-b border-border last:border-0">
              <button
                type="button"
                onClick={() => setOpen(expanded ? null : r.sql_fp)}
                aria-expanded={expanded}
                title={head}
                className="w-full text-left"
                style={{ display: narrow ? 'flex' : 'grid', gridTemplateColumns: narrow ? undefined : cols, flexDirection: narrow ? 'column' : undefined, gap: narrow ? '3px' : '12px', alignItems: narrow ? 'stretch' : 'center', background: 'none', border: 'none', padding: '7px 0', cursor: 'pointer', font: 'inherit' }}
              >
                <span style={{ display: 'flex', alignItems: 'center', gap: '5px', minWidth: 0 }}>
                  <ChevronRight size={13} style={{ flexShrink: 0, color: 'var(--muted)', transform: expanded ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }} />
                  <code style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: '12px', color: 'var(--text)' }}>{head || '(empty)'}</code>
                </span>
                {!narrow && <span className="text-[11px] text-muted" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.callers || 'unknown'}>{r.callers || 'unknown'}</span>}
                {!narrow && <span className="text-[11px] text-muted" style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{r.calls}×</span>}
                {!narrow && <span className="text-[11px] text-muted" style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>{fmtMs(r.median_ms)}</span>}
                <span style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
                  <span style={{ flex: 1, minWidth: '40px', height: '6px', borderRadius: '3px', background: 'var(--border)' }}>
                    <span style={{ display: 'block', width: `${(r.total_ms / max) * 100}%`, minWidth: '3px', height: '6px', borderRadius: '3px', background: r.errors > 0 ? 'var(--warn)' : 'var(--accent)' }} />
                  </span>
                  <span className="text-[11px]" style={{ width: '46px', textAlign: 'right', color: 'var(--text)', whiteSpace: 'nowrap' }}>{fmtMs(r.total_ms)}</span>
                </span>
              </button>
              {expanded && (
                <div style={{ paddingBottom: '8px' }}>
                  <div className="text-[11px] text-muted" style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', marginBottom: '6px' }}>
                    <span>{r.callers || 'unknown caller'}</span>
                    <span>{r.calls}× calls</span>
                    <span>median {fmtMs(r.median_ms)}</span>
                    <span>max {fmtMs(r.max_ms)}</span>
                    {r.errors > 0 && <span style={{ color: 'var(--warn)' }}>{r.errors} failed</span>}
                    {r.last_seen && <span>last {r.last_seen.slice(0, 16)}</span>}
                  </div>
                  <pre className="text-[11px] p-2 rounded overflow-x-auto" style={{ background: 'var(--bg)', border: '1px solid var(--border)', color: 'var(--text)', margin: 0, whiteSpace: 'pre', lineHeight: 1.5 }}>{r.slowest_sql ? formatSql(r.slowest_sql) : '(no SQL recorded)'}</pre>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </Card>
  )
}

/**
 * Renders a SKILL.md with a per-line truncation highlight: the left strip and
 * row tint turn RED in proportion to how far below the best-covered line each
 * line's PARTIAL-read reach sits — so a bright-red line is one that targeted
 * reads (head -N / sed / offset+limit) usually stop before, meaning it is often
 * truncated away and an agent reading the skill partially can miss it; a well-
 * covered line stays clean. Whole-file reads are excluded upstream (they cover
 * everything and would flatten the signal). Hover a red line for a styled
 * popover explaining the risk. Estimated from tool history; searches and writes are excluded.
 */
// Partial reads needed before the truncation heat renders at full intensity. Below this
// the map is faded: one partial read makes severity binary (0 or 1) against a maxHits of
// 1, so a single early stop would otherwise paint the whole tail full-red on no real
// distribution. Scaling by sample size keeps the signal visible but honestly faint until
// enough partial reads accumulate to trust it.
const PARTIAL_READS_FOR_FULL_HEAT = 4

function SkillBody({ skill }: { skill: SkillDoc }) {
  const lines = skill.content.split('\n')
  const cov = skill.coverage || []
  const maxHits = cov.reduce((m, h) => Math.max(m, h), 0)
  const partial = skill.partial_reads ?? 0
  // Reach (severity) says WHERE partial reads stop; confidence says HOW MUCH to trust
  // that, given how few reads back it. Multiplied into the rendered intensity only --
  // the tooltip's "X of Y reads" reports the raw reach unchanged.
  const confidence = Math.min(partial, PARTIAL_READS_FOR_FULL_HEAT) / PARTIAL_READS_FOR_FULL_HEAT
  const preEdit = skill.pre_edit_excluded ?? 0
  const since = skill.since
  // JS-driven hover (not CSS group-hover): arbitrary Tailwind hover classes from
  // app dist aren't in the dashboard's compiled CSS, so inline styles + state.
  const [hover, setHover] = useState<number | null>(null)
  return (
    <>
      <div className="text-[11px] mb-2 flex items-center gap-2 flex-wrap" style={{ color: 'var(--muted)' }}>
        {cov.length === 0
          ? <span>read-coverage estimate unavailable</span>
          : maxHits === 0
            ? <span>only whole-file reads recorded, so nothing is truncated</span>
            : <span className="flex items-center gap-1" style={{ cursor: 'help' }} title="Partial read: a head -N or offset+limit read that stops before the end of the file. Whole-file reads are excluded from the heat.">rarely truncated
                <span style={{ display: 'inline-block', width: '40px', height: '8px', borderRadius: '2px', background: 'linear-gradient(90deg, transparent, var(--danger))' }} />often truncated</span>}
        {maxHits > 0 && partial < PARTIAL_READS_FOR_FULL_HEAT && (
          <span
            title={`Only ${partial} partial read${partial === 1 ? "" : "s"} since the last edit — too few to rank lines confidently, so the heat is faded. It darkens as more partial reads accumulate (full strength at ${PARTIAL_READS_FOR_FULL_HEAT}).`}
          >
            faded ({partial} partial read{partial === 1 ? "" : "s"})
          </span>
        )}
        {preEdit > 0 && since && (
          <span
            title={`Reads from before the last edit (${since}) are excluded: their line numbers referenced an older version of this file.`}
          >
            {preEdit} pre-edit read{preEdit === 1 ? "" : "s"} excluded
          </span>
        )}
      </div>
      <div style={{ fontFamily: 'ui-monospace, SFMono-Regular, monospace', fontSize: '12px', lineHeight: '1.5' }}>
        {lines.map((line, i) => {
          const hits = cov[i] || 0
          // Invert the reach signal: severity = how far below the best-covered
          // line this one sits. Redder = targeted reads more often stop before
          // it, i.e. it is likelier to be truncated away on a partial read.
          const severity = maxHits > 0 ? (maxHits - hits) / maxHits : 0
          // Faded by confidence so a sparse sample can't render full-red; reach still
          // gates hover/strip presence, so a faint line stays inspectable.
          const intensity = severity * confidence
          const risk = severity > 0
          return (
            <div key={i}
              style={{ display: 'flex', alignItems: 'stretch', position: 'relative', background: risk ? `color-mix(in srgb, var(--danger) ${Math.round(intensity * 18)}%, transparent)` : 'transparent' }}>
              <span
                onMouseEnter={risk ? () => setHover(i) : undefined}
                onMouseLeave={risk ? () => setHover(h => (h === i ? null : h)) : undefined}
                style={{ flex: '0 0 12px', display: 'flex', alignItems: 'stretch', cursor: risk ? 'help' : 'default' }}>
                <span style={{ width: '4px', borderRadius: '1px', background: 'var(--danger)', opacity: intensity }} />
              </span>
              <span style={{ flex: 1, whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: 'var(--text)' }}>{line || '\u00A0'}</span>
              {risk && hover === i && (
                <div role="tooltip" style={{ position: 'absolute', top: '100%', left: 0, marginTop: '2px', zIndex: 20, maxWidth: '340px', padding: '8px 10px', borderRadius: '6px', background: 'var(--card)', border: '1px solid var(--border)', boxShadow: '0 6px 20px rgba(0,0,0,0.35)', fontSize: '11px', lineHeight: 1.45, color: 'var(--text)', pointerEvents: 'none', whiteSpace: 'normal' }}>
                  <div style={{ fontWeight: 600, color: 'var(--danger)', marginBottom: '3px' }}>Truncation risk</div>
                  Reached by {hits} of {maxHits} partial reads.
                </div>
              )}
            </div>
          )
        })}
        {skill.truncated && <div className="text-[11px] mt-2" style={{ color: 'var(--muted)' }}>… (truncated)</div>}
      </div>
    </>
  )
}

/**
 * Slide-over pane showing a skill's SKILL.md. Lens is a sandboxed iframe and
 * can't drive the dashboard's file panel, so the viewer lives in-app. Geometry
 * is inline-styled (arbitrary Tailwind classes from app dist aren't in the
 * dashboard's compiled CSS).
 */
function SkillDrawer({ skill, name, loadingName, error, onClose }: { skill: SkillDoc | null; name: string | null; loadingName: string | null; error: string | null; onClose: () => void }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  if (!name) return null
  return (
    <>
      <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 40 }} />
      <div role="dialog" aria-label="Skill viewer" style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: 'min(680px, 92vw)', zIndex: 50, background: 'var(--card)', borderLeft: '1px solid var(--border)', boxShadow: '-8px 0 24px rgba(0,0,0,0.2)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', padding: '14px 16px', borderBottom: '1px solid var(--border)' }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div className="text-sm" style={{ fontWeight: 600 }}>{name}</div>
            {skill && <div className="text-[11px] truncate" style={{ color: 'var(--muted)' }} title={skill.path}>{skill.path}</div>}
          </div>
          <button type="button" onClick={onClose} className="text-sm" style={{ background: 'none', border: '1px solid var(--border)', borderRadius: '6px', padding: '2px 8px', cursor: 'pointer', color: 'var(--text)' }}>Close</button>
        </div>
        <div style={{ flex: 1, overflow: 'auto', padding: '16px' }}>
          {error ? <p className="text-sm" style={{ color: 'var(--danger)' }}>{error}</p>
            : loadingName ? <div className="flex flex-col gap-2"><Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-5/6" /></div>
            : skill ? <SkillBody skill={skill} />
            : null}
        </div>
      </div>
    </>
  )
}

export default function Lens() {
  const api = useAppApi()
  const narrow = useNarrow()
  const [skill, setSkill] = useState<SkillDoc | null>(null)
  const [skillName, setSkillName] = useState<string | null>(null)
  const [skillLoading, setSkillLoading] = useState<string | null>(null)
  const [skillErr, setSkillErr] = useState<string | null>(null)

  const skillReqId = useRef(0)
  async function openSkill(name: string) {
    const reqId = ++skillReqId.current  // ignore responses from superseded clicks
    setSkillErr(null); setSkill(null); setSkillName(name); setSkillLoading(name)
    try {
      const doc = await api.get<SkillDoc>(`${API}/skill?name=${encodeURIComponent(name)}`)
      if (reqId === skillReqId.current) setSkill(doc)
    } catch (e: any) {
      if (reqId === skillReqId.current) setSkillErr(friendlyError(e))
    } finally {
      if (reqId === skillReqId.current) setSkillLoading(null)
    }
  }
  const closeSkill = () => { skillReqId.current++; setSkill(null); setSkillName(null); setSkillErr(null); setSkillLoading(null) }
  const [overview, setOverview] = useState<Overview | null>(null)
  const [views, setViews] = useState<CatalogView[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [catalogOpen, setCatalogOpen] = useState(false)

  useEffect(() => {
    let alive = true
    Promise.all([
      api.get<Overview>(`${API}/overview`),
      api.get<{ views: CatalogView[] }>(`${API}/catalog`),
    ])
      .then(([ov, cat]) => { if (!alive) return; setOverview(ov); setViews(cat.views || []) })
      .catch((e) => { if (alive) setError(friendlyError(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])

  const t = overview?.totals || {}
  const byDay = overview?.sessions_by_day || []
  const tools = overview?.top_tools || []
  const skills = overview?.skill_reads || []
  const maxTool = Math.max(1, ...tools.map(x => x.calls))
  const maxSkill = Math.max(1, ...skills.map(x => x.reads))

  return (
    <>
      <PageHeader title="Lens" subtitle="Kiro Crew session history, queryable" />
      <div className="px-6 pb-8 flex-1 min-h-0">
        {error && (
          <div className="mb-6">
            <EmptyState
              icon={<Search size={40} />}
              title="Couldn't reach the session database"
              subtitle={`Lens could not load your local history. No activity totals are shown until the connection is restored. ${error}`}
            />
          </div>
        )}

        <SetupCard />

        {!error && <>
        {/* At a glance (StatCard renders its own skeleton while value is undefined) */}
        <div className="grid gap-3.5 grid-cols-[repeat(auto-fit,minmax(150px,1fr))] mb-4">
          <StatCard label="Sessions" value={loading ? undefined : (t.sessions ?? 0)} accent />
          <StatCard label="Messages" value={loading ? undefined : (t.messages ?? 0)} />
          <StatCard label="Tool calls" value={loading ? undefined : (t.tool_calls ?? 0)} />
        </div>

        {/* Reference: collapsed by default so data outranks documentation */}
        <div className="mt-3">
          <Card>
            <button
              type="button"
              className="w-full flex items-center justify-between text-left"
              onClick={() => setCatalogOpen((o) => !o)}
              aria-expanded={catalogOpen}
            >
              <CardTitle>Query catalog</CardTitle>
              <span className="text-muted" style={{ display: 'inline-flex', alignItems: 'center' }}>
                <ChevronRight size={16} style={{ transform: catalogOpen ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }} />
              </span>
            </button>
            {loading ? (
              <Skeleton className="h-4 w-72 mt-1" />
            ) : (
              <p className="text-sm text-muted mt-1 mb-0">
                {views.length} views over your local Kiro Crew records. Ask the Lens agent to analyze your local history. Queries can read message text, tool inputs and outputs, and file-edit contents; ask for a narrow time range or topic to limit exposure. For example:{" "}
                <span className="text-accent">
                  “Use the Lens SQL tool to show my top tools this week.”
                </span>
              </p>
            )}
            {catalogOpen && !loading && (
              <div className="flex flex-col gap-3 mt-3">
                {views.map((v) => (
                  <div key={v.view} className="border-b border-border pb-2">
                    <div className="flex items-center gap-2">
                      <Badge variant="aim">{v.view}</Badge>
                      <span className="text-sm">{v.about}</span>
                    </div>
                    <div className="text-[11px] text-muted mt-1 flex flex-wrap gap-1">
                      {v.columns.map((c) => (
                        <span key={c} style={{ border: '1px solid var(--border)', borderRadius: '4px', padding: '0 5px' }}>{c}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* Activity: what runs and what gets consulted */}
        <div className="grid gap-3 lg:grid-cols-2 mb-3">
          <Card>
            <CardTitle>Top tools</CardTitle>
            {loading
              ? <BarRowSkeleton rows={8} />
              : tools.length === 0
                ? <p className="text-sm text-muted">No tool calls were found in the session files Lens can currently read.</p>
                : (
                  <div className="flex flex-col gap-1.5">
                    {tools.map(tt => (
                      <BarRow key={`${tt.tool_name}|${tt.tool_server ?? ''}`} label={tt.tool_name} sub={tt.tool_server} value={tt.calls} max={maxTool} narrow={narrow} />
                    ))}
                  </div>
                )}
          </Card>
          <Card>
            <CardTitle>Skill reads</CardTitle>
            <p className="text-[11px] text-muted mb-2">SKILL.md files the agent opened.</p>
            {loading
              ? <BarRowSkeleton rows={8} />
              : skills.length === 0
                ? <p className="text-sm text-muted">No skill reads recorded.</p>
                : (
                  <div className="flex flex-col gap-1.5">
                    {skills.map(s => (
                      <BarRow key={s.skill} label={s.skill} sub={s.last_read} value={s.reads} max={maxSkill} narrow={narrow} onLabelClick={() => openSkill(s.skill)} />
                    ))}
                  </div>
                )}
          </Card>
        </div>

        <QueryCostCard narrow={narrow} />

        {/* Timeline */}
        <Card>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '8px' }}>
            <CardTitle>Sessions</CardTitle>
            <span className="text-[11px] text-muted">last 14 days</span>
          </div>
          {loading
            ? <DayHistogramSkeleton />
            : byDay.length === 0
              ? <p className="text-sm text-muted">No sessions were found in the last 14 days.</p>
              : <DayHistogram days={fillDays(byDay)} />}
        </Card>
        </>}

        <SkillDrawer skill={skill} name={skillName} loadingName={skillLoading} error={skillErr} onClose={closeSkill} />
        {/* Build stamp: identifies which build the browser is actually rendering
            (the bundle URL is unversioned + cached, so screenshots need provenance). */}
        <div className="text-[10px] mt-4 text-center" style={{ color: 'var(--muted)', opacity: 0.6 }}>
          Lens build {typeof __LENS_BUILD__ !== 'undefined' ? __LENS_BUILD__ : 'unknown'}
        </div>
      </div>
    </>
  )
}
