/**
 * Pump Study — 4× Historical Pump Research
 * Phase 5A: page shell + runs list + run selection.
 * Phase 5B: episodes table with filters + row selection.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import Head from 'next/head';
import AppNav from '../components/AppNav';
import styles from '../styles/PumpStudy.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const POLL_MS = 3000;

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(s) {
  if (!s) return '—';
  return String(s).slice(0, 10);
}

function fmtNum(n) {
  if (n == null) return '—';
  return Number(n).toLocaleString();
}

function fmtX(n) {
  if (n == null) return '—';
  return `${Number(n).toFixed(2)}×`;
}

function fmtPct(n, sign = false) {
  if (n == null) return '—';
  const v = Number(n);
  return `${sign && v > 0 ? '+' : ''}${v.toFixed(1)}%`;
}

function ago(s) {
  if (!s) return '';
  const ms = Date.now() - new Date(s).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1)  return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Pump-type badge ───────────────────────────────────────────────────────────

const PUMP_TYPE_CFG = {
  ACCUMULATION_TO_EXPANSION: { short: 'ACC→EXP',   color: '#00e5ff' },
  POST_COMPRESSION_BREAKOUT: { short: 'POST-COMP',  color: '#00ff88' },
  CATALYST_IGNITION:         { short: 'CATALYST',   color: '#ffd600' },
  GAP_AND_GO:                { short: 'GAP&GO',     color: '#ff8800' },
  LOW_FLOAT_VELOCITY:        { short: 'LO-FLOAT',   color: '#ff4400' },
  CHAOTIC_SPECULATIVE:       { short: 'CHAOTIC',    color: '#cc44ff' },
  SECTOR_SYMPATHY:           { short: 'SYMPATHY',   color: '#80aaff' },
  UNKNOWN:                   { short: 'UNKNOWN',    color: '#555555' },
};

function PumpTypeBadge({ type }) {
  if (!type) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const cfg   = PUMP_TYPE_CFG[type] || { short: type, color: '#888' };
  const color = cfg.color;
  return (
    <span style={{
      color,
      fontWeight: 700,
      fontSize: 9,
      letterSpacing: '0.05em',
      padding: '2px 6px',
      borderRadius: 'var(--r-pill)',
      background: `${color}18`,
      border: `1px solid ${color}44`,
      whiteSpace: 'nowrap',
      fontFamily: 'var(--font-mono)',
    }}>
      {cfg.short}
    </span>
  );
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const cls = {
    running:             styles.statusRunning,
    detecting:           styles.statusRunning,
    enriching:           styles.statusRunning,
    completed:           styles.statusCompleted,
    comparison_complete: styles.statusComplete2,
    failed:              styles.statusFailed,
  }[status] || '';
  return (
    <span className={`${styles.statusBadge} ${cls}`}>{status || 'unknown'}</span>
  );
}

// ── Episodes table (Phase 5B) ─────────────────────────────────────────────────

const PUMP_TYPES = [
  '', 'ACCUMULATION_TO_EXPANSION', 'POST_COMPRESSION_BREAKOUT',
  'CATALYST_IGNITION', 'GAP_AND_GO', 'LOW_FLOAT_VELOCITY',
  'CHAOTIC_SPECULATIVE', 'SECTOR_SYMPATHY', 'UNKNOWN',
];

function EpisodesTable({ runId, episodes, loading, error, selectedEpId, onSelectEp, onReload }) {
  // ── Local filter state ──────────────────────────────────────────────────────
  const [symInput,    setSymInput]    = useState('');
  const [typeFilter,  setTypeFilter]  = useState('');
  const [mulInput,    setMulInput]    = useState('');
  const [caughtMode,  setCaughtMode]  = useState('all'); // 'all' | 'caught' | 'missed'

  // Expose composed filter object to parent via callback when filters change
  useEffect(() => {
    onReload({ symbol: symInput.trim().toUpperCase(), pump_type: typeFilter,
               min_multiple: mulInput.trim(), caught_mode: caughtMode });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeFilter, caughtMode]);

  function applyText() {
    onReload({ symbol: symInput.trim().toUpperCase(), pump_type: typeFilter,
               min_multiple: mulInput.trim(), caught_mode: caughtMode });
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div>
      {/* Filter row */}
      <div className={styles.filterRow}>
        <input
          className={styles.filterInput}
          placeholder="Symbol…"
          value={symInput}
          onChange={e => setSymInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && applyText()}
        />
        <select
          className={styles.filterSelect}
          value={typeFilter}
          onChange={e => setTypeFilter(e.target.value)}
        >
          {PUMP_TYPES.map(t => (
            <option key={t} value={t}>{t ? (PUMP_TYPE_CFG[t]?.short || t) : 'All Types'}</option>
          ))}
        </select>
        <input
          className={styles.filterInput}
          style={{ width: 72 }}
          placeholder="Min ×"
          value={mulInput}
          onChange={e => setMulInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && applyText()}
        />
        <div className={styles.modeToggle}>
          {[['all', 'All'], ['caught', 'Caught'], ['missed', 'Missed']].map(([v, label]) => (
            <button
              key={v}
              type="button"
              className={`${styles.modeBtn} ${caughtMode === v ? styles.modeBtnActive : ''}`}
              onClick={() => setCaughtMode(v)}
            >{label}</button>
          ))}
        </div>
        <button className={styles.exportBtn} onClick={applyText}>Apply</button>
        {loading && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>Loading…</span>}
      </div>

      {/* States */}
      {error && (
        <div className={styles.errorMsg}>{error}</div>
      )}
      {!loading && !error && episodes.length === 0 && (
        <div className={styles.emptyMsg}>No episodes match the current filters.</div>
      )}

      {/* Table */}
      {episodes.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className={styles.episodeTable}>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Start</th>
                <th>Peak</th>
                <th title="Peak / start price">Multiple</th>
                <th title="% gain from start to peak">Return</th>
                <th title="Trading days from start to peak">Days</th>
                <th>Family</th>
                <th title="Was it in scanner output on start date?">Caught</th>
                <th title="Had qualifying ribbon class in PRE window">Ribbon</th>
                <th title="Had ignition signal in PRE window">Ignition</th>
                <th title="Highest Wyckoff state reached in PRE window">Wyckoff</th>
                <th title="Largest gap up % in PRE+PUMP window">Max Gap</th>
                <th title="Max volume vs 20-day average">Max Vol</th>
              </tr>
            </thead>
            <tbody>
              {episodes.map(ep => {
                const caught = ep.caught_by_scanner;
                return (
                  <tr
                    key={ep.id}
                    className={`${styles.episodeRow} ${selectedEpId === ep.id ? styles.episodeRowActive : ''}`}
                    onClick={() => onSelectEp(ep.id)}
                  >
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--accent)' }}>
                      {ep.symbol}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10, whiteSpace: 'nowrap' }}>
                      {fmtDate(ep.pump_start_date)}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10, whiteSpace: 'nowrap' }}>
                      {fmtDate(ep.pump_peak_date)}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--lime)' }}>
                      {fmtX(ep.pump_multiple)}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--lime)' }}>
                      {ep.pump_return_pct != null ? fmtPct(ep.pump_return_pct, true) : '—'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
                      {ep.pump_days_to_peak ?? '—'}
                    </td>
                    <td><PumpTypeBadge type={ep.pump_type} /></td>
                    <td>
                      {caught == null
                        ? <span style={{ color: 'var(--text-muted)' }}>—</span>
                        : <span style={{ fontWeight: 700, fontSize: 10, color: caught ? 'var(--lime)' : 'var(--red)' }}>
                            {caught ? 'CAUGHT' : 'MISSED'}
                          </span>
                      }
                    </td>
                    <td style={{ fontWeight: 700, fontSize: 10,
                                 color: ep.had_ribbon ? 'var(--lime)' : 'var(--text-muted)' }}>
                      {ep.had_ribbon ? 'YES' : 'NO'}
                    </td>
                    <td style={{ fontWeight: 700, fontSize: 10,
                                 color: ep.had_ignition ? 'var(--cyan)' : 'var(--text-muted)' }}>
                      {ep.had_ignition ? 'YES' : 'NO'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-dim)' }}>
                      {ep.strongest_wyckoff_state || '—'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
                      {ep.largest_gap_pct != null ? fmtPct(ep.largest_gap_pct) : '—'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)',
                                 color: ep.max_volume_anomaly >= 3 ? 'var(--amber)' : 'var(--text-dim)' }}>
                      {ep.max_volume_anomaly != null ? `${Number(ep.max_volume_anomaly).toFixed(1)}×` : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', padding: '6px 2px' }}>
            {episodes.length} episode{episodes.length !== 1 ? 's' : ''}
            {selectedEpId && ' — click again to deselect'}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Runs list ─────────────────────────────────────────────────────────────────

function RunsList({ runs, selectedId, onSelect, loading }) {
  if (loading) {
    return <div className={styles.statusMsg}>Loading runs…</div>;
  }
  if (!runs.length) {
    return (
      <div className={styles.emptyMsg}>
        No runs found.
        <div className={styles.emptyHint}>
          Pump studies are launched via the backend API.<br />
          POST /api/replay/pump-study/run
        </div>
      </div>
    );
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className={styles.historyTable}>
        <thead>
          <tr className={styles.historyHead}>
            <th>ID</th>
            <th>Created</th>
            <th>Status</th>
            <th>Range</th>
            <th title="Raw detections before clustering">Raws</th>
            <th title="Merged clusters">Clust</th>
            <th title="4× episodes after dedup">Eps</th>
            <th title="Daily indicator snapshots">Snaps</th>
            <th title="Timeline milestone events">Events</th>
            <th>Min ×</th>
          </tr>
        </thead>
        <tbody>
          {runs.map(r => (
            <tr
              key={r.id}
              className={`${styles.historyRow} ${selectedId === r.id ? styles.historyRowActive : ''}`}
              onClick={() => onSelect(r.id)}
            >
              <td>
                <span className={styles.runId}>#{r.id}</span>
              </td>
              <td style={{ fontSize: 10, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>
                {fmtDate(r.created_at)}<br />
                <span style={{ color: 'var(--text-muted)', fontSize: 9 }}>{ago(r.created_at)}</span>
              </td>
              <td><StatusBadge status={r.status} /></td>
              <td style={{ fontSize: 10, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>
                {fmtDate(r.start_date)}<br />
                <span style={{ color: 'var(--text-muted)', fontSize: 9 }}>→ {fmtDate(r.end_date)}</span>
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                {fmtNum(r.raw_detection_count)}
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                {fmtNum(r.cluster_count)}
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700 }}>
                {fmtNum(r.episode_count)}
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                {fmtNum(r.snapshot_count)}
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                {fmtNum(r.event_count)}
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)' }}>
                {r.min_multiple != null ? `${r.min_multiple}×` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Run detail header (Phase 5A only — no tabs/content yet) ──────────────────

function RunDetailHeader({ run }) {
  if (!run) return null;

  const isRunning = ['running', 'detecting', 'enriching'].includes(run.status);

  const kpis = [
    { label: 'Raw Detections', value: fmtNum(run.raw_detection_count) },
    { label: 'Clusters',       value: fmtNum(run.cluster_count) },
    { label: 'Episodes',       value: fmtNum(run.episode_count) },
    { label: 'Snapshots',      value: fmtNum(run.snapshot_count) },
    { label: 'Events',         value: fmtNum(run.event_count) },
    { label: 'Window',         value: run.window_days != null ? `${run.window_days}d` : '—' },
    { label: 'Min Multiple',   value: run.min_multiple != null ? `${run.min_multiple}×` : '—' },
    { label: 'Min Volume',     value: run.min_volume != null ? fmtNum(run.min_volume) : '—' },
  ];

  return (
    <div className={styles.bundleSection}>
      {/* Status row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <StatusBadge status={run.status} />
        {isRunning && <span className={styles.pulsingDot} />}
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)' }}>
          Run #{run.id}
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {fmtDate(run.start_date)} → {fmtDate(run.end_date)}
        </span>
        <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 'auto' }}>
          Created {ago(run.created_at)}
        </span>
      </div>

      {/* KPI grid */}
      <div className={styles.summaryGrid}>
        {kpis.map(k => (
          <div key={k.label} className={styles.summaryKPI}>
            <div className={styles.kpiValue}>{k.value}</div>
            <div className={styles.kpiLabel}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* Notes */}
      {run.notes?.run_summary && (
        <div className={styles.notesBlock} style={{ marginTop: 12 }}>
          {run.notes.run_summary}
        </div>
      )}

    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PumpStudyPage() {
  const [runs,        setRuns]        = useState([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [selectedId,  setSelectedId]  = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const [runLoading,  setRunLoading]  = useState(false);
  const pollRef = useRef(null);

  // Episodes state
  const [episodes,    setEpisodes]    = useState([]);
  const [epLoading,   setEpLoading]   = useState(false);
  const [epError,     setEpError]     = useState('');
  const [selectedEpId, setSelectedEpId] = useState(null);
  const epFiltersRef = useRef({ symbol: '', pump_type: '', min_multiple: '', caught_mode: 'all' });

  // ── Load runs list ────────────────────────────────────────────────────────

  const loadRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const res  = await fetch(`${API_URL}/api/replay/pump-study/runs?limit=30`);
      const data = await res.json();
      setRuns(data.runs || []);
    } catch {
      // network failure — leave existing list intact
    } finally {
      setRunsLoading(false);
    }
  }, []);

  // ── Load single run detail ────────────────────────────────────────────────

  const loadRun = useCallback(async (runId) => {
    if (!runId) return;
    setRunLoading(true);
    try {
      const res  = await fetch(`${API_URL}/api/replay/pump-study/${runId}`);
      const data = await res.json();
      setSelectedRun(data.run || data);
    } catch {
      setSelectedRun(null);
    } finally {
      setRunLoading(false);
    }
  }, []);

  // ── Load episodes ─────────────────────────────────────────────────────────

  const loadEpisodes = useCallback(async (runId, filters = {}) => {
    if (!runId) return;
    epFiltersRef.current = { ...epFiltersRef.current, ...filters };
    const f = epFiltersRef.current;
    setEpLoading(true);
    setEpError('');
    try {
      const params = new URLSearchParams({ limit: 500 });
      if (f.symbol)       params.set('symbol',       f.symbol);
      if (f.pump_type)    params.set('pump_type',    f.pump_type);
      if (f.min_multiple) params.set('min_multiple', f.min_multiple);
      if (f.caught_mode === 'caught') params.set('caught_only', 'true');
      if (f.caught_mode === 'missed') params.set('missed_only', 'true');
      const res  = await fetch(`${API_URL}/api/replay/pump-study/${runId}/episodes?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setEpisodes(data.episodes || []);
    } catch (err) {
      setEpError(err.message || 'Failed to load episodes');
      setEpisodes([]);
    } finally {
      setEpLoading(false);
    }
  }, []);

  // ── Initial load ──────────────────────────────────────────────────────────

  useEffect(() => { loadRuns(); }, [loadRuns]);

  // ── Poll while run is active ──────────────────────────────────────────────

  useEffect(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }

    if (!selectedId) return;

    loadRun(selectedId);

    const isActive = !selectedRun ||
      ['running', 'detecting', 'enriching'].includes(selectedRun?.status);

    if (isActive) {
      pollRef.current = setInterval(() => {
        loadRun(selectedId);
        loadRuns();
      }, POLL_MS);
    }

    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Stop polling once run reaches terminal state
  useEffect(() => {
    const terminal = ['completed', 'comparison_complete', 'failed'];
    if (selectedRun && terminal.includes(selectedRun.status)) {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    }
  }, [selectedRun?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load episodes whenever a run is selected (reset filters)
  useEffect(() => {
    if (!selectedId) { setEpisodes([]); return; }
    epFiltersRef.current = { symbol: '', pump_type: '', min_multiple: '', caught_mode: 'all' };
    setSelectedEpId(null);
    loadEpisodes(selectedId);
  }, [selectedId, loadEpisodes]);

  function handleSelectRun(runId) {
    if (selectedId === runId) return; // already selected
    setSelectedId(runId);
    setSelectedRun(null);
  }

  function handleSelectEp(epId) {
    setSelectedEpId(prev => prev === epId ? null : epId); // toggle
  }

  function handleEpReload(filters) {
    loadEpisodes(selectedId, filters);
  }

  return (
    <>
      <Head><title>Pump Study — Pump Scout</title></Head>
      <AppNav />

      <div className={styles.page}>
        {/* ── Header ──────────────────────────────────────────────────────── */}
        <div className={styles.header}>
          <div className={styles.advisory}>RESEARCH ONLY — NOT INVESTMENT ADVICE</div>
          <h1 className={styles.title}>4× Pump Study</h1>
          <p className={styles.subtitle}>
            Retrospective analysis of historical 4× moves — episode classification,
            signal attribution, and comparison groups.
          </p>
        </div>

        {/* ── Body ────────────────────────────────────────────────────────── */}
        <div style={{ padding: '0 var(--page-px)', display: 'flex', flexDirection: 'column', gap: 20 }}>

          {/* Runs section */}
          <div className={styles.bundleSection}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <div className={styles.bundleSectionTitle} style={{ margin: 0, border: 'none', padding: 0 }}>
                PUMP STUDY RUNS
              </div>
              <button
                className={styles.exportBtn}
                onClick={loadRuns}
                disabled={runsLoading}
              >
                {runsLoading ? 'Refreshing…' : 'Refresh'}
              </button>
            </div>
            <div style={{ height: 1, background: 'var(--border)', margin: '10px 0 14px' }} />
            <RunsList
              runs={runs}
              selectedId={selectedId}
              onSelect={handleSelectRun}
              loading={runsLoading}
            />
          </div>

          {/* Selected run detail */}
          {selectedId && (
            <div>
              {runLoading && !selectedRun && (
                <div className={styles.statusMsg}>Loading run #{selectedId}…</div>
              )}
              {selectedRun && <RunDetailHeader run={selectedRun} />}
            </div>
          )}

          {/* Episodes table */}
          {selectedId && (
            <div className={styles.bundleSection}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <div className={styles.bundleSectionTitle} style={{ margin: 0, border: 'none', padding: 0 }}>
                  EPISODES
                </div>
                {selectedEpId && (
                  <span style={{ fontSize: 10, color: 'var(--accent)', fontFamily: 'var(--font-mono)' }}>
                    episode #{selectedEpId} selected — detail coming in Phase 5C
                  </span>
                )}
              </div>
              <div style={{ height: 1, background: 'var(--border)', margin: '10px 0 14px' }} />
              <EpisodesTable
                runId={selectedId}
                episodes={episodes}
                loading={epLoading}
                error={epError}
                selectedEpId={selectedEpId}
                onSelectEp={handleSelectEp}
                onReload={handleEpReload}
              />
            </div>
          )}

        </div>
      </div>
    </>
  );
}
