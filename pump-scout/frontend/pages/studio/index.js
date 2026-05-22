/**
 * Analytics Hub — Studio landing page
 * Shows all three studios as cards, config version, and scoring signals table.
 */
import { useEffect, useState } from 'react';
import Link from 'next/link';
import PumpLayout from '../../components/PumpLayout';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const fmtDate = d => d ? new Date(d).toISOString().slice(0, 10) : '—';

function StatusBadge({ s }) {
  const map = { done: '#00c864', complete: '#00c864', running: '#c8ff00', error: '#ff4444', failed: '#ff4444' };
  const c = map[(s || '').toLowerCase()] || '#666';
  return (
    <span style={{
      fontFamily: 'var(--f-mono)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.08em',
      padding: '2px 8px', borderRadius: 3, background: `${c}22`, color: c, border: `1px solid ${c}44`,
    }}>{s || '—'}</span>
  );
}

function StudioCard({ icon, title, description, href, recentRun }) {
  const [hover, setHover] = useState(false);
  return (
    <Link href={href} style={{ textDecoration: 'none' }}>
      <div
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        style={{
          background: hover ? 'var(--bg-2)' : 'var(--bg-1)',
          border: `1px solid ${hover ? 'var(--pump-lime)' : 'var(--stroke-soft)'}`,
          borderRadius: 12, padding: '22px 20px 18px',
          display: 'flex', flexDirection: 'column', gap: 12,
          cursor: 'pointer', transition: 'all 0.15s', minHeight: 200,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 8, background: 'rgba(200,255,0,0.10)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 18, color: 'var(--pump-lime)',
          }}>{icon}</div>
          <div style={{
            fontSize: 10, fontFamily: 'var(--f-mono)', color: 'var(--pump-lime)',
            background: 'rgba(200,255,0,0.08)', padding: '2px 7px', borderRadius: 4,
            letterSpacing: '0.07em', textTransform: 'uppercase', border: '1px solid rgba(200,255,0,0.18)',
          }}>Studio</div>
        </div>
        <div>
          <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--ink)', marginBottom: 5 }}>{title}</div>
          <div style={{ fontSize: 12, color: 'var(--ink-dim)', lineHeight: 1.6 }}>{description}</div>
        </div>
        <div style={{ marginTop: 'auto', paddingTop: 12, borderTop: '1px solid var(--stroke-soft)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          {recentRun ? (
            <>
              <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
                Last: {fmtDate(recentRun.created_at)}
              </span>
              {recentRun.status && <StatusBadge s={recentRun.status} />}
            </>
          ) : (
            <span style={{ fontSize: 11, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>No runs yet</span>
          )}
          <span style={{ fontSize: 12, color: hover ? 'var(--pump-lime)' : 'var(--ink-dim)', fontFamily: 'var(--f-mono)', transition: 'color 0.15s' }}>Open →</span>
        </div>
      </div>
    </Link>
  );
}

export default function StudioIndex() {
  const [config, setConfig] = useState(null);
  const [configErr, setConfigErr] = useState(null);
  const [pumpRun, setPumpRun] = useState(null);
  const [replayRun, setReplayRun] = useState(null);
  const [showSignals, setShowSignals] = useState(false);

  useEffect(() => {
    fetch(`${API}/api/analytics/scoring-config`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(setConfig)
      .catch(() => setConfigErr('Could not load scoring config'));

    fetch(`${API}/api/replay/pump-study/runs?limit=1`)
      .then(r => r.ok ? r.json() : [])
      .then(d => setPumpRun(Array.isArray(d) ? d[0] || null : null))
      .catch(() => {});

    fetch(`${API}/api/replay/history?limit=1`)
      .then(r => r.ok ? r.json() : [])
      .then(d => setReplayRun(Array.isArray(d) ? d[0] || null : null))
      .catch(() => {});
  }, []);

  const version = config ? (config.version || config.config_version || '—') : (configErr ? 'unavailable' : '…');
  const signals = config && config.signals ? Object.entries(config.signals) : [];

  return (
    <PumpLayout title="Analytics" subtitle="Platform">
      <div style={{ padding: '28px 32px', maxWidth: 1080, margin: '0 auto' }}>

        {/* Top banner */}
        <div style={{
          background: 'var(--bg-1)', border: '1px solid var(--stroke-soft)',
          borderRadius: 10, padding: '12px 18px', marginBottom: 28,
          display: 'flex', alignItems: 'center', gap: 18, flexWrap: 'wrap',
        }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: configErr ? '#ff4444' : 'var(--pump-lime)', flexShrink: 0 }} />
          <span style={{ fontSize: 18, fontWeight: 700, color: 'var(--ink)' }}>Analytics Platform</span>
          <div style={{
            fontSize: 11, fontFamily: 'var(--f-mono)', color: 'var(--pump-lime)',
            background: 'rgba(200,255,0,0.08)', border: '1px solid rgba(200,255,0,0.2)',
            padding: '3px 10px', borderRadius: 4, letterSpacing: '0.06em',
          }}>
            CONFIG v{version}
          </div>
          {signals.length > 0 && (
            <span style={{ fontSize: 12, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
              {signals.length} signals
            </span>
          )}
          {configErr && <span style={{ fontSize: 11, color: '#ff4444', marginLeft: 'auto' }}>{configErr}</span>}
        </div>

        {/* Studio cards grid */}
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 10, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)', letterSpacing: '0.1em', textTransform: 'uppercase', marginBottom: 6 }}>
            Research Workbench
          </div>
          <h2 style={{ margin: '0 0 20px', fontSize: 20, fontWeight: 600, color: 'var(--ink)' }}>Choose a Studio</h2>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 16, marginBottom: 36 }}>
          <StudioCard
            icon="⚡"
            title="Pump Study Studio"
            description="Detect pump episodes, measure signal lift, analyze gain distributions"
            href="/studio/pump-study"
            recentRun={pumpRun}
          />
          <StudioCard
            icon="↔"
            title="Replay Studio"
            description="Simulate scanner on historical data, measure alpha per score tier"
            href="/studio/replay"
            recentRun={replayRun}
          />
          <StudioCard
            icon="▮"
            title="Pattern Study"
            description="Mine bar label sequences that precede confirmed pump episodes"
            href="/studio/pattern"
            recentRun={null}
          />
        </div>

        {/* Scoring Config expandable */}
        <div style={{ border: '1px solid var(--stroke-soft)', borderRadius: 10, overflow: 'hidden' }}>
          <button
            onClick={() => setShowSignals(v => !v)}
            style={{
              width: '100%', background: 'var(--bg-1)', border: 'none',
              padding: '13px 18px', cursor: 'pointer', textAlign: 'left',
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              color: 'var(--ink)', fontSize: 13, fontFamily: 'var(--f-mono)', fontWeight: 600,
            }}
          >
            <span>Scoring Config <span style={{ color: 'var(--ink-dim)', fontWeight: 400, fontSize: 11 }}>(v{version})</span></span>
            <span style={{ color: 'var(--ink-dim)', fontSize: 11 }}>{showSignals ? '▲ collapse' : '▼ expand'}</span>
          </button>

          {showSignals && (
            <div style={{ padding: '16px 18px', borderTop: '1px solid var(--stroke-soft)', background: 'var(--bg-0)' }}>
              {signals.length === 0 ? (
                <div style={{ fontSize: 12, color: 'var(--ink-dim)', fontFamily: 'var(--f-mono)' }}>
                  {config ? 'No signals data available.' : 'Loading…'}
                </div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                      {['Signal', 'Group', 'Score', 'Enabled'].map(h => (
                        <th key={h} style={{
                          textAlign: 'left', padding: '5px 12px',
                          fontSize: 10, fontFamily: 'var(--f-mono)', color: 'var(--ink-dim)',
                          textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 400,
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {signals.map(([name, val], i) => {
                      const score = typeof val === 'object' ? (val.score ?? val.weight ?? 0) : (val ?? 0);
                      const group = typeof val === 'object' ? (val.group || val.category || '—') : '—';
                      const enabled = typeof val === 'object' ? val.enabled : true;
                      const isPos = score > 0;
                      const isNeg = score < 0;
                      return (
                        <tr key={i} style={{ borderBottom: '1px solid var(--stroke-soft)' }}>
                          <td style={{ padding: '7px 12px', color: 'var(--ink)', fontFamily: 'var(--f-mono)', fontSize: 11 }}>{name}</td>
                          <td style={{ padding: '7px 12px', color: 'var(--ink-dim)', fontSize: 11 }}>{group}</td>
                          <td style={{ padding: '7px 12px', fontFamily: 'var(--f-mono)', fontWeight: 600, color: isPos ? '#00c864' : isNeg ? '#ff4444' : 'var(--ink-dim)' }}>
                            {score > 0 ? `+${score}` : score}
                          </td>
                          <td style={{ padding: '7px 12px' }}>
                            {enabled === false
                              ? <span style={{ fontSize: 10, color: '#ff4444', fontFamily: 'var(--f-mono)' }}>off</span>
                              : <span style={{ fontSize: 10, color: '#00c864', fontFamily: 'var(--f-mono)' }}>on</span>
                            }
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </div>
      </div>
    </PumpLayout>
  );
}
