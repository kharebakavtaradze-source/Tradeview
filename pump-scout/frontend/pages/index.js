import { useCallback, useEffect, useRef, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';

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

// ── PUMP DESIGN SYSTEM COMPONENTS ────────────────────────────────────────────

const sp = (seed, n = 24, drift = 0) => Array.from({ length: n }, (_, i) => {
  const x = Math.sin(seed + i * 0.6) * 0.5 + Math.cos(seed * 0.31 + i * 0.21) * 0.3;
  return 50 + x * 18 + drift * i;
});
const symSeed = s => s ? s.split('').reduce((a, c) => a + c.charCodeAt(0), 0) % 100 : 42;

function PumpMark({ size = 24 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <path d="M12 1.5 C 12.7 7.6, 16.4 11.3, 22.5 12 C 16.4 12.7, 12.7 16.4, 12 22.5 C 11.3 16.4, 7.6 12.7, 1.5 12 C 7.6 11.3, 11.3 7.6, 12 1.5 Z" fill="var(--pump-lime)" />
    </svg>
  );
}

function Sparkline({ data = [], width = 80, height = 24, color = 'var(--pump-lime)' }) {
  if (!data.length) return <svg width={width} height={height} />;
  const min = Math.min(...data), max = Math.max(...data), range = max - min || 1;
  const pts = data.map((v, i) => [
    (i / (data.length - 1)) * (width - 2) + 1,
    height - ((v - min) / range) * (height - 2) - 1,
  ]);
  const d = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  return (
    <svg width={width} height={height} style={{ display: 'block', overflow: 'visible' }}>
      <path d={d} fill="none" stroke={color} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const NAV_ICONS = {
  home:     <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" />,
  search:   <><circle cx="11" cy="11" r="8" stroke="currentColor" fill="none" /><line x1="21" y1="21" x2="16.65" y2="16.65" stroke="currentColor" strokeLinecap="round" /></>,
  layers:   <><polygon points="12 2 2 7 12 12 22 7 12 2" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><polyline points="2 17 12 22 22 17" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><polyline points="2 12 12 17 22 12" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>,
  folder:   <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" />,
  globe:    <><circle cx="12" cy="12" r="10" stroke="currentColor" fill="none" /><line x1="2" y1="12" x2="22" y2="12" stroke="currentColor" strokeLinecap="round" /><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z" stroke="currentColor" fill="none" /></>,
  swap:     <><polyline points="17 1 21 5 17 9" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><path d="M3 11V9a4 4 0 014-4h14" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><polyline points="7 23 3 19 7 15" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><path d="M21 13v2a4 4 0 01-4 4H3" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>,
  bolt:     <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" />,
  candle:   <><rect x="9" y="6" width="6" height="12" rx="1" stroke="currentColor" fill="none" /><line x1="12" y1="2" x2="12" y2="6" stroke="currentColor" strokeLinecap="round" /><line x1="12" y1="18" x2="12" y2="22" stroke="currentColor" strokeLinecap="round" /></>,
  spark:    <><polyline points="23 6 13.5 15.5 8.5 10.5 1 18" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><polyline points="17 6 23 6 23 12" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>,
  settings: <><circle cx="12" cy="12" r="3" stroke="currentColor" fill="none" /><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z" stroke="currentColor" fill="none" /></>,
  grid:     <><rect x="3" y="3" width="7" height="7" stroke="currentColor" fill="none" strokeLinecap="round" /><rect x="14" y="3" width="7" height="7" stroke="currentColor" fill="none" strokeLinecap="round" /><rect x="14" y="14" width="7" height="7" stroke="currentColor" fill="none" strokeLinecap="round" /><rect x="3" y="14" width="7" height="7" stroke="currentColor" fill="none" strokeLinecap="round" /></>,
  bell:     <><path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><path d="M13.73 21a2 2 0 01-3.46 0" stroke="currentColor" fill="none" strokeLinecap="round" /></>,
  filter:   <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" />,
  'arrow-ur': <><line x1="7" y1="17" x2="17" y2="7" stroke="currentColor" strokeLinecap="round" /><polyline points="7 7 17 7 17 17" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>,
  right:    <polyline points="9 18 15 12 9 6" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" />,
  down:     <polyline points="6 9 12 15 18 9" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" />,
};

function NavIcon({ name, size = 18, color = 'currentColor' }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{ display: 'block', color }}>
      {NAV_ICONS[name] || <circle cx="12" cy="12" r="4" stroke="currentColor" fill="none" />}
    </svg>
  );
}

function LeftSidebar() {
  const router = useRouter();
  const items = [
    { href: '/',                  icon: 'home',     label: 'Dashboard' },
    { href: '/scanner-v2',        icon: 'search',   label: 'Scanner' },
    { href: '/sectors',           icon: 'layers',   label: 'Sectors' },
    { href: '/journal',           icon: 'folder',   label: 'Journal' },
    { href: '/macro-events',      icon: 'globe',    label: 'Macro' },
    { href: '/replay',            icon: 'swap',     label: 'Replay' },
    null,
    { href: '/pump-study',        icon: 'bolt',     label: 'Pump Study' },
    { href: '/raw-pattern-study', icon: 'candle',   label: 'Raw Patterns' },
    { href: '/ai-journal',        icon: 'spark',    label: 'AI Journal' },
    null,
    { href: '/design-system',     icon: 'grid',     label: 'Design System' },
  ];
  return (
    <aside style={{
      width: 78, flexShrink: 0, background: 'var(--bg-1)',
      borderRight: '1px solid var(--stroke-soft)',
      padding: '18px 12px 14px', display: 'flex', flexDirection: 'column',
      alignItems: 'center', gap: 6, position: 'sticky', top: 0, alignSelf: 'flex-start',
      minHeight: '100vh', zIndex: 10,
    }}>
      <div style={{ padding: '4px 0 8px' }} title="Pump"><PumpMark size={24} /></div>
      {items.map((item, i) => {
        if (!item) return <div key={`d${i}`} style={{ height: 1, background: 'var(--stroke-soft)', width: 28, margin: '4px 0' }} />;
        const active = router.pathname === item.href;
        return (
          <Link key={item.href} href={item.href} title={item.label} style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            width: 42, height: 38, borderRadius: 'var(--r-md)',
            background: active ? 'var(--pump-lime-soft)' : 'transparent',
            color: active ? 'var(--pump-lime)' : 'var(--ink-dim)',
            textDecoration: 'none', position: 'relative', transition: 'background 0.15s, color 0.15s',
          }}
          onMouseEnter={e => { if (!active) { e.currentTarget.style.background = 'var(--bg-2)'; e.currentTarget.style.color = 'var(--ink)'; }}}
          onMouseLeave={e => { if (!active) { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--ink-dim)'; }}}
          >
            <NavIcon name={item.icon} size={18} />
            {active && <span style={{ position: 'absolute', left: -14, top: '50%', transform: 'translateY(-50%)', width: 4, height: 18, borderRadius: 2, background: 'var(--pump-lime)' }} />}
          </Link>
        );
      })}
      <div style={{ flex: 1 }} />
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 42, height: 38, borderRadius: 'var(--r-md)', color: 'var(--ink-dim)', cursor: 'pointer' }} title="Alerts">
        <NavIcon name="bell" size={18} />
      </div>
    </aside>
  );
}

