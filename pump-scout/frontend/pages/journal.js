import { useCallback, useEffect, useState } from 'react';
import PumpLayout from '../components/PumpLayout';
import JournalModal from '../components/JournalModal';
import styles from '../styles/Journal.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const FILTER_TABS = ['ALL', 'OPEN', 'CLOSED', 'WIN', 'LOSS', 'CALENDAR', 'ANALYTICS'];
const FILTER_LABELS = {
  ALL: '📋 All', OPEN: '📂 Open', CLOSED: '✅ Closed',
  WIN: '🏆 Wins', LOSS: '📉 Losses', CALENDAR: '📅 Calendar', ANALYTICS: '📊 Analytics',
};

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
    <div style={{ margin: '2px 0 4px', padding: '0 14px' }}>
      <div style={{ height: 5, background: 'rgba(255,255,255,0.07)', borderRadius: 3, overflow: 'hidden' }}>
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
    <div style={{ fontSize: 9, color: 'var(--text-muted)', display: 'flex', gap: 6, flexWrap: 'wrap', padding: '0 14px 4px' }}>
      {parts.map((p, i) => <span key={i} style={{ background: 'rgba(255,255,255,0.06)', padding: '2px 6px', borderRadius: 3 }}>{p}</span>)}
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
  const [closeModal, setCloseModal] = useState(null); // { entry, initialReason }
  const [resetModal, setResetModal] = useState(false);
  const [resetConfirm, setResetConfirm] = useState('');
  const [resetLoading, setResetLoading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [balanceInput, setBalanceInput] = useState('');
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
      if (sRes.ok) {
        const s = await sRes.json();
        setStats(s);
        setBalanceInput(String(s.starting_balance ?? 2000));
      }
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

  async function handleClose(entry, exitPrice, reason, outcome) {
    await fetch(`${API_URL}/api/journal/${entry.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        exit_price: exitPrice,
        exit_date: new Date().toISOString().split('T')[0],
        outcome,
        status: outcome === 'loss' ? 'STOPPED' : 'CLOSED',
        exit_reason: reason,
        final_pnl_pct: parseFloat(((exitPrice - entry.entry_price) / entry.entry_price * 100).toFixed(2)),
      }),
    });
    setCloseModal(null);
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

  async function handleReset() {
    if (resetConfirm !== 'RESET') return;
    setResetLoading(true);
    try {
      await fetch(`${API_URL}/api/journal/reset`, { method: 'DELETE' });
      setResetModal(false);
      setResetConfirm('');
      await loadData();
    } catch { }
    finally { setResetLoading(false); }
  }

  async function handleSaveBalance() {
    const val = parseFloat(balanceInput);
    if (!val || val <= 0) return;
    try {
      await fetch(`${API_URL}/api/journal/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ starting_balance: val }),
      });
      setSettingsOpen(false);
      await loadData();
    } catch { }
  }

  const openCount = entries.filter(e => e.outcome === 'open').length;
  const winCount = entries.filter(e => e.outcome === 'win').length;
  const lossCount = entries.filter(e => e.outcome === 'loss').length;

  return (
    <PumpLayout title="Journal">
      <div className={styles.container}>

        {/* Capital bar + Reset */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
          {stats && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, padding: '5px 12px' }}>
              <span style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, letterSpacing: '0.05em' }}>CAPITAL</span>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>${(stats.starting_balance ?? 2000).toLocaleString()}</span>
              {stats.closed_trades > 0 && (
                <>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)', margin: '0 2px' }}>→</span>
                  <span style={{ fontSize: 13, fontWeight: 700, color: (stats.pnl_usd ?? 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>
                    ${(stats.portfolio_value_usd ?? stats.starting_balance ?? 2000).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
                  </span>
                  <span style={{ fontSize: 11, color: (stats.pnl_usd ?? 0) >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
                    ({(stats.pnl_usd ?? 0) >= 0 ? '+' : ''}${(stats.pnl_usd ?? 0).toFixed(0)})
                  </span>
                </>
              )}
              <button
                onClick={() => setSettingsOpen(v => !v)}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 12, padding: '0 2px', lineHeight: 1 }}
                title="Change starting balance"
              >⚙</button>
            </div>
          )}
          <div style={{ flex: 1 }} />
          <button
            onClick={() => { setResetModal(true); setResetConfirm(''); }}
            style={{ background: 'rgba(255,60,60,0.08)', border: '1px solid rgba(255,60,60,0.25)', color: '#ff6b6b', fontSize: 11, fontWeight: 600, padding: '5px 12px', borderRadius: 5, cursor: 'pointer', letterSpacing: '0.04em' }}
          >
            🗑 Reset Journal
          </button>
        </div>

        {/* Settings: change starting balance */}
        {settingsOpen && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 6, padding: '8px 12px' }}>
            <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600 }}>Starting capital $</span>
            <input
              type="number"
              value={balanceInput}
              onChange={e => setBalanceInput(e.target.value)}
              style={{ width: 90, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4, color: 'var(--text)', fontSize: 13, padding: '3px 8px', fontFamily: 'inherit' }}
              min="1"
            />
            <button onClick={handleSaveBalance} className={styles.btn} style={{ fontSize: 11, padding: '4px 12px' }}>Save</button>
            <button onClick={() => setSettingsOpen(false)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: 12 }}>✕</button>
          </div>
        )}

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
                No closed trades yet — close a position to see stats
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
                  <div className={styles.statMeta} style={{ color: (stats.pnl_usd ?? 0) >= 0 ? 'var(--green)' : 'var(--red)' }}>
                    {(stats.pnl_usd ?? 0) >= 0 ? '+' : ''}${(stats.pnl_usd ?? 0).toFixed(0)}
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
          {FILTER_TABS.map(t => {
            const count = t === 'ALL' ? entries.length
              : t === 'OPEN' ? openCount
              : t === 'CLOSED' ? entries.filter(e => ['win','loss','skip'].includes(e.outcome)).length
              : t === 'WIN' ? winCount
              : t === 'LOSS' ? lossCount
              : null;
            return (
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
                {FILTER_LABELS[t] || t}
                {count != null && count > 0 && (
                  <span className={`${styles.tabCount} ${filter === t ? styles.tabCountActive : ''}`}>
                    {count}
                  </span>
                )}
              </button>
            );
          })}
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

            {/* No closed trades message */}
            {!insightsLoading && !deepLoading && stats?.closed_trades === 0 && (
              <div style={{ padding: '32px 16px', textAlign: 'center', color: 'var(--text-muted)', background: 'rgba(255,255,255,0.03)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.06)' }}>
                <div style={{ fontSize: 32, marginBottom: 12 }}>📊</div>
                <div style={{ fontWeight: 700, color: 'var(--text)', marginBottom: 6 }}>Нет данных для анализа</div>
                <div style={{ fontSize: 12 }}>Закройте минимум 3 сделки чтобы увидеть AI-аналитику по сигналам, тирам и паттернам</div>
              </div>
            )}

            {/* AI Coaching Insights — removed, see Demand Scanner AI Journal */}
            {false && insights && !insights.message && (
              <div style={{ display: 'grid', gap: 12, marginBottom: 20 }}>
                {/* Header row */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.05em' }}>AI COACHING</div>
                  {insights.has_research && insights.research_context?.length > 0 && (
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      {insights.research_context.map((src, i) => (
                        <span key={i} style={{
                          fontSize: 9, padding: '2px 7px', borderRadius: 3, fontWeight: 700,
                          letterSpacing: '0.04em',
                          background: src.type === 'replay'      ? 'rgba(0,229,255,0.08)'  :
                                      src.type === 'raw_pattern'  ? 'rgba(0,255,136,0.07)'  :
                                                                    'rgba(255,214,0,0.07)',
                          border:     src.type === 'replay'      ? '1px solid rgba(0,229,255,0.22)' :
                                      src.type === 'raw_pattern'  ? '1px solid rgba(0,255,136,0.20)' :
                                                                    '1px solid rgba(255,214,0,0.22)',
                          color:      src.type === 'replay'      ? '#00e5ff' :
                                      src.type === 'raw_pattern'  ? '#00ff88' :
                                                                    '#ffd600',
                        }}>
                          {src.type === 'replay'     ? `⚡ Replay #${src.run_id}` :
                           src.type === 'raw_pattern' ? `🔬 Patterns #${src.run_id}` :
                                                        `📊 Study #${src.run_id}`}
                          {src.date ? ` ${src.date}` : ''}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Main coaching text */}
                {insights.insights && (
                  <div className={styles.statCard} style={{ gridColumn: '1/-1' }}>
                    <div style={{ fontSize: 12, lineHeight: 1.7, whiteSpace: 'pre-wrap', color: 'var(--text)' }}>
                      {insights.insights}
                    </div>
                  </div>
                )}

                {/* Legacy structured fields — shown if present (backward compat) */}
                {(insights.best_signal || insights.worst_signal || insights.optimal_hold_days) && (
                  <div className={styles.statCard} style={{ gridColumn: '1/-1' }}>
                    <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 11 }}>
                      {insights.best_signal && <span><b style={{ color: 'var(--green)' }}>Best signal:</b> {insights.best_signal}</span>}
                      {insights.worst_signal && <span><b style={{ color: 'var(--red)' }}>Worst signal:</b> {insights.worst_signal}</span>}
                      {insights.optimal_hold_days && <span><b>Hold time:</b> {insights.optimal_hold_days}</span>}
                    </div>
                  </div>
                )}
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
                {entries.length === 0
                  ? <><div style={{ fontSize: 28, marginBottom: 10 }}>📔</div>No trades yet — add your first trade!</>
                  : `No ${FILTER_LABELS[filter] || filter.toLowerCase()} trades.`}
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

              return (
                <div key={e.id} className={`${styles.tradeCard} ${isWin ? styles.tradeCardWin : isLoss ? styles.tradeCardLoss : isOpen ? styles.tradeCardOpen : styles.tradeCardSkip}`}>

                  {/* ── Header: symbol + tier + outcome badge ── */}
                  <div className={styles.cardHeader}>
                    <div className={styles.cardSymbolGroup}>
                      <span className={styles.tradeSymbol}>{e.symbol}</span>
                      {e.tier && (
                        <span className={styles.tradeBadge} style={{
                          color: TIER_COLORS[e.tier] || 'var(--text-muted)',
                          background: (TIER_COLORS[e.tier] || '#888') + '18',
                          border: `1px solid ${(TIER_COLORS[e.tier] || '#888')}44`,
                        }}>{e.tier}</span>
                      )}
                      {e.source === 'new_pump' && (
                        <span style={{
                          fontSize: 9, padding: '2px 6px', borderRadius: 3,
                          background: 'rgba(0,229,255,0.1)', border: '1px solid rgba(0,229,255,0.25)',
                          color: '#00e5ff', fontWeight: 700, letterSpacing: '0.04em',
                        }}>⚡ NP</span>
                      )}
                      {isOpen && e.days_held > 0 && (
                        <span className={styles.dayPill}>Day {e.days_held}</span>
                      )}
                    </div>
                    <div className={styles.cardPnlGroup}>
                      {isOpen ? (
                        <>
                          {displayPct != null && (
                            <span className={styles.livePct} style={{ color: displayPct >= 0 ? 'var(--green)' : 'var(--red)' }}>
                              {displayPct >= 0 ? '+' : ''}{displayPct.toFixed(1)}%
                              {isLive && <span className={styles.liveDot} title="Live price" />}
                            </span>
                          )}
                          <span className={`${styles.outcomeBadge} ${styles.outcomeOpen}`}>OPEN</span>
                        </>
                      ) : (
                        <span className={`${styles.outcomeBadge} ${isWin ? styles.outcomeWin : styles.outcomeLoss}`}>
                          {isWin ? '✅ WIN' : '❌ LOSS'}
                          {pnl != null && <b style={{ marginLeft: 6 }}>{pnl >= 0 ? '+' : ''}{pnl.toFixed(1)}%</b>}
                          {e.days_held > 0 && <span style={{ fontWeight: 400, opacity: 0.7, marginLeft: 6 }}>{e.days_held}d</span>}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* ── Price row ── */}
                  <div className={styles.priceRow}>
                    <span className={styles.priceEntry}>${e.entry_price?.toFixed(2)}</span>
                    {e.entry_date && (
                      <span className={styles.dateTag}>{new Date(e.entry_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
                    )}
                    <span className={styles.priceArrow}>→</span>
                    {isOpen ? (
                      livePrice
                        ? <span className={styles.priceExit} style={{ color: (displayPct ?? 0) >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>${livePrice.toFixed(2)}</span>
                        : <span className={styles.priceNoData}>no price</span>
                    ) : e.exit_price ? (
                      <>
                        <span className={styles.priceExit}>${e.exit_price.toFixed(2)}</span>
                        {e.exit_date && <span className={styles.dateTag}>{new Date(e.exit_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>}
                      </>
                    ) : null}
                    {e.exit_reason && (
                      <span className={styles.exitReasonPill}>{e.exit_reason.replace(/_/g, ' ')}</span>
                    )}
                  </div>

                  {/* ── Progress bar (open trades only) ── */}
                  {isOpen && (e.target_price || e.stop_loss) && (
                    <ProgressBar current={livePrice} entry={e.entry_price} target={e.target_price} stop={e.stop_loss} />
                  )}

                  {/* ── Signal + context ── */}
                  <SignalRow e={e} />
                  {e.source === 'new_pump' && (e.np_sequence || e.signal_date) && (() => {
                    let signalPrice = null;
                    try {
                      const snap = typeof e.indicators_snapshot === 'string'
                        ? JSON.parse(e.indicators_snapshot)
                        : e.indicators_snapshot;
                      if (snap?.signal_price) signalPrice = parseFloat(snap.signal_price);
                    } catch {}
                    return (
                      <div style={{ fontSize: 9, color: 'var(--text-muted)', display: 'flex', gap: 6, flexWrap: 'wrap', padding: '0 14px 4px' }}>
                        {e.np_sequence && (
                          <span style={{ background: 'rgba(0,229,255,0.07)', padding: '2px 6px', borderRadius: 3, color: '#00e5ff', fontWeight: 700, letterSpacing: '0.03em' }}>
                            {e.np_sequence.replace(/_/g, ' ')}
                          </span>
                        )}
                        {e.signal_date && (
                          <span style={{ background: 'rgba(255,255,255,0.05)', padding: '2px 6px', borderRadius: 3 }}>
                            signal {e.signal_date}
                          </span>
                        )}
                        {signalPrice != null && (
                          <span style={{ background: 'rgba(255,255,255,0.05)', padding: '2px 6px', borderRadius: 3 }}>
                            @ ${signalPrice.toFixed(2)}
                          </span>
                        )}
                      </div>
                    );
                  })()}
                  {e.catalyst && <div className={styles.catalyst}>📌 {e.catalyst}</div>}
                  {e.notes && <div className={styles.tradeNotes}>{e.notes}</div>}
                  {e.tags?.length > 0 && (
                    <div className={styles.tradeTags}>
                      {e.tags.map(t => <span key={t} className={styles.tradeTag}>{t}</span>)}
                    </div>
                  )}

                  {/* ── Alpha row (closed) ── */}
                  {!isOpen && (e.alpha_pct != null || e.spy_return_pct != null || e.max_gain_day != null || e.missed_exit_pct != null) && (
                    <div className={styles.alphaRow}>
                      {e.spy_return_pct != null && <span>SPY <b style={{ color: e.spy_return_pct >= 0 ? 'var(--green)' : 'var(--red)' }}>{e.spy_return_pct >= 0 ? '+' : ''}{e.spy_return_pct.toFixed(1)}%</b></span>}
                      {e.alpha_pct != null && <span>α <b style={{ color: e.alpha_pct >= 0 ? 'var(--cyan)' : 'var(--red)' }}>{e.alpha_pct >= 0 ? '+' : ''}{e.alpha_pct.toFixed(1)}%</b></span>}
                      {e.max_gain_day != null && <span>Peak <b style={{ color: 'var(--gold)' }}>Day {e.max_gain_day}</b></span>}
                      {e.missed_exit_pct > 0 && <span>Left <b style={{ color: '#ffa500' }}>{e.missed_exit_pct.toFixed(1)}%</b></span>}
                    </div>
                  )}

                  {/* ── Action bar ── */}
                  <div className={styles.cardActions}>
                    {isOpen && (
                      <div className={styles.closeActions}>
                        <button className={`${styles.actionBtn} ${styles.actionBtnClose}`}
                          onClick={() => setCloseModal({ entry: e, initialReason: 'MANUAL' })}>
                          ✓ Close
                        </button>
                        {e.stop_loss && (
                          <button className={`${styles.actionBtn} ${styles.actionBtnStop}`}
                            onClick={() => setCloseModal({ entry: e, initialReason: 'STOP_HIT' })}>
                            ⛔ Stop Hit
                          </button>
                        )}
                        {e.target_price && (
                          <button className={`${styles.actionBtn} ${styles.actionBtnTarget}`}
                            onClick={() => setCloseModal({ entry: e, initialReason: 'TARGET_HIT' })}>
                            🎯 Target
                          </button>
                        )}
                      </div>
                    )}
                    <div className={styles.utilActions}>
                      <button className={styles.utilBtn} onClick={() => setEditEntry(e)}>✎ Edit</button>
                      <button className={`${styles.utilBtn} ${styles.utilBtnDanger}`} onClick={() => handleDelete(e.id)}>✕</button>
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
      {closeModal && (
        <CloseModal
          entry={closeModal.entry}
          initialReason={closeModal.initialReason}
          livePrice={livePrices[closeModal.entry.symbol]?.price ?? closeModal.entry.current_price}
          onClose={() => setCloseModal(null)}
          onConfirm={(price, reason, outcome) => handleClose(closeModal.entry, price, reason, outcome)}
        />
      )}

      {/* Reset confirmation modal */}
      {resetModal && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.75)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16 }}>
          <div style={{ background: 'var(--card)', border: '1px solid rgba(255,60,60,0.35)', borderRadius: 10, padding: 28, maxWidth: 380, width: '100%' }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: '#ff6b6b', marginBottom: 10 }}>⚠️ Reset Journal</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6, marginBottom: 16 }}>
              This will permanently delete <strong style={{ color: 'var(--text)' }}>{entries.length} trade{entries.length !== 1 ? 's' : ''}</strong> and all position snapshots.
              This action cannot be undone.
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
              Type <strong style={{ color: 'var(--text)', letterSpacing: '0.08em' }}>RESET</strong> to confirm:
            </div>
            <input
              autoFocus
              value={resetConfirm}
              onChange={e => setResetConfirm(e.target.value)}
              placeholder="RESET"
              style={{ width: '100%', background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 5, color: 'var(--text)', fontSize: 14, padding: '6px 10px', fontFamily: 'inherit', marginBottom: 16, boxSizing: 'border-box', letterSpacing: '0.08em' }}
              onKeyDown={e => { if (e.key === 'Enter' && resetConfirm === 'RESET') handleReset(); }}
            />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button onClick={() => { setResetModal(false); setResetConfirm(''); }} style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)', color: 'var(--text-muted)', padding: '7px 16px', borderRadius: 5, cursor: 'pointer', fontSize: 12 }}>
                Cancel
              </button>
              <button
                onClick={handleReset}
                disabled={resetConfirm !== 'RESET' || resetLoading}
                style={{ background: resetConfirm === 'RESET' ? 'rgba(255,60,60,0.2)' : 'rgba(255,60,60,0.05)', border: `1px solid ${resetConfirm === 'RESET' ? 'rgba(255,60,60,0.5)' : 'rgba(255,60,60,0.15)'}`, color: resetConfirm === 'RESET' ? '#ff6b6b' : 'rgba(255,107,107,0.4)', padding: '7px 16px', borderRadius: 5, cursor: resetConfirm === 'RESET' ? 'pointer' : 'default', fontSize: 12, fontWeight: 700 }}
              >
                {resetLoading ? 'Resetting…' : '🗑 Delete All Trades'}
              </button>
            </div>
          </div>
        </div>
      )}
    </PumpLayout>
  );
}

function CloseModal({ entry, initialReason, livePrice, onClose, onConfirm }) {
  const suggested = livePrice ?? entry.current_price ?? entry.entry_price ?? 0;
  const [price, setPrice] = useState(suggested ? Number(suggested).toFixed(2) : '');
  const [reason, setReason] = useState(initialReason || 'MANUAL');
  const [saving, setSaving] = useState(false);

  const numPrice = parseFloat(price);
  const valid = numPrice > 0 && !isNaN(numPrice);
  const pnlPct = valid && entry.entry_price
    ? ((numPrice - entry.entry_price) / entry.entry_price * 100)
    : null;
  const isWin = reason === 'STOP_HIT' ? false : (pnlPct != null ? pnlPct >= 0 : true);

  async function confirm() {
    if (!valid) return;
    setSaving(true);
    const outcome = !isWin ? 'loss' : 'win';
    await onConfirm(numPrice, reason, outcome);
    setSaving(false);
  }

  return (
    <div className={styles.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={styles.modal} style={{ maxWidth: 340 }}>
        <div className={styles.modalTitle}>Close {entry.symbol}</div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 14, marginTop: -8 }}>
          Entry: <b>${entry.entry_price?.toFixed(2)}</b>
          {entry.entry_date && <span style={{ marginLeft: 8 }}>{new Date(entry.entry_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>}
        </div>

        <div style={{ marginBottom: 12 }}>
          <label className={styles.label}>EXIT PRICE</label>
          <input
            className={styles.input} type="number" step="0.01"
            value={price} onChange={e => setPrice(e.target.value)}
            autoFocus onKeyDown={e => e.key === 'Enter' && confirm()}
            placeholder="0.00"
            style={{ fontSize: 18, padding: '8px 12px', fontWeight: 700 }}
          />
        </div>

        {pnlPct != null && (
          <div style={{
            padding: '10px 14px', borderRadius: 6, marginBottom: 12, textAlign: 'center',
            background: isWin ? 'rgba(0,200,100,0.1)' : 'rgba(255,68,102,0.1)',
            border: `1px solid ${isWin ? 'rgba(0,200,100,0.35)' : 'rgba(255,68,102,0.35)'}`,
          }}>
            <span style={{ fontSize: 20, fontWeight: 800, color: isWin ? 'var(--green)' : 'var(--red)' }}>
              {isWin ? '✅ WIN' : '❌ LOSS'} {pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%
            </span>
          </div>
        )}

        <div style={{ marginBottom: 16 }}>
          <label className={styles.label}>EXIT REASON</label>
          <select className={styles.select} value={reason} onChange={e => setReason(e.target.value)}>
            <option value="MANUAL">Manual Close</option>
            <option value="TARGET_HIT">🎯 Target Hit</option>
            <option value="STOP_HIT">⛔ Stop Hit (Loss)</option>
            <option value="TRAILING_STOP">Trailing Stop</option>
            <option value="PARTIAL">Partial Exit</option>
          </select>
        </div>

        <div className={styles.modalFooter}>
          <button className={styles.btn} onClick={onClose}>Cancel</button>
          <button
            className={`${styles.btn} ${isWin ? styles.btnPrimary : styles.btnDanger}`}
            onClick={confirm} disabled={saving || !valid}
          >
            {saving ? 'Saving…' : `Confirm ${isWin ? 'WIN ✅' : 'LOSS ❌'}`}
          </button>
        </div>
      </div>
    </div>
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
