/**
 * Signals Explorer — Studio
 * Interactive cooccurrence + filter UI for the Live demand_ticker_history.
 * Powers the discovery loop: which TZ / PREUP / Line3-5 / Wyckoff
 * combinations show up most often, and how they distribute across tiers.
 */
import { useState, useCallback, useEffect, useMemo } from 'react';
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

const PRESETS_LS_KEY = 'studio.signals.presets.v1';

function loadPresets() {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(PRESETS_LS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch { return []; }
}

function savePresets(presets) {
  if (typeof window === 'undefined') return;
  try { window.localStorage.setItem(PRESETS_LS_KEY, JSON.stringify(presets)); } catch {}
}

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

  // Pump-lift
  const [withLift, setWithLift]   = useState(false);
  const [liftDays, setLiftDays]   = useState(14);
  const [liftTarget, setLiftTarget] = useState(1.5);
  const [significantOnly, setSignificantOnly] = useState(false);
  const [baseline, setBaseline]   = useState(null);
  const [baselineB, setBaselineB] = useState(null);

  // Version comparison
  const [compareMode, setCompareMode] = useState(false);
  const [configA, setConfigA]   = useState('');
  const [configB, setConfigB]   = useState('');
  const [rowsA, setRowsA]       = useState(null);
  const [rowsB, setRowsB]       = useState(null);

  // Presets (localStorage)
  const [presets, setPresets]   = useState([]);
  const [presetName, setPresetName] = useState('');
  useEffect(() => { setPresets(loadPresets()); }, []);

  const toggleField = (key) => {
    setGroupBy(prev => prev.includes(key)
      ? prev.filter(k => k !== key)
      : [...prev, key]
    );
  };

  // Build the URL for a single cooccurrence call.
  const buildQs = useCallback((cfgVer) => {
    const qs = new URLSearchParams({
      group_by:  groupBy.join(','),
      days:      String(days),
      min_count: String(minCount),
    });
    if (cfgVer) qs.set('config_version', cfgVer);
    if (withLift) {
      qs.set('with_pump_lift',    'true');
      qs.set('lift_window_days',  String(liftDays));
      qs.set('lift_min_multiple', String(liftTarget));
    }
    return qs;
  }, [groupBy, days, minCount, withLift, liftDays, liftTarget]);

  const fetchCoocc = useCallback(async (cfgVer) => {
    const url = `${API_URL}/api/analytics/live-history/cooccurrence?${buildQs(cfgVer)}`;
    let r;
    try {
      r = await fetch(url);
    } catch (netErr) {
      throw new Error(`Network error reaching ${API_URL}. Is the backend deployed and the endpoint live? (${netErr.message})`);
    }
    if (r.status === 404) {
      throw new Error(`Endpoint not found at ${API_URL}/api/analytics/live-history/cooccurrence — backend may not have the latest commit deployed yet.`);
    }
    if (!r.ok) {
      let detail = `HTTP ${r.status}`;
      try { const eb = await r.json(); if (eb?.detail) detail = `${detail}: ${eb.detail}`; } catch {}
      throw new Error(detail);
    }
    const data = await r.json();
    return {
      rows:     Array.isArray(data.rows) ? data.rows : [],
      baseline: data.baseline || null,
    };
  }, [buildQs]);

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
      if (compareMode) {
        const [a, b] = await Promise.all([
          fetchCoocc(configA || null),
          fetchCoocc(configB || null),
        ]);
        setRowsA(a.rows); setRowsB(b.rows);
        setBaseline(a.baseline); setBaselineB(b.baseline);
        setRows(null);
      } else {
        const r = await fetchCoocc(configVer || null);
        setRows(r.rows);
        setBaseline(r.baseline); setBaselineB(null);
        setRowsA(null); setRowsB(null);
      }
    } catch (e) {
      setError(e.message);
      if (compareMode) { setRowsA([]); setRowsB([]); }
      else { setRows([]); }
    }
    setLoading(false);
  }, [compareMode, groupBy, configVer, configA, configB, fetchCoocc]);

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
    let out = [...rows];
    if (significantOnly && withLift) {
      out = out.filter(r => r.significant);
    }
    out.sort((a, b) => {
      const av = a[sortKey] ?? (sortKey === 'p_value' ? 1 : 0);
      const bv = b[sortKey] ?? (sortKey === 'p_value' ? 1 : 0);
      // For p_value, ascending (low p = best) when sortDesc is true is awkward.
      // The toggleSort caller flips desc; keep arithmetic plain.
      return sortDesc ? bv - av : av - bv;
    });
    return out;
  }, [rows, sortKey, sortDesc, significantOnly, withLift]);

  // Merge rowsA/rowsB by combo key for side-by-side display.
  const mergedCompareRows = useMemo(() => {
    if (!rowsA && !rowsB) return null;
    const keyOf = (r) => groupBy.map(k => r[k] ?? '').join('|');
    const byKey = new Map();
    (rowsA || []).forEach(r => { byKey.set(keyOf(r), { combo: r, a: r, b: null }); });
    (rowsB || []).forEach(r => {
      const k = keyOf(r);
      const existing = byKey.get(k);
      if (existing) existing.b = r;
      else byKey.set(k, { combo: r, a: null, b: r });
    });
    const merged = Array.from(byKey.values());
    merged.sort((x, y) => {
      const xn = (x.a?.n || 0) + (x.b?.n || 0);
      const yn = (y.a?.n || 0) + (y.b?.n || 0);
      return yn - xn;
    });
    return merged;
  }, [rowsA, rowsB, groupBy]);

  // Presets
  const savePreset = () => {
    const name = presetName.trim();
    if (!name) return;
    const next = [
      { name, groupBy, days, minCount, configVer, withLift, liftDays, liftTarget,
        compareMode, configA, configB,
        savedAt: new Date().toISOString() },
      ...presets.filter(p => p.name !== name),
    ];
    setPresets(next);
    savePresets(next);
    setPresetName('');
  };
  const loadPreset = (p) => {
    setGroupBy(p.groupBy || ['tz_t_signal', 'preup_token']);
    setDays(p.days || 30);
    setMinCount(p.minCount || 3);
    setConfigVer(p.configVer || '');
    setWithLift(!!p.withLift);
    setLiftDays(p.liftDays || 14);
    setLiftTarget(p.liftTarget || 1.5);
    setCompareMode(!!p.compareMode);
    setConfigA(p.configA || '');
    setConfigB(p.configB || '');
  };
  const deletePreset = (name) => {
    const next = presets.filter(p => p.name !== name);
    setPresets(next);
    savePresets(next);
  };

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
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16, marginBottom: 12 }}>
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
          {!compareMode && (
            <Section title="Config Version (optional)">
              <input
                type="text" placeholder="e.g. v3" value={configVer}
                onChange={e => setConfigVer(e.target.value.trim())}
                style={inputStyle}
              />
            </Section>
          )}
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

        {/* Pump-lift + Compare mode + Presets */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
          {/* Pump lift toggle */}
          <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 8, padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 12 }}>
            <Chip label={withLift ? '✓ Pump Lift' : 'Pump Lift'} active={withLift} onClick={() => setWithLift(v => !v)} />
            {withLift && (
              <>
                <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>window</span>
                <input type="number" min="1" max="60" value={liftDays}
                  onChange={e => setLiftDays(parseInt(e.target.value) || 14)}
                  style={{ ...inputStyle, width: 60 }} /> <span style={{ fontSize: 11, color: 'var(--ink-faint)' }}>d</span>
                <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>≥</span>
                <input type="number" min="1.0" step="0.1" value={liftTarget}
                  onChange={e => setLiftTarget(parseFloat(e.target.value) || 1.5)}
                  style={{ ...inputStyle, width: 60 }} /> <span style={{ fontSize: 11, color: 'var(--ink-faint)' }}>×</span>
                <Chip label={significantOnly ? '✓ Sig only' : 'Sig only'} active={significantOnly} onClick={() => setSignificantOnly(v => !v)} />
              </>
            )}
          </div>

          {/* Compare mode */}
          <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 8, padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 10 }}>
            <Chip label={compareMode ? '✓ Compare Versions' : 'Compare Versions'} active={compareMode} onClick={() => setCompareMode(v => !v)} />
            {compareMode && (
              <>
                <input type="text" placeholder="A (e.g. v3)" value={configA}
                  onChange={e => setConfigA(e.target.value.trim())}
                  style={{ ...inputStyle, width: 110 }} />
                <span style={{ color: 'var(--ink-faint)' }}>vs</span>
                <input type="text" placeholder="B (e.g. v4)" value={configB}
                  onChange={e => setConfigB(e.target.value.trim())}
                  style={{ ...inputStyle, width: 110 }} />
              </>
            )}
          </div>

          {/* Presets */}
          <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 8, padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 280 }}>
            <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>PRESETS</span>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', flex: 1 }}>
              {presets.length === 0 && <span style={{ fontSize: 11, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)' }}>None saved yet</span>}
              {presets.map(p => (
                <span key={p.name} style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                  <Chip label={p.name} active={false} onClick={() => loadPreset(p)} />
                  <button
                    onClick={() => deletePreset(p.name)}
                    title={`Delete preset ${p.name}`}
                    style={{ background: 'transparent', border: 'none', color: 'var(--ink-faint)', fontSize: 14, cursor: 'pointer', padding: '0 4px' }}
                  >×</button>
                </span>
              ))}
            </div>
            <input type="text" placeholder="Name…" value={presetName}
              onChange={e => setPresetName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') savePreset(); }}
              style={{ ...inputStyle, width: 100 }} />
            <button
              onClick={savePreset}
              disabled={!presetName.trim()}
              style={{
                background: !presetName.trim() ? 'var(--bg-2)' : 'var(--pump-lime-soft)',
                color: !presetName.trim() ? 'var(--ink-dim)' : 'var(--pump-lime)',
                border: '1px solid var(--stroke-soft)', borderRadius: 6,
                padding: '5px 10px', fontSize: 11, fontFamily: 'var(--f-mono)',
                cursor: !presetName.trim() ? 'not-allowed' : 'pointer',
              }}
            >Save</button>
          </div>
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

        {/* Baseline panel — only when lift is on */}
        {withLift && (baseline || baselineB) && (
          <div style={{
            background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)',
            borderRadius: 8, padding: '10px 14px', marginBottom: 14,
            display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
            fontSize: 12, fontFamily: 'var(--f-mono)',
          }}>
            <span style={{ color: 'var(--ink-dim)', textTransform: 'uppercase', letterSpacing: '0.08em', fontSize: 10 }}>
              Baseline (any combo)
            </span>
            {baseline && (
              <span style={{ color: 'var(--ink)' }}>
                {compareMode && <span style={{ color: 'var(--ink-faint)', marginRight: 4 }}>A:</span>}
                {baseline.n_target}/{baseline.n} scans pumped ≥{liftTarget}× within {liftDays}d
                <span style={{ color: 'var(--pump-lime)', marginLeft: 6 }}>
                  ({((baseline.hit_rate || 0) * 100).toFixed(2)}%)
                </span>
              </span>
            )}
            {compareMode && baselineB && (
              <span style={{ color: 'var(--ink)' }}>
                <span style={{ color: 'var(--ink-faint)', marginRight: 4 }}>B:</span>
                {baselineB.n_target}/{baselineB.n}
                <span style={{ color: 'var(--pump-lime)', marginLeft: 6 }}>
                  ({((baselineB.hit_rate || 0) * 100).toFixed(2)}%)
                </span>
              </span>
            )}
            <span style={{ color: 'var(--ink-faint)', fontSize: 11, marginLeft: 'auto' }}>
              Lift &amp; p-value compare each combo against this baseline (one-sided binomial test).
            </span>
          </div>
        )}

        {/* Single mode table */}
        {!compareMode && sortedRows && sortedRows.length > 0 && (
          <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 10, overflow: 'auto' }}>
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
                  {withLift && (
                    <>
                      <SortTh active={sortKey === 'hit_rate'}          desc={sortDesc} onClick={() => toggleSort('hit_rate')}>Hit %</SortTh>
                      <SortTh active={sortKey === 'lift_vs_baseline'}  desc={sortDesc} onClick={() => toggleSort('lift_vs_baseline')}>Lift</SortTh>
                      <SortTh active={sortKey === 'p_value'}           desc={!sortDesc} onClick={() => toggleSort('p_value')}>p</SortTh>
                      <SortTh active={sortKey === 'avg_pump_multiple'} desc={sortDesc} onClick={() => toggleSort('avg_pump_multiple')}>Avg ×</SortTh>
                      <Th>Pumped</Th>
                    </>
                  )}
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
                      {withLift && (
                        <>
                          <td style={{ ...cellMono, color: r.hit_rate >= 0.3 ? '#00e676' : r.hit_rate >= 0.1 ? '#ffeb3b' : 'var(--ink-dim)', fontWeight: 600 }}>
                            {r.hit_rate != null ? `${(r.hit_rate * 100).toFixed(1)}%` : '—'}
                          </td>
                          <td style={{ ...cellMono, color: liftColor(r.lift_vs_baseline), fontWeight: 700 }}>
                            {r.lift_vs_baseline != null ? `${parseFloat(r.lift_vs_baseline).toFixed(2)}×` : '—'}
                          </td>
                          <td style={{ ...cellMono, color: pColor(r.p_value, r.significant), fontWeight: 600 }} title={r.significant ? 'p < 0.05 and lift > 1.0 — edge is statistically significant' : 'Not significant at α=0.05'}>
                            {r.p_value != null ? formatP(r.p_value) : '—'}
                          </td>
                          <td style={{ ...cellMono, color: r.avg_pump_multiple >= 2 ? '#00e676' : 'var(--ink-dim)', fontWeight: 600 }}>
                            {r.avg_pump_multiple != null ? `×${parseFloat(r.avg_pump_multiple).toFixed(2)}` : '—'}
                          </td>
                          <td style={{ ...cellMono, color: 'var(--ink-dim)' }}>
                            {r.n_pump_target ?? 0}/{r.n_pumped ?? 0}
                          </td>
                        </>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {/* Compare mode table */}
        {compareMode && mergedCompareRows && mergedCompareRows.length === 0 && (
          <div style={{ color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 13, padding: '40px 0', textAlign: 'center' }}>
            No combos found in either version. Try lowering Min Count, widening the time window, or checking that both config versions have data.
          </div>
        )}
        {compareMode && mergedCompareRows && mergedCompareRows.length > 0 && (
          <div style={{ background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)', borderRadius: 10, overflow: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ background: 'var(--bg-2)', borderBottom: '1px solid var(--stroke-soft)' }}>
                  {groupBy.map(k => (
                    <Th key={k}>{GROUP_BY_FIELDS.find(f => f.key === k)?.label || k}</Th>
                  ))}
                  <Th>A: n / score{withLift ? ' / hit' : ''}</Th>
                  <Th>B: n / score{withLift ? ' / hit' : ''}</Th>
                  <Th>Δ (B − A)</Th>
                </tr>
              </thead>
              <tbody>
                {mergedCompareRows.slice(0, 100).map((m, i) => {
                  const a = m.a, b = m.b, ref = a || b;
                  const aN = a?.n || 0, bN = b?.n || 0;
                  const aS = a?.avg_score, bS = b?.avg_score;
                  const dCount = bN - aN;
                  const dScore = (bS != null && aS != null) ? (bS - aS) : null;
                  return (
                    <tr key={i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                      {groupBy.map(k => (
                        <td key={k} style={cellMono}>{ref[k] || <span style={{ color: 'var(--ink-faint)' }}>—</span>}</td>
                      ))}
                      <td style={{ ...cellMono, color: a ? 'var(--ink)' : 'var(--ink-faint)' }}>
                        {a ? `${aN} · ${aS != null ? parseFloat(aS).toFixed(2) : '—'}` : '—'}
                        {a && withLift && a.hit_rate != null && (
                          <span style={{ color: 'var(--ink-faint)' }}> · {(a.hit_rate * 100).toFixed(0)}%</span>
                        )}
                      </td>
                      <td style={{ ...cellMono, color: b ? 'var(--ink)' : 'var(--ink-faint)' }}>
                        {b ? `${bN} · ${bS != null ? parseFloat(bS).toFixed(2) : '—'}` : '—'}
                        {b && withLift && b.hit_rate != null && (
                          <span style={{ color: 'var(--ink-faint)' }}> · {(b.hit_rate * 100).toFixed(0)}%</span>
                        )}
                      </td>
                      <td style={{ ...cellMono, fontWeight: 600,
                        color: dCount > 0 ? '#00e676' : dCount < 0 ? '#ff6b6b' : 'var(--ink-dim)',
                      }}>
                        {dCount > 0 ? '+' : ''}{dCount}
                        {dScore != null && (
                          <span style={{ color: 'var(--ink-faint)', fontWeight: 400, marginLeft: 6 }}>
                            (score {dScore > 0 ? '+' : ''}{dScore.toFixed(2)})
                          </span>
                        )}
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

function liftColor(lift) {
  if (lift == null) return 'var(--ink-dim)';
  if (lift >= 2.0) return '#00e676';
  if (lift >= 1.3) return '#76ff03';
  if (lift >= 1.0) return '#ffeb3b';
  if (lift >= 0.7) return '#ffa940';
  return '#ff6b6b';
}

function pColor(p, significant) {
  if (p == null) return 'var(--ink-dim)';
  if (significant)   return '#00e676';
  if (p < 0.10)      return '#ffeb3b';
  return 'var(--ink-dim)';
}

function formatP(p) {
  if (p == null) return '—';
  if (p < 0.001) return '<0.001';
  if (p < 0.01)  return p.toFixed(3);
  return p.toFixed(3);
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
