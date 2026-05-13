import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import styles from '../styles/ScannerV2.module.css';
import AppNav from '../components/AppNav';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ── Decision configs ──────────────────────────────────────────────────────────
const V2_CFG = {
  BUY_CANDIDATE_HIGH:   { color: '#00e676', bg: 'rgba(0,230,118,0.16)',   label: 'BUY HIGH'    },
  BUY_CANDIDATE_NORMAL: { color: '#69f0ae', bg: 'rgba(105,240,174,0.10)', label: 'BUY'         },
  WATCH_HIGH:           { color: '#00b0ff', bg: 'rgba(0,176,255,0.14)',   label: 'WATCH HIGH'  },
  WATCH_MEDIUM:         { color: '#40c4ff', bg: 'rgba(64,196,255,0.10)',  label: 'WATCH MED'   },
  WATCH_LOW:            { color: '#90a4ae', bg: 'rgba(144,164,174,0.10)', label: 'WATCH LOW'   },
  AVOID_RISK:           { color: '#ff5252', bg: 'rgba(255,82,82,0.12)',   label: 'AVOID RISK'  },
  AVOID_LOTTERY:        { color: '#ff9800', bg: 'rgba(255,152,0,0.12)',   label: 'LOTTERY'     },
  AVOID_DEAD:           { color: '#555',    bg: 'rgba(80,80,80,0.08)',    label: 'DEAD'        },
};

const NP_DECISION_CFG = {
  BUY_CANDIDATE: { color: '#00e676', label: 'BUY'     },
  WATCH:         { color: '#ffd600', label: 'WATCH'   },
  AVOID:         { color: '#ff5252', label: 'AVOID'   },
  IMPULSE_RISK:  { color: '#ff9800', label: 'IMPULSE' },
};

const PRIORITY_CFG = {
  PRIORITY_HIGH:   { color: '#00e676', label: 'HIGH'  },
  PRIORITY_MEDIUM: { color: '#ffd600', label: 'MED'   },
  PRIORITY_LOW:    { color: '#607d8b', label: 'LOW'   },
  PRIORITY_RISKY:  { color: '#ff5252', label: 'RISKY' },
};

const PHASE_CFG = {
  CONFIRMED_STRUCTURE: { color: '#00e676', short: 'CONFIRMED' },
  TRIGGERED_STRUCTURE: { color: '#00b0ff', short: 'TRIGGERED' },
  EARLY_STRUCTURE:     { color: '#ffd600', short: 'EARLY'     },
  SETUP_PHASE:         { color: '#ffd600', short: 'SETUP'     },
  IMPULSE_ONLY:        { color: '#c084fc', short: 'IMPULSE'   },
  BROKEN_STRUCTURE:    { color: '#ff9800', short: 'BROKEN'    },
  DEGRADED:            { color: '#ff5252', short: 'DEGRADED'  },
  TRUE_NONE:           { color: '#444',    short: 'NONE'      },
};

const DCONF_CFG = {
  D6_BEUP:                { color: '#4ade80', label: 'D6·BE↑' },
  D4_BEUP:                { color: '#69f0ae', label: 'D4·BE↑' },
  D4_L34:                 { color: '#00b0ff', label: 'D4·L34' },
  D3_L34:                 { color: '#40c4ff', label: 'D3·L34' },
  D3_BEUP:                { color: '#ffd600', label: 'D3·BE↑' },
  D6_L34:                 { color: '#ff9800', label: 'D6·L34' },
  D4_L43:                 { color: '#888',    label: 'D4·L43' },
  D6_L43:                 { color: '#888',    label: 'D6·L43' },
  D3_L43:                 { color: '#888',    label: 'D3·L43' },
  D9:                     { color: '#ff9800', label: 'D9'     },
  D11:                    { color: '#ff9800', label: 'D11'    },
  SECONDARY_D_CONFLUENCE: { color: '#666',    label: 'sD'     },
};

const REGIME_COLOR = {
  RISK_ON: '#00e676', RISK_OFF: '#ff5252', FEAR: '#ff6d00',
  ROTATION: '#ffd740', NEUTRAL: '#888',
};

const HYPE_COLOR = {
  VIRAL: '#ff4400', HOT: '#ff8800', WARM: '#ffd600', COLD: '#555',
};

