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

function RunHeader({ run, npCoverage, onRepairDone, onDelete }) {
  const isRunning = run.status === 'running';
  const needsRepair = run.status === 'complete' && !run.comparison_count;
  const [repairing,   setRepairing]   = useState(false);
  const [repairErr,   setRepairErr]   = useState('');
  const [copying,     setCopying]     = useState(false);
  const [copyDone,    setCopyDone]    = useState(false);
  const [downloading, setDownloading] = useState(false);

  const handleCopyContext = async () => {
    setCopying(true); setCopyDone(false);
    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/${run.id}/research-context`);
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      const text = d.context_text || '';
      // navigator.clipboard requires HTTPS; fall back to execCommand for HTTP dev environments
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(text);
      } else {
        const el = document.createElement('textarea');
        el.value = text;
        el.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;';
        document.body.appendChild(el);
        el.focus(); el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
      }
      setCopyDone(true);
      setTimeout(() => setCopyDone(false), 2500);
    } catch { /* ignore */ } finally { setCopying(false); }
  };

  const handleDownload = async () => {
    setDownloading(true);
    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/${run.id}/export?format=json`);
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail); }
      const blob = new Blob([await r.text()], { type: 'application/json' });
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url; a.download = `raw-pattern-run-${run.id}-full.json`;
      // Must be in DOM for Firefox and strict browser security policies
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch { /* ignore */ } finally { setDownloading(false); }
  };

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
        {run.status === 'complete' && (
          <>
            <button
              className={styles.contextBtn}
              disabled={copying || downloading}
              onClick={handleCopyContext}
              title="Copy research context to clipboard (for AI Analyst / Pump Study)"
            >
              {copyDone ? '✓ Copied' : copying ? '…' : 'Copy Context'}
            </button>
            <button
              className={styles.contextBtn}
              disabled={downloading || copying}
              onClick={handleDownload}
              title="Download full research context as JSON"
            >
              {downloading ? '…' : 'Download JSON'}
            </button>
          </>
        )}
        {onDelete && (
          <button className={styles.deleteRunBtn} onClick={onDelete} title="Delete this run permanently">
            Delete
          </button>
        )}
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
        {npCoverage && (
          <div className={styles.countItem}
               title={`${npCoverage.analyzed} analyzed, ${npCoverage.skipped} skipped (${npCoverage.skip_insufficient_candles} thin candles, ${npCoverage.skip_failed} errors)`}>
            <span className={styles.countVal}
                  style={{ color: npCoverage.coverage_pct >= 70 ? 'var(--lime)'
                                : npCoverage.coverage_pct >= 40 ? 'var(--amber)'
                                : 'var(--red)' }}>
              {npCoverage.coverage_pct != null ? `${npCoverage.coverage_pct}%` : '—'}
            </span>
            <span className={styles.countLabel}>NP Coverage</span>
          </div>
        )}
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

// ── Split context badge ───────────────────────────────────────────────────────

const SPLIT_CTX_BADGE_COLOR = {
  NO_SPLIT:             '#6b7280',
  FORWARD_SPLIT:        '#60a5fa',
  RECENT_REVERSE_SPLIT: '#fbbf24',
  OLD_REVERSE_SPLIT:    '#9ca3af',
  SPLIT_DURING_PUMP:    '#fb923c',
  SPLIT_ARTIFACT_RISK:  '#fb7185',
};
const SPLIT_CTX_SHORT = {
  NO_SPLIT:             'NO SPLIT',
  FORWARD_SPLIT:        'FWD',
  RECENT_REVERSE_SPLIT: 'REC RS',
  OLD_REVERSE_SPLIT:    'OLD RS',
  SPLIT_DURING_PUMP:    'PUMP',
  SPLIT_ARTIFACT_RISK:  '⚠ ARTIFACT',
};
function SplitContextBadge({ ctx }) {
  if (!ctx || ctx === 'NO_SPLIT') return <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>—</span>;
  const color = SPLIT_CTX_BADGE_COLOR[ctx] || '#6b7280';
  return (
    <span style={{
      color, fontWeight: 700, fontSize: 9, letterSpacing: '0.04em',
      padding: '2px 6px', borderRadius: 'var(--r-pill)',
      background: `${color}1a`, border: `1px solid ${color}44`,
      whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)',
    }}>{SPLIT_CTX_SHORT[ctx] || ctx}</span>
  );
}

// ── Structure phase badge ─────────────────────────────────────────────────────

const STRUCTURE_PHASE_COLOR = {
  CONFIRMED_STRUCTURE: '#86efac',
  TRIGGERED_STRUCTURE: '#22d3ee',
  EARLY_STRUCTURE:     '#60a5fa',
  SETUP_PHASE:         '#a8a29e',
  IMPULSE_ONLY:        '#6b7280',
  DEGRADED:            '#fbbf24',
  BROKEN_STRUCTURE:    '#fb7185',
};
const STRUCTURE_PHASE_SHORT = {
  CONFIRMED_STRUCTURE: 'CONFIRMED',
  TRIGGERED_STRUCTURE: 'TRIGGERED',
  EARLY_STRUCTURE:     'EARLY',
  SETUP_PHASE:         'SETUP',
  IMPULSE_ONLY:        'IMPULSE',
  DEGRADED:            'DEGRADED',
  BROKEN_STRUCTURE:    'BROKEN',
};
function StructurePhaseBadge({ phase }) {
  if (!phase) return <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>—</span>;
  const color = STRUCTURE_PHASE_COLOR[phase] || '#6b7280';
  return (
    <span style={{
      color, fontWeight: 700, fontSize: 9, letterSpacing: '0.04em',
      padding: '2px 6px', borderRadius: 'var(--r-pill)',
      background: `${color}1a`, border: `1px solid ${color}44`,
      whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)',
    }}>{STRUCTURE_PHASE_SHORT[phase] || phase}</span>
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
  { key: 'split_context',                           label: 'SplitCtx',        mono: false },
  { key: 'split_artifact_risk',                     label: 'Artifact?',       mono: true,  fmt: v => v ? '⚠ YES' : '—', colorFn: v => v ? '#fb7185' : undefined },
  { key: 'nearest_split_ratio',                     label: 'SplitRatio',      mono: true,  fmt: v => v != null ? `${Number(v).toFixed(2)}×` : '—' },
  { key: 'nearest_split_days_from_breakout',        label: 'SplitΔBrk',      mono: true  },
  { key: 'dominant_structure_phase_pre',            label: 'StrPhase',        mono: false },
  { key: 'had_confirmed_structure_pre',             label: 'Confirmed?',      mono: true,  fmt: v => v ? '✓' : '—', colorFn: v => v ? '#86efac' : undefined },
  { key: 'had_np_buy_candidate_pre',                label: 'NPBuy?',          mono: true,  fmt: v => v ? '✓' : '—', colorFn: v => v ? '#86efac' : undefined },
  { key: 'd_confluence_best_type_pre',              label: 'DType',           mono: true,  fmt: v => v || '—', small: true },
];