function TopBar({ marketTimer, regime }) {
  const regimeState = regime?.regime_state || regime?.state;
  const today = new Date();
  const dayName = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'][today.getDay()];
  const dateStr = today.toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', year: 'numeric' });
  return (
    <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 28px', borderBottom: '1px solid var(--stroke-soft)', background: 'var(--bg-0)', gap: 16, flexWrap: 'nowrap' }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 10, color: 'var(--ink-dim)', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--f-mono)', marginBottom: 2 }}>{dayName}</div>
        <h1 style={{ margin: 0, fontSize: 21, fontWeight: 500, letterSpacing: '-0.02em', color: 'var(--ink)' }}>
          Dashboard{' '}<em style={{ fontFamily: 'var(--f-serif)', fontStyle: 'italic', color: 'var(--pump-lime)', fontWeight: 400 }}>overview</em>
        </h1>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
        {regimeState && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 12px', background: 'var(--bg-1)', borderRadius: 'var(--r-pill)', border: '1px solid var(--stroke-soft)' }}>
            <span style={{ fontSize: 10, color: 'var(--ink-dim)', textTransform: 'uppercase', letterSpacing: '0.07em', fontFamily: 'var(--f-mono)' }}>Regime</span>
            <span style={{ fontSize: 11, fontWeight: 700, color: REGIME_COLORS[regimeState] || 'var(--ink-mute)', fontFamily: 'var(--f-mono)', letterSpacing: '0.05em' }}>{regimeState.replace(/_/g, ' ')}</span>
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 14px', background: 'var(--bg-1)', borderRadius: 'var(--r-pill)', whiteSpace: 'nowrap', border: '1px solid var(--stroke-soft)' }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: marketTimer.open ? 'var(--pos)' : 'var(--ink-dim)', display: 'inline-block' }} />
          <span style={{ fontSize: 10, color: 'var(--ink-mute)', letterSpacing: '0.08em', fontFamily: 'var(--f-mono)', textTransform: 'uppercase' }}>{marketTimer.open ? 'OPEN' : 'CLOSED'}</span>
          <span style={{ fontSize: 12, color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{marketTimer.label}</span>
        </div>
        <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', padding: '6px 12px', background: 'var(--bg-1)', borderRadius: 'var(--r-pill)', border: '1px solid var(--stroke-soft)' }}>{dateStr}</span>
      </div>
    </header>
  );
}

function HeroRead({ allResults, tc, hypeStatus, sectors, loading }) {
  const highConf = (tc.HIGH_CONF_BUY ?? 0) + (tc.PRIME_BUY ?? 0);
  const leadTicker = allResults[0]?.symbol || '—';
  const leadScore  = allResults[0] ? fmt(allResults[0].demand_composite_score, 1) : '—';
  const topSectors = Object.entries(sectors || {})
    .map(([name, d]) => ({ name, chg: d.change_1d ?? d.pct_change_1d ?? 0 }))
    .sort((a, b) => b.chg - a.chg).slice(0, 3)
    .map(s => s.name.split(' ')[0].toUpperCase().slice(0, 6));
  const sectorStr = topSectors.length ? topSectors.join(' · ') : '—';
  const hypeScore = hypeStatus?.total_divergences ?? 0;
  const hypeLabel = hypeScore > 20 ? 'HOT' : hypeScore > 10 ? 'WARM' : 'COOL';
  const volSurge  = hypeStatus?.avg_vol_surge ?? 0;
  const today = new Date().toLocaleDateString('en-US', { month: 'numeric', day: 'numeric', year: 'numeric' });
  return (
    <div style={{
      padding: '18px 22px',
      background: 'radial-gradient(ellipse at 100% 0%, oklch(0.96 0.18 125 / 0.65) 0%, transparent 55%), linear-gradient(135deg, oklch(0.94 0.20 125) 0%, oklch(0.84 0.20 120) 100%)',
      color: 'var(--on-lime)', borderRadius: 'var(--r-xl)', overflow: 'hidden', position: 'relative',
      display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap', minHeight: 130,
    }}>
      <svg style={{ position: 'absolute', right: -40, top: -50, opacity: 0.22, pointerEvents: 'none' }} width="240" height="240" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="48" fill="none" stroke="var(--on-lime)" strokeWidth="0.4" />
        <circle cx="50" cy="50" r="36" fill="none" stroke="var(--on-lime)" strokeWidth="0.4" />
        <circle cx="50" cy="50" r="24" fill="none" stroke="var(--on-lime)" strokeWidth="0.4" />
      </svg>
      <div style={{ flex: '1 1 300px', minWidth: 260, position: 'relative' }}>
        <div style={{ fontSize: 10, color: 'var(--on-lime)', opacity: 0.7, textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--f-mono)', marginBottom: 4 }}>Today's read · {today}</div>
        <div style={{ fontSize: 20, lineHeight: 1.25, letterSpacing: '-0.02em', color: 'var(--on-lime)' }}>
          <em style={{ fontFamily: 'var(--f-serif)', fontStyle: 'italic' }}>here's</em> what's hot —{' '}
          <span style={{ fontFamily: 'var(--f-mono)', fontWeight: 600 }}>{loading ? '…' : highConf}</span> high-conf setups firing, led by{' '}
          <span style={{ fontFamily: 'var(--f-mono)', fontWeight: 600 }}>{leadTicker}</span> at{' '}
          <span style={{ fontFamily: 'var(--f-mono)', fontWeight: 600 }}>{leadScore}</span>.
        </div>
      </div>
      <div style={{ display: 'flex', gap: 18, flexShrink: 0, position: 'relative' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 10, color: 'var(--on-lime)', opacity: 0.7, textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--f-mono)' }}>Conviction</div>
          <div style={{ display: 'flex', gap: 2, alignItems: 'flex-end', height: 26 }}>
            {[12, 18, 24, 16, 10].map((h, i) => <span key={i} style={{ width: 5, height: h, background: 'var(--on-lime)', borderRadius: 1.5, opacity: i >= 3 ? 0.5 : 1 }} />)}
          </div>
          <div style={{ fontSize: 10, color: 'var(--on-lime)', fontFamily: 'var(--f-mono)', letterSpacing: '0.08em' }}>BUILDING</div>
        </div>
        <span style={{ width: 1, height: 40, background: 'var(--on-lime)', opacity: 0.2, alignSelf: 'center' }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 10, color: 'var(--on-lime)', opacity: 0.7, textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--f-mono)' }}>Lead sectors</div>
          <div style={{ fontSize: 13, color: 'var(--on-lime)', fontFamily: 'var(--f-mono)', fontWeight: 500 }}>{sectorStr}</div>
          <div style={{ fontSize: 10, color: 'var(--on-lime)', opacity: 0.7, fontFamily: 'var(--f-mono)' }}>top {topSectors.length || '…'} of {Object.keys(sectors || {}).length || '…'}</div>
        </div>
        <span style={{ width: 1, height: 40, background: 'var(--on-lime)', opacity: 0.2, alignSelf: 'center' }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 10, color: 'var(--on-lime)', opacity: 0.7, textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--f-mono)' }}>Hype</div>
          <div style={{ fontSize: 13, color: 'var(--on-lime)', fontFamily: 'var(--f-mono)', fontWeight: 500 }}>{hypeScore} · {hypeLabel}</div>
          <div style={{ fontSize: 10, color: 'var(--on-lime)', opacity: 0.7, fontFamily: 'var(--f-mono)' }}>{volSurge > 0 ? `vol +${volSurge}%` : 'vol surge'}</div>
        </div>
      </div>
      <button style={{ background: 'var(--on-lime)', color: 'var(--pump-lime)', padding: '10px 16px', borderRadius: 'var(--r-pill)', fontSize: 13, fontWeight: 600, border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, whiteSpace: 'nowrap', position: 'relative', flexShrink: 0 }}>
        Open prep notebook <NavIcon name="arrow-ur" size={14} color="var(--pump-lime)" />
      </button>
    </div>
  );
}

function FunnelCard({ tc, ac, data, loading }) {
  const universe = data?.universe || 0;
  const atsTotal = (ac.ATS_PRIME || 0) + (ac.ATS_SETUP || 0) + (ac.ATS_WATCH || 0);
  const highConf = (tc.HIGH_CONF_BUY || 0) + (tc.PRIME_BUY || 0);
  const prime    = tc.PRIME_BUY || 0;
  const logW = v => v <= 0 ? 3 : Math.log(v + 1);
  const maxW = logW(universe || 1);
  const stages = [
    { label: 'UNIVERSE', count: universe >= 1000 ? `${(universe/1000).toFixed(1)}K` : String(universe), width: 100 },
    { label: 'ATS SETUP', count: String(atsTotal), width: universe > 0 ? Math.max(8, (logW(atsTotal) / maxW) * 90) : 62 },
    { label: 'HIGH CONF', count: String(highConf), width: universe > 0 ? Math.max(5, (logW(highConf) / maxW) * 90) : 26 },
    { label: 'PRIME BUY', count: String(prime),    width: prime > 0 ? Math.max(4, (logW(prime) / maxW) * 90) : 8 },
  ];
  const scannedAt = data?.scanned_at ? new Date(data.scanned_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
  return (
    <div style={{
      padding: '20px 22px',
      background: 'radial-gradient(ellipse at 0% 0%, oklch(0.82 0.13 268 / 0.7) 0%, transparent 55%), linear-gradient(135deg, var(--pump-blue) 0%, oklch(0.60 0.14 268) 100%)',
      color: 'white', borderRadius: 'var(--r-xl)', overflow: 'hidden', position: 'relative',
      display: 'flex', flexDirection: 'column', gap: 12,
    }}>
      <svg style={{ position: 'absolute', right: -30, bottom: -30, opacity: 0.22, pointerEvents: 'none' }} width="200" height="200" viewBox="0 0 100 100">
        <circle cx="50" cy="50" r="48" fill="none" stroke="white" strokeWidth="0.5" />
        <circle cx="50" cy="50" r="36" fill="none" stroke="white" strokeWidth="0.5" />
        <circle cx="50" cy="50" r="24" fill="none" stroke="white" strokeWidth="0.5" />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', position: 'relative' }}>
        <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.7)', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--f-mono)' }}>Scanner pipeline</span>
        {scannedAt && <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.8)', fontFamily: 'var(--f-mono)', letterSpacing: '0.06em' }}>{scannedAt}{data?.elapsed_secs ? ` · ${data.elapsed_secs}s` : ''}</span>}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, position: 'relative' }}>
        {stages.map((s, i) => (
          <div key={s.label} style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.7)', width: 78, fontFamily: 'var(--f-mono)', letterSpacing: '0.06em', flexShrink: 0 }}>{s.label}</span>
            <div style={{ flex: 1, height: 24, position: 'relative', background: 'rgba(255,255,255,0.10)', borderRadius: 'var(--r-sm)', overflow: 'hidden' }}>
              <div style={{ position: 'absolute', inset: 0, width: `${s.width}%`, background: i === stages.length - 1 ? 'var(--pump-lime)' : 'linear-gradient(90deg, rgba(255,255,255,0.65), rgba(255,255,255,0.88))', borderRadius: 'var(--r-sm)' }} />
              <div style={{ position: 'absolute', left: 10, top: 0, height: 24, display: 'flex', alignItems: 'center' }}>
                <span style={{ fontSize: 11, color: i === stages.length - 1 ? 'var(--on-lime)' : 'var(--pump-blue)', fontWeight: 600, fontFamily: 'var(--f-mono)' }}>{loading ? '…' : s.count}</span>
              </div>
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 14, position: 'relative', marginTop: 'auto', paddingTop: 8, borderTop: '1px dashed rgba(255,255,255,0.2)' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.7)', textTransform: 'uppercase', letterSpacing: '0.06em', fontFamily: 'var(--f-mono)' }}>BUY WATCH</span>
          <span style={{ fontSize: 18, color: 'white', fontWeight: 500, fontFamily: 'var(--f-mono)' }}>{loading ? '…' : (tc.BUY_WATCH ?? 0)}</span>
        </div>
        <span style={{ width: 1, height: 32, background: 'rgba(255,255,255,0.18)', alignSelf: 'center' }} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.7)', textTransform: 'uppercase', letterSpacing: '0.06em', fontFamily: 'var(--f-mono)' }}>ATS PRIME</span>
          <span style={{ fontSize: 18, color: 'white', fontWeight: 500, fontFamily: 'var(--f-mono)' }}>{loading ? '…' : (ac.ATS_PRIME ?? 0)}</span>
        </div>
        {data?.elapsed_secs && <>
          <span style={{ width: 1, height: 32, background: 'rgba(255,255,255,0.18)', alignSelf: 'center' }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.7)', textTransform: 'uppercase', letterSpacing: '0.06em', fontFamily: 'var(--f-mono)' }}>SCAN TIME</span>
            <span style={{ fontSize: 18, color: 'white', fontWeight: 500, fontFamily: 'var(--f-mono)' }}>{data.elapsed_secs}s</span>
          </div>
        </>}
      </div>
    </div>
  );
}

function KpiCell({ label, value, trend, color = 'var(--ink)', sparkData, sparkColor, tint }) {
  const tintBg =
    tint === 'blue' ? 'linear-gradient(135deg, color-mix(in oklch, var(--pump-blue) 14%, var(--bg-1)) 0%, var(--bg-1) 90%)' :
    tint === 'lime' ? 'linear-gradient(135deg, color-mix(in oklch, var(--pump-lime) 10%, var(--bg-1)) 0%, var(--bg-1) 90%)' :
    tint === 'warn' ? 'linear-gradient(135deg, color-mix(in oklch, var(--warn) 10%, var(--bg-1)) 0%, var(--bg-1) 90%)' :
    'var(--bg-1)';
  const borderColor = tint === 'blue' ? 'var(--pump-blue)' : tint === 'lime' ? 'var(--pump-lime)' : tint === 'warn' ? 'var(--warn)' : null;
  return (
    <div style={{ background: tintBg, borderRadius: 'var(--r-lg)', padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 8, minHeight: 108, minWidth: 0, border: borderColor ? `1px solid color-mix(in oklch, ${borderColor} 18%, transparent)` : '1px solid var(--stroke-soft)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 10, color: 'var(--ink-dim)', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--f-mono)' }}>{label}</span>
        {trend && <span style={{ fontSize: 10, color: trend.startsWith('+') ? 'var(--pos)' : trend.startsWith('-') ? 'var(--neg)' : 'var(--ink-dim)', fontFamily: 'var(--f-mono)', whiteSpace: 'nowrap' }}>{trend}</span>}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', marginTop: 'auto', minWidth: 0 }}>
        <span style={{ fontSize: 28, color, fontWeight: 500, letterSpacing: '-0.02em', lineHeight: 1, fontFamily: 'var(--f-mono)' }}>{value}</span>
        {sparkData && <Sparkline width={62} height={22} data={sparkData} color={sparkColor || color} />}
      </div>
    </div>
  );
}

function KpiStrip({ tc, ac, data, loading }) {
  const val = (v, big) => loading ? '…' : (big ? (v >= 1000 ? `${(v/1000).toFixed(1)}K` : String(v)) : String(v));
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 10 }}>
      <KpiCell label="PRIME BUY" value={val(tc.PRIME_BUY ?? 0)}    color="var(--pos)"       tint="lime" />
      <KpiCell label="HIGH CONF" value={val(tc.HIGH_CONF_BUY ?? 0)} color="var(--pump-blue)" tint="blue" />
      <KpiCell label="BUY WATCH" value={val(tc.BUY_WATCH ?? 0)}    color="var(--warn)"      tint="warn" />
      <KpiCell label="ATS PRIME" value={val(ac.ATS_PRIME ?? 0)}    color="var(--pos)"       tint="lime" />
      <KpiCell label="ATS SETUP" value={val(ac.ATS_SETUP ?? 0)}    color="var(--pump-blue)" tint="blue" />
      <KpiCell label="UNIVERSE"  value={val(data?.universe || 0, true)} color="var(--ink)" />
    </div>
  );
}

