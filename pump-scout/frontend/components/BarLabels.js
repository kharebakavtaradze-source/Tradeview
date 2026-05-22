/**
 * BarLabels — Per-bar T/Z/WLNBB/PREUP + Line3/4/5 (260521) combined signal labels.
 * Fetches from /api/bar-labels/{symbol} and renders a compact dark-mode table.
 */
import { useEffect, useState } from 'react';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ── Chip colors ───────────────────────────────────────────────────────────────

const BUCKET_COLORS = {
  W:  { bg: '#1e3a5f', color: '#93c5fd' },
  L:  { bg: '#0f3a3a', color: '#22d3ee' },
  N:  { bg: '#3a2e00', color: '#fbbf24' },
  B:  { bg: '#3a1a00', color: '#fb923c' },
  VB: { bg: '#3a0a0a', color: '#f87171' },
  '?':{ bg: '#1f2937', color: '#6b7280' },
};

const BODY_COLOR = {
  X: { bg: '#1c1b4b', color: '#a5b4fc' },
  M: { bg: '#1a2535', color: '#93c5fd' },
  S: { bg: '#0e2030', color: '#7dd3fc' },
};

const WICK_COLOR = {
  TB: { bg: '#14532d', color: '#86efac' },
  BB: { bg: '#2d0a0a', color: '#f87171' },
  J:  { bg: '#3a2e00', color: '#fbbf24' },
  F:  { bg: '#1f2937', color: '#9ca3af' },
};

const GAP_COLOR = {
  G1: { bg: '#042f2e', color: '#2dd4bf' },
  G2: { bg: '#063a2a', color: '#34d399' },
  G3: { bg: '#052e16', color: '#86efac' },
};

const RANGE_COLOR = {
  V: { bg: '#1c1b4b', color: '#a5b4fc' },
  N: { bg: '#1f2937', color: '#6b7280' },
  C: { bg: '#3a1a00', color: '#fb923c' },
};

const VIX_COLOR = {
  VX: { bg: '#2d0a0a', color: '#f87171' },
  VR: { bg: '#3a2e00', color: '#fbbf24' },
};

const PSAR_COLOR = {
  PB: { bg: '#052e16', color: '#4ade80' },
  PS: { bg: '#2d0a0a', color: '#fb923c' },
};

const RSI2_COLOR = {
  R2X: { bg: '#052e16', color: '#86efac' },
  R2D: { bg: '#2d0a0a', color: '#f87171' },
  R2L: { bg: '#063a2a', color: '#34d399' },
  R2H: { bg: '#3a0a0a', color: '#fca5a5' },
};

// ── Chip ──────────────────────────────────────────────────────────────────────

function Chip({ text, bg, color, title }) {
  if (!text) return null;
  return (
    <span
      title={title}
      style={{
        display: 'inline-block',
        padding: '1px 5px',
        borderRadius: 3,
        fontSize: 9,
        fontWeight: 700,
        fontFamily: 'var(--font-mono, monospace)',
        letterSpacing: '0.04em',
        background: bg || '#1f2937',
        color: color || '#9ca3af',
        border: `1px solid ${color ? color + '44' : '#374151'}`,
        whiteSpace: 'nowrap',
        lineHeight: 1.4,
      }}
    >
      {text}
    </span>
  );
}

function BucketChip({ bucket }) {
  const cfg = BUCKET_COLORS[bucket] || BUCKET_COLORS['?'];
  return <Chip text={bucket} bg={cfg.bg} color={cfg.color} title={`Volume bucket: ${bucket}`} />;
}

function CandleArrow({ bar }) {
  if (bar.is_bull)
    return <span style={{ color: '#86efac', fontSize: 11, fontWeight: 700 }}>▲</span>;
  if (bar.is_bear)
    return <span style={{ color: '#f87171', fontSize: 11, fontWeight: 700 }}>▼</span>;
  return <span style={{ color: '#9ca3af', fontSize: 11 }}>—</span>;
}

// ── Line3/4/5 cells ───────────────────────────────────────────────────────────

