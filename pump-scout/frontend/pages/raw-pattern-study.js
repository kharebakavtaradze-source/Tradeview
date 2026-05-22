/**
 * Raw Pattern Study viewer.
 * Browse raw_pattern_episode_features rows + per-feature comparison stats
 * for a completed raw-pattern-study run. Triggered with ?run_id=N or by
 * picking from the dropdown.
 */
import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/router';
import PumpLayout from '../components/PumpLayout';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function StatusBadge({ status }) {
  const map = {
    complete: { bg: 'rgba(0,200,100,0.15)', color: '#00c864' },
    running:  { bg: 'rgba(200,255,0,0.12)', color: 'var(--pump-lime)' },
    error:    { bg: 'rgba(255,68,68,0.15)', color: '#ff4444' },
    pending:  { bg: 'var(--bg-2)',          color: 'var(--ink-dim)' },
  };
  const s = map[status] || { bg: 'var(--bg-2)', color: 'var(--ink-dim)' };
  return (
    <span style={{
      fontSize: 10, fontFamily: 'var(--f-mono)', textTransform: 'uppercase',
      letterSpacing: '0.08em', padding: '2px 7px', borderRadius: 4,
      background: s.bg, color: s.color, display: 'inline-block',
    }}>{status || 'unknown'}</span>
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

const EPISODE_COLS = [
  { key: 'symbol',                       label: 'Symbol' },
  { key: 'group_type',                   label: 'Group' },
  { key: 'pump_multiple',                label: '×',          fmt: v => v != null ? `×${parseFloat(v).toFixed(2)}` : '—' },
  { key: 'pump_type',                    label: 'Type' },
  { key: 'pre_days',                     label: 'PRE d' },
  { key: 'pump_days',                    label: 'PUMP d' },
  { key: 'days_in_base',                 label: 'Base d' },
  { key: 'demand_tier_at_breakout',      label: 'Demand' },
  { key: 'demand_score_at_breakout',     label: 'D Score',    fmt: v => v != null ? parseFloat(v).toFixed(1) : '—' },
  { key: 'ats_at_breakout',              label: 'ATS' },
  { key: 'tz_t_signal_at_breakout',      label: 'T' },
  { key: 'preup_token_at_breakout',      label: 'PREUP' },
  { key: 'line5_at_breakout',            label: 'Line5' },
  { key: 'strongest_wyckoff_state',      label: 'Wyckoff' },
];

export default function RawPatternStudyPage() {
  const router = useRouter();
  const [runs, setRuns]             = useState([]);
  const [selectedId, setSelectedId] = useState('');
  const [run, setRun]               = useState(null);
  const [episodes, setEpisodes]     = useState(null);
  const [comparisons, setComparisons] = useState(null);
  const [loading, setLoading]       = useState(false);
  const [activeView, setActiveView] = useState('episodes'); // 'episodes' | 'comparisons'
  const [groupFilter, setGroupFilter] = useState('');

  useEffect(() => {
    fetch(`${API_URL}/api/replay/raw-pattern-study/runs?limit=30`)
      .then(r => r.ok ? r.json() : {})
      .then(data => {
        const rs = data.runs || [];
        setRuns(rs);
        const qp = router.query?.run_id;
        const initial = qp ? Number(qp) : (rs[0]?.id || '');
        if (initial) setSelectedId(initial);
      })
      .catch(() => setRuns([]));
  }, [router.query?.run_id]);

  const load = useCallback(async (id) => {
    if (!id) return;
    setLoading(true);
    setRun(null);
    setEpisodes(null);
    setComparisons(null);

    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/${id}`);
      const data = r.ok ? await r.json() : {};
      setRun(data.run || null);
    } catch {}

    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/${id}/episodes?limit=2000`);
      const data = r.ok ? await r.json() : {};
      setEpisodes(data.episodes || []);
    } catch { setEpisodes([]); }

    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/${id}/comparisons`);
      const data = r.ok ? await r.json() : {};
      setComparisons(data.comparisons || []);
    } catch { setComparisons([]); }

    setLoading(false);
  }, []);

  useEffect(() => { if (selectedId) load(selectedId); }, [selectedId, load]);

  const filteredEpisodes = (episodes || []).filter(e =>
    !groupFilter || e.group_type === groupFilter
  );
  const groupCounts = (episodes || []).reduce((acc, e) => {
    const k = e.group_type || 'unknown';
    acc[k] = (acc[k] || 0) + 1;
    return acc;
  }, {});

  const download = (format) => {
    if (!selectedId) return;
    window.location.href = `${API_URL}/api/replay/raw-pattern-study/${selectedId}/export?format=${format}`;
  };
  const downloadDaily = () => {
    if (!selectedId) return;
    window.location.href = `${API_URL}/api/replay/raw-pattern-study/${selectedId}/daily-features/export`;
  };

  return (
    <PumpLayout title="Raw Pattern Study" subtitle="Studio">
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      <div style={{ display: 'flex', height: 'calc(100vh - 64px)', overflow: 'hidden' }}>

        {/* LEFT */}
        <aside style={{
          width: 300, flexShrink: 0,
          borderRight: '1px solid var(--stroke-soft)',
          background: 'var(--bg-1)',
          display: 'flex', flexDirection: 'column', overflow: 'hidden',
        }}>
          <div style={{ padding: '20px 18px', overflowY: 'auto', flex: 1 }}>
            <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 18 }}>
              Raw Pattern Run
            </div>

            {runs.length === 0 ? (
              <div style={{ fontSize: 12, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)', padding: '8px 0' }}>
                No raw-pattern runs yet.{' '}
                <a href="/studio/pump-study" style={{ color: 'var(--pump-lime)', textDecoration: 'none' }}>
                  Run a Pump Study first →
                </a>
              </div>
            ) : (
              <>
                <select
                  value={selectedId}
                  onChange={e => setSelectedId(Number(e.target.value))}
                  style={{
                    width: '100%', background: 'var(--bg-0)', border: '1px solid var(--stroke-soft)',
                    borderRadius: 6, padding: '7px 10px', color: 'var(--ink)',
                    fontFamily: 'var(--f-mono)', fontSize: 12, outline: 'none',
                    boxSizing: 'border-box', cursor: 'pointer',
                  }}
                >
                  {runs.map(r => (
                    <option key={r.id} value={r.id}>
                      #{r.id} {r.start_date ? `(${r.start_date} → ${r.end_date})` : ''}
                    </option>
                  ))}
                </select>

                {run && (
                  <div style={{ marginTop: 16, background: 'var(--bg-0)', border: '1px solid var(--stroke-soft)', borderRadius: 8, padding: '12px 14px' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                      {[
                        ['Period',     `${run.start_date || '?'} → ${run.end_date || '?'}`],
                        ['Pump Study', run.pump_study_run_id ?? '—'],
                        ['Episodes',   run.episode_feature_count ?? '—'],
                        ['Daily rows', run.raw_daily_count ?? '—'],
                        ['Comparisons', run.comparison_count ?? '—'],
                        ['Status', null],
                      ].map(([k, v]) => (
                        <div key={k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>{k}</span>
                          {k === 'Status'
                            ? <StatusBadge status={run.status} />
                            : <span style={{ fontSize: 11, color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{v}</span>}
                        </div>
                      ))}
                    </div>
                    {run.pump_study_run_id != null && (
                      <a
                        href={`/studio/pump-study?run_id=${run.pump_study_run_id}`}
                        style={{
                          display: 'block', marginTop: 12, padding: '7px 10px',
                          textAlign: 'center', textDecoration: 'none',
                          fontSize: 11, fontFamily: 'var(--f-mono)',
                          color: 'var(--pump-lime)',
                          border: '1px solid var(--pump-lime)', borderRadius: 6,
                        }}
                      >
                        Pump Study #{run.pump_study_run_id} →
                      </a>
                    )}
                  </div>
                )}

                {/* Group filter */}
                {Object.keys(groupCounts).length > 0 && (
                  <div style={{ marginTop: 20 }}>
                    <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>
                      Group Type
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      <button
                        onClick={() => setGroupFilter('')}
                        style={{
                          background: !groupFilter ? 'var(--pump-lime-soft)' : 'transparent',
                          color: !groupFilter ? 'var(--pump-lime)' : 'var(--ink-dim)',
                          border: `1px solid ${!groupFilter ? 'var(--pump-lime)' : 'var(--stroke-soft)'}`,
                          borderRadius: 6, padding: '5px 10px', cursor: 'pointer',
                          fontSize: 11, fontFamily: 'var(--f-mono)',
                          display: 'flex', justifyContent: 'space-between',
                        }}
                      >
                        <span>all</span>
                        <span>{episodes?.length || 0}</span>
                      </button>
                      {Object.entries(groupCounts).map(([g, c]) => (
                        <button
                          key={g}
                          onClick={() => setGroupFilter(g)}
                          style={{
                            background: groupFilter === g ? 'var(--pump-lime-soft)' : 'transparent',
                            color: groupFilter === g ? 'var(--pump-lime)' : 'var(--ink-dim)',
                            border: `1px solid ${groupFilter === g ? 'var(--pump-lime)' : 'var(--stroke-soft)'}`,
                            borderRadius: 6, padding: '5px 10px', cursor: 'pointer',
                            fontSize: 11, fontFamily: 'var(--f-mono)',
                            display: 'flex', justifyContent: 'space-between',
                          }}
                        >
                          <span>{g}</span>
                          <span>{c}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Export */}
                {selectedId && (
                  <div style={{ marginTop: 24 }}>
                    <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>
                      Export
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                      {[
                        ['Episodes CSV',     () => download('csv')],
                        ['Daily Features CSV', () => downloadDaily()],
                        ['Full JSON',        () => download('json')],
                        ['Markdown summary', () => download('markdown')],
                      ].map(([label, fn]) => (
                        <button
                          key={label}
                          onClick={fn}
                          style={{
                            background: 'var(--bg-0)', border: '1px solid var(--stroke-soft)',
                            borderRadius: 6, padding: '6px 10px',
                            fontSize: 11, fontFamily: 'var(--f-mono)',
                            color: 'var(--ink)', cursor: 'pointer', textAlign: 'left',
                          }}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </aside>

        {/* RIGHT */}
        <main style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', background: 'var(--bg-0)' }}>
          {runs.length === 0 ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 16, color: 'var(--ink-dim)' }}>
              <div style={{ fontSize: 14, fontFamily: 'var(--f-mono)' }}>No raw-pattern-study runs found.</div>
              <a href="/studio/pump-study" style={{
                fontSize: 13, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)',
                border: '1px solid var(--pump-lime)', borderRadius: 7,
                padding: '8px 16px', textDecoration: 'none',
              }}>Go to Pump Study Studio →</a>
            </div>
          ) : loading ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
              <Spinner />
              <span style={{ fontSize: 14, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)' }}>Loading raw patterns…</span>
            </div>
          ) : (
            <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              {/* Header */}
              <div style={{
                padding: '14px 24px', borderBottom: '1px solid var(--stroke-soft)',
                background: 'var(--bg-1)', display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
              }}>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Run</div>
                  <div style={{ fontSize: 12, color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>#{selectedId}</div>
                </div>
                {episodes != null && (
                  <div>
                    <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Episodes</div>
                    <div style={{ fontSize: 12, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontWeight: 700 }}>{filteredEpisodes.length} / {episodes.length}</div>
                  </div>
                )}
                {comparisons != null && (
                  <div>
                    <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Comparison Rows</div>
                    <div style={{ fontSize: 12, color: 'var(--ink)', fontFamily: 'var(--f-mono)', fontWeight: 700 }}>{comparisons.length}</div>
                  </div>
                )}
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 0 }}>
                  {[
                    { v: 'episodes',    label: 'Episodes'    },
                    { v: 'comparisons', label: 'Feature Stats' },
                  ].map(({ v, label }, i, arr) => (
                    <button
                      key={v}
                      onClick={() => setActiveView(v)}
                      style={{
                        background: activeView === v ? 'var(--pump-lime-soft)' : 'transparent',
                        color: activeView === v ? 'var(--pump-lime)' : 'var(--ink-dim)',
                        border: `1px solid ${activeView === v ? 'var(--pump-lime)' : 'var(--stroke-soft)'}`,
                        padding: '5px 12px', cursor: 'pointer',
                        fontSize: 12, fontFamily: 'var(--f-mono)',
                        borderRadius:
                          i === 0           ? '6px 0 0 6px' :
                          i === arr.length - 1 ? '0 6px 6px 0' :
                          '0',
                        marginLeft: i === 0 ? 0 : -1,
                      }}
                    >{label}</button>
                  ))}
                </div>
              </div>

              {/* Content */}
              <div style={{ flex: 1, overflow: 'auto', padding: '20px 24px' }}>
                {activeView === 'episodes' && (
                  episodes == null ? (
                    <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)' }}>Loading…</div>
                  ) : filteredEpisodes.length === 0 ? (
                    <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)', padding: '24px 0', textAlign: 'center' }}>
                      {episodes.length === 0
                        ? 'No episode features built for this run.'
                        : `No episodes match group "${groupFilter}".`}
                    </div>
                  ) : (
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                          {EPISODE_COLS.map(c => (
                            <th key={c.key} style={{ textAlign: 'left', padding: '6px 10px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 400 }}>{c.label}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {filteredEpisodes.slice(0, 500).map((e, i) => (
                          <tr key={e.id || i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                            {EPISODE_COLS.map(c => {
                              const raw = e[c.key];
                              const v = c.fmt ? c.fmt(raw) : (raw == null ? '—' : String(raw));
                              return (
                                <td key={c.key} style={{
                                  padding: '6px 10px',
                                  fontFamily: 'var(--f-mono)',
                                  color: c.key === 'symbol' ? 'var(--ink)' : (c.key === 'pump_multiple' ? 'var(--pump-lime)' : 'var(--ink-dim)'),
                                  fontWeight: c.key === 'symbol' || c.key === 'pump_multiple' ? 600 : 400,
                                }}>{v}</td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )
                )}

                {activeView === 'comparisons' && (
                  comparisons == null ? (
                    <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)' }}>Loading…</div>
                  ) : comparisons.length === 0 ? (
                    <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)', padding: '24px 0', textAlign: 'center' }}>
                      No comparison rows for this run.
                    </div>
                  ) : (
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)', marginBottom: 12 }}>
                        One row per (group_type, feature) — mean / median / p25 / p75 / p90 across the group's episodes.
                      </div>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                            {['Group', 'Feature', 'N', 'Mean', 'Median', 'P25', 'P75', 'P90'].map(h => (
                              <th key={h} style={{ textAlign: 'left', padding: '6px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 400 }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {comparisons.slice(0, 1000).map((c, i) => {
                            const fmt = v => v == null ? '—' : (Number.isInteger(v) ? v : parseFloat(v).toFixed(3));
                            return (
                              <tr key={c.id || i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                                <td style={{ padding: '6px 12px', color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{c.group_name}</td>
                                <td style={{ padding: '6px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>{c.feature_name}</td>
                                <td style={{ padding: '6px 12px', color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontWeight: 600 }}>{c.member_count ?? '—'}</td>
                                <td style={{ padding: '6px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>{fmt(c.mean_value)}</td>
                                <td style={{ padding: '6px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>{fmt(c.median_value)}</td>
                                <td style={{ padding: '6px 12px', color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)' }}>{fmt(c.p25_value)}</td>
                                <td style={{ padding: '6px 12px', color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)' }}>{fmt(c.p75_value)}</td>
                                <td style={{ padding: '6px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>{fmt(c.p90_value)}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )
                )}
              </div>
            </div>
          )}
        </main>
      </div>
    </PumpLayout>
  );
}
