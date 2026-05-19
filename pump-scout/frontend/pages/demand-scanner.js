import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import styles from '../styles/ScannerV2.module.css';
import AppNav from '../components/AppNav';

// ── Constants ────────────────────────────────────────────────────────────────

const API = '/api/demand-scanner/latest';

const TIER_META = {
  PRIME_BUY:     { label: 'PRIME',      color: '#34d399', bg: 'rgba(52,211,153,0.15)' },
  HIGH_CONF_BUY: { label: 'HIGH CONF',  color: '#60a5fa', bg: 'rgba(96,165,250,0.15)' },
  BUY_WATCH:     { label: 'BUY WATCH',  color: '#fbbf24', bg: 'rgba(251,191,36,0.12)' },
  SETUP_MONITOR: { label: 'MONITOR',    color: '#a78bfa', bg: 'rgba(167,139,250,0.12)' },
  SKIP:          { label: 'SKIP',       color: '#6b7280', bg: 'rgba(107,114,128,0.08)' },
};

const ATS_META = {
  ATS_PRIME: { label: 'ATS PRIME', color: '#34d399' },
  ATS_SETUP: { label: 'ATS SETUP', color: '#60a5fa' },
  ATS_WATCH: { label: 'ATS WATCH', color: '#fbbf24' },
  ATS_NONE:  { label: '—',         color: '#4b5563' },
};

const REASONS_PRETTY = {
  price_1_3:             'Price $1–$3',
  price_sub1_liquid:     'Price <$1 (liquid)',
  price_3_10:            'Price $3–$10',
  atr_normal:            'ATR normal',
  dv_liquid:             'DV liquid',
  v2_buy_high:           'V2 BUY HIGH',
  v2_buy:                'V2 BUY',
  v2_watch_high:         'V2 WATCH HIGH',
  v2_watch_medium:       'V2 WATCH MED',
  v2_watch_or_fire:      'V2 WATCH / FIRE',
  np_setup:              'NP SETUP',
  has_l34_np_ld:         'L34+NP+LD ★',
  has_wc_gap_ld:         'WC→GAP+LD ★',
  l34_l43_wlnbb:         'L34/L43 WLNBB',
  d4_d6_beup:            'D4/D6 BEUP',
  d3_core_beup:          'D3/Core BEUP',
  core_d_l34_combo:      'Core-D + L34',
  triple_d_l34_beup:     'Triple D+L34+BEUP ★★',
  ats_prime:             'ATS PRIME ★★★',
  ats_setup:             'ATS SETUP ★★',
  ats_watch:             'ATS WATCH ★',
  sector_leading:        'Sector leading',
  macro_tailwind:        'Macro tailwind',
  sympathy_high:         'Sympathy high',
  hype_warm:             'Hype WARM',
  hype_hot:              'Hype HOT',
};

const ATS_COND_PRETTY = {
  vol_dryup_3d:    'Vol dryup 3d',
  atr_contracting: 'ATR contracting',
  demand_bar:      'Demand bar (L34/LD)',
  near_ema50:      'Near EMA50',
  not_pumped:      'Not pumped',
  tight_range_bonus: 'Tight range (bonus)',
};

// ── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (v, d = 1) => v == null ? '—' : Number(v).toFixed(d);
const fmtPct = v => v == null ? '—' : `${Number(v).toFixed(1)}%`;
const fmtK = v => {
  if (v == null) return '—';
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return String(v);
};

// ── Sub-components ────────────────────────────────────────────────────────────

function TierBadge({ tier }) {
  const m = TIER_META[tier] || TIER_META.SKIP;
  return (
    <span style={{
      display: 'inline-block', padding: '2px 7px', borderRadius: 4,
      fontSize: 10, fontWeight: 700, letterSpacing: '0.06em',
      color: m.color, background: m.bg, border: `1px solid ${m.color}40`,
    }}>{m.label}</span>
  );
}

function AtsBadge({ signal }) {
  const m = ATS_META[signal] || ATS_META.ATS_NONE;
  if (signal === 'ATS_NONE') return <span style={{ color: '#4b5563', fontSize: 10 }}>—</span>;
  return (
    <span style={{
      display: 'inline-block', padding: '2px 6px', borderRadius: 4,
      fontSize: 10, fontWeight: 700, letterSpacing: '0.06em',
      color: m.color, background: `${m.color}18`, border: `1px solid ${m.color}40`,
    }}>{m.label}</span>
  );
}

