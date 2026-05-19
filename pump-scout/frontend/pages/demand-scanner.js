import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import styles from '../styles/ScannerV2.module.css';
import AppNav from '../components/AppNav';

// ── Constants ────────────────────────────────────────────────────────────────

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const API = `${API_URL}/api/demand-scanner/latest`;

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

const READINESS_META = {
  HOT:  { label: 'HOT',  color: '#34d399', bg: 'rgba(52,211,153,0.15)' },
  WARM: { label: 'WARM', color: '#fbbf24', bg: 'rgba(251,191,36,0.12)' },
  COOL: { label: 'COOL', color: '#60a5fa', bg: 'rgba(96,165,250,0.12)' },
  COLD: { label: 'COLD', color: '#6b7280', bg: 'rgba(107,114,128,0.08)' },
};

const BREAKOUT_META = {
  BREAKING:  { label: 'BREAKING',  color: '#34d399' },
  SURGING:   { label: 'SURGING',   color: '#86efac' },
  AWAKENING: { label: 'AWAKENING', color: '#fbbf24' },
  TICKING:   { label: 'TICKING',   color: '#9ca3af' },
  COILING:   { label: 'COILING',   color: '#4b5563' },
};

const FRESHNESS_COLORS = {
  FRESH:    '#34d399',
  NORMAL:   '#9ca3af',
  AGING:    '#fbbf24',
  STALE:    '#f87171',
  DEAD:     '#ef4444',
  NO_DRYUP: '#4b5563',
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
    { key: 'flow',            label: 'Flow',      color: '#22d3ee' },
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

function ReadinessBadge({ tier, score }) {
  const m = READINESS_META[tier] || READINESS_META.COLD;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '2px 7px', borderRadius: 4,
      fontSize: 10, fontWeight: 700, letterSpacing: '0.06em',
      color: m.color, background: m.bg, border: `1px solid ${m.color}40`,
    }}>
      {m.label}
      {score != null && <span style={{ opacity: 0.7, fontSize: 9 }}>{score}/10</span>}
    </span>
  );
}

const CONFLUENCE_META = {
  PREUP_NOW:    { label: 'PREUP ▲',   color: '#4ade80', title: 'EMA stack aligning bullish right now' },
  PREUP_RECENT: { label: 'PREUP~',    color: '#86efac', title: 'PREUP signal in last 2–3 bars' },
  T1T2_BAR:     { label: 'T1/T2',     color: '#34d399', title: 'Strong demand bar (T1 or T2) in last 3 days' },
  WLNBB_L:      { label: 'BB-L',      color: '#22d3ee', title: 'Inside low Bollinger Band compression (L bucket)' },
};

const FLOW_SIGNAL_META = {
  OBV_ACCUM:            { label: 'OBV ▲',       color: '#34d399', title: 'OBV net accumulation >15% of 5d avg vol — smart money buying quietly' },
  LOWER_WICK_ABSORB:    { label: 'LWick ▲▲',    color: '#4ade80', title: 'Avg lower wick ≥30% of bar range last 3 bars — buyers absorbing supply at lows' },
  LOWER_WICK_PARTIAL:   { label: 'LWick ▲',     color: '#86efac', title: 'Avg lower wick ≥20% of bar range — partial lower-wick absorption' },
};

const FLOW_RISK_META = {
  OBV_DISTRIB:          { label: 'OBV ▼',        color: '#f87171', title: 'OBV net distribution — selling pressure accumulating' },
  EMA_SPREAD_WIDE:      { label: 'EMA wide',     color: '#ef4444', title: 'EMA9 >12% above EMA50 — price already extended, late entry risk' },
  EMA_SPREAD_ELEVATED:  { label: 'EMA elev',     color: '#fbbf24', title: 'EMA9 >8% above EMA50 — EMAs spread, some extension risk' },
};

function ReadinessBreakdown({ bd = {}, breakoutSignal, freshness, rsPct, floatTier, catalyst, confluenceSignals = [] }) {
  const bm = BREAKOUT_META[breakoutSignal] || BREAKOUT_META.COILING;
  const items = [
    { key: 'catalyst',   label: 'Catalyst',   color: '#a78bfa' },
    { key: 'breakout',   label: 'Breakout',   color: '#34d399' },
    { key: 'float',      label: 'Float',      color: '#60a5fa' },
    { key: 'freshness',  label: 'Freshness',  color: '#fbbf24' },
    { key: 'rs',         label: 'RS',         color: '#f472b6' },
    { key: 'confluence', label: 'Confluence', color: '#4ade80' },
  ];
  return (
    <div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        {items.map(i => (
          <div key={i.key} style={{ textAlign: 'center', minWidth: 40 }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: (bd[i.key] ?? 0) < 0 ? '#f87171' : i.color }}>
              {(bd[i.key] ?? 0) > 0 ? '+' : ''}{bd[i.key] ?? 0}
            </div>
            <div style={{ fontSize: 8, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              {i.label}
            </div>
          </div>
        ))}
      </div>
      {confluenceSignals.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 6 }}>
          {confluenceSignals.map(sig => {
            const m = CONFLUENCE_META[sig] || { label: sig, color: '#9ca3af', title: '' };
            return (
              <span key={sig} title={m.title} style={{
                background: 'rgba(74,222,128,0.1)', border: `1px solid ${m.color}`,
                color: m.color, borderRadius: 4, padding: '1px 6px', fontSize: 9, fontWeight: 700,
              }}>{m.label}</span>
            );
          })}
        </div>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, fontSize: 10 }}>
        <span style={{ color: bm.color, fontWeight: 600 }}>{bm.label}</span>
        {freshness && (
          <span style={{ color: FRESHNESS_COLORS[freshness] || '#9ca3af' }}>{freshness}</span>
        )}
        {rsPct != null && (
          <span style={{ color: rsPct > 0 ? '#34d399' : '#f87171' }}>
            RS {rsPct > 0 ? '+' : ''}{rsPct}%
          </span>
        )}
        {floatTier && floatTier !== 'UNKNOWN' && (
          <span style={{ color: '#9ca3af' }}>Float: {floatTier.replace('_PROXY', '~')}</span>
        )}
        {catalyst && <span style={{ color: '#a78bfa' }}>Pre-dryup catalyst ✓</span>}
      </div>
    </div>
  );
}

