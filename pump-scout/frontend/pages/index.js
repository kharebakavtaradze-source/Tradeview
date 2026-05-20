import { useCallback, useEffect, useRef, useState } from 'react';
import Head from 'next/head';
import AppNav from '../components/AppNav';

// ── Constants ─────────────────────────────────────────────────────────────────

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const TIER_META = {
  PRIME_BUY:     { label: 'PRIME',     color: 'var(--pos)',        bg: 'oklch(0.86 0.18 142 / 0.15)' },
  HIGH_CONF_BUY: { label: 'HIGH CONF', color: 'var(--pump-blue)',  bg: 'oklch(0.74 0.12 268 / 0.15)' },
  BUY_WATCH:     { label: 'BUY WATCH', color: 'var(--warn)',       bg: 'oklch(0.84 0.16 80 / 0.12)' },
  SETUP_MONITOR: { label: 'MONITOR',   color: 'var(--pump-blue)',  bg: 'oklch(0.74 0.12 268 / 0.12)' },
  SKIP:          { label: 'SKIP',      color: 'var(--ink-dim)',    bg: 'oklch(0.62 0.010 90 / 0.08)' },
};

const ATS_META = {
  ATS_PRIME: { label: 'ATS ★★★', color: 'var(--pos)' },
  ATS_SETUP: { label: 'ATS ★★',  color: 'var(--pump-blue)' },
  ATS_WATCH: { label: 'ATS ★',   color: 'var(--warn)' },
  ATS_NONE:  { label: '—',        color: 'var(--ink-faint)' },
};

const READINESS_META = {
  HOT:  { label: 'HOT',  color: 'var(--pos)',       bg: 'oklch(0.86 0.18 142 / 0.15)' },
  WARM: { label: 'WARM', color: 'var(--warn)',      bg: 'oklch(0.84 0.16 80 / 0.12)' },
  COOL: { label: 'COOL', color: 'var(--pump-blue)', bg: 'oklch(0.74 0.12 268 / 0.12)' },
  COLD: { label: 'COLD', color: 'var(--ink-dim)',   bg: 'oklch(0.62 0.010 90 / 0.08)' },
};

const ATS_COND_PRETTY = {
  vol_dryup_3d:    'Vol dryup 3d',
  atr_contracting: 'ATR contracting',
  demand_bar:      'Demand bar',
  near_ema50:      'Near EMA50',
  not_pumped:      'Not pumped',
  tight_range_bonus: 'Tight range',
};

const REASONS_PRETTY = {
  has_l34_np_ld: 'L34+NP+LD ★', has_wc_gap_ld: 'WC→GAP+LD ★',
  ats_prime: 'ATS PRIME ★★★', ats_setup: 'ATS SETUP ★★', ats_watch: 'ATS WATCH ★',
  triple_d_l34_beup: 'Triple D+L34 ★★', core_d_l34_combo: 'Core-D+L34',
  d4_d6_beup: 'D4/D6 BEUP', l34_l43_wlnbb: 'L34/L43 WLNBB',
  v2_buy_high: 'V2 BUY HIGH', v2_buy: 'V2 BUY', np_setup: 'NP SETUP',
  sector_leading: 'Sector ↑', hype_hot: 'Hype HOT', hype_warm: 'Hype WARM',
  macro_tailwind: 'Macro ↑', sympathy_high: 'Sympathy ↑',
  price_1_3: '$1-3', price_sub1_liquid: '<$1', price_3_10: '$3-10',
  atr_normal: 'ATR OK', dv_liquid: 'DV OK',
};

const CONFLUENCE_META = {
  PREUP_NOW:    { label: 'PREUP▲', color: 'var(--pos)' },
  PREUP_RECENT: { label: 'PREUP~', color: 'var(--pos)' },
  T1T2_BAR:     { label: 'T1/T2',  color: 'var(--pos)' },
  WLNBB_L:      { label: 'BB-L',   color: 'var(--pump-blue)' },
};

const FLOW_SIGNAL_META = {
  OBV_ACCUM:          { label: 'OBV▲',     color: 'var(--pos)', title: 'OBV net accumulation' },
  LOWER_WICK_ABSORB:  { label: 'LWick▲▲',  color: 'var(--pos)', title: 'Lower wick absorption' },
  LOWER_WICK_PARTIAL: { label: 'LWick▲',   color: 'var(--pos)', title: 'Partial lower-wick' },
};

const FLOW_RISK_META = {
  OBV_DISTRIB:         { label: 'OBV▼',     color: 'var(--neg)', title: 'OBV distribution' },
  EMA_SPREAD_WIDE:     { label: 'EMA wide', color: 'var(--neg)', title: 'EMA9 >12% above EMA50' },
  EMA_SPREAD_ELEVATED: { label: 'EMA elev', color: 'var(--warn)', title: 'EMA9 >8% above EMA50' },
};

const BREAKOUT_META = {
  BREAKING:  { label: 'BREAKING',  color: 'var(--pos)' },
  SURGING:   { label: 'SURGING',   color: 'var(--pos)' },
  AWAKENING: { label: 'AWAKENING', color: 'var(--warn)' },
  TICKING:   { label: 'TICKING',   color: 'var(--ink-mute)' },
  COILING:   { label: 'COILING',   color: 'var(--ink-faint)' },
};

const FRESHNESS_COLORS = {
  FRESH: 'var(--pos)', NORMAL: 'var(--ink-mute)', AGING: 'var(--warn)',
  STALE: 'var(--neg)', DEAD: 'var(--neg)', NO_DRYUP: 'var(--ink-faint)',
};

const TIER_COLORS_MINI = {
  PRIME_BUY: 'var(--pos)', HIGH_CONF_BUY: 'var(--warn)',
  BUY_WATCH: 'var(--pump-blue)', SETUP_MONITOR: 'var(--ink-mute)', SKIP: 'var(--bg-3)',
};

const REGIME_COLORS = {
  BULL_IMPULSE: 'var(--pos)', BULL_RECOVERY: 'var(--pos)', NEUTRAL: 'var(--warn)',
  BEAR_CAUTION: 'var(--neg)', BEAR_DECLINE: 'var(--neg)',
  ACCUMULATION: 'var(--pump-blue)', DISTRIBUTION: 'var(--pump-blue)',
};

// ── Market helpers ────────────────────────────────────────────────────────────

function getEtOffset(now) {
  const year = now.getUTCFullYear();
  const dstStart = (() => {
    const d = new Date(Date.UTC(year, 2, 1));
    return new Date(Date.UTC(year, 2, 1 + (7 - d.getUTCDay()) % 7 + 7, 7));
  })();
  const dstEnd = (() => {
    const d = new Date(Date.UTC(year, 10, 1));
    return new Date(Date.UTC(year, 10, 1 + (7 - d.getUTCDay()) % 7, 6));
  })();
  return now >= dstStart && now < dstEnd ? 4 : 5;
}

function isMarketOpen() {
  const now = new Date();
  const day = now.getUTCDay();
  if (day === 0 || day === 6) return false;
  const et = (now.getUTCHours() * 60 + now.getUTCMinutes() - getEtOffset(now) * 60 + 1440) % 1440;
  return et >= 570 && et < 960;
}

function getMarketCountdown() {
  const now = new Date();
  const off = getEtOffset(now) * 60 * 60 * 1000;
  const etNow = new Date(now.getTime() - off);
  const day = etNow.getUTCDay();
  const OPEN = 9 * 60 + 30, CLOSE = 16 * 60;
  const etMin = etNow.getUTCHours() * 60 + etNow.getUTCMinutes();
  const isWeekend = day === 0 || day === 6;
  const open = !isWeekend && etMin >= OPEN && etMin < CLOSE;
  let target;
  if (open) {
    target = new Date(Date.UTC(etNow.getUTCFullYear(), etNow.getUTCMonth(), etNow.getUTCDate(), 16, 0, 0)).getTime() + off;
  } else {
    let days = 0;
    if (!isWeekend && etMin < OPEN) { days = 0; }
    else { let d = day; do { days++; d = (d + 1) % 7; } while (d === 0 || d === 6); }
    target = new Date(Date.UTC(etNow.getUTCFullYear(), etNow.getUTCMonth(), etNow.getUTCDate() + days, 9, 30, 0)).getTime() + off;
  }
  const sec = Math.max(0, Math.floor((target - now.getTime()) / 1000));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const p = n => String(n).padStart(2, '0');
  return { open, label: `${p(h)}:${p(m)}:${p(s)}` };
}

