import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import AppNav from '../components/AppNav';
import styles from '../styles/Journal.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function HealthBadge({ health }) {
  const cfg = {
    STRONG: { bg: 'rgba(0,200,100,0.12)', color: '#00c864', border: 'rgba(0,200,100,0.3)' },
    NEUTRAL: { bg: 'rgba(255,200,0,0.1)', color: '#ffc800', border: 'rgba(255,200,0,0.3)' },
    WEAK: { bg: 'rgba(255,68,68,0.1)', color: '#ff4444', border: 'rgba(255,68,68,0.3)' },
  }[health] || { bg: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)', border: 'rgba(255,255,255,0.1)' };
  return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 3, background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}` }}>
      {health || '—'}
    </span>
  );
}

function SourceBadge({ source, scanData }) {
  const label = source === 'new_pump' ? 'NP' : 'SCANNER';
  const npLabel = source === 'new_pump' ? (scanData?.tier || scanData?.new_pump_label || '') : '';
  const isNP = source === 'new_pump';
  return (
    <span title={isNP ? `New Pump — ${npLabel}` : 'Classic Scanner'} style={{
      fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3, letterSpacing: '0.05em',
      background: isNP ? 'rgba(124,90,245,0.2)' : 'rgba(0,212,245,0.1)',
      color: isNP ? 'var(--accent)' : 'var(--cyan)',
      border: `1px solid ${isNP ? 'rgba(124,90,245,0.4)' : 'rgba(0,212,245,0.2)'}`,
    }}>
      {isNP ? `⚡ NP${npLabel ? ` · ${npLabel}` : ''}` : '📡 SCAN'}
    </span>
  );
}

function TwoTargetDisplay({ pos }) {
  const { entry_price, target_price: tp1, target_price_2: tp2, sell_pct_at_target_1: sellPct, tp1_hit, stop_loss } = pos;
  if (!tp1) return null;
  const pct2 = sellPct ?? 50;
  return (
    <div style={{ fontSize: 9, display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 3 }}>
      {stop_loss && (
        <span style={{ color: 'var(--red)' }}>
          Stop <b>${stop_loss.toFixed(2)}</b>
        </span>
      )}
      <span style={{ color: tp1_hit ? 'var(--lime)' : 'rgba(0,200,100,0.7)' }}>
        {tp1_hit ? '✅' : '🎯'} TP1 <b>${tp1.toFixed(2)}</b>
        <span style={{ color: 'var(--text-muted)', marginLeft: 2 }}>({pct2}%)</span>
      </span>
      {tp2 && (
        <span style={{ color: 'rgba(0,212,245,0.9)' }}>
          🎯 TP2 <b>${tp2.toFixed(2)}</b>
          <span style={{ color: 'var(--text-muted)', marginLeft: 2 }}>({100 - pct2}%)</span>
        </span>
      )}
    </div>
  );
}

function PriorPills({ scanData }) {
  if (!scanData) return null;
  const pills = [];
  const via = scanData.np_setup_via || scanData.np_setup_via;
  const vol = scanData.vol_ratio || 0;
  const wyck = scanData.wyckoff || '';
  const cmf = scanData.cmf_pctl || 0;
  const isIso = scanData.np_is_isolated_trigger;
  const source = scanData.source || '';

  if (isIso) pills.push({ label: 'ISO SIGNAL', color: '#ff6644', bg: 'rgba(255,100,68,0.12)' });
  else if (via && via !== 'NONE' && source === 'new_pump') pills.push({ label: `SETUP:${via}`, color: 'rgba(0,200,100,0.9)', bg: 'rgba(0,200,100,0.1)' });
  if (vol >= 5) pills.push({ label: `VOL×${vol.toFixed(1)}`, color: '#ffa500', bg: 'rgba(255,165,0,0.12)' });
  if (wyck === 'ACCUMULATION' || wyck === 'BREAKOUT') pills.push({ label: wyck, color: 'var(--lime)', bg: 'rgba(0,200,100,0.08)' });
  if (cmf >= 80) pills.push({ label: 'CMF+', color: 'var(--cyan)', bg: 'rgba(0,212,245,0.08)' });

  if (pills.length === 0) return null;
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 4 }}>
      {pills.map((p, i) => (
        <span key={i} style={{ fontSize: 8, fontWeight: 700, padding: '1px 5px', borderRadius: 2, background: p.bg, color: p.color, letterSpacing: '0.04em' }}>
          {p.label}
        </span>
      ))}
    </div>
  );
}

function TickerMemoryMini({ symbol, closedPositions }) {
  const trades = closedPositions.filter(p => p.symbol === symbol);
  if (trades.length === 0) return null;
  const wins = trades.filter(t => (t.pnl_pct || 0) > 0).length;
  const avg = trades.reduce((s, t) => s + (t.pnl_pct || 0), 0) / trades.length;
  const last = trades[0];
  const lastColor = (last.pnl_pct || 0) >= 0 ? 'var(--lime)' : 'var(--red)';
  return (
    <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 4, display: 'flex', gap: 8 }}>
      <span>🧠 Memory:</span>
      <span><b style={{ color: wins > 0 ? 'var(--lime)' : 'var(--text-muted)' }}>{wins}W</b>/<b style={{ color: trades.length - wins > 0 ? 'var(--red)' : 'var(--text-muted)' }}>{trades.length - wins}L</b></span>
      <span>avg <b style={{ color: avg >= 0 ? 'var(--lime)' : 'var(--red)' }}>{avg >= 0 ? '+' : ''}{avg.toFixed(1)}%</b></span>
      <span>last <b style={{ color: lastColor }}>{(last.pnl_pct || 0) >= 0 ? '+' : ''}{(last.pnl_pct || 0).toFixed(1)}%</b></span>
    </div>
  );
}

function PnlBadge({ pct, size = 14 }) {
  if (pct == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const color = pct > 0 ? 'var(--lime)' : pct < 0 ? 'var(--red)' : 'var(--text-muted)';
  return (
    <span style={{ fontWeight: 700, fontSize: size, color }}>
      {pct > 0 ? '+' : ''}{pct.toFixed(2)}%
    </span>
  );
}

function RiskBadge({ pos }) {
  const pnl = pos.pnl_pct || 0;
  const stop = pos.stop_loss;
  const price = pos.current_price || pos.entry_price;
  if (stop && price) {
    const distToStop = ((price - stop) / stop * 100);
    if (distToStop < 2) return <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 2, background: 'rgba(255,68,68,0.2)', color: 'var(--red)' }}>⚠️ NEAR STOP</span>;
  }
  if (pnl >= 10) return <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 2, background: 'rgba(0,200,100,0.15)', color: 'var(--lime)' }}>🎯 NEAR TARGET</span>;
  if (pnl <= -5) return <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 2, background: 'rgba(255,68,68,0.12)', color: '#ff6666' }}>📉 LOSING</span>;
  return null;
}

function PositionProgressBar({ pos }) {
  const stop = pos.stop_loss;
  const target = pos.target_price;
  const price = pos.current_price || pos.entry_price;
  if (!stop || !target || !price) return null;
  const range = target - stop;
  if (range <= 0) return null;
  const progress = Math.max(0, Math.min(100, (price - stop) / range * 100));
  const pnl = pos.pnl_pct || 0;
  return (
    <div style={{ margin: '6px 0 4px' }}>
      <div style={{ height: 4, background: 'rgba(255,255,255,0.07)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${progress}%`, borderRadius: 2,
          background: pnl >= 0 ? 'rgba(0,200,100,0.6)' : 'rgba(255,68,68,0.6)',
          transition: 'width 0.3s',
        }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, marginTop: 2, color: 'var(--text-muted)' }}>
        <span style={{ color: 'var(--red)' }}>Stop ${stop.toFixed(2)}</span>
        <span style={{ color: pnl >= 0 ? 'var(--lime)' : 'var(--red)', fontWeight: 700 }}>
          {price.toFixed(2)} ({pnl >= 0 ? '+' : ''}{pnl.toFixed(1)}%)
        </span>
        <span style={{ color: 'var(--lime)' }}>Target ${target.toFixed(2)}</span>
      </div>
    </div>
  );
}

