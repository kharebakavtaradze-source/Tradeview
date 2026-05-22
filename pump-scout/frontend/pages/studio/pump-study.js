/**
 * Pump Study Studio
 * Detect pump episodes, analyze signal lift, compare signal performance.
 */
import { useEffect, useState, useRef, useCallback } from 'react';
import PumpLayout from '../../components/PumpLayout';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function fmt(d) {
  if (!d) return '—';
  return new Date(d).toLocaleDateString();
}

function fmtDate(d) {
  if (!d) return '';
  return new Date(d).toISOString().slice(0, 10);
}

function defaultStart() {
  const d = new Date();
  d.setMonth(d.getMonth() - 6);
  return d.toISOString().slice(0, 10);
}

function defaultEnd() {
  return new Date().toISOString().slice(0, 10);
}

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

function Label({ children }) {
  return (
    <div style={{
      fontSize: 10, fontFamily: 'var(--f-mono)', color: 'var(--ink-dim)',
      textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 5,
    }}>
      {children}
    </div>
  );
}

function Input({ value, onChange, type = 'text', step, min, style }) {
  return (
    <input
      type={type}
      value={value}
      step={step}
      min={min}
      onChange={e => onChange(e.target.value)}
      style={{
        width: '100%', background: 'var(--bg-0)', border: '1px solid var(--stroke-soft)',
        borderRadius: 6, padding: '7px 10px', color: 'var(--ink)',
        fontFamily: 'var(--f-mono)', fontSize: 13, outline: 'none',
        boxSizing: 'border-box', ...style,
      }}
    />
  );
}

function Tab({ label, active, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active ? 'var(--pump-lime-soft)' : 'transparent',
        color: active ? 'var(--pump-lime)' : 'var(--ink-dim)',
        border: 'none', borderBottom: active ? '2px solid var(--pump-lime)' : '2px solid transparent',
        padding: '8px 14px', cursor: 'pointer', fontSize: 13, fontFamily: 'var(--f-mono)',
        borderRadius: '4px 4px 0 0', transition: 'all 0.15s',
      }}
    >
      {label}
    </button>
  );
}

function liftColor(lift) {
  if (lift >= 2.0) return '#00c864';
  if (lift >= 1.5) return '#a0d020';
  if (lift >= 1.0) return 'var(--ink)';
  return '#ff4444';
}

