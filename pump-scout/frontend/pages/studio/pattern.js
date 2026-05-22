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
            {cluster.canonical_start_date && cluster.canonical_peak_date
              ? `${cluster.canonical_start_date} → ${cluster.canonical_peak_date}`
              : (cluster.cluster_start_date && cluster.cluster_end_date
                  ? `${cluster.cluster_start_date} → ${cluster.cluster_end_date}`
                  : '')}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap' }}>
          {(cluster.raw_detection_count != null || (cluster.raw_detections && cluster.raw_detections.length)) && (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Detections</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>
                {cluster.raw_detection_count ?? cluster.raw_detections.length}
              </div>
            </div>
          )}
          {cluster.canonical_episode_id != null && (
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Episode</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)' }}>#{cluster.canonical_episode_id}</div>
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

      {expanded && cluster.raw_detections && cluster.raw_detections.length > 0 && (
        <div style={{ borderTop: '1px solid var(--stroke-soft)', padding: '12px 16px' }}>
          <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 10 }}>
            Raw Detections ({cluster.raw_detections.length})
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                {['Start', 'Peak', 'Multiple', 'Window', 'Canonical'].map(h => (
                  <th key={h} style={{ textAlign: 'left', padding: '4px 10px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.07em', fontWeight: 400 }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cluster.raw_detections.map((d, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                  <td style={{ padding: '6px 10px', color: 'var(--ink)', fontFamily: 'var(--f-mono)', fontSize: 11 }}>
                    {d.window_start_date || d.start_date || '—'}
                  </td>
                  <td style={{ padding: '6px 10px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 11 }}>
                    {d.window_peak_date || d.peak_date || '—'}
                  </td>
                  <td style={{ padding: '6px 10px', color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontWeight: 600 }}>
                    {(d.pump_multiple ?? d.multiple) != null
                      ? `×${parseFloat(d.pump_multiple ?? d.multiple).toFixed(2)}`
                      : '—'}
                  </td>
                  <td style={{ padding: '6px 10px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 11 }}>
                    {(d.window_days ?? d.pump_window_days) != null ? `${d.window_days ?? d.pump_window_days}d` : '—'}
                  </td>
                  <td style={{ padding: '6px 10px', fontFamily: 'var(--f-mono)', fontSize: 11, color: d.is_canonical ? '#00c864' : 'var(--ink-faint)' }}>
                    {d.is_canonical ? '✓' : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {expanded && (!cluster.raw_detections || cluster.raw_detections.length === 0) && (
        <div style={{ borderTop: '1px solid var(--stroke-soft)', padding: '12px 16px', fontSize: 12, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)' }}>
          No raw detections recorded for this cluster.
          {cluster.canonical_episode_id != null && (
            <span style={{ marginLeft: 6 }}>Canonical episode: #{cluster.canonical_episode_id}</span>
          )}
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
  const [liveCombos, setLiveCombos] = useState(null);
  const [loadingLive, setLoadingLive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [expandedCluster, setExpandedCluster] = useState(null);
  const [activeView, setActiveView] = useState('clusters'); // 'clusters' | 'comparisons' | 'live-xref'

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

  // Load Live cross-ref on demand: cooccurrence over the same date range as
  // the selected pump-study run. Lets the user compare "what combos appeared
  // in Live during the period" vs "what combos preceded confirmed pumps."
  const loadLiveCombos = useCallback(async () => {
    if (!selectedRun || !selectedRun.start_date || !selectedRun.end_date) {
      setLiveCombos([]);
      return;
    }
    setLoadingLive(true);
    try {
      const start = new Date(selectedRun.start_date);
      const end   = new Date(selectedRun.end_date);
      const days  = Math.max(1, Math.ceil((Date.now() - start.getTime()) / 86400000));
      const qs = new URLSearchParams({
        group_by: 'tz_t_signal,preup_token,line5',
        days:     String(days),
        min_count: '3',
      });
      if (selectedRun.scoring_config_version) {
        qs.set('config_version', selectedRun.scoring_config_version);
      }
      const r = await fetch(`${API_URL}/api/analytics/live-history/cooccurrence?${qs}`);
      const data = r.ok ? await r.json() : {};
      setLiveCombos(Array.isArray(data.rows) ? data.rows : []);
    } catch {
      setLiveCombos([]);
    }
    setLoadingLive(false);
  }, [selectedRun]);

  useEffect(() => {
    if (activeView === 'live-xref' && liveCombos === null) {
      loadLiveCombos();
    }
  }, [activeView, liveCombos, loadLiveCombos]);

  // Reset Live combos when run changes so we re-fetch on next tab visit.
  useEffect(() => { setLiveCombos(null); }, [selectedRunId]);

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
                  {[
                    { v: 'clusters',    label: 'Clusters'    },
                    { v: 'comparisons', label: 'Comparisons' },
                    { v: 'live-xref',   label: 'Live X-Ref'  },
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
                        transition: 'all 0.15s',
                      }}
                    >
                      {label}
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
                            {['Group Name', 'Count', 'Mean ×', 'Median ×', 'P90 ×', 'Days→Peak (median)'].map(h => (
                              <th key={h} style={{ textAlign: 'left', padding: '6px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 400 }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {comparisons.map((g, i) => {
                            const stats = g.stats || {};
                            const mult = stats.pump_multiple || {};
                            const dtp  = stats.days_to_peak  || {};
                            const fmtMult = (v) => v != null ? `×${parseFloat(v).toFixed(2)}` : '—';
                            return (
                              <tr key={i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                                <td style={{ padding: '8px 12px', color: 'var(--ink)', fontFamily: 'var(--f-mono)', fontWeight: 500 }}>
                                  {g.group_name || g.name || g.label || `Group ${i + 1}`}
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
                                  {g.member_count ?? g.count ?? g.size ?? '—'}
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontWeight: 600 }}>
                                  {fmtMult(mult.mean)}
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>
                                  {fmtMult(mult.median)}
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
                                  {fmtMult(mult.p90)}
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
                                  {dtp.median != null ? `${dtp.median}d` : '—'}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )
                )}

                {activeView === 'live-xref' && (
                  loadingLive || liveCombos === null ? (
                    <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)' }}>
                      <Spinner /> Querying Live history for this run's period…
                    </div>
                  ) : liveCombos.length === 0 ? (
                    <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)', padding: '24px 0', textAlign: 'center' }}>
                      No Live combos for this period.
                      <div style={{ marginTop: 6, fontSize: 11, color: 'var(--ink-faint)' }}>
                        Rows are only persisted from production scans after commit a378052. Run /api/admin/backfill-demand-history to hydrate older history.
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>
                        Live Combos — (T, PREUP, Line5) for {selectedRun?.start_date} → {selectedRun?.end_date}
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)', marginBottom: 14 }}>
                        Same date window as this pump-study run. Compare against the run's pump episodes to see which combos preceded confirmed pumps vs which were just noise.
                        {selectedRun?.scoring_config_version && (
                          <> · Filtered to scoring_config <span style={{ color: 'var(--pump-lime)' }}>{selectedRun.scoring_config_version}</span>.</>
                        )}
                      </div>
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                            {['T', 'PREUP', 'Line5', 'Count', 'Avg Score', 'Tier Mix'].map(h => (
                              <th key={h} style={{ textAlign: 'left', padding: '6px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 400 }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {liveCombos.slice(0, 50).map((r, i) => {
                            const total = (r.n_prime||0)+(r.n_high||0)+(r.n_watch||0)+(r.n_setup||0);
                            return (
                              <tr key={i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                                <td style={{ padding: '7px 12px', color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{r.tz_t_signal || '—'}</td>
                                <td style={{ padding: '7px 12px', color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{r.preup_token || '—'}</td>
                                <td style={{ padding: '7px 12px', color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{r.line5 || '—'}</td>
                                <td style={{ padding: '7px 12px', color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontWeight: 700 }}>{r.n}</td>
                                <td style={{ padding: '7px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
                                  {r.avg_score != null ? parseFloat(r.avg_score).toFixed(2) : '—'}
                                </td>
                                <td style={{ padding: '6px 12px' }}>
                                  {total > 0 ? (
                                    <div style={{ display: 'flex', width: 140, height: 10, borderRadius: 3, overflow: 'hidden', background: 'var(--bg-2)' }}>
                                      {(r.n_prime || 0) > 0 && <div title={`${r.n_prime} PRIME`} style={{ flex: r.n_prime, background: '#00e676' }} />}
                                      {(r.n_high  || 0) > 0 && <div title={`${r.n_high} HIGH`}   style={{ flex: r.n_high,  background: '#76ff03' }} />}
                                      {(r.n_watch || 0) > 0 && <div title={`${r.n_watch} WATCH`} style={{ flex: r.n_watch, background: '#ffeb3b' }} />}
                                      {(r.n_setup || 0) > 0 && <div title={`${r.n_setup} SETUP`} style={{ flex: r.n_setup, background: '#ffa940' }} />}
                                    </div>
                                  ) : <span style={{ color: 'var(--ink-faint)', fontSize: 11 }}>—</span>}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                      <div style={{ marginTop: 14, fontSize: 11, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)' }}>
                        Open the <a href="/studio/signals" style={{ color: 'var(--pump-lime)' }}>Signals Explorer</a> to query any field combination.
                      </div>
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
