/**
 * BarLabels — Per-bar T/Z/WLNBB/PREUP combined signal labels.
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

// ── Main component ────────────────────────────────────────────────────────────

export default function BarLabels({ symbol }) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState('');

  useEffect(() => {
    if (!symbol) return;
    let cancelled = false;
    setLoading(true);
    setError('');
    setData(null);

    fetch(`${API_URL}/api/bar-labels/${encodeURIComponent(symbol)}?bars=60`)
      .then(r => r.json().then(d => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (cancelled) return;
        if (!ok) throw new Error(d.detail || `HTTP error`);
        setData(d);
      })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [symbol]);

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

  // Reverse so most recent bar is at the top
  const bars = [...(data.bars || [])].reverse();

  return (
    <div style={{
      background: '#111827',
      border: '1px solid #1f2937',
      borderRadius: 6,
      overflow: 'hidden',
      maxWidth: 440,
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
        <span style={{ fontSize: 10, color: '#6b7280' }}>
          {data.total} bars
        </span>
      </div>

      {/* Column headers */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '64px 18px 28px 42px 42px 36px 40px 40px 48px',
        gap: 3,
        padding: '4px 8px',
        borderBottom: '1px solid #1f2937',
        background: '#0d1117',
      }}>
        {['Date', '', 'Bkt', 'T', 'Z', 'L', 'PREUP', 'PREDN', 'Suffix'].map((h, i) => (
          <div key={i} style={{ fontSize: 9, color: '#4b5563', fontWeight: 600, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
            {h}
          </div>
        ))}
      </div>

      {/* Rows */}
      <div style={{ overflowY: 'auto', maxHeight: 480 }}>
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
                gridTemplateColumns: '64px 18px 28px 42px 42px 36px 40px 40px 48px',
                gap: 3,
                padding: '3px 8px',
                alignItems: 'center',
                borderBottom: '1px solid #1a2130',
                background: rowBg,
              }}
            >
              {/* Date */}
              <div style={{
                fontSize: 9,
                color: '#6b7280',
                fontFamily: 'var(--font-mono, monospace)',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}>
                {bar.date || '—'}
              </div>

              {/* Candle direction */}
              <div style={{ textAlign: 'center' }}>
                <CandleArrow bar={bar} />
              </div>

              {/* Bucket */}
              <div>
                <BucketChip bucket={bar.bucket} />
              </div>

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
                fontSize: 9,
                color: '#6b7280',
                fontFamily: 'var(--font-mono, monospace)',
                whiteSpace: 'nowrap',
              }}>
                {(bar.ne || '') + (bar.wick || '') + (bar.pen || '') + (bar.append_close ? (bar.close_suf || '') : '')}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
