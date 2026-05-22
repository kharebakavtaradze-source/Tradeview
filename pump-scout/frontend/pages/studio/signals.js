/**
 * Signals Explorer — Studio
 * Interactive cooccurrence + filter UI for the Live demand_ticker_history.
 * Powers the discovery loop: which TZ / PREUP / Line3-5 / Wyckoff
 * combinations show up most often, and how they distribute across tiers.
 */
import { useState, useCallback, useMemo } from 'react';
import PumpLayout from '../../components/PumpLayout';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const GROUP_BY_FIELDS = [
  { key: 'tz_t_signal',            label: 'T signal' },
  { key: 'tz_z_signal',            label: 'Z signal' },
  { key: 'best_tz_t_signal_15bar', label: 'Best T (15bar)' },
  { key: 'preup_token',            label: 'PREUP' },
  { key: 'predn_token',            label: 'PREDN' },
  { key: 'line3',                  label: 'Line 3 (body/wick)' },
  { key: 'line4',                  label: 'Line 4 (gap/range)' },
  { key: 'line5',                  label: 'Line 5 (VX/PSAR/RSI2)' },
  { key: 'l_digits',               label: 'L digits' },
  { key: 'wyckoff_state',          label: 'Wyckoff' },
  { key: 'demand_composite_tier',  label: 'Demand tier' },
  { key: 'ats_signal',             label: 'ATS' },
];

const DAY_PRESETS = [7, 14, 30, 90];

function Chip({ label, active, onClick, dim = false }) {
  return (
    <button
      onClick={onClick}
      style={{
        background:  active ? 'var(--pump-lime)' : 'var(--bg-1)',
        color:       active ? '#0a0a0a' : (dim ? 'var(--ink-faint)' : 'var(--ink)'),
        border:     `1px solid ${active ? 'var(--pump-lime)' : 'var(--stroke-soft)'}`,
        borderRadius: 6, padding: '5px 11px', cursor: 'pointer',
        fontSize: 12, fontFamily: 'var(--f-mono)',
        transition: 'all 0.15s',
      }}
    >
      {label}
    </button>
  );
}

function Spinner() {
  return (
    <span style={{
      display: 'inline-block', width: 14, height: 14,
      border: '2px solid var(--stroke-soft)', borderTopColor: 'var(--pump-lime)',
      borderRadius: '50%', animation: 'spin 0.7s linear infinite',
      verticalAlign: 'middle',
    }} />
  );
}

const TIER_COLORS = {
  PRIME_BUY:     '#00e676',
  HIGH_CONF_BUY: '#76ff03',
  BUY_WATCH:     '#ffeb3b',
  SETUP_MONITOR: '#ffa940',
};

