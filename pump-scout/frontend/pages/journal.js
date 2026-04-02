import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import JournalModal from '../components/JournalModal';
import styles from '../styles/Journal.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const FILTER_TABS = ['ALL', 'OPEN', 'CLOSED', 'WIN', 'LOSS', 'CALENDAR', 'ANALYTICS'];

const TIER_COLORS = {
  FIRE: '#ffd700', ARM: '#00e5ff', BASE: '#00c853', STEALTH: '#cc44ff',
  SYMPATHY: '#00e5ff', WATCH: '#ff8800',
};

function CalendarView({ entries, calendarYear, calendarMonth, onPrevMonth, onNextMonth }) {
  const year = calendarYear;
  const month = calendarMonth; // 0-indexed

  const monthNames = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const dayNames = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

  // Build a map: date string -> array of entries
  const dateMap = {};
  for (const e of entries) {
    const entryDate = e.entry_date ? e.entry_date.slice(0, 10) : null;
    const exitDate = e.exit_date ? e.exit_date.slice(0, 10) : null;
    if (entryDate) {
      if (!dateMap[entryDate]) dateMap[entryDate] = [];
      dateMap[entryDate].push({ ...e, _dateRole: 'entry' });
    }
    if (exitDate && exitDate !== entryDate) {
      if (!dateMap[exitDate]) dateMap[exitDate] = [];
      dateMap[exitDate].push({ ...e, _dateRole: 'exit' });
    }
  }

  const firstDay = new Date(year, month, 1);
  // Monday=0 week, getDay() is Sun=0, so adjust:
  let startDow = firstDay.getDay(); // 0=Sun
  startDow = startDow === 0 ? 6 : startDow - 1; // convert to Mon=0
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const cells = [];
  for (let i = 0; i < startDow; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);

  const [selectedDate, setSelectedDate] = useState(null);
  const pad = n => String(n).padStart(2, '0');

  const selectedKey = selectedDate ? `${year}-${pad(month + 1)}-${pad(selectedDate)}` : null;
  const selectedEntries = selectedKey ? (dateMap[selectedKey] || []) : [];

  return (
    <div style={{ padding: '16px 0' }}>
      {/* Month navigation */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <button onClick={onPrevMonth} style={{ background: 'rgba(255,255,255,0.08)', border: 'none', color: 'var(--text)', padding: '4px 12px', borderRadius: 4, cursor: 'pointer', fontSize: 16 }}>‹</button>
        <span style={{ fontWeight: 700, fontSize: 16, color: 'var(--text)', minWidth: 120, textAlign: 'center' }}>
          {monthNames[month]} {year}
        </span>
        <button onClick={onNextMonth} style={{ background: 'rgba(255,255,255,0.08)', border: 'none', color: 'var(--text)', padding: '4px 12px', borderRadius: 4, cursor: 'pointer', fontSize: 16 }}>›</button>
      </div>

      {/* Day headers */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 2, marginBottom: 4 }}>
        {dayNames.map(d => (
          <div key={d} style={{ textAlign: 'center', fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, padding: '2px 0' }}>{d}</div>
        ))}
      </div>

      {/* Calendar grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: 2 }}>
        {cells.map((day, i) => {
          if (!day) return <div key={`empty-${i}`} />;
          const key = `${year}-${pad(month + 1)}-${pad(day)}`;
          const dayEntries = dateMap[key] || [];
          const hasEntry = dayEntries.some(e => e._dateRole === 'entry');
          const hasWin = dayEntries.some(e => e._dateRole === 'exit' && e.outcome === 'win');
          const hasLoss = dayEntries.some(e => e._dateRole === 'exit' && e.outcome === 'loss');
          const isSelected = selectedDate === day;
          return (
            <div key={key}
              onClick={() => setSelectedDate(isSelected ? null : day)}
              style={{
                minHeight: 44,
                background: isSelected ? 'rgba(0,229,255,0.15)' : 'rgba(255,255,255,0.03)',
                border: isSelected ? '1px solid var(--cyan)' : '1px solid rgba(255,255,255,0.05)',
                borderRadius: 4,
                padding: '4px 6px',
                cursor: dayEntries.length ? 'pointer' : 'default',
                position: 'relative',
              }}
            >
              <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600 }}>{day}</div>
              {/* Dots */}
              <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', marginTop: 3 }}>
                {hasEntry && <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#4488ff', display: 'inline-block' }} title="Opened" />}
                {hasWin && <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--green)', display: 'inline-block' }} title="Win closed" />}
                {hasLoss && <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--red)', display: 'inline-block' }} title="Loss closed" />}
              </div>
            </div>
          );
        })}
      </div>

      {/* Selected day detail */}
      {selectedDate && (
        <div style={{ marginTop: 16, padding: 12, background: 'rgba(255,255,255,0.03)', borderRadius: 6, border: '1px solid rgba(255,255,255,0.08)' }}>
          <div style={{ fontWeight: 700, marginBottom: 10, color: 'var(--text)', fontSize: 13 }}>
            {monthNames[month]} {selectedDate}, {year}
          </div>
          {selectedEntries.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Нет сделок за этот день</div>
          ) : selectedEntries.map((e, i) => {
            const pnl = e.final_pnl_pct ?? e.gain_pct;
            return (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 3, background: e._dateRole === 'entry' ? 'rgba(68,136,255,0.2)' : (e.outcome === 'win' ? 'rgba(0,200,100,0.2)' : 'rgba(255,68,68,0.2)'), color: e._dateRole === 'entry' ? '#4488ff' : (e.outcome === 'win' ? 'var(--green)' : 'var(--red)') }}>
                  {e._dateRole === 'entry' ? 'OPEN' : (e.outcome === 'win' ? 'WIN' : 'LOSS')}
                </span>
                <span style={{ fontWeight: 700, color: 'var(--text)', fontSize: 13 }}>{e.symbol}</span>
                {e.tier && <span style={{ fontSize: 10, color: TIER_COLORS[e.tier] || 'var(--cyan)' }}>{e.tier}</span>}
                {pnl != null && e._dateRole === 'exit' && (
                  <span style={{ marginLeft: 'auto', fontWeight: 700, color: pnl >= 0 ? 'var(--green)' : 'var(--red)', fontSize: 13 }}>
                    {pnl >= 0 ? '+' : ''}{pnl.toFixed(2)}%
                  </span>
                )}
                {e._dateRole === 'entry' && (
                  <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: 11 }}>
                    ${e.entry_price?.toFixed(2)}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, marginTop: 12, fontSize: 10, color: 'var(--text-muted)' }}>
        <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: '#4488ff', marginRight: 4 }} />Открыта</span>
        <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: 'var(--green)', marginRight: 4 }} />Закрыта WIN</span>
        <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: 'var(--red)', marginRight: 4 }} />Закрыта LOSS</span>
      </div>
    </div>
  );
}

