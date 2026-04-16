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

function RunHeader({ run, onRepairDone }) {
  const isRunning = run.status === 'running';
  const needsRepair = run.status === 'complete' && !run.comparison_count;
  const [repairing, setRepairing] = useState(false);
  const [repairErr, setRepairErr] = useState('');

  const handleRepair = async () => {
    setRepairing(true);
    setRepairErr('');
    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/${run.id}/repair`, { method: 'POST' });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
      if (onRepairDone) onRepairDone();
    } catch (e) {
      setRepairErr(String(e));
    } finally {
      setRepairing(false);
    }
  };

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
      {needsRepair && (
        <div className={styles.repairRow}>
          <span className={styles.repairHint}>Comparisons are empty — group_type may not have been assigned.</span>
          <button className={styles.repairBtn} disabled={repairing} onClick={handleRepair}>
            {repairing ? 'Repairing…' : 'Repair Groups + Rebuild Comparisons'}
          </button>
          {repairErr && <div className={styles.errorMsg}>{repairErr}</div>}
        </div>
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

// Must match _COMPARISON_FEATURES order in pump_study_engine.py
const COMP_FEATURES = [
  // PRIMARY — sequence / duration
  'days_from_breakout_to_peak',
  'compression_days_pre',
  'days_from_first_compression_to_breakout',
  'days_from_first_abnormal_volume_to_breakout',
  'dryup_day_count_pre',
  'days_in_base',
  'atr_contraction_days_pre',
  // PRIMARY — EMA ribbon (computed from daily ema_spread_pct)
  'avg_ema_spread_pre',
  'min_ema_spread_pre',
  // PRIMARY — structure depth
  'had_accumulation_like',
  'accumulation_like_day_count',
  'had_spring_test_lps',
  'reclaim_bar_count_pre',
  // SECONDARY — structure quality
  'had_breakout_retest',
  'retest_count',
  'avg_retest_quality',
  // SECONDARY — volume
  'max_volume_anomaly_pre',
  'median_volume_anomaly_pre',
  'abnormal_volume_day_count_pre',
  'max_dollar_volume_pre',
  // SECONDARY — candle / bar patterns
  'bullish_engulfing_count_pre',
  'expansion_bar_count_pre',
  'strong_close_count_pre',
  'wide_range_bar_count_pre',
  // LOW_SIGNAL
  'had_compression',
  'avg_body_pct_pre',
  'avg_upper_wick_pct_pre',
  'avg_lower_wick_pct_pre',
  'bearish_engulfing_count_pre',
  'inside_bar_count_pre',
  'outside_bar_count_pre',
];

// Used to derive badge when stats_json priority is absent (legacy runs)
const FEATURE_PRIORITY = {
  days_from_breakout_to_peak:                  'PRIMARY',
  compression_days_pre:                        'PRIMARY',
  days_from_first_compression_to_breakout:     'PRIMARY',
  days_from_first_abnormal_volume_to_breakout: 'PRIMARY',
  dryup_day_count_pre:                         'PRIMARY',
  days_in_base:                                'PRIMARY',
  atr_contraction_days_pre:                    'PRIMARY',
  avg_ema_spread_pre:                          'PRIMARY',
  min_ema_spread_pre:                          'PRIMARY',
  had_accumulation_like:                       'PRIMARY',
  accumulation_like_day_count:                 'PRIMARY',
  had_spring_test_lps:                         'PRIMARY',
  reclaim_bar_count_pre:                       'PRIMARY',
  had_breakout_retest:                         'SECONDARY',
  retest_count:                                'SECONDARY',
  avg_retest_quality:                          'SECONDARY',
  max_volume_anomaly_pre:                      'SECONDARY',
  median_volume_anomaly_pre:                   'SECONDARY',
  abnormal_volume_day_count_pre:               'SECONDARY',
  max_dollar_volume_pre:                       'SECONDARY',
  bullish_engulfing_count_pre:                 'SECONDARY',
  expansion_bar_count_pre:                     'SECONDARY',
  strong_close_count_pre:                      'SECONDARY',
  wide_range_bar_count_pre:                    'SECONDARY',
  had_compression:                             'LOW_SIGNAL',
  avg_body_pct_pre:                            'LOW_SIGNAL',
  avg_upper_wick_pct_pre:                      'LOW_SIGNAL',
  avg_lower_wick_pct_pre:                      'LOW_SIGNAL',
  bearish_engulfing_count_pre:                 'LOW_SIGNAL',
  inside_bar_count_pre:                        'LOW_SIGNAL',
  outside_bar_count_pre:                       'LOW_SIGNAL',
};

const TIER_ORDER = { PRIMARY: 0, SECONDARY: 1, LOW_SIGNAL: 2 };

function PriorityBadge({ priority }) {
  const cls = {
    PRIMARY:    styles.priBadge,
    SECONDARY:  styles.secBadge,
    LOW_SIGNAL: styles.lowBadge,
  }[priority] || styles.lowBadge;
  const label = { PRIMARY: 'PRI', SECONDARY: 'SEC', LOW_SIGNAL: 'LOW' }[priority] || priority;
  return <span className={cls}>{label}</span>;
}

function FlagBadges({ stats }) {
  if (!stats) return null;
  return (
    <>
      {stats.always_on_flag    && <span className={styles.alwaysOnBadge}>ALWAYS ON</span>}
      {stats.outlier_risk_flag && <span className={styles.outlierBadge}>OUTLIER</span>}
      {stats.low_variance_flag && !stats.always_on_flag && <span className={styles.lowVarBadge}>LOW VAR</span>}
    </>
  );
}

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

  // Collect known features, sort by priority tier then original order
  const allFeats = COMP_FEATURES.filter(f => pivot[f]);
  // Any features in data but not in COMP_FEATURES list (future-proof)
  const extraFeats = Object.keys(pivot).filter(f => !COMP_FEATURES.includes(f));
  const features = [...allFeats, ...extraFeats];

  // Get the effective priority for a feature (from stored stats or fallback)
  const getPriority = (feat) => {
    // Try to read from any group's stats
    const anyRow = Object.values(pivot[feat] || {})[0];
    return anyRow?.stats?.priority || FEATURE_PRIORITY[feat] || 'LOW_SIGNAL';
  };

  features.sort((a, b) => {
    const ta = TIER_ORDER[getPriority(a)] ?? 99;
    const tb = TIER_ORDER[getPriority(b)] ?? 99;
    if (ta !== tb) return ta - tb;
    return COMP_FEATURES.indexOf(a) - COMP_FEATURES.indexOf(b);
  });

  if (features.length === 0) {
    return <div className={styles.statusMsg}>No comparison data yet.</div>;
  }

  // Get flags from first available group row for a feature
  const getFlags = (feat) => {
    const anyRow = Object.values(pivot[feat] || {})[0];
    return anyRow?.stats || null;
  };

  return (
    <div className={styles.tableCard}>
      <div className={styles.tableHeader}>
        <span className={styles.tableTitle}>Feature Comparisons</span>
        <span className={styles.tableHint}>median (n=members) · sorted by priority</span>
      </div>
      <div className={styles.tableScroll}>
        <table className={styles.dataTable}>
          <thead>
            <tr>
              <th className={styles.dataHead} style={{ minWidth: 220 }}>Feature</th>
              <th className={styles.dataHead} style={{ minWidth: 70 }}>Priority</th>
              {GROUPS.map(g => (
                <th key={g} className={styles.dataHead} style={{ color: GROUP_COLOR[g] }}>{g}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {features.map(feat => {
              const priority = getPriority(feat);
              const flags    = getFlags(feat);
              return (
                <tr key={feat} className={styles.dataRow}>
                  <td className={styles.dataCell} style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-dim)' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <span>{feat}</span>
                      <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap' }}>
                        <FlagBadges stats={flags} />
                      </div>
                    </div>
                  </td>
                  <td className={styles.dataCell}>
                    <PriorityBadge priority={priority} />
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
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Top Pre-Pump Schemes ──────────────────────────────────────────────────────

const SCHEME_GROUP_DOT = {
  '4x_pump':       '#22d3ee',
  'normal_winner': '#86efac',
  'false_positive':'#fca5a5',
  'missed_mover':  '#fde68a',
};

function SchemeCard({ scheme }) {
  const t   = scheme.typical_timing || {};
  const sep = scheme.separator_strength;

  const sepLabel = sep == null ? null
    : sep >= 2   ? `${sep}× stronger`
    : sep >= 1.2 ? `${sep}× stronger`
    : `${sep}× (weak)`;

  return (
    <div className={styles.schemeCard}>
      <div className={styles.schemeHeader}>
        <span className={styles.schemeId}>{scheme.scheme_id}</span>
        <span className={styles.schemeLabel}>{scheme.scheme_label}</span>
        {sepLabel && (
          <span className={`${styles.schemeSepBadge} ${sep >= 2 ? styles.schemeSepStrong : sep >= 1.2 ? styles.schemeSepMid : styles.schemeSepWeak}`}>
            {sepLabel}
          </span>
        )}
      </div>

      {/* Ordered steps */}
      <div className={styles.schemeSteps}>
        {scheme.ordered_steps.map((step, i) => (
          <span key={step} className={styles.schemeStep}>
            {i > 0 && <span className={styles.stepArrow}>→</span>}
            <span className={styles.stepLabel}>{step.replace(/_/g, '\u00a0')}</span>
          </span>
        ))}
      </div>

      <div className={styles.schemeBottom}>
        {/* Group breakdown */}
        <div className={styles.schemeBreakdown}>
          {Object.entries(scheme.group_breakdown || {}).map(([g, n]) => (
            <span key={g} className={styles.breakdownItem}>
              <span className={styles.breakdownDot} style={{ background: SCHEME_GROUP_DOT[g] || '#888' }} />
              <span className={styles.breakdownGroup}>{g.replace(/_/g, ' ')}</span>
              <span className={styles.breakdownCount}>{n}</span>
              {g === '4x_pump' && scheme.share_of_4x_pumps != null && (
                <span className={styles.breakdownPct}>{Math.round(scheme.share_of_4x_pumps * 100)}%</span>
              )}
              {g === 'false_positive' && scheme.share_of_false_positives != null && (
                <span className={styles.breakdownPct}>{Math.round(scheme.share_of_false_positives * 100)}%</span>
              )}
              {g === 'normal_winner' && scheme.share_of_normal_winners != null && (
                <span className={styles.breakdownPct}>{Math.round(scheme.share_of_normal_winners * 100)}%</span>
              )}
            </span>
          ))}
        </div>

        {/* Timing */}
        <div className={styles.schemeTiming}>
          {t.compression_lead_days != null && (
            <span className={styles.timingChip}><span className={styles.timingKey}>compr</span><span className={styles.timingVal}>{t.compression_lead_days}d</span></span>
          )}
          {t.accumulation_days != null && (
            <span className={styles.timingChip}><span className={styles.timingKey}>accum</span><span className={styles.timingVal}>{t.accumulation_days}d</span></span>
          )}
          {t.vol_to_breakout_days != null && (
            <span className={styles.timingChip}><span className={styles.timingKey}>vol→brk</span><span className={styles.timingVal}>{t.vol_to_breakout_days}d</span></span>
          )}
          {t.breakout_to_peak_days != null && (
            <span className={styles.timingChip}><span className={styles.timingKey}>brk→peak</span><span className={styles.timingVal}>{t.breakout_to_peak_days}d</span></span>
          )}
          {t.days_in_base != null && (
            <span className={styles.timingChip}><span className={styles.timingKey}>base</span><span className={styles.timingVal}>{t.days_in_base}d</span></span>
          )}
        </div>
      </div>

      {scheme.notes?.length > 0 && (
        <div className={styles.schemeNotes}>
          {scheme.notes.map((n, i) => <span key={i}>{n}</span>)}
        </div>
      )}
    </div>
  );
}

function TopSchemesPanel({ runId }) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    fetch(`${API_URL}/api/replay/raw-pattern-study/${runId}/top-schemes`)
      .then(r => r.json().then(d => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (cancelled) return;
        if (!ok) throw new Error(d.detail || 'Request failed');
        setData(d);
      })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [runId]);

  if (loading) return <div className={styles.statusMsg}>Extracting schemes…</div>;
  if (error)   return <div className={styles.errorMsg}>{error}</div>;
  if (!data)   return null;

  const { schemes = [], absent_groups = [], total_episodes, analyzed_episodes, note } = data;

  return (
    <div className={styles.schemesPanel}>
      <div className={styles.schemesHeader}>
        <span className={styles.schemesTitle}>Top Pre-Pump Schemes</span>
        <span className={styles.schemesHint}>
          {analyzed_episodes}/{total_episodes} episodes matched · deterministic · pre-breakout only
        </span>
      </div>

      {absent_groups.length > 0 && (
        <div className={styles.schemesAbsent}>
          Groups absent from data: <strong>{absent_groups.join(', ')}</strong> — conclusions for these groups unavailable.
        </div>
      )}

      {schemes.length === 0 ? (
        <div className={styles.statusMsg}>
          No schemes detected — run may need group diversity or re-run comparisons via Repair.
        </div>
      ) : (
        <div className={styles.schemesList}>
          {schemes.map(s => <SchemeCard key={s.scheme_id} scheme={s} />)}
        </div>
      )}

      {note && <div className={styles.schemesNote}>{note}</div>}
    </div>
  );
}

// ── AI summary card ───────────────────────────────────────────────────────────

const AI_SECTIONS = [
  { key: 'repeated_patterns',           label: 'Patterns before 4× pumps' },
  { key: 'separators_vs_normal_winner', label: '4× pump vs normal winner' },
  { key: 'separators_vs_false_positive',label: '4× pump vs false positive' },
  { key: 'noisy_features',              label: 'Noisy / low-signal features' },
  { key: 'pump_engine_changes',         label: 'Pump Engine improvements' },
];

function AISummaryCard({ runId }) {
  const [data,     setData]     = useState(null);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState('');
  const [fetched,  setFetched]  = useState(false);

  const generate = async () => {
    setLoading(true);
    setError('');
    try {
      const r    = await fetch(`${API_URL}/api/replay/raw-pattern-study/${runId}/ai-summary`);
      const json = await r.json();
      if (!r.ok) throw new Error(json.detail || `HTTP ${r.status}`);
      setData(json);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
      setFetched(true);
    }
  };

  if (!fetched) {
    return (
      <div className={styles.aiCard}>
        <div className={styles.aiCardHeader}>
          <span className={styles.aiCardTitle}>AI Pattern Analysis</span>
          <span className={styles.aiPowered}>claude haiku</span>
        </div>
        <p className={styles.aiCardHint}>
          Evidence-only analysis of stored raw features. No catalyst or news data.
        </p>
        <button className={styles.aiGenBtn} onClick={generate}>
          Generate AI Summary
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className={styles.aiCard}>
        <div className={styles.aiCardHeader}>
          <span className={styles.aiCardTitle}>AI Pattern Analysis</span>
          <span className={styles.pulsingDot} />
        </div>
        <div className={styles.statusMsg}>Generating analysis…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.aiCard}>
        <div className={styles.aiErrorMsg}>{error}</div>
        <button className={styles.aiGenBtn} onClick={() => { setFetched(false); setError(''); }}>
          Retry
        </button>
      </div>
    );
  }

  if (data?.parse_failed) {
    return (
      <div className={styles.aiCard}>
        <div className={styles.aiErrorMsg}>
          AI output could not be parsed.{data.parse_error ? ` (${data.parse_error})` : ''}
        </div>
        {data.raw_text && (
          <pre className={styles.aiRaw}>{data.raw_text.slice(0, 400)}</pre>
        )}
      </div>
    );
  }

  const analysis = data?.analysis || {};
  const rec       = analysis.recommendation || data?.recommendation || '';
  const limits    = analysis.limitations || [];

  return (
    <div className={styles.aiCard}>
      <div className={styles.aiCardHeader}>
        <span className={styles.aiCardTitle}>AI Pattern Analysis</span>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className={styles.aiPowered}>{data?.model_used || 'claude haiku'}</span>
          {data?.cached && <span className={styles.aiCachedBadge}>cached</span>}
        </div>
      </div>

      {rec && (
        <div className={styles.aiRecommendation}>
          <span className={styles.aiRecLabel}>Recommendation</span>
          <span className={styles.aiRecText}>{rec}</span>
        </div>
      )}

      <div className={styles.aiSections}>
        {AI_SECTIONS.map(({ key, label }) => {
          const items = analysis[key];
          if (!Array.isArray(items) || items.length === 0) return null;
          return (
            <div key={key} className={styles.aiSection}>
              <div className={styles.aiSectionLabel}>{label}</div>
              <ul className={styles.aiList}>
                {items.map((item, i) => (
                  <li key={i} className={styles.aiListItem}>{item}</li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>

      {limits.length > 0 && (
        <div className={styles.aiLimitations}>
          <span className={styles.aiLimLabel}>Limitations</span>
          {limits.map((l, i) => <p key={i} className={styles.aiLimText}>{l}</p>)}
        </div>
      )}
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

  // Top schemes (loaded fresh on tab open via TopSchemesPanel's own useEffect)
  const [schemesKey, setSchemesKey] = useState(0); // bump to force remount

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
    setSchemesKey(k => k + 1);
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
                <RunHeader run={run} onRepairDone={() => { loadRun(selectedId); loadRuns(); loadEpisodes(selectedId); loadComparisons(selectedId); }} />

                {/* Tab row */}
                <div className={styles.tabRow}>
                  {[
                    { id: 'schemes',     label: 'Top Schemes' },
                    { id: 'episodes',    label: `Episodes (${episodes.length})` },
                    { id: 'comparisons', label: 'Comparisons' },
                    { id: 'ai',          label: 'AI Summary' },
                  ].map(({ id, label }) => (
                    <button
                      key={id}
                      className={`${styles.tab}${activeTab === id ? ' ' + styles.tabActive : ''}`}
                      onClick={() => setActiveTab(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {/* Top Schemes tab */}
                {activeTab === 'schemes' && (
                  run.status !== 'complete'
                    ? <div className={styles.statusMsg}>Schemes available after run completes.</div>
                    : <TopSchemesPanel key={`${selectedId}-${schemesKey}`} runId={selectedId} />
                )}

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

                {/* AI tab */}
                {activeTab === 'ai' && (
                  run.status !== 'complete'
                    ? <div className={styles.statusMsg}>AI summary available after run completes.</div>
                    : <AISummaryCard key={selectedId} runId={selectedId} />
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
