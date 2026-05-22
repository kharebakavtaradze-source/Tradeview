/**
 * Pattern Study Studio
 * Mine bar label sequences that precede confirmed pumps.
 * Discover what patterns look like before breakouts.
 */
import { useEffect, useState, useCallback } from 'react';
import PumpLayout from '../../components/PumpLayout';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function StatusBadge({ status }) {
  const map = {
    done:     { bg: 'rgba(0,200,100,0.15)',  color: '#00c864' },
    complete: { bg: 'rgba(0,200,100,0.15)',  color: '#00c864' },
    running:  { bg: 'rgba(200,255,0,0.12)',  color: 'var(--pump-lime)' },
    error:    { bg: 'rgba(255,68,68,0.15)',  color: '#ff4444' },
    failed:   { bg: 'rgba(255,68,68,0.15)',  color: '#ff4444' },
  };
  const s = map[status] || { bg: 'var(--bg-2)', color: 'var(--ink-dim)' };
  return (
    <span style={{
      fontSize: 10, fontFamily: 'var(--f-mono)', textTransform: 'uppercase',
      letterSpacing: '0.08em', padding: '2px 7px', borderRadius: 4,
      background: s.bg, color: s.color, display: 'inline-block',
    }}>
      {status || 'unknown'}
    </span>
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

function ClusterCard({ cluster, expanded, onToggle }) {
  return (
    <div style={{
      background: 'var(--bg-1)', border: `1px solid ${expanded ? 'var(--pump-lime)' : 'var(--stroke-soft)'}`,
      borderRadius: 10, overflow: 'hidden',
      transition: 'border-color 0.15s',
    }}>
      <button
        onClick={onToggle}
        style={{
          width: '100%', background: 'transparent', border: 'none',
          padding: '14px 16px', cursor: 'pointer', textAlign: 'left',
          display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
        }}
      >
        <div style={{ flex: 1, minWidth: 120 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--ink)', fontFamily: 'var(--f-mono)', marginBottom: 4 }}>
            {cluster.symbol || cluster.cluster_id || `Cluster ${cluster.id || ''}`}
          </div>
          <div style={{ fontSize: 11, color: 'var(--ink-dim)' }}>
            {cluster.date_range || (cluster.start_date && cluster.end_date ? `${cluster.start_date} → ${cluster.end_date}` : '')}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
          {cluster.cluster_size != null && (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Size</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{cluster.cluster_size}</div>
            </div>
          )}
          {cluster.avg_multiple != null && (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Avg ×</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)' }}>×{parseFloat(cluster.avg_multiple).toFixed(2)}</div>
            </div>
          )}
        </div>
        <svg
          width={16} height={16} viewBox="0 0 24 24" fill="none"
          stroke="var(--ink-dim)" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"
          style={{ transform: expanded ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s', flexShrink: 0 }}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {expanded && cluster.episodes && cluster.episodes.length > 0 && (
        <div style={{ borderTop: '1px solid var(--stroke-soft)', padding: '12px 16px' }}>
          <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
            Episodes in Cluster
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                {['Symbol', 'Multiple', 'Date', 'Type'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '4px 10px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.07em', fontWeight: 400 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cluster.episodes.map((ep, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                  <td style={{ padding: '6px 10px', color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontWeight: 600 }}>{ep.symbol || '—'}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>
                    {ep.multiple != null ? `×${parseFloat(ep.multiple).toFixed(2)}` : '—'}
                  </td>
                  <td style={{ padding: '6px 10px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 11 }}>{ep.start_date || ep.date || '—'}</td>
                  <td style={{ padding: '6px 10px', color: 'var(--ink-dim)' }}>{ep.pump_type || ep.type || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {expanded && (!cluster.episodes || cluster.episodes.length === 0) && (
        <div style={{ borderTop: '1px solid var(--stroke-soft)', padding: '12px 16px', fontSize: 12, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)' }}>
          No episode detail available for this cluster.
        </div>
      )}
    </div>
  );
}

export default function PatternStudio() {
  const [pumpRuns, setPumpRuns] = useState([]);
  const [selectedRunId, setSelectedRunId] = useState('');
  const [clusters, setClusters] = useState(null);
  const [comparisons, setComparisons] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expandedCluster, setExpandedCluster] = useState(null);
  const [activeView, setActiveView] = useState('clusters'); // 'clusters' | 'comparisons'

  useEffect(() => {
    fetch(`${API_URL}/api/replay/pump-study/runs`)
      .then(r => r.ok ? r.json() : {})
      .then(data => {
        const runs = Array.isArray(data) ? data : (data.runs || []);
        setPumpRuns(runs);
        if (runs.length > 0 && !selectedRunId) {
          setSelectedRunId(runs[0].run_id || runs[0].id || '');
        }
      })
      .catch(() => setPumpRuns([]));
  }, []);

  const loadPatterns = useCallback(async (runId) => {
    if (!runId) return;
    setLoading(true);
    setClusters(null);
    setComparisons(null);
    setExpandedCluster(null);

    try {
      const r = await fetch(`${API_URL}/api/replay/pump-study/${runId}/clusters`);
      const data = r.ok ? await r.json() : [];
      setClusters(Array.isArray(data) ? data : (data.clusters || []));
    } catch { setClusters([]); }

    try {
      const r = await fetch(`${API_URL}/api/replay/pump-study/${runId}/comparisons`);
      const data = r.ok ? await r.json() : [];
      setComparisons(Array.isArray(data) ? data : (data.comparisons || data.groups || []));
    } catch { setComparisons([]); }

    setLoading(false);
  }, []);

  useEffect(() => {
    if (selectedRunId) loadPatterns(selectedRunId);
  }, [selectedRunId, loadPatterns]);

  const selectedRun = pumpRuns.find(r => (r.run_id || r.id) === selectedRunId);

  return (
    <PumpLayout title="Pattern Study" subtitle="Studio">
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      <div style={{ display: 'flex', height: 'calc(100vh - 64px)', overflow: 'hidden' }}>

        {/* LEFT PANEL */}
        <aside style={{
          width: 300, flexShrink: 0,
          borderRight: '1px solid var(--stroke-soft)',
          background: 'var(--bg-1)',
          display: 'flex', flexDirection: 'column',
          overflow: 'hidden',
        }}>
          <div style={{ padding: '20px 18px', overflowY: 'auto', flex: 1 }}>
            <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 18 }}>
              Source Run
            </div>

            <div>
              <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5 }}>
                Pump Study Run
              </div>
              {pumpRuns.length === 0 ? (
                <div style={{ fontSize: 12, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)', padding: '8px 0' }}>
                  No pump study runs available.{' '}
                  <a href="/studio/pump-study" style={{ color: 'var(--pump-lime)', textDecoration: 'none' }}>Run one first →</a>
                </div>
              ) : (
                <select
                  value={selectedRunId}
                  onChange={e => setSelectedRunId(e.target.value)}
                  style={{
                    width: '100%', background: 'var(--bg-0)', border: '1px solid var(--stroke-soft)',
                    borderRadius: 6, padding: '7px 10px', color: 'var(--ink)',
                    fontFamily: 'var(--f-mono)', fontSize: 12, outline: 'none',
                    boxSizing: 'border-box', cursor: 'pointer',
                  }}
                >
                  {pumpRuns.map(r => {
                    const rid = r.run_id || r.id;
                    return (
                      <option key={rid} value={rid}>
                        {rid} {r.start_date ? `(${r.start_date})` : ''}
                      </option>
                    );
                  })}
                </select>
              )}
            </div>

            {selectedRun && (
              <div style={{ marginTop: 16, background: 'var(--bg-0)', border: '1px solid var(--stroke-soft)', borderRadius: 8, padding: '12px 14px' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {[
                    ['Period', `${selectedRun.start_date || '?'} → ${selectedRun.end_date || '?'}`],
                    ['Min ×', selectedRun.min_multiple || '—'],
                    ['Episodes', selectedRun.episode_count ?? '—'],
                    ['Status', null],
                  ].map(([k, v]) => (
                    <div key={k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>{k}</span>
                      {k === 'Status' ? <StatusBadge status={selectedRun.status} /> : (
                        <span style={{ fontSize: 11, color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{v}</span>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Cluster summary */}
            {clusters != null && (
              <div style={{ marginTop: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
                  <span style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                    Clusters Found
                  </span>
                  <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)' }}>
                    {clusters.length}
                  </span>
                </div>
              </div>
            )}

            {/* Past runs list */}
            {pumpRuns.length > 0 && (
              <div style={{ marginTop: 24 }}>
                <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>
                  All Runs
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {pumpRuns.map((run, i) => {
                    const rid = run.run_id || run.id;
                    const isActive = rid === selectedRunId;
                    return (
                      <button
                        key={rid || i}
                        onClick={() => setSelectedRunId(rid)}
                        style={{
                          background: isActive ? 'var(--pump-lime-soft)' : 'var(--bg-0)',
                          border: `1px solid ${isActive ? 'var(--pump-lime)' : 'var(--stroke-soft)'}`,
                          borderRadius: 8, padding: '8px 12px',
                          textAlign: 'left', cursor: 'pointer', width: '100%',
                          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                        }}
                      >
                        <div>
                          <div style={{ fontSize: 10, color: isActive ? 'var(--pump-lime)' : 'var(--ink-dim)', fontFamily: 'var(--f-mono)', marginBottom: 2 }}>{rid}</div>
                          <div style={{ fontSize: 11, color: 'var(--ink-dim)' }}>{run.start_date || '?'} → {run.end_date || '?'}</div>
                        </div>
                        <StatusBadge status={run.status} />
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </aside>

        {/* RIGHT PANEL */}
        <main style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', background: 'var(--bg-0)' }}>
          {pumpRuns.length === 0 ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 16, color: 'var(--ink-dim)' }}>
              <svg width={48} height={48} viewBox="0 0 24 24" fill="none" style={{ color: 'var(--stroke-soft)' }}>
                <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <div style={{ fontSize: 14, fontFamily: 'var(--f-mono)' }}>No pump study runs found.</div>
              <a href="/studio/pump-study" style={{
                fontSize: 13, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)',
                border: '1px solid var(--pump-lime)', borderRadius: 7,
                padding: '8px 16px', textDecoration: 'none',
              }}>
                Go to Pump Study Studio →
              </a>
            </div>
          ) : loading ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
              <Spinner />
              <span style={{ fontSize: 14, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)' }}>Loading patterns…</span>
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
                  <div style={{ fontSize: 12, color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{selectedRunId}</div>
                </div>
                {clusters != null && (
                  <div>
                    <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Clusters</div>
                    <div style={{ fontSize: 12, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontWeight: 700 }}>{clusters.length}</div>
                  </div>
                )}
                {comparisons != null && (
                  <div>
                    <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Comparison Groups</div>
                    <div style={{ fontSize: 12, color: 'var(--ink)', fontFamily: 'var(--f-mono)', fontWeight: 700 }}>{comparisons.length}</div>
                  </div>
                )}
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 0 }}>
                  {['clusters', 'comparisons'].map(v => (
                    <button
                      key={v}
                      onClick={() => setActiveView(v)}
                      style={{
                        background: activeView === v ? 'var(--pump-lime-soft)' : 'transparent',
                        color: activeView === v ? 'var(--pump-lime)' : 'var(--ink-dim)',
                        border: `1px solid ${activeView === v ? 'var(--pump-lime)' : 'var(--stroke-soft)'}`,
                        padding: '5px 12px', cursor: 'pointer',
                        fontSize: 12, fontFamily: 'var(--f-mono)',
                        borderRadius: v === 'clusters' ? '6px 0 0 6px' : '0 6px 6px 0',
                        transition: 'all 0.15s',
                      }}
                    >
                      {v === 'clusters' ? 'Clusters' : 'Comparisons'}
                    </button>
                  ))}
                </div>
              </div>

              {/* Content */}
              <div style={{ flex: 1, overflow: 'auto', padding: '20px 24px' }}>
                {activeView === 'clusters' && (
                  clusters == null ? (
                    <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)' }}>Loading…</div>
                  ) : clusters.length === 0 ? (
                    <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)', padding: '24px 0', textAlign: 'center' }}>
                      No clusters found for this run.
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                      {clusters.map((cl, i) => (
                        <ClusterCard
                          key={cl.cluster_id || cl.id || i}
                          cluster={cl}
                          expanded={expandedCluster === i}
                          onToggle={() => setExpandedCluster(expandedCluster === i ? null : i)}
                        />
                      ))}
                    </div>
                  )
                )}

                {activeView === 'comparisons' && (
                  comparisons == null ? (
                    <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)' }}>Loading…</div>
                  ) : comparisons.length === 0 ? (
                    <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)', padding: '24px 0', textAlign: 'center' }}>
                      No comparison groups found for this run.
                    </div>
                  ) : (
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 14 }}>
                        Comparison Groups
                      </div>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                            {['Group Name', 'Count', 'Avg ×', 'Pump Type'].map(h => (
                              <th key={h} style={{ textAlign: 'left', padding: '6px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 400 }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {comparisons.map((g, i) => (
                            <tr key={i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                              <td style={{ padding: '8px 12px', color: 'var(--ink)', fontFamily: 'var(--f-mono)', fontWeight: 500 }}>
                                {g.group_name || g.name || g.label || `Group ${i + 1}`}
                              </td>
                              <td style={{ padding: '8px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
                                {g.count ?? g.size ?? '—'}
                              </td>
                              <td style={{ padding: '8px 12px', color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontWeight: 600 }}>
                                {g.avg_multiple != null ? `×${parseFloat(g.avg_multiple).toFixed(2)}` : '—'}
                              </td>
                              <td style={{ padding: '8px 12px', color: 'var(--ink-dim)' }}>
                                {g.pump_type || g.type || '—'}
                              </td>
                            </tr>
                          ))}
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