function Line3Cell({ bar }) {
  const bc = BODY_COLOR[bar.body_class] || { bg: '#1f2937', color: '#6b7280' };
  const wc = WICK_COLOR[bar.wick_class];
  return (
    <div style={{ display: 'flex', gap: 2, flexWrap: 'nowrap' }}>
      {bar.body_class && (
        <Chip text={bar.body_class} bg={bc.bg} color={bc.color} title={`Body size: ${bar.body_class}`} />
      )}
      {bar.wick_class && wc && (
        <Chip text={bar.wick_class} bg={wc.bg} color={wc.color} title={`Wick class: ${bar.wick_class}`} />
      )}
    </div>
  );
}

function Line4Cell({ bar }) {
  const gc = GAP_COLOR[bar.gap_class];
  const rc = RANGE_COLOR[bar.range_class] || { bg: '#1f2937', color: '#6b7280' };
  return (
    <div style={{ display: 'flex', gap: 2, flexWrap: 'nowrap' }}>
      {bar.gap_class && gc && (
        <Chip text={bar.gap_class} bg={gc.bg} color={gc.color} title={`Gap ATR-relative: ${bar.gap_class}`} />
      )}
      {bar.range_class && (
        <Chip text={bar.range_class} bg={rc.bg} color={rc.color} title={`Range vs ATR: ${bar.range_class}`} />
      )}
    </div>
  );
}

function Line5Cell({ bar }) {
  const vc = VIX_COLOR[bar.vix_token];
  const pc = PSAR_COLOR[bar.psar_token];
  const rc = RSI2_COLOR[bar.rsi2_token];
  return (
    <div style={{ display: 'flex', gap: 2, flexWrap: 'nowrap' }}>
      {bar.vix_token && vc && (
        <Chip text={bar.vix_token} bg={vc.bg} color={vc.color} title={`Williams VIX-Fix: ${bar.vix_token}`} />
      )}
      {bar.psar_token && pc && (
        <Chip text={bar.psar_token} bg={pc.bg} color={pc.color} title={`PSAR: ${bar.psar_token}`} />
      )}
      {bar.rsi2_token && rc && (
        <Chip text={bar.rsi2_token} bg={rc.bg} color={rc.color} title={`RSI2: ${bar.rsi2_token}`} />
      )}
    </div>
  );
}

// ── Export helpers ────────────────────────────────────────────────────────────