function PumpSetupCard({ r, livePrice, journaled, adding, added, onAdd, onClick, scoreHistory }) {
  const price    = livePrice?.price ?? r.price;
  const chgPct   = livePrice?.change_pct ?? r.price_change_pct;
  const chgUp    = chgPct != null ? chgPct >= 0 : true;
  const score    = fmt(r.demand_composite_score, 1);
  const atsRating = r.ats_signal === 'ATS_PRIME' ? 3 : r.ats_signal === 'ATS_SETUP' ? 2 : r.ats_signal === 'ATS_WATCH' ? 1 : 0;
  const readTemp = (r.readiness_tier === 'HOT' || r.readiness_tier === 'WARM') ? 'WARM' : 'COOL';
  const tempLvl  = r.readiness_tier === 'HOT' ? 5 : r.readiness_tier === 'WARM' ? 3 : r.readiness_tier === 'COOL' ? 2 : 1;
  const tempColor = readTemp === 'WARM' ? 'var(--warn)' : 'var(--pump-blue)';
  const criteria  = (r.demand_buy_reasons || []).slice(0, 4).map(rr => REASONS_PRETTY[rr] || rr);
  const sparkData = scoreHistory?.length >= 2 ? scoreHistory : sp(symSeed(r.symbol), 30, chgUp ? 0.3 : -0.2);
  const sparkColor = scoreHistory?.length >= 2 ? 'var(--pump-lime)' : (chgUp ? 'var(--pump-lime)' : 'var(--neg)');
  return (
    <div onClick={() => onClick(r)} style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 'var(--r-xl)', padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 12, cursor: 'pointer', transition: 'border-color 0.15s' }}
      onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--pump-lime-soft)'}
      onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--stroke-soft)'}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
            <span style={{ fontSize: 20, fontWeight: 600, letterSpacing: '-0.01em', color: 'var(--ink)' }}>{r.symbol}</span>
            <span style={{ fontSize: 9, padding: '2px 6px', borderRadius: 4, background: 'var(--pump-blue-soft)', color: 'var(--pump-blue)', fontFamily: 'var(--f-mono)', fontWeight: 700, letterSpacing: '0.06em' }}>{TIER_META[r.demand_composite_tier]?.label || 'SETUP'}</span>
          </div>
          <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>{r.sector || '—'}</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
          <span style={{ fontSize: 26, color: 'var(--pump-lime)', fontWeight: 600, letterSpacing: '-0.02em', lineHeight: 1, fontFamily: 'var(--f-mono)' }}>{score}</span>
          <span style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>/ 20</span>
        </div>
      </div>
      <div style={{ position: 'relative', background: 'var(--bg-2)', borderRadius: 'var(--r-md)', padding: '8px 10px', overflow: 'hidden', minHeight: 58 }}>
        <Sparkline width={268} height={42} data={sparkData} color={sparkColor} />
        {scoreHistory?.length >= 2 && (
          <div style={{ position: 'absolute', bottom: 6, left: 10, fontSize: 9, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.06em' }}>
            SCORE HIST · {scoreHistory.length}d
          </div>
        )}
        <div style={{ position: 'absolute', top: 8, right: 12, display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: 14, color: 'var(--ink)', fontWeight: 500, fontFamily: 'var(--f-mono)' }}>${fmt(price, 2)}</span>
          {chgPct != null && <span style={{ fontSize: 11, color: chgUp ? 'var(--pos)' : 'var(--neg)', fontFamily: 'var(--f-mono)' }}>{chgUp ? '▲' : '▼'} {Math.abs(chgPct).toFixed(2)}%</span>}
        </div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: 10, color: 'var(--ink-dim)', textTransform: 'uppercase', letterSpacing: '0.08em', fontFamily: 'var(--f-mono)' }}>ATS</span>
          <span style={{ color: 'var(--pump-lime)', fontSize: 12, letterSpacing: '0.06em' }}>{'★'.repeat(atsRating)}{'☆'.repeat(3-atsRating)}</span>
        </div>
        {r.readiness_tier && <>
          <span style={{ width: 1, height: 14, background: 'var(--stroke-soft)' }} />
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 10, color: tempColor, letterSpacing: '0.1em', fontFamily: 'var(--f-mono)' }}>{readTemp}</span>
            <div style={{ display: 'flex', gap: 2 }}>
              {[1,2,3,4,5].map(n => <span key={n} style={{ width: 8, height: 4, borderRadius: 1, background: n <= tempLvl ? tempColor : 'var(--bg-3)' }} />)}
            </div>
          </div>
        </>}
      </div>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {criteria.map((c, i) => <span key={i} style={{ fontSize: 10, padding: '3px 7px', borderRadius: 'var(--r-pill)', background: 'color-mix(in oklch, var(--pump-blue) 22%, transparent)', color: 'var(--pump-blue)', fontFamily: 'var(--f-mono)' }}>{c}</span>)}
      </div>
      <div style={{ borderTop: '1px dashed var(--stroke-soft)', paddingTop: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }} onClick={e => e.stopPropagation()}>
        <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>Vol <span style={{ color: 'var(--ink-mute)' }}>{fmtK(r.volume_today)}</span></span>
        {(journaled || added) ? (
          <span style={{ fontSize: 11, color: 'var(--pos)', fontFamily: 'var(--f-mono)' }}>✓ Journaled</span>
        ) : (
          <button onClick={e => { e.stopPropagation(); onAdd(r); }} disabled={adding} style={{ fontSize: 11, padding: '4px 10px', borderRadius: 'var(--r-pill)', background: 'var(--pump-lime)', color: 'var(--on-lime)', border: 'none', cursor: adding ? 'not-allowed' : 'pointer', fontFamily: 'var(--f-mono)', fontWeight: 600, whiteSpace: 'nowrap' }}>{adding ? '…' : '+ Journal'}</button>
        )}
      </div>
    </div>
  );
}