// ── Formatters ────────────────────────────────────────────────────────────────

const fmt = (v, d = 1) => v == null ? '—' : Number(v).toFixed(d);
const fmtK = v => {
  if (v == null) return '—';
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(0)}K`;
  return String(v);
};
const fmtAge = iso => {
  if (!iso) return '';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
};

// ── Shared micro-components ───────────────────────────────────────────────────

function TierBadge({ tier, small }) {
  const m = TIER_META[tier] || TIER_META.SKIP;
  return (
    <span style={{
      display: 'inline-block', padding: small ? '1px 5px' : '2px 7px', borderRadius: 4,
      fontSize: small ? 9 : 10, fontWeight: 700, letterSpacing: '0.06em',
      color: m.color, background: m.bg, border: `1px solid ${m.color}40`,
    }}>{m.label}</span>
  );
}

function AtsBadge({ signal }) {
  const m = ATS_META[signal] || ATS_META.ATS_NONE;
  if (signal === 'ATS_NONE') return <span style={{ color: 'var(--ink-faint)', fontSize: 10 }}>—</span>;
  return (
    <span style={{
      display: 'inline-block', padding: '2px 6px', borderRadius: 4,
      fontSize: 10, fontWeight: 700, color: m.color,
      background: `${m.color}18`, border: `1px solid ${m.color}40`,
    }}>{m.label}</span>
  );
}

function ScoreBar({ score, max = 20, width = 60 }) {
  const pct = Math.min(100, (score / max) * 100);
  const color = score >= 13 ? 'var(--pos)' : score >= 9 ? 'var(--pump-blue)' : score >= 6 ? 'var(--warn)' : 'var(--ink-dim)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width, height: 4, background: 'var(--bg-3)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>
        {fmt(score, 1)}
      </span>
    </div>
  );
}

function ReadinessBadge({ tier, score }) {
  const m = READINESS_META[tier] || READINESS_META.COLD;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 3,
      padding: '1px 6px', borderRadius: 4, fontSize: 9, fontWeight: 700,
      color: m.color, background: m.bg, border: `1px solid ${m.color}40`,
    }}>
      {m.label}{score != null && <span style={{ opacity: 0.7 }}>{score}</span>}
    </span>
  );
}

// ── TOP PICK CARD ─────────────────────────────────────────────────────────────

function TopPickCard({ r, livePrice, journaled, adding, added, onAdd, onClick }) {
  const tier = TIER_META[r.demand_composite_tier] || TIER_META.SKIP;
  const price = livePrice?.price ?? r.price;
  const chg = livePrice?.change_pct;
  const topReasons = (r.demand_buy_reasons || []).slice(0, 4);

  return (
    <div
      onClick={() => onClick(r)}
      style={{
        minWidth: 200, maxWidth: 220, background: 'var(--bg-1)',
        border: `1px solid ${tier.color}40`, borderRadius: 'var(--r-xl)',
        padding: '14px 16px', cursor: 'pointer', flexShrink: 0,
        transition: 'border-color 0.15s, transform 0.1s',
        position: 'relative',
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = tier.color; e.currentTarget.style.transform = 'translateY(-2px)'; }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = `${tier.color}40`; e.currentTarget.style.transform = 'none'; }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--ink)', fontFamily: 'var(--f-mono)', letterSpacing: '-0.5px' }}>
            {r.symbol}
          </div>
          <TierBadge tier={r.demand_composite_tier} />
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 20, fontWeight: 800, color: tier.color, lineHeight: 1 }}>
            {fmt(r.demand_composite_score, 1)}
          </div>
          <div style={{ fontSize: 8, color: 'var(--ink-dim)', textTransform: 'uppercase', letterSpacing: '0.07em' }}>/ 20</div>
        </div>
      </div>

      {/* Score bar */}
      <div style={{ marginBottom: 10 }}>
        <ScoreBar score={r.demand_composite_score} width={80} />
      </div>

      {/* Price */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 8 }}>
        <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--ink)', fontVariantNumeric: 'tabular-nums' }}>
          ${fmt(price, 2)}
        </span>
        {chg != null && (
          <span style={{ fontSize: 12, fontWeight: 600, color: chg >= 0 ? 'var(--pos)' : 'var(--neg)' }}>
            {chg >= 0 ? '+' : ''}{chg.toFixed(2)}%
          </span>
        )}
        {livePrice && (
          <span style={{ fontSize: 9, color: 'var(--pos)', marginLeft: 2 }}>●</span>
        )}
      </div>

      {/* ATS + Readiness */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        <AtsBadge signal={r.ats_signal} />
        {r.readiness_tier && <ReadinessBadge tier={r.readiness_tier} score={r.readiness_score} />}
      </div>

      {/* Signals */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginBottom: 10, minHeight: 20 }}>
        {topReasons.map(rr => (
          <span key={rr} style={{
            fontSize: 8, padding: '1px 4px', borderRadius: 3,
            background: 'var(--pump-blue-soft)', color: 'var(--pump-blue)',
            border: '1px solid oklch(0.74 0.12 268 / 0.25)',
          }}>{REASONS_PRETTY[rr] || rr}</span>
        ))}
      </div>

      {/* Footer: vol + sector + journal */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--stroke-soft)', paddingTop: 8 }}>
        <div style={{ fontSize: 9, color: 'var(--ink-dim)' }}>
          <span style={{ marginRight: 6 }}>Vol {fmtK(r.volume_today)}</span>
          {r.sector && <span style={{ color: 'var(--ink-faint)' }}>{r.sector?.split(' ').slice(-1)[0]}</span>}
        </div>
        {(journaled || added) ? (
          <span style={{ fontSize: 9, color: 'var(--pos)', fontWeight: 700 }}>✓ Journaled</span>
        ) : (
          <button
            onClick={e => { e.stopPropagation(); onAdd(r); }}
            disabled={adding}
            style={{
              background: 'var(--pump-lime)', border: 'none',
              color: 'var(--on-lime)', borderRadius: 4, padding: '2px 7px',
              fontSize: 9, fontWeight: 600, cursor: adding ? 'not-allowed' : 'pointer',
            }}
          >{adding ? '…' : '+ Journal'}</button>
        )}
      </div>
    </div>
  );
}

// ── ATS PANEL ─────────────────────────────────────────────────────────────────

function AtsPanel({ results }) {
  const prime = results.filter(r => r.ats_signal === 'ATS_PRIME').slice(0, 8);
  const setup = results.filter(r => r.ats_signal === 'ATS_SETUP').slice(0, 6);
  return (
    <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 10, padding: '14px 16px', height: '100%' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--pump-blue)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 12 }}>
        ATS Signals
      </div>
      {prime.length > 0 && (
        <>
          <div style={{ fontSize: 9, color: 'var(--pos)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6, fontWeight: 700 }}>
            ★★★ PRIME ({prime.length})
          </div>
          {prime.map(r => (
            <div key={r.symbol} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5, padding: '3px 0', borderBottom: '1px solid var(--stroke-soft)' }}>
              <span style={{ fontFamily: 'var(--f-mono)', fontWeight: 700, color: 'var(--ink)', fontSize: 12 }}>{r.symbol}</span>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span style={{ fontSize: 10, color: 'var(--pos)', fontVariantNumeric: 'tabular-nums' }}>{fmt(r.demand_composite_score, 1)}</span>
                <TierBadge tier={r.demand_composite_tier} small />
              </div>
            </div>
          ))}
        </>
      )}
      {setup.length > 0 && (
        <>
          <div style={{ fontSize: 9, color: 'var(--pump-blue)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6, marginTop: 10, fontWeight: 700 }}>
            ★★ SETUP ({setup.length})
          </div>
          {setup.map(r => (
            <div key={r.symbol} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5, padding: '3px 0', borderBottom: '1px solid var(--stroke-soft)' }}>
              <span style={{ fontFamily: 'var(--f-mono)', fontWeight: 700, color: 'var(--ink-mute)', fontSize: 12 }}>{r.symbol}</span>
              <span style={{ fontSize: 10, color: 'var(--pump-blue)', fontVariantNumeric: 'tabular-nums' }}>{fmt(r.demand_composite_score, 1)}</span>
            </div>
          ))}
        </>
      )}
      {prime.length === 0 && setup.length === 0 && (
        <div style={{ color: 'var(--ink-faint)', fontSize: 11, textAlign: 'center', paddingTop: 20 }}>No ATS signals in current scan</div>
      )}
    </div>
  );
}

// ── SECTOR HEATMAP ────────────────────────────────────────────────────────────

const SECTOR_ABBR = {
  'Technology': 'Tech',
  'Healthcare': 'Health',
  'Financial Services': 'Finance',
  'Consumer Cyclical': 'Consumer Cyc',
  'Communication Services': 'Comm',
  'Industrials': 'Industrials',
  'Consumer Defensive': 'Consumer Def',
  'Energy': 'Energy',
  'Utilities': 'Utilities',
  'Real Estate': 'Real Estate',
  'Basic Materials': 'Materials',
};

function SectorHeatmap({ sectors }) {
  const entries = Object.entries(sectors || {})
    .map(([name, d]) => ({ name, chg: d.change_1d ?? d.pct_change_1d ?? 0, rank: d.rank_1d ?? 99 }))
    .sort((a, b) => b.chg - a.chg);

  if (entries.length === 0) {
    return (
      <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 10, padding: '14px 16px', height: '100%' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ink-mute)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 12 }}>Sectors</div>
        <div style={{ color: 'var(--ink-faint)', fontSize: 11, textAlign: 'center', paddingTop: 20 }}>Loading sectors…</div>
      </div>
    );
  }

  const maxAbs = Math.max(...entries.map(e => Math.abs(e.chg)), 1);

  return (
    <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 10, padding: '14px 16px', height: '100%' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ink-mute)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 12 }}>Sector Performance</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
        {entries.map(({ name, chg }) => {
          const color = chg > 0.5 ? 'var(--pos)' : chg > 0 ? 'var(--pos)' : chg > -0.5 ? 'var(--warn)' : 'var(--neg)';
          const barW = Math.abs(chg) / maxAbs * 100;
          const abbr = SECTOR_ABBR[name] || name.split(' ')[0];
          return (
            <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 80, fontSize: 10, color: 'var(--ink-mute)', textAlign: 'right', flexShrink: 0 }}>{abbr}</div>
              <div style={{ flex: 1, height: 14, background: 'var(--bg-3)', borderRadius: 3, overflow: 'hidden', position: 'relative' }}>
                <div style={{
                  position: 'absolute',
                  [chg >= 0 ? 'left' : 'right']: 0,
                  width: `${barW}%`, height: '100%',
                  background: color, opacity: 0.7, borderRadius: 3,
                }} />
              </div>
              <div style={{ width: 46, textAlign: 'right', fontSize: 11, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>
                {chg >= 0 ? '+' : ''}{chg.toFixed(2)}%
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── GAINERS / LOSERS ──────────────────────────────────────────────────────────

function GainersLosers({ livePrices, results, marketOpen }) {
  const [tab, setTab] = useState('gainers');

  const enriched = Object.entries(livePrices)
    .filter(([, d]) => d.change_pct != null)
    .map(([sym, d]) => {
      const r = results.find(rr => rr.symbol === sym);
      return { symbol: sym, price: d.price, chg: d.change_pct, tier: r?.demand_composite_tier };
    });

  const gainers = [...enriched].sort((a, b) => b.chg - a.chg).slice(0, 8);
  const losers  = [...enriched].sort((a, b) => a.chg - b.chg).slice(0, 8);
  const list = tab === 'gainers' ? gainers : losers;

  return (
    <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 10, padding: '14px 16px', height: '100%' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
        {['gainers', 'losers'].map(t => (
          <button key={t} onClick={() => setTab(t)} style={{
            background: tab === t ? (t === 'gainers' ? 'oklch(0.86 0.18 142 / 0.15)' : 'oklch(0.72 0.21 25 / 0.15)') : 'none',
            border: `1px solid ${tab === t ? (t === 'gainers' ? 'var(--pos)' : 'var(--neg)') : 'var(--stroke)'}`,
            color: tab === t ? (t === 'gainers' ? 'var(--pos)' : 'var(--neg)') : 'var(--ink-dim)',
            borderRadius: 6, padding: '3px 10px', fontSize: 10, fontWeight: 700,
            cursor: 'pointer', textTransform: 'uppercase', letterSpacing: '0.06em',
          }}>{t === 'gainers' ? '▲ Gainers' : '▼ Losers'}</button>
        ))}
        {!marketOpen && <span style={{ fontSize: 9, color: 'var(--ink-faint)', marginLeft: 'auto' }}>Market closed</span>}
        {marketOpen && list.length === 0 && <span style={{ fontSize: 9, color: 'var(--ink-faint)', marginLeft: 'auto' }}>Loading prices…</span>}
      </div>
      {list.length === 0 && marketOpen && (
        <div style={{ color: 'var(--ink-faint)', fontSize: 11, textAlign: 'center', paddingTop: 16 }}>
          Fetching live prices…
        </div>
      )}
      {!marketOpen && (
        <div style={{ color: 'var(--ink-faint)', fontSize: 11, textAlign: 'center', paddingTop: 16 }}>
          Live data available during market hours (9:30–16:00 ET)
        </div>
      )}
      {list.map(({ symbol, price, chg, tier }) => (
        <div key={symbol} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, padding: '4px 0', borderBottom: '1px solid var(--stroke-soft)' }}>
          <span style={{ fontFamily: 'var(--f-mono)', fontWeight: 700, color: 'var(--ink)', fontSize: 12, minWidth: 44 }}>{symbol}</span>
          {tier && <TierBadge tier={tier} small />}
          <span style={{ marginLeft: 'auto', fontSize: 12, fontWeight: 700, color: chg >= 0 ? 'var(--pos)' : 'var(--neg)', fontVariantNumeric: 'tabular-nums' }}>
            {chg >= 0 ? '+' : ''}{chg.toFixed(2)}%
          </span>
          <span style={{ fontSize: 11, color: 'var(--ink-mute)', fontVariantNumeric: 'tabular-nums' }}>
            ${fmt(price, 2)}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── NEWS FEED ─────────────────────────────────────────────────────────────────

function NewsFeed({ articles, loading }) {
  if (loading) {
    return (
      <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 10, padding: '14px 16px' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ink-mute)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 12 }}>Market News</div>
        <div style={{ color: 'var(--ink-faint)', fontSize: 11 }}>Loading news…</div>
      </div>
    );
  }
  if (!articles?.length) {
    return (
      <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 10, padding: '14px 16px' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ink-mute)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 12 }}>Market News</div>
        <div style={{ color: 'var(--ink-faint)', fontSize: 11 }}>No news available for current top picks</div>
      </div>
    );
  }

  return (
    <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 10, padding: '14px 16px' }}>
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ink-mute)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 12 }}>
        Market News — Top Picks
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 10 }}>
        {articles.slice(0, 12).map((a, i) => {
          const tickers = (a.tickers || []).slice(0, 4);
          const src = a.publisher?.name || a.source || '';
          const age = fmtAge(a.published_utc);
          return (
            <a
              key={a.id || i}
              href={a.article_url || '#'}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'block', textDecoration: 'none',
                background: 'var(--bg-2)', border: '1px solid var(--stroke-soft)', borderRadius: 8,
                padding: '10px 12px', transition: 'border-color 0.15s, background 0.15s',
              }}
              onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-3)'; e.currentTarget.style.borderColor = 'var(--pump-blue)'; }}
              onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-2)'; e.currentTarget.style.borderColor = 'var(--stroke-soft)'; }}
            >
              <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--ink)', lineHeight: 1.4, marginBottom: 6 }}>
                {a.title}
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                {tickers.map(t => (
                  <span key={t} style={{ fontSize: 9, fontFamily: 'var(--f-mono)', color: 'var(--pump-blue)', fontWeight: 700 }}>{t}</span>
                ))}
                {src && <span style={{ fontSize: 9, color: 'var(--ink-faint)', marginLeft: 'auto' }}>{src}</span>}
                {age && <span style={{ fontSize: 9, color: 'var(--ink-faint)' }}>{age}</span>}
              </div>
            </a>
          );
        })}
      </div>
    </div>
  );
}

// ── HYPE STRIP ────────────────────────────────────────────────────────────────

function HypeStrip({ hypeStatus, hypeResults }) {
  const hot = (hypeStatus?.hot_tickers || []).slice(0, 10);
  if (!hot.length && !hypeStatus) return null;
  return (
    <div style={{
      background: 'var(--bg-1)', border: '1px solid var(--pump-blue-soft)',
      borderRadius: 10, padding: '10px 16px',
      display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
    }}>
      <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--pump-blue)', textTransform: 'uppercase', letterSpacing: '0.07em', flexShrink: 0 }}>
        Hype Monitor
      </span>
      {hot.map(t => (
        <span key={t} style={{
          fontFamily: 'var(--f-mono)', fontWeight: 700, fontSize: 11, color: 'var(--pump-blue)',
          background: 'var(--pump-blue-soft)', border: '1px solid oklch(0.74 0.12 268 / 0.35)',
          borderRadius: 4, padding: '1px 6px',
        }}>{t}</span>
      ))}
      {hypeStatus?.total_divergences > 0 && (
        <span style={{ fontSize: 10, color: 'var(--ink-dim)', marginLeft: 4 }}>
          {hypeStatus.total_divergences} signals · {hypeStatus.tickers_monitored} monitored
        </span>
      )}
      {hypeStatus?.last_run_at && (
        <span style={{ fontSize: 9, color: 'var(--ink-faint)', marginLeft: 'auto' }}>
          {fmtAge(hypeStatus.last_run_at)}
        </span>
      )}
    </div>
  );
}

// ── MARKET CONTEXT BAR ────────────────────────────────────────────────────────

function MarketContextBar({ marketTimer, regime, livePrices, marketOpen }) {
  const regimeState = regime?.regime_state || regime?.state;
  const regimeColor = REGIME_COLORS[regimeState] || '#9ca3af';
  const liveCount = Object.keys(livePrices).length;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', flexWrap: 'wrap',
      background: 'var(--bg-1)', borderBottom: '1px solid var(--stroke-soft)', fontSize: 11,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 16px', borderRight: '1px solid var(--stroke-soft)' }}>
        <span style={{
          width: 7, height: 7, borderRadius: '50%', display: 'inline-block',
          background: marketOpen ? 'var(--pos)' : 'var(--ink-dim)',
          boxShadow: marketOpen ? '0 0 6px var(--pos)' : 'none',
        }} />
        <span style={{ color: marketOpen ? 'var(--pos)' : 'var(--ink-mute)', fontWeight: 700, letterSpacing: '0.05em' }}>
          {marketOpen ? 'MARKET OPEN' : 'MARKET CLOSED'}
        </span>
        <span style={{ color: 'var(--ink-faint)', fontVariantNumeric: 'tabular-nums' }}>{marketTimer.label}</span>
      </div>
      {regimeState && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px', borderRight: '1px solid var(--stroke-soft)' }}>
          <span style={{ color: 'var(--ink-dim)', textTransform: 'uppercase', letterSpacing: '0.07em', fontSize: 10 }}>Regime</span>
          <span style={{ color: regimeColor, fontWeight: 700 }}>{regimeState.replace(/_/g, ' ')}</span>
        </div>
      )}
      {marketOpen && liveCount > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '7px 14px' }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--pos)', display: 'inline-block', animation: 'pulse 1.5s infinite' }} />
          <span style={{ color: 'var(--pos)', fontSize: 10 }}>Live · {liveCount} tickers · 30s</span>
        </div>
      )}
    </div>
  );
}

// ── DRAWER (full detail) ──────────────────────────────────────────────────────

function ScoreHistory({ symbol }) {
  const [hist, setHist] = useState([]);
  useEffect(() => {
    if (!symbol) return;
    fetch(`${API_URL}/api/demand-scanner/history/${symbol}?limit=20`)
      .then(r => r.json()).then(d => setHist((d.history || []).reverse())).catch(() => {});
  }, [symbol]);
  if (hist.length < 2) return null;
  const maxScore = Math.max(...hist.map(h => h.combined_score || 0), 10);
  const W = 280, H = 44, pad = 4;
  const pts = hist.map((h, i) => {
    const x = pad + (i / (hist.length - 1)) * (W - pad * 2);
    const y = H - pad - ((h.combined_score || 0) / maxScore) * (H - pad * 2);
    return [x, y, h];
  });
  const pathD = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  return (
    <div style={{ marginTop: 6 }}>
      <svg width={W} height={H} style={{ display: 'block', overflow: 'visible' }}>
        <path d={pathD} fill="none" stroke="var(--stroke)" strokeWidth={1.5} />
        {pts.map(([x, y, h], i) => (
          <circle key={i} cx={x} cy={y} r={3}
            fill={TIER_COLORS_MINI[h.demand_composite_tier] || '#374151'}
            title={`${h.scanned_at?.slice(0,10)} ${h.combined_score}`}
          />
        ))}
      </svg>
    </div>
  );
}

function ScoreBreakdown({ bd = {} }) {
  const items = [
    { key: 'regime', label: 'Regime', color: 'var(--pump-blue)' },
    { key: 'base_pump', label: 'NP', color: 'var(--pump-blue)' },
    { key: 'demand_bars', label: 'Demand', color: 'var(--pos)' },
    { key: 'ats', label: 'ATS', color: 'var(--warn)' },
    { key: 'context', label: 'Context', color: 'var(--pump-lime)' },
    { key: 'flow', label: 'Flow', color: 'var(--pump-blue)' },
    { key: 'expansion_penalty', label: 'ExpPen', color: 'var(--neg)' },
  ];
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 6 }}>
      {items.filter(i => bd[i.key] != null && bd[i.key] !== 0).map(i => (
        <div key={i.key} style={{ textAlign: 'center', minWidth: 32 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: bd[i.key] < 0 ? 'var(--neg)' : i.color }}>
            {bd[i.key] > 0 ? '+' : ''}{fmt(bd[i.key], 1)}
          </div>
          <div style={{ fontSize: 8, color: 'var(--ink-dim)', textTransform: 'uppercase' }}>{i.label}</div>
        </div>
      ))}
    </div>
  );
}

function ReadinessBreakdown({ bd = {}, breakoutSignal, freshness, rsPct, floatTier, catalyst, confluenceSignals = [] }) {
  const bm = BREAKOUT_META[breakoutSignal] || BREAKOUT_META.COILING;
  const items = [
    { key: 'catalyst', label: 'Cat', color: 'var(--pump-blue)' },
    { key: 'breakout', label: 'BO', color: 'var(--pos)' },
    { key: 'float', label: 'Float', color: 'var(--pump-blue)' },
    { key: 'freshness', label: 'Fresh', color: 'var(--warn)' },
    { key: 'rs', label: 'RS', color: 'var(--pump-lime)' },
    { key: 'confluence', label: 'Conf', color: 'var(--pos)' },
  ];
  return (
    <div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
        {items.map(i => (
          <div key={i.key} style={{ textAlign: 'center', minWidth: 36 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: (bd[i.key] ?? 0) < 0 ? 'var(--neg)' : i.color }}>
              {(bd[i.key] ?? 0) > 0 ? '+' : ''}{bd[i.key] ?? 0}
            </div>
            <div style={{ fontSize: 8, color: 'var(--ink-dim)', textTransform: 'uppercase' }}>{i.label}</div>
          </div>
        ))}
      </div>
      {confluenceSignals.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 6 }}>
          {confluenceSignals.map(sig => {
            const m = CONFLUENCE_META[sig] || { label: sig, color: 'var(--ink-mute)' };
            return (
              <span key={sig} style={{ background: 'oklch(0.86 0.18 142 / 0.10)', border: `1px solid ${m.color}`, color: m.color, borderRadius: 4, padding: '1px 5px', fontSize: 9, fontWeight: 700 }}>{m.label}</span>
            );
          })}
        </div>
      )}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, fontSize: 10 }}>
        <span style={{ color: bm.color, fontWeight: 600 }}>{bm.label}</span>
        {freshness && <span style={{ color: FRESHNESS_COLORS[freshness] || 'var(--ink-mute)' }}>{freshness}</span>}
        {rsPct != null && <span style={{ color: rsPct > 0 ? 'var(--pos)' : 'var(--neg)' }}>RS {rsPct > 0 ? '+' : ''}{rsPct}%</span>}
        {floatTier && floatTier !== 'UNKNOWN' && <span style={{ color: 'var(--ink-mute)' }}>Float: {floatTier.replace('_PROXY', '~')}</span>}
        {catalyst && <span style={{ color: 'var(--pump-blue)' }}>Catalyst ✓</span>}
      </div>
    </div>
  );
}

function DetailDrawer({ row, onClose, narrative, narrativeLoading, onFetchNarrative }) {
  if (!row) return null;
  const tier = TIER_META[row.demand_composite_tier] || TIER_META.SKIP;
  return (
    <div style={{
      position: 'fixed', right: 0, top: 0, bottom: 0, width: 420,
      background: 'var(--bg-1)', borderLeft: '1px solid var(--stroke-soft)',
      zIndex: 1000, overflowY: 'auto', padding: 20,
      boxShadow: '-8px 0 32px rgba(0,0,0,0.5)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--ink)' }}>{row.symbol}</div>
          <div style={{ fontSize: 12, color: 'var(--ink-mute)', marginTop: 2 }}>${fmt(row.price, 2)} · {row.sector || '—'}</div>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: '1px solid var(--stroke)', color: 'var(--ink-mute)', borderRadius: 6, padding: '4px 10px', cursor: 'pointer', fontSize: 12 }}>Close</button>
      </div>

      <div style={{ background: tier.bg, border: `1px solid ${tier.color}40`, borderRadius: 8, padding: '12px 16px', marginBottom: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <TierBadge tier={row.demand_composite_tier} />
          <div style={{ fontSize: 28, fontWeight: 800, color: tier.color }}>{fmt(row.demand_composite_score, 1)}<span style={{ fontSize: 14, opacity: 0.5 }}>/20</span></div>
        </div>
        <ScoreBreakdown bd={row.demand_score_breakdown || {}} />
      </div>

      <div style={{ background: 'var(--bg-2)', borderRadius: 8, padding: '10px 12px', marginBottom: 12 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--ink-mute)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.07em' }}>Score History</div>
        <ScoreHistory symbol={row.symbol} />
      </div>

      {row.readiness_tier && (
        <div style={{ background: READINESS_META[row.readiness_tier]?.bg || 'rgba(107,114,128,0.08)', border: `1px solid ${READINESS_META[row.readiness_tier]?.color || '#6b7280'}40`, borderRadius: 8, padding: '12px 14px', marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: '#9ca3af', textTransform: 'uppercase', letterSpacing: '0.07em' }}>Trigger Readiness</div>
            <ReadinessBadge tier={row.readiness_tier} score={row.readiness_score} />
          </div>
          <ReadinessBreakdown bd={row.readiness_breakdown || {}} breakoutSignal={row.breakout_signal} freshness={row.freshness_label} rsPct={row.rs_during_dryup_pct} floatTier={row.float_proxy_tier} catalyst={row.catalyst_proxy} confluenceSignals={row.confluence_signals || []} />
        </div>
      )}

      {((row.flow_signals?.length > 0) || (row.flow_risks?.length > 0)) && (
        <div style={{ background: 'var(--bg-2)', borderRadius: 8, padding: '10px 12px', marginBottom: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--ink-mute)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.07em' }}>Flow Divergence</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {(row.flow_signals || []).map(sig => { const m = FLOW_SIGNAL_META[sig] || { label: sig, color: 'var(--pump-blue)' }; return <span key={sig} title={m.title} style={{ background: 'var(--pump-blue-soft)', border: `1px solid ${m.color}`, color: m.color, borderRadius: 4, padding: '1px 5px', fontSize: 9, fontWeight: 700 }}>{m.label}</span>; })}
            {(row.flow_risks || []).map(r => { const m = FLOW_RISK_META[r] || { label: r, color: 'var(--neg)' }; return <span key={r} title={m.title} style={{ background: 'oklch(0.72 0.21 25 / 0.08)', border: `1px solid ${m.color}`, color: m.color, borderRadius: 4, padding: '1px 5px', fontSize: 9, fontWeight: 700 }}>{m.label}</span>; })}
          </div>
        </div>
      )}

      <div style={{ background: 'var(--bg-2)', borderRadius: 8, padding: '10px 12px', marginBottom: 12 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--ink-mute)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.07em' }}>ATS Signal</div>
        <AtsBadge signal={row.ats_signal} />
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 5 }}>
          {(row.ats_conditions_met || []).map(c => <span key={c} style={{ fontSize: 9, padding: '1px 4px', borderRadius: 3, background: 'oklch(0.86 0.18 142 / 0.12)', color: 'var(--pos)', border: '1px solid oklch(0.86 0.18 142 / 0.25)' }}>{ATS_COND_PRETTY[c] || c}</span>)}
          {(row.ats_conditions_missing || []).map(c => <span key={c} style={{ fontSize: 9, padding: '1px 4px', borderRadius: 3, background: 'oklch(0.72 0.21 25 / 0.08)', color: 'var(--neg)', border: '1px solid oklch(0.72 0.21 25 / 0.2)' }}>{ATS_COND_PRETTY[c] || c}</span>)}
        </div>
      </div>

      <div style={{ background: 'var(--bg-2)', borderRadius: 8, padding: '10px 12px', marginBottom: 12 }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--ink-mute)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.07em' }}>Active Signals</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3 }}>
          {(row.demand_buy_reasons || []).slice(0, 8).map(r => <span key={r} style={{ fontSize: 9, padding: '1px 4px', borderRadius: 3, background: 'var(--pump-blue-soft)', color: 'var(--pump-blue)', border: '1px solid oklch(0.74 0.12 268 / 0.25)' }}>{REASONS_PRETTY[r] || r}</span>)}
        </div>
        {(row.demand_risk_flags || []).length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 5 }}>
            {row.demand_risk_flags.map(f => <span key={f} style={{ fontSize: 9, padding: '1px 4px', borderRadius: 3, background: 'oklch(0.72 0.21 25 / 0.08)', color: 'var(--neg)', border: '1px solid oklch(0.72 0.21 25 / 0.2)' }}>{f}</span>)}
          </div>
        )}
      </div>

      {[
        ['Dryup streak', `${row.dc_dryup_streak ?? '—'} days`], ['ATR contract', row.dc_atr_contracting ? 'Yes' : 'No'],
        ['Near EMA50', row.dc_near_ema50 ? 'Yes' : 'No'], ['EMA50 dist', row.dc_ema_dist_pct != null ? `${row.dc_ema_dist_pct}%` : '—'],
        ['Vol ratio', row.dc_vol_ratio != null ? `${row.dc_vol_ratio}×` : '—'], ['5d range', row.dc_range_pct_5d != null ? `${row.dc_range_pct_5d}%` : '—'],
        ['10d max gain', row.dc_max_gain_10d != null ? `${row.dc_max_gain_10d}%` : '—'],
      ].length > 0 && (
        <div style={{ background: 'var(--bg-2)', borderRadius: 8, padding: '10px 12px', marginBottom: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--ink-mute)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.07em' }}>Candle Metrics</div>
          {[
            ['Dryup streak', `${row.dc_dryup_streak ?? '—'}d`], ['ATR contract', row.dc_atr_contracting ? '✓' : '—'],
            ['Near EMA50', row.dc_near_ema50 ? '✓' : '—'], ['EMA50 dist', row.dc_ema_dist_pct != null ? `${row.dc_ema_dist_pct}%` : '—'],
            ['Vol ratio', row.dc_vol_ratio != null ? `${row.dc_vol_ratio}×` : '—'], ['10d max gain', row.dc_max_gain_10d != null ? `${row.dc_max_gain_10d}%` : '—'],
          ].map(([label, val]) => (
            <div key={label} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
              <span style={{ fontSize: 11, color: 'var(--ink-mute)' }}>{label}</span>
              <span style={{ fontSize: 11, color: 'var(--ink)', fontVariantNumeric: 'tabular-nums' }}>{val}</span>
            </div>
          ))}
        </div>
      )}

      <div style={{ background: 'var(--bg-2)', border: '1px solid var(--pump-blue-soft)', borderRadius: 8, padding: '10px 12px' }}>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--pump-blue)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.07em' }}>AI Setup Analysis</div>
        {!narrative && !narrativeLoading && (
          <button onClick={() => onFetchNarrative(row)} style={{ background: 'var(--pump-lime)', color: 'var(--on-lime)', border: 'none', borderRadius: 6, padding: '7px 14px', fontSize: 11, fontWeight: 600, cursor: 'pointer', width: '100%' }}>
            Generate AI Analysis
          </button>
        )}
        {narrativeLoading && <div style={{ color: 'var(--ink-mute)', fontSize: 11, textAlign: 'center', padding: '8px 0' }}>Generating…</div>}
        {narrative && <p style={{ fontSize: 12, color: 'var(--ink-mute)', lineHeight: 1.7, margin: 0 }}>{narrative}</p>}
      </div>
    </div>
  );
}

// ── FULL SCANNER TABLE ────────────────────────────────────────────────────────

function ScannerTable({ results, livePrices, journaledSet, addingJournal, addedJournal, onAddToJournal, onRowClick, tierF, setTierF, atsF, setAtsF, readyF, setReadyF, minScore, setMinScore, limit, setLimit, onRefresh, triggerScan, scanning, scanProgress, scanError }) {
  const [sortCol, setSortCol] = useState('demand_composite_score');
  const [sortDir, setSortDir] = useState('desc');

  const filtered = readyF ? results.filter(r => r.readiness_tier === readyF) : results;
  const sorted = [...filtered].sort((a, b) => {
    const av = a[sortCol] ?? 0, bv = b[sortCol] ?? 0;
    if (sortCol === 'symbol') return sortDir === 'asc' ? String(av).localeCompare(String(bv)) : String(bv).localeCompare(String(av));
    return sortDir === 'asc' ? av - bv : bv - av;
  });

  const toggleSort = col => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortCol(col); setSortDir('desc'); }
  };

  const Th = ({ col, label }) => (
    <th onClick={() => toggleSort(col)} style={{
      padding: '7px 8px', textAlign: 'left', fontSize: 9, fontWeight: 700,
      textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--ink-dim)',
      cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap',
      borderBottom: '1px solid var(--stroke-soft)',
    }}>
      {label}{sortCol === col ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
    </th>
  );

  const selStyle = { background: 'var(--bg-2)', color: 'var(--ink)', border: '1px solid var(--stroke)', borderRadius: 5, padding: '4px 8px', fontSize: 11 };

  return (
    <div>
      {/* Controls */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', padding: '10px 0 14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <label style={{ fontSize: 11, color: 'var(--ink-mute)' }}>Tier</label>
          <select value={tierF} onChange={e => setTierF(e.target.value)} style={selStyle}>
            <option value="">All</option>
            {Object.entries(TIER_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <label style={{ fontSize: 11, color: 'var(--ink-mute)' }}>ATS</label>
          <select value={atsF} onChange={e => setAtsF(e.target.value)} style={selStyle}>
            <option value="">All</option>
            {Object.entries(ATS_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <label style={{ fontSize: 11, color: 'var(--ink-mute)' }}>Ready</label>
          <select value={readyF} onChange={e => setReadyF(e.target.value)} style={selStyle}>
            <option value="">All</option>
            {Object.entries(READINESS_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <label style={{ fontSize: 11, color: 'var(--ink-mute)' }}>Min</label>
          <input type="number" min={0} max={20} step={0.5} value={minScore} onChange={e => setMinScore(Number(e.target.value))}
            style={{ width: 50, ...selStyle }} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <label style={{ fontSize: 11, color: 'var(--ink-mute)' }}>Limit</label>
          <select value={limit} onChange={e => setLimit(Number(e.target.value))} style={selStyle}>
            {[50, 100, 200, 500].map(n => <option key={n} value={n}>{n}</option>)}
          </select>
        </div>
        <button onClick={onRefresh} style={{ background: 'var(--pump-lime)', color: 'var(--on-lime)', border: 'none', borderRadius: 6, padding: '5px 12px', fontSize: 11, fontWeight: 600, cursor: 'pointer' }}>Refresh</button>
        <button onClick={triggerScan} disabled={scanning} style={{
          background: scanning ? 'var(--bg-3)' : 'oklch(0.86 0.18 142 / 0.15)', color: scanning ? 'var(--ink-dim)' : 'var(--pos)',
          border: `1px solid ${scanning ? 'var(--stroke)' : 'var(--pos)'}`, borderRadius: 6, padding: '5px 12px', fontSize: 11, fontWeight: 600, cursor: scanning ? 'not-allowed' : 'pointer',
        }}>{scanning ? 'Scanning…' : 'Scan Today'}</button>
        <span style={{ fontSize: 11, color: 'var(--ink-dim)', marginLeft: 'auto' }}>{sorted.length} results</span>
      </div>

      {scanning && scanProgress && (
        <div style={{ background: 'var(--bg-2)', border: '1px solid var(--pump-blue-soft)', borderRadius: 8, padding: '8px 14px', marginBottom: 8, display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 11, color: 'var(--pump-blue)' }}>
          <span style={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--pump-blue)' }}>{scanProgress.phase?.replace(/_/g, ' ')}</span>
          {scanProgress.universe_size > 0 && <span>Universe: {scanProgress.universe_size.toLocaleString()}</span>}
          {scanProgress.analyzed_count > 0 && <span>Analyzed: {scanProgress.analyzed_count}</span>}
          {scanProgress.elapsed_secs > 0 && <span style={{ color: 'var(--ink-dim)' }}>{scanProgress.elapsed_secs}s</span>}
        </div>
      )}
      {scanError && <div style={{ padding: '6px 0', color: 'var(--neg)', fontSize: 11 }}>{scanError}</div>}

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <thead>
            <tr style={{ background: 'var(--bg-2)' }}>
              <Th col="symbol" label="Symbol" />
              <Th col="demand_composite_tier" label="Tier" />
              <Th col="demand_composite_score" label="Score" />
              <Th col="ats_signal" label="ATS" />
              <Th col="readiness_score" label="Ready" />
              <Th col="price" label="Price" />
              <Th col="volume_today" label="Volume" />
              <th style={{ padding: '7px 8px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--ink-dim)', borderBottom: '1px solid var(--stroke-soft)' }}>Demand Flags</th>
              <th style={{ padding: '7px 8px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--ink-dim)', borderBottom: '1px solid var(--stroke-soft)' }}>Context</th>
              <th style={{ padding: '7px 8px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--ink-dim)', borderBottom: '1px solid var(--stroke-soft)' }}>Sector</th>
              <th style={{ padding: '7px 8px', fontSize: 9, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.07em', color: 'var(--ink-dim)', borderBottom: '1px solid var(--stroke-soft)' }}>Journal</th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 && (
              <tr><td colSpan={11} style={{ padding: '20px', color: 'var(--ink-dim)', fontSize: 13, textAlign: 'center' }}>No results — run a scan or adjust filters</td></tr>
            )}
            {sorted.map(r => {
              const lp = livePrices[r.symbol];
              const price = lp?.price ?? r.price;
              const chg = lp?.change_pct;
              return (
                <tr key={r.symbol} onClick={() => onRowClick(r)} style={{ cursor: 'pointer', borderBottom: '1px solid var(--stroke-soft)' }}
                  onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-2)'}
                  onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                >
                  <td style={{ padding: '7px 10px', fontWeight: 700, color: 'var(--ink)', fontSize: 13, fontFamily: 'var(--f-mono)' }}>{r.symbol}</td>
                  <td style={{ padding: '7px 8px' }}><TierBadge tier={r.demand_composite_tier} /></td>
                  <td style={{ padding: '7px 8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                      <div style={{ width: 50, height: 4, background: 'var(--bg-3)', borderRadius: 2, overflow: 'hidden' }}>
                        <div style={{ width: `${Math.min(100, (r.demand_composite_score / 20) * 100)}%`, height: '100%', background: r.demand_composite_score >= 13 ? 'var(--pos)' : r.demand_composite_score >= 9 ? 'var(--pump-blue)' : 'var(--warn)', borderRadius: 2 }} />
                      </div>
                      <span style={{ fontSize: 11, fontWeight: 700, color: r.demand_composite_score >= 13 ? 'var(--pos)' : r.demand_composite_score >= 9 ? 'var(--pump-blue)' : 'var(--warn)', fontVariantNumeric: 'tabular-nums' }}>{fmt(r.demand_composite_score, 1)}</span>
                    </div>
                  </td>
                  <td style={{ padding: '7px 8px' }}><AtsBadge signal={r.ats_signal} /></td>
                  <td style={{ padding: '7px 8px' }}>
                    {r.readiness_tier ? <ReadinessBadge tier={r.readiness_tier} score={r.readiness_score} /> : <span style={{ color: 'var(--stroke)', fontSize: 10 }}>—</span>}
                  </td>
                  <td style={{ padding: '7px 8px', fontSize: 11, fontVariantNumeric: 'tabular-nums' }}>
                    <span style={{ color: 'var(--ink)' }}>${fmt(price, 2)}</span>
                    {chg != null && <span style={{ marginLeft: 4, fontSize: 10, color: chg >= 0 ? 'var(--pos)' : 'var(--neg)' }}>{chg >= 0 ? '+' : ''}{chg.toFixed(1)}%</span>}
                  </td>
                  <td style={{ padding: '7px 8px', fontSize: 11, color: 'var(--ink-mute)', fontVariantNumeric: 'tabular-nums' }}>{fmtK(r.volume_today)}</td>
                  <td style={{ padding: '7px 8px', fontSize: 11 }}>
                    <span style={{ color: r.has_l34_np_ld ? 'var(--pos)' : 'var(--stroke)', fontWeight: 700 }}>{r.has_l34_np_ld ? 'L34NP' : '—'}</span>
                    {' '}<span style={{ color: r.has_wc_gap_ld ? 'var(--pos)' : 'var(--stroke)', fontWeight: 700 }}>{r.has_wc_gap_ld ? 'WcGap' : ''}</span>
                    {' '}<span style={{ color: r.l34_wlnbb ? 'var(--pump-blue)' : 'var(--stroke)' }}>{r.l34_wlnbb ? 'L34' : ''}</span>
                    {' '}<span style={{ color: (r.d4_beup || r.d6_beup) ? 'var(--pump-blue)' : 'var(--stroke)', fontWeight: 700 }}>{r.d6_beup ? 'D6' : r.d4_beup ? 'D4' : ''}</span>
                  </td>
                  <td style={{ padding: '7px 8px', fontSize: 10, color: 'var(--ink-dim)' }}>
                    {r.dc_dryup_streak > 0 && <span style={{ color: r.dc_dryup_streak >= 3 ? 'var(--warn)' : 'var(--ink-dim)', marginRight: 4 }}>Dry×{r.dc_dryup_streak}</span>}
                    {r.dc_near_ema50 && <span style={{ color: 'var(--pump-blue)', marginRight: 4 }}>EMA</span>}
                    {r.dc_atr_contracting && <span style={{ color: 'var(--pump-blue)' }}>ATR↘</span>}
                  </td>
                  <td style={{ padding: '7px 8px', fontSize: 10, color: 'var(--ink-dim)' }}>{r.sector || '—'}</td>
                  <td style={{ padding: '7px 8px' }} onClick={e => e.stopPropagation()}>
                    {(journaledSet.has(r.symbol) || addedJournal.has(r.symbol)) ? (
                      <span style={{ fontSize: 9, color: 'var(--pos)', fontWeight: 700 }}>✓</span>
                    ) : (
                      <button onClick={() => onAddToJournal(r)} disabled={addingJournal === r.symbol} style={{
                        background: 'var(--pump-lime)', border: 'none',
                        color: 'var(--on-lime)', borderRadius: 4, padding: '1px 6px', fontSize: 9, fontWeight: 600,
                        cursor: addingJournal === r.symbol ? 'not-allowed' : 'pointer',
                      }}>{addingJournal === r.symbol ? '…' : '+J'}</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── PAGE ──────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  // Scan data
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState(null);

  // Filters for full table
  const [tierF,    setTierF]    = useState('');
  const [atsF,     setAtsF]     = useState('');
  const [readyF,   setReadyF]   = useState('');
  const [minScore, setMinScore] = useState(0);
  const [limit,    setLimit]    = useState(200);

  // Scan trigger
  const [scanning,     setScanning]     = useState(false);
  const [scanProgress, setScanProgress] = useState(null);
  const [scanError,    setScanError]    = useState(null);

  // Drawer
  const [drawerRow,        setDrawerRow]        = useState(null);
  const [narratives,       setNarratives]       = useState({});
  const [narrativeLoading, setNarrativeLoading] = useState(null);

  // Context
  const [marketTimer, setMarketTimer] = useState({ open: false, label: '00:00:00' });
  const [regime,      setRegime]      = useState(null);
  const [hypeStatus,  setHypeStatus]  = useState(null);
  const [hypeResults, setHypeResults] = useState([]);
  const [livePrices,  setLivePrices]  = useState({});
  const [sectors,     setSectors]     = useState({});
  const [news,        setNews]        = useState([]);
  const [newsLoading, setNewsLoading] = useState(false);

  // Journal
  const [journaledSet,  setJournaledSet]  = useState(new Set());
  const [addingJournal, setAddingJournal] = useState(null);
  const [addedJournal,  setAddedJournal]  = useState(new Set());

  // UI
  const [showFullTable, setShowFullTable] = useState(false);

  // Fetch demand scanner data
  const fetchData = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const params = new URLSearchParams();
      if (tierF)        params.set('tier', tierF);
      if (atsF)         params.set('ats_signal', atsF);
      if (minScore > 0) params.set('min_score', minScore);
      params.set('limit', limit);
      const res  = await fetch(`${API_URL}/api/demand-scanner/latest?${params}`);
      const json = await res.json();
      setData(json);
    } catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [tierF, atsF, minScore, limit]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Market context — regime + hype + sectors
  const fetchContext = useCallback(async () => {
    try {
      const [regRes, statusRes, resultsRes, secRes] = await Promise.all([
        fetch(`${API_URL}/api/market-regime`).catch(() => null),
        fetch(`${API_URL}/api/hype/status`).catch(() => null),
        fetch(`${API_URL}/api/hype/results`).catch(() => null),
        fetch(`${API_URL}/api/sector-momentum`).catch(() => null),
      ]);
      if (regRes?.ok)     setRegime(await regRes.json());
      if (statusRes?.ok)  setHypeStatus(await statusRes.json());
      if (resultsRes?.ok) { const d = await resultsRes.json(); setHypeResults(d.results || []); }
      if (secRes?.ok)     setSectors(await secRes.json());
    } catch { /* optional */ }
  }, []);

  useEffect(() => { fetchContext(); const id = setInterval(fetchContext, 5 * 60 * 1000); return () => clearInterval(id); }, [fetchContext]);

  // Market countdown
  useEffect(() => {
    const tick = () => setMarketTimer(getMarketCountdown());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  // Live prices every 30s during market hours
  const fetchLivePrices = useCallback(async (results) => {
    if (!results?.length || !isMarketOpen()) return;
    const syms = results.map(r => r.symbol).join(',');
    try {
      const res = await fetch(`${API_URL}/api/prices/live?symbols=${encodeURIComponent(syms)}`);
      if (res.ok) setLivePrices(await res.json());
    } catch { /* best-effort */ }
  }, []);

  useEffect(() => {
    if (!data?.results?.length) return;
    fetchLivePrices(data.results);
    const id = setInterval(() => fetchLivePrices(data.results), 30 * 1000);
    return () => clearInterval(id);
  }, [data, fetchLivePrices]);

  // News for top 10 picks
  useEffect(() => {
    if (!data?.results?.length) return;
    const topSyms = data.results.slice(0, 10).map(r => r.symbol).join(',');
    setNewsLoading(true);
    fetch(`${API_URL}/api/demand-scanner/news?symbols=${encodeURIComponent(topSyms)}&limit=18`)
      .then(r => r.ok ? r.json() : { articles: [] })
      .then(d => setNews(d.articles || []))
      .catch(() => setNews([]))
      .finally(() => setNewsLoading(false));
  }, [data?.results?.length > 0 && data.results.map(r => r.symbol).slice(0, 10).join(',')]); // eslint-disable-line

  // Journal check
  const checkJournaled = useCallback(async (results) => {
    if (!results?.length) return;
    const syms = results.map(r => r.symbol).join(',');
    try {
      const res = await fetch(`${API_URL}/api/demand-scanner/journal-check?symbols=${encodeURIComponent(syms)}`);
      if (res.ok) { const d = await res.json(); setJournaledSet(new Set(d.journaled || [])); }
    } catch { /* optional */ }
  }, []);

  useEffect(() => { if (data?.results?.length) checkJournaled(data.results); }, [data, checkJournaled]);

  const addToJournal = useCallback(async (row) => {
    const sym = row.symbol;
    setAddingJournal(sym);
    try {
      const today = new Date().toISOString().slice(0, 10);
      const lp = livePrices[sym];
      const payload = {
        symbol: sym, entry_price: lp?.price ?? row.price,
        entry_date: today, source: 'demand_scanner',
        tier: row.demand_composite_tier || '', score: row.demand_composite_score ?? 0,
        signal_date: data?.scanned_at?.slice(0, 10) || today,
        notes: [
          row.demand_composite_tier ? `Tier: ${row.demand_composite_tier}` : null,
          row.ats_signal && row.ats_signal !== 'ATS_NONE' ? `ATS: ${row.ats_signal}` : null,
          row.readiness_tier ? `Ready: ${row.readiness_tier}` : null,
          (row.demand_buy_reasons || []).slice(0, 3).map(r => REASONS_PRETTY[r] || r).join(', '),
        ].filter(Boolean).join(' · '),
        indicators_snapshot: {
          demand_composite_score: row.demand_composite_score, demand_composite_tier: row.demand_composite_tier,
          ats_signal: row.ats_signal, readiness_tier: row.readiness_tier,
          readiness_score: row.readiness_score, demand_buy_reasons: row.demand_buy_reasons,
          scan_price: row.price, live_price_at_add: lp?.price ?? null,
        },
      };
      const res = await fetch(`${API_URL}/api/journal`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (res.ok) { setAddedJournal(prev => new Set([...prev, sym])); }
      else { const err = await res.json().catch(() => ({})); alert(`Failed: ${err.detail || res.statusText}`); }
    } catch (e) { alert(`Error: ${e}`); }
    finally { setAddingJournal(null); }
  }, [data, livePrices]);

  // Narrative
  const fetchNarrative = useCallback(async (row) => {
    const sym = row.symbol;
    if (narratives[sym] || narrativeLoading === sym) return;
    setNarrativeLoading(sym);
    try {
      const res  = await fetch(`${API_URL}/api/demand-scanner/narrative`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(row) });
      const json = await res.json();
      setNarratives(prev => ({ ...prev, [sym]: json.narrative || json.detail || 'No narrative.' }));
    } catch (e) { setNarratives(prev => ({ ...prev, [sym]: `Error: ${e}` })); }
    finally { setNarrativeLoading(null); }
  }, [narratives, narrativeLoading]);

  // Scan trigger
  const triggerScan = useCallback(async () => {
    setScanError(null);
    try {
      const res = await fetch(`${API_URL}/api/demand-scanner/run`, { method: 'POST' });
      const json = await res.json();
      if (json.status === 'already_running' || json.status === 'started') setScanning(true);
    } catch (e) { setScanError(`Failed: ${e}`); }
  }, []);

  useEffect(() => {
    if (!scanning) return;
    const poll = setInterval(async () => {
      try {
        const res = await fetch(`${API_URL}/api/demand-scanner/status`);
        const json = await res.json();
        setScanProgress(json);
        if (!json.running && (json.phase === 'done' || json.phase === 'error')) {
          setScanning(false); clearInterval(poll);
          if (json.phase === 'done') fetchData();
          if (json.phase === 'error') setScanError(json.last_error || 'Scan failed');
        }
      } catch (_) {}
    }, 2000);
    return () => clearInterval(poll);
  }, [scanning, fetchData]);

  const allResults = data?.results || [];
  const tc = data?.tier_counts || {};
  const ac = data?.ats_counts  || {};
  const topPicks = allResults.slice(0, 12);

  return (
    <>
      <Head><title>Dashboard — Pump Scout</title></Head>
      <AppNav />
      <MarketContextBar marketTimer={marketTimer} regime={regime} livePrices={livePrices} marketOpen={marketTimer.open} />

      <div style={{ background: 'var(--bg-0)', minHeight: '100vh', padding: '16px 20px 80px' }}>

        {/* ── Overview stats ─────────────────────────────────────────────────── */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 20 }}>
          {[
            { label: 'PRIME BUY',  val: data?.demand_prime_count ?? tc.PRIME_BUY ?? 0,     color: 'var(--pos)' },
            { label: 'HIGH CONF',  val: data?.demand_high_count  ?? tc.HIGH_CONF_BUY ?? 0, color: 'var(--pump-blue)' },
            { label: 'BUY WATCH',  val: data?.demand_watch_count ?? tc.BUY_WATCH ?? 0,     color: 'var(--warn)' },
            { label: 'ATS PRIME',  val: data?.ats_prime_count    ?? ac.ATS_PRIME ?? 0,      color: 'var(--pos)' },
            { label: 'ATS SETUP',  val: ac.ATS_SETUP ?? 0,                                  color: 'var(--pump-blue)' },
            { label: 'UNIVERSE',   val: (data?.universe || 0).toLocaleString(),              color: 'var(--ink-mute)' },
          ].map(({ label, val, color }) => (
            <div key={label} style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 'var(--r-xl)', padding: '12px 18px', textAlign: 'center', minWidth: 90 }}>
              <div style={{ fontSize: 26, fontWeight: 800, color, lineHeight: 1 }}>{loading ? '…' : val}</div>
              <div style={{ fontSize: 9, color: 'var(--ink-dim)', textTransform: 'uppercase', letterSpacing: '0.07em', marginTop: 4 }}>{label}</div>
            </div>
          ))}
          {data?.scanned_at && (
            <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 'var(--r-xl)', padding: '12px 18px', textAlign: 'center', minWidth: 120, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--ink-mute)' }}>{new Date(data.scanned_at).toLocaleDateString()}</div>
              <div style={{ fontSize: 10, color: 'var(--ink-dim)', marginTop: 2 }}>{new Date(data.scanned_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · {data.elapsed_secs}s</div>
              <div style={{ fontSize: 9, color: 'var(--ink-faint)', marginTop: 2 }}>Last scan</div>
            </div>
          )}
        </div>

        {error && <div style={{ padding: '12px 16px', background: 'oklch(0.72 0.21 25 / 0.10)', border: '1px solid oklch(0.72 0.21 25 / 0.30)', borderRadius: 8, color: 'var(--neg)', fontSize: 12, marginBottom: 16 }}>{error}</div>}

        {/* ── Top Picks Carousel ─────────────────────────────────────────────── */}
        {!loading && topPicks.length > 0 && (
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--ink-mute)', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: 10 }}>
              Top Demand Setups
            </div>
            <div style={{ display: 'flex', gap: 12, overflowX: 'auto', paddingBottom: 8 }}>
              {topPicks.map(r => (
                <TopPickCard
                  key={r.symbol}
                  r={r}
                  livePrice={livePrices[r.symbol]}
                  journaled={journaledSet.has(r.symbol)}
                  adding={addingJournal === r.symbol}
                  added={addedJournal.has(r.symbol)}
                  onAdd={addToJournal}
                  onClick={setDrawerRow}
                />
              ))}
            </div>
          </div>
        )}

        {/* ── 3-column grid: Sectors | ATS Panel | Gainers/Losers ───────────── */}
        {!loading && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 240px 280px', gap: 12, marginBottom: 20 }}>
            <SectorHeatmap sectors={sectors} />
            <AtsPanel results={allResults} />
            <GainersLosers livePrices={livePrices} results={allResults} marketOpen={marketTimer.open} />
          </div>
        )}

        {/* ── Hype Strip ─────────────────────────────────────────────────────── */}
        {(hypeStatus || hypeResults.length > 0) && (
          <div style={{ marginBottom: 16 }}>
            <HypeStrip hypeStatus={hypeStatus} hypeResults={hypeResults} />
          </div>
        )}

        {/* ── News Feed ──────────────────────────────────────────────────────── */}
        {!loading && (
          <div style={{ marginBottom: 20 }}>
            <NewsFeed articles={news} loading={newsLoading} />
          </div>
        )}

        {/* ── Full Scanner Toggle ────────────────────────────────────────────── */}
        <div style={{ marginBottom: 8 }}>
          <button
            onClick={() => setShowFullTable(s => !s)}
            style={{
              background: showFullTable ? 'var(--pump-blue-soft)' : 'var(--bg-1)',
              border: `1px solid ${showFullTable ? 'var(--pump-blue)' : 'var(--stroke)'}`,
              color: showFullTable ? 'var(--pump-blue)' : 'var(--ink-mute)',
              borderRadius: 8, padding: '8px 18px', fontSize: 12, fontWeight: 600,
              cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8,
            }}
          >
            <span style={{ fontSize: 10 }}>{showFullTable ? '▲' : '▼'}</span>
            {showFullTable ? 'Hide' : 'Show'} Full Scanner
            <span style={{ fontSize: 11, opacity: 0.7 }}>({allResults.length} results)</span>
          </button>
        </div>

        {/* ── Full Scanner Table ─────────────────────────────────────────────── */}
        {showFullTable && (
          <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 10, padding: '14px 16px' }}>
            <ScannerTable
              results={allResults}
              livePrices={livePrices}
              journaledSet={journaledSet}
              addingJournal={addingJournal}
              addedJournal={addedJournal}
              onAddToJournal={addToJournal}
              onRowClick={setDrawerRow}
              tierF={tierF} setTierF={setTierF}
              atsF={atsF} setAtsF={setAtsF}
              readyF={readyF} setReadyF={setReadyF}
              minScore={minScore} setMinScore={setMinScore}
              limit={limit} setLimit={setLimit}
              onRefresh={fetchData}
              triggerScan={triggerScan}
              scanning={scanning}
              scanProgress={scanProgress}
              scanError={scanError}
            />
          </div>
        )}

      </div>

      {/* Drawer */}
      {drawerRow && (
        <>
          <div onClick={() => setDrawerRow(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 999 }} />
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