// ── Score History ─────────────────────────────────────────────────────────────

const TIER_COLORS_MINI = {
  PRIME_BUY:     '#4ade80',
  HIGH_CONF_BUY: '#fbbf24',
  BUY_WATCH:     '#60a5fa',
  SETUP_MONITOR: '#9ca3af',
  SKIP:          '#374151',
};

function ScoreHistory({ symbol }) {
  const [hist, setHist] = useState([]);
  useEffect(() => {
    if (!symbol) return;
    fetch(`${API_URL}/api/demand-scanner/history/${symbol}?limit=20`)
      .then(r => r.json())
      .then(d => setHist((d.history || []).reverse()))
      .catch(() => {});
  }, [symbol]);
  if (hist.length < 2) return null;
  const maxScore = Math.max(...hist.map(h => h.combined_score || 0), 10);
  const W = 300, H = 48, pad = 4;
  const pts = hist.map((h, i) => {
    const x = pad + (i / (hist.length - 1)) * (W - pad * 2);
    const y = H - pad - ((h.combined_score || 0) / maxScore) * (H - pad * 2);
    return [x, y, h];
  });
  const pathD = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const latest = hist[hist.length - 1];
  return (
    <div style={{ marginTop: 8 }}>
      <svg width={W} height={H} style={{ display: 'block', overflow: 'visible' }}>
        <path d={pathD} fill="none" stroke="#374151" strokeWidth={1.5} />
        {pts.map(([x, y, h], i) => (
          <circle key={i} cx={x} cy={y} r={3}
            fill={TIER_COLORS_MINI[h.demand_composite_tier] || '#374151'}
            title={`${h.scanned_at?.slice(0,10)} score:${h.combined_score} ${h.demand_composite_tier}`}
          />
        ))}
      </svg>
      <div style={{ display: 'flex', gap: 12, fontSize: 9, color: '#6b7280', marginTop: 2 }}>
        <span>↑ Combined score over {hist.length} scans</span>
        <span>Latest: <span style={{ color: TIER_COLORS_MINI[latest?.demand_composite_tier] || '#9ca3af', fontWeight: 700 }}>{latest?.demand_composite_tier}</span> {latest?.combined_score}</span>
      </div>
    </div>
  );
}

// ── Similar Pumps ─────────────────────────────────────────────────────────────

