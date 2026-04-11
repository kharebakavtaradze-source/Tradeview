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

// ── Bundle Tab component ──────────────────────────────────────────────────────

function BucketTable({ data }) {
  if (!data || data.length === 0) return <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>No data</div>;
  return (
    <table className={styles.bucketTable}>
      <thead>
        <tr>
          <th>Bucket</th>
          <th>#</th>
          <th>Avg 5d</th>
          <th>Win%</th>
          <th>Avg 10d</th>
          <th>Avg DD</th>
          <th>α/SPY 5d</th>
        </tr>
      </thead>
      <tbody>
        {data.map((b, i) => (
          <tr key={i}>
            <td className={styles.bucketName}>{b.bucket}</td>
            <td style={{ fontFamily: 'var(--font-mono)' }}>{b.count}</td>
            <td>{pctCell(b.avg_return_5d)}</td>
            <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
              {b.win_rate_5d != null ? `${b.win_rate_5d}%` : '—'}
            </td>
            <td>{pctCell(b.avg_return_10d)}</td>
            <td>{pctCell(b.avg_max_drawdown_pct)}</td>
            <td>{pctCell(b.alpha_vs_spy_5d)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PatternReview({ review }) {
  if (!review) return null;
  const sections = [
    { key: 'what_worked',          label: 'What Worked',       itemCls: styles.patternItemWorked },
    { key: 'what_failed',          label: 'What Failed',       itemCls: styles.patternItemFailed },
    { key: 'missed_patterns',      label: 'Missed Patterns',   itemCls: styles.patternItem },
    { key: 'likely_strict_filters',label: 'Too Strict',        itemCls: styles.patternItemStrict },
    { key: 'likely_noisy_filters', label: 'Too Noisy',         itemCls: styles.patternItemStrict },
    { key: 'suggested_focus',      label: 'Suggested Focus',   itemCls: styles.patternItemFocus },
  ];
  const nonEmpty = sections.filter(s => (review[s.key] || []).length > 0);
  if (!nonEmpty.length) return <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>Insufficient data for pattern analysis.</div>;
  return (
    <div className={styles.patternGrid}>
      {nonEmpty.map(({ key, label, itemCls }) => (
        <div key={key} className={styles.patternCard}>
          <div className={styles.patternCardTitle}>{label}</div>
          {(review[key] || []).map((item, i) => (
            <div key={i} className={`${styles.patternItem} ${itemCls}`}>{item}</div>
          ))}
        </div>
      ))}
    </div>
  );
}

function ExperimentCard({ exp, idx }) {
  const confCls = {
    HIGH:   styles.confHigh,
    MEDIUM: styles.confMedium,
    LOW:    styles.confLow,
  }[exp.confidence] || styles.confLow;
  return (
    <div className={`${styles.experimentCard} ${confCls}`}>
      <div className={styles.experimentTitle}>{idx}. {exp.title}</div>
      <div className={styles.experimentMeta}>
        <span className={styles.experimentType}>{exp.experiment_type}</span>
        <span className={styles.experimentConf}>{exp.confidence}</span>
      </div>
      <div className={styles.experimentDesc}>{exp.description}</div>
      {exp.evidence && <div className={styles.experimentEvidence}>Evidence: {exp.evidence}</div>}
    </div>
  );
}

function BundleTab({ bundle, loading, runId, onReload, apiUrl }) {
  const [copied, setCopied] = useState(false);

  async function copyMarkdown() {
    try {
      const r = await fetch(`${apiUrl}/api/replay/${runId}/research-bundle/markdown`);
      if (r.ok) {
        await navigator.clipboard.writeText(await r.text());
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch (_) {}
  }

  function downloadJSON() {
    window.open(`${apiUrl}/api/replay/${runId}/research-bundle/download?format=json`);
  }

  function downloadMarkdown() {
    window.open(`${apiUrl}/api/replay/${runId}/research-bundle/download?format=markdown`);
  }

  if (loading) return <div className={styles.statusMsg}>Building research bundle…</div>;
  if (!bundle) return (
    <div className={styles.emptyMsg}>
      Research bundle not loaded.
      <div className={styles.emptyHint}>
        <button className={styles.runBtn} style={{ width: 'auto', marginTop: 8 }} onClick={onReload}>
          Build Bundle
        </button>
      </div>
    </div>
  );

  const s    = bundle.summary || {};
  const pr   = bundle.pattern_review || {};
  const exps = bundle.suggested_experiments || [];
  const fps  = bundle.false_positives || [];
  const mm   = bundle.missed_movers || [];
  const lc   = s.outcome_label_counts || {};

  return (
    <div className={styles.bundleWrap}>
      {/* Export bar */}
      <div className={styles.exportRow}>
        <div className={styles.researchWarning}>⚠ Research Only — No auto-apply</div>
        <button className={`${styles.exportBtn} ${styles.exportBtnPrimary}`} onClick={copyMarkdown}>
          {copied ? '✓ Copied' : 'Copy Markdown'}
        </button>
        <button className={styles.exportBtn} onClick={downloadJSON}>Download JSON</button>
        <button className={styles.exportBtn} onClick={downloadMarkdown}>Download .md</button>
        <button className={styles.exportBtn} onClick={onReload}>Rebuild</button>
      </div>

      {/* Summary KPIs */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Replay Overview</div>
        <div className={styles.summaryGrid}>
          <div className={styles.summaryKPI}>
            <div className={styles.kpiValue}>{s.total_candidates ?? 0}</div>
            <div className={styles.kpiLabel}>Candidates</div>
          </div>
          <div className={styles.summaryKPI}>
            <div className={styles.kpiValue}>{s.total_outcomes_5d ?? 0}</div>
            <div className={styles.kpiLabel}>5d Outcomes</div>
          </div>
          <div className={styles.summaryKPI}>
            <div className={styles.kpiValue}>{s.total_missed_movers ?? 0}</div>
            <div className={styles.kpiLabel}>Missed Movers</div>
          </div>
          {s.avg_return_5d != null && (
            <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
              <div className={`${styles.kpiValue} ${s.avg_return_5d >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                {s.avg_return_5d >= 0 ? '+' : ''}{fmt(s.avg_return_5d)}%
              </div>
              <div className={styles.kpiLabel}>Avg 5d Return</div>
            </div>
          )}
          {s.win_rate_5d != null && (
            <div className={styles.summaryKPI}>
              <div className={styles.kpiValue}>{fmt(s.win_rate_5d)}%</div>
              <div className={styles.kpiLabel}>Win Rate 5d</div>
            </div>
          )}
          {s.avg_alpha_vs_spy_5d != null && (
            <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
              <div className={`${styles.kpiValue} ${s.avg_alpha_vs_spy_5d >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                {s.avg_alpha_vs_spy_5d >= 0 ? '+' : ''}{fmt(s.avg_alpha_vs_spy_5d)}%
              </div>
              <div className={styles.kpiLabel}>α vs SPY 5d</div>
            </div>
          )}
        </div>

        {/* Outcome label pills */}
        {s.total_outcomes_5d > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
            {[
              ['SUCCESSFUL_BREAKOUT', lc.SUCCESSFUL_BREAKOUT, 'var(--lime)'],
              ['EARLY_WINNER',        lc.EARLY_WINNER,        'var(--cyan)'],
              ['NO_FOLLOW_THROUGH',   lc.NO_FOLLOW_THROUGH,   'var(--text-muted)'],
              ['LATE_SIGNAL',         lc.LATE_SIGNAL,         'var(--amber)'],
              ['FAILED_BREAKOUT',     lc.FAILED_BREAKOUT,     'var(--red)'],
              ['FALSE_POSITIVE',      lc.FALSE_POSITIVE,      '#ff4466'],
            ].filter(([, v]) => v > 0).map(([label, count, color]) => (
              <span key={label} style={{
                fontSize: 9, fontWeight: 700, letterSpacing: '0.05em',
                padding: '2px 8px', borderRadius: 'var(--r-pill)',
                background: `${color}18`, border: `1px solid ${color}44`, color,
              }}>
                {label.replace('_', ' ')}: {count}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Performance by Tier */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Performance by Tier</div>
        <BucketTable data={bundle.performance_by_tier} />
      </div>

      {/* Performance by Signal Combo */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Performance by Signal Combination</div>
        <BucketTable data={bundle.performance_by_source} />
      </div>

      {/* Performance: Ignition + Ribbon side by side */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div className={styles.bundleSection}>
          <div className={styles.bundleSectionTitle}>By Ignition Signal</div>
          <BucketTable data={bundle.performance_by_ignition_signal} />
        </div>
        <div className={styles.bundleSection}>
          <div className={styles.bundleSectionTitle}>By Ribbon Signal</div>
          <BucketTable data={bundle.performance_by_ribbon_signal} />
        </div>
      </div>

      {/* False Positives */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Top False Positives / Failures</div>
        {fps.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>No significant false positives in this run.</div>
        ) : (
          <table className={styles.fpTable}>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Date</th>
                <th>Tier</th>
                <th>Score</th>
                <th>3d Ret</th>
                <th>5d Ret</th>
                <th>Max DD</th>
                <th>Label</th>
                <th>Ign</th>
                <th>Rib</th>
              </tr>
            </thead>
            <tbody>
              {fps.slice(0, 15).map((fp, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>{fp.symbol}</td>
                  <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>{fp.scan_date || '—'}</td>
                  <td><TierBadge tier={fp.tier} /></td>
                  <td style={{ fontFamily: 'var(--font-mono)' }}>{fp.total_score != null ? fmt(fp.total_score, 1) : '—'}</td>
                  <td>{pctCell(fp.return_3d)}</td>
                  <td>{pctCell(fp.return_5d)}</td>
                  <td>{pctCell(fp.max_drawdown_pct)}</td>
                  <td>{fp.outcome_label ? <OutcomeLabel label={fp.outcome_label} /> : '—'}</td>
                  <td style={{ color: fp.ignition_signal ? 'var(--lime)' : 'var(--text-muted)' }}>
                    {fp.ignition_signal ? '✓' : '—'}
                  </td>
                  <td style={{ color: fp.ribbon_signal ? 'var(--cyan)' : 'var(--text-muted)' }}>
                    {fp.ribbon_signal ? '✓' : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Missed Movers */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Top Missed Movers</div>
        {mm.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>No significant missed movers in this run.</div>
        ) : (
          <table className={styles.fpTable}>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Date</th>
                <th>Price</th>
                <th>3d Ret</th>
                <th>5d Ret</th>
                <th>10d Ret</th>
                <th>Why Missed</th>
                <th>Pre-filtered</th>
              </tr>
            </thead>
            <tbody>
              {mm.slice(0, 15).map((m, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>{m.symbol}</td>
                  <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>{m.scan_date || '—'}</td>
                  <td style={{ fontFamily: 'var(--font-mono)' }}>{m.price_on_date != null ? `$${fmt(m.price_on_date, 2)}` : '—'}</td>
                  <td>{pctCell(m.future_return_3d)}</td>
                  <td>{pctCell(m.future_return_5d)}</td>
                  <td>{pctCell(m.future_return_10d)}</td>
                  <td><span className={styles.whyMissed}>{m.why_missed || '—'}</span></td>
                  <td style={{ color: m.was_filtered_pre_score ? 'var(--amber)' : 'var(--text-muted)', fontSize: 10 }}>
                    {m.was_filtered_pre_score ? 'Yes' : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pattern Review */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Pattern Review</div>
        <PatternReview review={pr} />
      </div>

      {/* Suggested Experiments */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Suggested Experiments</div>
        <div className={styles.researchWarning}>⚠ Proposals only — not auto-applied</div>
        {exps.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>No experiments suggested — run may have insufficient data.</div>
        ) : (
          <div className={styles.experimentsGrid}>
            {exps.map((exp, i) => <ExperimentCard key={i} exp={exp} idx={i + 1} />)}
          </div>
        )}
      </div>
    </div>
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
  const [tab, setTab]                 = useState('candidates'); // candidates | outcomes | missed | summary | bundle

  const [candidates, setCandidates]   = useState([]);
  const [outcomes, setOutcomes]       = useState([]);
  const [missed, setMissed]           = useState([]);
  const [summary, setSummary]         = useState(null);
  const [bundle, setBundle]           = useState(null);
  const [bundleLoading, setBundleLoading] = useState(false);

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
      if (r.ok) {
        const data = await r.json();
        setHistory(Array.isArray(data) ? data : (data.runs || []));
      }
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
      if (candR.ok) {
        const data = await candR.json();
        setCandidates(Array.isArray(data) ? data : (data.candidates || []));
      }
      if (summR.ok) setSummary(await summR.json());
    } catch (_) {}
    setLoadingDetail(false);
  }

  async function loadOutcomes(runId) {
    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}/outcomes?limit=500`);
      if (r.ok) {
        const data = await r.json();
        setOutcomes(Array.isArray(data) ? data : (data.outcomes || []));
      }
    } catch (_) {}
  }

  async function loadMissed(runId) {
    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}/missed?limit=100`);
      if (r.ok) {
        const data = await r.json();
        setMissed(Array.isArray(data) ? data : (data.missed_movers || []));
      }
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

  async function loadBundle(runId) {
    setBundleLoading(true);
    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}/research-bundle`);
      if (r.ok) setBundle(await r.json());
    } catch (_) {}
    setBundleLoading(false);
  }

  // Load outcomes/missed/bundle lazily on tab change
  useEffect(() => {
    if (!activeRun) return;
    if (tab === 'outcomes' && outcomes.length === 0) loadOutcomes(activeRun.id);
    if (tab === 'missed'   && missed.length   === 0) loadMissed(activeRun.id);
    if (tab === 'bundle'   && !bundle)               loadBundle(activeRun.id);
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
    setBundle(null);
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
                  {['candidates', 'outcomes', 'missed', 'summary', 'bundle'].map(t => (
                    <button
                      key={t}
                      className={`${styles.tab} ${tab === t ? styles.tabActive : ''}`}
                      onClick={() => setTab(t)}
                    >
                      {t === 'candidates' && `Candidates (${candidates.length})`}
                      {t === 'outcomes'   && `Outcomes (${outcomes.length})`}
                      {t === 'missed'     && `Missed Movers (${missed.length})`}
                      {t === 'summary'    && 'Summary'}
                      {t === 'bundle'     && 'Research Bundle'}
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
                      {/* KPI grid — keys match API: total_candidates, total_outcomes, missed_movers, avg_returns */}
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
                          <div className={styles.kpiValue}>{summary.missed_movers ?? 0}</div>
                          <div className={styles.kpiLabel}>Missed Movers</div>
                        </div>
                        {summary.avg_returns?.['5d'] != null && (
                          <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
                            <div className={`${styles.kpiValue} ${summary.avg_returns['5d'] >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                              {summary.avg_returns['5d'] >= 0 ? '+' : ''}{fmt(summary.avg_returns['5d'])}%
                            </div>
                            <div className={styles.kpiLabel}>Avg 5d Return</div>
                          </div>
                        )}
                        {summary.avg_returns?.['1d'] != null && (
                          <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
                            <div className={`${styles.kpiValue} ${summary.avg_returns['1d'] >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                              {summary.avg_returns['1d'] >= 0 ? '+' : ''}{fmt(summary.avg_returns['1d'])}%
                            </div>
                            <div className={styles.kpiLabel}>Avg 1d Return</div>
                          </div>
                        )}
                        {summary.avg_returns?.['10d'] != null && (
                          <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
                            <div className={`${styles.kpiValue} ${summary.avg_returns['10d'] >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                              {summary.avg_returns['10d'] >= 0 ? '+' : ''}{fmt(summary.avg_returns['10d'])}%
                            </div>
                            <div className={styles.kpiLabel}>Avg 10d Return</div>
                          </div>
                        )}
                      </div>

                      {/* Outcome distribution — API key: outcome_labels */}
                      {summary.outcome_labels && Object.keys(summary.outcome_labels).length > 0 && (
                        <div className={styles.outcomeSection}>
                          <div className={styles.sectionTitle} style={{ marginBottom: 10 }}>
                            Outcome Distribution
                          </div>
                          <div className={styles.outcomeGrid}>
                            <div className={styles.outcomeBlock}>
                              <div className={styles.outcomeBlockTitle}>Label Counts</div>
                              {Object.entries(summary.outcome_labels).map(([label, count]) => (
                                <div key={label} className={styles.outcomeRow}>
                                  <span className={styles.outcomeLabel}>
                                    <OutcomeLabel label={label} />
                                  </span>
                                  <span className={styles.outcomeCount}>{count}</span>
                                </div>
                              ))}
                            </div>

                            {summary.best_5?.length > 0 && (
                              <div className={styles.outcomeBlock}>
                                <div className={styles.outcomeBlockTitle}>Best Performers (5d)</div>
                                {summary.best_5.map((r, i) => (
                                  <div key={i} className={styles.outcomeRow}>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 10 }}>
                                      {r.symbol}
                                    </span>
                                    <span>{pctCell(r.return_5d)}</span>
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

                {/* ── Research Bundle tab ───────────────────────────────── */}
                {tab === 'bundle' && <BundleTab
                  bundle={bundle}
                  loading={bundleLoading}
                  runId={activeRun.id}
                  onReload={() => { setBundle(null); loadBundle(activeRun.id); }}
                  apiUrl={API_URL}
                />}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