export default function AIPortfolio() {
  const [state, setState] = useState(null);
  const [positions, setPositions] = useState([]);
  const [history, setHistory] = useState({ positions: [], history: [] });
  const [report, setReport] = useState(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [journalStats, setJournalStats] = useState(null);
  const [deepAnalytics, setDeepAnalytics] = useState(null);

  const load = useCallback(async () => {
    try {
      const [stateRes, posRes, histRes, repRes, jStatsRes, deepRes] = await Promise.all([
        fetch(`${API_URL}/api/ai-portfolio/state`),
        fetch(`${API_URL}/api/ai-portfolio/positions`),
        fetch(`${API_URL}/api/ai-portfolio/history`),
        fetch(`${API_URL}/api/ai-portfolio/report/latest`),
        fetch(`${API_URL}/api/journal/stats`),
        fetch(`${API_URL}/api/journal/deep-analytics`),
      ]);
      if (stateRes.ok) setState(await stateRes.json());
      if (posRes.ok) setPositions((await posRes.json()).positions || []);
      if (histRes.ok) setHistory(await histRes.json());
      if (repRes.ok) setReport(await repRes.json());
      if (jStatsRes.ok) setJournalStats(await jStatsRes.json());
      if (deepRes.ok) setDeepAnalytics(await deepRes.json());
    } catch (e) {
      console.error('Portfolio load failed:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Auto-refresh every 60s during market hours
  useEffect(() => {
    const interval = setInterval(load, 60_000);
    return () => clearInterval(interval);
  }, [load]);

  async function runNow() {
    setRunning(true);
    await fetch(`${API_URL}/api/ai-portfolio/run-now`, { method: 'POST' });
    setTimeout(async () => { await load(); setRunning(false); }, 12000);
  }

  const [refreshing, setRefreshing] = useState(false);
  async function refreshPrices() {
    setRefreshing(true);
    try {
      await fetch(`${API_URL}/api/ai-portfolio/refresh-prices`, { method: 'POST' });
      await load();
    } finally {
      setRefreshing(false);
    }
  }

  const allPositions = history.positions || [];
  const closedPositions = allPositions.filter(p => p.status === 'CLOSED').slice(0, 15);
  const portfolioHistory = history.history || [];

  const totalValue = state?.total_value || 2000;
  const totalPnl = state?.total_pnl_pct || 0;
  const cash = state?.cash || 0;
  const invested = state?.invested || 0;

  // AI portfolio closed trade stats
  const closedPnls = closedPositions.map(p => p.pnl_pct || 0);
  const aiWins = closedPositions.filter(p => (p.pnl_pct || 0) > 0);
  const aiLosses = closedPositions.filter(p => (p.pnl_pct || 0) <= 0);
  const aiWinRate = closedPositions.length > 0 ? Math.round(aiWins.length / closedPositions.length * 100) : null;
  const aiAvgPnl = closedPnls.length > 0 ? (closedPnls.reduce((a, b) => a + b, 0) / closedPnls.length).toFixed(1) : null;

  // Risk summary
  const nearStopCount = positions.filter(p => {
    const stop = p.stop_loss; const price = p.current_price || p.entry_price;
    return stop && price && ((price - stop) / stop * 100) < 2;
  }).length;

  return (
    <>
      <Head>
        <title>AI Portfolio — Pump Scout</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
      <div className={styles.container}>
        <AppNav />

        {/* Page header + action buttons */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px var(--page-px, 28px) 10px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
          <div style={{ fontSize: 13, fontWeight: 700, letterSpacing: '0.06em', color: 'var(--text)', flex: 1 }}>
            AI PORTFOLIO
          </div>
          <button
            onClick={refreshPrices}
            disabled={refreshing}
            style={{
              fontSize: 11, fontWeight: 600, padding: '5px 12px', borderRadius: 5,
              border: '1px solid var(--cyan-border, rgba(0,212,245,0.3))',
              background: 'var(--cyan-dim, rgba(0,212,245,0.08))',
              color: 'var(--cyan)', cursor: refreshing ? 'not-allowed' : 'pointer',
              opacity: refreshing ? 0.5 : 1, transition: 'opacity 0.15s',
            }}
          >
            {refreshing ? '⟳ Refreshing…' : '⟳ Refresh Prices'}
          </button>
          <button
            onClick={runNow}
            disabled={running}
            style={{
              fontSize: 11, fontWeight: 600, padding: '5px 12px', borderRadius: 5,
              border: '1px solid var(--accent-border, rgba(124,90,245,0.35))',
              background: 'var(--accent-dim, rgba(124,90,245,0.1))',
              color: 'var(--accent)', cursor: running ? 'not-allowed' : 'pointer',
              opacity: running ? 0.5 : 1, transition: 'opacity 0.15s',
            }}
          >
            {running ? '⏳ Running…' : '▶ Run AI Now'}
          </button>
        </div>


        {/* Portfolio value card */}
        {state && (
          <div style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, padding: '16px 20px', marginBottom: 12 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>PORTFOLIO VALUE</div>
                <div style={{ fontSize: 28, fontWeight: 700 }}>${totalValue.toFixed(2)}</div>
              </div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>
                <PnlBadge pct={totalPnl} size={20} />
              </div>
              {report?.report && <HealthBadge health={report.report.portfolio_health} />}
              {nearStopCount > 0 && (
                <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 3, background: 'rgba(255,68,68,0.15)', color: 'var(--red)', fontWeight: 700 }}>
                  ⚠️ {nearStopCount} near stop
                </span>
              )}
            </div>
            <div style={{ display: 'flex', gap: 20, marginTop: 8, fontSize: 11, color: 'var(--text-muted)', flexWrap: 'wrap' }}>
              <span>💵 Cash: <b style={{ color: 'var(--text-primary)' }}>${cash.toFixed(2)}</b></span>
              <span>📈 Invested: <b style={{ color: 'var(--text-primary)' }}>${invested.toFixed(2)}</b></span>
              <span>Started: <b>$2,000.00</b></span>
              <span>Positions: <b>{positions.length}/5</b></span>
              {aiWinRate !== null && <span>AI WR: <b style={{ color: aiWinRate >= 50 ? 'var(--lime)' : 'var(--red)' }}>{aiWinRate}%</b> ({aiWins.length}W/{aiLosses.length}L)</span>}
              {aiAvgPnl !== null && <span>Avg trade: <b style={{ color: parseFloat(aiAvgPnl) >= 0 ? 'var(--lime)' : 'var(--red)' }}>{parseFloat(aiAvgPnl) >= 0 ? '+' : ''}{aiAvgPnl}%</b></span>}
            </div>

            {/* Value history sparkline */}
            {portfolioHistory.length > 1 && (
              <div style={{ marginTop: 10, display: 'flex', gap: 2, alignItems: 'flex-end', height: 32 }}>
                {portfolioHistory.map((h, i) => {
                  const pct = (h.total_value - 2000) / 2000;
                  const height = Math.max(4, Math.abs(pct) * 300 + 4);
                  return (
                    <div key={i} title={`${h.date}: $${h.total_value.toFixed(0)} (${h.total_pnl_pct >= 0 ? '+' : ''}${h.total_pnl_pct.toFixed(1)}%)`}
                      style={{
                        flex: 1, height, borderRadius: 2, alignSelf: 'flex-end',
                        background: pct >= 0 ? 'rgba(0,200,100,0.5)' : 'rgba(255,68,68,0.5)',
                        minWidth: 6,
                      }} />
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Daily report */}
        {report?.report && (
          <div style={{ background: 'rgba(100,200,255,0.04)', border: '1px solid rgba(100,200,255,0.12)', borderRadius: 6, padding: '12px 16px', marginBottom: 12, fontSize: 12 }}>
            <div style={{ fontWeight: 700, color: 'var(--cyan)', marginBottom: 6 }}>📋 Today's Report</div>
            <div style={{ lineHeight: 1.6 }}>{report.report.summary}</div>
            {report.report.best_position && report.report.best_position !== 'null' && (
              <div style={{ marginTop: 6, color: 'var(--lime)' }}>🏆 {report.report.best_position}</div>
            )}
            {report.report.concern && report.report.concern !== 'null' && (
              <div style={{ marginTop: 4, color: '#ffa500' }}>⚠️ {report.report.concern}</div>
            )}
            {report.report.tomorrow_plan && (
              <div style={{ marginTop: 4, color: 'var(--text-muted)' }}>📋 Tomorrow: {report.report.tomorrow_plan}</div>
            )}
          </div>
        )}

        {/* AI decision reasoning */}
        {state?.decisions && (state.decisions.portfolio_note || state.decisions.risk_assessment) && (
          <div style={{ background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 6, padding: '10px 14px', marginBottom: 12, fontSize: 11, lineHeight: 1.6 }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 5 }}>🤖 LAST AI DECISION</div>
            {state.decisions.risk_assessment && (
              <div style={{ color: '#ffa500', marginBottom: 4 }}>⚖️ {state.decisions.risk_assessment}</div>
            )}
            {state.decisions.portfolio_note && (
              <div style={{ color: 'rgba(255,255,255,0.75)' }}>{state.decisions.portfolio_note}</div>
            )}
            {state.decisions.no_trade_reason && (
              <div style={{ marginTop: 4, fontSize: 10, color: 'var(--text-muted)' }}>
                Причина: {state.decisions.no_trade_reason}
              </div>
            )}
          </div>
        )}

        {/* Open positions */}
        <div style={{ marginBottom: 8, fontSize: 11, color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.05em' }}>
          OPEN POSITIONS ({positions.length}/5)
        </div>
        {positions.length === 0 && !loading && (
          <div className={styles.empty} style={{ marginBottom: 16 }}>
            Нет открытых позиций. Нажмите "Run Now" для запуска AI-решений.
          </div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 10, marginBottom: 20 }}>
          {positions.map(p => {
            const pnl = p.pnl_pct || 0;
            const isWinning = pnl > 0;
            const isLosing = pnl < 0;
            const pnlColor = isWinning ? 'var(--lime)' : isLosing ? 'var(--red)' : 'var(--text-muted)';
            const borderColor = pnl >= 3 ? 'var(--lime)' : pnl <= -2 ? 'var(--red)' : isWinning ? 'rgba(40,217,113,0.4)' : isLosing ? 'rgba(240,62,92,0.4)' : 'var(--border2)';
            const bgColor = pnl >= 3 ? 'rgba(40,217,113,0.04)' : pnl <= -2 ? 'rgba(240,62,92,0.04)' : 'var(--surface)';
            return (
              <div key={p.id} style={{
                background: bgColor,
                border: `1px solid var(--border)`,
                borderLeft: `3px solid ${borderColor}`,
                borderRadius: 6, padding: '10px 12px',
              }}>
                {/* Header row */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 700, fontSize: 15 }}>{p.symbol}</span>
                    <SourceBadge source={p.source} scanData={p.scan_data} />
                    {p.tp1_hit && (
                      <span style={{ fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 2, background: 'rgba(0,200,100,0.15)', color: 'var(--lime)' }}>✅ TP1 HIT</span>
                    )}
                    {pnl !== 0 && (
                      <span style={{
                        fontSize: 9, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                        background: isWinning ? 'rgba(40,217,113,0.15)' : 'rgba(240,62,92,0.15)',
                        color: pnlColor, letterSpacing: '0.05em',
                      }}>
                        {isWinning ? '▲' : '▼'} {Math.abs(pnl).toFixed(1)}%
                      </span>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                    <RiskBadge pos={p} />
                    <PnlBadge pct={pnl} size={14} />
                  </div>
                </div>

                {/* Price row */}
                <div style={{ fontSize: 10, color: 'var(--text-muted)', display: 'flex', gap: 10, marginBottom: 2, flexWrap: 'wrap' }}>
                  <span>Entry <b style={{ color: 'var(--text-primary)' }}>${p.entry_price?.toFixed(2)}</b></span>
                  <span>Now <b style={{ color: pnl >= 0 ? 'var(--lime)' : 'var(--red)' }}>${(p.current_price || p.entry_price)?.toFixed(2)}</b></span>
                  <span>Size <b>${p.invested_usd?.toFixed(0)}</b></span>
                  <span>Day <b>{p.days_held}</b></span>
                </div>

                {/* TP1 / TP2 / Stop row */}
                <TwoTargetDisplay pos={p} />
                {/* Price freshness */}
                {(() => {
                  if (!p.price_updated_at) return (
                    <div style={{ fontSize: 9, color: '#ff8800', marginBottom: 2 }}>
                      ⚠️ Price not yet updated — click ⟳ Refresh Prices
                    </div>
                  );
                  const mins = Math.round((Date.now() - new Date(p.price_updated_at + 'Z').getTime()) / 60000);
                  const color = mins > 60 ? '#ff8800' : mins > 15 ? '#ffd600' : '#555';
                  const label = mins < 1 ? 'just now' : mins < 60 ? `${mins}m ago` : `${Math.floor(mins/60)}h ${mins%60}m ago`;
                  return (
                    <div style={{ fontSize: 9, color, marginBottom: 2 }}>
                      Price as of: {label}
                    </div>
                  );
                })()}

                {/* Peak/trough */}
                {(p.max_gain_pct !== 0 || p.max_loss_pct !== 0) && (
                  <div style={{ fontSize: 9, color: 'var(--text-muted)', display: 'flex', gap: 8, marginBottom: 2 }}>
                    <span>Peak: <b style={{ color: 'var(--lime)' }}>{p.max_gain_pct >= 0 ? '+' : ''}{(p.max_gain_pct || 0).toFixed(1)}%</b></span>
                    <span>Low: <b style={{ color: 'var(--red)' }}>{(p.max_loss_pct || 0).toFixed(1)}%</b></span>
                  </div>
                )}

                {/* Progress bar: stop → current → target */}
                <PositionProgressBar pos={p} />

                {/* Exit reason badge if any */}
                {p.exit_reason && (
                  <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 4 }}>
                    Exit: {p.exit_reason}
                  </div>
                )}

                {/* Research prior pills */}
                <PriorPills scanData={p.scan_data} />

                {/* Ticker memory */}
                <TickerMemoryMini symbol={p.symbol} closedPositions={closedPositions} />

                {/* AI reasoning */}
                {p.reason && (
                  <div style={{ fontSize: 10, color: 'var(--text-dim)', lineHeight: 1.5, fontStyle: 'italic', marginTop: 4, paddingTop: 4, borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                    {p.reason}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Closed positions */}
        {closedPositions.length > 0 && (
          <>
            <div style={{ marginBottom: 8, fontSize: 11, color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.05em' }}>
              CLOSED POSITIONS ({closedPositions.length})
            </div>
            <div style={{ display: 'grid', gap: 4, marginBottom: 20 }}>
              {closedPositions.map(p => (
                <div key={p.id} style={{
                  display: 'flex', alignItems: 'center', gap: 10, padding: '7px 10px',
                  background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)',
                  borderLeft: `3px solid ${(p.pnl_pct || 0) >= 0 ? 'var(--lime)' : 'var(--red)'}`,
                  borderRadius: 4, fontSize: 11,
                }}>
                  <span style={{ fontWeight: 700, minWidth: 50 }}>{p.symbol}</span>
                  <SourceBadge source={p.source} scanData={p.scan_data} />
                  <PnlBadge pct={p.pnl_pct} size={11} />
                  <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{p.days_held}d</span>
                  {p.exit_reason && (
                    <span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 2, background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)' }}>
                      {p.exit_reason}
                    </span>
                  )}
                  <span style={{ color: 'var(--text-muted)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 10 }}>
                    {p.reason}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        {/* Research Signal Bias — global priors reminder */}
        <div style={{ background: 'rgba(124,90,245,0.04)', border: '1px solid rgba(124,90,245,0.15)', borderRadius: 6, padding: '10px 14px', marginBottom: 12 }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: 'rgba(124,90,245,0.8)', marginBottom: 6, letterSpacing: '0.06em' }}>🔬 RESEARCH SIGNAL BIAS (Replay + Raw Pattern)</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {[
              { label: 'Early Setup', note: '+ positive', color: 'var(--lime)' },
              { label: 'Isolated Signal', note: '− penalty', color: 'var(--red)' },
              { label: 'Extreme Anomaly', note: '− caution', color: '#ffa500' },
              { label: 'Bull Stack', note: '+ positive', color: 'var(--lime)' },
              { label: 'Late Confirm', note: '− caution', color: '#ffa500' },
              { label: 'Strong Label', note: '+ bias', color: 'var(--cyan)' },
              { label: 'Vol Gate', note: 'don\'t overfilter', color: 'var(--text-muted)' },
            ].map((b, i) => (
              <span key={i} style={{
                fontSize: 9, fontWeight: 600, padding: '2px 7px', borderRadius: 3,
                background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
                color: 'var(--text-muted)',
              }}>
                <span style={{ color: b.color }}>{b.label}</span>
                <span style={{ color: 'rgba(255,255,255,0.3)', margin: '0 3px' }}>·</span>
                {b.note}
              </span>
            ))}
          </div>
        </div>

        {/* Comparison: Journal vs AI vs SPY */}
        <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: '14px 16px' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em', marginBottom: 12 }}>📊 YOUR JOURNAL vs AI PORTFOLIO vs SPY</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 10 }}>
            {/* Journal */}
            <div style={{ background: 'rgba(0,200,100,0.06)', border: '1px solid rgba(0,200,100,0.15)', borderRadius: 6, padding: '10px 12px' }}>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>📔 YOUR JOURNAL</div>
              {journalStats ? (
                <>
                  <div style={{ fontSize: 18, fontWeight: 700, color: (journalStats.total_pnl_pct || 0) >= 0 ? 'var(--lime)' : 'var(--red)' }}>
                    {(journalStats.total_pnl_pct || 0) >= 0 ? '+' : ''}{(journalStats.total_pnl_pct || 0).toFixed(1)}%
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
                    {journalStats.win_rate_pct}% WR · {journalStats.total_trades} trades
                  </div>
                  {deepAnalytics?.alpha?.avg_alpha_vs_spy != null && (
                    <div style={{ fontSize: 10, marginTop: 2 }}>
                      α SPY: <b style={{ color: deepAnalytics.alpha.avg_alpha_vs_spy >= 0 ? 'var(--cyan)' : 'var(--red)' }}>
                        {deepAnalytics.alpha.avg_alpha_vs_spy >= 0 ? '+' : ''}{deepAnalytics.alpha.avg_alpha_vs_spy.toFixed(1)}%
                      </b>
                    </div>
                  )}
                </>
              ) : <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>Нет закрытых сделок</div>}
            </div>

            {/* AI Portfolio */}
            <div style={{ background: 'rgba(100,200,255,0.06)', border: '1px solid rgba(100,200,255,0.15)', borderRadius: 6, padding: '10px 12px' }}>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>🤖 AI PORTFOLIO</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: totalPnl >= 0 ? 'var(--cyan)' : 'var(--red)' }}>
                {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(1)}%
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>${totalValue.toFixed(0)} value</div>
              {aiWinRate !== null && (
                <div style={{ fontSize: 10, marginTop: 2 }}>
                  WR: <b style={{ color: aiWinRate >= 50 ? 'var(--lime)' : 'var(--red)' }}>{aiWinRate}%</b> · {closedPositions.length} closed
                </div>
              )}
            </div>

            {/* SPY */}
            <div style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, padding: '10px 12px' }}>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 4 }}>📈 SPY (BASELINE)</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 8, lineHeight: 1.5 }}>
                Альфа vs SPY показывается в карточках журнала и во вкладке Analytics.
              </div>
            </div>
          </div>

          {journalStats && journalStats.closed_trades > 0 && (
            <div style={{ marginTop: 10, fontSize: 10, color: 'var(--text-muted)', borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 8 }}>
              {(journalStats.total_pnl_pct || 0) > totalPnl
                ? <span>🏆 <b style={{ color: 'var(--lime)' }}>Ваш журнал</b> опережает AI портфель на <b>{((journalStats.total_pnl_pct || 0) - totalPnl).toFixed(1)}%</b></span>
                : (journalStats.total_pnl_pct || 0) < totalPnl
                ? <span>🤖 <b style={{ color: 'var(--cyan)' }}>AI портфель</b> опережает ваш журнал на <b>{(totalPnl - (journalStats.total_pnl_pct || 0)).toFixed(1)}%</b></span>
                : <span>Ничья между журналом и AI портфелем.</span>
              }
            </div>
          )}
        </div>
      </div>
    </>
  );
}
