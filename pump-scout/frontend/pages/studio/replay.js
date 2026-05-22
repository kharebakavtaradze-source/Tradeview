/**
 * Replay Studio
 * Run historical scanner simulations, measure alpha per score tier, validate signal changes.
 */
import { useEffect, useState, useRef, useCallback } from 'react';
import PumpLayout from '../../components/PumpLayout';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

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

function TierBadge({ tier }) {
  const colors = {
    A: { bg: 'rgba(0,200,100,0.18)', color: '#00c864' },
    B: { bg: 'rgba(200,255,0,0.14)', color: 'var(--pump-lime)' },
    C: { bg: 'rgba(255,180,0,0.14)', color: '#ffb400' },
    D: { bg: 'rgba(255,68,68,0.12)', color: '#ff4444' },
  };
  const s = colors[tier] || { bg: 'var(--bg-2)', color: 'var(--ink-dim)' };
  return (
    <span style={{
      fontSize: 11, fontFamily: 'var(--f-mono)', fontWeight: 700,
      padding: '2px 8px', borderRadius: 4,
      background: s.bg, color: s.color, display: 'inline-block',
    }}>
      {tier || '—'}
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

function Input({ value, onChange, type = 'text', step, min, placeholder }) {
  return (
    <input
      type={type}
      value={value}
      step={step}
      min={min}
      placeholder={placeholder}
      onChange={e => onChange(e.target.value)}
      style={{
        width: '100%', background: 'var(--bg-0)', border: '1px solid var(--stroke-soft)',
        borderRadius: 6, padding: '7px 10px', color: 'var(--ink)',
        fontFamily: 'var(--f-mono)', fontSize: 13, outline: 'none',
        boxSizing: 'border-box',
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

function StatCard({ label, value, accent }) {
  return (
    <div style={{
      background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)',
      borderRadius: 10, padding: '14px 18px', minWidth: 120,
    }}>
      <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: accent ? 'var(--pump-lime)' : 'var(--ink)', fontFamily: 'var(--f-mono)' }}>
        {value ?? '—'}
      </div>
    </div>
  );
}

export default function ReplayStudio() {
  const [startDate, setStartDate] = useState(defaultStart);
  const [endDate, setEndDate] = useState(defaultEnd);
  const [universeLimit, setUniverseLimit] = useState('0');

  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState(null);
  const sawRunningRef = useRef(false);

  const [activeRun, setActiveRun] = useState(null);
  const [summary, setSummary] = useState(null);
  const [activeTab, setActiveTab] = useState('candidates');

  const [candidates, setCandidates] = useState(null);
  const [outcomes, setOutcomes] = useState(null);
  const [missed, setMissed] = useState(null);
  const [pastRuns, setPastRuns] = useState([]);

  const [loadingTab, setLoadingTab] = useState(false);

  const pollRef = useRef(null);

  const loadHistory = useCallback(() => {
    fetch(`${API_URL}/api/replay/history`)
      .then(r => r.ok ? r.json() : {})
      .then(data => setPastRuns(Array.isArray(data) ? data : (data.runs || [])))
      .catch(() => setPastRuns([]));
  }, []);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  // Replay POST returns no run_id; poll the global progress endpoint until idle,
  // then pick up the run_id it exposes and load that run's details.
  useEffect(() => {
    if (!running) return;
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`${API_URL}/api/replay/status`);
        if (!r.ok) return;
        const prog = await r.json();
        if (prog.running) {
          sawRunningRef.current = true;
          return;
        }
        // Avoid terminating on the startup race before the engine flips to running.
        if (!sawRunningRef.current && !prog.run_id) return;
        clearInterval(pollRef.current);
        setRunning(false);
        loadHistory();
        const finishedId = prog.run_id;
        if (finishedId) {
          try {
            const rr = await fetch(`${API_URL}/api/replay/${finishedId}`);
            if (rr.ok) setActiveRun(await rr.json());
          } catch {}
          loadRunDetails(finishedId);
        }
      } catch {}
    }, 3000);
    return () => clearInterval(pollRef.current);
  }, [running, loadHistory]);

  const loadRunDetails = useCallback(async (runId) => {
    setSummary(null);
    setCandidates(null);
    setOutcomes(null);
    setMissed(null);
    setLoadingTab(true);

    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}/summary`);
      if (r.ok) setSummary(await r.json());
    } catch {}

    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}/candidates`);
      const data = r.ok ? await r.json() : [];
      setCandidates(Array.isArray(data) ? data : (data.candidates || []));
    } catch { setCandidates([]); }

    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}/outcomes`);
      const data = r.ok ? await r.json() : [];
      setOutcomes(Array.isArray(data) ? data : (data.outcomes || []));
    } catch { setOutcomes([]); }

    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}/missed`);
      const data = r.ok ? await r.json() : [];
      setMissed(Array.isArray(data) ? data : (data.missed_movers || data.missed || []));
    } catch { setMissed([]); }

    setLoadingTab(false);
  }, []);

  const handleRun = async () => {
    setRunError(null);
    setRunning(true);
    setActiveRun(null);
    setSummary(null);
    setCandidates(null);
    setOutcomes(null);
    setMissed(null);
    try {
      const r = await fetch(`${API_URL}/api/replay/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          start_date: startDate,
          end_date: endDate,
          universe_limit: parseInt(universeLimit) || 0,
        }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await r.json();
      sawRunningRef.current = false;
    } catch (e) {
      setRunError(e.message);
      setRunning(false);
    }
  };

  const handleViewRun = async (run) => {
    const runId = run.run_id || run.id;
    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}`);
      const data = r.ok ? await r.json() : run;
      setActiveRun(data);
    } catch { setActiveRun(run); }
    setActiveTab('candidates');
    loadRunDetails(runId);
  };

  return (
    <PumpLayout title="Replay" subtitle="Studio">
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
                <Label>Universe Limit (0 = all)</Label>
                <Input type="number" value={universeLimit} onChange={setUniverseLimit} step="1" min="0" placeholder="0" />
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
              {running ? <><Spinner /> Running…</> : '▶ Run Replay'}
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
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>
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
                <circle cx="12" cy="12" r="10" stroke="currentColor" fill="none" />
                <polyline points="10 8 16 12 10 16 10 8" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <div style={{ fontSize: 14, fontFamily: 'var(--f-mono)' }}>Configure and run a replay, or select a past run</div>
            </div>
          ) : running && !activeRun ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 16 }}>
              <Spinner />
              <div style={{ fontSize: 14, color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)' }}>Running replay…</div>
              <div style={{ fontSize: 12, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>Polling for results every 3s</div>
            </div>
          ) : activeRun ? (
            <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              {/* Run header */}
              <div style={{
                padding: '14px 24px', borderBottom: '1px solid var(--stroke-soft)',
                background: 'var(--bg-1)', display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
              }}>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Run ID</div>
                  <div style={{ fontSize: 12, color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{activeRun.run_id || activeRun.id}</div>
                </div>
                <div>
                  <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Period</div>
                  <div style={{ fontSize: 12, color: 'var(--ink)' }}>{activeRun.start_date} → {activeRun.end_date}</div>
                </div>
                <div style={{ marginLeft: 'auto' }}>
                  <StatusBadge status={activeRun.status} />
                </div>
              </div>

              {/* Summary stats */}
              {summary && (
                <div style={{ padding: '14px 24px', borderBottom: '1px solid var(--stroke-soft)', display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                  <StatCard label="Total Candidates" value={summary.total_candidates ?? summary.candidates} />
                  <StatCard label="Winners" value={summary.winners} accent />
                  <StatCard label="Win Rate" value={summary.win_rate != null ? `${(parseFloat(summary.win_rate) * 100).toFixed(1)}%` : null} accent />
                </div>
              )}

              {/* Tabs */}
              <div style={{ borderBottom: '1px solid var(--stroke-soft)', background: 'var(--bg-1)', padding: '0 24px', display: 'flex', gap: 0 }}>
                {[
                  { key: 'candidates', label: 'Candidates' },
                  { key: 'outcomes',   label: 'Outcomes' },
                  { key: 'missed',     label: 'Missed' },
                ].map(t => (
                  <Tab key={t.key} label={t.label} active={activeTab === t.key} onClick={() => setActiveTab(t.key)} />
                ))}
              </div>

              {/* Tab content */}
              <div style={{ flex: 1, overflow: 'auto', padding: '20px 24px' }}>
                {loadingTab ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 13 }}>
                    <Spinner /> Loading…
                  </div>
                ) : (
                  <>
                    {/* CANDIDATES */}
                    {activeTab === 'candidates' && (
                      candidates && candidates.length === 0 ? (
                        <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)', padding: '16px 0' }}>No candidates found.</div>
                      ) : candidates ? (
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                          <thead>
                            <tr style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                              {['Symbol', 'Score Tier', 'Score', 'Date', 'Signal'].map(h => (
                                <th key={h} style={{ textAlign: 'left', padding: '6px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 400 }}>{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {candidates.map((c, i) => (
                              <tr key={i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                                <td style={{ padding: '8px 12px', color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontWeight: 600 }}>{c.symbol || '—'}</td>
                                <td style={{ padding: '8px 12px' }}>
                                  <TierBadge tier={c.demand_composite_tier || c.score_tier || c.tier} />
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{c.score ?? c.composite_score ?? '—'}</td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 11 }}>{c.date || c.scan_date || '—'}</td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink-dim)', fontSize: 11, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.signal || c.top_signal || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : null
                    )}

                    {/* OUTCOMES */}
                    {activeTab === 'outcomes' && (
                      outcomes && outcomes.length === 0 ? (
                        <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)', padding: '16px 0' }}>No outcome data.</div>
                      ) : outcomes ? (
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                          <thead>
                            <tr style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                              {['Symbol', 'Outcome', 'Return 5d', 'Score'].map(h => (
                                <th key={h} style={{ textAlign: 'left', padding: '6px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 400 }}>{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {outcomes.map((o, i) => {
                              const ret = o.return_5d ?? o.return5d ?? o.return;
                              const isPos = ret != null && parseFloat(ret) >= 0;
                              return (
                                <tr key={i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                                  <td style={{ padding: '8px 12px', color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontWeight: 600 }}>{o.symbol || '—'}</td>
                                  <td style={{ padding: '8px 12px', color: 'var(--ink-dim)' }}>{o.outcome_label || o.outcome || '—'}</td>
                                  <td style={{ padding: '8px 12px', color: ret != null ? (isPos ? '#00c864' : '#ff4444') : 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontWeight: 600 }}>
                                    {ret != null ? `${isPos ? '+' : ''}${(parseFloat(ret) * 100).toFixed(1)}%` : '—'}
                                  </td>
                                  <td style={{ padding: '8px 12px', color: 'var(--ink)', fontFamily: 'var(--f-mono)' }}>{o.score ?? '—'}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      ) : null
                    )}

                    {/* MISSED */}
                    {activeTab === 'missed' && (
                      missed && missed.length === 0 ? (
                        <div style={{ color: 'var(--ink-dim)', fontSize: 13, fontFamily: 'var(--f-mono)', padding: '16px 0' }}>No missed pumps recorded.</div>
                      ) : missed ? (
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                          <thead>
                            <tr style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                              {['Symbol', 'Multiple', 'Miss Reason', 'Date'].map(h => (
                                <th key={h} style={{ textAlign: 'left', padding: '6px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 400 }}>{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {missed.map((m, i) => (
                              <tr key={i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                                <td style={{ padding: '8px 12px', color: 'var(--pump-lime)', fontFamily: 'var(--f-mono)', fontWeight: 600 }}>{m.symbol || '—'}</td>
                                <td style={{ padding: '8px 12px', color: '#ff4444', fontFamily: 'var(--f-mono)' }}>
                                  {m.multiple != null ? `×${parseFloat(m.multiple).toFixed(2)}` : m.gain_multiple != null ? `×${parseFloat(m.gain_multiple).toFixed(2)}` : '—'}
                                </td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink-dim)' }}>{m.miss_reason || m.reason || '—'}</td>
                                <td style={{ padding: '8px 12px', color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', fontSize: 11 }}>{m.date || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      ) : null
                    )}
                  </>
                )}
              </div>
            </div>
          ) : null}
        </main>
      </div>
    </PumpLayout>
  );
}
