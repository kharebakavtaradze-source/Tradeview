/**
 * Replay — Historical Backdated Scan Mode (Demand Engine)
 * Research-only page. Runs the Demand Engine pipeline on past dates with
 * strict temporal isolation (no future leakage).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import PumpLayout from '../components/PumpLayout';
import BarLabels from '../components/BarLabels';
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

const DEMAND_TIER_COLORS = {
  PRIME_BUY:      '#34d399',
  HIGH_CONF_BUY:  '#60a5fa',
  BUY_WATCH:      '#fbbf24',
  SETUP_MONITOR:  '#a78bfa',
  SKIP:           '#6b7280',
};

function DemandTierBadge({ tier }) {
  if (!tier) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const color = DEMAND_TIER_COLORS[tier] || '#6b7280';
  const short = { PRIME_BUY: 'PRIME', HIGH_CONF_BUY: 'HIGH', BUY_WATCH: 'WATCH', SETUP_MONITOR: 'MONITOR', SKIP: 'SKIP' }[tier] || tier;
  return (
    <span style={{
      color, fontWeight: 700, fontSize: 9, letterSpacing: '0.06em',
      padding: '1px 5px', borderRadius: 3,
      background: color + '18', border: `1px solid ${color}44`,
      whiteSpace: 'nowrap',
    }}>{short}</span>
  );
}

function AtsBadge({ sig }) {
  if (!sig) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const color = sig === 'ATS_PRIME' ? '#34d399' : sig === 'ATS_SETUP' ? '#60a5fa' : sig === 'ATS_WATCH' ? '#fbbf24' : '#6b7280';
  const short = { ATS_PRIME: 'PRIME', ATS_SETUP: 'SETUP', ATS_WATCH: 'WATCH', ATS_NONE: 'NONE' }[sig] || sig;
  return (
    <span style={{
      color, fontWeight: 700, fontSize: 9, letterSpacing: '0.06em',
      padding: '1px 5px', borderRadius: 3,
      background: color + '18', border: `1px solid ${color}44`,
      whiteSpace: 'nowrap',
    }}>{short}</span>
  );
}

const NP_LABEL_COLORS = {
  NEW_PUMP_FIRE:         '#ff4400',
  NEW_PUMP_STRONG:       '#ff8800',
  NEW_PUMP_SETUP:        '#ffd600',
  NEW_PUMP_TRIGGER_ONLY: '#00e5ff',
  NEW_PUMP_WEAK:         '#888',
  NEW_PUMP_NONE:         '#444',
};
const NP_LABEL_SHORT = {
  NEW_PUMP_FIRE:         'FIRE',
  NEW_PUMP_STRONG:       'STRONG',
  NEW_PUMP_SETUP:        'SETUP',
  NEW_PUMP_TRIGGER_ONLY: 'TRIGGER',
  NEW_PUMP_WEAK:         'WEAK',
  NEW_PUMP_NONE:         'NONE',
};
function npScoreColor(s) {
  if (s == null) return 'var(--text-muted)';
  if (s >= 70) return '#ff4400';
  if (s >= 55) return '#ff8800';
  if (s >= 40) return '#ffd600';
  if (s >= 25) return '#00e5ff';
  if (s >= 10) return '#888';
  return '#444';
}
function NpLabelBadge({ label }) {
  const color = NP_LABEL_COLORS[label] || '#444';
  const short = NP_LABEL_SHORT[label] || label || '—';
  return (
    <span style={{
      color, fontWeight: 700, fontSize: 9, letterSpacing: '0.06em',
      padding: '1px 5px', borderRadius: 3,
      background: color === '#444' ? 'transparent' : color + '18',
      border: `1px solid ${color}44`,
    }}>{short}</span>
  );
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

// ── Shared performance table used across bundle sections ─────────────────────

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

// ── Research Bundle tab — demand engine focused ──────────────────────────────

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

  const ov = bundle.overall || {};
  const mm = bundle.missed_movers || [];
  const best = bundle.best_candidates || [];
  const worst = bundle.worst_candidates || [];
  const lc = ov.outcome_label_dist || {};

  return (
    <div className={styles.bundleWrap}>
      {/* Export bar */}
      <div className={styles.exportRow}>
        <div className={styles.researchWarning}>⚠ Research Only — No auto-apply</div>
        <button className={`${styles.exportBtn} ${styles.exportBtnPrimary}`} onClick={copyMarkdown}>
          {copied ? '✓ Copied' : 'Copy Markdown'}
        </button>
        <button className={styles.exportBtn} onClick={() => window.open(`${apiUrl}/api/replay/${runId}/research-bundle/download?format=json`)}>
          Download JSON
        </button>
        <button className={styles.exportBtn} onClick={() => window.open(`${apiUrl}/api/replay/${runId}/research-bundle/download?format=markdown`)}>
          Download .md
        </button>
        <button className={styles.exportBtn} onClick={onReload}>Rebuild</button>
      </div>

      {/* KPI strip */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Overview</div>
        <div className={styles.summaryGrid}>
          <div className={styles.summaryKPI}>
            <div className={styles.kpiValue}>{ov.total_candidates ?? 0}</div>
            <div className={styles.kpiLabel}>Candidates</div>
          </div>
          <div className={styles.summaryKPI}>
            <div className={styles.kpiValue}>{ov.total_outcomes ?? 0}</div>
            <div className={styles.kpiLabel}>Outcomes</div>
          </div>
          <div className={styles.summaryKPI}>
            <div className={styles.kpiValue}>{ov.missed_movers ?? 0}</div>
            <div className={styles.kpiLabel}>Missed Movers</div>
          </div>
          {ov.avg_return_5d != null && (
            <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
              <div className={`${styles.kpiValue} ${ov.avg_return_5d >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                {ov.avg_return_5d >= 0 ? '+' : ''}{fmt(ov.avg_return_5d)}%
              </div>
              <div className={styles.kpiLabel}>Avg 5d Return</div>
            </div>
          )}
          {ov.win_rate_5d != null && (
            <div className={styles.summaryKPI}>
              <div className={styles.kpiValue}>{fmt(ov.win_rate_5d)}%</div>
              <div className={styles.kpiLabel}>Win Rate 5d</div>
            </div>
          )}
        </div>

        {/* Outcome label pills */}
        {Object.keys(lc).length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
            {Object.entries(lc).filter(([, v]) => v > 0).map(([label, count]) => {
              const color = OUTCOME_COLORS[label] || 'var(--text-muted)';
              return (
                <span key={label} style={{
                  fontSize: 9, fontWeight: 700, letterSpacing: '0.05em',
                  padding: '2px 8px', borderRadius: 'var(--r-pill)',
                  background: `${color}18`, border: `1px solid ${color}44`, color,
                }}>
                  {label.replace(/_/g, ' ')}: {count}
                </span>
              );
            })}
          </div>
        )}
      </div>

      {/* Performance by Demand Tier */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle} style={{ color: '#34d399' }}>
          ◈ Performance by Demand Tier
        </div>
        <BucketTable data={bundle.performance_by_demand_tier} />
      </div>

      {/* Performance by ATS Signal */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle} style={{ color: '#60a5fa' }}>
          ◈ Performance by ATS Signal
        </div>
        <BucketTable data={bundle.performance_by_ats_signal} />
      </div>

      {/* Performance by Readiness Tier */}
      {(bundle.performance_by_readiness_tier?.length ?? 0) > 0 && (
        <div className={styles.bundleSection}>
          <div className={styles.bundleSectionTitle} style={{ color: '#a78bfa' }}>
            ◈ Performance by Readiness Tier
          </div>
          <BucketTable data={bundle.performance_by_readiness_tier} />
        </div>
      )}

      {/* Performance by NP Label */}
      {(bundle.performance_by_new_pump_label?.length ?? 0) > 0 && (
        <div className={styles.bundleSection} style={{ borderTop: '1px solid var(--border)', paddingTop: 12, marginTop: 4 }}>
          <div className={styles.bundleSectionTitle} style={{ color: '#ff8800' }}>
            ◈ New Pump Engine — Performance by Label
          </div>
          <BucketTable data={bundle.performance_by_new_pump_label} />
        </div>
      )}

      {/* TZ Signal Analytics */}
      {(bundle.performance_by_tz_t_signal?.length ?? 0) > 0 && (
        <div className={styles.bundleSection} style={{ borderTop: '1px solid var(--border)', paddingTop: 12, marginTop: 4 }}>
          <div className={styles.bundleSectionTitle} style={{ color: '#34d399' }}>
            ◈ TZ Signal — Performance by T/Z Bar Pattern
          </div>
          <BucketTable data={bundle.performance_by_tz_t_signal} />
        </div>
      )}

      {(bundle.performance_by_preup_token?.length ?? 0) > 0 && (
        <div className={styles.bundleSection}>
          <div className={styles.bundleSectionTitle} style={{ color: '#60a5fa' }}>
            ◈ PREUP Token — EMA Cross Signals
          </div>
          <BucketTable data={bundle.performance_by_preup_token} />
        </div>
      )}

      {(bundle.performance_by_line5?.length ?? 0) > 0 && (
        <div className={styles.bundleSection}>
          <div className={styles.bundleSectionTitle} style={{ color: '#a78bfa' }}>
            ◈ Line5 — VIX-Fix / PSAR / RSI2 Composite
          </div>
          <BucketTable data={bundle.performance_by_line5} />
        </div>
      )}

      {(bundle.tz_demand_tier_combos?.length ?? 0) > 0 && (
        <div className={styles.bundleSection} style={{ borderTop: '1px solid var(--border)', paddingTop: 12, marginTop: 4 }}>
          <div className={styles.bundleSectionTitle} style={{ color: '#fbbf24' }}>
            ◈ TZ × Demand Tier Combinations (min 3 occurrences)
          </div>
          <BucketTable data={bundle.tz_demand_tier_combos} />
        </div>
      )}

      {(bundle.tz_ats_combos?.length ?? 0) > 0 && (
        <div className={styles.bundleSection}>
          <div className={styles.bundleSectionTitle} style={{ color: '#fbbf24' }}>
            ◈ TZ × ATS Signal Combinations (min 3 occurrences)
          </div>
          <BucketTable data={bundle.tz_ats_combos} />
        </div>
      )}

      {/* Best/Worst candidates */}
      {(best.length > 0 || worst.length > 0) && (
        <div className={styles.bundleSection}>
          <div className={styles.bundleSectionTitle}>Top Performers &amp; Failures</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            {best.length > 0 && (
              <div>
                <div style={{ fontSize: 9, color: 'var(--lime)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>Best 5d</div>
                <table className={styles.fpTable}>
                  <thead>
                    <tr><th>Symbol</th><th>Date</th><th>5d Ret</th><th>Demand</th><th>ATS</th></tr>
                  </thead>
                  <tbody>
                    {best.map((c, i) => (
                      <tr key={i}>
                        <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>{c.symbol}</td>
                        <td style={{ color: 'var(--text-muted)', fontSize: 9 }}>{c.scan_date || '—'}</td>
                        <td>{pctCell(c.return_5d)}</td>
                        <td><DemandTierBadge tier={c.demand_tier} /></td>
                        <td><AtsBadge sig={c.ats_signal} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {worst.length > 0 && (
              <div>
                <div style={{ fontSize: 9, color: 'var(--red)', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>Worst 5d</div>
                <table className={styles.fpTable}>
                  <thead>
                    <tr><th>Symbol</th><th>Date</th><th>5d Ret</th><th>Demand</th><th>ATS</th></tr>
                  </thead>
                  <tbody>
                    {worst.map((c, i) => (
                      <tr key={i}>
                        <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>{c.symbol}</td>
                        <td style={{ color: 'var(--text-muted)', fontSize: 9 }}>{c.scan_date || '—'}</td>
                        <td>{pctCell(c.return_5d)}</td>
                        <td><DemandTierBadge tier={c.demand_tier} /></td>
                        <td><AtsBadge sig={c.ats_signal} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Missed Movers */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Top Missed Movers</div>
        {mm.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>No missed movers in this run.</div>
        ) : (
          <table className={styles.fpTable}>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Date</th>
                <th>5d Ret</th>
                <th>10d Ret</th>
                <th>Why Missed</th>
              </tr>
            </thead>
            <tbody>
              {mm.map((m, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>{m.symbol}</td>
                  <td style={{ color: 'var(--text-muted)', fontSize: 9 }}>{m.scan_date || '—'}</td>
                  <td>{pctCell(m.return_5d)}</td>
                  <td>{pctCell(m.return_10d)}</td>
                  <td><span className={styles.whyMissed}>{m.why_missed || '—'}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ReplayPage() {
  // ── Form state ──────────────────────────────────────────────────────────────
  const [mode, setMode]               = useState('single_day');
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
  const [activeRun, setActiveRun]     = useState(null);
  const [tab, setTab]                 = useState('candidates');

  const [candidates, setCandidates]   = useState([]);
  const [outcomes, setOutcomes]       = useState([]);
  const [missed, setMissed]           = useState([]);
  const [summary, setSummary]         = useState(null);
  const [bundle, setBundle]           = useState(null);
  const [bundleLoading, setBundleLoading] = useState(false);

  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError]             = useState('');

  // ── Delete state ────────────────────────────────────────────────────────────
  const [deleteTarget,   setDeleteTarget]   = useState(null);
  const [deleting,       setDeleting]       = useState(false);
  const [deleteError,    setDeleteError]    = useState('');

  // ── Demand filter state ──────────────────────────────────────────────────────
  const [demandTierF,    setDemandTierF]    = useState('');
  const [atsF,           setAtsF]           = useState('');
  const [readyF,         setReadyF]         = useState('');

  // ── Bar labels panel ─────────────────────────────────────────────────────────
  const [selectedCand,   setSelectedCand]   = useState(null);

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
          loadHistory();
          if (p.run_id) loadRunDetail(p.run_id);
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

  async function handleDeleteConfirm() {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError('');
    try {
      const res = await fetch(`${API_URL}/api/replay/${deleteTarget.id}`, { method: 'DELETE' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      if (activeRun?.id === deleteTarget.id) {
        setActiveRun(null);
        setCandidates([]);
        setOutcomes([]);
        setMissed([]);
        setSummary(null);
        setBundle(null);
        stopPolling();
      }
      setHistory(prev => prev.filter(r => r.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err.message || 'Delete failed');
    } finally {
      setDeleting(false);
    }
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

  async function loadBundle(runId) {
    setBundleLoading(true);
    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}/research-bundle`);
      if (r.ok) setBundle(await r.json());
    } catch (_) {}
    setBundleLoading(false);
  }

  // Initial load
  useEffect(() => {
    loadHistory();
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

  // Lazy tab loads
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
      const pollStatus = await fetch(`${API_URL}/api/replay/status`);
      if (pollStatus.ok) setProgress(await pollStatus.json());
      startPolling();
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
    <PumpLayout title="Replay">
      <div className={styles.page}>
        <div className={styles.header}>
          <div className={styles.advisory}>⏪ HISTORICAL REPLAY — RESEARCH ONLY</div>
          <h1 className={styles.title}>Backdated Scan Replay — Demand Engine</h1>
          <p className={styles.subtitle}>
            Run the Demand Engine pipeline on past dates with strict temporal isolation.
            Candidates are scored by Demand Composite Tier, ATS Signal, and Readiness.
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
                <div className={styles.formHint}>Only data up to this date is used.</div>
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
                  <div className={styles.progressTrack}>
                    <div
                      className={styles.progressFill}
                      style={{ width: `${Math.round((progress.days_completed / progress.days_total) * 100)}%` }}
                    />
                  </div>
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
                      <th></th>
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
                        <td onClick={e => e.stopPropagation()}>
                          <button
                            className={styles.btnDanger}
                            style={{ padding: '3px 10px', fontSize: 10 }}
                            onClick={() => { setDeleteTarget(run); setDeleteError(''); }}
                          >
                            Delete
                          </button>
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
                    <>
                      {/* Demand filter controls */}
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8, padding: '6px 0' }}>
                        {(() => {
                          const ss = { background: '#13132a', border: '1px solid #242438', color: '#aaa', fontSize: 10, borderRadius: 3, padding: '3px 8px', fontFamily: 'inherit' };
                          return (
                            <>
                              <span style={{ fontSize: 10, color: '#666', fontWeight: 700, letterSpacing: '0.5px', textTransform: 'uppercase' }}>Filter</span>
                              <select value={demandTierF} onChange={e => setDemandTierF(e.target.value)} style={ss}>
                                <option value="">All tiers</option>
                                <option value="PRIME_BUY">PRIME BUY</option>
                                <option value="HIGH_CONF_BUY">HIGH CONF</option>
                                <option value="BUY_WATCH">BUY WATCH</option>
                                <option value="SETUP_MONITOR">MONITOR</option>
                                <option value="SKIP">SKIP</option>
                              </select>
                              <select value={atsF} onChange={e => setAtsF(e.target.value)} style={ss}>
                                <option value="">All ATS</option>
                                <option value="ATS_PRIME">ATS PRIME</option>
                                <option value="ATS_SETUP">ATS SETUP</option>
                                <option value="ATS_WATCH">ATS WATCH</option>
                                <option value="ATS_NONE">ATS NONE</option>
                              </select>
                              <select value={readyF} onChange={e => setReadyF(e.target.value)} style={ss}>
                                <option value="">All readiness</option>
                                <option value="HOT">HOT</option>
                                <option value="WARM">WARM</option>
                                <option value="COOL">COOL</option>
                                <option value="COLD">COLD</option>
                              </select>
                              {(demandTierF || atsF || readyF) && (
                                <button
                                  onClick={() => { setDemandTierF(''); setAtsF(''); setReadyF(''); }}
                                  style={{ fontSize: 10, color: '#888', background: 'transparent', border: '1px solid #333', borderRadius: 3, padding: '2px 8px', cursor: 'pointer' }}
                                >
                                  Clear
                                </button>
                              )}
                              <span style={{ flex: 1 }} />
                              <button
                                onClick={() => window.open(`${API_URL}/api/replay/${activeRun.id}/export?format=csv`)}
                                style={{ fontSize: 10, color: '#22c55e', background: 'transparent', border: '1px solid #22c55e44', borderRadius: 3, padding: '2px 10px', cursor: 'pointer', fontFamily: 'inherit' }}
                              >↓ CSV</button>
                              <button
                                onClick={() => window.open(`${API_URL}/api/replay/${activeRun.id}/export?format=json`)}
                                style={{ fontSize: 10, color: '#aaa', background: 'transparent', border: '1px solid #333', borderRadius: 3, padding: '2px 10px', cursor: 'pointer', fontFamily: 'inherit' }}
                              >↓ JSON</button>
                            </>
                          );
                        })()}
                      </div>
                      <table className={styles.candidateTable}>
                        <thead>
                          <tr>
                            <th>Symbol</th>
                            <th>Date</th>
                            <th>Price</th>
                            <th>Demand</th>
                            <th>ATS</th>
                            <th>Ready</th>
                            <th>D Score</th>
                            <th>TZ</th>
                            <th>PREUP</th>
                            <th>Line5</th>
                            <th>NP Score</th>
                            <th>NP Label</th>
                            <th>NP Sequence</th>
                            <th>Wyckoff</th>
                            <th>Sector</th>
                          </tr>
                        </thead>
                        <tbody>
                          {candidates
                            .filter(c => {
                              if (demandTierF && c.demand_composite_tier !== demandTierF) return false;
                              if (atsF && c.ats_signal !== atsF) return false;
                              if (readyF && c.readiness_tier !== readyF) return false;
                              return true;
                            })
                            .map(c => (
                            <tr
                              key={c.id}
                              style={{
                                cursor: 'pointer',
                                background: selectedCand?.id === c.id ? 'rgba(34,211,238,0.08)' : undefined,
                              }}
                              onClick={() => setSelectedCand(selectedCand?.id === c.id ? null : c)}
                            >
                              <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>
                                {c.symbol}
                              </td>
                              <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 10 }}>
                                {c.scan_date}
                              </td>
                              <td style={{ fontFamily: 'var(--font-mono)' }}>
                                {c.price != null ? `$${fmt(c.price, 2)}` : '—'}
                              </td>
                              <td style={{ fontSize: 9 }}>
                                <DemandTierBadge tier={c.demand_composite_tier} />
                              </td>
                              <td style={{ fontSize: 9 }}>
                                <AtsBadge sig={c.ats_signal} />
                              </td>
                              <td style={{ fontSize: 9, color: 'var(--text-muted)' }}>
                                {c.readiness_tier || '—'}
                              </td>
                              <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
                                {c.demand_composite_score != null ? Number(c.demand_composite_score).toFixed(1) : '—'}
                              </td>
                              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: c.tz_t_signal ? '#34d399' : 'var(--text-muted)' }}>
                                {c.tz_t_signal || c.tz_z_signal || '—'}
                              </td>
                              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: c.preup_token ? '#60a5fa' : 'var(--text-muted)' }}>
                                {c.preup_token || c.predn_token || '—'}
                              </td>
                              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)' }}>
                                {c.line5 || '—'}
                              </td>
                              <td style={{ fontFamily: 'var(--font-mono)', color: npScoreColor(c.new_pump_score) }}>
                                {c.new_pump_score != null ? Number(c.new_pump_score).toFixed(1) : '—'}
                              </td>
                              <td style={{ fontSize: 9 }}>
                                <NpLabelBadge label={c.new_pump_label} />
                              </td>
                              <td style={{ fontSize: 9, color: 'var(--text-muted)', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {c.new_pump_sequence_label || '—'}
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
                      {selectedCand && (
                        <div style={{ marginTop: 12 }}>
                          <div style={{
                            fontSize: 10, color: 'var(--text-muted)', marginBottom: 6,
                            letterSpacing: '0.06em', textTransform: 'uppercase',
                          }}>
                            Bar Labels — {selectedCand.symbol}
                          </div>
                          <BarLabels symbol={selectedCand.symbol} />
                        </div>
                      )}
                    </>
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
                        {summary.avg_returns?.['10d'] != null && (
                          <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
                            <div className={`${styles.kpiValue} ${summary.avg_returns['10d'] >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                              {summary.avg_returns['10d'] >= 0 ? '+' : ''}{fmt(summary.avg_returns['10d'])}%
                            </div>
                            <div className={styles.kpiLabel}>Avg 10d Return</div>
                          </div>
                        )}
                      </div>

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
                                  <span className={styles.outcomeLabel}><OutcomeLabel label={label} /></span>
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

                      {summary.demand_tier_distribution && Object.keys(summary.demand_tier_distribution).length > 0 && (
                        <div className={styles.outcomeSection} style={{ marginTop: 12 }}>
                          <div className={styles.sectionTitle} style={{ marginBottom: 10 }}>
                            Demand Tier Breakdown
                          </div>
                          <div className={styles.outcomeGrid}>
                            <div className={styles.outcomeBlock}>
                              <div className={styles.outcomeBlockTitle}>Demand Tiers</div>
                              {['PRIME_BUY','HIGH_CONF_BUY','BUY_WATCH','SETUP_MONITOR','SKIP'].map(tier => {
                                const count = summary.demand_tier_distribution[tier];
                                if (!count) return null;
                                return (
                                  <div key={tier} className={styles.outcomeRow}>
                                    <span className={styles.outcomeLabel}><DemandTierBadge tier={tier} /></span>
                                    <span className={styles.outcomeCount}>{count}</span>
                                  </div>
                                );
                              })}
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

      {/* ── Delete confirmation modal ──────────────────────────────────────── */}
      {deleteTarget && (
        <div className={styles.modalOverlay} onClick={() => !deleting && setDeleteTarget(null)}>
          <div className={styles.modalBox} onClick={e => e.stopPropagation()}>
            <div className={styles.modalTitle}>Permanently Delete Run #{deleteTarget.id}?</div>
            <div className={styles.modalBody}>
              This will remove the run and <strong>all linked DB rows</strong>:
              candidates, outcomes, and missed movers.
              <br /><br />
              <strong>This cannot be undone.</strong>
            </div>
            {deleteError && (
              <div style={{ fontSize: 11, color: 'var(--red, #f87171)' }}>{deleteError}</div>
            )}
            <div className={styles.modalActions}>
              <button className={styles.btnCancel} onClick={() => setDeleteTarget(null)} disabled={deleting}>
                Cancel
              </button>
              <button className={styles.btnDanger} onClick={handleDeleteConfirm} disabled={deleting}>
                {deleting ? 'Deleting…' : 'Delete Permanently'}
              </button>
            </div>
          </div>
        </div>
      )}
    </PumpLayout>
  );
}