function ProgressBar({ current, entry, target, stop }) {
  if (!target || !entry) return null;
  const effectiveStop = stop || entry * 0.9;
  const range = target - effectiveStop;
  const effectiveCurrent = current || entry;
  const progress = Math.max(0, Math.min(100, (effectiveCurrent - effectiveStop) / range * 100));
  const hasCurrent = current != null && current > 0;
  const pct = hasCurrent ? ((current - entry) / entry * 100) : null;
  const stopDist = ((entry - effectiveStop) / entry * 100);
  const targetDist = ((target - entry) / entry * 100);
  return (
    <div style={{ margin: '6px 0' }}>
      <div style={{ height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${progress}%`, borderRadius: 2,
          background: pct == null ? 'rgba(100,100,100,0.4)' : pct >= 0 ? 'rgba(0,200,100,0.6)' : 'rgba(255,68,68,0.6)',
          transition: 'width 0.3s',
        }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, marginTop: 2, color: 'var(--text-muted)' }}>
        <span style={{ color: 'var(--red)' }}>Stop -{stopDist.toFixed(1)}%</span>
        <span style={{ color: pct != null ? (pct >= 0 ? 'var(--green)' : 'var(--red)') : 'var(--text-muted)', fontWeight: 700 }}>
          {pct != null ? `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%` : '─'}
        </span>
        <span style={{ color: 'var(--green)' }}>Target +{targetDist.toFixed(1)}%</span>
      </div>
    </div>
  );
}

function SignalRow({ e }) {
  const parts = [];
  if (e.entry_wyckoff) parts.push(e.entry_wyckoff);
  if (e.entry_cmf_pctl != null) parts.push(`CMF ${Math.round(e.entry_cmf_pctl)}%`);
  if (e.entry_vol_ratio) parts.push(`Vol ${parseFloat(e.entry_vol_ratio).toFixed(1)}x`);
  if (e.entry_hype > 0) parts.push(`Hype ${e.entry_hype}`);
  if (!parts.length) return null;
  return (
    <div style={{ fontSize: 9, color: 'var(--text-muted)', display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 3 }}>
      {parts.map((p, i) => <span key={i} style={{ background: 'rgba(255,255,255,0.06)', padding: '1px 5px', borderRadius: 2 }}>{p}</span>)}
    </div>
  );
}

function AIBox({ analysis }) {
  const [expanded, setExpanded] = useState(false);
  if (!analysis) return null;
  let parsed = null;
  try { parsed = JSON.parse(analysis); } catch { return null; }
  if (!parsed) return null;

  const timingColor = parsed.exit_timing === 'OPTIMAL' ? 'var(--green)'
    : parsed.exit_timing === 'TOO_EARLY' ? '#ffa500'
    : parsed.exit_timing === 'TOO_LATE' ? 'var(--red)'
    : 'var(--text-muted)';

  return (
    <div style={{ marginTop: 6, fontSize: 10, background: 'rgba(100,200,255,0.05)', borderRadius: 4, padding: '6px 8px', border: '1px solid rgba(100,200,255,0.12)' }}>
      <div style={{ fontWeight: 700, color: 'var(--cyan)', marginBottom: 3 }}>
        🤖 AI Analysis
        <button onClick={() => setExpanded(!expanded)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 9, color: 'var(--text-muted)', marginLeft: 6 }}>
          {expanded ? '▲ collapse' : '▼ expand'}
        </button>
      </div>
      {parsed.what_worked && <div>✅ {parsed.what_worked}</div>}
      {parsed.key_lesson && <div style={{ marginTop: 3, color: 'var(--gold)' }}>💡 {parsed.key_lesson}</div>}
      {parsed.exit_timing && (
        <div style={{ marginTop: 3 }}>
          <span style={{ color: 'var(--text-muted)' }}>Exit timing: </span>
          <span style={{ color: timingColor, fontWeight: 700 }}>{parsed.exit_timing}</span>
        </div>
      )}
      {parsed.alpha_comment && <div style={{ marginTop: 3, color: 'var(--cyan)', opacity: 0.8 }}>α {parsed.alpha_comment}</div>}
      {expanded && (
        <>
          {parsed.what_failed && <div style={{ marginTop: 3, color: 'var(--red)' }}>❌ {parsed.what_failed}</div>}
          {parsed.suggestion && <div style={{ marginTop: 3, color: 'var(--text-muted)' }}>→ {parsed.suggestion}</div>}
        </>
      )}
    </div>
  );
}

function isMarketHours() {
  const now = new Date();
  const day = now.getDay(); // 0=Sun, 6=Sat
  if (day === 0 || day === 6) return false;
  // Convert to ET (UTC-4 EDT / UTC-5 EST) — approximate with UTC-4 (handles EDT)
  const etHour = (now.getUTCHours() - 4 + 24) % 24;
  const etMin = now.getUTCMinutes();
  const etTotal = etHour * 60 + etMin;
  return etTotal >= 9 * 60 + 30 && etTotal < 16 * 60; // 9:30–16:00 ET
}

export default function Journal() {
  const [entries, setEntries] = useState([]);
  const [stats, setStats] = useState(null);
  const [filter, setFilter] = useState('ALL');
  const [showAdd, setShowAdd] = useState(false);
  const [editEntry, setEditEntry] = useState(null);
  const [insights, setInsights] = useState(null);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [deepAnalytics, setDeepAnalytics] = useState(null);
  const [deepLoading, setDeepLoading] = useState(false);
  const [livePrices, setLivePrices] = useState({});
  const now = new Date();
  const [calendarYear, setCalendarYear] = useState(now.getFullYear());
  const [calendarMonth, setCalendarMonth] = useState(now.getMonth());

  function prevMonth() {
    if (calendarMonth === 0) { setCalendarYear(y => y - 1); setCalendarMonth(11); }
    else setCalendarMonth(m => m - 1);
  }
  function nextMonth() {
    if (calendarMonth === 11) { setCalendarYear(y => y + 1); setCalendarMonth(0); }
    else setCalendarMonth(m => m + 1);
  }

  const loadData = useCallback(async () => {
    try {
      const [jRes, sRes] = await Promise.all([
        fetch(`${API_URL}/api/journal`),
        fetch(`${API_URL}/api/journal/stats`),
      ]);
      if (jRes.ok) setEntries((await jRes.json()).entries || []);
      if (sRes.ok) setStats(await sRes.json());
    } catch (e) {
      console.error('Failed to load journal:', e);
    }
  }, []);

  const loadLivePrices = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/journal/live-prices`);
      if (res.ok) setLivePrices(await res.json());
    } catch { }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // Load live prices on mount always; poll every 60s only during market hours
  useEffect(() => {
    loadLivePrices();
    if (!isMarketHours()) return;
    const interval = setInterval(loadLivePrices, 60_000);
    return () => clearInterval(interval);
  }, [loadLivePrices]);

  const filtered = entries.filter(e => {
    if (filter === 'ALL' || filter === 'ANALYTICS' || filter === 'CALENDAR') return true;
    if (filter === 'OPEN') return e.outcome === 'open';
    if (filter === 'CLOSED') return ['win', 'loss', 'skip'].includes(e.outcome);
    if (filter === 'WIN') return e.outcome === 'win';
    if (filter === 'LOSS') return e.outcome === 'loss';
    return true;
  });

  async function handleClose(id, reason) {
    const entry = entries.find(e => e.id === id);
    if (!entry) return;
    const price = parseFloat(prompt(`Exit price for ${entry.symbol}?`, entry.current_price || entry.entry_price));
    if (!price) return;
    const outcome = reason === 'STOP_HIT' ? 'loss' : 'win';
    await fetch(`${API_URL}/api/journal/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        exit_price: price,
        exit_date: new Date().toISOString().split('T')[0],
        outcome,
        status: reason === 'STOP_HIT' ? 'STOPPED' : 'CLOSED',
        exit_reason: reason,
        final_pnl_pct: parseFloat(((price - entry.entry_price) / entry.entry_price * 100).toFixed(2)),
      }),
    });
    loadData();
  }

  async function handleDelete(id) {
    if (!confirm('Delete this journal entry?')) return;
    await fetch(`${API_URL}/api/journal/${id}`, { method: 'DELETE' });
    loadData();
  }

  async function loadInsights() {
    setInsightsLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/journal/insights`);
      if (res.ok) setInsights(await res.json());
    } catch { }
    finally { setInsightsLoading(false); }
  }

  async function loadDeepAnalytics() {
    setDeepLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/journal/deep-analytics`);
      if (res.ok) setDeepAnalytics(await res.json());
    } catch { }
    finally { setDeepLoading(false); }
  }

  const openCount = entries.filter(e => e.outcome === 'open').length;
  const winCount = entries.filter(e => e.outcome === 'win').length;
  const lossCount = entries.filter(e => e.outcome === 'loss').length;

  return (
    <>
      <Head>
        <title>Trade Journal — Pump Scout</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>
      <div className={styles.container}>
        {/* Nav */}
        <nav className={styles.nav}>
          <Link href="/" className={styles.backLink}>← Scanner</Link>
          <span className={styles.navTitle}>📔 TRADE JOURNAL</span>
          <div className={styles.navActions}>
            <Link href="/ai-portfolio" className={`${styles.btn} ${styles.btnGold}`}>🤖 AI Portfolio</Link>
            <button className={styles.btn} onClick={() => window.location.href = `${API_URL}/api/journal/export`}>↓ CSV</button>
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={() => setShowAdd(true)}>+ Add Trade</button>
          </div>
        </nav>

        {/* Stats */}
        {stats && (
          <div className={styles.statsGrid}>
            <div className={styles.statCard}>
              <div className={styles.statLabel}>TOTAL</div>
              <div className={styles.statValue}>{stats.total_trades}</div>
              <div className={styles.statMeta}>{openCount} open · {stats.closed_trades} closed</div>
            </div>
            {stats.closed_trades === 0 ? (
              <div className={styles.statCard} style={{ gridColumn: 'span 4', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 12 }}>
                Нет закрытых сделок — закройте позицию чтобы увидеть статистику
              </div>
            ) : (
              <>
                <div className={styles.statCard}>
                  <div className={styles.statLabel}>WIN RATE</div>
                  <div className={`${styles.statValue} ${stats.win_rate_pct >= 50 ? styles.win : styles.neutral}`}>
                    {stats.win_rate_pct}%
                  </div>
                  <div className={styles.statMeta}>{winCount}W / {lossCount}L</div>
                </div>
                <div className={styles.statCard}>
                  <div className={styles.statLabel}>AVG WIN</div>
                  <div className={`${styles.statValue} ${styles.win}`}>{stats.avg_gain_winners > 0 ? '+' : ''}{stats.avg_gain_winners}%</div>
                </div>
                <div className={styles.statCard}>
                  <div className={styles.statLabel}>AVG LOSS</div>
                  <div className={`${styles.statValue} ${styles.loss}`}>{(stats.avg_loss_losers || 0).toFixed(1)}%</div>
                </div>
                <div className={styles.statCard}>
                  <div className={styles.statLabel}>TOTAL PnL</div>
                  <div className={`${styles.statValue} ${stats.total_pnl_pct >= 0 ? styles.win : styles.loss}`}>
                    {stats.total_pnl_pct >= 0 ? '+' : ''}{stats.total_pnl_pct}%
                  </div>
                </div>
              </>
            )}
            {stats.best_tier && (
              <div className={styles.statCard}>
                <div className={styles.statLabel}>BEST TIER</div>
                <div className={styles.statValue} style={{ color: TIER_COLORS[stats.best_tier] || 'var(--cyan)' }}>
                  {stats.best_tier}
                </div>
              </div>
            )}
            {stats.avg_alpha_pct != null && (
              <div className={styles.statCard}>
                <div className={styles.statLabel}>AVG ALPHA</div>
                <div className={`${styles.statValue} ${stats.avg_alpha_pct >= 0 ? styles.win : styles.loss}`}>
                  {stats.avg_alpha_pct >= 0 ? '+' : ''}{stats.avg_alpha_pct?.toFixed(1)}%
                </div>
                <div className={styles.statMeta}>vs SPY</div>
              </div>
            )}
            {stats.avg_hold_days != null && (
              <div className={styles.statCard}>
                <div className={styles.statLabel}>AVG HOLD</div>
                <div className={styles.statValue}>{stats.avg_hold_days}d</div>
              </div>
            )}
            {stats.best_trade && (
              <div className={styles.statCard}>
                <div className={styles.statLabel}>BEST TRADE</div>
                <div className={`${styles.statValue} ${styles.win}`} style={{ fontSize: 14 }}>
                  {stats.best_trade.symbol}
                </div>
                <div className={styles.statMeta}>+{stats.best_trade.pnl_pct}%</div>
              </div>
            )}
            {stats.worst_trade && (
              <div className={styles.statCard}>
                <div className={styles.statLabel}>WORST TRADE</div>
                <div className={`${styles.statValue} ${styles.loss}`} style={{ fontSize: 14 }}>
                  {stats.worst_trade.symbol}
                </div>
                <div className={styles.statMeta}>{stats.worst_trade.pnl_pct}%</div>
              </div>
            )}
          </div>
        )}

        {/* Filter tabs */}
        <div className={styles.filterBar}>
          {FILTER_TABS.map(t => (
            <button key={t}
              className={`${styles.filterTab} ${filter === t ? styles.filterTabActive : ''}`}
              onClick={() => {
                setFilter(t);
                if (t === 'ANALYTICS') {
                  if (!insights) loadInsights();
                  if (!deepAnalytics) loadDeepAnalytics();
                }
              }}
            >
              {t}
              {t !== 'ANALYTICS' && t !== 'CALENDAR' && (
                <span style={{ marginLeft: 5, opacity: 0.6 }}>
                  ({t === 'ALL' ? entries.length
                    : t === 'OPEN' ? openCount
                    : t === 'CLOSED' ? entries.filter(e => ['win','loss','skip'].includes(e.outcome)).length
                    : entries.filter(e => e.outcome === t.toLowerCase()).length})
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Calendar tab */}
        {filter === 'CALENDAR' && (
          <CalendarView
            entries={entries}
            calendarYear={calendarYear}
            calendarMonth={calendarMonth}
            onPrevMonth={prevMonth}
            onNextMonth={nextMonth}
          />
        )}

        {/* Analytics tab */}
        {filter === 'ANALYTICS' && (
          <div style={{ padding: '16px 0' }}>
            <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
              <button className={`${styles.btn} ${styles.btnGold}`} onClick={() => { loadInsights(); loadDeepAnalytics(); }} disabled={insightsLoading || deepLoading}>
                {(insightsLoading || deepLoading) ? '⏳ Analyzing…' : '🔄 Refresh All'}
              </button>
            </div>

            {(insightsLoading || deepLoading) && <div className={styles.loading}><span className={styles.spinner} /> Analyzing trades…</div>}

            {/* AI Coaching Insights */}
            {insights && !insights.message && (
              <div style={{ display: 'grid', gap: 12, marginBottom: 20 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em' }}>🤖 AI COACHING</div>
                <div className={styles.statCard} style={{ gridColumn: '1/-1' }}>
                  <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                    {insights.best_signal && <span><b style={{ color: 'var(--green)' }}>Best signal:</b> {insights.best_signal}</span>}
                    {insights.worst_signal && <span><b style={{ color: 'var(--red)' }}>Worst signal:</b> {insights.worst_signal}</span>}
                    {insights.best_wyckoff && <span><b style={{ color: 'var(--gold)' }}>Best Wyckoff:</b> {insights.best_wyckoff}</span>}
                    {insights.optimal_hold_days && <span><b>Hold time:</b> {insights.optimal_hold_days}</span>}
                    {insights.hype_sweet_spot && <span><b>Hype sweet spot:</b> {insights.hype_sweet_spot}</span>}
                  </div>
                </div>
                {insights.top_3_improvements && (
                  <div className={styles.statCard} style={{ gridColumn: '1/-1' }}>
                    <div className={styles.statLabel} style={{ marginBottom: 8 }}>🎯 TOP IMPROVEMENTS</div>
                    {insights.top_3_improvements.map((imp, i) => (
                      <div key={i} style={{ fontSize: 12, padding: '4px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                        {i + 1}. {imp}
                      </div>
                    ))}
                  </div>
                )}
                {insights.avoid_pattern && (
                  <div className={styles.statCard} style={{ background: 'rgba(255,68,68,0.06)', border: '1px solid rgba(255,68,68,0.2)' }}>
                    <div className={styles.statLabel} style={{ color: 'var(--red)', marginBottom: 4 }}>⛔ AVOID</div>
                    <div style={{ fontSize: 12 }}>{insights.avoid_pattern}</div>
                  </div>
                )}
              </div>
            )}
            {insights?.message && <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 16 }}>{insights.message}</div>}

            {/* Deep Analytics */}
            {deepAnalytics && (
              <div style={{ display: 'grid', gap: 16 }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em' }}>📊 SIGNAL PERFORMANCE ({deepAnalytics.total_closed} closed trades)</div>

                {/* By Tier */}
                {deepAnalytics.signal_performance?.by_tier && Object.keys(deepAnalytics.signal_performance.by_tier).length > 0 && (
                  <div className={styles.statCard}>
                    <div className={styles.statLabel} style={{ marginBottom: 8 }}>BY TIER</div>
                    <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
                      <thead>
                        <tr style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                          <th style={{ textAlign: 'left', paddingBottom: 4 }}>Tier</th>
                          <th style={{ textAlign: 'right' }}>Trades</th>
                          <th style={{ textAlign: 'right' }}>Win%</th>
                          <th style={{ textAlign: 'right' }}>Avg P&L</th>
                          <th style={{ textAlign: 'right' }}>Avg Alpha</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(deepAnalytics.signal_performance.by_tier).map(([tier, d]) => (
                          <tr key={tier} style={{ borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                            <td style={{ padding: '3px 0', fontWeight: 700, color: TIER_COLORS[tier] || 'var(--text-primary)' }}>{tier}</td>
                            <td style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{d.count}</td>
                            <td style={{ textAlign: 'right', color: (d.win_rate || 0) >= 0.5 ? 'var(--green)' : 'var(--red)' }}>{((d.win_rate || 0) * 100).toFixed(0)}%</td>
                            <td style={{ textAlign: 'right', color: (d.avg_pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>{(d.avg_pnl || 0) >= 0 ? '+' : ''}{(d.avg_pnl || 0).toFixed(1)}%</td>
                            <td style={{ textAlign: 'right', color: (d.avg_alpha || 0) >= 0 ? 'var(--cyan)' : 'var(--red)' }}>{(d.avg_alpha || 0) >= 0 ? '+' : ''}{(d.avg_alpha || 0).toFixed(1)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* By Wyckoff */}
                {deepAnalytics.signal_performance?.by_wyckoff && Object.keys(deepAnalytics.signal_performance.by_wyckoff).length > 0 && (
                  <div className={styles.statCard}>
                    <div className={styles.statLabel} style={{ marginBottom: 8 }}>BY WYCKOFF REGIME</div>
                    <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
                      <thead>
                        <tr style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                          <th style={{ textAlign: 'left', paddingBottom: 4 }}>Regime</th>
                          <th style={{ textAlign: 'right' }}>Trades</th>
                          <th style={{ textAlign: 'right' }}>Win%</th>
                          <th style={{ textAlign: 'right' }}>Avg P&L</th>
                          <th style={{ textAlign: 'right' }}>Avg Alpha</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(deepAnalytics.signal_performance.by_wyckoff).map(([regime, d]) => (
                          <tr key={regime} style={{ borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                            <td style={{ padding: '3px 0', fontWeight: 700 }}>{regime}</td>
                            <td style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{d.count}</td>
                            <td style={{ textAlign: 'right', color: (d.win_rate || 0) >= 0.5 ? 'var(--green)' : 'var(--red)' }}>{((d.win_rate || 0) * 100).toFixed(0)}%</td>
                            <td style={{ textAlign: 'right', color: (d.avg_pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>{(d.avg_pnl || 0) >= 0 ? '+' : ''}{(d.avg_pnl || 0).toFixed(1)}%</td>
                            <td style={{ textAlign: 'right', color: (d.avg_alpha || 0) >= 0 ? 'var(--cyan)' : 'var(--red)' }}>{(d.avg_alpha || 0) >= 0 ? '+' : ''}{(d.avg_alpha || 0).toFixed(1)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {/* By CMF Bucket */}
                {deepAnalytics.signal_performance?.by_cmf_bucket && Object.keys(deepAnalytics.signal_performance.by_cmf_bucket).length > 0 && (
                  <div className={styles.statCard}>
                    <div className={styles.statLabel} style={{ marginBottom: 8 }}>BY CMF PERCENTILE</div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      {Object.entries(deepAnalytics.signal_performance.by_cmf_bucket).map(([bucket, d]) => (
                        <div key={bucket} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 4, padding: '6px 10px', fontSize: 10, textAlign: 'center', minWidth: 80 }}>
                          <div style={{ fontWeight: 700, marginBottom: 3 }}>{bucket}</div>
                          <div style={{ color: 'var(--text-muted)' }}>{d.count} trades</div>
                          <div style={{ color: (d.win_rate || 0) >= 0.5 ? 'var(--green)' : 'var(--red)' }}>{((d.win_rate || 0) * 100).toFixed(0)}% WR</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* By Hype Bucket */}
                {deepAnalytics.signal_performance?.by_hype_bucket && Object.keys(deepAnalytics.signal_performance.by_hype_bucket).length > 0 && (
                  <div className={styles.statCard}>
                    <div className={styles.statLabel} style={{ marginBottom: 8 }}>BY HYPE SCORE</div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      {Object.entries(deepAnalytics.signal_performance.by_hype_bucket).map(([bucket, d]) => (
                        <div key={bucket} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 4, padding: '6px 10px', fontSize: 10, textAlign: 'center', minWidth: 80 }}>
                          <div style={{ fontWeight: 700, marginBottom: 3 }}>{bucket}</div>
                          <div style={{ color: 'var(--text-muted)' }}>{d.count} trades</div>
                          <div style={{ color: (d.win_rate || 0) >= 0.5 ? 'var(--green)' : 'var(--red)' }}>{((d.win_rate || 0) * 100).toFixed(0)}% WR</div>
                          <div style={{ color: (d.avg_pnl || 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>{(d.avg_pnl || 0) >= 0 ? '+' : ''}{(d.avg_pnl || 0).toFixed(1)}%</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Timing */}
                {deepAnalytics.timing && (
                  <div className={styles.statCard}>
                    <div className={styles.statLabel} style={{ marginBottom: 8 }}>⏱ EXIT TIMING</div>
                    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 11 }}>
                      <span><b style={{ color: 'var(--cyan)' }}>Avg hold:</b> {deepAnalytics.timing.avg_days_held}d</span>
                      <span><b style={{ color: 'var(--gold)' }}>Peak day:</b> Day {deepAnalytics.timing.avg_max_gain_day || '?'}</span>
                      {deepAnalytics.timing.suggested_hold_days && <span><b style={{ color: 'var(--green)' }}>Optimal hold:</b> {deepAnalytics.timing.suggested_hold_days}d</span>}
                      <span><b style={{ color: 'var(--red)' }}>Left on table:</b> {deepAnalytics.timing.avg_missed_exit_pct?.toFixed(1) || 0}%</span>
                      <span style={{ color: 'var(--text-muted)' }}>Late exits: {deepAnalytics.timing.exit_too_late_count} · Early exits: {deepAnalytics.timing.exit_too_early_count}</span>
                    </div>
                  </div>
                )}

                {/* Alpha */}
                {deepAnalytics.alpha && (
                  <div className={styles.statCard}>
                    <div className={styles.statLabel} style={{ marginBottom: 8 }}>α ALPHA VS SPY</div>
                    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', fontSize: 11 }}>
                      <span>
                        <b>Avg alpha: </b>
                        <span style={{ color: (deepAnalytics.alpha.avg_alpha_vs_spy || 0) >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>
                          {(deepAnalytics.alpha.avg_alpha_vs_spy || 0) >= 0 ? '+' : ''}{(deepAnalytics.alpha.avg_alpha_vs_spy || 0).toFixed(2)}%
                        </span>
                      </span>
                      <span>
                        <b>Beat SPY rate: </b>
                        <span style={{ color: (deepAnalytics.alpha.positive_alpha_rate || 0) >= 0.5 ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>
                          {((deepAnalytics.alpha.positive_alpha_rate || 0) * 100).toFixed(0)}%
                        </span>
                      </span>
                    </div>
                  </div>
                )}

                {/* Missed Opportunities */}
                {deepAnalytics.missed_opportunities?.candidates && deepAnalytics.missed_opportunities.candidates.length > 0 && (
                  <div className={styles.statCard} style={{ border: '1px solid rgba(255,165,0,0.2)' }}>
                    <div className={styles.statLabel} style={{ color: '#ffa500', marginBottom: 8 }}>🔍 MISSED OPPORTUNITIES (scanned but not journaled)</div>
                    <div style={{ display: 'grid', gap: 6 }}>
                      {deepAnalytics.missed_opportunities.candidates.slice(0, 8).map((c, i) => (
                        <div key={i} style={{ display: 'flex', gap: 12, fontSize: 10, alignItems: 'center', borderTop: i > 0 ? '1px solid rgba(255,255,255,0.05)' : 'none', paddingTop: i > 0 ? 4 : 0 }}>
                          <span style={{ fontWeight: 700, minWidth: 50, color: TIER_COLORS[c.tier] || 'var(--text-primary)' }}>{c.symbol}</span>
                          <span style={{ color: 'var(--text-muted)', minWidth: 40 }}>{c.tier}</span>
                          {c.ret_5d != null && <span style={{ color: c.ret_5d >= 0 ? 'var(--green)' : 'var(--red)' }}>5d: {c.ret_5d >= 0 ? '+' : ''}{c.ret_5d.toFixed(1)}%</span>}
                          {c.ret_10d != null && <span style={{ color: c.ret_10d >= 0 ? 'var(--green)' : 'var(--red)' }}>10d: {c.ret_10d >= 0 ? '+' : ''}{c.ret_10d.toFixed(1)}%</span>}
                          {c.ret_20d != null && <span style={{ color: c.ret_20d >= 0 ? 'var(--green)' : 'var(--red)' }}>20d: {c.ret_20d >= 0 ? '+' : ''}{c.ret_20d.toFixed(1)}%</span>}
                          <span style={{ color: 'var(--text-muted)', flex: 1, textAlign: 'right' }}>{c.scan_date}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Trade list */}
        {filter !== 'ANALYTICS' && filter !== 'CALENDAR' && (
          <div className={styles.tradeList}>
            {filtered.length === 0 ? (
              <div className={styles.empty}>
                {entries.length === 0 ? 'No trades yet. Add your first trade!' : `No ${filter.toLowerCase()} trades.`}
              </div>
            ) : filtered.map(e => {
              const isOpen = e.outcome === 'open';
              const isWin = e.outcome === 'win';
              const isLoss = e.outcome === 'loss';
              const pnl = e.final_pnl_pct ?? e.gain_pct;
              const live = isOpen ? livePrices[e.symbol] : null;
              const livePrice = live?.price ?? e.current_price;
              const livePct = live?.pct ?? e.current_pct;
              const displayPct = isOpen ? livePct : pnl;
              const isLive = isOpen && !!live;

              const cardStyle = isWin
                ? { borderLeft: '3px solid var(--green)' }
                : isLoss
                ? { borderLeft: '3px solid var(--red)' }
                : { borderLeft: '3px solid rgba(255,255,255,0.1)' };

              return (
                <div key={e.id} className={`${styles.tradeCard} ${isWin ? styles.tradeCardWin : isLoss ? styles.tradeCardLoss : isOpen ? styles.tradeCardOpen : styles.tradeCardSkip}`}
                  style={cardStyle}>

                  {/* Header */}
                  <div className={styles.tradeMeta} style={{ alignItems: 'center' }}>
                    <span className={styles.tradeSymbol}>{e.symbol}</span>
                    {e.tier && (
                      <span className={styles.tradeBadge} style={{
                        color: TIER_COLORS[e.tier] || 'var(--text-muted)',
                        background: (TIER_COLORS[e.tier] || '#888') + '18',
                        border: `1px solid ${(TIER_COLORS[e.tier] || '#888')}44`,
                      }}>{e.tier}</span>
                    )}
                    {isOpen && e.days_held > 0 && (
                      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>Day {e.days_held}</span>
                    )}
                    {!isOpen && (
                      <span style={{
                        fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 3,
                        background: isWin ? 'rgba(0,200,100,0.12)' : 'rgba(255,68,68,0.12)',
                        color: isWin ? 'var(--green)' : 'var(--red)',
                      }}>
                        {isWin ? '✅ WIN' : '❌ LOSS'}
                        {pnl != null ? ` ${pnl >= 0 ? '+' : ''}${pnl.toFixed(1)}%` : ''}
                        {e.days_held > 0 ? ` · ${e.days_held}d` : ''}
                      </span>
                    )}
                    {displayPct != null && isOpen && (
                      <span style={{
                        fontSize: 11, fontWeight: 700,
                        color: displayPct >= 0 ? 'var(--green)' : 'var(--red)',
                      }}>
                        {displayPct >= 0 ? '+' : ''}{displayPct.toFixed(1)}%
                      </span>
                    )}
                  </div>

                  {/* Price row */}
                  <div className={styles.tradeBody}>
                    <div className={styles.tradeRow} style={{ fontSize: 11 }}>
                      <span>
                        <span className={styles.tradeLabel}>Entry </span>
                        ${e.entry_price?.toFixed(2)}
                        {isOpen && livePrice && (
                          <span style={{ color: 'var(--text-muted)' }}>
                            {' → '}
                            <b style={{ color: displayPct >= 0 ? 'var(--green)' : 'var(--red)' }}>
                              ${livePrice?.toFixed(2)}
                            </b>
                            {isLive && <span style={{ fontSize: 9, color: 'var(--text-muted)', marginLeft: 3 }}>●</span>}
                          </span>
                        )}
                        {!isOpen && e.exit_price && (
                          <span style={{ color: 'var(--text-muted)' }}> → ${e.exit_price?.toFixed(2)}</span>
                        )}
                      </span>
                      {e.exit_reason && (
                        <span style={{ fontSize: 9, color: 'var(--text-muted)', background: 'rgba(255,255,255,0.06)', padding: '1px 5px', borderRadius: 2 }}>
                          {e.exit_reason}
                        </span>
                      )}
                    </div>

                    {/* Progress bar for open trades */}
                    {isOpen && (e.target_price || e.stop_loss) && (
                      <ProgressBar current={livePrice} entry={e.entry_price}
                        target={e.target_price} stop={e.stop_loss} />
                    )}

                    {/* Signal row */}
                    <SignalRow e={e} />

                    {e.catalyst && (
                      <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 2 }}>
                        📌 {e.catalyst}
                      </div>
                    )}
                    {e.notes && <div className={styles.tradeNotes}>{e.notes}</div>}
                    {e.tags?.length > 0 && (
                      <div className={styles.tradeTags}>
                        {e.tags.map(t => <span key={t} className={styles.tradeTag}>{t}</span>)}
                      </div>
                    )}

                    {/* Alpha / SPY metrics for closed trades */}
                    {!isOpen && (e.alpha_pct != null || e.spy_return_pct != null || e.max_gain_day != null || e.missed_exit_pct != null) && (
                      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 9, marginTop: 4, padding: '3px 6px', background: 'rgba(255,255,255,0.04)', borderRadius: 3 }}>
                        {e.spy_return_pct != null && (
                          <span style={{ color: 'var(--text-muted)' }}>SPY: <b style={{ color: e.spy_return_pct >= 0 ? 'var(--green)' : 'var(--red)' }}>{e.spy_return_pct >= 0 ? '+' : ''}{e.spy_return_pct.toFixed(1)}%</b></span>
                        )}
                        {e.alpha_pct != null && (
                          <span style={{ color: 'var(--text-muted)' }}>α: <b style={{ color: e.alpha_pct >= 0 ? 'var(--cyan)' : 'var(--red)' }}>{e.alpha_pct >= 0 ? '+' : ''}{e.alpha_pct.toFixed(1)}%</b></span>
                        )}
                        {e.max_gain_day != null && (
                          <span style={{ color: 'var(--text-muted)' }}>Peak: <b style={{ color: 'var(--gold)' }}>Day {e.max_gain_day}</b></span>
                        )}
                        {e.missed_exit_pct != null && e.missed_exit_pct > 0 && (
                          <span style={{ color: 'var(--text-muted)' }}>Left: <b style={{ color: '#ffa500' }}>{e.missed_exit_pct.toFixed(1)}%</b></span>
                        )}
                      </div>
                    )}

                    {/* AI analysis box for closed trades */}
                    {!isOpen && e.ai_analysis && <AIBox analysis={e.ai_analysis} />}
                  </div>

                  {/* Actions */}
                  <div className={styles.tradeActions}>
                    {isOpen && (
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        <button className={styles.smallBtn}
                          onClick={() => handleClose(e.id, 'MANUAL')}
                          style={{ color: 'var(--cyan)' }}>✓ Close</button>
                        {e.stop_loss && (
                          <button className={styles.smallBtn}
                            onClick={() => handleClose(e.id, 'STOP_HIT')}
                            style={{ color: 'var(--red)' }}>⛔ Stop</button>
                        )}
                        {e.target_price && (
                          <button className={styles.smallBtn}
                            onClick={() => handleClose(e.id, 'TARGET_HIT')}
                            style={{ color: 'var(--green)' }}>🎯 Target</button>
                        )}
                      </div>
                    )}
                    <div className={styles.actionBtns}>
                      <button className={styles.smallBtn} onClick={() => setEditEntry(e)} title="Edit">✎</button>
                      <button className={styles.smallBtn} onClick={() => handleDelete(e.id)}
                        style={{ color: 'var(--red)' }} title="Delete">✕</button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {showAdd && (
        <JournalModal onClose={() => setShowAdd(false)} onSaved={() => { loadData(); setShowAdd(false); }} />
      )}
      {editEntry && (
        <EditModal entry={editEntry} onClose={() => setEditEntry(null)} onSaved={() => { loadData(); setEditEntry(null); }} />
      )}
    </>
  );
}

function EditModal({ entry, onClose, onSaved }) {
  const [form, setForm] = useState({
    exit_price: entry.exit_price || '',
    exit_date: entry.exit_date || '',
    outcome: entry.outcome || 'open',
    notes: entry.notes || '',
    tags: entry.tags || [],
    stop_loss: entry.stop_loss || '',
    target_price: entry.target_price || '',
  });
  const [saving, setSaving] = useState(false);
  const TAG_OPTIONS = ['wyckoff', 'squeeze', 'sympathy', 'stealth', 'institutional', 'gap', 'divergence'];

  function toggleTag(tag) {
    setForm(f => ({ ...f, tags: f.tags.includes(tag) ? f.tags.filter(t => t !== tag) : [...f.tags, tag] }));
  }

  async function save() {
    setSaving(true);
    try {
      await fetch(`${API_URL}/api/journal/${entry.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...form,
          exit_price: form.exit_price ? parseFloat(form.exit_price) : null,
          stop_loss: form.stop_loss ? parseFloat(form.stop_loss) : null,
          target_price: form.target_price ? parseFloat(form.target_price) : null,
        }),
      });
      onSaved();
    } finally { setSaving(false); }
  }

  return (
    <div className={styles.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={styles.modal}>
        <div className={styles.modalTitle}>✎ EDIT — {entry.symbol}</div>
        <div className={styles.formGrid}>
          <div>
            <label className={styles.label}>EXIT PRICE</label>
            <input className={styles.input} type="number" step="0.01" value={form.exit_price}
              onChange={e => setForm(f => ({ ...f, exit_price: e.target.value }))} />
          </div>
          <div>
            <label className={styles.label}>EXIT DATE</label>
            <input className={styles.input} type="date" value={form.exit_date}
              onChange={e => setForm(f => ({ ...f, exit_date: e.target.value }))} />
          </div>
          <div>
            <label className={styles.label}>STOP LOSS</label>
            <input className={styles.input} type="number" step="0.01" value={form.stop_loss}
              onChange={e => setForm(f => ({ ...f, stop_loss: e.target.value }))} />
          </div>
          <div>
            <label className={styles.label}>TARGET PRICE</label>
            <input className={styles.input} type="number" step="0.01" value={form.target_price}
              onChange={e => setForm(f => ({ ...f, target_price: e.target.value }))} />
          </div>
          <div className={styles.formFull}>
            <label className={styles.label}>OUTCOME</label>
            <select className={styles.select} value={form.outcome}
              onChange={e => setForm(f => ({ ...f, outcome: e.target.value }))}>
              {['open', 'win', 'loss', 'skip'].map(o => <option key={o} value={o}>{o.toUpperCase()}</option>)}
            </select>
          </div>
          <div className={styles.formFull}>
            <label className={styles.label}>NOTES</label>
            <textarea className={styles.textarea} value={form.notes}
              onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
          </div>
          <div className={styles.formFull}>
            <label className={styles.label}>TAGS</label>
            <div className={styles.tagsGrid}>
              {TAG_OPTIONS.map(tag => (
                <label key={tag} className={styles.tagCheck}>
                  <input type="checkbox" checked={form.tags.includes(tag)} onChange={() => toggleTag(tag)} />
                  {tag}
                </label>
              ))}
            </div>
          </div>
        </div>
        <div className={styles.modalFooter}>
          <button className={styles.btn} onClick={onClose}>Cancel</button>
          <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={save} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