const ALL_V2_DECISIONS = [
  'BUY_CANDIDATE_HIGH', 'BUY_CANDIDATE_NORMAL',
  'WATCH_HIGH', 'WATCH_MEDIUM', 'WATCH_LOW',
  'AVOID_RISK', 'AVOID_LOTTERY', 'AVOID_DEAD',
];
const ALL_NP_DECISIONS = ['BUY_CANDIDATE', 'WATCH', 'AVOID', 'IMPULSE_RISK'];
const ALL_PRIORITIES   = ['PRIORITY_HIGH', 'PRIORITY_MEDIUM', 'PRIORITY_LOW', 'PRIORITY_RISKY'];
const ALL_PHASES = [
  'CONFIRMED_STRUCTURE', 'TRIGGERED_STRUCTURE',
  'EARLY_STRUCTURE', 'SETUP_PHASE', 'IMPULSE_ONLY',
  'BROKEN_STRUCTURE', 'DEGRADED', 'TRUE_NONE',
];

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmt(n, d = 1) { return n == null ? '—' : Number(n).toFixed(d); }
function fmtVol(n) {
  if (n == null) return '—';
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return String(n);
}

function bestDConf(row) {
  const c = row?.confirmation || {};
  const v1 = c.d_confluence_type;
  if (v1 && v1 !== 'NONE') return v1;
  const v2 = c.d_confluence_type_v2;
  if (v2 && v2 !== 'NONE') return v2.replace('_SAME', '');
  return null;
}

function ssColor(s) {
  if (s == null) return '#444';
  if (s >= 66) return '#00e676';
  if (s >= 46) return '#ff9800';
  return '#ff5252';
}

// ── Badge components ──────────────────────────────────────────────────────────
function V2Badge({ decision }) {
  if (!decision) return <span style={{ color: '#333', fontSize: 9 }}>—</span>;
  const cfg = V2_CFG[decision] || { color: '#888', bg: 'transparent', label: decision };
  return (
    <span style={{
      display: 'inline-block', padding: '3px 9px', borderRadius: 3,
      fontSize: 10, fontWeight: 800, letterSpacing: '0.07em',
      color: cfg.color, background: cfg.bg,
      border: `1px solid ${cfg.color}55`, whiteSpace: 'nowrap',
    }}>{cfg.label}</span>
  );
}

function SplitBadge({ splitStatus }) {
  if (!splitStatus) return <span style={{ color: '#333', fontSize: 9 }}>—</span>;
  const { has_upcoming_split, has_recent_split, split_window_label,
          upcoming_split_type, recent_split_type, upcoming_split_ratio, recent_split_ratio } = splitStatus;
  if (!has_upcoming_split && !has_recent_split) return <span style={{ color: '#333', fontSize: 9 }}>—</span>;
  const isUpcoming = has_upcoming_split;
  const isReverse  = (isUpcoming ? upcoming_split_type : recent_split_type || '').toUpperCase().includes('REVERSE');
  const color      = isUpcoming
    ? (isReverse ? '#ff5252' : '#ffd600')
    : (isReverse ? '#ff9800' : '#90a4ae');
  const ratio      = isUpcoming ? upcoming_split_ratio : recent_split_ratio;
  const tip        = ratio ? `${split_window_label} (${ratio})` : split_window_label;
  return (
    <span title={tip} style={{
      display: 'inline-block', padding: '2px 7px', borderRadius: 3,
      fontSize: 9, fontWeight: 800, letterSpacing: '0.05em',
      color, background: color + '22', border: `1px solid ${color}55`,
      whiteSpace: 'nowrap', cursor: 'default',
    }}>{split_window_label}</span>
  );
}

function NpBadge({ decision }) {
  if (!decision) return <span style={{ color: '#333', fontSize: 9 }}>—</span>;
  const cfg = NP_DECISION_CFG[decision] || { color: '#888', label: decision };
  return (
    <span style={{
      display: 'inline-block', padding: '2px 6px', borderRadius: 3,
      fontSize: 9, fontWeight: 700, letterSpacing: '0.06em',
      color: cfg.color, background: cfg.color + '1a',
      border: `1px solid ${cfg.color}44`, whiteSpace: 'nowrap',
    }}>{cfg.label}</span>
  );
}

function PriorityBadge({ score, label }) {
  if (score == null && !label) return <span style={{ color: '#333', fontSize: 9 }}>—</span>;
  const cfg = PRIORITY_CFG[label] || { color: '#888', label: label || '—' };
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 6px', borderRadius: 3,
      fontSize: 9, fontWeight: 700, letterSpacing: '0.05em',
      color: cfg.color, background: cfg.color + '14',
      border: `1px solid ${cfg.color}44`, whiteSpace: 'nowrap',
    }}>
      {score != null && <span style={{ fontVariantNumeric: 'tabular-nums', opacity: 0.85 }}>{score}</span>}
      <span>{cfg.label}</span>
    </span>
  );
}

