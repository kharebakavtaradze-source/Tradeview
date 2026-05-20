import { useEffect, useState } from 'react';
import PumpLayout from '../components/PumpLayout';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const fmt = (v, d = 1) => v == null ? '—' : Number(v).toFixed(d);
const CONFIDENCE_COLOR = { HIGH: '#34d399', MEDIUM: '#fbbf24', LOW: '#f87171' };

const pnlColor = v => v > 0 ? '#34d399' : v < 0 ? '#f87171' : '#9ca3af';
const pnlSign  = v => v > 0 ? '+' : '';

const fmtPatternKey = key => {
  if (!key) return key;
  return key.split('|').map(p => p.replace(/_/g, ' ')).join(' + ');
};

export default function AIJournalPage() {
  const [state,       setState]       = useState(null);
  const [positions,   setPositions]   = useState([]);
  const [entries,     setEntries]     = useState([]);
  const [running,     setRunning]     = useState(false);
  const [tab,         setTab]         = useState('journal');
  const [perfStats,   setPerfStats]   = useState(null);
  const [patterns,    setPatterns]    = useState([]);
  const [lessons,     setLessons]     = useState([]);
  const [blacklist,   setBlacklist]   = useState([]);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillMsg, setBackfillMsg] = useState(null);
  const [loadError,   setLoadError]   = useState(null);

  const reload = async () => {
    setLoadError(null);
    try {
      const [s, p, e, h, stats, pats, les, bl] = await Promise.all([
        fetch(`${API_URL}/api/ai-journal/state`).then(r => { if (!r.ok) throw new Error(`state ${r.status}`); return r.json(); }),
        fetch(`${API_URL}/api/ai-journal/positions?status=OPEN`).then(r => r.json()).catch(() => ({ positions: [] })),
        fetch(`${API_URL}/api/ai-journal/entries?limit=20`).then(r => r.json()).catch(() => ({ entries: [] })),
        fetch(`${API_URL}/api/ai-journal/positions?status=CLOSED`).then(r => r.json()).catch(() => ({ positions: [] })),
        fetch(`${API_URL}/api/ai-journal/stats`).then(r => r.json()).catch(() => null),
        fetch(`${API_URL}/api/ai-journal/patterns`).then(r => r.json()).catch(() => ({ patterns: [] })),
        fetch(`${API_URL}/api/ai-journal/lessons?limit=30`).then(r => r.json()).catch(() => ({ lessons: [] })),
        fetch(`${API_URL}/api/ai-journal/blacklist`).then(r => r.json()).catch(() => ({ blacklist: [] })),
      ]);
      setState(s);
      setPositions(p.positions || []);
      setEntries(e.entries || []);
      setState(prev => ({ ...prev, _closed: h.positions || [] }));
      if (stats) setPerfStats(stats);
      setPatterns(pats.patterns || []);
      setLessons(les.lessons || []);
      setBlacklist(bl.blacklist || []);
    } catch (err) {
      console.error('AIJournal reload failed:', err);
      setLoadError(err.message);
    }
  };

  useEffect(() => { reload(); }, []);

  const runSession = async () => {
    setRunning(true);
    try {
      const res  = await fetch(`${API_URL}/api/ai-journal/run`, { method: 'POST' });
      const json = await res.json();
      if (json.error) throw new Error(json.error);
      await reload();
    } catch (e) {
      alert(`AI Journal error: ${e.message}`);
    } finally {
      setRunning(false);
    }
  };

  const runBackfill = async () => {
    setBackfilling(true);
    setBackfillMsg(null);
    try {
      const res  = await fetch(`${API_URL}/api/ai-journal/backfill`, { method: 'POST' });
      const json = await res.json();
      setBackfillMsg(`Backfilled ${json.backfilled ?? 0} signals (${json.errors ?? 0} errors)`);
      setTimeout(() => setBackfillMsg(null), 5000);
      await reload();
    } catch (e) {
      setBackfillMsg(`Backfill error: ${e.message}`);
      setTimeout(() => setBackfillMsg(null), 5000);
    } finally {
      setBackfilling(false);
    }
  };

  // ── Loading / error state ─────────────────────────────────────────────────
  if (!state) return (
    <PumpLayout title="AI Journal">
      <div style={{ maxWidth: 960, margin: '60px auto', padding: '0 24px' }}>
        <div style={{
          background: '#0a0f1a', border: '1px solid #1e3a5f', borderRadius: 10,
          padding: '32px 24px', textAlign: 'center',
        }}>
          <div style={{ fontSize: 18, fontWeight: 800, color: '#60a5fa', marginBottom: 12 }}>
            AI TRADING JOURNAL
          </div>
          {loadError ? (
            <>
              <div style={{ color: '#f87171', fontSize: 13, marginBottom: 16 }}>
                Could not connect to journal API: {loadError}
              </div>
              <button
                onClick={reload}
                style={{ background: '#1e3a5f', border: 'none', color: '#93c5fd', borderRadius: 6, padding: '8px 18px', fontSize: 12, cursor: 'pointer' }}
              >
                Retry
              </button>
            </>
          ) : (
            <div style={{ color: '#6b7280', fontSize: 13 }}>Connecting to journal API…</div>
          )}
        </div>
      </div>
    </PumpLayout>
  );

  const pnlPct  = state.starting_capital > 0
    ? ((state.capital - state.starting_capital) / state.starting_capital * 100).toFixed(1)
    : '0.0';
  const pnlUsd  = (state.capital - state.starting_capital).toFixed(2);
  const isProfit = state.capital >= state.starting_capital;
  const activeBlacklist = blacklist.filter(b => b.active).length;

  return (
    <PumpLayout title="AI Journal">
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '28px 24px' }}>

        {/* Page header */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
            <div>
              <h1 style={{ fontSize: 22, fontWeight: 800, color: '#60a5fa', margin: 0, letterSpacing: '0.03em' }}>
                AI TRADING JOURNAL
              </h1>
              <p style={{ fontSize: 12, color: '#4b5563', margin: '4px 0 0' }}>
                $500 virtual account · R154–R157 strategy · Opus 4.7 adaptive thinking
              </p>
            </div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              {backfillMsg && (
                <span style={{ fontSize: 11, color: '#60a5fa', background: 'rgba(30,58,95,0.5)', padding: '5px 10px', borderRadius: 5 }}>
                  {backfillMsg}
                </span>
              )}
              <button
                onClick={runBackfill}
                disabled={backfilling}
                style={{
                  background: 'transparent', color: backfilling ? '#4b5563' : '#6b7280',
                  border: '1px solid #1f2937', borderRadius: 6, padding: '7px 14px',
                  cursor: backfilling ? 'not-allowed' : 'pointer', fontSize: 11, fontWeight: 600,
                }}
              >
                {backfilling ? 'Backfilling…' : 'Backfill Returns'}
              </button>
              <button
                onClick={reload}
                style={{
                  background: 'transparent', color: '#6b7280',
                  border: '1px solid #1f2937', borderRadius: 6, padding: '7px 14px',
                  cursor: 'pointer', fontSize: 11, fontWeight: 600,
                }}
              >
                Refresh
              </button>
              <button
                onClick={runSession}
                disabled={running}
                style={{
                  background: running ? '#1f2937' : '#1d4ed8',
                  color: running ? '#6b7280' : '#fff',
                  border: 'none', borderRadius: 6, padding: '8px 20px',
                  cursor: running ? 'not-allowed' : 'pointer', fontSize: 12, fontWeight: 700,
                }}
              >
                {running ? '🤖 Thinking…' : 'Run AI Review'}
              </button>
            </div>
          </div>
        </div>

        {/* Account summary cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 10, marginBottom: 20 }}>
          {[
            ['Portfolio',  `$${fmt(state.capital, 2)}`,      isProfit ? '#34d399' : '#f87171'],
            ['Cash',       `$${fmt(state.cash, 2)}`,         '#9ca3af'],
            ['Invested',   `$${fmt(state.invested, 2)}`,     '#60a5fa'],
            ['Total P&L',  `${pnlSign(parseFloat(pnlUsd))}$${pnlUsd}`, pnlColor(parseFloat(pnlUsd))],
            ['Return',     `${pnlSign(parseFloat(pnlPct))}${pnlPct}%`, pnlColor(parseFloat(pnlPct))],
            ['Open',       state.open_positions,              '#fbbf24'],
            ['Closed',     state.closed_trades,               '#9ca3af'],
            ['Win Rate',   `${state.win_rate_pct}%`,          '#34d399'],
          ].map(([label, val, color]) => (
            <div key={label} style={{
              background: '#0d1117', border: '1px solid #1f2937', borderRadius: 8,
              padding: '12px 14px', textAlign: 'center',
            }}>
              <div style={{ fontSize: 16, fontWeight: 800, color }}>{val}</div>
              <div style={{ fontSize: 9, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.06em', marginTop: 3 }}>{label}</div>
            </div>
          ))}
        </div>

        {/* Detailed perf stats */}
        {perfStats && perfStats.total_trades > 0 && (
          <div style={{
            display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 20,
            padding: '10px 16px', background: 'rgba(17,24,39,0.8)',
            borderRadius: 7, border: '1px solid #1f2937', fontSize: 11,
          }}>
            <span style={{ color: '#9ca3af' }}>
              Total trades: <strong style={{ color: '#f9fafb' }}>{perfStats.total_trades}</strong>
            </span>
            <span style={{ color: '#9ca3af' }}>
              Win rate: <strong style={{ color: '#34d399' }}>{(perfStats.win_rate * 100).toFixed(0)}%</strong>
            </span>
            {perfStats.avg_win_pct != null && (
              <span style={{ color: '#9ca3af' }}>
                Avg win: <strong style={{ color: '#34d399' }}>+{fmt(perfStats.avg_win_pct, 1)}%</strong>
              </span>
            )}
            {perfStats.avg_loss_pct != null && (
              <span style={{ color: '#9ca3af' }}>
                Avg loss: <strong style={{ color: '#f87171' }}>{fmt(perfStats.avg_loss_pct, 1)}%</strong>
              </span>
            )}
            <span style={{ color: '#9ca3af' }}>
              Total P&L: <strong style={{ color: pnlColor(perfStats.total_pnl_usd) }}>
                {pnlSign(perfStats.total_pnl_usd)}${fmt(perfStats.total_pnl_usd, 2)}
              </strong>
            </span>
          </div>
        )}

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 16, flexWrap: 'wrap', borderBottom: '1px solid #1f2937', paddingBottom: 12 }}>
          {[
            ['journal',   `Journal (${entries.length})`],
            ['positions', `Open Positions (${positions.length})`],
            ['history',   `History (${(state._closed || []).length})`],
            ['patterns',  `Patterns (${patterns.length})`],
            ['lessons',   `Lessons (${lessons.length})`],
            ['blacklist', activeBlacklist > 0
              ? `Blacklist ⚠ ${activeBlacklist}`
              : `Blacklist (${blacklist.length})`],
          ].map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)} style={{
              background: tab === id ? '#1e3a5f' : 'transparent',
              color: tab === id ? '#60a5fa'
                : id === 'blacklist' && activeBlacklist > 0 ? '#fbbf24'
                : '#6b7280',
              border: `1px solid ${tab === id ? '#1e3a5f' : '#1f2937'}`,
              borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontSize: 11, fontWeight: 600,
            }}>{label}</button>
          ))}
        </div>

        {/* ── Journal tab ────────────────────────────────────────────────── */}
        {tab === 'journal' && (
          <div>
            {entries.length === 0 ? (
              <div style={{ color: '#4b5563', fontSize: 13, padding: '40px 0', textAlign: 'center' }}>
                No journal entries yet. Run an AI review after a demand scan.
              </div>
            ) : entries.map(e => (
              <div key={e.id} style={{
                background: '#0d1117', borderRadius: 8, padding: '14px 16px',
                marginBottom: 12, border: '1px solid #1f2937',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
                  <span style={{ fontSize: 11, color: '#4b5563' }}>
                    {e.created_at?.slice(0, 16).replace('T', ' ')}
                  </span>
                  <div style={{ display: 'flex', gap: 10, fontSize: 10 }}>
                    {e.positions_opened > 0 && (
                      <span style={{ color: '#34d399' }}>+{e.positions_opened} opened</span>
                    )}
                    {e.positions_closed > 0 && (
                      <span style={{ color: '#fbbf24' }}>{e.positions_closed} closed</span>
                    )}
                    <span style={{ color: pnlColor(e.capital_after - e.capital_before), fontWeight: 700 }}>
                      {pnlSign(e.capital_after - e.capital_before)}${(e.capital_after - e.capital_before).toFixed(2)}
                    </span>
                  </div>
                </div>
                <p style={{ fontSize: 12, color: '#d1d5db', lineHeight: 1.8, margin: 0, whiteSpace: 'pre-wrap' }}>
                  {e.journal_text}
                </p>
                {e.strategy_notes && (
                  <div style={{
                    marginTop: 10, padding: '8px 12px', background: 'rgba(96,165,250,0.06)',
                    border: '1px solid rgba(96,165,250,0.15)', borderRadius: 6,
                    fontSize: 11, color: '#93c5fd',
                  }}>
                    Strategy update: {e.strategy_notes}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* ── Positions tab ──────────────────────────────────────────────── */}
        {tab === 'positions' && (
          <div>
            {positions.length === 0 ? (
              <div style={{ color: '#4b5563', fontSize: 13, padding: '40px 0', textAlign: 'center' }}>
                No open positions.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>
                      {['Symbol', 'Entry', 'Current', 'P&L %', 'Target', 'Stop', 'Tier', 'ATS', 'Days'].map(h => (
                        <th key={h} style={{ padding: '8px 12px', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', color: '#6b7280', borderBottom: '1px solid #1f2937', textAlign: 'left', letterSpacing: '0.05em' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map(p => (
                      <tr key={p.id} style={{ borderBottom: '1px solid #111827' }}>
                        <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontWeight: 700, fontSize: 13, color: '#f9fafb' }}>{p.symbol}</td>
                        <td style={{ padding: '10px 12px', fontSize: 12, color: '#9ca3af' }}>${fmt(p.entry_price, 2)}</td>
                        <td style={{ padding: '10px 12px', fontSize: 12, color: p.current_price ? '#f9fafb' : '#4b5563' }}>
                          {p.current_price ? `$${fmt(p.current_price, 2)}` : '—'}
                        </td>
                        <td style={{ padding: '10px 12px', fontSize: 12, fontWeight: 700, color: p.current_pnl_pct != null ? pnlColor(p.current_pnl_pct) : '#4b5563' }}>
                          {p.current_pnl_pct != null ? `${pnlSign(p.current_pnl_pct)}${fmt(p.current_pnl_pct, 1)}%` : '—'}
                        </td>
                        <td style={{ padding: '10px 12px', fontSize: 12, color: '#34d399' }}>${fmt(p.target_price, 2)}</td>
                        <td style={{ padding: '10px 12px', fontSize: 12, color: '#f87171' }}>${fmt(p.stop_price, 2)}</td>
                        <td style={{ padding: '10px 12px', fontSize: 10, color: '#9ca3af' }}>{p.scan_tier?.replace('_BUY', '').replace('_', ' ')}</td>
                        <td style={{ padding: '10px 12px', fontSize: 10, color: '#6b7280' }}>{p.ats_signal?.replace('ATS_', '') || '—'}</td>
                        <td style={{ padding: '10px 12px', fontSize: 11, color: p.days_held >= 12 ? '#fbbf24' : '#6b7280' }}>
                          {p.days_held != null ? `${p.days_held}d` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ── History tab ────────────────────────────────────────────────── */}
        {tab === 'history' && (
          <div>
            {!(state._closed?.length) ? (
              <div style={{ color: '#4b5563', fontSize: 13, padding: '40px 0', textAlign: 'center' }}>
                No closed trades yet.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr>
                      {['Symbol', 'Entry', 'Exit', 'P&L $', 'P&L %', 'Reason', 'Tier', 'Closed'].map(h => (
                        <th key={h} style={{ padding: '8px 12px', fontSize: 10, fontWeight: 700, textTransform: 'uppercase', color: '#6b7280', borderBottom: '1px solid #1f2937', textAlign: 'left', letterSpacing: '0.05em' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(state._closed || []).map(p => (
                      <tr key={p.id} style={{ borderBottom: '1px solid #111827' }}>
                        <td style={{ padding: '10px 12px', fontFamily: 'monospace', fontWeight: 700, fontSize: 13, color: '#f9fafb' }}>{p.symbol}</td>
                        <td style={{ padding: '10px 12px', fontSize: 12, color: '#9ca3af' }}>${fmt(p.entry_price, 2)}</td>
                        <td style={{ padding: '10px 12px', fontSize: 12, color: '#9ca3af' }}>{p.exit_price ? `$${fmt(p.exit_price, 2)}` : '—'}</td>
                        <td style={{ padding: '10px 12px', fontSize: 12, fontWeight: 700, color: pnlColor(p.pnl_usd) }}>
                          {pnlSign(p.pnl_usd)}${fmt(p.pnl_usd, 2)}
                        </td>
                        <td style={{ padding: '10px 12px', fontSize: 12, fontWeight: 700, color: pnlColor(p.pnl_pct) }}>
                          {pnlSign(p.pnl_pct)}{fmt(p.pnl_pct, 1)}%
                        </td>
                        <td style={{ padding: '10px 12px', fontSize: 10, color: '#6b7280' }}>{p.exit_reason || '—'}</td>
                        <td style={{ padding: '10px 12px', fontSize: 10, color: '#9ca3af' }}>{p.scan_tier?.replace('_BUY', '').replace('_', ' ') || '—'}</td>
                        <td style={{ padding: '10px 12px', fontSize: 11, color: '#4b5563' }}>{p.exit_date?.slice(0, 10)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* ── Patterns tab ───────────────────────────────────────────────── */}
        {tab === 'patterns' && (
          <div>
            {patterns.length === 0 ? (
              <div style={{ color: '#4b5563', fontSize: 13, padding: '40px 0', textAlign: 'center' }}>
                No pattern data yet. Run AI reviews after scans to build pattern memory.
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12 }}>
                {patterns.map((pt, i) => {
                  const wr = pt.win_rate || 0;
                  const wrColor = wr > 0.6 ? '#34d399' : wr > 0.4 ? '#fbbf24' : '#f87171';
                  return (
                    <div key={pt.pattern_key || i} style={{
                      background: '#0d1117', borderRadius: 8, padding: '12px 14px',
                      border: '1px solid #1f2937',
                    }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 6 }}>
                        <span style={{ fontSize: 12, fontWeight: 700, color: '#e5e7eb', fontFamily: 'monospace' }}>
                          {fmtPatternKey(pt.pattern_key)}
                        </span>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0, marginLeft: 8 }}>
                          <span style={{
                            fontSize: 11, fontWeight: 700, color: wrColor,
                            background: `${wrColor}20`, padding: '2px 8px', borderRadius: 4,
                          }}>
                            {(wr * 100).toFixed(0)}% win
                          </span>
                          <span style={{ fontSize: 10, color: '#6b7280' }}>{pt.n_trades} trades</span>
                        </div>
                      </div>
                      {pt.notes && (
                        <p style={{ fontSize: 11, color: '#9ca3af', margin: 0, lineHeight: 1.6 }}>
                          {pt.notes.slice(0, 160)}{pt.notes.length > 160 ? '…' : ''}
                        </p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* ── Lessons tab ────────────────────────────────────────────────── */}
        {tab === 'lessons' && (
          <div>
            {lessons.length === 0 ? (
              <div style={{ color: '#4b5563', fontSize: 13, padding: '40px 0', textAlign: 'center' }}>
                No trade lessons yet. Lessons are generated automatically when positions close.
              </div>
            ) : lessons.map(l => {
              const pnlColor2 = l.pnl_pct > 0 ? '#34d399' : l.pnl_pct < 0 ? '#f87171' : '#9ca3af';
              const confColor = CONFIDENCE_COLOR[l.confidence] || '#9ca3af';
              return (
                <div key={l.id} style={{
                  background: '#0d1117', borderRadius: 8, padding: '14px 16px',
                  marginBottom: 12, border: `1px solid ${l.pnl_pct > 0 ? '#14532d40' : '#4b182840'}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <span style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 14, color: '#f9fafb' }}>
                        {l.symbol}
                      </span>
                      <span style={{ fontSize: 13, fontWeight: 700, color: pnlColor2 }}>
                        {l.pnl_pct > 0 ? '+' : ''}{fmt(l.pnl_pct, 1)}%
                      </span>
                      <span style={{ fontSize: 10, color: '#4b5563', background: '#1f2937', padding: '2px 6px', borderRadius: 3 }}>
                        {l.exit_reason}
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      {l.confidence && (
                        <span style={{ fontSize: 10, color: confColor, border: `1px solid ${confColor}40`, padding: '2px 7px', borderRadius: 4 }}>
                          {l.confidence}
                        </span>
                      )}
                      <span style={{ fontSize: 10, color: '#4b5563' }}>
                        {l.created_at?.slice(0, 10)}
                      </span>
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
                    {l.scan_tier && (
                      <span style={{ fontSize: 10, color: '#60a5fa', background: 'rgba(96,165,250,0.1)', padding: '2px 7px', borderRadius: 4 }}>
                        {l.scan_tier.replace('_BUY', '')}
                      </span>
                    )}
                    {l.ats_signal && l.ats_signal !== 'ATS_NONE' && (
                      <span style={{ fontSize: 10, color: '#fbbf24', background: 'rgba(251,191,36,0.1)', padding: '2px 7px', borderRadius: 4 }}>
                        {l.ats_signal}
                      </span>
                    )}
                    {(l.tags || []).map(t => (
                      <span key={t} style={{ fontSize: 10, color: '#9ca3af', background: '#1f2937', padding: '2px 7px', borderRadius: 4 }}>{t}</span>
                    ))}
                  </div>
                  {l.what_worked && (
                    <div style={{ fontSize: 11, color: '#86efac', marginBottom: 4 }}>
                      <span style={{ color: '#4b5563' }}>✓ </span>{l.what_worked}
                    </div>
                  )}
                  {l.what_failed && (
                    <div style={{ fontSize: 11, color: '#fca5a5', marginBottom: 4 }}>
                      <span style={{ color: '#4b5563' }}>✗ </span>{l.what_failed}
                    </div>
                  )}
                  {l.lesson && (
                    <div style={{
                      marginTop: 8, padding: '8px 12px', background: 'rgba(96,165,250,0.06)',
                      border: '1px solid rgba(96,165,250,0.12)', borderRadius: 5,
                      fontSize: 11, color: '#93c5fd', fontStyle: 'italic', lineHeight: 1.7,
                    }}>
                      {l.lesson}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* ── Blacklist tab ──────────────────────────────────────────────── */}
        {tab === 'blacklist' && (
          <div>
            {blacklist.length === 0 ? (
              <div style={{ color: '#4b5563', fontSize: 13, padding: '40px 0', textAlign: 'center' }}>
                No blacklisted patterns. The AI will add patterns here when it identifies repeated failures.
              </div>
            ) : blacklist.map(b => (
              <div key={b.pattern_key} style={{
                background: b.active ? 'rgba(239,68,68,0.04)' : 'rgba(17,24,39,0.5)',
                border: `1px solid ${b.active ? 'rgba(239,68,68,0.25)' : '#1f2937'}`,
                borderRadius: 8, padding: '12px 16px', marginBottom: 10,
                opacity: b.active ? 1 : 0.5,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <span style={{ fontFamily: 'monospace', fontSize: 12, fontWeight: 700, color: b.active ? '#fca5a5' : '#6b7280' }}>
                    {fmtPatternKey(b.pattern_key)}
                  </span>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                    <span style={{ fontSize: 10, color: '#ef4444', background: 'rgba(239,68,68,0.1)', padding: '2px 8px', borderRadius: 4 }}>
                      {b.n_failures} failure{b.n_failures !== 1 ? 's' : ''}
                    </span>
                    <span style={{ fontSize: 10, color: b.active ? '#f87171' : '#4b5563' }}>
                      {b.active
                        ? (b.suspended_until ? `until ${b.suspended_until?.slice(0, 10)}` : 'permanent')
                        : 'expired'}
                    </span>
                  </div>
                </div>
                {b.reason && (
                  <p style={{ fontSize: 11, color: '#9ca3af', margin: 0, lineHeight: 1.6 }}>{b.reason}</p>
                )}
              </div>
            ))}
            <div style={{ fontSize: 11, color: '#374151', marginTop: 10 }}>
              The AI automatically manages this list based on pattern performance. Entries expire after their suspension period.
            </div>
          </div>
        )}

      </div>
    </PumpLayout>
  );
}
