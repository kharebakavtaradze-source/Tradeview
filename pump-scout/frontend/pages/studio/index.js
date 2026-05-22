/**
 * Studio Hub — Analytics Studio landing page
 * Shows the three studios as cards with recent run info and config version banner.
 */
import { useEffect, useState } from 'react';
import Link from 'next/link';
import PumpLayout from '../../components/PumpLayout';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function StatusBadge({ status }) {
  const colors = {
    done:     { bg: 'rgba(0,200,100,0.15)',  color: 'var(--pos)' },
    running:  { bg: 'rgba(200,255,0,0.12)',  color: 'var(--pump-lime)' },
    error:    { bg: 'rgba(255,68,68,0.15)',  color: 'var(--neg)' },
    complete: { bg: 'rgba(0,200,100,0.15)',  color: 'var(--pos)' },
  };
  const s = colors[status] || { bg: 'var(--bg-2)', color: 'var(--ink-dim)' };
  return (
    <span style={{
      fontSize: 10, fontFamily: 'var(--f-mono)', textTransform: 'uppercase',
      letterSpacing: '0.08em', padding: '2px 7px', borderRadius: 4,
      background: s.bg, color: s.color,
    }}>
      {status || 'unknown'}
    </span>
  );
}

function StudioCard({ title, description, href, recentRun, icon }) {
  const [hover, setHover] = useState(false);
  return (
    <Link href={href} style={{ textDecoration: 'none' }}>
      <div
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          background: hover ? 'var(--bg-2)' : 'var(--bg-1)',
          border: `1px solid ${hover ? 'var(--stroke)' : 'var(--stroke-soft)'}`,
          borderRadius: 14,
          padding: '24px 22px 20px',
          display: 'flex', flexDirection: 'column', gap: 12,
          cursor: 'pointer', transition: 'background 0.15s, border-color 0.15s',
          minHeight: 200,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
          <div style={{
            width: 40, height: 40, borderRadius: 10,
            background: 'var(--pump-lime-soft)', display: 'flex',
            alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          }}>
            <svg width={20} height={20} viewBox="0 0 24 24" fill="none" style={{ color: 'var(--pump-lime)' }}>
              {icon}
            </svg>
          </div>
          <div style={{
            fontSize: 10, fontFamily: 'var(--f-mono)', color: 'var(--pump-lime)',
            background: 'var(--pump-lime-soft)', padding: '3px 8px', borderRadius: 4,
            letterSpacing: '0.06em', textTransform: 'uppercase',
          }}>
            Studio
          </div>
        </div>

        <div>
          <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--ink)', marginBottom: 6 }}>{title}</div>
          <div style={{ fontSize: 13, color: 'var(--ink-dim)', lineHeight: 1.55 }}>{description}</div>
        </div>

        <div style={{ marginTop: 'auto', paddingTop: 12, borderTop: '1px solid var(--stroke-soft)' }}>
          {recentRun ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
                Last: {recentRun.created_at ? new Date(recentRun.created_at).toLocaleDateString() : 'N/A'}
              </span>
              {recentRun.status && <StatusBadge status={recentRun.status} />}
            </div>
          ) : (
            <span style={{ fontSize: 11, color: 'var(--ink-faint)', fontFamily: 'var(--f-mono)' }}>
              No runs yet — click to get started
            </span>
          )}
        </div>

        <div style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          fontSize: 12, fontWeight: 500, color: hover ? 'var(--pump-lime)' : 'var(--ink-dim)',
          transition: 'color 0.15s',
        }}>
          New Run
          <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
            <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
          </svg>
        </div>
      </div>
    </Link>
  );
}

const PUMP_ICON = <><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>;
const REPLAY_ICON = <><circle cx="12" cy="12" r="10" stroke="currentColor" fill="none" /><polyline points="10 8 16 12 10 16 10 8" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>;
const PATTERN_ICON = <><polyline points="22 12 18 12 15 21 9 3 6 12 2 12" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>;
const SIGNALS_ICON = <><rect x="3" y="13" width="4" height="8" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><rect x="10" y="8" width="4" height="13" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /><rect x="17" y="3" width="4" height="18" stroke="currentColor" fill="none" strokeLinecap="round" strokeLinejoin="round" /></>;