function ScoreBar({ score, max = 20 }) {
  const pct = Math.min(100, (score / max) * 100);
  const color = score >= 13 ? '#34d399' : score >= 9 ? '#60a5fa' : score >= 6 ? '#fbbf24' : '#6b7280';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width: 60, height: 5, background: '#1f2937', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>
        {fmt(score, 1)}
      </span>
    </div>
  );
}

function AtsConditions({ met = [], missing = [] }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
      {met.map(c => (
        <span key={c} style={{
          fontSize: 9, padding: '1px 5px', borderRadius: 3,
          background: 'rgba(52,211,153,0.12)', color: '#34d399',
          border: '1px solid rgba(52,211,153,0.25)',
        }}>{ATS_COND_PRETTY[c] || c}</span>
      ))}
      {missing.map(c => (
        <span key={c} style={{
          fontSize: 9, padding: '1px 5px', borderRadius: 3,
          background: 'rgba(239,68,68,0.08)', color: '#ef4444',
          border: '1px solid rgba(239,68,68,0.2)',
        }}>{ATS_COND_PRETTY[c] || c}</span>
      ))}
    </div>
  );
}

function ReasonChips({ reasons = [] }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
      {reasons.slice(0, 8).map(r => (
        <span key={r} style={{
          fontSize: 9, padding: '1px 5px', borderRadius: 3,
          background: 'rgba(96,165,250,0.1)', color: '#93c5fd',
          border: '1px solid rgba(96,165,250,0.2)',
        }}>{REASONS_PRETTY[r] || r}</span>
      ))}
    </div>
  );
}