function ScoreDistChart({ episodes }) {
  if (!episodes || episodes.length === 0) return (
    <div style={{ color: 'var(--ink-dim)', fontSize: 13, padding: '24px 0', textAlign: 'center', fontFamily: 'var(--f-mono)' }}>
      No episode data
    </div>
  );

  const buckets = [
    { label: '1–2×',  min: 1,  max: 2   },
    { label: '2–4×',  min: 2,  max: 4   },
    { label: '4–10×', min: 4,  max: 10  },
    { label: '10×+',  min: 10, max: Infinity },
  ];

  const counts = buckets.map(b => ({
    ...b,
    count: episodes.filter(e => {
      const m = parseFloat(e.multiple || e.gain_multiple || e.max_multiple || 0);
      return m >= b.min && m < b.max;
    }).length,
  }));

  const maxCount = Math.max(...counts.map(c => c.count), 1);

  return (
    <div style={{ padding: '16px 0' }}>
      <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 16 }}>
        Episode Count by Multiple Bucket
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 12, height: 120 }}>
        {counts.map(b => (
          <div key={b.label} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
            <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>{b.count}</div>
            <div style={{
              width: '100%', background: 'var(--pump-lime-soft)',
              border: '1px solid var(--pump-lime)',
              borderRadius: '3px 3px 0 0',
              height: `${Math.max(4, (b.count / maxCount) * 80)}px`,
              position: 'relative',
            }}>
              <div style={{
                position: 'absolute', inset: 0,
                background: 'linear-gradient(to top, var(--pump-lime), transparent)',
                opacity: 0.4, borderRadius: '3px 3px 0 0',
              }} />
            </div>
            <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', whiteSpace: 'nowrap' }}>{b.label}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function PumpStudyStudio() {
  const [startDate, setStartDate] = useState(defaultStart);
  const [endDate, setEndDate] = useState(defaultEnd);
  const [minMultiple, setMinMultiple] = useState('1.2');
  const [windowDays, setWindowDays] = useState('14');

  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState(null);
  const [pollRunId, setPollRunId] = useState(null);

  const [activeRun, setActiveRun] = useState(null);
  const [activeTab, setActiveTab] = useState('episodes');

  const [episodes, setEpisodes] = useState(null);
  const [signalLift, setSignalLift] = useState(null);
  const [scoringConfig, setScoringConfig] = useState(null);
  const [pastRuns, setPastRuns] = useState([]);
  const [expandedEpisode, setExpandedEpisode] = useState(null);

  const [loadingEpisodes, setLoadingEpisodes] = useState(false);
  const [loadingLift, setLoadingLift] = useState(false);
  const [reScoring, setReScoring] = useState(false);

  const pollRef = useRef(null);

  // Load past runs on mount
  useEffect(() => {
    fetch(`${API_URL}/api/replay/pump-study/runs`)
      .then(r => r.ok ? r.json() : {})
      .then(data => setPastRuns(Array.isArray(data) ? data : (data.runs || [])))
      .catch(() => setPastRuns([]));

    fetch(`${API_URL}/api/analytics/scoring-config`)
      .then(r => r.ok ? r.json() : null)
      .then(data => setScoringConfig(data ? (data.config || data) : null))
      .catch(() => {});
  }, []);

  // Polling
  useEffect(() => {
    if (!pollRunId) return;
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`${API_URL}/api/replay/pump-study/${pollRunId}`);
        if (!r.ok) return;
        const body = await r.json();
        const run = body.run || body;
        if (run.status !== 'running') {
          clearInterval(pollRef.current);
          setPollRunId(null);
          setRunning(false);
          setActiveRun(run);
          setPastRuns(prev => {
            const filtered = prev.filter(x => (x.run_id || x.id) !== (run.run_id || run.id));
            return [run, ...filtered];
          });
          loadRunData(run.run_id || run.id);
        }
      } catch {}
    }, 3000);
    return () => clearInterval(pollRef.current);
  }, [pollRunId]);

  const loadRunData = useCallback(async (runId) => {
    setEpisodes(null);
    setSignalLift(null);
    setLoadingEpisodes(true);
    setLoadingLift(true);

    try {
      const r = await fetch(`${API_URL}/api/replay/pump-study/${runId}/episodes`);
      const data = r.ok ? await r.json() : [];
      setEpisodes(Array.isArray(data) ? data : (data.episodes || []));
    } catch { setEpisodes([]); }
    setLoadingEpisodes(false);

    try {
      const r = await fetch(`${API_URL}/api/replay/pump-study/${runId}/signal-lift`);
      const data = r.ok ? await r.json() : [];
      const arr = Array.isArray(data) ? data : (data.signal_lift || data.signals || data.lift || []);
      setSignalLift([...arr].sort((a, b) => (b.lift || 0) - (a.lift || 0)));
    } catch { setSignalLift([]); }
    setLoadingLift(false);
  }, []);

  const handleRun = async () => {
    setRunError(null);
    setRunning(true);
    setActiveRun(null);
    setEpisodes(null);
    setSignalLift(null);
    try {
      const r = await fetch(`${API_URL}/api/replay/pump-study/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_date: startDate,
          end_date: endDate,
          min_multiple: parseFloat(minMultiple) || 1.2,
          window_days: parseInt(windowDays) || 14,
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      const runId = data.run_id || data.id;
      setPollRunId(runId);
    } catch (e) {
      setRunError(e.message);
      setRunning(false);
    }
  };

  const handleDeleteRun = async (run) => {
    const runId = run.run_id || run.id;
    const ok = typeof window !== 'undefined' && window.confirm(
      `Delete pump-study run ${runId}?\n\nThis removes the run, its episodes, snapshots, clusters, events, comparisons, and any linked raw-pattern run. Cannot be undone.`
    );
    if (!ok) return;
    try {
      const r = await fetch(`${API_URL}/api/replay/pump-study/${runId}`, { method: 'DELETE' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setPastRuns(prev => prev.filter(x => (x.run_id || x.id) !== runId));
      if (activeRun && (activeRun.run_id || activeRun.id) === runId) {
        setActiveRun(null);
        setEpisodes(null);
        setSignalLift(null);
      }
    } catch (e) {
      setRunError(`Delete failed: ${e.message}`);
    }
  };

  const handleViewRun = async (run) => {
    const runId = run.run_id || run.id;
    try {
      const r = await fetch(`${API_URL}/api/replay/pump-study/${runId}`);
      const body = r.ok ? await r.json() : null;
      setActiveRun(body ? (body.run || body) : run);
    } catch { setActiveRun(run); }
    setActiveTab('episodes');
    setExpandedEpisode(null);
    loadRunData(runId);
  };

  const handleReScore = async () => {
    if (!activeRun) return;
    const runId = activeRun.run_id || activeRun.id;
    setReScoring(true);
    try {
      const r = await fetch(`${API_URL}/api/replay/pump-study/${runId}/score-demand`, { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      // Poll the run-detail until scoring_config_version flips to the target version.
      const target = data.target_config_version;
      const start  = Date.now();
      const tick = async () => {
        if (Date.now() - start > 10 * 60 * 1000) { setReScoring(false); return; }
        try {
          const rr = await fetch(`${API_URL}/api/replay/pump-study/${runId}`);
          if (rr.ok) {
            const body = await rr.json();
            const run  = body.run || body;
            if (run.scoring_config_version === target) {
              setActiveRun(run);
              setPastRuns(prev => prev.map(x =>
                (x.run_id || x.id) === runId ? run : x
              ));
              loadRunData(runId);
              setReScoring(false);
              return;
            }
          }
        } catch {}
        setTimeout(tick, 3000);
      };
      tick();
    } catch (e) {
      setRunError(e.message);
      setReScoring(false);
    }
  };

  const signalScore = (name) => {
    if (!scoringConfig || !scoringConfig.signals) return null;
    const s = scoringConfig.signals[name];
    if (s == null) return null;
    return typeof s === 'object' ? s.score : s;
  };

  return (
    <PumpLayout title="Pump Study" subtitle="Studio">
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>

      <div style={{ display: 'flex', height: 'calc(100vh - 64px)', overflow: 'hidden' }}>

        {/* LEFT PANEL */}
        <aside style={{
          width: 320, flexShrink: 0,
          borderRight: '1px solid var(--stroke-soft)',
          background: 'var(--bg-1)',
          display: 'flex', flexDirection: 'column',
          overflow: 'hidden',
        }}>
          <div style={{ padding: '20px 18px', overflowY: 'auto', flex: 1 }}>
            <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 18 }}>
              Run Config
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <div>
                <Label>Start Date</Label>
                <Input type="date" value={startDate} onChange={setStartDate} />
              </div>
              <div>
                <Label>End Date</Label>
                <Input type="date" value={endDate} onChange={setEndDate} />
              </div>
              <div>
                <Label>Min Gain (×)</Label>
                <Input type="number" value={minMultiple} onChange={setMinMultiple} step="0.1" min="1" />
              </div>
              <div>
                <Label>Window Days</Label>
                <Input type="number" value={windowDays} onChange={setWindowDays} step="1" min="1" />
              </div>
            </div>

            <button
              onClick={handleRun}
              disabled={running}
              style={{
                marginTop: 20, width: '100%', padding: '10px 0',
                background: running ? 'var(--bg-2)' : 'var(--pump-lime)',
                color: running ? 'var(--ink-dim)' : '#0a0a0a',
                border: 'none', borderRadius: 8, cursor: running ? 'not-allowed' : 'pointer',
                fontSize: 13, fontWeight: 700, fontFamily: 'var(--f-mono)',
                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                transition: 'background 0.15s',
              }}
            >
              {running ? <><Spinner /> Running…</> : '▶ Run Pump Study'}
            </button>

            {runError && (
              <div style={{ marginTop: 10, fontSize: 12, color: '#ff4444', fontFamily: 'var(--f-mono)' }}>
                Error: {runError}
              </div>
            )}

            {/* Past Runs */}
            <div style={{ marginTop: 28 }}>
              <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 10 }}>
                Past Runs
              </div>
              {pastRuns.length === 0 ? (
                <div style={{ fontSize: 12, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)', padding: '8px 0' }}>
                  No runs yet
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {pastRuns.map((run, i) => {
                    const rid = run.run_id || run.id;
                    const isActive = activeRun && (activeRun.run_id || activeRun.id) === rid;
                    return (
                      <div key={rid || i} style={{
                        background: isActive ? 'var(--pump-lime-soft)' : 'var(--bg-0)',
                        border: `1px solid ${isActive ? 'var(--pump-lime)' : 'var(--stroke-soft)'}`,
                        borderRadius: 8, padding: '10px 12px',
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                          <span style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 140 }}>
                            {rid}
                          </span>
                          <StatusBadge status={run.status} />
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--ink-dim)', marginBottom: 6 }}>
                          {run.start_date || '?'} → {run.end_date || '?'}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <span style={{ fontSize: 11, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)' }}>
                            {run.episode_count != null ? `${run.episode_count} episodes` : ''}
                            {run.min_multiple ? ` · ×${run.min_multiple}` : ''}
                            {run.scoring_config_version ? ` · cfg ${run.scoring_config_version}` : ''}
                          </span>
                          <button
                            onClick={() => handleViewRun(run)}
                            style={{
                              background: 'var(--bg-2)', border: '1px solid var(--stroke-soft)',
                              borderRadius: 5, padding: '3px 10px', cursor: 'pointer',
                              fontSize: 11, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)',
                            }}
                          >
                            View
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); handleDeleteRun(run); }}
                            title="Delete this run and all its child rows"
                            style={{
                              background: 'transparent', border: '1px solid var(--stroke-soft)',
                              borderRadius: 5, padding: '3px 8px', cursor: 'pointer',
                              fontSize: 11, color: '#ff6b6b', fontFamily: 'var(--f-mono)',
                              marginLeft: 6,
                            }}
                          >
                            ×
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        </aside>

        {/* RIGHT PANEL */}
        <main style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', background: 'var(--bg-0)' }}>
          {!activeRun && !running ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 16, color: 'var(--ink-dim)' }}>
              <svg width={48} height={48} viewBox="0 0 24 24" fill="none" style={{ color: 'var(--stroke-soft)' }}>
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <div style={{ fontSize: 14, fontFamily: 'var(--f-mono)' }}>Configure and run a pump study, or select a past run</div>
            </div>
          ) : running && !activeRun ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 16 }}>
              <Spinner />
              <div style={{ fontSize: 14, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)' }}>Running pump study…</div>
              <div style={{ fontSize: 12, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>Polling for results every 3s</div>
            </div>
          ) : activeRun ? (
            <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              {/* Run header */}
              <div style={{
                padding: '16px 24px', borderBottom: '1px solid var(--stroke-soft)',
                background: 'var(--bg-1)', display: 'flex', alignItems: 'center',
                gap: 20, flexWrap: 'wrap',
              }}>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Run</div>
                  <div style={{ fontSize: 12, color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{activeRun.run_id || activeRun.id}</div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Period</div>
                  <div style={{ fontSize: 12, color: 'var(--ink)' }}>{activeRun.start_date} → {activeRun.end_date}</div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Min ×</div>
                  <div style={{ fontSize: 12, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)' }}>{activeRun.min_multiple || '—'}</div>
                </div>
                {activeRun.episode_count != null && (
                  <div>
                    <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Episodes</div>
                    <div style={{ fontSize: 12, color: 'var(--ink)' }}>{activeRun.episode_count}</div>
                  </div>
                )}
                <div>
                  <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Config</div>
                  <div style={{ fontSize: 12, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)' }}>
                    {activeRun.scoring_config_version || '—'}
                    {scoringConfig && scoringConfig.version && activeRun.scoring_config_version &&
                     scoringConfig.version !== activeRun.scoring_config_version && (
                      <span style={{ color: '#ffa940', marginLeft: 6 }} title={`Current config is ${scoringConfig.version}`}>
                        (stale)
                      </span>
                    )}
                  </div>
                </div>
                <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
                  <button
                    onClick={handleReScore}
                    disabled={reScoring || !activeRun || activeRun.status === 'running'}
                    title="Re-run demand scoring on existing snapshots with the current scoring_config. No candle re-fetch."
                    style={{
                      background: reScoring ? 'var(--bg-2)' : 'var(--bg-1)',
                      border: '1px solid var(--stroke-soft)',
                      borderRadius: 6, padding: '5px 11px',
                      cursor: reScoring ? 'not-allowed' : 'pointer',
                      fontSize: 11, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)',
                      display: 'inline-flex', alignItems: 'center', gap: 6,
                    }}
                  >
                    {reScoring ? <><Spinner /> Re-scoring…</> : '↻ Re-score'}
                  </button>
                  <StatusBadge status={activeRun.status} />
                </div>
              </div>

              {/* Tabs */}
              <div style={{ borderBottom: '1px solid var(--stroke-soft)', background: 'var(--bg-1)', padding: '0 24px', display: 'flex', gap: 0 }}>
                {['episodes', 'signal-lift', 'score-dist'].map(t => (
                  <Tab key={t} label={t === 'episodes' ? 'Episodes' : t === 'signal-lift' ? 'Signal Lift' : 'Score Distribution'} active={activeTab === t} onClick={() => setActiveTab(t)} />
                ))}
              </div>

              {/* Tab content */}
              <div style={{ flex: 1, overflow: 'auto', padding: '20px 24px' }}>

                {/* EPISODES TAB */}
                {activeTab === 'episodes' && (
                  <div>
                    {loadingEpisodes ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 13 }}>
                        <Spinner /> Loading episodes…
                      </div>
                    ) : episodes && episodes.length === 0 ? (
                      <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)', padding: '16px 0' }}>No episodes found.</div>
                    ) : episodes ? (
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                            {['Symbol', 'Multiple', 'Type', 'Start Date', 'Caught?', 'Score'].map(h => (
                              <th key={h} style={{ textAlign: 'left', padding: '6px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 400 }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {episodes.map((ep, i) => {
                            const rid = ep.symbol || i;
                            const expanded = expandedEpisode === i;
                            return [
                              <tr
                                key={`row-${i}`}
                                onClick={() => setExpandedEpisode(expanded ? null : i)}
                                style={{
                                  borderBottom: expanded ? 'none' : '1px solid var(--stroke-soft)',
                                  cursor: 'pointer',
                                  background: expanded ? 'var(--bg-1)' : 'transparent',
                                  transition: 'background 0.1s',
                                }}
                              >
                                <td style={{ padding: '8px 12px', color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontWeight: 600 }}>{ep.symbol || '—'}</td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>
                                  {ep.multiple != null ? `×${parseFloat(ep.multiple).toFixed(2)}` : ep.gain_multiple != null ? `×${parseFloat(ep.gain_multiple).toFixed(2)}` : '—'}
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink-dim)' }}>{ep.pump_type || ep.type || '—'}</td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 11 }}>{ep.start_date || ep.date || '—'}</td>
                                <td style={{ padding: '8px 12px' }}>
                                  {ep.caught != null ? (
                                    <span style={{ color: ep.caught ? '#00c864' : '#ff4444', fontFamily: 'var(--f-mono)', fontSize: 11 }}>
                                      {ep.caught ? 'Yes' : 'No'}
                                    </span>
                                  ) : '—'}
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>
                                  {ep.score != null ? ep.score : '—'}
                                </td>
                              </tr>,
                              expanded && (
                                <tr key={`exp-${i}`} style={{ background: 'var(--bg-1)', borderBottom: '1px solid var(--stroke-soft)' }}>
                                  <td colSpan={6} style={{ padding: '12px 20px' }}>
                                    <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: 12 }}>
                                      {[
                                        ['Pump Type', ep.pump_type || ep.type || '—'],
                                        ['Duration (days)', ep.duration_days || '—'],
                                        ['Peak Price', ep.peak_price != null ? `$${parseFloat(ep.peak_price).toFixed(2)}` : '—'],
                                        ['Start Price', ep.start_price != null ? `$${parseFloat(ep.start_price).toFixed(2)}` : '—'],
                                        ['End Date', ep.end_date || '—'],
                                      ].map(([k, v]) => (
                                        <div key={k}>
                                          <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>{k}</div>
                                          <div style={{ color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{v}</div>
                                        </div>
                                      ))}
                                    </div>
                                  </td>
                                </tr>
                              ),
                            ];
                          })}
                        </tbody>
                      </table>
                    ) : null}
                  </div>
                )}

                {/* SIGNAL LIFT TAB */}
                {activeTab === 'signal-lift' && (
                  <div>
                    {loadingLift ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 13 }}>
                        <Spinner /> Loading signal lift…
                      </div>
                    ) : signalLift && signalLift.length === 0 ? (
                      <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)', padding: '16px 0' }}>No signal lift data.</div>
                    ) : signalLift ? (
                      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                        <thead>
                          <tr style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                            {['Signal', 'Score', 'Lift', 'Target Rate', 'Baseline Rate', 'Count'].map(h => (
                              <th key={h} style={{ textAlign: 'left', padding: '6px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 400 }}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {signalLift.map((row, i) => {
                            const sc = signalScore(row.signal || row.name);
                            return (
                              <tr key={i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                                <td style={{ padding: '8px 12px', color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{row.signal || row.name || '—'}</td>
                                <td style={{ padding: '8px 12px', color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontSize: 11 }}>
                                  {sc != null ? sc : <span style={{ color: 'var(--ink-faint)' }}>—</span>}
                                </td>
                                <td style={{ padding: '8px 12px', color: liftColor(row.lift), fontFamily: 'var(--f-mono)', fontWeight: 600 }}>
                                  {row.lift != null ? parseFloat(row.lift).toFixed(2) : '—'}
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
                                  {row.target_rate != null ? `${(parseFloat(row.target_rate) * 100).toFixed(1)}%` : '—'}
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
                                  {row.baseline_rate != null ? `${(parseFloat(row.baseline_rate) * 100).toFixed(1)}%` : '—'}
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>{row.count || '—'}</td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    ) : null}
                  </div>
                )}

                {/* SCORE DISTRIBUTION TAB */}
                {activeTab === 'score-dist' && (
                  <ScoreDistChart episodes={episodes || []} />
                )}
              </div>
            </div>
          ) : null}
        </main>
      </div>
    </PumpLayout>
  );
}