export default function StudioIndex() {
  const [pumpRuns, setPumpRuns] = useState([]);
  const [replayRuns, setReplayRuns] = useState([]);
  const [config, setConfig] = useState(null);
  const [configError, setConfigError] = useState(null);

  useEffect(() => {
    fetch(`${API_URL}/api/replay/pump-study/runs?limit=3`)
      .then(r => r.ok ? r.json() : {})
      .then(data => setPumpRuns(Array.isArray(data) ? data : (data.runs || [])))
      .catch(() => setPumpRuns([]));

    fetch(`${API_URL}/api/replay/history?limit=3`)
      .then(r => r.ok ? r.json() : {})
      .then(data => setReplayRuns(Array.isArray(data) ? data : (data.runs || [])))
      .catch(() => setReplayRuns([]));

    fetch(`${API_URL}/api/analytics/scoring-config`)
      .then(r => r.ok ? r.json() : null)
      .then(data => setConfig(data ? (data.config || data) : null))
      .catch(() => setConfigError('Could not load scoring config'));
  }, []);

  const signalCount = config
    ? (config.signals ? Object.keys(config.signals).length : (config.signal_count || '—'))
    : '—';

  return (
    <PumpLayout title="Analytics" subtitle="Studio">
      <div style={{ padding: '24px 28px', maxWidth: 1100, margin: '0 auto' }}>

        {/* Config Version Banner */}
        <div style={{
          background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)',
          borderRadius: 10, padding: '12px 18px', marginBottom: 28,
          display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap',
        }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: configError ? 'var(--neg)' : 'var(--pump-lime)', flexShrink: 0,
          }} />
          <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
              <span style={{ color: 'var(--ink-faint)', marginRight: 6 }}>CONFIG VERSION</span>
              <span style={{ color: 'var(--ink)' }}>
                {configError ? 'unavailable' : (config ? (config.version || config.config_version || '—') : 'loading…')}
              </span>
            </span>
            <span style={{ fontSize: 12, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
              <span style={{ color: 'var(--ink-faint)', marginRight: 6 }}>SIGNALS</span>
              <span style={{ color: 'var(--pump-lime)' }}>{config ? signalCount : '…'}</span>
            </span>
          </div>
          {configError && (
            <span style={{ fontSize: 11, color: 'var(--neg)', marginLeft: 'auto' }}>{configError}</span>
          )}
        </div>

        {/* Page header */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6 }}>
            Research Workbench
          </div>
          <h2 style={{ margin: 0, fontSize: 22, fontWeight: 600, color: 'var(--ink)' }}>
            Choose a Studio
          </h2>
          <p style={{ margin: '6px 0 0', fontSize: 14, color: 'var(--ink-dim)' }}>
            Run backtests, analyze signal performance, and discover patterns in pump episodes.
          </p>
        </div>

        {/* 3-column card grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: 16,
        }}>
          <StudioCard
            title="Pump Study Studio"
            description="Detect pump episodes, analyze signal lift, compare signal performance across time windows."
            href="/studio/pump-study"
            recentRun={pumpRuns[0] || null}
            icon={PUMP_ICON}
          />
          <StudioCard
            title="Replay Studio"
            description="Run historical scanner simulations, measure alpha per score tier, validate signal changes."
            href="/studio/replay"
            recentRun={replayRuns[0] || null}
            icon={REPLAY_ICON}
          />
          <StudioCard
            title="Pattern Study"
            description="Mine bar label sequences that precede confirmed pumps. Discover what patterns look like before breakouts."
            href="/studio/pattern"
            recentRun={null}
            icon={PATTERN_ICON}
          />
          <StudioCard
            title="Signals Explorer"
            description="Query Live history by TZ / PREUP / Line3-5 / Wyckoff. Find which combinations appear most often and how they distribute across tiers."
            href="/studio/signals"
            recentRun={null}
            icon={SIGNALS_ICON}
          />
        </div>

        {/* Recent activity */}
        {(pumpRuns.length > 0 || replayRuns.length > 0) && (
          <div style={{ marginTop: 36 }}>
            <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 14 }}>
              Recent Activity
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {[...pumpRuns.map(r => ({ ...r, _type: 'Pump Study' })), ...replayRuns.map(r => ({ ...r, _type: 'Replay' }))]
                .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))
                .slice(0, 6)
                .map((run, i) => (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '10px 14px', background: 'var(--bg-1)',
                    border: '1px solid var(--stroke-soft)', borderRadius: 8,
                    fontSize: 12,
                  }}>
                    <span style={{ color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', width: 88, flexShrink: 0 }}>
                      {run._type}
                    </span>
                    <span style={{ color: 'var(--ink)', flex: 1, fontFamily: 'var(--f-mono)', fontSize: 11 }}>
                      {run.run_id || run.id || '—'}
                    </span>
                    <span style={{ color: 'var(--ink-dim)' }}>
                      {run.created_at ? new Date(run.created_at).toLocaleDateString() : ''}
                    </span>
                    {run.scoring_config_version && (
                      <span style={{
                        fontSize: 10, fontFamily: 'var(--f-mono)',
                        color: 'var(--pump-lime)', background: 'var(--pump-lime-soft)',
                        padding: '1px 6px', borderRadius: 3,
                      }}>
                        cfg {run.scoring_config_version}
                      </span>
                    )}
                    {run.status && <StatusBadge status={run.status} />}
                  </div>
                ))
              }
            </div>
          </div>
        )}

        {/* Maintenance */}
        <MaintenancePanel />

      </div>
    </PumpLayout>
  );
}