function downloadJson(payload, filename) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadCsv(bars, symbol) {
  if (!bars.length) return;
  const COLS = [
    'date','o','h','l','c','v','is_bull','is_bear','bucket',
    't_signal','z_signal','l_digits','preup','predn',
    'ne','wick','pen','close_suf','append_close','label',
    'body_class','wick_class','line3',
    'gap_class','range_class','line4',
    'vix_token','psar_token','rsi2_token','line5',
  ];
  const header = COLS.join(',');
  const rows = bars.map(b =>
    COLS.map(k => {
      const v = b[k] ?? '';
      const s = String(v);
      return s.includes(',') || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(',')
  );
  const csv = [header, ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `bar-labels-${symbol}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Grid layout constants ─────────────────────────────────────────────────────

const GRID = '64px 18px 28px 42px 42px 36px 40px 40px 52px 70px 68px 90px';
const HEADERS = ['Date', '', 'Bkt', 'T', 'Z', 'L', 'PREUP', 'PREDN', 'Suffix', 'L3 Body+Wick', 'L4 Gap+Rng', 'L5 VIX/SAR/RSI2'];

// ── Filter helpers ────────────────────────────────────────────────────────────

const FILTER_GROUPS = [
  { key: 'body_class',  label: 'Body',  values: ['X', 'M', 'S'],              colorMap: BODY_COLOR },
  { key: 'wick_class',  label: 'Wick',  values: ['TB', 'BB', 'J', 'F'],       colorMap: WICK_COLOR },
  { key: 'gap_class',   label: 'Gap',   values: ['G1', 'G2', 'G3'],           colorMap: GAP_COLOR },
  { key: 'range_class', label: 'Range', values: ['V', 'N', 'C'],              colorMap: RANGE_COLOR },
  { key: 'vix_token',   label: 'VIX',   values: ['VX', 'VR'],                 colorMap: VIX_COLOR },
  { key: 'psar_token',  label: 'PSAR',  values: ['PB', 'PS'],                 colorMap: PSAR_COLOR },
  { key: 'rsi2_token',  label: 'RSI2',  values: ['R2X', 'R2D', 'R2L', 'R2H'],colorMap: RSI2_COLOR },
];

function filterBars(bars, activeFilters) {
  if (Object.keys(activeFilters).length === 0) return bars;
  return bars.filter(bar =>
    Object.entries(activeFilters).every(([key, vals]) =>
      vals.length === 0 || vals.includes(bar[key] || '')
    )
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function BarLabels({ symbol, barsOverride }) {
  const [data,          setData]          = useState(null);
  const [loading,       setLoading]       = useState(false);
  const [error,         setError]         = useState('');
  const [activeFilters, setActiveFilters] = useState({});

  const bars_param = barsOverride || 60;

  function toggleFilter(key, val) {
    setActiveFilters(prev => {
      const current = prev[key] || [];
      const next = current.includes(val) ? current.filter(v => v !== val) : [...current, val];
      if (next.length === 0) {
        const { [key]: _, ...rest } = prev;
        return rest;
      }
      return { ...prev, [key]: next };
    });
  }

  function clearFilters() { setActiveFilters({}); }

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    setData(null);

    fetch(`${API_URL}/api/bar-labels/${encodeURIComponent(symbol)}?bars=${bars_param}`)
      .then(r => r.json().then(d => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (cancelled) return;
        if (!ok) throw new Error(d.detail || `HTTP error`);
        setData(d);
      })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [symbol, bars_param]);

  if (loading) {
    return (
      <div style={{ padding: '16px 12px', color: '#9ca3af', fontSize: 12 }}>
        Loading bar labels…
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: '12px', color: '#f87171', fontSize: 12 }}>
        {error}
      </div>
    );
  }

  if (!data) return null;

  const allBars = [...(data.bars || [])].reverse();
  const bars    = filterBars(allBars, activeFilters);
  const hasFilters = Object.keys(activeFilters).length > 0;

  return (
    <div style={{
      background: '#111827',
      border: '1px solid #1f2937',
      borderRadius: 6,
      overflow: 'hidden',
      width: '100%',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '7px 10px',
        borderBottom: '1px solid #1f2937',
        background: '#0d1117',
      }}>
        <span style={{
          fontSize: 11,
          fontWeight: 700,
          color: '#e5e7eb',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          fontFamily: 'var(--font-mono, monospace)',
        }}>
          {data.symbol}
        </span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 10, color: '#6b7280' }}>{data.total} bars</span>
          <button
            onClick={() => downloadJson(data, `bar-labels-${data.symbol}.json`)}
            title="Download full JSON"
            style={{
              fontSize: 10, padding: '2px 7px', borderRadius: 4, cursor: 'pointer',
              background: '#1f2937', color: '#93c5fd', border: '1px solid #374151',
              fontFamily: 'var(--font-mono, monospace)', fontWeight: 600,
            }}
          >↓ JSON</button>
          <button
            onClick={() => downloadCsv(hasFilters ? bars : allBars, data.symbol)}
            title={hasFilters ? `Download filtered CSV (${bars.length} bars)` : 'Download CSV'}
            style={{
              fontSize: 10, padding: '2px 7px', borderRadius: 4, cursor: 'pointer',
              background: '#1f2937', color: '#4ade80', border: '1px solid #374151',
              fontFamily: 'var(--font-mono, monospace)', fontWeight: 600,
            }}
          >↓ CSV</button>
        </div>
      </div>

      {/* Filter chips */}
      <div style={{
        padding: '6px 10px',
        borderBottom: '1px solid #1f2937',
        background: '#0a0f1a',
        display: 'flex',
        flexWrap: 'wrap',
        gap: 6,
        alignItems: 'center',
      }}>
        {FILTER_GROUPS.map(grp => (
          <div key={grp.key} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            <span style={{ fontSize: 8, color: '#4b5563', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em', marginRight: 1 }}>
              {grp.label}
            </span>
            {grp.values.map(val => {
              const isActive = (activeFilters[grp.key] || []).includes(val);
              const cfg = grp.colorMap[val] || { bg: '#1f2937', color: '#9ca3af' };
              return (
                <button
                  key={val}
                  onClick={() => toggleFilter(grp.key, val)}
                  title={`Filter by ${val}`}
                  style={{
                    padding: '1px 5px', borderRadius: 3, cursor: 'pointer',
                    fontSize: 9, fontWeight: 700, fontFamily: 'var(--font-mono, monospace)',
                    letterSpacing: '0.04em', lineHeight: 1.4, whiteSpace: 'nowrap',
                    background: isActive ? cfg.bg : '#111827',
                    color: isActive ? cfg.color : '#374151',
                    border: `1px solid ${isActive ? cfg.color + '66' : '#1f2937'}`,
                    opacity: isActive ? 1 : 0.55,
                    transition: 'all 0.1s',
                  }}
                >{val}</button>
              );
            })}
          </div>
        ))}
        {hasFilters && (
          <button
            onClick={clearFilters}
            style={{
              marginLeft: 4, padding: '1px 7px', borderRadius: 3, cursor: 'pointer',
              fontSize: 9, fontWeight: 700, background: '#1f2937', color: '#f87171',
              border: '1px solid #374151', fontFamily: 'var(--font-mono, monospace)',
            }}
          >✕ clear</button>
        )}
        {hasFilters && (
          <span style={{ fontSize: 9, color: '#6b7280', marginLeft: 4 }}>
            {bars.length} / {allBars.length} bars
          </span>
        )}
      </div>

      {/* Column headers */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: GRID,
        gap: 3,
        padding: '4px 8px',
        borderBottom: '1px solid #1f2937',
        background: '#0d1117',
      }}>
        {HEADERS.map((h, i) => (
          <div key={i} style={{ fontSize: 9, color: '#4b5563', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
            {h}
          </div>
        ))}
      </div>

      {/* Rows */}
      <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: 480 }}>
        {bars.length === 0 && (
          <div style={{ padding: '12px', color: '#6b7280', fontSize: 11 }}>No bars.</div>
        )}
        {bars.map((bar, i) => {
          const rowBg = i % 2 === 0 ? 'transparent' : 'rgba(31,41,55,0.3)';
          return (
            <div
              key={i}
              title={`O:${bar.o} H:${bar.h} L:${bar.l} C:${bar.c} V:${bar.v}`}
              style={{
                display: 'grid',
                gridTemplateColumns: GRID,
                gap: 3,
                padding: '3px 8px',
                alignItems: 'center',
                borderBottom: '1px solid #1a2130',
                background: rowBg,
              }}
            >
              {/* Date */}
              <div style={{
                fontSize: 9, color: '#6b7280',
                fontFamily: 'var(--font-mono, monospace)',
                whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
              }}>
                {bar.date || '—'}
              </div>

              {/* Candle direction */}
              <div style={{ textAlign: 'center' }}>
                <CandleArrow bar={bar} />
              </div>

              {/* Bucket */}
              <div><BucketChip bucket={bar.bucket} /></div>

              {/* T signal */}
              <div>
                {bar.t_signal
                  ? <Chip text={bar.t_signal} bg="#052e16" color="#86efac" title="Bull T signal" />
                  : null}
              </div>

              {/* Z signal */}
              <div>
                {bar.z_signal
                  ? <Chip text={bar.z_signal} bg="#2d0a0a" color="#f87171" title="Bear Z signal" />
                  : null}
              </div>

              {/* L digits */}
              <div>
                {bar.l_digits
                  ? <Chip text={'L' + bar.l_digits} bg="#042f2e" color="#2dd4bf" title="WLNBB L digits" />
                  : null}
              </div>

              {/* PREUP */}
              <div>
                {bar.preup
                  ? <Chip text={bar.preup} bg="#052e16" color="#4ade80" title="PREUP EMA cross" />
                  : null}
              </div>

              {/* PREDN */}
              <div>
                {bar.predn
                  ? <Chip text={bar.predn} bg="#2d0a0a" color="#fb923c" title="PREDN EMA drop" />
                  : null}
              </div>

              {/* Suffix */}
              <div style={{
                fontSize: 9, color: '#6b7280',
                fontFamily: 'var(--font-mono, monospace)',
                whiteSpace: 'nowrap',
              }}>
                {(bar.ne || '') + (bar.wick || '') + (bar.pen || '') + (bar.append_close ? (bar.close_suf || '') : '')}
              </div>

              {/* L3: Body + Wick */}
              <div><Line3Cell bar={bar} /></div>

              {/* L4: Gap + Range */}
              <div><Line4Cell bar={bar} /></div>

              {/* L5: VIX / PSAR / RSI2 */}
              <div><Line5Cell bar={bar} /></div>
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div style={{
        display: 'flex', flexWrap: 'wrap', gap: 6, padding: '6px 10px',
        borderTop: '1px solid #1f2937', background: '#0d1117',
      }}>
        {[
          { text: 'X',   bg: BODY_COLOR.X.bg,  color: BODY_COLOR.X.color,  title: 'Body X: Extra-large (≥1.5× previous bar body)' },
          { text: 'M',   bg: BODY_COLOR.M.bg,  color: BODY_COLOR.M.color,  title: 'Body M: Micro/Minimal (≤0.5× previous bar body — tiny body)' },
          { text: 'S',   bg: BODY_COLOR.S.bg,  color: BODY_COLOR.S.color,  title: 'Body S: Standard/Normal (between 0.5× and 1.5× previous bar body)' },
          { text: 'TB',  bg: WICK_COLOR.TB.bg, color: WICK_COLOR.TB.color, title: 'Top wick dominant' },
          { text: 'BB',  bg: WICK_COLOR.BB.bg, color: WICK_COLOR.BB.color, title: 'Bottom wick dominant' },
          { text: 'J',   bg: WICK_COLOR.J.bg,  color: WICK_COLOR.J.color,  title: 'Doji — tiny body' },
          { text: 'F',   bg: WICK_COLOR.F.bg,  color: WICK_COLOR.F.color,  title: 'Full body, small wicks' },
          { text: 'G1',  bg: GAP_COLOR.G1.bg,  color: GAP_COLOR.G1.color,  title: 'Gap <0.5 ATR' },
          { text: 'G2',  bg: GAP_COLOR.G2.bg,  color: GAP_COLOR.G2.color,  title: 'Gap 0.5–1.0 ATR' },
          { text: 'G3',  bg: GAP_COLOR.G3.bg,  color: GAP_COLOR.G3.color,  title: 'Gap >1.0 ATR' },
          { text: 'V',   bg: RANGE_COLOR.V.bg, color: RANGE_COLOR.V.color, title: 'Range: Volatile (>1.5 ATR)' },
          { text: 'N',   bg: RANGE_COLOR.N.bg, color: RANGE_COLOR.N.color, title: 'Range: Normal' },
          { text: 'C',   bg: RANGE_COLOR.C.bg, color: RANGE_COLOR.C.color, title: 'Range: Compressed (<0.5 ATR)' },
          { text: 'VX',  bg: VIX_COLOR.VX.bg,  color: VIX_COLOR.VX.color,  title: 'Williams VIX-Fix spike' },
          { text: 'VR',  bg: VIX_COLOR.VR.bg,  color: VIX_COLOR.VR.color,  title: 'Williams VIX-Fix range' },
          { text: 'PB',  bg: PSAR_COLOR.PB.bg, color: PSAR_COLOR.PB.color, title: 'PSAR: Price above SAR (bullish)' },
          { text: 'PS',  bg: PSAR_COLOR.PS.bg, color: PSAR_COLOR.PS.color, title: 'PSAR: Price below SAR (bearish)' },
          { text: 'R2X', bg: RSI2_COLOR.R2X.bg,color: RSI2_COLOR.R2X.color,title: 'RSI2: Reclaim above 20' },
          { text: 'R2D', bg: RSI2_COLOR.R2D.bg,color: RSI2_COLOR.R2D.color,title: 'RSI2: Drop below 80' },
          { text: 'R2L', bg: RSI2_COLOR.R2L.bg,color: RSI2_COLOR.R2L.color,title: 'RSI2: Below 20 (oversold)' },
          { text: 'R2H', bg: RSI2_COLOR.R2H.bg,color: RSI2_COLOR.R2H.color,title: 'RSI2: Above 80 (overbought)' },
        ].map(cfg => (
          <Chip key={cfg.text} text={cfg.text} bg={cfg.bg} color={cfg.color} title={cfg.title} />
        ))}
      </div>
    </div>
  );
}