function PumpSetupGrid({ allResults, livePrices, journaledSet, addingJournal, addedJournal, addToJournal, setDrawerRow, loading, scoreHistMap }) {
  const topSetups = allResults.filter(r => r.demand_composite_tier !== 'SKIP').slice(0, 8);
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <h2 style={{ fontSize: 18, fontWeight: 500, letterSpacing: '-0.01em', margin: 0, color: 'var(--ink)' }}>Top demand setups</h2>
          <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>{topSetups.length} shown · ranked by Pump score</span>
        </div>
      </div>
      {loading ? (
        <div style={{ color: 'var(--ink-dim)', fontSize: 13, padding: '20px 0' }}>Loading setups…</div>
      ) : topSetups.length === 0 ? (
        <div style={{ color: 'var(--ink-dim)', fontSize: 13, padding: '20px 0' }}>No setups — run a scan or check the scanner.</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(290px, 1fr))', gap: 14 }}>
          {topSetups.map(r => (
            <PumpSetupCard key={r.symbol} r={r} livePrice={livePrices[r.symbol]} journaled={journaledSet.has(r.symbol)} adding={addingJournal === r.symbol} added={addedJournal.has(r.symbol)} onAdd={addToJournal} onClick={setDrawerRow} scoreHistory={scoreHistMap?.[r.symbol]} />
          ))}
        </div>
      )}
    </div>
  );
}