function MaintenancePanel() {
  const [keepLastN, setKeepLastN] = useState(3);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const runCleanup = async (dryRun) => {
    setBusy(true); setMsg(null);
    try {
      const qs = new URLSearchParams({ keep_last_n: String(keepLastN), dry_run: dryRun ? 'true' : 'false' });
      const r = await fetch(`${API_URL}/api/admin/cleanup-all?${qs}`, { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      if (dryRun) {
        setPreview(data);
        setMsg('Preview — pass real cleanup to execute.');
      } else {
        setPreview(null);
        setMsg(`Cleanup done. See server logs for per-table counts.`);
      }
    } catch (e) {
      setMsg(`Error: ${e.message}`);
    }
    setBusy(false);
  };

  const wipeLiveHistory = async () => {
    if (!window.confirm('Wipe ALL demand_ticker_history rows? This deletes every Live scan snapshot. Cannot be undone.')) return;
    setBusy(true); setMsg(null);
    try {
      const r = await fetch(`${API_URL}/api/analytics/live-history?confirm=true`, { method: 'DELETE' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setMsg(`Deleted ${data.deleted} Live history rows.`);
    } catch (e) {
      setMsg(`Error: ${e.message}`);
    }
    setBusy(false);
  };

  return (
    <div style={{ marginTop: 40, paddingTop: 24, borderTop: '1px solid var(--stroke-soft)' }}>
      <div style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 14 }}>
        Maintenance
      </div>
      <div style={{
        background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)',
        borderRadius: 10, padding: 16,
        display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 12, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
            Cleanup old runs — keep last
          </span>
          <input type="number" min="1" max="50" value={keepLastN}
            onChange={e => setKeepLastN(parseInt(e.target.value) || 3)}
            style={{
              width: 60, padding: '6px 8px',
              background: 'var(--bg-2)', border: '1px solid var(--stroke-soft)',
              borderRadius: 6, color: 'var(--ink)',
              fontSize: 12, fontFamily: 'var(--f-mono)',
            }}
          />
          <button
            onClick={() => runCleanup(true)}
            disabled={busy}
            style={{
              padding: '5px 12px', borderRadius: 6, border: '1px solid var(--stroke-soft)',
              background: 'var(--bg-2)', color: 'var(--ink)',
              fontSize: 12, fontFamily: 'var(--f-mono)', cursor: busy ? 'not-allowed' : 'pointer',
            }}
          >
            Preview
          </button>
          <button
            onClick={() => {
              if (window.confirm(`Delete ALL replay / pump-study / raw-pattern runs except the ${keepLastN} most recent of each? Cannot be undone.`)) {
                runCleanup(false);
              }
            }}
            disabled={busy}
            style={{
              padding: '5px 12px', borderRadius: 6, border: '1px solid #ff6b6b',
              background: 'rgba(255,107,107,0.08)', color: '#ff6b6b',
              fontSize: 12, fontFamily: 'var(--f-mono)', fontWeight: 600,
              cursor: busy ? 'not-allowed' : 'pointer',
            }}
          >
            Execute Cleanup
          </button>
        </div>

        <div style={{ width: 1, height: 24, background: 'var(--stroke-soft)' }} />

        <button
          onClick={wipeLiveHistory}
          disabled={busy}
          title="Delete every row in demand_ticker_history"
          style={{
            padding: '5px 12px', borderRadius: 6, border: '1px solid #ff6b6b',
            background: 'rgba(255,107,107,0.08)', color: '#ff6b6b',
            fontSize: 12, fontFamily: 'var(--f-mono)', fontWeight: 600,
            cursor: busy ? 'not-allowed' : 'pointer',
          }}
        >
          Wipe Live History
        </button>

        {msg && (
          <span style={{ fontSize: 11, color: msg.startsWith('Error') ? '#ff4444' : 'var(--ink-dim)', fontFamily: 'var(--f-mono)', marginLeft: 'auto' }}>
            {msg}
          </span>
        )}
      </div>

      {preview && (
        <pre style={{
          marginTop: 10, padding: 12, borderRadius: 8,
          background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)',
          fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)',
          overflowX: 'auto', whiteSpace: 'pre-wrap',
        }}>
          {JSON.stringify(preview, null, 2)}
        </pre>
      )}
    </div>
  );
}