function PhaseBadge({ phase }) {
  if (!phase) return <span style={{ color: '#333', fontSize: 9 }}>—</span>;
  const cfg = PHASE_CFG[phase] || { color: '#888', short: phase };
  return (
    <span style={{
      display: 'inline-block', padding: '2px 6px', borderRadius: 3,
      fontSize: 9, fontWeight: 700, letterSpacing: '0.05em',
      color: cfg.color, background: cfg.color + '1a',
      border: `1px solid ${cfg.color}33`, whiteSpace: 'nowrap',
    }}>{cfg.short}</span>
  );
}

function DConfBadge({ row }) {
  const label = bestDConf(row);
  if (!label) return <span style={{ color: '#333', fontSize: 9 }}>—</span>;
  const cfg = DCONF_CFG[label] || { color: '#666', label };
  return (
    <span title={row?.confirmation?.window_explanation || label} style={{
      display: 'inline-block', padding: '2px 6px', borderRadius: 3,
      fontSize: 8, fontWeight: 800, letterSpacing: '0.04em',
      color: cfg.color, background: cfg.color + '22',
      border: `1px solid ${cfg.color}44`,
    }}>{cfg.label}</span>
  );
}

function CtxChip({ label, color }) {
  if (!label) return null;
  return (
    <span style={{
      fontSize: 8, padding: '1px 5px', borderRadius: 2,
      fontWeight: 700, letterSpacing: '0.04em',
      color: color || '#888',
      background: (color || '#888') + '18',
      border: `1px solid ${(color || '#888')}33`,
    }}>{label}</span>
  );
}

function SortTh({ col, sortCol, sortDir, onSort, children }) {
  const active = sortCol === col;
  return (
    <th className={styles.sortTh} onClick={() => onSort(col)}>
      {children}
      <span className={styles.sortArrow} style={{ opacity: active ? 1 : 0.2 }}>
        {active && sortDir === 'asc' ? ' ↑' : ' ↓'}
      </span>
    </th>
  );
}

// ── Drawer ────────────────────────────────────────────────────────────────────
function DRow({ label, children }) {
  return (
    <div className={styles.dRow}>
      <span className={styles.dLabel}>{label}</span>
      <span className={styles.dValue}>{children}</span>
    </div>
  );
}

function SecCard({ title, children }) {
  return (
    <div className={styles.secCard}>
      <div className={styles.secTitle}>{title}</div>
      {children}
    </div>
  );
}

const NEG_FLAG_PREFIXES = [
  'expansion_risk', 'overheated', 'sector_lag', 'macro_head',
  'risk_off', 'hype_late', 'd3_beup', 'd6_l34', 'd_standalone',
  'setup_only', 'lottery', 'has_risk',
];
function isNegFlag(f) { return NEG_FLAG_PREFIXES.some(p => f.startsWith(p)); }

function FlagList({ flags }) {
  if (!flags?.length) return <span className={styles.dValue} style={{ color: '#444' }}>none</span>;
  return (
    <div className={styles.flagsRow}>
      {flags.map(f => (
        <span key={f} className={`${styles.flag} ${isNegFlag(f) ? styles.flagNeg : styles.flagPos}`}>
          {f.replace(/_/g, ' ')}
        </span>
      ))}
    </div>
  );
}