function PumpSectorTile({ name, count, perf, topSymbols, lead = false }) {
  const isPos = perf >= 0;
  const intensity = Math.min(Math.abs(perf) / 4, 1);
  const bg = lead
    ? `radial-gradient(ellipse at 100% 0%, oklch(0.96 0.18 125 / 0.5) 0%, transparent 55%), linear-gradient(135deg, color-mix(in oklch, var(--pump-lime) ${55 + intensity * 25}%, var(--bg-1)) 0%, color-mix(in oklch, var(--pump-lime) ${30 + intensity * 15}%, var(--bg-1)) 100%)`
    : isPos ? `color-mix(in oklch, var(--pump-lime) ${10 + intensity * 22}%, var(--bg-1))`
    : `color-mix(in oklch, var(--neg) ${8 + intensity * 20}%, var(--bg-1))`;
  const fg = lead && isPos ? 'var(--on-lime)' : 'var(--ink)';
  const dimFg = lead && isPos ? 'color-mix(in oklch, var(--on-lime) 70%, transparent)' : 'var(--ink-dim)';
  return (
    <div style={{ background: bg, borderRadius: 'var(--r-lg)', padding: lead ? '18px 20px' : '12px 14px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gridColumn: lead ? 'span 2' : 'span 1', gridRow: lead ? 'span 2' : 'span 1', minHeight: lead ? 0 : 100, color: fg, position: 'relative', overflow: 'hidden' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ fontSize: lead ? 15 : 12, fontWeight: 500, letterSpacing: '-0.01em', color: fg }}>{name}</span>
          <span style={{ fontSize: 10, color: dimFg, letterSpacing: '0.06em', fontFamily: 'var(--f-mono)' }}>{count} SETUPS</span>
        </div>
        <span style={{ fontSize: lead ? 24 : 15, color: isPos ? (lead ? fg : 'var(--pos)') : 'var(--neg)', fontWeight: 500, letterSpacing: '-0.01em', whiteSpace: 'nowrap', flexShrink: 0, fontFamily: 'var(--f-mono)' }}>{isPos ? '+' : ''}{perf.toFixed(2)}%</span>
      </div>
      {lead && <Sparkline width={210} height={28} data={sp(name.length * 7, 24, 0.3)} color="var(--on-lime)" />}
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {topSymbols.slice(0, lead ? 5 : 3).map((t, i) => (
          <span key={i} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 'var(--r-pill)', background: lead ? 'color-mix(in oklch, var(--on-lime) 18%, transparent)' : 'var(--bg-2)', color: lead ? fg : 'var(--ink-mute)', fontFamily: 'var(--f-mono)', fontWeight: 500 }}>{t}</span>
        ))}
      </div>
    </div>
  );
}