function EpisodeTable({ episodes, symFilter, setSymFilter, groupFilter, setGroupFilter }) {
  const [hideArtifacts, setHideArtifacts] = useState(false);

  const filtered = episodes.filter(ep => {
    if (symFilter    && !ep.symbol?.toLowerCase().includes(symFilter.toLowerCase())) return false;
    if (groupFilter  && ep.group_type !== groupFilter) return false;
    if (hideArtifacts && ep.split_artifact_risk === true) return false;
    return true;
  });

  const artifactCount = episodes.filter(ep => ep.split_artifact_risk === true).length;

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
          {artifactCount > 0 && (
            <label style={{
              display: 'flex', alignItems: 'center', gap: 5,
              fontSize: 10, color: hideArtifacts ? '#fb7185' : 'var(--text-muted)',
              cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap',
            }}>
              <input
                type="checkbox"
                checked={hideArtifacts}
                onChange={e => setHideArtifacts(e.target.checked)}
                style={{ margin: 0 }}
              />
              Hide artifacts ({artifactCount})
            </label>
          )}
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
              {filtered.map((ep, i) => {
                const isArtifact = ep.split_artifact_risk === true;
                return (
                  <tr key={ep.episode_id ?? i} className={styles.dataRow}
                    style={isArtifact ? { background: 'rgba(251,113,133,0.06)' } : undefined}>
                    {EP_COLS.map(c => {
                      const raw = ep[c.key];
                      const val = c.fmt ? c.fmt(raw) : (raw ?? '—');

                      if (c.key === 'group_type') return (
                        <td key={c.key} className={styles.dataCell}>
                          <GroupBadge type={raw} />
                        </td>
                      );
                      if (c.key === 'split_context') return (
                        <td key={c.key} className={styles.dataCell}>
                          <SplitContextBadge ctx={raw} />
                        </td>
                      );
                      if (c.key === 'dominant_structure_phase_pre') return (
                        <td key={c.key} className={styles.dataCell}>
                          <StructurePhaseBadge phase={raw} />
                        </td>
                      );

                      const color = c.colorFn
                        ? (c.colorFn(raw) ?? (val === '—' ? 'var(--text-muted)' : undefined))
                        : (val === '—' ? 'var(--text-muted)' : undefined);
                      return (
                        <td key={c.key} className={styles.dataCell}
                          style={{
                            fontFamily: c.mono ? 'var(--font-mono)' : undefined,
                            fontSize:   c.small ? 9 : undefined,
                            color,
                            fontWeight: c.colorFn && c.colorFn(raw) ? 700 : undefined,
                          }}>
                          {val}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
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
  // PRIMARY — NP signal presence & timing (Scanner v2 structural core)
  'had_valid_recent_setup',
  'had_valid_recent_trigger',
  'had_valid_recent_confirm',
  'had_valid_full_sequence',
  'best_new_pump_label_rank',
  'days_from_last_setup_to_breakout',
  'days_from_last_trigger_to_breakout',
  'days_from_g4_to_b2',
  // PRIMARY — NP count-based PRE-window aggregates
  'l34_count_pre',
  'fri34_count_pre',
  'g4_count_pre',
  'b2_count_pre',
  'isolated_g4_count_pre',
  'isolated_b2_count_pre',
  'full_fri34_g4_b2_count_pre',
  'valid_setup_days_pre',
  'valid_full_sequence_days_pre',
  // SECONDARY — NP count details
  'setup_only_l34_count_pre',
  'setup_only_fri34_count_pre',
  'trigger_after_l34_count_pre',
  'trigger_after_fri34_count_pre',
  'full_l34_g4_b2_count_pre',
  'confirm_after_g4_count_pre',
  'valid_trigger_days_pre',
  'valid_confirm_days_pre',
  // PRIMARY — sequence / duration
  'days_from_breakout_to_peak',
  'compression_days_pre',
  'days_from_first_compression_to_breakout',
  'days_from_first_abnormal_volume_to_breakout',
  'dryup_day_count_pre',
  'days_in_base',
  'atr_contraction_days_pre',
  'avg_ema_spread_pre',
  'min_ema_spread_pre',
  'had_bull_stack_pre',
  'bull_stack_days_pre',
  'days_above_ema50_pre',
  'ema50_reclaim_count_pre',
  // SECONDARY — EMA position metrics
  'days_above_ema200_pre',
  'avg_close_vs_ema50_pct_pre',
  'avg_close_vs_ema200_pct_pre',
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
  // PRIMARY — Scanner v2 structural (Phase 2B-7)
  'had_confirmed_structure_pre',
  'had_triggered_structure_pre',
  'max_structure_score_pre',
  'avg_structure_score_pre',
  'had_d_confluence_pre',
  'had_core_d_beup_pre',
  'had_core_d_l34_pre',
  'd_confluence_day_count_pre',
  'd_confluence_best_type_pre',
  'had_np_buy_candidate_pre',
  'buy_candidate_day_count_pre',
  'watch_day_count_pre',
  // SECONDARY — structural detail
  'dominant_structure_phase_pre',
  'best_structure_phase_pre',
  'had_early_structure_pre',
  'had_setup_phase_pre',
  'had_impulse_only_pre',
  'had_degraded_pre',
  'had_accumulation_ready_pre',
  'had_expansion_start_pre',
  'had_overheated_expansion_pre',
  'max_expansion_timing_risk_pre',
  'high_expansion_risk_day_count_pre',
  'had_d6_beup_pre',
  'had_d4_beup_pre',
  'had_d3_beup_pre',
  'had_l34_then_d4_3b_pre',
  'had_d4_then_beup_5b_pre',
  'had_d3_beup_toxic_pre',
  'dominant_d_confluence_type_pre',
  'dominant_d_confluence_family_pre',
  'had_np_watch_pre',
  'had_np_avoid_pre',
  'max_np_structure_score_pre',
  'avoid_day_count_pre',
  'had_late_confirm_sequence_pre',
  'had_expansion_risk_flag_pre',
  'had_setup_only_l34_mid_avoid_pre',
  // SECONDARY — split context
  'has_split_near_episode',
  'has_reverse_split_near_episode',
  'split_artifact_risk',
  'reverse_split_event_count',
  'nearest_split_days_from_breakout',
];

// Used to derive badge when stats_json priority is absent (legacy runs)
const FEATURE_PRIORITY = {
  // NP signal presence & counts (Scanner v2 structural core)
  had_valid_recent_setup:            'PRIMARY',
  had_valid_recent_trigger:          'PRIMARY',
  had_valid_recent_confirm:          'PRIMARY',
  had_valid_full_sequence:           'PRIMARY',
  best_new_pump_label_rank:          'PRIMARY',
  days_from_last_setup_to_breakout:  'PRIMARY',
  days_from_last_trigger_to_breakout:'PRIMARY',
  days_from_g4_to_b2:                'PRIMARY',
  l34_count_pre:                     'PRIMARY',
  fri34_count_pre:                   'PRIMARY',
  g4_count_pre:                      'PRIMARY',
  b2_count_pre:                      'PRIMARY',
  isolated_g4_count_pre:             'PRIMARY',
  isolated_b2_count_pre:             'PRIMARY',
  full_fri34_g4_b2_count_pre:        'PRIMARY',
  valid_setup_days_pre:              'PRIMARY',
  valid_full_sequence_days_pre:      'PRIMARY',
  setup_only_l34_count_pre:          'SECONDARY',
  setup_only_fri34_count_pre:        'SECONDARY',
  trigger_after_l34_count_pre:       'SECONDARY',
  trigger_after_fri34_count_pre:     'SECONDARY',
  full_l34_g4_b2_count_pre:          'SECONDARY',
  confirm_after_g4_count_pre:        'SECONDARY',
  valid_trigger_days_pre:            'SECONDARY',
  valid_confirm_days_pre:            'SECONDARY',
  max_bull_stack_days_pre:           'PRIMARY',
  extreme_anomaly_day_count_pre:     'SECONDARY',
  median_dollar_volume_pre:          'SECONDARY',
  days_from_breakout_to_peak:                  'PRIMARY',
  compression_days_pre:                        'PRIMARY',
  days_from_first_compression_to_breakout:     'PRIMARY',
  days_from_first_abnormal_volume_to_breakout: 'PRIMARY',
  dryup_day_count_pre:                         'PRIMARY',
  days_in_base:                                'PRIMARY',
  atr_contraction_days_pre:                    'PRIMARY',
  avg_ema_spread_pre:                          'PRIMARY',
  min_ema_spread_pre:                          'PRIMARY',
  had_bull_stack_pre:                          'PRIMARY',
  bull_stack_days_pre:                         'PRIMARY',
  days_above_ema50_pre:                        'PRIMARY',
  ema50_reclaim_count_pre:                     'PRIMARY',
  days_above_ema200_pre:                       'SECONDARY',
  avg_close_vs_ema50_pct_pre:                  'SECONDARY',
  avg_close_vs_ema200_pct_pre:                 'SECONDARY',
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
  // Scanner v2 structural (Phase 2B-7)
  had_confirmed_structure_pre:                 'PRIMARY',
  had_triggered_structure_pre:                 'PRIMARY',
  max_structure_score_pre:                     'PRIMARY',
  avg_structure_score_pre:                     'PRIMARY',
  had_d_confluence_pre:                        'PRIMARY',
  had_core_d_beup_pre:                         'PRIMARY',
  had_core_d_l34_pre:                          'PRIMARY',
  d_confluence_day_count_pre:                  'PRIMARY',
  d_confluence_best_type_pre:                  'PRIMARY',
  had_np_buy_candidate_pre:                    'PRIMARY',
  buy_candidate_day_count_pre:                 'PRIMARY',
  watch_day_count_pre:                         'PRIMARY',
  dominant_structure_phase_pre:                'SECONDARY',
  best_structure_phase_pre:                    'SECONDARY',
  had_early_structure_pre:                     'SECONDARY',
  had_setup_phase_pre:                         'SECONDARY',
  had_impulse_only_pre:                        'SECONDARY',
  had_degraded_pre:                            'SECONDARY',
  had_accumulation_ready_pre:                  'SECONDARY',
  had_expansion_start_pre:                     'SECONDARY',
  had_overheated_expansion_pre:                'SECONDARY',
  max_expansion_timing_risk_pre:               'SECONDARY',
  high_expansion_risk_day_count_pre:           'SECONDARY',
  had_d6_beup_pre:                             'SECONDARY',
  had_d4_beup_pre:                             'SECONDARY',
  had_d3_beup_pre:                             'SECONDARY',
  had_l34_then_d4_3b_pre:                      'SECONDARY',
  had_d4_then_beup_5b_pre:                     'SECONDARY',
  had_d3_beup_toxic_pre:                       'SECONDARY',
  dominant_d_confluence_type_pre:              'SECONDARY',
  dominant_d_confluence_family_pre:            'SECONDARY',
  had_np_watch_pre:                            'SECONDARY',
  had_np_avoid_pre:                            'SECONDARY',
  max_np_structure_score_pre:                  'SECONDARY',
  avoid_day_count_pre:                         'SECONDARY',
  had_late_confirm_sequence_pre:               'SECONDARY',
  had_expansion_risk_flag_pre:                 'SECONDARY',
  had_setup_only_l34_mid_avoid_pre:            'SECONDARY',
  // Split context
  has_split_near_episode:                      'SECONDARY',
  has_reverse_split_near_episode:              'SECONDARY',
  split_artifact_risk:                         'SECONDARY',
  reverse_split_event_count:                   'SECONDARY',
  nearest_split_days_from_breakout:            'SECONDARY',
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
      <div className={styles.excludedNote}>
        <strong>missed_mover</strong> is excluded from this table — no deterministic pre-pump
        anchor dates exist, so PRE-window feature extraction is structurally impossible.
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
  const t    = scheme.typical_timing || {};
  const sep  = scheme.separator_strength;
  const sepNw = scheme.separator_vs_normal_winner;

  const sepLabel = sep == null ? null
    : sep >= 2   ? `${sep}× vs fp`
    : sep >= 1.2 ? `${sep}× vs fp`
    : `${sep}× vs fp (weak)`;

  const sepNwLabel = sepNw == null ? null
    : sepNw >= 2   ? `${sepNw}× vs nw`
    : sepNw >= 1.2 ? `${sepNw}× vs nw`
    : `${sepNw}× vs nw (weak)`;

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
        {sepNwLabel && (
          <span className={styles.schemeSepNwBadge}>
            {sepNwLabel}
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
          {t.avg_days_above_ema50 != null && (
            <span className={styles.timingChip}><span className={styles.timingKey}>ema50↑</span><span className={styles.timingVal}>{t.avg_days_above_ema50}d</span></span>
          )}
          {t.avg_ema_spread_pre != null && (
            <span className={styles.timingChip}><span className={styles.timingKey}>ema·spr</span><span className={styles.timingVal}>{t.avg_ema_spread_pre}%</span></span>
          )}
          {t.bull_stack_pct != null && (
            <span className={styles.timingChip}><span className={styles.timingKey}>bull·stk</span><span className={styles.timingVal}>{Math.round(t.bull_stack_pct * 100)}%</span></span>
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

      {absent_groups.filter(g => g !== 'missed_mover').length > 0 && (
        <div className={styles.schemesAbsent}>
          Groups absent from data:{' '}
          <strong>{absent_groups.filter(g => g !== 'missed_mover').join(', ')}</strong>
          {' '}— conclusions for these groups unavailable.
        </div>
      )}
      <div className={styles.excludedNote}>
        <strong>missed_mover</strong> is formally excluded from episode-feature comparisons
        — no deterministic pre-pump anchor dates exist.
      </div>

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
  { key: 'scanner_v2_changes',          label: 'Scanner v2 improvements' },
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

// ── Engine Patch Plan ─────────────────────────────────────────────────────────

const VERDICT_STYLE = {
  BOOST:    { color: 'var(--lime,  #86efac)', label: 'BOOST'    },
  INCREASE: { color: 'var(--cyan,  #22d3ee)', label: 'INCREASE' },
  PENALIZE: { color: 'var(--red,   #f87171)', label: 'PENALIZE' },
  REDUCE:   { color: 'var(--amber, #fbbf24)', label: 'REDUCE'   },
  IGNORE:   { color: 'var(--text-muted)',      label: 'IGNORE'   },
};

const REC_AREA_LABEL = {
  sequence_duration_weights:  'Sequence / Duration',
  compression_persistence:    'Compression Persistence',
  volume_sweet_spot:          'Volume Sweet-Spot',
  accumulation_spring_reclaim:'Accumulation / Spring / Reclaim',
  ema_ribbon_quality:         'EMA Structure Quality',
  body_wick_noise_reduction:  'Body / Wick Noise Reduction',
  scanner_v2_structural:      'Scanner v2 — NP Signal Chain',
};

function EnginePatchPlan({ runId }) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState('');

  const load = useCallback(() => {
    setLoading(true); setError(''); setData(null);
    fetch(`${API_URL}/api/replay/raw-pattern-study/${runId}/engine-patch-plan`)
      .then(r => r.json())
      .then(d => {
        if (!d.ok) throw new Error(d.detail || 'Server error');
        setData(d); setLoading(false);
      })
      .catch(e => { setError(String(e)); setLoading(false); });
  }, [runId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className={styles.statusMsg}>Building patch plan…</div>;
  if (error)   return (
    <div className={styles.errorMsg}>
      {error.replace('TypeError: ', '').replace('Error: ', '')}
      <button onClick={load} style={{ marginLeft: 12, fontSize: 11, cursor: 'pointer' }}>Retry</button>
    </div>
  );
  if (!data)   return null;
  if (data.has_data === false) return (
    <div className={styles.statusMsg}>
      {(data.summary && data.summary.note) || 'No engine plan available for this run.'}
    </div>
  );

  const { feature_verdicts = [], recommendations = [], summary = {} } = data;

  return (
    <div>
      {/* Summary row */}
      <div className={styles.tableCard} style={{ marginBottom: 12 }}>
        <div className={styles.tableHeader}>
          <span className={styles.tableTitle}>Scanner v2 Patch Plan</span>
          <span className={styles.tableHint}>deterministic · based on comparison medians · no AI</span>
        </div>
        <div style={{ display: 'flex', gap: 16, padding: '8px 12px', flexWrap: 'wrap' }}>
          {[['BOOST', summary.boost_count], ['INCREASE', summary.increase_count],
            ['PENALIZE', summary.penalize_count], ['REDUCE', summary.reduce_count],
            ['IGNORE', summary.ignore_count]].map(([v, n]) => (
            <span key={v} style={{ fontSize: 11, color: VERDICT_STYLE[v]?.color }}>
              {v} <strong>{n ?? 0}</strong>
            </span>
          ))}
          {!summary.ema_data_available && (
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontStyle: 'italic' }}>
              EMA data not yet populated
            </span>
          )}
          {!summary.delta_available && (
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontStyle: 'italic' }}>
              delta deferred
            </span>
          )}
        </div>
        {summary.note && (
          <div className={styles.excludedNote} style={{ margin: '0 12px 10px' }}>{summary.note}</div>
        )}
      </div>

      {/* Domain recommendations */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
        {recommendations.map(rec => {
          const vs = VERDICT_STYLE[rec.action] || VERDICT_STYLE.REDUCE;
          return (
            <div key={rec.area} className={styles.tableCard} style={{ padding: '8px 12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 10, fontWeight: 700, color: vs.color, minWidth: 64 }}>{vs.label}</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>
                  {REC_AREA_LABEL[rec.area] || rec.area}
                </span>
                {rec.delta_available === false && (
                  <span style={{ fontSize: 9, color: 'var(--text-muted)', fontStyle: 'italic' }}>delta deferred</span>
                )}
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-dim)', marginBottom: 4 }}>{rec.rationale}</div>
              {rec.boost?.length > 0 && (
                <div style={{ fontSize: 10 }}>
                  <span style={{ color: 'var(--lime, #86efac)' }}>↑ </span>
                  {rec.boost.join(', ')}
                </div>
              )}
              {rec.reduce?.length > 0 && (
                <div style={{ fontSize: 10 }}>
                  <span style={{ color: 'var(--amber, #fbbf24)' }}>↓ </span>
                  {rec.reduce.join(', ')}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Feature verdicts table */}
      <div className={styles.tableCard}>
        <div className={styles.tableHeader}>
          <span className={styles.tableTitle}>Feature Verdicts</span>
          <span className={styles.tableHint}>sorted by verdict · sep = 4x_median / group_median</span>
        </div>
        <div className={styles.tableScroll}>
          <table className={styles.dataTable}>
            <thead>
              <tr>
                <th className={styles.dataHead} style={{ minWidth: 220 }}>Feature</th>
                <th className={styles.dataHead}>Priority</th>
                <th className={styles.dataHead}>Verdict</th>
                <th className={styles.dataHead}>sep vs fp</th>
                <th className={styles.dataHead}>sep vs nw</th>
                <th className={styles.dataHead}>4x med</th>
                <th className={styles.dataHead}>fp med</th>
                <th className={styles.dataHead}>Reason</th>
              </tr>
            </thead>
            <tbody>
              {feature_verdicts.map(v => {
                const vs = VERDICT_STYLE[v.verdict] || VERDICT_STYLE.REDUCE;
                return (
                  <tr key={v.feature} className={styles.dataRow}>
                    <td className={styles.dataCell}>{v.feature}</td>
                    <td className={styles.dataCell}>
                      <span className={styles[{ PRIMARY: 'priBadge', SECONDARY: 'secBadge', LOW_SIGNAL: 'lowBadge' }[v.priority] || 'lowBadge']}>
                        {v.priority === 'PRIMARY' ? 'PRI' : v.priority === 'SECONDARY' ? 'SEC' : 'LOW'}
                      </span>
                    </td>
                    <td className={styles.dataCell}>
                      <span style={{ fontSize: 10, fontWeight: 700, color: vs.color }}>{vs.label}</span>
                    </td>
                    <td className={styles.dataCell}>{v.sep_vs_fp ?? '—'}</td>
                    <td className={styles.dataCell}>{v.sep_vs_nw ?? '—'}</td>
                    <td className={styles.dataCell}>{v.median_4x != null ? fmtNum(v.median_4x) : '—'}</td>
                    <td className={styles.dataCell}>{v.median_fp  != null ? fmtNum(v.median_fp)  : '—'}</td>
                    <td className={styles.dataCell} style={{ maxWidth: 300, fontSize: 10, color: 'var(--text-dim)' }}>{v.reason}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── NP Bundle Panel ───────────────────────────────────────────────────────────

const NP_GROUP_COLOR = {
  '4x_pump':       '#22d3ee',
  'normal_winner': '#86efac',
  'false_positive':'#fca5a5',
  'missed_mover':  '#fde68a',
};

function NPBundlePanel({ runId }) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(''); setData(null);
    fetch(`${API_URL}/api/replay/raw-pattern-study/${runId}/np-count-bundle`)
      .then(r => r.json().then(d => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (cancelled) return;
        if (!ok) throw new Error(d.detail || `HTTP error`);
        setData(d);
      })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [runId]);

  if (loading) return <div className={styles.statusMsg}>Loading NP bundle…</div>;
  if (error)   return <div className={styles.errorMsg}>{error.replace('TypeError: ', '').replace('Error: ', '')}</div>;
  if (!data)   return null;

  const analysis       = data.np_count_analysis || {};
  const groupCounts    = data.group_counts || {};
  const patternReview  = analysis.count_pattern_review || [];
  const sepSummary     = analysis.separation_summary || [];
  const setupAnalysis  = analysis.setup_analysis || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* Group counts */}
      <div className={styles.tableCard}>
        <div className={styles.tableHeader}>
          <span className={styles.tableTitle}>Group Counts</span>
          <span className={styles.tableHint}>total episodes: {data.total_episodes ?? '—'}</span>
        </div>
        <div style={{ display: 'flex', gap: 20, padding: '10px 12px', flexWrap: 'wrap' }}>
          {Object.entries(groupCounts).map(([g, n]) => (
            <span key={g} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: NP_GROUP_COLOR[g] || '#888', display: 'inline-block' }} />
              <span style={{ color: 'var(--text-muted)', textTransform: 'uppercase', fontSize: 10 }}>{g.replace(/_/g, ' ')}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--text)' }}>{n}</span>
            </span>
          ))}
        </div>
      </div>

      {/* Count pattern review */}
      {patternReview.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Count Pattern Review</span>
          </div>
          <ul style={{ margin: '8px 12px 10px', padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 6 }}>
            {patternReview.map((item, i) => (
              <li key={i} style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.5, paddingLeft: 14, position: 'relative' }}>
                <span style={{ position: 'absolute', left: 0, color: 'var(--cyan, #22d3ee)' }}>·</span>
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Separation summary table */}
      {sepSummary.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Separation Summary</span>
            <span className={styles.tableHint}>NP count metrics vs group medians</span>
          </div>
          <div className={styles.tableScroll}>
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  {Object.keys(sepSummary[0]).map(k => (
                    <th key={k} className={styles.dataHead}>{k.replace(/_/g, ' ')}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sepSummary.map((row, i) => (
                  <tr key={i} className={styles.dataRow}>
                    {Object.entries(row).map(([k, v]) => (
                      <td key={k} className={styles.dataCell}>
                        {v == null ? '—' : typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(v)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Setup analysis */}
      {setupAnalysis.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Setup Analysis</span>
          </div>
          <ul style={{ margin: '8px 12px 10px', padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: 6 }}>
            {setupAnalysis.map((item, i) => (
              <li key={i} style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.5, paddingLeft: 14, position: 'relative' }}>
                <span style={{ position: 'absolute', left: 0, color: 'var(--lime, #86efac)' }}>·</span>
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      {patternReview.length === 0 && sepSummary.length === 0 && setupAnalysis.length === 0 && (
        <div className={styles.statusMsg}>No NP bundle analysis available for this run.</div>
      )}
    </div>
  );
}

// ── Split Impact Panel ────────────────────────────────────────────────────────

const SPLIT_CTX_COLOR = {
  NO_SPLIT:              'var(--text-muted)',
  FORWARD_SPLIT:         'var(--blue,  #60a5fa)',
  RECENT_REVERSE_SPLIT:  'var(--amber, #fbbf24)',
  OLD_REVERSE_SPLIT:     'var(--text-dim)',
  SPLIT_DURING_PUMP:     'var(--orange, #fb923c)',
  SPLIT_ARTIFACT_RISK:   'var(--rose,  #fb7185)',
};

function SplitImpactPanel({ runId }) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(false);
  const [err,     setErr]     = useState('');

  useEffect(() => {
    setLoading(true); setErr(''); setData(null);
    fetch(`${API_URL}/api/replay/raw-pattern-study/${runId}/split-impact`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(d => setData(d))
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false));
  }, [runId]);

  if (loading) return <div className={styles.statusMsg}>Loading split impact…</div>;
  if (err)     return <div className={styles.errorMsg}>Split impact error: {err}</div>;
  if (!data)   return null;

  const byCtx    = data.performance_by_split_context         || {};
  const byTiming = data.performance_by_reverse_split_timing  || {};
  const artifacts = data.split_artifact_candidates           || [];
  // summary is a list of strings from the backend
  const summaryLines = Array.isArray(data.split_impact_summary)
    ? data.split_impact_summary
    : (data.split_impact_summary ? [String(data.split_impact_summary)] : []);
  // recs is a list of dicts from the backend
  const recs = Array.isArray(data.scanner_v2_split_patch_recommendations)
    ? data.scanner_v2_split_patch_recommendations
    : [];

  const fmtCount = (row, key) => row[key] ?? '—';
  const fmtRate  = (row, key) => row[key] != null ? `${(Number(row[key]) * 100).toFixed(1)}%` : '—';
  const fmtPctOf = (num, denom) =>
    num != null && denom > 0 ? `${((num / denom) * 100).toFixed(1)}%` : '—';
  const fmtRet   = (row, key) => row[key] != null ? `${Number(row[key]).toFixed(1)}%` : '—';

  const hasAnyData = Object.keys(byCtx).length > 0 || artifacts.length > 0 || recs.length > 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

      {/* Summary lines */}
      {summaryLines.length > 0 && (
        <div className={styles.tableCard} style={{ padding: '10px 14px' }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.07em',
                        color: 'var(--text-muted)', textTransform: 'uppercase',
                        marginBottom: 6 }}>Summary</div>
          {summaryLines.map((line, i) => (
            <div key={i} style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.6,
                                  fontFamily: 'var(--font-mono)' }}>{line}</div>
          ))}
        </div>
      )}

      {/* Performance by split context */}
      {Object.keys(byCtx).some(k => (byCtx[k].episode_count || 0) > 0) && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Performance by Split Context</span>
            <span className={styles.tableHint}>
              episode_count · 4x% · fp% · avg return · med return
            </span>
          </div>
          <div className={styles.tableScroll}>
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th className={styles.dataHead}>Context</th>
                  <th className={styles.dataHead}>N</th>
                  <th className={styles.dataHead}>4×%</th>
                  <th className={styles.dataHead}>FP%</th>
                  <th className={styles.dataHead}>FP Rate</th>
                  <th className={styles.dataHead}>Avg Ret</th>
                  <th className={styles.dataHead}>Med Ret</th>
                  <th className={styles.dataHead}>Avg Days</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(byCtx)
                  .filter(([, row]) => (row.episode_count || 0) > 0)
                  .map(([ctx, row]) => (
                    <tr key={ctx} className={styles.dataRow}>
                      <td className={styles.dataCell}
                        style={{ color: SPLIT_CTX_COLOR[ctx] || 'var(--text)', fontWeight: 600, fontSize: 11 }}>
                        {ctx}
                      </td>
                      <td className={styles.dataCell}>{fmtCount(row, 'episode_count')}</td>
                      <td className={styles.dataCell}>{fmtPctOf(row['4x_pump_count'], row.episode_count)}</td>
                      <td className={styles.dataCell}>{fmtPctOf(row['false_positive_count'], row.episode_count)}</td>
                      <td className={styles.dataCell}>{fmtRate(row, 'false_positive_rate')}</td>
                      <td className={styles.dataCell}>{fmtRet(row, 'avg_pump_return_pct')}</td>
                      <td className={styles.dataCell}>{fmtRet(row, 'median_pump_return_pct')}</td>
                      <td className={styles.dataCell}>
                        {row.avg_days_to_peak != null ? `${Number(row.avg_days_to_peak).toFixed(1)}d` : '—'}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Performance by reverse-split timing */}
      {Object.keys(byTiming).some(k => (byTiming[k].episode_count || 0) > 0) && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Performance by Reverse-Split Timing Bucket</span>
          </div>
          <div className={styles.tableScroll}>
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th className={styles.dataHead}>Timing bucket</th>
                  <th className={styles.dataHead}>N</th>
                  <th className={styles.dataHead}>4×%</th>
                  <th className={styles.dataHead}>FP%</th>
                  <th className={styles.dataHead}>FP Rate</th>
                  <th className={styles.dataHead}>Med Ret</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(byTiming)
                  .filter(([, row]) => (row.episode_count || 0) > 0)
                  .map(([bucket, row]) => (
                    <tr key={bucket} className={styles.dataRow}>
                      <td className={styles.dataCell}
                        style={{ fontSize: 11, color: 'var(--amber, #fbbf24)', fontFamily: 'var(--font-mono)' }}>
                        {bucket}
                      </td>
                      <td className={styles.dataCell}>{fmtCount(row, 'episode_count')}</td>
                      <td className={styles.dataCell}>{fmtPctOf(row['4x_pump_count'], row.episode_count)}</td>
                      <td className={styles.dataCell}>{fmtPctOf(row['false_positive_count'], row.episode_count)}</td>
                      <td className={styles.dataCell}>{fmtRate(row, 'false_positive_rate')}</td>
                      <td className={styles.dataCell}>{fmtRet(row, 'median_pump_return_pct')}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Split artifact candidates */}
      {artifacts.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle} style={{ color: 'var(--rose, #fb7185)' }}>
              Split Artifact Candidates ({artifacts.length})
            </span>
            <span className={styles.tableHint}>price jump ≈ split ratio · exclude from calibration</span>
          </div>
          <div className={styles.tableScroll}>
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th className={styles.dataHead}>Symbol</th>
                  <th className={styles.dataHead}>Group</th>
                  <th className={styles.dataHead}>Raw Move</th>
                  <th className={styles.dataHead}>Split Ratio</th>
                  <th className={styles.dataHead}>Split Type</th>
                  <th className={styles.dataHead}>Adj Est</th>
                  <th className={styles.dataHead}>Reason</th>
                </tr>
              </thead>
              <tbody>
                {artifacts.map((a, i) => (
                  <tr key={i} className={styles.dataRow}>
                    <td className={styles.dataCell}
                      style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{a.symbol}</td>
                    <td className={styles.dataCell}><GroupBadge type={a.group_type} /></td>
                    <td className={styles.dataCell}>
                      {a.raw_move_pct != null ? `${Number(a.raw_move_pct).toFixed(1)}%` : '—'}
                    </td>
                    <td className={styles.dataCell}>
                      {a.split_ratio != null ? `${Number(a.split_ratio).toFixed(2)}×` : '—'}
                    </td>
                    <td className={styles.dataCell}
                      style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--amber, #fbbf24)' }}>
                      {a.split_type || '—'}
                    </td>
                    <td className={styles.dataCell}>
                      {a.split_adjusted_move_estimate != null
                        ? `${Number(a.split_adjusted_move_estimate).toFixed(1)}%` : '—'}
                    </td>
                    <td className={styles.dataCell}
                      style={{ fontSize: 10, color: 'var(--text-dim)', maxWidth: 260 }}>
                      {a.split_artifact_reason || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Scanner v2 patch recommendations */}
      {recs.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Scanner v2 Split Patch Recommendations</span>
            <span className={styles.tableHint}>reporting only — no scoring changes applied</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, padding: '10px 14px' }}>
            {recs.map((r, i) => {
              const delta = r.suggested_score_delta;
              const deltaStr = delta != null ? (delta > 0 ? `+${delta}` : String(delta)) : null;
              return (
                <div key={i} style={{
                  background: 'var(--surface2)', border: '1px solid var(--border)',
                  borderRadius: 'var(--r-sm)', padding: '8px 12px',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700,
                                   color: 'var(--amber, #fbbf24)' }}>
                      {r.suggested_flag || 'flag'}
                    </span>
                    {deltaStr && (
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10,
                                     color: delta < 0 ? 'var(--red, #f87171)' : 'var(--lime, #86efac)' }}>
                        {deltaStr} pts
                      </span>
                    )}
                    {r.confidence && (
                      <span style={{ fontSize: 9, color: 'var(--text-muted)',
                                     border: '1px solid var(--border)', borderRadius: 3,
                                     padding: '1px 5px' }}>
                        {r.confidence}
                      </span>
                    )}
                    {r.sample_size != null && (
                      <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>
                        n={r.sample_size}
                      </span>
                    )}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.5 }}>
                    {r.evidence || '—'}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {!hasAnyData && (
        <div className={styles.statusMsg}>
          No split impact data for this run — splits phase may not have run yet.
        </div>
      )}
    </div>
  );
}

// ── Pattern Discovery Panel ───────────────────────────────────────────────────

const WINDOWS_ALL = [1, 2, 3, 5, 10];
const WINDOW_LABELS = { 1: '1 (single bar)', 2: '2 (two-bar seq)', 3: '3 (three-bar seq)', 5: '5 (five-bar)', 10: '10 (context)' };
const SOURCE_TYPE_LABELS = {
  SINGLE_BAR:         'Single Bar',
  TWO_BAR_SEQUENCE:   'Two-Bar Seq',
  THREE_BAR_SEQUENCE: 'Three-Bar Seq',
  FIVE_BAR_SEQUENCE:  'Five-Bar',
  TEN_BAR_CONTEXT:    'Ten-Bar Context',
  EPISODE_AGGREGATE:  'Episode Agg',
};

function normalizeSourceType(sourceType, signalId) {
  if (sourceType && sourceType !== 'EPISODE_AGGREGATE') return sourceType;
  if (!signalId) return 'EPISODE_AGGREGATE';
  if (signalId.startsWith('DISC_BAR_TEN_BAR_CONTEXT_'))    return 'TEN_BAR_CONTEXT';
  if (signalId.startsWith('DISC_BAR_THREE_BAR_SEQUENCE_')) return 'THREE_BAR_SEQUENCE';
  if (signalId.startsWith('DISC_BAR_TWO_BAR_SEQUENCE_'))   return 'TWO_BAR_SEQUENCE';
  if (signalId.startsWith('DISC_BAR_FIVE_BAR_SEQUENCE_'))  return 'FIVE_BAR_SEQUENCE';
  if (signalId.startsWith('DISC_BAR_SINGLE_BAR_'))         return 'SINGLE_BAR';
  return sourceType || 'EPISODE_AGGREGATE';
}
const STATUS_COLOR = {
  EXPERIMENTAL:      'var(--lime)',
  EXPERIMENTAL_RARE: 'var(--cyan)',
  RESEARCH_ONLY:     'var(--amber)',
  REJECT:            'var(--red)',
};

function fmtPct(v) { return v == null ? '—' : `${(Number(v) * 100).toFixed(1)}%`; }
function fmtLift(v) { return v == null ? '—' : `${Number(v).toFixed(2)}×`; }

const FF_COLOR = { FLOW: 'var(--blue)', COMBINED: 'var(--purple, #a855f7)' };

function PatternRow({ p }) {
  const st = normalizeSourceType(p.source_type, p.signal_id);
  const ff = p.feature_family;
  const showFfBadge = ff === 'FLOW' || ff === 'COMBINED';
  return (
    <tr>
      <td className={styles.dataCell} style={{ fontFamily: 'var(--font-mono)', fontSize: 9 }}>
        {p.signal_id}
      </td>
      <td className={styles.dataCell} style={{ fontSize: 9, color: 'var(--text-muted)' }}>
        <span style={{ border: '1px solid var(--border)', borderRadius: 3, padding: '1px 5px',
                       fontSize: 8, color: 'var(--text-muted)' }}>
          {SOURCE_TYPE_LABELS[st] || st}
        </span>
        {showFfBadge && (
          <span style={{ marginLeft: 4, border: `1px solid ${FF_COLOR[ff]}`, borderRadius: 3,
                         padding: '1px 4px', fontSize: 8, color: FF_COLOR[ff] }}>
            {ff}
          </span>
        )}
      </td>
      <td className={styles.dataCell}>
        <span style={{ fontSize: 9, fontWeight: 600, color: STATUS_COLOR[p.status] || 'inherit' }}>
          {p.status}
        </span>
      </td>
      <td className={styles.dataCell} style={{ fontFamily: 'var(--font-mono)', fontSize: 10,
                                               color: 'var(--lime)' }}>
        {fmtLift(p.lift_vs_false_positive)}
      </td>
      <td className={styles.dataCell} style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
        {p.count_all_4x ?? '—'}
      </td>
      <td className={styles.dataCell} style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
        {p.count_missed_4x ?? '—'}
      </td>
      <td className={styles.dataCell} style={{ fontFamily: 'var(--font-mono)', fontSize: 10,
                                               color: 'var(--red)' }}>
        {fmtPct(p.false_positive_rate)}
      </td>
      <td className={styles.dataCell} style={{ fontSize: 10, maxWidth: 260,
                                               color: 'var(--text-dim)' }}>
        {p.description || p.sequence_signature || '—'}
      </td>
    </tr>
  );
}

function PatternDiscoveryPanel({ runId }) {
  // Controls
  const [mode,        setMode]        = useState('both');
  const [windows,     setWindows]     = useState([1, 2, 3, 5, 10]);
  const [excludeSplit, setExcludeSplit] = useState(true);

  // Launch state
  const [launching,   setLaunching]   = useState(false);
  const [launchErr,   setLaunchErr]   = useState('');

  // Status polling
  const [status,      setStatus]      = useState(null);   // null | progress dict
  const [polling,     setPolling]     = useState(false);
  const pollRef = useRef(null);

  // Results
  const [results,     setResults]     = useState(null);
  const [loadingRes,  setLoadingRes]  = useState(false);
  const [resErr,      setResErr]      = useState('');

  // Sub-tab inside results
  const [resTab, setResTab] = useState('top-lift');

  // FLOW Impact tab — lazy-loaded from summary export
  const [flowImpact,        setFlowImpact]        = useState(null);
  const [loadingFlowImpact, setLoadingFlowImpact] = useState(false);
  const [flowImpactErr,     setFlowImpactErr]     = useState('');

  // Curated FLOW Replay tab — lazy-loaded from summary export
  const [curatedFlow,        setCuratedFlow]        = useState(null);
  const [loadingCuratedFlow, setLoadingCuratedFlow] = useState(false);
  const [curatedFlowErr,     setCuratedFlowErr]     = useState('');

  const stopPoll = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    setPolling(false);
  };

  const fetchFlowImpact = async () => {
    if (flowImpact || loadingFlowImpact) return;
    setLoadingFlowImpact(true);
    setFlowImpactErr('');
    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/${runId}/discover/export-full?section=summary`);
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail || `HTTP ${r.status}`); }
      const d = await r.json();
      setFlowImpact(d.flow_replay_analysis || {});
    } catch (e) {
      setFlowImpactErr(String(e));
    } finally {
      setLoadingFlowImpact(false);
    }
  };

  const fetchCuratedFlow = async () => {
    if (curatedFlow || loadingCuratedFlow) return;
    setLoadingCuratedFlow(true);
    setCuratedFlowErr('');
    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/${runId}/discover/export-full?section=summary`);
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail || `HTTP ${r.status}`); }
      const d = await r.json();
      setCuratedFlow(d.curated_flow_replay_analysis || {});
    } catch (e) {
      setCuratedFlowErr(String(e));
    } finally {
      setLoadingCuratedFlow(false);
    }
  };

  const fetchStatus = async () => {
    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/${runId}/discover/status`);
      if (!r.ok) return;
      const d = await r.json();
      setStatus(d);
      if (!d.running && d.phase === 'COMPLETE') {
        stopPoll();
        fetchResults();
      } else if (!d.running && d.phase === 'ERROR') {
        stopPoll();
      }
    } catch { /* ignore */ }
  };

  const fetchResults = async () => {
    setLoadingRes(true);
    setResErr('');
    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/${runId}/discover/results`);
      if (!r.ok) { const d = await r.json(); throw new Error(d.detail || `HTTP ${r.status}`); }
      const d = await r.json();
      setResults(d);
    } catch (e) {
      setResErr(String(e));
    } finally {
      setLoadingRes(false);
    }
  };

  // On mount, fetch current status (to detect a prior run)
  useEffect(() => {
    fetchStatus();
    return () => stopPoll();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const toggleWindow = (w) => {
    setWindows(prev => prev.includes(w) ? prev.filter(x => x !== w) : [...prev, w].sort((a,b)=>a-b));
  };

  const handleLaunch = async () => {
    if (windows.length === 0) { setLaunchErr('Select at least one window size.'); return; }
    setLaunching(true);
    setLaunchErr('');
    setResults(null);
    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/${runId}/discover`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ mode, windows, exclude_split_artifacts: excludeSplit }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || `HTTP ${r.status}`);
      if (d.status === 'ALREADY_RUNNING') {
        setLaunchErr('Discovery is already running for this run.');
      } else {
        // Start polling
        setPolling(true);
        pollRef.current = setInterval(fetchStatus, 2500);
      }
    } catch (e) {
      setLaunchErr(String(e));
    } finally {
      setLaunching(false);
    }
  };

  // Derive status label
  const isRunning = status?.running;
  const phase     = status?.phase;
  const hasError  = phase === 'ERROR';
  const isComplete = phase === 'COMPLETE';

  // Parse patterns out of results
  const patterns = results?.patterns || [];
  const bySourceType = {};
  for (const p of patterns) {
    const st = normalizeSourceType(p.source_type, p.signal_id);
    (bySourceType[st] = bySourceType[st] || []).push(p);
  }

  // feature_family breakdown
  const byFamily = {};
  for (const p of patterns) {
    const ff = p.feature_family || 'EPISODE_AGGREGATE';
    (byFamily[ff] = byFamily[ff] || []).push(p);
  }
  const flowPatterns     = byFamily['FLOW']     || [];
  const combinedPatterns = byFamily['COMBINED'] || [];

  // Top by lift
  const topByLift = [...patterns]
    .filter(p => p.lift_vs_false_positive != null)
    .sort((a, b) => (b.lift_vs_false_positive || 0) - (a.lift_vs_false_positive || 0))
    .slice(0, 10);

  // Top by missed_4x catch
  const topByMissed = [...patterns]
    .filter(p => p.count_missed_4x != null)
    .sort((a, b) => (b.count_missed_4x || 0) - (a.count_missed_4x || 0))
    .slice(0, 10);

  // Top flow patterns by lift
  const topFlowByLift = [...flowPatterns]
    .filter(p => p.lift_vs_false_positive != null)
    .sort((a, b) => (b.lift_vs_false_positive || 0) - (a.lift_vs_false_positive || 0))
    .slice(0, 10);

  // Top combined patterns by lift
  const topCombinedByLift = [...combinedPatterns]
    .filter(p => p.lift_vs_false_positive != null)
    .sort((a, b) => (b.lift_vs_false_positive || 0) - (a.lift_vs_false_positive || 0))
    .slice(0, 10);

  // Contamination warnings
  const contaminated = patterns.filter(p => (p.split_artifact_exposure || 0) > 0.5);

  const PHASE_LABEL = {
    LOADING_DATASET:         'Loading episodes…',
    PATTERN_MINING_V1A:      'Mining episode patterns (V1A)…',
    LOADING_BAR_FEATURES:    'Loading bar features…',
    BUILDING_BAR_SEQUENCES:  'Building bar sequences…',
    MINING_BAR_PATTERNS:     'Mining bar patterns (V1B)…',
    MINING_FLOW_PATTERNS:    'Mining flow patterns (V1C)…',
    MINING_COMBINED_PATTERNS:'Mining combined patterns (V1C)…',
    PUMP_WATCH_SCORING:      'Scoring Pump Watch…',
    PERSISTING_SCORES:       'Persisting scores…',
    PERSISTING_PATTERNS:     'Persisting patterns…',
    UPDATING_REGISTRY:       'Updating registry…',
    BUILDING_REPORT:         'Building report…',
    COMPLETE:                'Complete',
    ERROR:                   'Error',
  };

  return (
    <div className={styles.discoveryPanel}>
      {/* ── Controls ─────────────────────────────────────────────────────── */}
      <div className={styles.discoveryControls}>
        <div className={styles.discoveryControlsTitle}>Pattern Discovery</div>
        <div className={styles.discoveryNote}>
          Mines pre-breakout bar patterns from completed run data. Does NOT modify Scanner V2 routing.
        </div>

        <div className={styles.discoveryRow}>
          {/* Mode select */}
          <div className={styles.discoveryField}>
            <label className={styles.discoveryLabel}>Mode</label>
            <select
              className={styles.discoverySelect}
              value={mode}
              onChange={e => setMode(e.target.value)}
              disabled={isRunning || launching}
            >
              <option value="both">Both (V1A + V1B)</option>
              <option value="episode_aggregate">Episode Aggregate only (V1A, fast)</option>
              <option value="bar_sequence">Bar Sequence only (V1B)</option>
              <option value="flow">Flow Only (V1C — OHLCV proxy)</option>
              <option value="combined">Combined Price+Flow (V1B+V1C)</option>
              <option value="all">All (V1A + V1B + V1C)</option>
            </select>
          </div>

          {/* Windows multi-select */}
          <div className={styles.discoveryField}>
            <label className={styles.discoveryLabel}>Bar Windows</label>
            <div className={styles.windowCheckboxes}>
              {WINDOWS_ALL.map(w => (
                <label key={w} className={styles.windowCheckLabel}>
                  <input
                    type="checkbox"
                    checked={windows.includes(w)}
                    onChange={() => toggleWindow(w)}
                    disabled={isRunning || launching || mode === 'episode_aggregate' || mode === 'flow'}
                  />
                  {WINDOW_LABELS[w]}
                </label>
              ))}
            </div>
          </div>

          {/* Exclude split artifacts */}
          <div className={styles.discoveryField}>
            <label className={styles.windowCheckLabel}>
              <input
                type="checkbox"
                checked={excludeSplit}
                onChange={e => setExcludeSplit(e.target.checked)}
                disabled={isRunning || launching}
              />
              Exclude split artifacts from counts
            </label>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 12 }}>
          <button
            className={styles.runBtn}
            onClick={handleLaunch}
            disabled={isRunning || launching}
            style={{ minWidth: 160 }}
          >
            {launching ? 'Starting…' : isRunning ? 'Running…' : 'Run Pattern Discovery'}
          </button>

          {results && !isRunning && (
            <button
              className={styles.discoveryRefreshBtn}
              onClick={fetchResults}
              disabled={loadingRes}
            >
              {loadingRes ? '…' : '↻ Refresh Results'}
            </button>
          )}

          {results && !isRunning && (
            <span style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
              <a
                href={`${API_URL}/api/replay/raw-pattern-study/${runId}/discover/export-full?section=compact`}
                download={`raw-pattern-run-${runId}-discovery-compact.json`}
                className={styles.discoveryExportBtn}
                style={{ textDecoration: 'none' }}
              >
                ⬇ Compact JSON
              </a>
              <a
                href={`${API_URL}/api/replay/raw-pattern-study/${runId}/discover/export-full?section=summary`}
                download={`raw-pattern-run-${runId}-discovery-summary.json`}
                className={styles.discoveryExportBtnSm}
                style={{ textDecoration: 'none' }}
              >
                Summary
              </a>
              <a
                href={`${API_URL}/api/replay/raw-pattern-study/${runId}/discover/export-full?section=accepted`}
                download={`raw-pattern-run-${runId}-discovery-accepted.json`}
                className={styles.discoveryExportBtnSm}
                style={{ textDecoration: 'none' }}
              >
                Accepted
              </a>
              <a
                href={`${API_URL}/api/replay/raw-pattern-study/${runId}/discover/export-full?section=rankings`}
                download={`raw-pattern-run-${runId}-discovery-rankings.json`}
                className={styles.discoveryExportBtnSm}
                style={{ textDecoration: 'none' }}
              >
                Rankings
              </a>
              <a
                href={`${API_URL}/api/replay/raw-pattern-study/${runId}/discover/export-full?section=episodes`}
                download={`raw-pattern-run-${runId}-discovery-episodes.json`}
                className={styles.discoveryExportBtnSm}
                style={{ textDecoration: 'none' }}
              >
                Episodes
              </a>
              <a
                href={`${API_URL}/api/replay/raw-pattern-study/${runId}/discover/export-full?section=full`}
                download={`raw-pattern-run-${runId}-discovery-full.json`}
                className={styles.discoveryExportBtnSm}
                style={{ textDecoration: 'none', opacity: 0.7 }}
                title="Large file — may be slow"
              >
                Full (large)
              </a>
            </span>
          )}
        </div>

        {launchErr && <div className={styles.errorMsg} style={{ marginTop: 8 }}>{launchErr}</div>}
      </div>

      {/* ── Status banner ─────────────────────────────────────────────────── */}
      {status && (
        <div className={`${styles.discoveryStatus} ${
          hasError    ? styles.discoveryStatusError    :
          isRunning   ? styles.discoveryStatusRunning  :
          isComplete  ? styles.discoveryStatusComplete : ''
        }`}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            {isRunning && <span className={styles.pulsingDot} />}
            <span style={{ fontWeight: 600 }}>
              {isRunning ? (PHASE_LABEL[phase] || phase) : isComplete ? 'Discovery complete' : hasError ? 'Discovery failed' : phase || 'idle'}
            </span>
            {status.episodes > 0 && (
              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                {status.episodes} episodes · {status.episodes_scored} scored ·{' '}
                {status.patterns_evaluated} ep-patterns · {status.bar_patterns_evaluated} bar ·{' '}
                {status.flow_patterns_evaluated > 0 ? `${status.flow_patterns_evaluated} flow · ` : ''}
                {status.combined_patterns_evaluated > 0 ? `${status.combined_patterns_evaluated} combined · ` : ''}
                {status.patterns_saved} saved
              </span>
            )}
          </div>
          {/* Group classification debug */}
          {status.group_counts && Object.keys(status.group_counts).length > 0 && (
            <div style={{ marginTop: 6, display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 10, color: 'var(--text-muted)' }}>
              {Object.entries(status.group_counts).map(([g, n]) => (
                <span key={g} style={{ fontFamily: 'var(--font-mono)' }}>
                  <span style={{ color: n === 0 ? 'var(--red)' : 'inherit' }}>{g}</span>={n}
                </span>
              ))}
              {(status.pre_daily_rows_loaded > 0 || status.bar_snapshots_created > 0) && (
                <>
                  <span style={{ color: 'var(--border)' }}>|</span>
                  <span>daily_rows={status.pre_daily_rows_loaded}</span>
                  <span>snapshots={status.bar_snapshots_created}</span>
                  <span>price_seqs={status.bar_sequences_created}</span>
                  {status.flow_sequences_created > 0 && (
                    <span style={{ color: 'var(--blue)' }}>flow_seqs={status.flow_sequences_created}</span>
                  )}
                  {status.combined_sequences_created > 0 && (
                    <span style={{ color: 'var(--blue)' }}>comb_seqs={status.combined_sequences_created}</span>
                  )}
                </>
              )}
            </div>
          )}
          {hasError && status.error && (
            <div className={styles.errorMsg} style={{ marginTop: 6 }}>{status.error}</div>
          )}
        </div>
      )}

      {/* ── Results ───────────────────────────────────────────────────────── */}
      {loadingRes && <div className={styles.statusMsg}>Loading results…</div>}
      {resErr     && <div className={styles.errorMsg}>{resErr}</div>}

      {results && !loadingRes && (
        <>
          {/* Summary cards */}
          <div className={styles.discoverySummary}>
            {[
              { label: 'Total Patterns',    value: patterns.length },
              { label: 'Episode Agg',       value: (byFamily['EPISODE_AGGREGATE'] || []).length },
              { label: 'Price Action',      value: (byFamily['PRICE_ACTION'] || []).length },
              { label: 'Flow (V1C)',        value: flowPatterns.length,     highlight: flowPatterns.length > 0 },
              { label: 'Combined (V1C)',    value: combinedPatterns.length,  highlight: combinedPatterns.length > 0 },
              { label: 'Single Bar',        value: (bySourceType['SINGLE_BAR'] || []).length },
              { label: 'Two-Bar Seq',       value: (bySourceType['TWO_BAR_SEQUENCE'] || []).length },
              { label: 'Three-Bar Seq',     value: (bySourceType['THREE_BAR_SEQUENCE'] || []).length },
              { label: 'Five-Bar',          value: (bySourceType['FIVE_BAR_SEQUENCE'] || []).length },
            ].map(({ label, value, highlight }) => (
              <div key={label} className={styles.discoverySummaryCard}
                style={highlight ? { borderColor: 'var(--blue)' } : {}}>
                <div className={styles.discoverySummaryVal}
                  style={highlight ? { color: 'var(--blue)' } : {}}>
                  {fmtNum(value)}
                </div>
                <div className={styles.discoverySummaryLabel}>{label}</div>
              </div>
            ))}
          </div>

          {/* Contamination warnings */}
          {contaminated.length > 0 && (
            <div className={styles.discoveryWarning}>
              <strong>Split artifact contamination:</strong>{' '}
              {contaminated.length} pattern{contaminated.length > 1 ? 's' : ''} have &gt;50% split artifact
              exposure — {contaminated.slice(0, 3).map(p => p.signal_id).join(', ')}.
              Do not add these to Pump Watch without cleaning split episodes.
            </div>
          )}

          {/* Sub-tabs */}
          <div className={styles.tabRow} style={{ marginTop: 12 }}>
            {[
              { id: 'top-lift',     label: 'Top by Lift' },
              { id: 'top-missed',   label: 'Top Missed 4x' },
              { id: 'top-flow',     label: `Top Flow (${flowPatterns.length})`,     hidden: flowPatterns.length === 0 },
              { id: 'top-combined', label: `Top Combined (${combinedPatterns.length})`, hidden: combinedPatterns.length === 0 },
              { id: 'by-family',    label: 'By Family' },
              { id: 'by-type',      label: 'By Source Type' },
              { id: 'all',          label: `All (${patterns.length})` },
              { id: 'flow-impact',   label: 'FLOW Impact' },
              { id: 'curated-flow',  label: 'Curated FLOW' },
              { id: 'custom-signals', label: 'Custom Signals' },
            ].filter(t => !t.hidden).map(({ id, label }) => (
              <button
                key={id}
                className={`${styles.tab}${resTab === id ? ' ' + styles.tabActive : ''}`}
                onClick={() => {
                  setResTab(id);
                  if (id === 'flow-impact')  fetchFlowImpact();
                  if (id === 'curated-flow') fetchCuratedFlow();
                  // custom-signals reads directly from results — no extra fetch
                }}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Top by lift */}
          {resTab === 'top-lift' && (
            <PatternTable title="Top 10 Patterns by Lift vs False-Positive" rows={topByLift} />
          )}

          {/* Top by missed 4x */}
          {resTab === 'top-missed' && (
            <PatternTable title="Top 10 Patterns Capturing Missed 4× Pumps" rows={topByMissed} />
          )}

          {/* Top flow patterns */}
          {resTab === 'top-flow' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <div className={styles.discoveryNote} style={{ padding: '6px 10px', fontSize: 11 }}>
                Flow features are OHLCV-derived proxies (CLV, OBV, ADL, CMF, signed_volume_proxy).
                NOT true bid/ask delta.
              </div>
              <PatternTable
                title={`Top Flow Patterns by Lift (${Math.min(topFlowByLift.length, 10)} shown)`}
                rows={topFlowByLift}
              />
            </div>
          )}

          {/* Top combined patterns */}
          {resTab === 'top-combined' && (
            <PatternTable
              title={`Top Combined (Price+Flow) Patterns by Lift (${Math.min(topCombinedByLift.length, 10)} shown)`}
              rows={topCombinedByLift}
            />
          )}

          {/* By feature family */}
          {resTab === 'by-family' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {Object.entries(byFamily).map(([ff, pats]) => (
                <PatternTable
                  key={ff}
                  title={`${ff} (${pats.length})`}
                  rows={[...pats].sort((a,b)=>((b.lift_vs_false_positive||0)-(a.lift_vs_false_positive||0))).slice(0, 15)}
                />
              ))}
            </div>
          )}

          {/* By source type */}
          {resTab === 'by-type' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {Object.entries(bySourceType).map(([st, pats]) => (
                <PatternTable
                  key={st}
                  title={`${SOURCE_TYPE_LABELS[st] || st} (${pats.length})`}
                  rows={[...pats].sort((a,b)=>((b.lift_vs_false_positive||0)-(a.lift_vs_false_positive||0))).slice(0, 15)}
                />
              ))}
            </div>
          )}

          {/* All patterns including REJECT */}
          {resTab === 'all' && (
            <AllPatternsTable patterns={patterns} />
          )}

          {/* FLOW Impact (research-only) */}
          {resTab === 'flow-impact' && (
            <FlowImpactTab
              data={flowImpact}
              loading={loadingFlowImpact}
              error={flowImpactErr}
            />
          )}

          {/* Curated FLOW Replay (research-only) */}
          {resTab === 'curated-flow' && (
            <CuratedFlowTab
              data={curatedFlow}
              loading={loadingCuratedFlow}
              error={curatedFlowErr}
            />
          )}

          {/* Custom D/L/WLNBB Signals (research-only) */}
          {resTab === 'custom-signals' && (
            <CustomSignalsTab results={results} />
          )}
        </>
      )}
    </div>
  );
}

// ── FLOW Impact Tab ───────────────────────────────────────────────────────────

function FlowImpactTab({ data, loading, error }) {
  if (loading) return <div className={styles.statusMsg}>Loading FLOW impact analysis…</div>;
  if (error)   return <div className={styles.errorMsg}>{error}</div>;
  if (!data || Object.keys(data).length === 0)
    return <div className={styles.statusMsg}>No FLOW impact data. Run discovery with flow/combined mode first.</div>;

  const fmtPct = v => (v == null ? '—' : `${(v * 100).toFixed(1)}%`);
  const fmtN   = v => (v == null ? '—' : String(v));
  const fmtScore = v => (v == null ? '—' : v.toFixed(2));

  const bySubtype    = data.by_flow_subtype    || {};
  const byDiag       = data.by_diagnostic_label || {};
  const combos       = data.combo_analysis      || [];
  const missed4x     = data.missed_4x_rescue_candidates || [];
  const fpTraps      = data.false_positive_traps || [];
  const scoreDist    = data.flow_replay_score_distribution || {};
  const pwMatrix     = data.pump_watch_vs_flow_matrix || {};
  const recs         = data.recommendations || [];

  const SUBTYPE_LABELS = {
    FLOW_DIVERGENCE:     'FLOW Divergence',
    FLOW_ABSORPTION:     'FLOW Absorption',
    FLOW_BEARISH_STRESS: 'Bearish Stress',
    FLOW_BULLISH_ACCUM:  'Bullish Accum',
    FLOW_MIXED_CONTEXT:  'Mixed Context',
    FLOW_GAP_FADE:       'Gap Fade',
    FLOW_GAP_RECLAIM:    'Gap Reclaim',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Research-only banner */}
      <div className={styles.discoveryWarning} style={{ borderColor: 'var(--blue)', background: 'rgba(59,130,246,0.08)' }}>
        <strong>RESEARCH ONLY</strong> — scores and routing here do NOT affect Scanner V2.
        No BUY promotions. No score boosts. Analysis only.
      </div>

      {/* A: By FLOW Subtype */}
      {Object.keys(bySubtype).length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>A: By FLOW Subtype</span>
            <span className={styles.tableHint}>Episode-level outcomes grouped by inferred FLOW context</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.historyTable} style={{ width: '100%' }}>
              <thead>
                <tr className={styles.historyHead}>
                  <th>Subtype</th>
                  <th>Episodes</th>
                  <th>4x Count</th>
                  <th>FP Count</th>
                  <th>4x Rate</th>
                  <th>FP Rate</th>
                  <th>Median Score</th>
                  <th>Symbols (sample)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(bySubtype).map(([st, row]) => (
                  <tr key={st} className={styles.historyRow}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                      {SUBTYPE_LABELS[st] || st}
                    </td>
                    <td>{fmtN(row.total)}</td>
                    <td>{fmtN(row['4x_pump_count'])}</td>
                    <td>{fmtN(row.false_positive_count)}</td>
                    <td style={{ color: (row['4x_rate'] || 0) >= 0.45 ? 'var(--green)' : undefined }}>
                      {fmtPct(row['4x_rate'])}
                    </td>
                    <td style={{ color: (row.false_positive_rate || 0) >= 0.35 ? 'var(--red)' : undefined }}>
                      {fmtPct(row.false_positive_rate)}
                    </td>
                    <td>{fmtScore(row.median_pump_watch_score)}</td>
                    <td style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                      {(row.sample_symbols || []).slice(0, 5).join(', ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* B: By Diagnostic Label */}
      {Object.keys(byDiag).length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>B: By Diagnostic Label</span>
            <span className={styles.tableHint}>Pump Watch diagnostic badge outcomes</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.historyTable} style={{ width: '100%' }}>
              <thead>
                <tr className={styles.historyHead}>
                  <th>Diagnostic Label</th>
                  <th>Episodes</th>
                  <th>4x Count</th>
                  <th>FP Count</th>
                  <th>4x Rate</th>
                  <th>FP Rate</th>
                  <th>Median Score</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(byDiag).map(([lbl, row]) => (
                  <tr key={lbl} className={styles.historyRow}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{lbl}</td>
                    <td>{fmtN(row.total)}</td>
                    <td>{fmtN(row['4x_pump_count'])}</td>
                    <td>{fmtN(row.false_positive_count)}</td>
                    <td style={{ color: (row['4x_rate'] || 0) >= 0.45 ? 'var(--green)' : undefined }}>
                      {fmtPct(row['4x_rate'])}
                    </td>
                    <td style={{ color: (row.false_positive_rate || 0) >= 0.35 ? 'var(--red)' : undefined }}>
                      {fmtPct(row.false_positive_rate)}
                    </td>
                    <td>{fmtScore(row.median_pump_watch_score)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* C: Combo Analysis */}
      {combos.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>C: Combination Analysis ({combos.length})</span>
            <span className={styles.tableHint}>FLOW + Diagnostic badge combinations; precision measurement</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.historyTable} style={{ width: '100%' }}>
              <thead>
                <tr className={styles.historyHead}>
                  <th>Combo</th>
                  <th>N</th>
                  <th>4x Rate</th>
                  <th>FP Rate</th>
                  <th>Median Score</th>
                </tr>
              </thead>
              <tbody>
                {combos.map((c, i) => (
                  <tr key={i} className={styles.historyRow}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{c.combo_label || c.label}</td>
                    <td>{fmtN(c.total)}</td>
                    <td style={{ color: (c['4x_rate'] || 0) >= 0.45 ? 'var(--green)' : undefined }}>
                      {fmtPct(c['4x_rate'])}
                    </td>
                    <td style={{ color: (c.false_positive_rate || 0) >= 0.35 ? 'var(--red)' : undefined }}>
                      {fmtPct(c.false_positive_rate)}
                    </td>
                    <td>{fmtScore(c.median_pump_watch_score)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Missed 4x Rescue Candidates */}
      {missed4x.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Missed 4x Rescue Candidates</span>
            <span className={styles.tableHint}>
              4x pumps missed by scanner with STRONG rescue + PUMP_SPECULATIVE routing
            </span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.historyTable} style={{ width: '100%' }}>
              <thead>
                <tr className={styles.historyHead}>
                  <th>Symbol</th>
                  <th>Flow Context</th>
                  <th>PW Label</th>
                  <th>PW Score</th>
                  <th>Flow Score</th>
                  <th>Diagnostics</th>
                </tr>
              </thead>
              <tbody>
                {missed4x.slice(0, 30).map((ep, i) => (
                  <tr key={i} className={styles.historyRow}>
                    <td style={{ fontWeight: 600 }}>{ep.symbol || ep.ticker}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
                      {ep.flow_replay_context || ep.flow_context}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
                      {ep.pump_watch_label}
                    </td>
                    <td>{ep.pump_watch_score}</td>
                    <td style={{ color: (ep.flow_replay_score || 0) >= 8 ? 'var(--green)' : undefined }}>
                      {ep.flow_replay_score != null ? `${ep.flow_replay_score} (${ep.flow_replay_bucket || '—'})` : '—'}
                    </td>
                    <td style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                      {(Array.isArray(ep.pump_watch_diagnostic_labels)
                        ? ep.pump_watch_diagnostic_labels
                        : []
                      ).join(', ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* False Positive Traps */}
      {fpTraps.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>False Positive Traps</span>
            <span className={styles.tableHint}>
              High-score FPs with REVERSE_SPLIT + STRONG_RESCUE — caution candidates
            </span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.historyTable} style={{ width: '100%' }}>
              <thead>
                <tr className={styles.historyHead}>
                  <th>Symbol</th>
                  <th>Flow Context</th>
                  <th>PW Label</th>
                  <th>PW Score</th>
                  <th>Flow Score</th>
                  <th>Diagnostics</th>
                </tr>
              </thead>
              <tbody>
                {fpTraps.slice(0, 30).map((ep, i) => (
                  <tr key={i} className={styles.historyRow}>
                    <td style={{ fontWeight: 600, color: 'var(--red)' }}>{ep.symbol || ep.ticker}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
                      {ep.flow_replay_context || ep.flow_context}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
                      {ep.pump_watch_label}
                    </td>
                    <td>{ep.pump_watch_score}</td>
                    <td>{ep.flow_replay_score != null ? `${ep.flow_replay_score} (${ep.flow_replay_bucket || '—'})` : '—'}</td>
                    <td style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                      {(Array.isArray(ep.pump_watch_diagnostic_labels)
                        ? ep.pump_watch_diagnostic_labels
                        : []
                      ).join(', ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Flow Replay Score Distribution */}
      {Object.keys(scoreDist).length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Flow Replay Score Distribution</span>
            <span className={styles.tableHint}>HIGH ≥8 · MEDIUM 5–7 · LOW 3–4 · IGNORE &lt;3 (research only)</span>
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', padding: '12px 16px' }}>
            {['HIGH', 'MEDIUM', 'LOW', 'IGNORE'].map(bucket => {
              const bd = scoreDist[bucket] || {};
              const color = bucket === 'HIGH' ? 'var(--green)' : bucket === 'MEDIUM' ? 'var(--blue)' : bucket === 'LOW' ? 'var(--text-muted)' : 'var(--red)';
              return (
                <div key={bucket} className={styles.discoverySummaryCard} style={{ minWidth: 100 }}>
                  <div className={styles.discoverySummaryVal} style={{ color }}>{fmtN(bd.total)}</div>
                  <div className={styles.discoverySummaryLabel}>{bucket}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                    4x: {fmtPct(bd['4x_rate'])} · FP: {fmtPct(bd.false_positive_rate)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Pump Watch vs FLOW Matrix */}
      {Object.keys(pwMatrix).length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Pump Watch × FLOW Score Matrix</span>
            <span className={styles.tableHint}>Rows = PW label, Columns = FLOW score bucket</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.historyTable} style={{ width: '100%' }}>
              <thead>
                <tr className={styles.historyHead}>
                  <th>PW Label</th>
                  {['HIGH', 'MEDIUM', 'LOW', 'IGNORE'].map(b => (
                    <th key={b}>{b} (n / 4x%)</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(pwMatrix).map(([label, buckets]) => (
                  <tr key={label} className={styles.historyRow}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{label}</td>
                    {['HIGH', 'MEDIUM', 'LOW', 'IGNORE'].map(b => {
                      const cell = (buckets || {})[b] || {};
                      const rate = cell['4x_rate'];
                      return (
                        <td key={b} style={{ fontSize: 10 }}>
                          {cell.total > 0
                            ? <span style={{ color: rate >= 0.45 ? 'var(--green)' : rate >= 0.25 ? undefined : 'var(--text-muted)' }}>
                                {cell.total} / {fmtPct(rate)}
                              </span>
                            : <span style={{ color: 'var(--text-muted)' }}>—</span>
                          }
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Recommendations */}
      {recs.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Recommendations</span>
          </div>
          <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 6 }}>
            {recs.map((rec, i) => (
              <div key={i} style={{ fontSize: 12, display: 'flex', gap: 8 }}>
                <span style={{ color: 'var(--blue)', flexShrink: 0 }}>▸</span>
                <span>{typeof rec === 'string' ? rec : rec.text || JSON.stringify(rec)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Curated FLOW Replay Tab ────────────────────────────────────────────────────

function CuratedFlowTab({ data, loading, error }) {
  if (loading) return <div className={styles.statusMsg}>Loading Curated FLOW analysis…</div>;
  if (error)   return <div className={styles.errorMsg}>{error}</div>;
  if (!data || Object.keys(data).length === 0)
    return <div className={styles.statusMsg}>No Curated FLOW data. Run discovery with flow mode first.</div>;

  const fmtPct  = v => (v == null ? '—' : `${(v * 100).toFixed(1)}%`);
  const fmtN    = v => (v == null ? '—' : String(v));
  const fmtInt  = v => (v == null ? '—' : String(Math.round(v)));

  const bucketPerf = data.bucket_performance      || {};
  const matrix     = data.pump_watch_x_curated_flow_matrix || {};
  const badgePerf  = data.badge_performance        || [];
  const missed4x   = data.missed_4x_rescue         || [];
  const fpTraps    = data.false_positive_traps      || [];
  const baseline   = data.baseline_vs_curated_flow  || {};
  const summary    = data.summary                   || {};
  const warnings   = data.warnings                  || [];
  const recs       = data.recommendations           || [];

  const BUCKET_ORDER  = ['CURATED_FLOW_HIGH', 'CURATED_FLOW_MEDIUM', 'CURATED_FLOW_LOW', 'CURATED_FLOW_IGNORE'];
  const BUCKET_LABELS = {
    CURATED_FLOW_HIGH:   'CF HIGH (≥8)',
    CURATED_FLOW_MEDIUM: 'CF MEDIUM (5-7)',
    CURATED_FLOW_LOW:    'CF LOW (3-4)',
    CURATED_FLOW_IGNORE: 'CF IGNORE (<3)',
  };
  const PW_ORDER = ['PUMP_WATCH_HIGH', 'PUMP_WATCH_MEDIUM', 'PUMP_SPECULATIVE', 'PUMP_IGNORE'];

  const BADGE_LABELS = {
    PX_FLOW_DIVERGENCE_ACCUM_PRESSURE: 'Divergence Accum (+4)',
    PX_FLOW_BULLISH_ACCUM_IGNITION:    'Bullish Accum (+3)',
    PX_FLOW_DIVERGENCE_SUPPLY_ABSORB:  'Supply Absorb (+3)',
    PX_IGNITION_CONFIRM_PRICE_ACTION:  'Ignition Confirm (+2)',
    PX_GAP_RESET_RECLAIM_CONTEXT:      'Gap Reset (+2)',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

      {/* Safety note */}
      <div className={styles.discoveryNote} style={{ padding: '8px 12px', fontSize: 11 }}>
        <strong>RESEARCH ONLY</strong> — Curated FLOW layer from run 139 top patterns (5 frozen rules).
        No BUY promotion. No Scanner V2 change. All output is experimental.
        {data.anti_leakage_note && <span> · {data.anti_leakage_note}</span>}
      </div>

      {/* Warnings */}
      {warnings.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle} style={{ color: 'var(--yellow)' }}>⚠ Warnings</span>
          </div>
          <div style={{ padding: '10px 16px', display: 'flex', flexDirection: 'column', gap: 4 }}>
            {warnings.map((w, i) => (
              <div key={i} style={{ fontSize: 12, color: 'var(--yellow)', display: 'flex', gap: 8 }}>
                <span>⚠</span><span>{w}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Summary cards */}
      {Object.keys(summary).length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(140px,1fr))', gap: 10 }}>
          {[
            { label: 'Total Episodes',    val: fmtN(summary.total_episodes) },
            { label: 'CF HIGH',           val: fmtN(summary.cf_high_count) },
            { label: 'CF HIGH 4× Rate',   val: fmtPct(summary.cf_high_4x_rate) },
            { label: 'CF HIGH FP Rate',   val: fmtPct(summary.cf_high_fp_rate) },
            { label: 'Rescued 4×',        val: fmtN(summary.missed_4x_rescued) },
            { label: 'FP Traps',          val: fmtN(summary.fp_traps) },
          ].map(({ label, val }) => (
            <div key={label} className={styles.tableCard} style={{ padding: '10px 14px', textAlign: 'center' }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--blue)' }}>{val}</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Bucket Performance */}
      {Object.keys(bucketPerf).length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Bucket Performance</span>
            <span className={styles.tableHint}>Score thresholds: HIGH≥8, MED 5-7, LOW 3-4, IGNORE&lt;3</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.historyTable} style={{ width: '100%' }}>
              <thead>
                <tr className={styles.historyHead}>
                  <th>Bucket</th><th>Count</th><th>4× Rate</th><th>FP Rate</th>
                  <th>4× Count</th><th>FP Count</th>
                  <th>Split Art.</th><th>Rev Split</th><th>Low DV</th>
                </tr>
              </thead>
              <tbody>
                {BUCKET_ORDER.map(bk => {
                  const r = bucketPerf[bk];
                  if (!r) return null;
                  return (
                    <tr key={bk} className={styles.historyRow}>
                      <td style={{ fontWeight: 600 }}>{BUCKET_LABELS[bk] || bk}</td>
                      <td>{fmtN(r.total)}</td>
                      <td style={{ color: (r.four_x_rate||0) > 0.35 ? 'var(--green)' : undefined }}>
                        {fmtPct(r.four_x_rate)}
                      </td>
                      <td style={{ color: (r.fp_rate||0) > 0.30 ? 'var(--red)' : undefined }}>
                        {fmtPct(r.fp_rate)}
                      </td>
                      <td>{fmtN(r.four_x_count)}</td>
                      <td>{fmtN(r.fp_count)}</td>
                      <td>{fmtN(r.split_artifact_count)}</td>
                      <td>{fmtN(r.reverse_split_count)}</td>
                      <td>{fmtN(r.low_dollar_volume_count)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* PW × CF Matrix */}
      {Object.keys(matrix).length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Pump Watch × Curated FLOW Matrix</span>
            <span className={styles.tableHint}>4× rate per cell</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.historyTable} style={{ width: '100%' }}>
              <thead>
                <tr className={styles.historyHead}>
                  <th>PW Label</th>
                  {BUCKET_ORDER.map(bk => <th key={bk}>{BUCKET_LABELS[bk] || bk}</th>)}
                </tr>
              </thead>
              <tbody>
                {PW_ORDER.map(pw => (
                  <tr key={pw} className={styles.historyRow}>
                    <td style={{ fontWeight: 600, whiteSpace: 'nowrap' }}>{pw.replace('_', ' ')}</td>
                    {BUCKET_ORDER.map(bk => {
                      const cell = (matrix[pw] || {})[bk];
                      if (!cell) return <td key={bk}>—</td>;
                      return (
                        <td key={bk} style={{
                          background: (cell.four_x_rate||0) > 0.40 ? 'rgba(0,200,100,0.08)' :
                                      (cell.four_x_rate||0) < 0.10 ? 'rgba(200,50,50,0.06)' : undefined,
                        }}>
                          {fmtPct(cell.four_x_rate)} <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>n={cell.total}</span>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Badge Performance */}
      {badgePerf.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Badge Performance</span>
            <span className={styles.tableHint}>Per frozen rule stats</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.historyTable} style={{ width: '100%' }}>
              <thead>
                <tr className={styles.historyHead}>
                  <th>Badge</th><th>Count</th><th>4× Rate</th><th>FP Rate</th>
                  <th>Split Art.</th><th>Rev Split</th><th>Low DV</th>
                </tr>
              </thead>
              <tbody>
                {badgePerf.map((b, i) => (
                  <tr key={i} className={styles.historyRow}>
                    <td style={{ fontSize: 11 }}>{BADGE_LABELS[b.badge] || b.badge}</td>
                    <td>{fmtN(b.total)}</td>
                    <td style={{ color: (b.four_x_rate||0) > 0.35 ? 'var(--green)' : undefined }}>
                      {fmtPct(b.four_x_rate)}
                    </td>
                    <td style={{ color: (b.fp_rate||0) > 0.30 ? 'var(--red)' : undefined }}>
                      {fmtPct(b.fp_rate)}
                    </td>
                    <td>{fmtN(b.split_artifact_count)}</td>
                    <td>{fmtN(b.reverse_split_count)}</td>
                    <td>{fmtN(b.low_dollar_volume_count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Missed 4× Rescue */}
      {missed4x.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Missed 4× Rescue Candidates</span>
            <span className={styles.tableHint}>4× episodes missed by PW but caught by CF HIGH/MEDIUM</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.historyTable} style={{ width: '100%' }}>
              <thead>
                <tr className={styles.historyHead}>
                  <th>Symbol</th><th>PW Label</th><th>CF Bucket</th><th>CF Score</th>
                  <th>Badges</th><th>Split</th>
                </tr>
              </thead>
              <tbody>
                {missed4x.slice(0, 30).map((ep, i) => (
                  <tr key={i} className={styles.historyRow}>
                    <td style={{ fontWeight: 600 }}>{ep.ticker || ep.symbol || '—'}</td>
                    <td style={{ fontSize: 11 }}>{ep.pump_watch_label || '—'}</td>
                    <td style={{ color: 'var(--green)' }}>{ep.curated_flow_bucket || '—'}</td>
                    <td>{fmtInt(ep.curated_flow_score)}</td>
                    <td style={{ fontSize: 10 }}>{(ep.curated_flow_badges || []).map(b => BADGE_LABELS[b] || b).join(', ') || '—'}</td>
                    <td style={{ fontSize: 10 }}>{ep.split_context || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* FP Traps */}
      {fpTraps.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>False Positive Traps</span>
            <span className={styles.tableHint}>FP episodes with CF HIGH/MEDIUM — study trap patterns</span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.historyTable} style={{ width: '100%' }}>
              <thead>
                <tr className={styles.historyHead}>
                  <th>Symbol</th><th>CF Bucket</th><th>CF Score</th>
                  <th>Badges</th><th>Trap Notes</th>
                </tr>
              </thead>
              <tbody>
                {fpTraps.slice(0, 30).map((ep, i) => (
                  <tr key={i} className={styles.historyRow}>
                    <td style={{ fontWeight: 600 }}>{ep.ticker || ep.symbol || '—'}</td>
                    <td style={{ color: 'var(--red)' }}>{ep.curated_flow_bucket || '—'}</td>
                    <td>{fmtInt(ep.curated_flow_score)}</td>
                    <td style={{ fontSize: 10 }}>{(ep.curated_flow_badges || []).map(b => BADGE_LABELS[b] || b).join(', ') || '—'}</td>
                    <td style={{ fontSize: 10, color: 'var(--yellow)' }}>{(ep.trap_notes || []).join('; ') || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Recommendations */}
      {recs.length > 0 && (
        <div className={styles.tableCard}>
          <div className={styles.tableHeader}>
            <span className={styles.tableTitle}>Recommendations</span>
          </div>
          <div style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 6 }}>
            {recs.map((rec, i) => (
              <div key={i} style={{ fontSize: 12, display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                <span style={{ color: 'var(--blue)', flexShrink: 0 }}>▸</span>
                <span>{typeof rec === 'string' ? rec : rec.text || JSON.stringify(rec)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Custom D/L/WLNBB Signals Tab ─────────────────────────────────────────────

function CustomSignalsTab({ results }) {
  if (!results || Object.keys(results).length === 0)
    return <div className={styles.statusMsg}>No results loaded.</div>;

  const ffCounts  = results.feature_family_counts || {};
  const csCount   = ffCounts.CUSTOM_SIGNAL || 0;
  const fccCount  = ffCounts.FLOW_CUSTOM_COMBINED || 0;
  const hasData   = csCount > 0 || fccCount > 0;

  const l43Pats  = results.top_custom_l43_patterns           || [];
  const lSerPats = results.top_custom_l_series_patterns      || [];
  const dConfPats= results.top_custom_d_confluence_patterns  || [];
  const fccPats  = results.top_flow_custom_combined          || [];
  const topClean = results.top_custom_signal_clean_reliability || [];

  if (!hasData) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div className={styles.discoveryNote} style={{ padding: '10px 14px', fontSize: 12 }}>
          <strong>Custom Signals not yet mined.</strong> Run pattern discovery with
          <code style={{ margin: '0 4px' }}>mode=custom</code> or
          <code style={{ margin: '0 4px' }}>mode=all</code> to populate L43, L34, D4_BEUP and
          other WLNBB signal patterns.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(140px,1fr))', gap: 10 }}>
          {[
            { label: 'CUSTOM_SIGNAL',       val: csCount },
            { label: 'FLOW_CUSTOM_COMBINED', val: fccCount },
          ].map(({ label, val }) => (
            <div key={label} className={styles.tableCard} style={{ padding: '10px 14px', textAlign: 'center' }}>
              <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text-muted)' }}>{val}</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>{label}</div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

      {/* Safety note */}
      <div className={styles.discoveryNote} style={{ padding: '8px 12px', fontSize: 11 }}>
        <strong>RESEARCH ONLY</strong> — Custom D/L/WLNBB signal layer.
        No BUY promotion. No Scanner V2 change. All output is experimental.
        Tags populated from pre-computed feature_json flags (has_l43, has_d4_beup, etc.).
      </div>

      {/* Summary cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill,minmax(140px,1fr))', gap: 10 }}>
        {[
          { label: 'CUSTOM_SIGNAL patterns',        val: csCount },
          { label: 'FLOW+Custom combined',          val: fccCount },
          { label: 'L43 patterns',                  val: l43Pats.length },
          { label: 'L34/L64/L22 patterns',          val: lSerPats.length },
          { label: 'D-confluence patterns',         val: dConfPats.length },
          { label: 'Top clean (cnt≥4, exp≤50%)',    val: topClean.length },
        ].map(({ label, val }) => (
          <div key={label} className={styles.tableCard} style={{ padding: '10px 14px', textAlign: 'center' }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--blue)' }}>{val}</div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>{label}</div>
          </div>
        ))}
      </div>

      {/* L43 patterns */}
      <PatternTable
        title={`L43 Patterns — all families (${l43Pats.length})`}
        rows={l43Pats.slice(0, 15)}
      />

      {/* L34 / L64 / L22 patterns */}
      <PatternTable
        title={`L34 / L64 / L22 Patterns (${lSerPats.length})`}
        rows={lSerPats.slice(0, 15)}
      />

      {/* D-confluence patterns */}
      <PatternTable
        title={`D-Confluence Patterns — D3/D4/D6 BEUP + D+L combos (${dConfPats.length})`}
        rows={dConfPats.slice(0, 15)}
      />

      {/* FLOW + Custom combined */}
      <PatternTable
        title={`FLOW + Custom Combined Patterns (${fccPats.length})`}
        rows={fccPats.slice(0, 15)}
      />

      {/* Top clean reliability */}
      {topClean.length > 0 && (
        <PatternTable
          title={`Top Custom Signal — Clean Reliability (cnt≥4, exposure≤50%)`}
          rows={topClean.slice(0, 15)}
        />
      )}
    </div>
  );
}

function PatternTable({ title, rows }) {
  if (!rows || rows.length === 0) {
    return (
      <div className={styles.tableCard}>
        <div className={styles.tableHeader}><span className={styles.tableTitle}>{title}</span></div>
        <div className={styles.statusMsg}>No patterns to display.</div>
      </div>
    );
  }
  return (
    <div className={styles.tableCard}>
      <div className={styles.tableHeader}>
        <span className={styles.tableTitle}>{title}</span>
        <span className={styles.tableHint}>{rows.length} pattern{rows.length !== 1 ? 's' : ''}</span>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table className={styles.historyTable} style={{ width: '100%' }}>
          <thead>
            <tr className={styles.historyHead}>
              <th>Signal ID</th>
              <th>Source</th>
              <th>Status</th>
              <th>Lift vs FP</th>
              <th>4x Ep</th>
              <th>Missed</th>
              <th>FP Rate</th>
              <th>Description / Signature</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((p, i) => <PatternRow key={p.signal_id || i} p={p} />)}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function _rejectReason(p) {
  if (p.status !== 'REJECT') return null;
  if ((p.count_all_4x || 0) < 2) return 'low_count';
  if ((p.lift_vs_false_positive || 0) < 1.0) return 'low_lift';
  return 'unknown';
}

function AllPatternsTable({ patterns }) {
  const sorted = [...patterns].sort((a, b) => {
    const sOrder = { EXPERIMENTAL: 0, EXPERIMENTAL_RARE: 1, RESEARCH_ONLY: 2, REJECT: 3 };
    const sd = (sOrder[a.status] ?? 9) - (sOrder[b.status] ?? 9);
    if (sd !== 0) return sd;
    return (b.lift_vs_false_positive || 0) - (a.lift_vs_false_positive || 0);
  });

  const accepted = sorted.filter(p => p.status !== 'REJECT');
  const rejected = sorted.filter(p => p.status === 'REJECT');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className={styles.tableCard}>
        <div className={styles.tableHeader}>
          <span className={styles.tableTitle}>Accepted Patterns ({accepted.length})</span>
          <span className={styles.tableHint}>EXPERIMENTAL / EXPERIMENTAL_RARE / RESEARCH_ONLY</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className={styles.historyTable} style={{ width: '100%' }}>
            <thead>
              <tr className={styles.historyHead}>
                <th>Signal ID</th><th>Source</th><th>Status</th>
                <th>Lift vs FP</th><th>4x Ep</th><th>Missed</th>
                <th>FP Rate</th><th>Recommendation</th>
              </tr>
            </thead>
            <tbody>
              {accepted.length === 0
                ? <tr><td colSpan={8} className={styles.dataCell} style={{ color: 'var(--red)', textAlign: 'center' }}>No accepted patterns — all patterns were rejected.</td></tr>
                : accepted.map((p, i) => <PatternRow key={p.signal_id || i} p={p} />)
              }
            </tbody>
          </table>
        </div>
      </div>

      <div className={styles.tableCard}>
        <div className={styles.tableHeader}>
          <span className={styles.tableTitle} style={{ color: 'var(--red)' }}>
            Rejected Patterns ({rejected.length})
          </span>
          <span className={styles.tableHint}>REJECT — shown for debug visibility</span>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className={styles.historyTable} style={{ width: '100%' }}>
            <thead>
              <tr className={styles.historyHead}>
                <th>Signal ID</th><th>Source</th><th>Reject Reason</th>
                <th>Lift vs FP</th><th>4x Ep</th><th>FP Ep</th>
                <th>NW Ep</th><th>Description / Signature</th>
              </tr>
            </thead>
            <tbody>
              {rejected.length === 0
                ? <tr><td colSpan={8} className={styles.dataCell} style={{ color: 'var(--text-muted)', textAlign: 'center' }}>No rejected patterns.</td></tr>
                : rejected.map((p, i) => {
                    const st = normalizeSourceType(p.source_type, p.signal_id);
                    const reason = _rejectReason(p);
                    return (
                      <tr key={p.signal_id || i}>
                        <td className={styles.dataCell} style={{ fontFamily: 'var(--font-mono)', fontSize: 9 }}>{p.signal_id}</td>
                        <td className={styles.dataCell} style={{ fontSize: 9 }}>
                          <span style={{ border: '1px solid var(--border)', borderRadius: 3, padding: '1px 4px', fontSize: 8 }}>
                            {SOURCE_TYPE_LABELS[st] || st}
                          </span>
                        </td>
                        <td className={styles.dataCell}>
                          <span style={{ fontSize: 9, fontWeight: 600, color: 'var(--red)' }}>{reason}</span>
                        </td>
                        <td className={styles.dataCell} style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
                          {fmtLift(p.lift_vs_false_positive)}
                        </td>
                        <td className={styles.dataCell} style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
                          {p.count_all_4x ?? '—'}
                        </td>
                        <td className={styles.dataCell} style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
                          {p.count_false_positive ?? '—'}
                        </td>
                        <td className={styles.dataCell} style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
                          {p.count_normal_winner ?? '—'}
                        </td>
                        <td className={styles.dataCell} style={{ fontSize: 10, maxWidth: 260, color: 'var(--text-dim)' }}>
                          {p.description || p.sequence_signature || '—'}
                        </td>
                      </tr>
                    );
                  })
              }
            </tbody>
          </table>
        </div>
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
  const [npCoverage,  setNpCoverage]  = useState(null);
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

  // Delete
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting,      setDeleting]      = useState(false);
  const [deleteErr,     setDeleteErr]     = useState('');

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
      setNpCoverage(data.np_coverage || null);
    } catch {
      setRun(null);
      setNpCoverage(null);
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

  // ── Delete run ────────────────────────────────────────────────────────────
  const handleDeleteRun = async () => {
    if (!selectedId) return;
    setDeleting(true);
    setDeleteErr('');
    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/${selectedId}`, { method: 'DELETE' });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
      setRuns(prev => prev.filter(x => x.id !== selectedId));
      setSelectedId(null);
      setRun(null);
      setEpisodes([]);
      setComparisons([]);
      setConfirmDelete(false);
    } catch (e) {
      setDeleteErr(String(e));
    } finally {
      setDeleting(false);
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
                <RunHeader
                  run={run}
                  npCoverage={npCoverage}
                  onRepairDone={() => { loadRun(selectedId); loadRuns(); loadEpisodes(selectedId); loadComparisons(selectedId); }}
                  onDelete={() => { setConfirmDelete(true); setDeleteErr(''); }}
                />

                {/* Tab row */}
                <div className={styles.tabRow}>
                  {[
                    { id: 'schemes',     label: 'Top Schemes' },
                    { id: 'episodes',    label: `Episodes (${episodes.length})` },
                    { id: 'comparisons', label: 'Comparisons' },
                    { id: 'np-bundle',     label: 'NP Bundle' },
                    { id: 'split-impact', label: 'Split Impact' },
                    { id: 'discovery',    label: 'Pattern Discovery' },
                    { id: 'ai',           label: 'AI Summary' },
                    { id: 'patch-plan',   label: 'Engine Plan' },
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

                {/* NP Bundle tab */}
                {activeTab === 'np-bundle' && (
                  run.status !== 'complete'
                    ? <div className={styles.statusMsg}>NP bundle available after run completes.</div>
                    : <NPBundlePanel key={selectedId} runId={selectedId} />
                )}

                {/* Split Impact tab */}
                {activeTab === 'split-impact' && (
                  run.status !== 'complete'
                    ? <div className={styles.statusMsg}>Split impact available after run completes.</div>
                    : <SplitImpactPanel key={selectedId} runId={selectedId} />
                )}

                {/* Pattern Discovery tab */}
                {activeTab === 'discovery' && (
                  run.status !== 'complete'
                    ? <div className={styles.statusMsg}>Pattern Discovery available after run completes.</div>
                    : <PatternDiscoveryPanel key={selectedId} runId={selectedId} />
                )}

                {/* AI tab */}
                {activeTab === 'ai' && (
                  run.status !== 'complete'
                    ? <div className={styles.statusMsg}>AI summary available after run completes.</div>
                    : <AISummaryCard key={selectedId} runId={selectedId} />
                )}

                {/* Engine Patch Plan tab */}
                {activeTab === 'patch-plan' && (
                  run.status !== 'complete'
                    ? <div className={styles.statusMsg}>Engine plan available after run completes.</div>
                    : <EnginePatchPlan key={selectedId} runId={selectedId} />
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* ── Delete confirmation modal ──────────────────────────────────── */}
      {confirmDelete && (
        <div className={styles.modalOverlay}>
          <div className={styles.modalBox}>
            <div className={styles.modalTitle}>Delete Run #{selectedId}?</div>
            <p className={styles.modalBody}>
              This will permanently remove all daily features, episode features,
              comparisons, and the AI summary for this run. This cannot be undone.
            </p>
            {deleteErr && <div className={styles.errorMsg}>{deleteErr}</div>}
            <div className={styles.modalActions}>
              <button
                className={styles.modalCancelBtn}
                disabled={deleting}
                onClick={() => { setConfirmDelete(false); setDeleteErr(''); }}
              >
                Cancel
              </button>
              <button
                className={styles.modalDeleteBtn}
                disabled={deleting}
                onClick={handleDeleteRun}
              >
                {deleting ? 'Deleting…' : 'Delete Permanently'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