export default function SignalsExplorer() {
  const [groupBy, setGroupBy]     = useState(['tz_t_signal', 'preup_token']);
  const [days, setDays]           = useState(30);
  const [minCount, setMinCount]   = useState(3);
  const [configVer, setConfigVer] = useState('');
  const [rows, setRows]           = useState(null);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState(null);
  const [sortKey, setSortKey]     = useState('n');
  const [sortDesc, setSortDesc]   = useState(true);
  const [drillRow, setDrillRow]   = useState(null);
  const [drillRows, setDrillRows] = useState(null);

  const toggleField = (key) => {
    setGroupBy(prev => prev.includes(key)
      ? prev.filter(k => k !== key)
      : [...prev, key]
    );
  };

  const runQuery = useCallback(async () => {
    if (groupBy.length === 0) {
      setError('Pick at least one Group By field.');
      return;
    }
    setLoading(true);
    setError(null);
    setDrillRow(null);
    setDrillRows(null);
    try {
      const qs = new URLSearchParams({
        group_by:  groupBy.join(','),
        days:      String(days),
        min_count: String(minCount),
      });
      if (configVer) qs.set('config_version', configVer);
      const r = await fetch(`${API_URL}/api/analytics/live-history/cooccurrence?${qs}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setRows(Array.isArray(data.rows) ? data.rows : []);
    } catch (e) {
      setError(e.message);
      setRows([]);
    }
    setLoading(false);
  }, [groupBy, days, minCount, configVer]);

  const drill = useCallback(async (row) => {
    setDrillRow(row);
    setDrillRows(null);
    const qs = new URLSearchParams({ days: String(days), limit: '100' });
    for (const k of groupBy) {
      if (row[k]) qs.set(_filterParam(k), row[k]);
    }
    if (configVer) qs.set('config_version', configVer);
    try {
      const r = await fetch(`${API_URL}/api/analytics/live-history/filter?${qs}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setDrillRows(Array.isArray(data.rows) ? data.rows : []);
    } catch {
      setDrillRows([]);
    }
  }, [groupBy, days, configVer]);

  const sortedRows = useMemo(() => {
    if (!rows) return null;
    const out = [...rows];
    out.sort((a, b) => {
      const av = a[sortKey] ?? 0;
      const bv = b[sortKey] ?? 0;
      return sortDesc ? bv - av : av - bv;
    });
    return out;
  }, [rows, sortKey, sortDesc]);

  const toggleSort = (key) => {
    if (sortKey === key) setSortDesc(d => !d);
    else { setSortKey(key); setSortDesc(true); }
  };

  return (
    <PumpLayout title="Signals" subtitle="Studio">
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      <div style={{ padding: '20px 24px', maxWidth: 1400, margin: '0 auto' }}>

        {/* Header */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6 }}>
            Live History Explorer
          </div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 600, color: 'var(--ink)' }}>
            Signal Co-occurrence
          </h2>
          <p style={{ margin: '6px 0 0', fontSize: 13, color: 'var(--ink-dim)' }}>
            Pick fields to group by. Find which combinations appear most often in production scans, and how they distribute across tiers.
          </p>
        </div>

        {/* Group By */}
        <Section title="Group By">
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {GROUP_BY_FIELDS.map(f => (
              <Chip
                key={f.key}
                label={f.label}
                active={groupBy.includes(f.key)}
                onClick={() => toggleField(f.key)}
              />
            ))}
          </div>
        </Section>

        {/* Filters */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, marginBottom: 20 }}>
          <Section title="Time Window">
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {DAY_PRESETS.map(d => (
                <Chip key={d} label={`${d}d`} active={days === d} onClick={() => setDays(d)} />
              ))}
            </div>
          </Section>
          <Section title="Min Count">
            <input
              type="number" min="1" step="1" value={minCount}
              onChange={e => setMinCount(parseInt(e.target.value) || 1)}
              style={inputStyle}
            />
          </Section>
          <Section title="Config Version (optional)">
            <input
              type="text" placeholder="e.g. v3" value={configVer}
              onChange={e => setConfigVer(e.target.value.trim())}
              style={inputStyle}
            />
          </Section>
          <Section title=" ">
            <button
              onClick={runQuery}
              disabled={loading || groupBy.length === 0}
              style={{
                width: '100%', padding: '8px 0',
                background: (loading || groupBy.length === 0) ? 'var(--bg-2)' : 'var(--pump-lime)',
                color:      (loading || groupBy.length === 0) ? 'var(--ink-dim)' : '#0a0a0a',
                border: 'none', borderRadius: 6,
                cursor: (loading || groupBy.length === 0) ? 'not-allowed' : 'pointer',
                fontSize: 13, fontWeight: 700, fontFamily: 'var(--f-mono)',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              }}
            >
              {loading ? <><Spinner /> Querying…</> : '▶ Run'}
            </button>
          </Section>
        </div>

        {error && (
          <div style={{ marginBottom: 14, fontSize: 12, color: '#ff4444', fontFamily: 'var(--f-mono)' }}>
            Error: {error}
          </div>
        )}

        {/* Results table */}
        {sortedRows && sortedRows.length === 0 && (
          <div style={{ color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 13, padding: '40px 0', textAlign: 'center' }}>
            No combos found. Try lowering Min Count or widening the time window.
            <div style={{ marginTop: 6, fontSize: 11, color: 'var(--ink-faint)' }}>
              Note: only scans persisted after commit a378052 contain bar-label data. Run /api/admin/backfill-demand-history to hydrate older rows.
            </div>
          </div>
        )}

        {sortedRows && sortedRows.length > 0 && (
          <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 10, overflow: 'hidden' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--bg-2)', borderBottom: '1px solid var(--stroke-soft)' }}>
                  {groupBy.map(k => (
                    <Th key={k}>{GROUP_BY_FIELDS.find(f => f.key === k)?.label || k}</Th>
                  ))}
                  <SortTh active={sortKey === 'n'}            desc={sortDesc} onClick={() => toggleSort('n')}>Count</SortTh>
                  <SortTh active={sortKey === 'avg_score'}    desc={sortDesc} onClick={() => toggleSort('avg_score')}>Avg Score</SortTh>
                  <SortTh active={sortKey === 'avg_combined'} desc={sortDesc} onClick={() => toggleSort('avg_combined')}>Avg Combined</SortTh>
                  <Th>Tier Mix</Th>
                </tr>
              </thead>
              <tbody>
                {sortedRows.map((r, i) => {
                  const total = (r.n_prime||0)+(r.n_high||0)+(r.n_watch||0)+(r.n_setup||0);
                  return (
                    <tr key={i} onClick={() => drill(r)} style={{
                      cursor: 'pointer', borderBottom: '1px solid var(--stroke-soft)',
                      background: drillRow && JSON.stringify(drillRow) === JSON.stringify(r) ? 'var(--pump-lime-soft)' : 'transparent',
                    }}>
                      {groupBy.map(k => (
                        <td key={k} style={cellMono}>{r[k] || <span style={{ color: 'var(--ink-faint)' }}>—</span>}</td>
                      ))}
                      <td style={{ ...cellMono, color: 'var(--pump-lime)', fontWeight: 700 }}>{r.n}</td>
                      <td style={cellMono}>{r.avg_score != null ? parseFloat(r.avg_score).toFixed(2) : '—'}</td>
                      <td style={cellMono}>{r.avg_combined != null ? parseFloat(r.avg_combined).toFixed(2) : '—'}</td>
                      <td style={{ padding: '6px 12px' }}>
                        <TierBar n_prime={r.n_prime} n_high={r.n_high} n_watch={r.n_watch} n_setup={r.n_setup} total={total} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Drilldown */}
        {drillRow && (
          <div style={{ marginTop: 24 }}>
            <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>
              Drilldown — {groupBy.map(k => `${k}=${drillRow[k] || '—'}`).join(' · ')}
            </div>
            {drillRows === null ? (
              <div style={{ color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 12 }}><Spinner /> Loading rows…</div>
            ) : drillRows.length === 0 ? (
              <div style={{ color: 'var(--ink-faint)', fontSize: 12, fontFamily: 'var(--f-mono)' }}>No rows.</div>
            ) : (
              <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 8, overflow: 'auto', maxHeight: 400 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                  <thead>
                    <tr style={{ background: 'var(--bg-2)' }}>
                      <Th>Date</Th><Th>Symbol</Th><Th>Tier</Th><Th>Score</Th>
                      <Th>T</Th><Th>PREUP</Th><Th>Line3</Th><Th>Line4</Th><Th>Line5</Th><Th>Wyckoff</Th><Th>Cfg</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {drillRows.map((row, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                        <td style={cellMono}>{row.scanned_at ? row.scanned_at.slice(0, 16).replace('T', ' ') : '—'}</td>
                        <td style={{ ...cellMono, color: 'var(--ink)', fontWeight: 600 }}>{row.symbol}</td>
                        <td style={cellMono}>
                          <span style={{ color: TIER_COLORS[row.demand_composite_tier] || 'var(--ink-dim)' }}>
                            {row.demand_composite_tier || '—'}
                          </span>
                        </td>
                        <td style={cellMono}>{row.demand_composite_score != null ? parseFloat(row.demand_composite_score).toFixed(1) : '—'}</td>
                        <td style={cellMono}>{row.tz_t_signal || '—'}</td>
                        <td style={cellMono}>{row.preup_token || '—'}</td>
                        <td style={cellMono}>{row.line3 || '—'}</td>
                        <td style={cellMono}>{row.line4 || '—'}</td>
                        <td style={cellMono}>{row.line5 || '—'}</td>
                        <td style={cellMono}>{row.wyckoff_state || '—'}</td>
                        <td style={{ ...cellMono, color: 'var(--ink-faint)' }}>{row.scoring_config_version || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

      </div>
    </PumpLayout>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 16 }}>
      {title && title.trim() && (
        <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 6 }}>
          {title}
        </div>
      )}
      {children}
    </div>
  );
}

const inputStyle = {
  width: '100%', padding: '7px 10px',
  background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)',
  borderRadius: 6, color: 'var(--ink)',
  fontSize: 13, fontFamily: 'var(--f-mono)',
};

const cellMono = {
  padding: '7px 12px',
  fontFamily: 'var(--f-mono)',
  color: 'var(--ink)',
  whiteSpace: 'nowrap',
};

function Th({ children }) {
  return (
    <th style={{
      textAlign: 'left', padding: '7px 12px',
      color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)',
      fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 500,
    }}>{children}</th>
  );
}

function SortTh({ children, active, desc, onClick }) {
  return (
    <th
      onClick={onClick}
      style={{
        textAlign: 'left', padding: '7px 12px',
        color: active ? 'var(--pump-lime)' : 'var(--ink-dim)',
        fontFamily: 'var(--f-mono)', cursor: 'pointer',
        fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 500,
        userSelect: 'none',
      }}>
      {children} {active ? (desc ? '▼' : '▲') : ''}
    </th>
  );
}

function TierBar({ n_prime, n_high, n_watch, n_setup, total }) {
  if (!total) return <span style={{ color: 'var(--ink-faint)', fontSize: 11, fontFamily: 'var(--f-mono)' }}>—</span>;
  const seg = (n, color) => n > 0 ? (
    <div title={`${n}`} style={{
      flex: n, background: color, height: 12, display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 9, color: '#0a0a0a', fontFamily: 'var(--f-mono)', fontWeight: 700,
    }}>
      {n / total > 0.15 ? n : ''}
    </div>
  ) : null;
  return (
    <div style={{ display: 'flex', width: 180, height: 12, borderRadius: 3, overflow: 'hidden', background: 'var(--bg-2)' }}>
      {seg(n_prime || 0, TIER_COLORS.PRIME_BUY)}
      {seg(n_high  || 0, TIER_COLORS.HIGH_CONF_BUY)}
      {seg(n_watch || 0, TIER_COLORS.BUY_WATCH)}
      {seg(n_setup || 0, TIER_COLORS.SETUP_MONITOR)}
    </div>
  );
}

// Maps a group_by column name to its filter query param name on /filter.
function _filterParam(col) {
  return {
    tz_t_signal:            'tz_t',
    tz_z_signal:            'tz_z',
    best_tz_t_signal_15bar: 'best_tz_t_15',
    best_tz_z_signal_15bar: 'best_tz_z_15',
    preup_token:            'preup',
    predn_token:            'predn',
    line3:                  'line3',
    line4:                  'line4',
    line5:                  'line5',
    l_digits:               'l_digits',
    wyckoff_state:          'wyckoff',
    demand_composite_tier:  'tier',
    ats_signal:             'ats',
  }[col] || col;
}