function PumpSectorHeat({ sectors, allResults, sectorsLoading }) {
  const entries = Object.entries(sectors || {})
    .map(([name, d]) => ({
      name,
      chg: d.change_pct ?? d.change_1d ?? d.pct_change_1d ?? 0,
      count: allResults.filter(r => r.sector === name || r.sector === d.gics_name).length,
      topSyms: allResults.filter(r => r.sector === name || r.sector === d.gics_name).slice(0, 4).map(r => r.symbol),
    }))
    .sort((a, b) => b.chg - a.chg);
  return (
    <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 'var(--r-xl)', padding: '18px 20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <h3 style={{ fontSize: 14, margin: 0, color: 'var(--ink-mute)', fontWeight: 500 }}>Sectors</h3>
          <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>by setup count · close perf</span>
        </div>
      </div>
      {sectorsLoading && entries.length === 0 ? (
        <div style={{ color: 'var(--ink-dim)', fontSize: 12, padding: '20px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: '50%', border: '2px solid var(--pump-lime)', borderTopColor: 'transparent', animation: 'spin 0.8s linear infinite' }} />
          Loading sector data…
        </div>
      ) : entries.length === 0 ? (
        <div style={{ color: 'var(--ink-faint)', fontSize: 12, padding: '20px 0' }}>No sector data — market may be closed</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, gridAutoRows: 'minmax(100px, auto)' }}>
          {entries.slice(0, 1).map(e => <PumpSectorTile key={e.name} name={e.name} count={e.count} perf={e.chg} topSymbols={e.topSyms} lead />)}
          {entries.slice(1, 7).map(e => <PumpSectorTile key={e.name} name={e.name.split(' ')[0]} count={e.count} perf={e.chg} topSymbols={e.topSyms} />)}
        </div>
      )}
    </div>
  );
}

function PumpAtsSignals({ allResults }) {
  const prime = allResults.filter(r => r.ats_signal === 'ATS_PRIME').slice(0, 3);
  const setup = allResults.filter(r => r.ats_signal === 'ATS_SETUP').slice(0, 6);
  const AtsRow = ({ r, tier }) => {
    const toneColor = tier === 'PRIME' ? 'var(--pos)' : 'var(--pump-blue)';
    const score = r.demand_composite_score ?? 0;
    const barPct = Math.min(100, (score / 20) * 100);
    return (
      <div style={{ display: 'grid', gridTemplateColumns: '60px 1fr 52px', alignItems: 'center', padding: '9px 0', gap: 10, borderBottom: '1px solid var(--stroke-soft)' }}>
        <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--ink)' }}>{r.symbol}</span>
        <div style={{ height: 4, borderRadius: 2, background: 'var(--bg-3)', overflow: 'hidden' }}>
          <div style={{ width: `${barPct}%`, height: '100%', background: toneColor, borderRadius: 2 }} />
        </div>
        <span style={{ fontSize: 13, color: toneColor, textAlign: 'right', fontFamily: 'var(--f-mono)', fontWeight: 600 }}>{fmt(score, 1)}</span>
      </div>
    );
  };
  return (
    <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 'var(--r-xl)', padding: '18px 20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <h3 style={{ fontSize: 14, margin: 0, color: 'var(--ink)', fontWeight: 500 }}>ATS signals</h3>
          <span style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.06em' }}>{prime.length} PRIME · {setup.length} SETUP</span>
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        {prime.length > 0 && <>
          <span style={{ fontSize: 10, color: 'var(--pos)', letterSpacing: '0.1em', marginBottom: 2, fontFamily: 'var(--f-mono)' }}>★★★ PRIME · {prime.length}</span>
          {prime.map(r => <AtsRow key={r.symbol} r={r} tier="PRIME" />)}
        </>}
        {setup.length > 0 && <>
          <span style={{ fontSize: 10, color: 'var(--pump-blue)', letterSpacing: '0.1em', marginTop: prime.length ? 12 : 0, marginBottom: 2, fontFamily: 'var(--f-mono)' }}>★★ SETUP · {setup.length}</span>
          {setup.map(r => <AtsRow key={r.symbol} r={r} tier="SETUP" />)}
        </>}
        {prime.length === 0 && setup.length === 0 && <div style={{ color: 'var(--ink-faint)', fontSize: 12, padding: '12px 0', textAlign: 'center' }}>No ATS signals in current scan</div>}
      </div>
    </div>
  );
}

function PumpMoversCard({ kind, livePrices, allResults, marketOpen }) {
  const isUp = kind === 'gainers';
  const tone = isUp ? 'var(--pos)' : 'var(--neg)';
  const enriched = Object.entries(livePrices)
    .filter(([, d]) => d.change_pct != null)
    .map(([sym, d]) => ({ symbol: sym, price: d.price, chg: d.change_pct }));
  const fromResults = allResults
    .filter(r => r.price_change_pct != null || r.dc_range_pct_5d != null)
    .map(r => ({ symbol: r.symbol, price: r.price, chg: r.price_change_pct ?? null }));
  const pool = enriched.length > 0 ? enriched : fromResults;
  const rows = pool.length > 0
    ? [...pool].sort((a, b) => isUp ? (b.chg ?? 0) - (a.chg ?? 0) : (a.chg ?? 0) - (b.chg ?? 0)).slice(0, 10)
    : allResults.slice(isUp ? 0 : Math.max(0, allResults.length - 10)).map(r => ({ symbol: r.symbol, price: r.price, chg: null })).slice(0, 10);
  return (
    <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 'var(--r-xl)', padding: '18px 20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 22, height: 22, borderRadius: '50%', background: `color-mix(in oklch, ${tone} 22%, transparent)`, color: tone, fontSize: 11, fontWeight: 700 }}>{isUp ? '▲' : '▼'}</span>
          <h3 style={{ fontSize: 14, margin: 0, color: 'var(--ink)', fontWeight: 500 }}>{isUp ? 'Top gainers' : 'Top losers'}</h3>
        </div>
        <span style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.06em' }}>{marketOpen ? 'LIVE' : 'LAST CLOSE'}</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
        {rows.length === 0 ? (
          <div style={{ color: 'var(--ink-faint)', fontSize: 12, padding: '12px 0', textAlign: 'center' }}>{marketOpen ? 'Loading prices…' : 'Live data during market hours (9:30–16:00 ET)'}</div>
        ) : rows.map(({ symbol, price, chg }, i) => {
          const maxAbsChg = Math.max(...rows.filter(r => r.chg != null).map(r => Math.abs(r.chg ?? 0)), 1);
          const barW = chg != null ? Math.round((Math.abs(chg) / maxAbsChg) * 100) : 0;
          return (
          <div key={symbol} style={{ display: 'grid', gridTemplateColumns: '56px 1fr 58px 68px', alignItems: 'center', padding: '8px 0', gap: 8, borderBottom: i < rows.length - 1 ? '1px solid var(--stroke-soft)' : 'none' }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{symbol}</span>
            <div style={{ height: 4, borderRadius: 2, background: 'var(--bg-3)', overflow: 'hidden' }}>
              <div style={{ width: `${barW}%`, height: '100%', background: tone, borderRadius: 2 }} />
            </div>
            <span style={{ fontSize: 12, color: 'var(--ink-mute)', textAlign: 'right', fontFamily: 'var(--f-mono)' }}>${fmt(price, 2)}</span>
            <span style={{ fontSize: 12, color: chg != null ? tone : 'var(--ink-dim)', textAlign: 'right', fontWeight: 600, fontFamily: 'var(--f-mono)' }}>{chg != null ? `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%` : '—'}</span>
          </div>
          );
        })}
      </div>
    </div>
  );
}

function PumpHypeMonitor({ hypeStatus, hypeResults }) {
  const hot       = hypeStatus?.hot_tickers || [];
  const divCount  = hypeStatus?.total_divergences ?? 0;
  const hypeLabel = divCount > 20 ? 'HOT' : divCount > 10 ? 'WARM' : 'COOL';
  const monitored = hypeStatus?.tickers_monitored ?? 0;
  const volSurge  = hypeStatus?.avg_vol_surge ?? 0;
  const mentions  = hypeStatus?.social_count ?? 0;
  return (
    <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 'var(--r-xl)', padding: '18px 22px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <h3 style={{ fontSize: 14, margin: 0, color: 'var(--ink-mute)', fontWeight: 500 }}>Hype monitor</h3>
          <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>volume/social momentum · last 24h</span>
        </div>
        <span style={{ fontSize: 11, padding: '3px 10px', borderRadius: 'var(--r-pill)', background: 'var(--bg-2)', border: '1px solid var(--stroke-soft)', color: 'var(--ink-mute)', fontFamily: 'var(--f-mono)' }}>{hypeLabel} · {divCount}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 10, color: 'var(--ink-dim)', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--f-mono)' }}>Vol surge</span>
          <span style={{ fontSize: 24, color: 'var(--pump-lime)', fontWeight: 500, fontFamily: 'var(--f-mono)' }}>{volSurge > 0 ? `+${volSurge}%` : '—'}</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 10, color: 'var(--ink-dim)', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--f-mono)' }}>Social mentions</span>
          <span style={{ fontSize: 24, color: 'var(--pump-blue)', fontWeight: 500, fontFamily: 'var(--f-mono)' }}>{mentions > 0 ? mentions.toLocaleString() : '—'}</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 10, color: 'var(--ink-dim)', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--f-mono)' }}>Monitored</span>
          <span style={{ fontSize: 24, color: 'var(--ink)', fontWeight: 500, fontFamily: 'var(--f-mono)' }}>{monitored || '—'}</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ fontSize: 10, color: 'var(--ink-dim)', textTransform: 'uppercase', letterSpacing: '0.1em', fontFamily: 'var(--f-mono)' }}>Hot tickers</span>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
            {hot.slice(0, 6).map(t => <span key={t} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 'var(--r-pill)', background: 'var(--pump-lime-soft)', color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontWeight: 600 }}>{t}</span>)}
            {hot.length === 0 && <span style={{ fontSize: 12, color: 'var(--ink-faint)' }}>—</span>}
          </div>
        </div>
      </div>
    </div>
  );
}