function SimilarPumps({ symbol }) {
  const [data, setData]   = useState(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    if (loading || data) return;
    setLoading(true);
    fetch(`${API_URL}/api/demand-scanner/similar/${symbol}?top_n=5`)
      .then(r => r.json())
      .then(d => setData(d))
      .catch(() => setData({ similar: [] }))
      .finally(() => setLoading(false));
  };

  return (
    <div>
      {!data && !loading && (
        <button onClick={load} style={{
          background: '#1f2937', border: '1px solid #374151', color: '#9ca3af',
          borderRadius: 6, padding: '5px 12px', cursor: 'pointer', fontSize: 11,
        }}>Find Similar Pumps</button>
      )}
      {loading && <div style={{ color: '#6b7280', fontSize: 11 }}>Searching...</div>}
      {data?.note && <div style={{ color: '#6b7280', fontSize: 11 }}>{data.note}</div>}
      {data?.similar?.length > 0 && (
        <div>
          {data.similar.map((ep, i) => (
            <div key={i} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '5px 0', borderBottom: '1px solid #1f2937',
            }}>
              <div>
                <span style={{ color: '#f9fafb', fontWeight: 700, fontSize: 12 }}>{ep.symbol}</span>
                <span style={{ color: '#9ca3af', fontSize: 10, marginLeft: 6 }}>{ep.pump_start_date}</span>
                {ep.pump_type && (
                  <span style={{ color: '#6b7280', fontSize: 9, marginLeft: 6 }}>{ep.pump_type}</span>
                )}
              </div>
              <div style={{ textAlign: 'right' }}>
                <span style={{ color: '#4ade80', fontWeight: 700, fontSize: 13 }}>
                  {ep.pump_multiple ? `${ep.pump_multiple.toFixed(1)}×` : '?'}
                </span>
                <span style={{ color: '#9ca3af', fontSize: 9, marginLeft: 6 }}>
                  sim:{(ep.similarity * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          ))}
          {data.similar.length === 0 && (
            <div style={{ color: '#6b7280', fontSize: 11 }}>No similar episodes found</div>
          )}
        </div>
      )}
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

      {/* Score trajectory */}
      <div style={{ background: '#1f2937', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#9ca3af', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          Score History
        </div>
        <ScoreHistory symbol={row.symbol} />
      </div>

      {/* Readiness */}
      {row.readiness_tier && (
        <div style={{
          background: READINESS_META[row.readiness_tier]?.bg || 'rgba(107,114,128,0.08)',
          border: `1px solid ${READINESS_META[row.readiness_tier]?.color || '#6b7280'}40`,
          borderRadius: 8, padding: '12px 16px', marginBottom: 16,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
              Trigger Readiness
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <ReadinessBadge tier={row.readiness_tier} score={row.readiness_score} />
            </div>
          </div>
          <ReadinessBreakdown
            bd={row.readiness_breakdown || {}}
            breakoutSignal={row.breakout_signal}
            freshness={row.freshness_label}
            rsPct={row.rs_during_dryup_pct}
            floatTier={row.float_proxy_tier}
            catalyst={row.catalyst_proxy}
            confluenceSignals={row.confluence_signals || []}
          />
        </div>
      )}

      {/* Flow Divergence */}
      {((row.flow_signals?.length > 0) || (row.flow_risks?.length > 0)) && (
        <div style={{ background: '#1f2937', borderRadius: 8, padding: '12px 14px', marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
              Flow Divergence <span style={{ color: '#374151', fontWeight: 400 }}>(CFR_A · R157)</span>
            </div>
            {row.demand_score_breakdown?.flow != null && row.demand_score_breakdown.flow !== 0 && (
              <span style={{
                fontSize: 11, fontWeight: 700,
                color: row.demand_score_breakdown.flow > 0 ? '#22d3ee' : '#f87171',
              }}>
                {row.demand_score_breakdown.flow > 0 ? '+' : ''}{row.demand_score_breakdown.flow.toFixed(1)} pts
              </span>
            )}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {(row.flow_signals || []).map(sig => {
              const m = FLOW_SIGNAL_META[sig] || { label: sig, color: '#22d3ee', title: '' };
              return (
                <span key={sig} title={m.title} style={{
                  background: 'rgba(34,211,238,0.1)', border: `1px solid ${m.color}`,
                  color: m.color, borderRadius: 4, padding: '1px 6px', fontSize: 9, fontWeight: 700,
                }}>{m.label}</span>
              );
            })}
            {(row.flow_risks || []).map(r => {
              const m = FLOW_RISK_META[r] || { label: r, color: '#f87171', title: '' };
              return (
                <span key={r} title={m.title} style={{
                  background: 'rgba(239,68,68,0.08)', border: `1px solid ${m.color}40`,
                  color: m.color, borderRadius: 4, padding: '1px 6px', fontSize: 9, fontWeight: 700,
                }}>{m.label}</span>
              );
            })}
          </div>
        </div>
      )}

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

      {/* Similar historical pumps */}
      <div style={{ background: '#1f2937', borderRadius: 8, padding: '12px 14px', marginBottom: 12, marginTop: 12 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: '#9ca3af', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          Historical Analogues
        </div>
        <SimilarPumps symbol={row.symbol} />
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
      <td style={{ padding: '8px 8px' }}>
        {r.readiness_tier
          ? <ReadinessBadge tier={r.readiness_tier} score={r.readiness_score} />
          : <span style={{ color: '#374151', fontSize: 10 }}>—</span>}
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

// ── AI Trading Journal ────────────────────────────────────────────────────────

const CONFIDENCE_COLOR = { HIGH: '#34d399', MEDIUM: '#fbbf24', LOW: '#f87171' };

function AIJournal() {
  const [state,       setState]       = useState(null);
  const [positions,   setPositions]   = useState([]);
  const [entries,     setEntries]     = useState([]);
  const [running,     setRunning]     = useState(false);
  const [expanded,    setExpanded]    = useState(true);
  const [tab,         setTab]         = useState('journal');
  const [perfStats,   setPerfStats]   = useState(null);
  const [patterns,    setPatterns]    = useState([]);
  const [lessons,     setLessons]     = useState([]);
  const [blacklist,   setBlacklist]   = useState([]);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillMsg, setBackfillMsg] = useState(null);

  const reload = async () => {
    try {
      const [s, p, e, h, stats, pats, les, bl] = await Promise.all([
        fetch(`${API_URL}/api/ai-journal/state`).then(r => r.json()),
        fetch(`${API_URL}/api/ai-journal/positions?status=OPEN`).then(r => r.json()),
        fetch(`${API_URL}/api/ai-journal/entries?limit=8`).then(r => r.json()),
        fetch(`${API_URL}/api/ai-journal/positions?status=CLOSED`).then(r => r.json()),
        fetch(`${API_URL}/api/ai-journal/stats`).then(r => r.json()).catch(() => null),
        fetch(`${API_URL}/api/ai-journal/patterns`).then(r => r.json()).catch(() => ({ patterns: [] })),
        fetch(`${API_URL}/api/ai-journal/lessons?limit=15`).then(r => r.json()).catch(() => ({ lessons: [] })),
        fetch(`${API_URL}/api/ai-journal/blacklist`).then(r => r.json()).catch(() => ({ blacklist: [] })),
      ]);
      setState(s);
      setPositions(p.positions || []);
      setEntries(e.entries || []);
      setState(prev => ({ ...prev, _closed: h.positions || [] }));
      if (stats) setPerfStats(stats);
      setPatterns(pats.patterns || []);
      setLessons(les.lessons || []);
      setBlacklist(bl.blacklist || []);
    } catch {}
  };

  useEffect(() => { reload(); }, []);

  const runSession = async () => {
    setRunning(true);
    try {
      const res  = await fetch(`${API_URL}/api/ai-journal/run`, { method: 'POST' });
      const json = await res.json();
      if (json.error) throw new Error(json.error);
      await reload();
    } catch (e) {
      alert(`AI Journal error: ${e.message}`);
    } finally {
      setRunning(false);
    }
  };

  const runBackfill = async () => {
    setBackfilling(true);
    setBackfillMsg(null);
    try {
      const res  = await fetch(`${API_URL}/api/ai-journal/backfill`, { method: 'POST' });
      const json = await res.json();
      setBackfillMsg(`Backfilled ${json.backfilled ?? 0} signals (${json.errors ?? 0} errors)`);
      setTimeout(() => setBackfillMsg(null), 5000);
      await reload();
    } catch (e) {
      setBackfillMsg(`Backfill error: ${e.message}`);
      setTimeout(() => setBackfillMsg(null), 5000);
    } finally {
      setBackfilling(false);
    }
  };

  const pnlColor = v => v > 0 ? '#34d399' : v < 0 ? '#f87171' : '#9ca3af';
  const pnlSign  = v => v > 0 ? '+' : '';

  const fmtPatternKey = key => {
    if (!key) return key;
    return key.split('|').map(p => p.replace(/_/g, ' ')).join(' + ');
  };

  if (!state) return null;

  const pnlPct  = state.starting_capital > 0
    ? ((state.capital - state.starting_capital) / state.starting_capital * 100).toFixed(1)
    : '0.0';
  const pnlUsd  = (state.capital - state.starting_capital).toFixed(2);
  const isProfit = state.capital >= state.starting_capital;

  return (
    <div style={{
      background: '#0a0f1a', border: '1px solid #1e3a5f', borderRadius: 10,
      marginTop: 20, overflow: 'hidden',
    }}>
      {/* Header */}
      <div
        onClick={() => setExpanded(v => !v)}
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 18px', cursor: 'pointer',
          background: 'rgba(30,58,95,0.3)',
          borderBottom: expanded ? '1px solid #1e3a5f' : 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 13, fontWeight: 800, color: '#60a5fa', letterSpacing: '0.04em' }}>
            AI TRADING JOURNAL
          </span>
          <span style={{ fontSize: 10, color: '#374151', background: '#1e3a5f', borderRadius: 3, padding: '1px 6px' }}>
            $500 virtual account · R154–R157 strategy
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{ textAlign: 'right' }}>
            <span style={{ fontSize: 16, fontWeight: 800, color: isProfit ? '#34d399' : '#f87171' }}>
              ${fmt(state.capital, 2)}
            </span>
            <span style={{ fontSize: 11, color: pnlColor(parseFloat(pnlPct)), marginLeft: 6 }}>
              {pnlSign(parseFloat(pnlPct))}{pnlPct}%
            </span>
          </div>
          <span style={{ color: '#4b5563', fontSize: 12 }}>{expanded ? '▲' : '▼'}</span>
        </div>
      </div>

      {!expanded ? null : (
        <div style={{ padding: '14px 18px' }}>

          {/* Performance stats bar */}
          {perfStats && perfStats.total_trades > 0 && (
            <div style={{
              display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 10,
              padding: '8px 12px', background: 'rgba(17,24,39,0.8)',
              borderRadius: 6, border: '1px solid #1f2937', fontSize: 10,
            }}>
              <span style={{ color: '#9ca3af' }}>
                Win Rate: <strong style={{ color: '#34d399' }}>
                  {(perfStats.win_rate * 100).toFixed(0)}%
                </strong>
              </span>
              {perfStats.avg_win_pct != null && (
                <span style={{ color: '#9ca3af' }}>
                  Avg Win: <strong style={{ color: '#34d399' }}>
                    +{fmt(perfStats.avg_win_pct, 1)}%
                  </strong>
                </span>
              )}
              {perfStats.avg_loss_pct != null && (
                <span style={{ color: '#9ca3af' }}>
                  Avg Loss: <strong style={{ color: '#f87171' }}>
                    {fmt(perfStats.avg_loss_pct, 1)}%
                  </strong>
                </span>
              )}
              <span style={{ color: '#9ca3af' }}>
                Total P&amp;L: <strong style={{ color: pnlColor(perfStats.total_pnl_usd) }}>
                  {pnlSign(perfStats.total_pnl_usd)}${fmt(perfStats.total_pnl_usd, 2)}
                </strong>
              </span>
            </div>
          )}

          {/* Stats row */}
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: 14 }}>
            {[
              ['Cash',       `$${fmt(state.cash, 2)}`,      '#9ca3af'],
              ['Invested',   `$${fmt(state.invested, 2)}`,  '#60a5fa'],
              ['Positions',  state.open_positions,           '#fbbf24'],
              ['Closed',     state.closed_trades,            '#9ca3af'],
              ['Win Rate',   `${state.win_rate_pct}%`,       '#34d399'],
              ['P&L',        `${pnlSign(parseFloat(pnlUsd))}$${pnlUsd}`, pnlColor(parseFloat(pnlUsd))],
            ].map(([label, val, color]) => (
              <div key={label} style={{ textAlign: 'center', minWidth: 52 }}>
                <div style={{ fontSize: 13, fontWeight: 700, color }}>{val}</div>
                <div style={{ fontSize: 9, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
              </div>
            ))}
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
              {backfillMsg && (
                <span style={{ fontSize: 10, color: '#60a5fa', background: 'rgba(30,58,95,0.4)', padding: '3px 8px', borderRadius: 4 }}>
                  {backfillMsg}
                </span>
              )}
              <button
                onClick={runBackfill}
                disabled={backfilling}
                style={{
                  background: 'transparent',
                  color: backfilling ? '#4b5563' : '#6b7280',
                  border: '1px solid #1f2937', borderRadius: 6, padding: '5px 10px',
                  cursor: backfilling ? 'not-allowed' : 'pointer', fontSize: 10, fontWeight: 600,
                }}
              >
                {backfilling ? 'Backfilling…' : 'Backfill Returns'}
              </button>
              <button
                onClick={runSession}
                disabled={running}
                style={{
                  background: running ? '#1f2937' : '#1d4ed8',
                  color: running ? '#6b7280' : '#fff',
                  border: 'none', borderRadius: 6, padding: '6px 14px',
                  cursor: running ? 'not-allowed' : 'pointer', fontSize: 11, fontWeight: 600,
                }}
              >
                {running ? 'Thinking…' : 'Run AI Review'}
              </button>
            </div>
          </div>

          {/* Tabs */}
          <div style={{ display: 'flex', gap: 4, marginBottom: 12, flexWrap: 'wrap' }}>
            {[
              ['journal',   'Journal'],
              ['positions', `Positions (${positions.length})`],
              ['history',   'History'],
              ['patterns',  `Patterns (${patterns.length})`],
              ['lessons',   `Lessons (${lessons.length})`],
              ['blacklist', blacklist.filter(b => b.active).length > 0
                ? `Blacklist ⚠ ${blacklist.filter(b => b.active).length}`
                : 'Blacklist'],
            ].map(([id, label]) => (
              <button key={id} onClick={() => setTab(id)} style={{
                background: tab === id ? '#1e3a5f' : 'transparent',
                color: tab === id ? '#60a5fa'
                  : id === 'blacklist' && blacklist.filter(b => b.active).length > 0 ? '#fbbf24'
                  : '#6b7280',
                border: `1px solid ${tab === id ? '#1e3a5f' : '#1f2937'}`,
                borderRadius: 5, padding: '4px 10px', cursor: 'pointer', fontSize: 10, fontWeight: 600,
              }}>{label}</button>
            ))}
          </div>

          {/* Journal tab */}
          {tab === 'journal' && (
            <div>
              {entries.length === 0 ? (
                <div style={{ color: '#4b5563', fontSize: 12, padding: '20px 0', textAlign: 'center' }}>
                  No journal entries yet. Run an AI review after a demand scan.
                </div>
              ) : entries.map(e => (
                <div key={e.id} style={{
                  background: '#111827', borderRadius: 7, padding: '12px 14px',
                  marginBottom: 10, border: '1px solid #1f2937',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                    <span style={{ fontSize: 10, color: '#4b5563' }}>
                      {e.created_at?.slice(0, 16).replace('T', ' ')}
                    </span>
                    <div style={{ display: 'flex', gap: 8, fontSize: 9 }}>
                      {e.positions_opened > 0 && (
                        <span style={{ color: '#34d399' }}>+{e.positions_opened} opened</span>
                      )}
                      {e.positions_closed > 0 && (
                        <span style={{ color: '#fbbf24' }}>{e.positions_closed} closed</span>
                      )}
                      <span style={{ color: pnlColor(e.capital_after - e.capital_before) }}>
                        {pnlSign(e.capital_after - e.capital_before)}${(e.capital_after - e.capital_before).toFixed(2)}
                      </span>
                    </div>
                  </div>
                  <p style={{ fontSize: 11, color: '#d1d5db', lineHeight: 1.7, margin: 0, whiteSpace: 'pre-wrap' }}>
                    {e.journal_text}
                  </p>
                  {e.strategy_notes && (
                    <div style={{
                      marginTop: 8, padding: '6px 10px', background: 'rgba(96,165,250,0.06)',
                      border: '1px solid rgba(96,165,250,0.15)', borderRadius: 5,
                      fontSize: 10, color: '#93c5fd',
                    }}>
                      Strategy update: {e.strategy_notes}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Positions tab */}
          {tab === 'positions' && (
            <div>
              {positions.length === 0 ? (
                <div style={{ color: '#4b5563', fontSize: 12, padding: '20px 0', textAlign: 'center' }}>
                  No open positions.
                </div>
              ) : positions.map(p => (
                <div key={p.id} style={{
                  display: 'grid', gridTemplateColumns: '80px 1fr 1fr 1fr 1fr 1fr',
                  gap: 8, padding: '8px 0', borderBottom: '1px solid #1f2937', alignItems: 'center',
                }}>
                  <span style={{ color: '#f9fafb', fontWeight: 700, fontSize: 12, fontFamily: 'monospace' }}>
                    {p.symbol}
                  </span>
                  <div style={{ fontSize: 10 }}>
                    <div style={{ color: '#9ca3af' }}>Entry</div>
                    <div style={{ color: '#f9fafb' }}>${fmt(p.entry_price, 2)}</div>
                  </div>
                  <div style={{ fontSize: 10 }}>
                    <div style={{ color: '#9ca3af' }}>Current</div>
                    <div style={{ color: p.current_price ? '#f9fafb' : '#4b5563' }}>
                      {p.current_price ? `$${fmt(p.current_price, 2)}` : '—'}
                    </div>
                  </div>
                  <div style={{ fontSize: 10 }}>
                    <div style={{ color: '#9ca3af' }}>P&amp;L%</div>
                    <div style={{ color: p.current_pnl_pct != null ? pnlColor(p.current_pnl_pct) : '#4b5563', fontWeight: 700 }}>
                      {p.current_pnl_pct != null
                        ? `${pnlSign(p.current_pnl_pct)}${fmt(p.current_pnl_pct, 1)}%`
                        : '—'}
                    </div>
                  </div>
                  <div style={{ fontSize: 10 }}>
                    <div style={{ color: '#9ca3af' }}>Target / Stop</div>
                    <div style={{ color: '#34d399' }}>${fmt(p.target_price, 2)}</div>
                    <div style={{ color: '#f87171' }}>${fmt(p.stop_price, 2)}</div>
                  </div>
                  <div style={{ fontSize: 10 }}>
                    <div style={{ color: '#9ca3af' }}>{p.scan_tier?.replace('_BUY', '').replace('_', ' ')}</div>
                    <div style={{ color: '#6b7280', fontSize: 9 }}>{p.ats_signal?.replace('ATS_', '')}</div>
                    {p.days_held != null && (
                      <div style={{ color: p.days_held >= 12 ? '#fbbf24' : '#6b7280', fontSize: 9 }}>
                        {p.days_held}d held
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* History tab */}
          {tab === 'history' && (
            <div>
              {!(state._closed?.length) ? (
                <div style={{ color: '#4b5563', fontSize: 12, padding: '20px 0', textAlign: 'center' }}>
                  No closed trades yet.
                </div>
              ) : (state._closed || []).slice(0, 15).map(p => (
                <div key={p.id} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '7px 0', borderBottom: '1px solid #1f2937',
                }}>
                  <div>
                    <span style={{ color: '#f9fafb', fontWeight: 700, fontSize: 12, fontFamily: 'monospace' }}>
                      {p.symbol}
                    </span>
                    <span style={{ color: '#4b5563', fontSize: 9, marginLeft: 6 }}>
                      {p.exit_date?.slice(0, 10)}
                    </span>
                    <span style={{ color: '#374151', fontSize: 9, marginLeft: 6 }}>
                      {p.exit_reason}
                    </span>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: pnlColor(p.pnl_usd) }}>
                      {pnlSign(p.pnl_usd)}${fmt(p.pnl_usd, 2)}
                    </div>
                    <div style={{ fontSize: 10, color: pnlColor(p.pnl_pct) }}>
                      {pnlSign(p.pnl_pct)}{fmt(p.pnl_pct, 1)}%
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Patterns tab */}
          {tab === 'patterns' && (
            <div>
              {patterns.length === 0 ? (
                <div style={{ color: '#4b5563', fontSize: 12, padding: '20px 0', textAlign: 'center' }}>
                  No pattern data yet. Run AI reviews after scans to build pattern memory.
                </div>
              ) : patterns.map((pt, i) => {
                const wr = pt.win_rate || 0;
                const wrColor = wr > 0.6 ? '#34d399' : wr > 0.4 ? '#fbbf24' : '#f87171';
                return (
                  <div key={pt.pattern_key || i} style={{
                    background: '#111827', borderRadius: 6, padding: '10px 12px',
                    marginBottom: 8, border: '1px solid #1f2937',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
                      <span style={{ fontSize: 11, fontWeight: 700, color: '#e5e7eb', fontFamily: 'monospace' }}>
                        {fmtPatternKey(pt.pattern_key)}
                      </span>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0, marginLeft: 8 }}>
                        <span style={{
                          fontSize: 10, fontWeight: 700, color: wrColor,
                          background: `${wrColor}20`, padding: '1px 6px', borderRadius: 3,
                        }}>
                          {(wr * 100).toFixed(0)}% win
                        </span>
                        <span style={{ fontSize: 9, color: '#6b7280' }}>{pt.n_trades} trades</span>
                      </div>
                    </div>
                    {pt.notes && (
                      <p style={{ fontSize: 10, color: '#9ca3af', margin: 0, lineHeight: 1.6 }}>
                        {pt.notes.slice(0, 120)}{pt.notes.length > 120 ? '…' : ''}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Lessons tab */}
          {tab === 'lessons' && (
            <div>
              {lessons.length === 0 ? (
                <div style={{ color: '#4b5563', fontSize: 12, padding: '20px 0', textAlign: 'center' }}>
                  No trade lessons yet. Lessons are generated automatically when positions close.
                </div>
              ) : lessons.map(l => {
                const pnlColor2 = l.pnl_pct > 0 ? '#34d399' : l.pnl_pct < 0 ? '#f87171' : '#9ca3af';
                const confColor = CONFIDENCE_COLOR[l.confidence] || '#9ca3af';
                return (
                  <div key={l.id} style={{
                    background: '#111827', borderRadius: 6, padding: '10px 12px',
                    marginBottom: 8, border: `1px solid ${l.pnl_pct > 0 ? '#14532d40' : '#4b182840'}`,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 12, color: '#f9fafb' }}>
                          {l.symbol}
                        </span>
                        <span style={{ fontSize: 11, fontWeight: 700, color: pnlColor2 }}>
                          {l.pnl_pct > 0 ? '+' : ''}{fmt(l.pnl_pct, 1)}%
                        </span>
                        <span style={{ fontSize: 9, color: '#4b5563', background: '#1f2937', padding: '1px 5px', borderRadius: 3 }}>
                          {l.exit_reason}
                        </span>
                      </div>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        {l.confidence && (
                          <span style={{ fontSize: 9, color: confColor, border: `1px solid ${confColor}40`, padding: '1px 5px', borderRadius: 3 }}>
                            {l.confidence}
                          </span>
                        )}
                        <span style={{ fontSize: 9, color: '#4b5563' }}>
                          {l.created_at?.slice(0, 10)}
                        </span>
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 6, marginBottom: 6, flexWrap: 'wrap' }}>
                      {l.scan_tier && (
                        <span style={{ fontSize: 9, color: '#60a5fa', background: 'rgba(96,165,250,0.1)', padding: '1px 5px', borderRadius: 3 }}>
                          {l.scan_tier.replace('_BUY', '')}
                        </span>
                      )}
                      {l.ats_signal && l.ats_signal !== 'ATS_NONE' && (
                        <span style={{ fontSize: 9, color: '#fbbf24', background: 'rgba(251,191,36,0.1)', padding: '1px 5px', borderRadius: 3 }}>
                          {l.ats_signal}
                        </span>
                      )}
                      {(l.tags || []).map(t => (
                        <span key={t} style={{ fontSize: 9, color: '#9ca3af', background: '#1f2937', padding: '1px 5px', borderRadius: 3 }}>{t}</span>
                      ))}
                    </div>
                    {l.what_worked && (
                      <div style={{ fontSize: 10, color: '#86efac', marginBottom: 3 }}>
                        <span style={{ color: '#4b5563' }}>✓ </span>{l.what_worked}
                      </div>
                    )}
                    {l.what_failed && (
                      <div style={{ fontSize: 10, color: '#fca5a5', marginBottom: 3 }}>
                        <span style={{ color: '#4b5563' }}>✗ </span>{l.what_failed}
                      </div>
                    )}
                    {l.lesson && (
                      <div style={{
                        marginTop: 6, padding: '5px 8px', background: 'rgba(96,165,250,0.06)',
                        border: '1px solid rgba(96,165,250,0.12)', borderRadius: 4,
                        fontSize: 10, color: '#93c5fd', fontStyle: 'italic',
                      }}>
                        {l.lesson}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Blacklist tab */}
          {tab === 'blacklist' && (
            <div>
              {blacklist.length === 0 ? (
                <div style={{ color: '#4b5563', fontSize: 12, padding: '20px 0', textAlign: 'center' }}>
                  No blacklisted patterns. The AI will add patterns here when it identifies repeated failures.
                </div>
              ) : blacklist.map(b => (
                <div key={b.pattern_key} style={{
                  background: b.active ? 'rgba(239,68,68,0.05)' : 'rgba(17,24,39,0.5)',
                  border: `1px solid ${b.active ? 'rgba(239,68,68,0.25)' : '#1f2937'}`,
                  borderRadius: 6, padding: '10px 12px', marginBottom: 8,
                  opacity: b.active ? 1 : 0.5,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 700, color: b.active ? '#fca5a5' : '#6b7280' }}>
                      {fmtPatternKey(b.pattern_key)}
                    </span>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <span style={{ fontSize: 9, color: '#ef4444', background: 'rgba(239,68,68,0.1)', padding: '1px 6px', borderRadius: 3 }}>
                        {b.n_failures} failure{b.n_failures !== 1 ? 's' : ''}
                      </span>
                      <span style={{ fontSize: 9, color: b.active ? '#f87171' : '#4b5563' }}>
                        {b.active
                          ? (b.suspended_until ? `until ${b.suspended_until?.slice(0,10)}` : 'permanent')
                          : 'expired'}
                      </span>
                    </div>
                  </div>
                  {b.reason && (
                    <p style={{ fontSize: 10, color: '#9ca3af', margin: 0, lineHeight: 1.5 }}>{b.reason}</p>
                  )}
                </div>
              ))}
              <div style={{ fontSize: 10, color: '#374151', marginTop: 8 }}>
                The AI automatically manages this list based on pattern performance. Entries expire after their suspension period.
              </div>
            </div>
          )}

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

  const [tierF,      setTierF]      = useState('');
  const [atsF,       setAtsF]       = useState('');
  const [readyF,     setReadyF]     = useState('');
  const [minScore,   setMinScore]   = useState(0);
  const [limit,      setLimit]      = useState(200);

  const [drawerRow,        setDrawerRow]        = useState(null);
  const [narratives,       setNarratives]       = useState({});
  const [narrativeLoading, setNarrativeLoading] = useState(null);
  const [sortCol,   setSortCol]   = useState('demand_composite_score');
  const [sortDir,   setSortDir]   = useState('desc');

  const [scanning,     setScanning]     = useState(false);
  const [scanProgress, setScanProgress] = useState(null);
  const [scanError,    setScanError]    = useState(null);

  const fetchNarrative = useCallback(async (row) => {
    const sym = row.symbol;
    if (narratives[sym] || narrativeLoading === sym) return;
    setNarrativeLoading(sym);
    try {
      const res  = await fetch(`${API_URL}/api/demand-scanner/narrative`, {
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

  const triggerScan = useCallback(async () => {
    setScanError(null);
    try {
      const res  = await fetch(`${API_URL}/api/demand-scanner/run`, { method: 'POST' });
      const json = await res.json();
      if (json.status === 'already_running' || json.status === 'started') {
        setScanning(true);
      }
    } catch (e) {
      setScanError(`Failed to start scan: ${e}`);
    }
  }, []);

  // Poll scan status while a scan is running
  useEffect(() => {
    if (!scanning) return;
    const poll = setInterval(async () => {
      try {
        const res  = await fetch(`${API_URL}/api/demand-scanner/status`);
        const json = await res.json();
        setScanProgress(json);
        if (!json.running && (json.phase === 'done' || json.phase === 'error')) {
          setScanning(false);
          clearInterval(poll);
          if (json.phase === 'done') fetchData();
          if (json.phase === 'error') setScanError(json.last_error || 'Scan failed');
        }
      } catch (_) {}
    }, 2000);
    return () => clearInterval(poll);
  }, [scanning, fetchData]);

  const rawResults = data?.results || [];
  const results = readyF
    ? rawResults.filter(r => r.readiness_tier === readyF)
    : rawResults;

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
            <label style={{ fontSize: 11, color: '#9ca3af' }}>Ready</label>
            <select
              value={readyF} onChange={e => setReadyF(e.target.value)}
              style={{ background: '#1f2937', color: '#f9fafb', border: '1px solid #374151', borderRadius: 5, padding: '4px 8px', fontSize: 11 }}
            >
              <option value="">All</option>
              {Object.keys(READINESS_META).map(t => (
                <option key={t} value={t}>{READINESS_META[t].label}</option>
              ))}
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
          <button
            onClick={triggerScan}
            disabled={scanning}
            style={{
              background: scanning ? '#374151' : '#065f46',
              color: scanning ? '#9ca3af' : '#34d399',
              border: `1px solid ${scanning ? '#4b5563' : '#34d399'}`,
              borderRadius: 6, padding: '6px 14px', fontSize: 11, fontWeight: 600,
              cursor: scanning ? 'not-allowed' : 'pointer',
            }}
          >
            {scanning ? 'Scanning…' : 'Scan Today'}
          </button>
        </div>

        {/* Scan progress banner */}
        {scanning && scanProgress && (
          <div style={{
            background: '#0a1628', border: '1px solid #1e3a5f', borderRadius: 8,
            padding: '10px 16px', margin: '8px 0', display: 'flex', alignItems: 'center',
            gap: 12, fontSize: 11, color: '#93c5fd', flexWrap: 'wrap',
          }}>
            <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#3b82f6', animation: 'pulse 1.5s infinite' }} />
            <span style={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: '#60a5fa' }}>
              {scanProgress.phase?.replace(/_/g, ' ')}
            </span>
            {scanProgress.universe_size > 0 && <span>Universe: {scanProgress.universe_size.toLocaleString()}</span>}
            {scanProgress.analyzed_count > 0 && <span>Analyzed: {scanProgress.analyzed_count}</span>}
            {scanProgress.fire_count > 0 && <span style={{ color: '#34d399' }}>PRIME: {scanProgress.fire_count}</span>}
            {scanProgress.elapsed_secs > 0 && <span style={{ color: '#6b7280' }}>{scanProgress.elapsed_secs}s</span>}
          </div>
        )}
        {scanError && (
          <div style={{ padding: '8px 16px', color: '#f87171', fontSize: 11 }}>{scanError}</div>
        )}

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
                  <Th col="readiness_score"         label="Ready"    />
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
                    <td colSpan={10} style={{ padding: '24px', color: '#6b7280', fontSize: 13, textAlign: 'center' }}>
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

      {/* AI Trading Journal */}
      <AIJournal />

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