function ScoreBreakdown({ bd = {} }) {
  const items = [
    { key: 'regime',          label: 'Regime',    color: '#a78bfa' },
    { key: 'base_pump',       label: 'NP Base',   color: '#60a5fa' },
    { key: 'demand_bars',     label: 'Demand',    color: '#34d399' },
    { key: 'ats',             label: 'ATS',       color: '#fbbf24' },
    { key: 'context',         label: 'Context',   color: '#f472b6' },
    { key: 'expansion_penalty', label: 'Exp Pen', color: '#f87171' },
  ];
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
      {items.filter(i => bd[i.key] != null && bd[i.key] !== 0).map(i => (
        <div key={i.key} style={{ textAlign: 'center', minWidth: 36 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: bd[i.key] < 0 ? '#f87171' : i.color }}>
            {bd[i.key] > 0 ? '+' : ''}{fmt(bd[i.key], 1)}
          </div>
          <div style={{ fontSize: 8, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {i.label}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Drawer ────────────────────────────────────────────────────────────────────

function DetailDrawer({ row, onClose, narrative, narrativeLoading, onFetchNarrative }) {
  if (!row) return null;
  const tier = TIER_META[row.demand_composite_tier] || TIER_META.SKIP;
  return (
    <div style={{
      position: 'fixed', right: 0, top: 0, bottom: 0, width: 420,
      background: '#111827', borderLeft: '1px solid #1f2937',
      zIndex: 1000, overflowY: 'auto', padding: 20,
      boxShadow: '-8px 0 32px rgba(0,0,0,0.5)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, color: '#f9fafb' }}>{row.symbol}</div>
          <div style={{ fontSize: 12, color: '#9ca3af', marginTop: 2 }}>
            ${fmt(row.price, 2)} · {row.sector || '—'}
          </div>
        </div>
        <button onClick={onClose} style={{
          background: 'none', border: '1px solid #374151', color: '#9ca3af',
          borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontSize: 12,
        }}>Close</button>
      </div>

      {/* Tier + score */}
      <div style={{
        background: tier.bg, border: `1px solid ${tier.color}40`,
        borderRadius: 8, padding: '12px 16px', marginBottom: 16,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <TierBadge tier={row.demand_composite_tier} />
          <div style={{ fontSize: 28, fontWeight: 800, color: tier.color }}>
            {fmt(row.demand_composite_score, 1)}<span style={{ fontSize: 14, opacity: 0.5 }}>/20</span>
          </div>
        </div>
        <div style={{ marginTop: 10 }}>
          <ScoreBreakdown bd={row.demand_score_breakdown || {}} />
        </div>
      </div>

      {/* ATS Signal */}
      <div style={{
        background: '#1f2937', borderRadius: 8, padding: '12px 14px', marginBottom: 12,
      }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#9ca3af', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          Accumulation Trap Signal
        </div>
        <AtsBadge signal={row.ats_signal} />
        <AtsConditions
          met={row.ats_conditions_met || []}
          missing={row.ats_conditions_missing || []}
        />
      </div>

      {/* Reasons */}
      <div style={{ background: '#1f2937', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#9ca3af', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          Active Signals
        </div>
        <ReasonChips reasons={row.demand_buy_reasons || []} />
        {(row.demand_risk_flags || []).length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 6 }}>
            {row.demand_risk_flags.map(f => (
              <span key={f} style={{
                fontSize: 9, padding: '1px 5px', borderRadius: 3,
                background: 'rgba(239,68,68,0.08)', color: '#f87171',
                border: '1px solid rgba(239,68,68,0.2)',
              }}>{f}</span>
            ))}
          </div>
        )}
      </div>

      {/* Candle metrics */}
      <div style={{ background: '#1f2937', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#9ca3af', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          Candle Metrics
        </div>
        {[
          ['Dryup streak', `${row.dc_dryup_streak ?? '—'} days`],
          ['ATR contracting', row.dc_atr_contracting ? 'Yes' : 'No'],
          ['Near EMA50', row.dc_near_ema50 ? 'Yes' : 'No'],
          ['EMA50 dist', row.dc_ema_dist_pct != null ? `${row.dc_ema_dist_pct}%` : '—'],
          ['Vol ratio', row.dc_vol_ratio != null ? `${row.dc_vol_ratio}×` : '—'],
          ['5d range', row.dc_range_pct_5d != null ? `${row.dc_range_pct_5d}%` : '—'],
          ['10d max gain', row.dc_max_gain_10d != null ? `${row.dc_max_gain_10d}%` : '—'],
          ['Tight range', row.dc_tight_range ? 'Yes' : 'No'],
        ].map(([label, val]) => (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 11, color: '#9ca3af' }}>{label}</span>
            <span style={{ fontSize: 11, color: '#f9fafb', fontVariantNumeric: 'tabular-nums' }}>{val}</span>
          </div>
        ))}
      </div>

      {/* Demand bar flags */}
      <div style={{ background: '#1f2937', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#9ca3af', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          Demand Bar Flags
        </div>
        {[
          ['has_l34_np_ld',    'L34+NP+LD',        '#34d399'],
          ['has_wc_gap_ld',    'WC→GAP+LD',        '#34d399'],
          ['l34_wlnbb',        'L34 WLNBB',         '#60a5fa'],
          ['l43_wlnbb',        'L43 WLNBB',         '#60a5fa'],
          ['d4_beup',          'D4 BEUP',           '#a78bfa'],
          ['d6_beup',          'D6 BEUP',           '#a78bfa'],
          ['core_d_l34',       'Core-D+L34',        '#fbbf24'],
          ['has_triple_d_l34_beup', 'Triple D★',   '#f472b6'],
        ].map(([key, lbl, col]) => (
          <div key={key} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 11, color: '#9ca3af' }}>{lbl}</span>
            <span style={{ fontSize: 11, color: row[key] ? col : '#374151', fontWeight: row[key] ? 700 : 400 }}>
              {row[key] ? '✓' : '—'}
            </span>
          </div>
        ))}
      </div>

      {/* NP engine */}
      <div style={{ background: '#1f2937', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#9ca3af', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          NP Engine
        </div>
        {[
          ['NP score',     row.new_pump_score],
          ['NP label',     row.new_pump_label?.replace('NEW_PUMP_', '') || '—'],
          ['Structure',    row.structure_phase || '—'],
          ['CE state',     row.compression_expansion_state || '—'],
          ['Exp risk',     row.expansion_timing_risk || '—'],
          ['Decision',     row.decision || '—'],
        ].map(([label, val]) => (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontSize: 11, color: '#9ca3af' }}>{label}</span>
            <span style={{ fontSize: 11, color: '#f9fafb' }}>{val ?? '—'}</span>
          </div>
        ))}
      </div>

      {/* AI Analysis */}
      <div style={{ background: '#0f172a', border: '1px solid #1e3a5f', borderRadius: 8, padding: '12px 14px' }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#60a5fa', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          AI Setup Analysis
        </div>
        {!narrative && !narrativeLoading && (
          <button
            onClick={() => onFetchNarrative(row)}
            style={{
              background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 6,
              padding: '7px 14px', fontSize: 11, fontWeight: 600, cursor: 'pointer',
              width: '100%',
            }}
          >
            Generate AI Analysis
          </button>
        )}
        {narrativeLoading && (
          <div style={{ color: '#9ca3af', fontSize: 11, textAlign: 'center', padding: '8px 0' }}>
            Generating…
          </div>
        )}
        {narrative && (
          <p style={{ fontSize: 12, color: '#d1d5db', lineHeight: 1.7, margin: 0 }}>
            {narrative}
          </p>
        )}
      </div>
    </div>
  );
}

// ── Main table row ────────────────────────────────────────────────────────────

function ResultRow({ r, onClick }) {
  const tier = TIER_META[r.demand_composite_tier] || TIER_META.SKIP;
  return (
    <tr
      onClick={() => onClick(r)}
      style={{ cursor: 'pointer', borderBottom: '1px solid #1f2937' }}
      onMouseEnter={e => e.currentTarget.style.background = '#1a2433'}
      onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
    >
      <td style={{ padding: '8px 12px', fontWeight: 700, color: '#f9fafb', fontSize: 13, fontFamily: 'monospace' }}>
        {r.symbol}
      </td>
      <td style={{ padding: '8px 8px' }}>
        <TierBadge tier={r.demand_composite_tier} />
      </td>
      <td style={{ padding: '8px 8px' }}>
        <ScoreBar score={r.demand_composite_score} />
      </td>
      <td style={{ padding: '8px 8px' }}>
        <AtsBadge signal={r.ats_signal} />
      </td>
      <td style={{ padding: '8px 8px', fontSize: 11, color: '#e5e7eb', fontVariantNumeric: 'tabular-nums' }}>
        ${fmt(r.price, 2)}
      </td>
      <td style={{ padding: '8px 8px', fontSize: 11, color: '#9ca3af', fontVariantNumeric: 'tabular-nums' }}>
        {fmtK(r.volume_today)}
      </td>
      <td style={{ padding: '8px 8px', fontSize: 11 }}>
        <span style={{ color: r.has_l34_np_ld ? '#34d399' : '#374151', fontWeight: 700 }}>
          {r.has_l34_np_ld ? 'L34NP' : '—'}
        </span>
        {' '}
        <span style={{ color: r.has_wc_gap_ld ? '#34d399' : '#374151', fontWeight: 700 }}>
          {r.has_wc_gap_ld ? 'WcGap' : ''}
        </span>
        {' '}
        <span style={{ color: r.l34_wlnbb ? '#60a5fa' : '#374151' }}>
          {r.l34_wlnbb ? 'L34' : ''}
        </span>
        {' '}
        <span style={{ color: (r.d4_beup || r.d6_beup) ? '#a78bfa' : '#374151', fontWeight: 700 }}>
          {r.d6_beup ? 'D6' : r.d4_beup ? 'D4' : ''}
        </span>
      </td>
      <td style={{ padding: '8px 8px', fontSize: 10, color: '#6b7280' }}>
        {r.dc_dryup_streak > 0 && <span style={{ color: r.dc_dryup_streak >= 3 ? '#fbbf24' : '#6b7280', marginRight: 4 }}>
          Dry×{r.dc_dryup_streak}
        </span>}
        {r.dc_near_ema50 && <span style={{ color: '#60a5fa', marginRight: 4 }}>EMA✓</span>}
        {r.dc_atr_contracting && <span style={{ color: '#a78bfa' }}>ATR↘</span>}
      </td>
      <td style={{ padding: '8px 8px', fontSize: 10, color: '#6b7280' }}>
        {r.sector || '—'}
      </td>
    </tr>
  );
}

// ── Summary cards ─────────────────────────────────────────────────────────────

function SummaryCard({ label, val, color = '#f9fafb', sub }) {
  return (
    <div style={{
      background: '#111827', border: '1px solid #1f2937', borderRadius: 10,
      padding: '14px 18px', minWidth: 110, textAlign: 'center',
    }}>
      <div style={{ fontSize: 26, fontWeight: 800, color, lineHeight: 1 }}>{val}</div>
      <div style={{ fontSize: 9, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.07em', marginTop: 4 }}>
        {label}
      </div>
      {sub && <div style={{ fontSize: 10, color: '#9ca3af', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

// ── ATS Explanation card ──────────────────────────────────────────────────────

function AtsExplainer() {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ margin: '0 var(--page-px, 20px) 12px', background: '#0f172a', border: '1px solid #1e3a5f', borderRadius: 8, overflow: 'hidden' }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', textAlign: 'left', background: 'none', border: 'none',
          padding: '10px 14px', cursor: 'pointer', color: '#60a5fa', fontSize: 12, fontWeight: 600,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}
      >
        <span>ACCUMULATION TRAP SIGNAL — how it works</span>
        <span style={{ fontSize: 10 }}>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div style={{ padding: '0 14px 14px', fontSize: 11, color: '#9ca3af', lineHeight: 1.7 }}>
          <p style={{ margin: '0 0 8px' }}>
            ATS detects stocks in <strong style={{ color: '#e5e7eb' }}>silent accumulation</strong> — quiet compression
            with demand bars, sitting near support, before a potential breakout.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {[
              ['vol_dryup_3d',    'Vol dryup 3d',    '3+ consecutive days below 55% of 20d avg volume'],
              ['atr_contracting', 'ATR contracting',  '5d ATR < 70% of 20d ATR — range shrinking'],
              ['demand_bar',      'Demand bar',       'L34/NP or lower-wick reclaim bar in last 5 days'],
              ['near_ema50',      'Near EMA50',       'Price within −5% to +8% of EMA50 support'],
              ['not_pumped',      'Not pumped',       'Max gain last 10 days < 35% (fresh setup)'],
            ].map(([key, name, desc]) => (
              <div key={key} style={{ background: '#1e293b', borderRadius: 6, padding: '8px 10px' }}>
                <div style={{ color: '#34d399', fontWeight: 700, marginBottom: 2 }}>{name}</div>
                <div style={{ fontSize: 10, color: '#6b7280' }}>{desc}</div>
              </div>
            ))}
            <div style={{ background: '#1e293b', borderRadius: 6, padding: '8px 10px' }}>
              <div style={{ color: '#fbbf24', fontWeight: 700, marginBottom: 2 }}>tight_range (bonus)</div>
              <div style={{ fontSize: 10, color: '#6b7280' }}>5d range &lt; 1.5× daily ATR — extra compression</div>
            </div>
          </div>
          <p style={{ margin: '8px 0 0', fontSize: 10, color: '#4b5563' }}>
            Derived from R156 pattern #1 (rel=0.822, 11.7× lift) and CFR research signals.
            Research only — no Scanner V2 change.
          </p>
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DemandScannerPage() {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  const [tierF,    setTierF]    = useState('');
  const [atsF,     setAtsF]     = useState('');
  const [minScore, setMinScore] = useState(0);
  const [limit,    setLimit]    = useState(200);

  const [drawerRow,        setDrawerRow]        = useState(null);
  const [narratives,       setNarratives]       = useState({});
  const [narrativeLoading, setNarrativeLoading] = useState(null);
  const [sortCol,   setSortCol]   = useState('demand_composite_score');
  const [sortDir,   setSortDir]   = useState('desc');

  const fetchNarrative = useCallback(async (row) => {
    const sym = row.symbol;
    if (narratives[sym] || narrativeLoading === sym) return;
    setNarrativeLoading(sym);
    try {
      const res  = await fetch('/api/demand-scanner/narrative', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(row),
      });
      const json = await res.json();
      setNarratives(prev => ({ ...prev, [sym]: json.narrative || json.detail || 'No narrative returned.' }));
    } catch (e) {
      setNarratives(prev => ({ ...prev, [sym]: `Error: ${e}` }));
    } finally {
      setNarrativeLoading(null);
    }
  }, [narratives, narrativeLoading]);

  const fetchData = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const params = new URLSearchParams();
      if (tierF)      params.set('tier', tierF);
      if (atsF)       params.set('ats_signal', atsF);
      if (minScore > 0) params.set('min_score', minScore);
      params.set('limit', limit);
      const res  = await fetch(`${API}?${params}`);
      const json = await res.json();
      setData(json);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [tierF, atsF, minScore, limit]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const results = data?.results || [];

  // Client-side sort
  const sorted = [...results].sort((a, b) => {
    const av = a[sortCol] ?? 0, bv = b[sortCol] ?? 0;
    if (sortCol === 'symbol') return sortDir === 'asc' ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    return sortDir === 'asc' ? av - bv : bv - av;
  });

  const toggleSort = col => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('desc'); }
  };

  const Th = ({ col, label }) => (
    <th
      onClick={() => toggleSort(col)}
      style={{
        padding: '8px 8px', textAlign: 'left', fontSize: 9, fontWeight: 700,
        textTransform: 'uppercase', letterSpacing: '0.07em', color: '#6b7280',
        cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap',
        borderBottom: '1px solid #1f2937',
      }}
    >
      {label}{sortCol === col ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
    </th>
  );

  const tc = data?.tier_counts || {};
  const ac = data?.ats_counts  || {};

  return (
    <>
      <Head><title>Demand Scanner — pump-scout</title></Head>
      <AppNav />
      <div className={styles.page}>

        {/* Header */}
        <div className={styles.header}>
          <h1 className={styles.title}>Demand Composite Scanner</h1>
          <p className={styles.subtitle}>
            ATS + R156 signal fusion · PRIME_BUY → HIGH_CONF → BUY_WATCH · Research only
          </p>
          {data?.scanned_at && (
            <div className={styles.scanTime}>
              Scanned {new Date(data.scanned_at).toLocaleString()} · {data.universe?.toLocaleString()} universe · {data.elapsed_secs}s
            </div>
          )}
        </div>

        {/* Summary bar */}
        <div className={styles.summaryBar}>
          <div className={styles.summaryItem}>
            <span className={styles.summaryNum} style={{ color: '#34d399' }}>
              {data?.demand_prime_count ?? tc.PRIME_BUY ?? 0}
            </span>
            <span className={styles.summaryLbl}>PRIME BUY</span>
          </div>
          <div className={styles.summaryItem}>
            <span className={styles.summaryNum} style={{ color: '#60a5fa' }}>
              {data?.demand_high_count ?? tc.HIGH_CONF_BUY ?? 0}
            </span>
            <span className={styles.summaryLbl}>HIGH CONF</span>
          </div>
          <div className={styles.summaryItem}>
            <span className={styles.summaryNum} style={{ color: '#fbbf24' }}>
              {data?.demand_watch_count ?? tc.BUY_WATCH ?? 0}
            </span>
            <span className={styles.summaryLbl}>BUY WATCH</span>
          </div>
          <div className={styles.summaryItem}>
            <span className={styles.summaryNum} style={{ color: '#34d399' }}>
              {data?.ats_prime_count ?? ac.ATS_PRIME ?? 0}
            </span>
            <span className={styles.summaryLbl}>ATS PRIME</span>
          </div>
          <div className={styles.summaryItem}>
            <span className={styles.summaryNum}>{ac.ATS_SETUP ?? 0}</span>
            <span className={styles.summaryLbl}>ATS SETUP</span>
          </div>
          <div className={styles.summaryItem}>
            <span className={styles.summaryNum}>{data?.total ?? 0}</span>
            <span className={styles.summaryLbl}>SHOWING</span>
          </div>
        </div>

        {/* ATS explainer */}
        <div style={{ paddingTop: 12 }}>
          <AtsExplainer />
        </div>

        {/* Controls */}
        <div className={styles.controls}>
          <div className={styles.filterGroup}>
            <label style={{ fontSize: 11, color: '#9ca3af' }}>Tier</label>
            <select
              value={tierF} onChange={e => setTierF(e.target.value)}
              style={{ background: '#1f2937', color: '#f9fafb', border: '1px solid #374151', borderRadius: 5, padding: '4px 8px', fontSize: 11 }}
            >
              <option value="">All tiers</option>
              {Object.keys(TIER_META).map(t => <option key={t} value={t}>{TIER_META[t].label}</option>)}
            </select>
          </div>
          <div className={styles.filterGroup}>
            <label style={{ fontSize: 11, color: '#9ca3af' }}>ATS</label>
            <select
              value={atsF} onChange={e => setAtsF(e.target.value)}
              style={{ background: '#1f2937', color: '#f9fafb', border: '1px solid #374151', borderRadius: 5, padding: '4px 8px', fontSize: 11 }}
            >
              <option value="">All ATS</option>
              {Object.keys(ATS_META).map(s => <option key={s} value={s}>{ATS_META[s].label}</option>)}
            </select>
          </div>
          <div className={styles.filterGroup}>
            <label style={{ fontSize: 11, color: '#9ca3af' }}>Min score</label>
            <input
              type="number" min={0} max={20} step={0.5} value={minScore}
              onChange={e => setMinScore(Number(e.target.value))}
              style={{ width: 50, background: '#1f2937', color: '#f9fafb', border: '1px solid #374151', borderRadius: 5, padding: '4px 6px', fontSize: 11 }}
            />
          </div>
          <div className={styles.filterGroup}>
            <label style={{ fontSize: 11, color: '#9ca3af' }}>Limit</label>
            <select
              value={limit} onChange={e => setLimit(Number(e.target.value))}
              style={{ background: '#1f2937', color: '#f9fafb', border: '1px solid #374151', borderRadius: 5, padding: '4px 8px', fontSize: 11 }}
            >
              {[50, 100, 200, 500].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <button
            onClick={fetchData}
            style={{
              background: '#1d4ed8', color: '#fff', border: 'none', borderRadius: 6,
              padding: '6px 14px', fontSize: 11, fontWeight: 600, cursor: 'pointer',
            }}
          >
            Refresh
          </button>
        </div>

        {/* State */}
        {loading && <div className={styles.summaryBar} style={{ padding: '16px 20px', color: '#9ca3af', fontSize: 13 }}>Loading…</div>}
        {error   && <div style={{ padding: '16px 20px', color: '#f87171', fontSize: 12 }}>{error}</div>}

        {/* Table */}
        {!loading && !error && (
          <div style={{ overflowX: 'auto', padding: '0 0 80px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: '#0f1729' }}>
                  <Th col="symbol"                  label="Symbol"   />
                  <Th col="demand_composite_tier"   label="Tier"     />
                  <Th col="demand_composite_score"  label="Score"    />
                  <Th col="ats_signal"              label="ATS"      />
                  <Th col="price"                   label="Price"    />
                  <Th col="volume_today"            label="Volume"   />
                  <th style={{ padding: '8px 8px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#6b7280', borderBottom: '1px solid #1f2937' }}>
                    Demand Flags
                  </th>
                  <th style={{ padding: '8px 8px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#6b7280', borderBottom: '1px solid #1f2937' }}>
                    Candle Context
                  </th>
                  <th style={{ padding: '8px 8px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#6b7280', borderBottom: '1px solid #1f2937' }}>
                    Sector
                  </th>
                </tr>
              </thead>
              <tbody>
                {sorted.length === 0 && (
                  <tr>
                    <td colSpan={9} style={{ padding: '24px', color: '#6b7280', fontSize: 13, textAlign: 'center' }}>
                      No results — run a scan first or adjust filters.
                    </td>
                  </tr>
                )}
                {sorted.map(r => (
                  <ResultRow key={r.symbol} r={r} onClick={setDrawerRow} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Detail drawer */}
      {drawerRow && (
        <>
          <div
            onClick={() => setDrawerRow(null)}
            style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)', zIndex: 999 }}
          />
          <DetailDrawer
            row={drawerRow}
            onClose={() => setDrawerRow(null)}
            narrative={narratives[drawerRow?.symbol]}
            narrativeLoading={narrativeLoading === drawerRow?.symbol}
            onFetchNarrative={fetchNarrative}
          />
        </>
      )}
    </>
  );
}