function PumpNewsGrid({ news, newsLoading }) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <h2 style={{ fontSize: 18, fontWeight: 500, letterSpacing: '-0.01em', margin: 0, color: 'var(--ink)' }}>Market news</h2>
          <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>top picks · ranked by ticker relevance</span>
        </div>
      </div>
      {newsLoading ? (
        <div style={{ color: 'var(--ink-dim)', fontSize: 12, padding: '12px 0' }}>Loading news…</div>
      ) : !news?.length ? (
        <div style={{ color: 'var(--ink-dim)', fontSize: 12, padding: '12px 0' }}>No news available for current top picks</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 12 }}>
          {news.slice(0, 10).map((a, i) => {
            const tickers = (a.tickers || []).slice(0, 4);
            const src = a.publisher?.name || a.source || '';
            const age = fmtAge(a.published_utc);
            return (
              <a key={a.id || i} href={a.article_url || '#'} target="_blank" rel="noopener noreferrer" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'space-between', textDecoration: 'none', background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 'var(--r-lg)', padding: '14px 16px', minHeight: 120, transition: 'border-color 0.15s' }}
                onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--pump-blue)'}
                onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--stroke-soft)'}
              >
                <p style={{ margin: '0 0 10px', fontSize: 12, lineHeight: 1.4, color: 'var(--ink)', fontWeight: 500 }}>{a.title}</p>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {tickers.map((t, ti) => <span key={ti} style={{ fontSize: 10, padding: '2px 7px', borderRadius: 'var(--r-pill)', background: ti === 0 ? 'var(--pump-lime-soft)' : 'color-mix(in oklch, var(--pump-blue) 22%, transparent)', color: ti === 0 ? 'var(--pump-lime)' : 'var(--pump-blue)', fontFamily: 'var(--f-mono)', fontWeight: 500 }}>{t}</span>)}
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: 10, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)' }}>{src}</span>
                    <span style={{ fontSize: 10, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)' }}>{age}</span>
                  </div>
                </div>
              </a>
            );
          })}
        </div>
      )}
    </div>
  );
}

