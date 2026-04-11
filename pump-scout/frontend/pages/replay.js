/**
 * Replay — Historical Backdated Scan Mode
 * Research-only page. Runs the scanner pipeline on past dates with
 * strict temporal isolation (no future leakage).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import Head from 'next/head';
import AppNav from '../components/AppNav';
import styles from '../styles/Replay.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const POLL_MS  = 2000;

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n, decimals = 1) {
  if (n === null || n === undefined) return '—';
  return typeof n === 'number' ? n.toFixed(decimals) : n;
}

function pctCell(v) {
  if (v === null || v === undefined) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const color = v >= 0 ? 'var(--lime)' : 'var(--red)';
  return <span style={{ color, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{v >= 0 ? '+' : ''}{fmt(v)}%</span>;
}

function TierBadge({ tier }) {
  const cls = {
    FIRE: styles.tierFire,
    ARM:  styles.tierArm,
    BASE: styles.tierBase,
    WATCH: styles.tierWatch,
  }[tier] || styles.tierOther;
  return <span className={cls} style={{ fontWeight: 700 }}>{tier || '—'}</span>;
}

function StatusBadge({ status }) {
  const cls = {
    running:   styles.statusRunning,
    completed: styles.statusCompleted,
    failed:    styles.statusFailed,
  }[status] || '';
  return <span className={`${styles.statusBadge} ${cls}`}>{status || 'unknown'}</span>;
}

const OUTCOME_COLORS = {
  SUCCESSFUL_BREAKOUT: 'var(--lime)',
  EARLY_WINNER:        'var(--cyan)',
  NO_FOLLOW_THROUGH:   'var(--text-muted)',
  LATE_SIGNAL:         'var(--amber)',
  FAILED_BREAKOUT:     'var(--red)',
  FALSE_POSITIVE:      '#ff4466',
  NO_DATA:             'var(--text-dim)',
};

function OutcomeLabel({ label }) {
  const color = OUTCOME_COLORS[label] || 'var(--text-muted)';
  const short = {
    SUCCESSFUL_BREAKOUT: 'BREAKOUT',
    EARLY_WINNER:        'EARLY WIN',
    NO_FOLLOW_THROUGH:   'NO FOLLOW',
    LATE_SIGNAL:         'LATE SIG',
    FAILED_BREAKOUT:     'FAILED',
    FALSE_POSITIVE:      'FALSE POS',
    NO_DATA:             'NO DATA',
  }[label] || label;
  return (
    <span style={{
      color, fontWeight: 700, fontSize: 9, letterSpacing: '0.06em',
      padding: '2px 7px', borderRadius: 'var(--r-pill)',
      background: `${color}18`, border: `1px solid ${color}44`,
      whiteSpace: 'nowrap',
    }}>
      {short}
    </span>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ReplayPage() {
  // ── Form state ──────────────────────────────────────────────────────────────
  const [mode, setMode]               = useState('single_day');  // single_day | date_range
  const [singleDate, setSingleDate]   = useState('');
  const [startDate, setStartDate]     = useState('');
  const [endDate, setEndDate]         = useState('');
  const [universeMode, setUniverseMode] = useState('approx');

  // ── Run state ───────────────────────────────────────────────────────────────
  const [launching, setLaunching]     = useState(false);
  const [progress, setProgress]       = useState(null);
  const pollRef                       = useRef(null);

  // ── History + detail ────────────────────────────────────────────────────────
  const [history, setHistory]         = useState([]);
  const [activeRun, setActiveRun]     = useState(null);   // run object
  const [tab, setTab]                 = useState('candidates'); // candidates | outcomes | missed | summary

  const [candidates, setCandidates]   = useState([]);
  const [outcomes, setOutcomes]       = useState([]);
  const [missed, setMissed]           = useState([]);
  const [summary, setSummary]         = useState(null);

  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError]             = useState('');

  // ── Polling ─────────────────────────────────────────────────────────────────

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`${API_URL}/api/replay/status`);
        if (!r.ok) return;
        const p = await r.json();
        setProgress(p);
        if (!p.running) {
          stopPolling();
          // Refresh history + reload active run detail
          loadHistory();
          if (p.run_id) {
            loadRunDetail(p.run_id);
          }
        }
      } catch (_) {}
    }, POLL_MS);
  }, [stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  // ── Data loaders ─────────────────────────────────────────────────────────────

  async function loadHistory() {
    try {
      const r = await fetch(`${API_URL}/api/replay/history?limit=20`);
      if (r.ok) setHistory(await r.json());
    } catch (_) {}
  }

  async function loadRunDetail(runId) {
    setLoadingDetail(true);
    try {
      const [runR, candR, summR] = await Promise.all([
        fetch(`${API_URL}/api/replay/${runId}`),
        fetch(`${API_URL}/api/replay/${runId}/candidates?limit=200`),
        fetch(`${API_URL}/api/replay/${runId}/summary`),
      ]);
      if (runR.ok)  setActiveRun(await runR.json());
      if (candR.ok) setCandidates(await candR.json());
      if (summR.ok) setSummary(await summR.json());
    } catch (_) {}
    setLoadingDetail(false);
  }

  async function loadOutcomes(runId) {
    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}/outcomes?limit=500`);
      if (r.ok) setOutcomes(await r.json());
    } catch (_) {}
  }

  async function loadMissed(runId) {
    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}/missed?limit=100`);
      if (r.ok) setMissed(await r.json());
    } catch (_) {}
  }

  // Initial load
  useEffect(() => {
    loadHistory();
    // Check if a replay is already running
    fetch(`${API_URL}/api/replay/status`)
      .then(r => r.ok ? r.json() : null)
      .then(p => {
        if (p) {
          setProgress(p);
          if (p.running) startPolling();
        }
      })
      .catch(() => {});
  }, []);

  // Load outcomes/missed lazily on tab change
  useEffect(() => {
    if (!activeRun) return;
    if (tab === 'outcomes' && outcomes.length === 0) loadOutcomes(activeRun.id);
    if (tab === 'missed'   && missed.length   === 0) loadMissed(activeRun.id);
  }, [tab, activeRun]);

  // ── Actions ──────────────────────────────────────────────────────────────────

  async function handleRun() {
    setError('');
    const body = mode === 'single_day'
      ? { mode: 'single_day', as_of_date: singleDate, universe_mode: universeMode }
      : { mode: 'date_range',  start_date: startDate, end_date: endDate, universe_mode: universeMode };

    if (mode === 'single_day' && !singleDate) { setError('Select a date.'); return; }
    if (mode === 'date_range' && (!startDate || !endDate)) { setError('Select start and end dates.'); return; }

    setLaunching(true);
    try {
      const r = await fetch(`${API_URL}/api/replay/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) {
        setError(data.detail || 'Failed to start replay.');
        return;
      }
      // Immediately start polling
      const pollStatus = await fetch(`${API_URL}/api/replay/status`);
      if (pollStatus.ok) setProgress(await pollStatus.json());
      startPolling();
      // Refresh history
      setTimeout(loadHistory, 500);
    } catch (e) {
      setError(String(e));
    } finally {
      setLaunching(false);
    }
  }

  function handleSelectRun(run) {
    setActiveRun(run);
    setCandidates([]);
    setOutcomes([]);
    setMissed([]);
    setSummary(null);
    setTab('candidates');
    loadRunDetail(run.id);
  }

  // ── Derived ───────────────────────────────────────────────────────────────────

  const isRunning   = progress?.running === true;
  const runBtnLabel = launching ? 'Launching…' : isRunning ? 'Running…' : 'Run Replay';

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <>
      <Head>
        <title>Replay · Pump Scout</title>
      </Head>
      <AppNav />

      <div className={styles.page}>
        <div className={styles.header}>
          <div className={styles.advisory}>⏪ HISTORICAL REPLAY — RESEARCH ONLY</div>
          <h1 className={styles.title}>Backdated Scan Replay</h1>
          <p className={styles.subtitle}>
            Run the scanner pipeline on past dates with strict temporal isolation.
            No future data is used during the scan.
          </p>
        </div>

        <div className={styles.layout}>
          {/* ── Left: Run panel ─────────────────────────────────────────────── */}
          <div className={styles.runPanel}>
            <div className={styles.runPanelTitle}>CONFIGURE REPLAY</div>

            {/* Mode toggle */}
            <div className={styles.modeToggle}>
              <button
                className={`${styles.modeBtn} ${mode === 'single_day' ? styles.modeBtnActive : ''}`}
                onClick={() => setMode('single_day')}
              >
                Single Day
              </button>
              <button
                className={`${styles.modeBtn} ${mode === 'date_range' ? styles.modeBtnActive : ''}`}
                onClick={() => setMode('date_range')}
              >
                Date Range
              </button>
            </div>

            {/* Date input(s) */}
            {mode === 'single_day' ? (
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Scan Date</label>
                <input
                  type="date"
                  className={styles.formInput}
                  value={singleDate}
                  onChange={e => setSingleDate(e.target.value)}
                  max={new Date(Date.now() - 86400000).toISOString().slice(0, 10)}
                />
                <div className={styles.formHint}>The scanner will only see data up to this date.</div>
              </div>
            ) : (
              <>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Start Date</label>
                  <input
                    type="date"
                    className={styles.formInput}
                    value={startDate}
                    onChange={e => setStartDate(e.target.value)}
                    max={endDate || new Date(Date.now() - 86400000).toISOString().slice(0, 10)}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>End Date</label>
                  <input
                    type="date"
                    className={styles.formInput}
                    value={endDate}
                    onChange={e => setEndDate(e.target.value)}
                    min={startDate}
                    max={new Date(Date.now() - 86400000).toISOString().slice(0, 10)}
                  />
                  <div className={styles.formHint}>Weekends are skipped automatically.</div>
                </div>
              </>
            )}

            {/* Universe mode */}
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Universe Mode</label>
              <select
                className={styles.formSelect}
                value={universeMode}
                onChange={e => setUniverseMode(e.target.value)}
              >
                <option value="approx">Approx (recommended)</option>
                <option value="strict">Strict (fallback to approx)</option>
              </select>
              <div className={styles.formHint}>
                Approx uses grouped-daily snapshot for the date.
                Strict mode requires a historical ticker reference (not yet available — falls back to approx).
              </div>
            </div>

            {error && (
              <div style={{ color: 'var(--red)', fontSize: 11, marginBottom: 10 }}>{error}</div>
            )}

            <button
              className={styles.runBtn}
              onClick={handleRun}
              disabled={launching || isRunning}
            >
              {runBtnLabel}
            </button>

            {/* Progress */}
            {progress && (
              <div className={styles.progressWrap}>
                <div className={styles.progressRow}>
                  <span className={styles.progressLabel}>Status</span>
                  <StatusBadge status={progress.running ? 'running' : (progress.error ? 'failed' : 'completed')} />
                </div>
                {progress.mode === 'date_range' && (
                  <div className={styles.progressRow}>
                    <span className={styles.progressLabel}>Days</span>
                    <span className={styles.progressValue}>
                      {progress.days_completed} / {progress.days_total}
                    </span>
                  </div>
                )}
                {progress.current_date && (
                  <div className={styles.progressRow}>
                    <span className={styles.progressLabel}>Date</span>
                    <span className={styles.progressValue}>{progress.current_date}</span>
                  </div>
                )}
                <div className={styles.progressRow}>
                  <span className={styles.progressLabel}>Candidates</span>
                  <span className={styles.progressValue}>{progress.candidates_found ?? 0}</span>
                </div>
                <div className={styles.progressRow}>
                  <span className={styles.progressLabel}>Outcomes</span>
                  <span className={styles.progressValue}>{progress.outcomes_computed ?? 0}</span>
                </div>
                {progress.mode === 'date_range' && progress.days_total > 0 && (
                  <>
                    <div className={styles.progressTrack}>
                      <div
                        className={styles.progressFill}
                        style={{ width: `${Math.round((progress.days_completed / progress.days_total) * 100)}%` }}
                      />
                    </div>
                  </>
                )}
                {progress.error && (
                  <div style={{ color: 'var(--red)', fontSize: 10, marginTop: 6 }}>
                    {progress.error}
                  </div>
                )}
                {progress.elapsed_secs > 0 && (
                  <div className={styles.progressRow}>
                    <span className={styles.progressLabel}>Elapsed</span>
                    <span className={styles.progressValue}>{progress.elapsed_secs}s</span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Right: Main panel ───────────────────────────────────────────── */}
          <div className={styles.mainPanel}>

            {/* Run history */}
            <div>
              <div className={styles.sectionTitle}>Run History</div>
              {history.length === 0 ? (
                <div className={styles.emptyMsg}>
                  No replay runs yet.
                  <div className={styles.emptyHint}>Configure a date above and click Run Replay.</div>
                </div>
              ) : (
                <table className={styles.historyTable}>
                  <thead>
                    <tr className={styles.historyHead}>
                      <th>ID</th>
                      <th>Mode</th>
                      <th>Date(s)</th>
                      <th>Candidates</th>
                      <th>Outcomes</th>
                      <th>Status</th>
                      <th>Started</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map(run => (
                      <tr
                        key={run.id}
                        className={`${styles.historyRow} ${activeRun?.id === run.id ? styles.historyRowActive : ''}`}
                        onClick={() => handleSelectRun(run)}
                      >
                        <td><span className={styles.runId}>#{run.id}</span></td>
                        <td><span className={styles.runMode}>{run.mode}</span></td>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
                          {run.mode === 'single_day'
                            ? run.as_of_date
                            : `${run.start_date} → ${run.end_date}`}
                        </td>
                        <td style={{ fontFamily: 'var(--font-mono)' }}>{run.total_candidates ?? 0}</td>
                        <td style={{ fontFamily: 'var(--font-mono)' }}>{run.outcomes_computed ?? 0}</td>
                        <td><StatusBadge status={run.status} /></td>
                        <td style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                          {run.created_at ? new Date(run.created_at).toLocaleString() : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {/* Detail panel */}
            {activeRun && (
              <div>
                <div className={styles.sectionTitle}>
                  Run #{activeRun.id} — {activeRun.mode === 'single_day'
                    ? activeRun.as_of_date
                    : `${activeRun.start_date} → ${activeRun.end_date}`}
                </div>

                {/* Tabs */}
                <div className={styles.tabRow}>
                  {['candidates', 'outcomes', 'missed', 'summary'].map(t => (
                    <button
                      key={t}
                      className={`${styles.tab} ${tab === t ? styles.tabActive : ''}`}
                      onClick={() => setTab(t)}
                    >
                      {t === 'candidates' && `Candidates (${candidates.length})`}
                      {t === 'outcomes'   && `Outcomes (${outcomes.length})`}
                      {t === 'missed'     && `Missed Movers (${missed.length})`}
                      {t === 'summary'    && 'Summary'}
                    </button>
                  ))}
                </div>

                {loadingDetail && (
                  <div className={styles.statusMsg}>Loading…</div>
                )}

                {/* ── Candidates tab ─────────────────────────────────────── */}
                {tab === 'candidates' && !loadingDetail && (
                  candidates.length === 0 ? (
                    <div className={styles.emptyMsg}>No candidates for this run.</div>
                  ) : (
                    <table className={styles.candidateTable}>
                      <thead>
                        <tr>
                          <th>Symbol</th>
                          <th>Date</th>
                          <th>Price</th>
                          <th>Tier</th>
                          <th>Score</th>
                          <th>Ignition</th>
                          <th>Ribbon</th>
                          <th>Wyckoff</th>
                          <th>Sector</th>
                        </tr>
                      </thead>
                      <tbody>
                        {candidates.map(c => (
                          <tr key={c.id}>
                            <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>
                              {c.symbol}
                            </td>
                            <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                              {c.scan_date}
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)' }}>
                              {c.price != null ? `$${fmt(c.price, 2)}` : '—'}
                            </td>
                            <td><TierBadge tier={c.tier} /></td>
                            <td style={{ fontFamily: 'var(--font-mono)' }}>{c.total_score ?? '—'}</td>
                            <td style={{ color: c.ignition_signal ? 'var(--lime)' : 'var(--text-muted)' }}>
                              {c.ignition_signal ? '✓' : '—'}
                            </td>
                            <td style={{ color: c.ribbon_signal ? 'var(--cyan)' : 'var(--text-muted)' }}>
                              {c.ribbon_signal ? '✓' : '—'}
                            </td>
                            <td style={{ fontSize: 9, color: 'var(--text-muted)' }}>
                              {c.wyckoff_state || '—'}
                            </td>
                            <td style={{ fontSize: 9, color: 'var(--text-dim)' }}>
                              {c.sector || '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )
                )}

                {/* ── Outcomes tab ───────────────────────────────────────── */}
                {tab === 'outcomes' && (
                  outcomes.length === 0 ? (
                    <div className={styles.emptyMsg}>
                      {loadingDetail ? 'Loading…' : 'No outcomes data yet.'}
                    </div>
                  ) : (
                    <table className={styles.candidateTable}>
                      <thead>
                        <tr>
                          <th>Symbol</th>
                          <th>Date</th>
                          <th>Horizon</th>
                          <th>Entry</th>
                          <th>Exit</th>
                          <th>Return</th>
                          <th>Max Gain</th>
                          <th>Max DD</th>
                          <th>α vs SPY</th>
                          <th>Outcome</th>
                        </tr>
                      </thead>
                      <tbody>
                        {outcomes.map((o, i) => (
                          <tr key={i}>
                            <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>
                              {o.symbol}
                            </td>
                            <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>
                              {o.scan_date}
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
                              {o.horizon}
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)' }}>
                              {o.entry_price != null ? `$${fmt(o.entry_price, 2)}` : '—'}
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)' }}>
                              {o.exit_price != null ? `$${fmt(o.exit_price, 2)}` : '—'}
                            </td>
                            <td>{pctCell(o.return_pct)}</td>
                            <td>{pctCell(o.max_gain_pct)}</td>
                            <td>{pctCell(o.max_drawdown_pct)}</td>
                            <td>{pctCell(o.alpha_vs_spy)}</td>
                            <td>
                              {o.outcome_label
                                ? <OutcomeLabel label={o.outcome_label} />
                                : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )
                )}

                {/* ── Missed Movers tab ──────────────────────────────────── */}
                {tab === 'missed' && (
                  missed.length === 0 ? (
                    <div className={styles.emptyMsg}>
                      {loadingDetail ? 'Loading…' : 'No missed movers data yet.'}
                    </div>
                  ) : (
                    <table className={styles.missedTable}>
                      <thead>
                        <tr>
                          <th>Symbol</th>
                          <th>Date</th>
                          <th>Price</th>
                          <th>3d Return</th>
                          <th>5d Return</th>
                          <th>10d Return</th>
                          <th>Why Missed</th>
                        </tr>
                      </thead>
                      <tbody>
                        {missed.map((m, i) => (
                          <tr key={i}>
                            <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>
                              {m.symbol}
                            </td>
                            <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>
                              {m.scan_date}
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)' }}>
                              {m.price_on_date != null ? `$${fmt(m.price_on_date, 2)}` : '—'}
                            </td>
                            <td>{pctCell(m.future_return_3d)}</td>
                            <td>{pctCell(m.future_return_5d)}</td>
                            <td>{pctCell(m.future_return_10d)}</td>
                            <td><span className={styles.whyMissed}>{m.why_missed || '—'}</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )
                )}

                {/* ── Summary tab ────────────────────────────────────────── */}
                {tab === 'summary' && (
                  !summary ? (
                    <div className={styles.emptyMsg}>No summary available yet.</div>
                  ) : (
                    <>
                      {/* KPI grid */}
                      <div className={styles.summaryGrid}>
                        <div className={styles.summaryKPI}>
                          <div className={styles.kpiValue}>{summary.total_candidates ?? 0}</div>
                          <div className={styles.kpiLabel}>Candidates</div>
                        </div>
                        <div className={styles.summaryKPI}>
                          <div className={styles.kpiValue}>{summary.total_outcomes ?? 0}</div>
                          <div className={styles.kpiLabel}>Outcomes</div>
                        </div>
                        <div className={styles.summaryKPI}>
                          <div className={styles.kpiValue}>{summary.total_missed ?? 0}</div>
                          <div className={styles.kpiLabel}>Missed Movers</div>
                        </div>
                        {summary.avg_return_5d != null && (
                          <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
                            <div className={`${styles.kpiValue} ${summary.avg_return_5d >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                              {summary.avg_return_5d >= 0 ? '+' : ''}{fmt(summary.avg_return_5d)}%
                            </div>
                            <div className={styles.kpiLabel}>Avg 5d Return</div>
                          </div>
                        )}
                        {summary.avg_alpha_5d != null && (
                          <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
                            <div className={`${styles.kpiValue} ${summary.avg_alpha_5d >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                              {summary.avg_alpha_5d >= 0 ? '+' : ''}{fmt(summary.avg_alpha_5d)}%
                            </div>
                            <div className={styles.kpiLabel}>Avg α vs SPY</div>
                          </div>
                        )}
                        {summary.win_rate_5d != null && (
                          <div className={styles.summaryKPI}>
                            <div className={styles.kpiValue}>{fmt(summary.win_rate_5d)}%</div>
                            <div className={styles.kpiLabel}>Win Rate (5d)</div>
                          </div>
                        )}
                      </div>

                      {/* Outcome distribution */}
                      {summary.label_distribution && Object.keys(summary.label_distribution).length > 0 && (
                        <div className={styles.outcomeSection}>
                          <div className={styles.sectionTitle} style={{ marginBottom: 10 }}>
                            Outcome Distribution
                          </div>
                          <div className={styles.outcomeGrid}>
                            <div className={styles.outcomeBlock}>
                              <div className={styles.outcomeBlockTitle}>Label Counts</div>
                              {Object.entries(summary.label_distribution).map(([label, count]) => (
                                <div key={label} className={styles.outcomeRow}>
                                  <span className={styles.outcomeLabel}>
                                    <OutcomeLabel label={label} />
                                  </span>
                                  <span className={styles.outcomeCount}>{count}</span>
                                </div>
                              ))}
                            </div>

                            {(summary.best_5 || summary.worst_5) && (
                              <div className={styles.outcomeBlock}>
                                <div className={styles.outcomeBlockTitle}>Best Performers (5d)</div>
                                {(summary.best_5 || []).map((r, i) => (
                                  <div key={i} className={styles.outcomeRow}>
                                    <span className={styles.outcomeLabel} style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                                      {r.symbol}
                                    </span>
                                    <span>{pctCell(r.return_pct)}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Tier distribution */}
                      {summary.tier_distribution && Object.keys(summary.tier_distribution).length > 0 && (
                        <div className={styles.outcomeSection} style={{ marginTop: 12 }}>
                          <div className={styles.sectionTitle} style={{ marginBottom: 10 }}>
                            Tier Breakdown
                          </div>
                          <div className={styles.outcomeGrid}>
                            <div className={styles.outcomeBlock}>
                              <div className={styles.outcomeBlockTitle}>Candidate Tiers</div>
                              {Object.entries(summary.tier_distribution).map(([tier, count]) => (
                                <div key={tier} className={styles.outcomeRow}>
                                  <span className={styles.outcomeLabel}>
                                    <TierBadge tier={tier} />
                                  </span>
                                  <span className={styles.outcomeCount}>{count}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      )}
                    </>
                  )
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
