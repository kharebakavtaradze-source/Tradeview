/**
 * Raw Pattern Study — Feature Discovery
 * Phase 5A: page shell + runs list + launch form + run selection + run header.
 * Phase 5B (future): episode features table with group filters.
 * Phase 5C (future): comparison charts.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import Head from 'next/head';
import AppNav from '../components/AppNav';
import styles from '../styles/RawPatternStudy.module.css';

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

function ago(s) {
  if (!s) return '';
  const ms   = Date.now() - new Date(s).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1)  return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const MAP = {
    pending:  styles.statusPending,
    running:  styles.statusRunning,
    complete: styles.statusComplete,
    error:    styles.statusError,
  };
  return (
    <span className={`${styles.statusBadge} ${MAP[status] || styles.statusPending}`}>
      {status || 'unknown'}
    </span>
  );
}

// ── Run header card ───────────────────────────────────────────────────────────

function RunHeader({ run }) {
  const isRunning = run.status === 'running';
  return (
    <div className={styles.runHeader}>
      <div className={styles.runHeaderTop}>
        <span className={styles.runIdLabel}>Run #{run.id}</span>
        <StatusBadge status={run.status} />
        {isRunning && <span className={styles.pulsingDot} />}
      </div>

      <div className={styles.runMeta}>
        <span>{fmtDate(run.start_date)} → {fmtDate(run.end_date)}</span>
        {run.pump_study_run_id != null && (
          <span>Pump Study #{run.pump_study_run_id}</span>
        )}
        {run.created_at && <span>{ago(run.created_at)}</span>}
        {run.finished_at && <span>Finished {ago(run.finished_at)}</span>}
      </div>

      <div className={styles.runCounts}>
        <div className={styles.countItem}>
          <span className={styles.countVal}>{fmtNum(run.raw_daily_count)}</span>
          <span className={styles.countLabel}>Daily Features</span>
        </div>
        <div className={styles.countItem}>
          <span className={styles.countVal}>{fmtNum(run.episode_feature_count)}</span>
          <span className={styles.countLabel}>Episodes</span>
        </div>
        <div className={styles.countItem}>
          <span className={styles.countVal}>{fmtNum(run.comparison_count)}</span>
          <span className={styles.countLabel}>Comparisons</span>
        </div>
      </div>

      {run.notes && (
        <div className={styles.runNotes}>{run.notes}</div>
      )}
      {run.error_message && (
        <div className={styles.errorMsg}>{run.error_message}</div>
      )}
    </div>
  );
}

// ── Group config ──────────────────────────────────────────────────────────────

const GROUPS = ['4x_pump', 'normal_winner', 'false_positive', 'missed_mover'];

const GROUP_COLOR = {
  '4x_pump':       'var(--lime)',
  'normal_winner': 'var(--cyan)',
  'false_positive':'var(--amber)',
  'missed_mover':  'var(--text-muted)',
};

function GroupBadge({ type }) {
  const color = GROUP_COLOR[type] || 'var(--text-muted)';
  return (
    <span style={{
      color, fontWeight: 700, fontSize: 9, letterSpacing: '0.05em',
      padding: '2px 6px', borderRadius: 'var(--r-pill)',
      background: `${color}18`, border: `1px solid ${color}44`,
      whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)',
    }}>{type || '—'}</span>
  );
}

// ── Episode table ─────────────────────────────────────────────────────────────

const EP_COLS = [
  { key: 'symbol',                                  label: 'Symbol',          mono: true  },
  { key: 'group_type',                              label: 'Group',           mono: false },
  { key: 'pump_multiple',                           label: 'Mult',            mono: true,  fmt: v => v != null ? `${Number(v).toFixed(2)}×` : '—' },
  { key: 'pump_type',                               label: 'Type',            mono: true,  fmt: v => v || '—', small: true },
  { key: 'days_in_base',                            label: 'Base d',          mono: true  },
  { key: 'days_from_first_abnormal_volume_to_breakout', label: 'AbVol→Brk', mono: true  },
  { key: 'days_from_breakout_to_peak',              label: 'Brk→Peak',        mono: true  },
  { key: 'max_volume_anomaly_pre',                  label: 'MaxVol×',         mono: true,  fmt: v => v != null ? Number(v).toFixed(1) : '—' },
  { key: 'abnormal_volume_day_count_pre',           label: 'AbVolDays',       mono: true  },
  { key: 'had_compression',                         label: 'Comp?',           mono: true,  fmt: v => v ? '✓' : '—' },
  { key: 'compression_days_pre',                    label: 'CmpDays',         mono: true  },
  { key: 'had_accumulation_like',                   label: 'Acc?',            mono: true,  fmt: v => v ? '✓' : '—' },
  { key: 'had_spring_test_lps',                     label: 'Spr?',            mono: true,  fmt: v => v ? '✓' : '—' },
  { key: 'avg_body_pct_pre',                        label: 'AvgBody',         mono: true,  fmt: v => v != null ? `${(v * 100).toFixed(0)}%` : '—' },
  { key: 'bullish_engulfing_count_pre',             label: 'BullEng',         mono: true  },
  { key: 'reclaim_bar_count_pre',                   label: 'Reclaim',         mono: true  },
];

function EpisodeTable({ episodes, symFilter, setSymFilter, groupFilter, setGroupFilter }) {
  const filtered = episodes.filter(ep => {
    if (symFilter   && !ep.symbol?.toLowerCase().includes(symFilter.toLowerCase())) return false;
    if (groupFilter && ep.group_type !== groupFilter) return false;
    return true;
  });

  return (
    <div className={styles.tableCard}>
      <div className={styles.tableHeader}>
        <span className={styles.tableTitle}>Episode Features ({filtered.length})</span>
        <div className={styles.filterRow}>
          <input
            className={styles.filterInput}
            placeholder="Symbol…"
            value={symFilter}
            onChange={e => setSymFilter(e.target.value)}
          />
          <select
            className={styles.filterSelect}
            value={groupFilter}
            onChange={e => setGroupFilter(e.target.value)}
          >
            <option value="">All groups</option>
            {GROUPS.map(g => <option key={g} value={g}>{g}</option>)}
          </select>
        </div>
      </div>

      {filtered.length === 0 && <div className={styles.statusMsg}>No episodes match.</div>}

      {filtered.length > 0 && (
        <div className={styles.tableScroll}>
          <table className={styles.dataTable}>
            <thead>
              <tr>
                {EP_COLS.map(c => (
                  <th key={c.key} className={styles.dataHead}>{c.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((ep, i) => (
                <tr key={ep.episode_id ?? i} className={styles.dataRow}>
                  {EP_COLS.map(c => {
                    const raw = ep[c.key];
                    const val = c.fmt ? c.fmt(raw) : (raw ?? '—');
                    if (c.key === 'group_type') return (
                      <td key={c.key} className={styles.dataCell}>
                        <GroupBadge type={raw} />
                      </td>
                    );
                    return (
                      <td key={c.key} className={styles.dataCell}
                        style={{
                          fontFamily: c.mono ? 'var(--font-mono)' : undefined,
                          fontSize: c.small ? 9 : undefined,
                          color: val === '—' ? 'var(--text-muted)' : undefined,
                        }}>
                        {val}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Comparison grid ───────────────────────────────────────────────────────────

const COMP_FEATURES = [
  'max_volume_anomaly_pre', 'median_volume_anomaly_pre', 'abnormal_volume_day_count_pre',
  'dryup_day_count_pre', 'had_compression', 'compression_days_pre',
  'avg_body_pct_pre', 'avg_upper_wick_pct_pre', 'avg_lower_wick_pct_pre',
  'bullish_engulfing_count_pre', 'reclaim_bar_count_pre', 'expansion_bar_count_pre',
  'had_accumulation_like', 'had_spring_test_lps', 'days_in_base', 'days_from_breakout_to_peak',
];

function fmtStat(v) {
  if (v == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const n = Number(v);
  if (Math.abs(n) < 10) return n.toFixed(2);
  return n.toFixed(0);
}

function ComparisonGrid({ comparisons }) {
  // Pivot: { feature → { group → row } }
  const pivot = {};
  for (const c of comparisons) {
    if (!pivot[c.feature_name]) pivot[c.feature_name] = {};
    pivot[c.feature_name][c.group_name] = c;
  }

  const features = COMP_FEATURES.filter(f => pivot[f]);

  if (features.length === 0) {
    return <div className={styles.statusMsg}>No comparison data yet.</div>;
  }

  return (
    <div className={styles.tableCard}>
      <div className={styles.tableHeader}>
        <span className={styles.tableTitle}>Feature Comparisons</span>
        <span className={styles.tableHint}>median (n=members)</span>
      </div>
      <div className={styles.tableScroll}>
        <table className={styles.dataTable}>
          <thead>
            <tr>
              <th className={styles.dataHead} style={{ minWidth: 200 }}>Feature</th>
              {GROUPS.map(g => (
                <th key={g} className={styles.dataHead} style={{ color: GROUP_COLOR[g] }}>{g}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {features.map(feat => (
              <tr key={feat} className={styles.dataRow}>
                <td className={styles.dataCell} style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-dim)' }}>
                  {feat}
                </td>
                {GROUPS.map(g => {
                  const row = pivot[feat]?.[g];
                  return (
                    <td key={g} className={styles.dataCell} style={{ fontFamily: 'var(--font-mono)' }}>
                      {row ? (
                        <>
                          <span style={{ fontWeight: 700 }}>{fmtStat(row.median_value)}</span>
                          <span style={{ fontSize: 9, color: 'var(--text-muted)', marginLeft: 4 }}>
                            n={row.member_count}
                          </span>
                        </>
                      ) : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RawPatternStudy() {
  // Runs list
  const [runs,        setRuns]        = useState([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [runsError,   setRunsError]   = useState('');

  // Selected run detail
  const [selectedId,  setSelectedId]  = useState(null);
  const [run,         setRun]         = useState(null);
  const [loadingRun,  setLoadingRun]  = useState(false);

  // Episodes
  const [episodes,        setEpisodes]        = useState([]);
  const [loadingEpisodes, setLoadingEpisodes] = useState(false);
  const [episodesError,   setEpisodesError]   = useState('');
  const [symFilter,       setSymFilter]       = useState('');
  const [groupFilter,     setGroupFilter]     = useState('');

  // Comparisons
  const [comparisons,    setComparisons]    = useState([]);
  const [loadingComps,   setLoadingComps]   = useState(false);
  const [compsError,     setCompsError]     = useState('');

  // Active tab in main panel
  const [activeTab, setActiveTab] = useState('episodes');

  // Launch form
  const [psRunId,   setPsRunId]   = useState('');
  const [notes,     setNotes]     = useState('');
  const [launching, setLaunching] = useState(false);
  const [launchErr, setLaunchErr] = useState('');

  const pollRef = useRef(null);

  // ── Fetch runs list ────────────────────────────────────────────────────────
  const loadRuns = useCallback(async () => {
    setLoadingRuns(true);
    setRunsError('');
    try {
      const r    = await fetch(`${API_URL}/api/replay/raw-pattern-study/runs?limit=40`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setRuns(data.runs || []);
    } catch (e) {
      setRunsError(String(e));
    } finally {
      setLoadingRuns(false);
    }
  }, []);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  // ── Fetch one run detail ───────────────────────────────────────────────────
  const loadRun = useCallback(async (id) => {
    setLoadingRun(true);
    try {
      const r    = await fetch(`${API_URL}/api/replay/raw-pattern-study/${id}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setRun(data.run || null);
    } catch {
      setRun(null);
    } finally {
      setLoadingRun(false);
    }
  }, []);

  // ── Fetch episodes ─────────────────────────────────────────────────────────
  const loadEpisodes = useCallback(async (id) => {
    setLoadingEpisodes(true);
    setEpisodesError('');
    try {
      const r    = await fetch(`${API_URL}/api/replay/raw-pattern-study/${id}/episodes?limit=2000`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setEpisodes(data.episodes || []);
    } catch (e) {
      setEpisodesError(String(e));
    } finally {
      setLoadingEpisodes(false);
    }
  }, []);

  // ── Fetch comparisons ──────────────────────────────────────────────────────
  const loadComparisons = useCallback(async (id) => {
    setLoadingComps(true);
    setCompsError('');
    try {
      const r    = await fetch(`${API_URL}/api/replay/raw-pattern-study/${id}/comparisons`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setComparisons(data.comparisons || []);
    } catch (e) {
      setCompsError(String(e));
    } finally {
      setLoadingComps(false);
    }
  }, []);

  // ── Load episode + comparison data when run becomes complete ───────────────
  useEffect(() => {
    if (!selectedId || !run) return;
    if (run.status === 'complete') {
      loadEpisodes(selectedId);
      loadComparisons(selectedId);
    }
  }, [selectedId, run?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Reset child data when run changes ─────────────────────────────────────
  useEffect(() => {
    setEpisodes([]);
    setComparisons([]);
    setSymFilter('');
    setGroupFilter('');
    setActiveTab('episodes');
  }, [selectedId]);

  // ── Poll if selected run is still running ──────────────────────────────────
  useEffect(() => {
    clearInterval(pollRef.current);
    if (!selectedId) return;
    loadRun(selectedId);
    if (run?.status === 'running') {
      pollRef.current = setInterval(() => {
        loadRun(selectedId);
        loadRuns();
      }, POLL_MS);
    }
    return () => clearInterval(pollRef.current);
  }, [selectedId, run?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Launch ─────────────────────────────────────────────────────────────────
  const handleLaunch = async () => {
    if (!psRunId) { setLaunchErr('Pump Study Run ID is required'); return; }
    setLaunching(true);
    setLaunchErr('');
    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/run`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          pump_study_run_id: Number(psRunId),
          ...(notes ? { notes } : {}),
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
      setSelectedId(data.raw_run_id);
      setPsRunId('');
      setNotes('');
      await loadRuns();
    } catch (e) {
      setLaunchErr(String(e));
    } finally {
      setLaunching(false);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <>
      <Head><title>Raw Pattern Study — Pump Scout</title></Head>
      <div className={styles.page}>
        <AppNav />

        <div className={styles.header}>
          <div className={styles.advisory}>Research</div>
          <h1 className={styles.title}>Raw Pattern Study</h1>
          <p className={styles.subtitle}>
            Feature discovery across 4× pump / normal winner / false positive / missed mover groups
          </p>
        </div>

        <div className={styles.layout}>
          {/* ── Left side panel ─────────────────────────────────────────── */}
          <div className={styles.sidePanel}>

            {/* Launch form */}
            <div className={styles.runPanel}>
              <div className={styles.runPanelTitle}>Launch New Run</div>
              {launchErr && <div className={styles.errorMsg}>{launchErr}</div>}
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Pump Study Run ID</label>
                <input
                  className={styles.formInput}
                  type="number"
                  min="1"
                  placeholder="e.g. 42"
                  value={psRunId}
                  onChange={e => setPsRunId(e.target.value)}
                />
              </div>
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Notes (optional)</label>
                <input
                  className={styles.formInput}
                  type="text"
                  placeholder="e.g. baseline v1"
                  value={notes}
                  onChange={e => setNotes(e.target.value)}
                />
              </div>
              <button
                className={styles.runBtn}
                disabled={launching}
                onClick={handleLaunch}
              >
                {launching ? 'Launching…' : 'Launch Run'}
              </button>
            </div>

            {/* Runs list */}
            <div className={styles.runsWrap}>
              <div className={styles.sectionTitle}>
                <span>Runs</span>
                <button className={styles.refreshBtn} onClick={loadRuns} title="Refresh">↻</button>
              </div>

              {loadingRuns && <div className={styles.statusMsg}>Loading…</div>}
              {runsError  && <div className={styles.errorMsg}>{runsError}</div>}
              {!loadingRuns && !runsError && runs.length === 0 && (
                <div className={styles.statusMsg}>No runs yet — launch one above.</div>
              )}

              {runs.length > 0 && (
                <table className={styles.historyTable}>
                  <thead>
                    <tr className={styles.historyHead}>
                      <th>ID</th>
                      <th>Status</th>
                      <th>Range</th>
                      <th>Daily</th>
                      <th>Eps</th>
                      <th>Cmp</th>
                      <th>Age</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map(r => (
                      <tr
                        key={r.id}
                        className={`${styles.historyRow}${selectedId === r.id ? ' ' + styles.historyRowActive : ''}`}
                        onClick={() => setSelectedId(r.id)}
                      >
                        <td><span className={styles.runId}>#{r.id}</span></td>
                        <td><StatusBadge status={r.status} /></td>
                        <td style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', lineHeight: 1.5 }}>
                          {fmtDate(r.start_date)}<br />{fmtDate(r.end_date)}
                        </td>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{fmtNum(r.raw_daily_count)}</td>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{fmtNum(r.episode_feature_count)}</td>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{fmtNum(r.comparison_count)}</td>
                        <td style={{ fontSize: 9, color: 'var(--text-muted)' }}>{ago(r.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* ── Main panel ──────────────────────────────────────────────── */}
          <div className={styles.mainPanel}>
            {!selectedId && (
              <div className={styles.emptyState}>
                Select a run from the list, or launch a new one above.
              </div>
            )}

            {selectedId && loadingRun && (
              <div className={styles.statusMsg}>Loading run #{selectedId}…</div>
            )}

            {selectedId && !loadingRun && !run && (
              <div className={styles.errorMsg}>
                Could not load run #{selectedId}.
              </div>
            )}

            {selectedId && !loadingRun && run && (
              <>
                <RunHeader run={run} />

                {/* Tab row */}
                <div className={styles.tabRow}>
                  {['episodes', 'comparisons'].map(tab => (
                    <button
                      key={tab}
                      className={`${styles.tab}${activeTab === tab ? ' ' + styles.tabActive : ''}`}
                      onClick={() => setActiveTab(tab)}
                    >
                      {tab === 'episodes' ? `Episodes (${episodes.length})` : 'Comparisons'}
                    </button>
                  ))}
                </div>

                {/* Episodes tab */}
                {activeTab === 'episodes' && (
                  loadingEpisodes
                    ? <div className={styles.statusMsg}>Loading episodes…</div>
                    : episodesError
                      ? <div className={styles.errorMsg}>{episodesError}</div>
                      : run.status !== 'complete'
                        ? <div className={styles.statusMsg}>Episodes available after run completes.</div>
                        : <EpisodeTable
                            episodes={episodes}
                            symFilter={symFilter}
                            setSymFilter={setSymFilter}
                            groupFilter={groupFilter}
                            setGroupFilter={setGroupFilter}
                          />
                )}

                {/* Comparisons tab */}
                {activeTab === 'comparisons' && (
                  loadingComps
                    ? <div className={styles.statusMsg}>Loading comparisons…</div>
                    : compsError
                      ? <div className={styles.errorMsg}>{compsError}</div>
                      : run.status !== 'complete'
                        ? <div className={styles.statusMsg}>Comparisons available after run completes.</div>
                        : <ComparisonGrid comparisons={comparisons} />
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