function PumpFooterCta({ allResults, setShowFullTable }) {
  return (
    <div style={{ padding: '16px 20px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-1)', border: '1px dashed var(--stroke)', borderRadius: 'var(--r-xl)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <NavIcon name="filter" size={16} color="var(--ink-mute)" />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          <span style={{ fontSize: 13, color: 'var(--ink)' }}>Show full scanner</span>
          <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>{allResults.length} results · universe</span>
        </div>
      </div>
      <button onClick={() => setShowFullTable(s => !s)} style={{ fontSize: 12, padding: '7px 16px', borderRadius: 'var(--r-pill)', background: 'var(--pump-lime)', color: 'var(--on-lime)', border: 'none', cursor: 'pointer', fontWeight: 600, fontFamily: 'var(--f-mono)', display: 'flex', alignItems: 'center', gap: 6 }}>
        Open scanner <NavIcon name="right" size={14} color="var(--on-lime)" />
      </button>
    </div>
  );
}

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
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    if (!symbol) return;
    setLoading(true);
    fetch(`${API_URL}/api/demand-scanner/history/${symbol}?limit=30`)
      .then(r => r.json())
      .then(d => setHist((d.history || []).reverse()))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [symbol]);

  if (loading) return <div style={{ fontSize: 11, color: 'var(--ink-faint)', padding: '8px 0' }}>Loading history…</div>;
  if (hist.length < 2) return <div style={{ fontSize: 11, color: 'var(--ink-faint)', padding: '8px 0' }}>No score history yet</div>;

  const scores = hist.map(h => h.combined_score ?? h.demand_composite_score ?? 0);
  const maxScore = Math.max(...scores, 1);
  const minScore = Math.min(...scores, 0);
  const range = maxScore - minScore || 1;
  const W = 360, H = 72, padX = 4, padY = 6;
  const pts = hist.map((h, i) => {
    const s = h.combined_score ?? h.demand_composite_score ?? 0;
    const x = padX + (i / (hist.length - 1)) * (W - padX * 2);
    const y = H - padY - ((s - minScore) / range) * (H - padY * 2);
    return [x, y, h, s];
  });
  const pathD = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const areaD = pathD + ` L${pts[pts.length-1][0].toFixed(1)},${H} L${pts[0][0].toFixed(1)},${H} Z`;
  const last = pts[pts.length - 1];
  return (
    <div style={{ marginTop: 6 }}>
      <svg width={W} height={H} style={{ display: 'block', overflow: 'visible', width: '100%' }} viewBox={`0 0 ${W} ${H}`}>
        <defs>
          <linearGradient id={`hist-grad-${symbol}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--pump-lime)" stopOpacity="0.25" />
            <stop offset="100%" stopColor="var(--pump-lime)" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={areaD} fill={`url(#hist-grad-${symbol})`} />
        <path d={pathD} fill="none" stroke="var(--pump-lime)" strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
        {pts.map(([x, y, h, s], i) => (
          <circle key={i} cx={x} cy={y} r={i === pts.length - 1 ? 4 : 2.5}
            fill={i === pts.length - 1 ? 'var(--pump-lime)' : (TIER_COLORS_MINI[h.demand_composite_tier] || 'var(--stroke)')}
            stroke="var(--bg-1)" strokeWidth={i === pts.length - 1 ? 1.5 : 0}
          >
            <title>{h.scanned_at?.slice(0,10)} · score {s?.toFixed(1)}</title>
          </circle>
        ))}
        <text x={last[0]} y={last[1] - 8} fontSize={9} fill="var(--pump-lime)" textAnchor="middle" fontFamily="var(--f-mono)">{last[3]?.toFixed(1)}</text>
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3 }}>
        <span style={{ fontSize: 9, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)' }}>{hist[0]?.scanned_at?.slice(5,10)}</span>
        <span style={{ fontSize: 9, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>{hist.length} scans</span>
        <span style={{ fontSize: 9, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)' }}>{hist[hist.length-1]?.scanned_at?.slice(5,10)}</span>
      </div>
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
  const [sectors,        setSectors]        = useState({});
  const [sectorsLoading, setSectorsLoading] = useState(true);
  const [news,        setNews]        = useState([]);
  const [newsLoading, setNewsLoading] = useState(false);

  // Score history for sparklines
  const [scoreHistMap, setScoreHistMap] = useState({});

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
    setSectorsLoading(true);
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
      if (secRes?.ok) {
        const secData = await secRes.json();
        setSectors(typeof secData === 'object' && !Array.isArray(secData) ? secData : {});
      }
    } catch { /* optional */ }
    finally { setSectorsLoading(false); }
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

  // Score history for top 8 setup sparklines
  useEffect(() => {
    if (!data?.results?.length) return;
    const top8 = data.results.filter(r => r.demand_composite_tier !== 'SKIP').slice(0, 8);
    const missing = top8.filter(r => !scoreHistMap[r.symbol]);
    if (!missing.length) return;
    missing.forEach(r => {
      fetch(`${API_URL}/api/demand-scanner/history/${r.symbol}?limit=20`)
        .then(res => res.ok ? res.json() : { history: [] })
        .then(d => {
          const pts = (d.history || []).reverse().map(h => h.combined_score ?? h.demand_composite_score ?? 0);
          if (pts.length >= 2) setScoreHistMap(prev => ({ ...prev, [r.symbol]: pts }));
        })
        .catch(() => {});
    });
  }, [data?.results]); // eslint-disable-line

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
      <div style={{ minHeight: '100vh', background: 'var(--bg-0)', display: 'flex' }}>
        <LeftSidebar />
        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
          <TopBar marketTimer={marketTimer} regime={regime} />
          <main style={{ padding: '22px 24px', display: 'flex', flexDirection: 'column', gap: 14, minWidth: 1020 }}>

            {error && (
              <div style={{ padding: '10px 14px', background: 'oklch(0.72 0.21 25 / 0.10)', border: '1px solid oklch(0.72 0.21 25 / 0.30)', borderRadius: 8, color: 'var(--neg)', fontSize: 12 }}>{error}</div>
            )}

            {/* Row 1: Hero (lime) + Funnel (blue) */}
            <div style={{ display: 'grid', gridTemplateColumns: '1.8fr 1fr', gap: 14 }}>
              <HeroRead allResults={allResults} tc={tc} hypeStatus={hypeStatus} sectors={sectors} loading={loading} />
              <FunnelCard tc={tc} ac={ac} data={data} loading={loading} />
            </div>

            {/* KPI strip */}
            <KpiStrip tc={tc} ac={ac} data={data} loading={loading} />

            {/* Top demand setups grid */}
            <PumpSetupGrid
              allResults={allResults} livePrices={livePrices} journaledSet={journaledSet}
              addingJournal={addingJournal} addedJournal={addedJournal}
              addToJournal={addToJournal} setDrawerRow={setDrawerRow} loading={loading}
              scoreHistMap={scoreHistMap}
            />

            {/* Sectors + ATS Signals */}
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 14, alignItems: 'start' }}>
              <PumpSectorHeat sectors={sectors} allResults={allResults} sectorsLoading={sectorsLoading} />
              <PumpAtsSignals allResults={allResults} />
            </div>

            {/* Gainers + Losers */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <PumpMoversCard kind="gainers" livePrices={livePrices} allResults={allResults} marketOpen={marketTimer.open} />
              <PumpMoversCard kind="losers"  livePrices={livePrices} allResults={allResults} marketOpen={marketTimer.open} />
            </div>

            {/* Hype Monitor */}
            <PumpHypeMonitor hypeStatus={hypeStatus} hypeResults={hypeResults} />

            {/* News */}
            <PumpNewsGrid news={news} newsLoading={newsLoading} />

            {/* Footer / scanner CTA */}
            <PumpFooterCta allResults={allResults} setShowFullTable={setShowFullTable} />

            {/* Full scanner table (toggled by footer CTA) */}
            {showFullTable && (
              <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 10, padding: '14px 16px' }}>
                <ScannerTable
                  results={allResults} livePrices={livePrices}
                  journaledSet={journaledSet} addingJournal={addingJournal} addedJournal={addedJournal}
                  onAddToJournal={addToJournal} onRowClick={setDrawerRow}
                  tierF={tierF} setTierF={setTierF}
                  atsF={atsF} setAtsF={setAtsF}
                  readyF={readyF} setReadyF={setReadyF}
                  minScore={minScore} setMinScore={setMinScore}
                  limit={limit} setLimit={setLimit}
                  onRefresh={fetchData} triggerScan={triggerScan}
                  scanning={scanning} scanProgress={scanProgress} scanError={scanError}
                />
              </div>
            )}
          </main>
        </div>
      </div>

      {/* Detail drawer */}
      {drawerRow && (
        <>
          <div onClick={() => setDrawerRow(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)', zIndex: 999 }} />
          <DetailDrawer
            row={drawerRow} onClose={() => setDrawerRow(null)}
            narrative={narratives[drawerRow?.symbol]}
            narrativeLoading={narrativeLoading === drawerRow?.symbol}
            onFetchNarrative={fetchNarrative}
          />
        </>
      )}
    </>
  );
}