function V2Drawer({ row, onClose }) {
  if (!row) return null;
  const np  = row.new_pump || {};
  const pr  = row.priority || {};
  const cf  = row.confirmation || {};
  const ctx = row.context || {};
  const sc  = ctx.sector_context || {};
  const mc  = ctx.macro_context  || {};
  const nhc = ctx.news_hype_context || {};
  const syc = ctx.sympathy_context  || {};
  const lc  = ctx.legacy_context    || null;
  const v2cfg = V2_CFG[row.scanner_v2_decision] || { color: '#888', label: row.scanner_v2_decision || '—' };
  const sp  = row.split_status || {};

  return (
    <>
      <div className={styles.overlay} onClick={onClose} />
      <div className={styles.drawer}>
        <div className={styles.drawerHeader}>
          <span className={styles.drawerSym}>{row.symbol}</span>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className={styles.drawerBody}>

          {/* 1. Final Scanner v2 Decision */}
          <SecCard title="Scanner v2 Decision">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{
                fontSize: 28, fontWeight: 900, color: v2cfg.color,
                fontVariantNumeric: 'tabular-nums', lineHeight: 1,
              }}>{row.scanner_v2_score ?? '—'}</span>
              <V2Badge decision={row.scanner_v2_decision} />
              <span style={{ fontSize: 9, color: '#444', marginLeft: 'auto' }}>
                rank #{row.scanner_v2_rank}
              </span>
            </div>
            <div style={{ fontSize: 10, color: '#888', marginTop: 6, fontStyle: 'italic', lineHeight: 1.4 }}>
              {row.suggested_action}
            </div>
            {row.scanner_v2_reason && (
              <div style={{ fontSize: 9, color: '#444', marginTop: 4 }}>{row.scanner_v2_reason}</div>
            )}
            <DRow label="V2 Flags"><FlagList flags={row.scanner_v2_flags} /></DRow>
          </SecCard>

          {/* 2. New Pump Structural Core */}
          <SecCard title="New Pump Structural Core">
            <DRow label="NP Decision"><NpBadge decision={np.np_decision} /></DRow>
            <DRow label="Phase"><PhaseBadge phase={np.structure_phase} /></DRow>
            <DRow label="Structure Score">
              <span style={{ color: ssColor(np.structure_score), fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                {np.structure_score ?? '—'}
              </span>
              <span style={{ color: '#555', fontSize: 9, marginLeft: 6 }}>
                bucket {np.structure_score_bucket || '—'}
              </span>
            </DRow>
            <DRow label="Sequence"><span style={{ color: '#aaa' }}>{np.sequence || '—'}</span></DRow>
            <DRow label="C/E State"><span style={{ color: '#aaa' }}>{np.compression_expansion_state || '—'}</span></DRow>
            <DRow label="Exp Risk">
              <span style={{
                color: np.expansion_timing_risk === 'HIGH' ? '#ff5252' : np.expansion_timing_risk === 'MED' ? '#ff9800' : '#888',
                fontWeight: 700,
              }}>{np.expansion_timing_risk || '—'}</span>
            </DRow>
            {np.decision_reason && (
              <div style={{ fontSize: 9, color: '#555', fontStyle: 'italic', marginTop: 3 }}>{np.decision_reason}</div>
            )}
            <DRow label="NP Flags"><FlagList flags={np.decision_flags} /></DRow>
          </SecCard>

          {/* 3. Priority Breakdown */}
          <SecCard title="Priority Breakdown">
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{
                fontSize: 22, fontWeight: 900,
                color: PRIORITY_CFG[pr.priority_label]?.color || '#888',
                fontVariantNumeric: 'tabular-nums', lineHeight: 1,
              }}>{pr.priority_score ?? '—'}</span>
              <PriorityBadge score={null} label={pr.priority_label} />
            </div>
            <DRow label="Priority Flags"><FlagList flags={pr.priority_flags} /></DRow>
            {pr.priority_reason && (
              <div style={{ fontSize: 9, color: '#444', marginTop: 4, wordBreak: 'break-all' }}>{pr.priority_reason}</div>
            )}
          </SecCard>

          {/* 4. D/WLNBB Confirmation */}
          <SecCard title="D / WLNBB Confirmation">
            <DRow label="Confluence">
              <DConfBadge row={row} />
              {cf.d_confluence_family && (
                <span style={{ marginLeft: 6, fontSize: 9, color: '#666' }}>
                  family: <b style={{ color: '#aaa' }}>{cf.d_confluence_family}</b>
                </span>
              )}
            </DRow>
            <DRow label="Timing"><span style={{ color: '#aaa' }}>{cf.d_confluence_timing || '—'}</span></DRow>
            <DRow label="v1 / v2">
              <span style={{ color: '#666', fontSize: 10 }}>
                {cf.d_confluence_type || '—'} / {cf.d_confluence_type_v2 || '—'}
              </span>
            </DRow>
            <DRow label="Active D">
              <span style={{ color: '#aaa', fontSize: 10 }}>
                {(cf.active_d_signals || []).join(', ') || '—'}
              </span>
            </DRow>
            <DRow label="Active WLNBB">
              <span style={{ color: '#aaa', fontSize: 10 }}>
                {(cf.active_wlnbb_signals || []).join(', ') || '—'}
              </span>
            </DRow>
            {cf.window_explanation && (
              <div style={{ fontSize: 9, color: '#555', marginTop: 3, fontStyle: 'italic' }}>{cf.window_explanation}</div>
            )}
          </SecCard>

          {/* 5. Sector / Subsector Context */}
          <SecCard title="Sector / Subsector">
            <DRow label="Sector">
              <span style={{ color: '#ddd' }}>{sc.sector || row.sector || '—'}</span>
              {sc.sector_etf && <span style={{ marginLeft: 6, color: '#666' }}>({sc.sector_etf})</span>}
            </DRow>
            <DRow label="Subsector"><span style={{ color: '#aaa' }}>{sc.subsector || row.subsector || '—'}</span></DRow>
            <DRow label="Sector Strength"><span style={{ color: '#aaa' }}>{sc.sector_strength || 'UNKNOWN'}</span></DRow>
            <DRow label="Subsector Str."><span style={{ color: '#aaa' }}>{sc.subsector_strength || 'UNKNOWN'}</span></DRow>
            <DRow label="Trend"><span style={{ color: '#aaa' }}>{sc.sector_trend || '—'}</span></DRow>
          </SecCard>

          {/* 6. Macro Context */}
          <SecCard title="Macro / Regime">
            <DRow label="Regime">
              <CtxChip label={mc.market_regime || 'UNKNOWN'} color={REGIME_COLOR[mc.market_regime] || '#888'} />
            </DRow>
            {mc.macro_tailwind && <DRow label="Alignment"><span style={{ color: '#00e676', fontWeight: 700 }}>TAILWIND</span></DRow>}
            {mc.macro_headwind && <DRow label="Alignment"><span style={{ color: '#ff5252', fontWeight: 700 }}>HEADWIND</span></DRow>}
            {mc.macro_reason && <div style={{ fontSize: 9, color: '#555', fontStyle: 'italic' }}>{mc.macro_reason}</div>}
          </SecCard>

          {/* 7. News / Hype */}
          <SecCard title="News / Hype">
            <DRow label="Hype Tier">
              <CtxChip label={nhc.hype_tier || 'COLD'} color={HYPE_COLOR[nhc.hype_tier] || '#555'} />
              {nhc.hype_score != null && (
                <span style={{ marginLeft: 6, color: '#888', fontSize: 10 }}>score {nhc.hype_score}</span>
              )}
            </DRow>
            <DRow label="State"><span style={{ color: '#aaa' }}>{(nhc.hype_state || 'UNKNOWN').replace(/_/g, ' ')}</span></DRow>
            {nhc.catalyst_type && <DRow label="Catalyst"><CtxChip label={nhc.catalyst_type} color="#ffd600" /></DRow>}
            {nhc.catalyst_risk_flags?.length > 0 && (
              <DRow label="Risk Flags">
                <div className={styles.flagsRow}>
                  {nhc.catalyst_risk_flags.map(f => <CtxChip key={f} label={f.replace(/_/g, ' ')} color="#ff5252" />)}
                </div>
              </DRow>
            )}
          </SecCard>

          {/* 8. Sympathy + Legacy */}
          <SecCard title="Sympathy / Legacy">
            <DRow label="Theme"><span style={{ color: '#aaa' }}>{syc.sympathy_theme || '—'}</span></DRow>
            <DRow label="Leader"><span style={{ color: '#ddd', fontWeight: 700 }}>{syc.leader_symbol || '—'}</span></DRow>
            <DRow label="Alignment"><CtxChip label={syc.candidate_alignment || 'UNKNOWN'} color={syc.candidate_alignment === 'LAG' ? '#ffd600' : syc.candidate_alignment === 'LEAD' ? '#00e676' : '#888'} /></DRow>
            {syc.sympathy_reason && <div style={{ fontSize: 9, color: '#555', fontStyle: 'italic' }}>{syc.sympathy_reason}</div>}
            {lc && (
              <>
                <DRow label="Legacy Tier"><span style={{ color: '#aaa' }}>{lc.legacy_tier || '—'}</span></DRow>
                <DRow label="Legacy Tags">
                  <div className={styles.flagsRow}>
                    {(lc.legacy_tags || []).map(t => <CtxChip key={t} label={t} color="#90a4ae" />)}
                  </div>
                </DRow>
              </>
            )}
          </SecCard>

          {/* 9. Risk Flags (combined) */}
          <SecCard title="Risk Summary">
            <DRow label="Exp Risk">
              <span style={{
                color: np.expansion_timing_risk === 'HIGH' ? '#ff5252' : '#aaa',
                fontWeight: np.expansion_timing_risk === 'HIGH' ? 800 : 400,
              }}>{np.expansion_timing_risk || '—'}</span>
            </DRow>
            <DRow label="Combined">
              <FlagList flags={[
                ...(row.scanner_v2_flags || []).filter(isNegFlag),
                ...(pr.priority_flags || []).filter(isNegFlag),
              ]} />
            </DRow>
          </SecCard>

          {/* 10. Split Status */}
          <SecCard title="Split Status (±30d / +7d)">
            {!sp.has_recent_split && !sp.has_upcoming_split ? (
              <div style={{ fontSize: 10, color: '#444' }}>No splits in window</div>
            ) : (
              <>
                {sp.has_upcoming_split && (
                  <div style={{ marginBottom: 8 }}>
                    <div style={{ fontSize: 9, color: '#888', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 3 }}>Upcoming</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <SplitBadge splitStatus={{ ...sp, has_recent_split: false }} />
                      <span style={{ fontSize: 10, color: '#ddd', fontWeight: 700 }}>
                        {sp.upcoming_split_date}
                      </span>
                      <span style={{ fontSize: 10, color: '#aaa' }}>
                        in {sp.upcoming_split_days_ahead}d
                      </span>
                      {sp.upcoming_split_ratio && (
                        <span style={{ fontSize: 10, color: '#888', fontFamily: 'monospace' }}>
                          {sp.upcoming_split_ratio}
                        </span>
                      )}
                    </div>
                  </div>
                )}
                {sp.has_recent_split && (
                  <div>
                    <div style={{ fontSize: 9, color: '#888', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 3 }}>Recent</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <SplitBadge splitStatus={{ ...sp, has_upcoming_split: false }} />
                      <span style={{ fontSize: 10, color: '#ddd', fontWeight: 700 }}>
                        {sp.recent_split_date}
                      </span>
                      <span style={{ fontSize: 10, color: '#aaa' }}>
                        {sp.recent_split_days_ago}d ago
                      </span>
                      {sp.recent_split_ratio && (
                        <span style={{ fontSize: 10, color: '#888', fontFamily: 'monospace' }}>
                          {sp.recent_split_ratio}
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </SecCard>

          {/* 11. Suggested Action */}
          <SecCard title="Suggested Action">
            <div style={{ fontSize: 12, color: v2cfg.color, fontWeight: 700, lineHeight: 1.4 }}>
              {row.suggested_action || '—'}
            </div>
          </SecCard>

        </div>
      </div>
    </>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ScannerV2Page() {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  // Filters
  const [finalDecF,  setFinalDecF]  = useState('');
  const [npDecF,     setNpDecF]     = useState('');
  const [priorityF,  setPriorityF]  = useState('');
  const [phaseF,     setPhaseF]     = useState('');
  const [sectorF,    setSectorF]    = useState('');
  const [subsectorF, setSubsectorF] = useState('');
  const [minScore,   setMinScore]   = useState(0);
  const [limit,      setLimit]      = useState(500);

  // Sort
  const [sortCol, setSortCol] = useState('v2_score');
  const [sortDir, setSortDir] = useState('desc');

  // Drawer
  const [drawerRow, setDrawerRow] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (finalDecF)  params.set('final_decision', finalDecF);
      if (npDecF)     params.set('decision', npDecF);
      if (priorityF)  params.set('priority_label', priorityF);
      if (phaseF)     params.set('structure_phase', phaseF);
      if (sectorF)    params.set('sector', sectorF);
      if (subsectorF) params.set('subsector', subsectorF);
      if (minScore)   params.set('min_score', String(minScore));
      if (limit)      params.set('limit', String(limit));
      const url = `${API_URL}/api/scanner/v2/latest${params.toString() ? '?' + params.toString() : ''}`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
    } catch (e) {
      setError(e.message || 'Fetch failed');
    } finally {
      setLoading(false);
    }
  }, [finalDecF, npDecF, priorityF, phaseF, sectorF, subsectorF, minScore, limit]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const toggleSort = (col) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('desc'); }
  };

  const results = data?.results || [];
  const counts  = data?.v2_decision_counts || {};
  const npCounts = data?.np_decision_counts || {};

  // Local sort overlay (server already returns scanner_v2_score desc default)
  const sorted = [...results].sort((a, b) => {
    const m = sortDir === 'asc' ? 1 : -1;
    let va, vb;
    switch (sortCol) {
      case 'v2_score':       va = a.scanner_v2_score; vb = b.scanner_v2_score; break;
      case 'priority_score': va = a.priority?.priority_score; vb = b.priority?.priority_score; break;
      case 'structure_score': va = a.new_pump?.structure_score; vb = b.new_pump?.structure_score; break;
      case 'symbol':         va = a.symbol; vb = b.symbol; break;
      default: return 0;
    }
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    return va < vb ? -m : va > vb ? m : 0;
  });

  return (
    <>
      <Head><title>Scanner v2 — Pump Scout</title></Head>
      <AppNav />
      <div className={styles.page}>

        {/* Header */}
        <div className={styles.header}>
          <h1 className={styles.title}>Scanner v2</h1>
          <p className={styles.subtitle}>
            New Pump structural core · priority ranking · final classification
          </p>
          {data?.scanned_at && (
            <div className={styles.scanTime}>
              Scanned {new Date(data.scanned_at).toLocaleString()}
              {data.universe ? ` · universe ${data.universe.toLocaleString()}` : ''}
              {data.elapsed_secs != null ? ` · ${data.elapsed_secs}s` : ''}
            </div>
          )}
        </div>

        {/* Decision counts summary */}
        {results.length > 0 && (
          <div className={styles.summaryBar}>
            {ALL_V2_DECISIONS.map(d => {
              const cfg = V2_CFG[d] || {};
              return (
                <div key={d} className={styles.summaryItem}>
                  <span className={styles.summaryNum} style={{ color: cfg.color }}>{counts[d] || 0}</span>
                  <span className={styles.summaryLbl} style={{ color: (cfg.color || '#888') + 'aa' }}>
                    {cfg.label || d}
                  </span>
                </div>
              );
            })}
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum}>{results.length}</span>
              <span className={styles.summaryLbl}>Total</span>
            </div>
          </div>
        )}

        {/* NP decision counts (smaller) */}
        {results.length > 0 && (
          <div className={styles.summaryBar} style={{ borderTop: '1px solid var(--border)', opacity: 0.85 }}>
            {ALL_NP_DECISIONS.map(d => {
              const cfg = NP_DECISION_CFG[d] || {};
              return (
                <div key={d} className={styles.summaryItem}>
                  <span className={styles.summaryNum} style={{ color: cfg.color, fontSize: 13 }}>{npCounts[d] || 0}</span>
                  <span className={styles.summaryLbl}>NP {cfg.label || d}</span>
                </div>
              );
            })}
            <div className={styles.summaryItem} style={{ opacity: 0.5 }}>
              <span className={styles.summaryLbl} style={{ fontSize: 8 }}>np_decision is the eligibility gate</span>
            </div>
          </div>
        )}

        {/* Filters */}
        <div className={styles.controls}>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel} style={{ color: '#00e676' }}>V2 Decision</span>
            <select className={styles.select} value={finalDecF} onChange={e => setFinalDecF(e.target.value)}>
              <option value="">All</option>
              {ALL_V2_DECISIONS.map(d => <option key={d} value={d}>{V2_CFG[d]?.label || d}</option>)}
            </select>
          </div>

          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>NP Decision</span>
            <select className={styles.select} value={npDecF} onChange={e => setNpDecF(e.target.value)}>
              <option value="">All</option>
              {ALL_NP_DECISIONS.map(d => <option key={d} value={d}>{NP_DECISION_CFG[d]?.label || d}</option>)}
            </select>
          </div>

          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Priority</span>
            <select className={styles.select} value={priorityF} onChange={e => setPriorityF(e.target.value)}>
              <option value="">All</option>
              {ALL_PRIORITIES.map(p => <option key={p} value={p}>{PRIORITY_CFG[p]?.label || p}</option>)}
            </select>
          </div>

          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Phase</span>
            <select className={styles.select} value={phaseF} onChange={e => setPhaseF(e.target.value)}>
              <option value="">All</option>
              {ALL_PHASES.map(p => <option key={p} value={p}>{PHASE_CFG[p]?.short || p}</option>)}
            </select>
          </div>

          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Sector</span>
            <input
              className={styles.select}
              style={{ width: 130 }}
              value={sectorF}
              onChange={e => setSectorF(e.target.value)}
              placeholder="e.g. Energy"
            />
          </div>

          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Subsector</span>
            <input
              className={styles.select}
              style={{ width: 130 }}
              value={subsectorF}
              onChange={e => setSubsectorF(e.target.value)}
              placeholder="e.g. Semiconductors"
            />
          </div>

          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Min Score</span>
            <select className={styles.select} value={minScore} onChange={e => setMinScore(Number(e.target.value))}>
              {[0, 25, 40, 55, 70, 85].map(v => <option key={v} value={v}>{v === 0 ? 'All' : `${v}+`}</option>)}
            </select>
          </div>

          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Limit</span>
            <select className={styles.select} value={limit} onChange={e => setLimit(Number(e.target.value))}>
              {[100, 250, 500, 1000].map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>

          <button className={styles.refreshBtn} onClick={fetchData} disabled={loading}>
            {loading ? '…' : '⟳ Refresh'}
          </button>
        </div>

        {/* Body */}
        {error ? (
          <div className={styles.error}>Error: {error}</div>
        ) : loading && !data ? (
          <div className={styles.loading}>Loading Scanner v2 results…</div>
        ) : !data ? (
          <div className={styles.empty}>No data.</div>
        ) : sorted.length === 0 ? (
          <div className={styles.empty}>No tickers match the current filters.</div>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <SortTh col="symbol" sortCol={sortCol} sortDir={sortDir} onSort={toggleSort}>Symbol</SortTh>
                  <th>V2 Decision</th>
                  <SortTh col="v2_score" sortCol={sortCol} sortDir={sortDir} onSort={toggleSort}>V2 Score</SortTh>
                  <th>NP</th>
                  <SortTh col="priority_score" sortCol={sortCol} sortDir={sortDir} onSort={toggleSort}>Priority</SortTh>
                  <th>Phase</th>
                  <SortTh col="structure_score" sortCol={sortCol} sortDir={sortDir} onSort={toggleSort}>SS</SortTh>
                  <th>D/W</th>
                  <th title="Split within ±30d past / +7d ahead">Split</th>
                  <th>Sector</th>
                  <th>Subsector</th>
                  <th>Macro</th>
                  <th>Hype</th>
                  <th>Sympathy</th>
                  <th>Risk</th>
                  <th>Suggested Action</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map(r => {
                  const np = r.new_pump || {};
                  const pr = r.priority || {};
                  const ctx = r.context || {};
                  const mc = ctx.macro_context || {};
                  const nhc = ctx.news_hype_context || {};
                  const syc = ctx.sympathy_context || {};
                  const isAvoid = (r.scanner_v2_decision || '').startsWith('AVOID');
                  return (
                    <tr key={r.symbol} className={isAvoid ? styles.rowDim : ''} onClick={() => setDrawerRow(r)}>
                      <td className={styles.symbolCell} onClick={e => e.stopPropagation()}>
                        <Link href={`/ticker/${r.symbol}`} className={styles.symLink}>{r.symbol}</Link>
                      </td>
                      <td><V2Badge decision={r.scanner_v2_decision} /></td>
                      <td className={styles.scoreCell}
                          style={{ color: V2_CFG[r.scanner_v2_decision]?.color || '#888' }}>
                        {r.scanner_v2_score ?? '—'}
                      </td>
                      <td><NpBadge decision={np.np_decision} /></td>
                      <td><PriorityBadge score={pr.priority_score} label={pr.priority_label} /></td>
                      <td><PhaseBadge phase={np.structure_phase} /></td>
                      <td className={styles.ssCell}
                          style={{ color: ssColor(np.structure_score) }}
                          title={np.structure_score_bucket ? `bucket ${np.structure_score_bucket}` : ''}>
                        {np.structure_score ?? '—'}
                      </td>
                      <td><DConfBadge row={r} /></td>
                      <td><SplitBadge splitStatus={r.split_status} /></td>
                      <td className={styles.seqCell} style={{ color: '#aaa', fontSize: 10 }}>
                        {r.sector || '—'}
                      </td>
                      <td className={styles.seqCell} style={{ color: '#888', fontSize: 10 }}>
                        {r.subsector || '—'}
                      </td>
                      <td>
                        {mc.market_regime && (
                          <CtxChip label={mc.market_regime} color={REGIME_COLOR[mc.market_regime] || '#888'} />
                        )}
                      </td>
                      <td>
                        {nhc.hype_tier && nhc.hype_tier !== 'COLD' && (
                          <CtxChip label={nhc.hype_tier} color={HYPE_COLOR[nhc.hype_tier] || '#555'} />
                        )}
                      </td>
                      <td>
                        {syc.candidate_alignment && (
                          <CtxChip
                            label={syc.candidate_alignment}
                            color={syc.candidate_alignment === 'LAG' ? '#ffd600' : syc.candidate_alignment === 'LEAD' ? '#00e676' : '#888'}
                          />
                        )}
                      </td>
                      <td>
                        {np.expansion_timing_risk === 'HIGH' ? (
                          <CtxChip label="HIGH" color="#ff5252" />
                        ) : np.expansion_timing_risk === 'MED' ? (
                          <CtxChip label="MED" color="#ff9800" />
                        ) : (
                          <span style={{ color: '#444', fontSize: 9 }}>—</span>
                        )}
                      </td>
                      <td className={styles.actionCell} title={r.suggested_action}>
                        {r.suggested_action || '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

      </div>

      {drawerRow && <V2Drawer row={drawerRow} onClose={() => setDrawerRow(null)} />}
    </>
  );
}
