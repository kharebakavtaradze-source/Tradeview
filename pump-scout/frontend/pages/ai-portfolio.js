import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import styles from '../styles/Journal.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function HealthBadge({ health }) {
  const colors = {
    STRONG: { bg: 'rgba(0,200,100,0.12)', color: '#00c864', border: 'rgba(0,200,100,0.3)' },
    NEUTRAL: { bg: 'rgba(255,200,0,0.1)', color: '#ffc800', border: 'rgba(255,200,0,0.3)' },
    WEAK: { bg: 'rgba(255,68,68,0.1)', color: '#ff4444', border: 'rgba(255,68,68,0.3)' },
  }[health] || { bg: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)', border: 'rgba(255,255,255,0.1)' };
  return (
    <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 3, background: colors.bg, color: colors.color, border: `1px solid ${colors.border}` }}>
      {health || '—'}
    </span>
  );
}

function PnlBadge({ pct }) {
  if (pct == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  return (
    <span style={{ fontWeight: 700, color: pct >= 0 ? 'var(--green)' : 'var(--red)' }}>
      {pct >= 0 ? '+' : ''}{pct.toFixed(1)}%
    </span>
  );
}

export default function AIPortfolio() {
  const [state, setState] = useState(null);
  const [positions, setPositions] = useState([]);
  const [history, setHistory] = useState({ positions: [], history: [] });
  const [report, setReport] = useState(null);
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [stateRes, posRes, histRes, repRes] = await Promise.all([
        fetch(`${API_URL}/api/ai-portfolio/state`),
        fetch(`${API_URL}/api/ai-portfolio/positions`),
        fetch(`${API_URL}/api/ai-portfolio/history`),
        fetch(`${API_URL}/api/ai-portfolio/report/latest`),
      ]);
      if (stateRes.ok) setState(await stateRes.json());
      if (posRes.ok) setPositions((await posRes.json()).positions || []);
      if (histRes.ok) setHistory(await histRes.json());
      if (repRes.ok) setReport(await repRes.json());
    } catch (e) {
      console.error('Portfolio load failed:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function runNow() {
    setRunning(true);
    await fetch(`${API_URL}/api/ai-portfolio/run-now`, { method: 'POST' });
    setTimeout(async () => { await load(); setRunning(false); }, 10000);
  }

  const closedPositions = (history.positions || []).filter(p => p.status === 'CLOSED').slice(0, 10);
  const portfolioHistory = history.history || [];

  const totalValue = state?.total_value || 1000;
  const totalPnl = state?.total_pnl_pct || 0;
  const cash = state?.cash || 0;
  const invested = state?.invested || 0;

  return (
    <>
      <Head>
        <title>AI Portfolio — Pump Scout</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
      <div className={styles.container}>
        {/* Nav */}
        <nav className={styles.nav}>
          <Link href="/" className={styles.backLink}>← Scanner</Link>
          <span className={styles.navTitle}>🤖 AI PORTFOLIO</span>
          <div className={styles.navActions}>
            <Link href="/journal" className={styles.btn}>📔 Journal</Link>
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={runNow} disabled={running}>
              {running ? '⏳ Running…' : '▶ Run Now'}
            </button>
          </div>
        </nav>

        {loading && <div className={styles.loading}><span className={styles.spinner} /> Loading portfolio…</div>}

        {/* Portfolio value card */}
        {state && (
          <div style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, padding: '16px 20px', marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>PORTFOLIO VALUE</div>
                <div style={{ fontSize: 28, fontWeight: 700 }}>${totalValue.toFixed(2)}</div>
              </div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>
                <PnlBadge pct={totalPnl} />
              </div>
              {report?.report && <HealthBadge health={report.report.portfolio_health} />}
            </div>
            <div style={{ display: 'flex', gap: 20, marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>
              <span>💵 Cash: <b style={{ color: 'var(--text-primary)' }}>${cash.toFixed(2)}</b></span>
              <span>📈 Invested: <b style={{ color: 'var(--text-primary)' }}>${invested.toFixed(2)}</b></span>
              <span>Started: <b>$1,000.00</b></span>
            </div>

            {/* Value history bar */}
            {portfolioHistory.length > 1 && (
              <div style={{ marginTop: 10, display: 'flex', gap: 2, alignItems: 'flex-end', height: 32 }}>
                {portfolioHistory.map((h, i) => {
                  const pct = (h.total_value - 1000) / 1000;
                  const height = Math.max(4, Math.abs(pct) * 200 + 4);
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
          <div style={{ background: 'rgba(100,200,255,0.04)', border: '1px solid rgba(100,200,255,0.12)', borderRadius: 6, padding: '12px 16px', marginBottom: 16, fontSize: 12 }}>
            <div style={{ fontWeight: 700, color: 'var(--cyan)', marginBottom: 6 }}>📋 Today's Report</div>
            <div style={{ lineHeight: 1.5 }}>{report.report.summary}</div>
            {report.report.best_position && (
              <div style={{ marginTop: 6, color: 'var(--green)' }}>🏆 {report.report.best_position}</div>
            )}
            {report.report.concern && report.report.concern !== 'null' && (
              <div style={{ marginTop: 4, color: '#ffa500' }}>⚠️ {report.report.concern}</div>
            )}
            {report.report.tomorrow_plan && (
              <div style={{ marginTop: 4, color: 'var(--text-muted)' }}>📋 Tomorrow: {report.report.tomorrow_plan}</div>
            )}
          </div>
        )}

        {/* Open positions */}
        <div style={{ marginBottom: 8, fontSize: 11, color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.05em' }}>
          OPEN POSITIONS ({positions.length})
        </div>
        {positions.length === 0 && !loading && (
          <div className={styles.empty} style={{ marginBottom: 16 }}>No open positions. Click "Run Now" to let AI make decisions.</div>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10, marginBottom: 20 }}>
          {positions.map(p => (
            <div key={p.id} style={{
              background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
              borderLeft: `3px solid ${(p.pnl_pct || 0) >= 0 ? 'var(--green)' : 'var(--red)'}`,
              borderRadius: 6, padding: '10px 12px',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontWeight: 700, fontSize: 14 }}>{p.symbol}</span>
                <PnlBadge pct={p.pnl_pct} />
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', display: 'flex', gap: 10, marginBottom: 6 }}>
                <span>Entry ${p.entry_price?.toFixed(2)}</span>
                <span>Invested ${p.invested_usd?.toFixed(0)}</span>
                <span>Day {p.days_held}</span>
              </div>
              <div style={{ fontSize: 10, color: 'var(--text-dim)', lineHeight: 1.4, fontStyle: 'italic' }}>
                {p.reason?.slice(0, 80)}{p.reason?.length > 80 ? '…' : ''}
              </div>
            </div>
          ))}
        </div>

        {/* Closed positions */}
        {closedPositions.length > 0 && (
          <>
            <div style={{ marginBottom: 8, fontSize: 11, color: 'var(--text-muted)', fontWeight: 700, letterSpacing: '0.05em' }}>
              CLOSED POSITIONS (last 10)
            </div>
            <div style={{ display: 'grid', gap: 6 }}>
              {closedPositions.map(p => (
                <div key={p.id} style={{
                  display: 'flex', alignItems: 'center', gap: 12, padding: '8px 12px',
                  background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.06)',
                  borderRadius: 4, fontSize: 11,
                }}>
                  <span style={{
                    fontSize: 10, fontWeight: 700, minWidth: 30,
                    color: (p.pnl_pct || 0) >= 0 ? 'var(--green)' : 'var(--red)',
                  }}>
                    {(p.pnl_pct || 0) >= 0 ? '✅' : '❌'}
                  </span>
                  <span style={{ fontWeight: 700, minWidth: 50 }}>{p.symbol}</span>
                  <PnlBadge pct={p.pnl_pct} />
                  <span style={{ color: 'var(--text-muted)' }}>{p.days_held}d</span>
                  <span style={{ color: 'var(--text-muted)', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {p.reason?.slice(0, 60)}
                  </span>
                </div>
              ))}
            </div>
          </>
        )}

        {/* Comparison with user journal */}
        <div style={{ marginTop: 20, padding: '10px 14px', background: 'rgba(255,255,255,0.03)', borderRadius: 6, fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 16 }}>
          <span>🤖 AI Portfolio: <b style={{ color: totalPnl >= 0 ? 'var(--green)' : 'var(--red)' }}>{totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(1)}%</b></span>
          <span style={{ opacity: 0.5 }}>Compare with your journal in Analytics tab</span>
        </div>
      </div>
    </>
  );
}
