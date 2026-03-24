import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import JournalModal from '../components/JournalModal';
import styles from '../styles/Journal.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const FILTER_TABS = ['ALL', 'OPEN', 'CLOSED', 'WIN', 'LOSS', 'ANALYTICS'];

const TIER_COLORS = {
  FIRE: '#ffd700', ARM: '#00e5ff', BASE: '#00c853', STEALTH: '#cc44ff',
  SYMPATHY: '#00e5ff', WATCH: '#ff8800',
};

function ProgressBar({ current, entry, target, stop }) {
  if (!target || !entry) return null;
  const range = target - (stop || entry * 0.9);
  const progress = Math.max(0, Math.min(100, ((current || entry) - (stop || entry * 0.9)) / range * 100));
  const pct = current ? ((current - entry) / entry * 100) : 0;
  return (
    <div style={{ margin: '6px 0' }}>
      <div style={{ height: 4, background: 'rgba(255,255,255,0.08)', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${progress}%`, borderRadius: 2,
          background: pct >= 0 ? 'rgba(0,200,100,0.6)' : 'rgba(255,68,68,0.6)',
          transition: 'width 0.3s',
        }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, marginTop: 2, color: 'var(--text-muted)' }}>
        <span style={{ color: 'var(--red)' }}>Stop ${stop?.toFixed(2) || '?'}</span>
        <span style={{ color: pct >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>
          {pct >= 0 ? '+' : ''}{pct.toFixed(1)}% to target
        </span>
        <span style={{ color: 'var(--green)' }}>Target ${target?.toFixed(2)}</span>
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
      {expanded && (
        <>
          {parsed.what_failed && <div style={{ marginTop: 3, color: 'var(--red)' }}>❌ {parsed.what_failed}</div>}
          {parsed.suggestion && <div style={{ marginTop: 3, color: 'var(--text-muted)' }}>→ {parsed.suggestion}</div>}
        </>
      )}
    </div>
  );
}

export default function Journal() {
  const [entries, setEntries] = useState([]);
  const [stats, setStats] = useState(null);
  const [filter, setFilter] = useState('ALL');
  const [showAdd, setShowAdd] = useState(false);
  const [editEntry, setEditEntry] = useState(null);
  const [insights, setInsights] = useState(null);
  const [insightsLoading, setInsightsLoading] = useState(false);

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

  useEffect(() => { loadData(); }, [loadData]);

  const filtered = entries.filter(e => {
    if (filter === 'ALL' || filter === 'ANALYTICS') return true;
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
        final_pnl_pct: ((price - entry.entry_price) / entry.entry_price * 100).toFixed(2),
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
            {stats.best_tier && (
              <div className={styles.statCard}>
                <div className={styles.statLabel}>BEST TIER</div>
                <div className={styles.statValue} style={{ color: TIER_COLORS[stats.best_tier] || 'var(--cyan)' }}>
                  {stats.best_tier}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Filter tabs */}
        <div className={styles.filterBar}>
          {FILTER_TABS.map(t => (
            <button key={t}
              className={`${styles.filterTab} ${filter === t ? styles.filterTabActive : ''}`}
              onClick={() => { setFilter(t); if (t === 'ANALYTICS' && !insights) loadInsights(); }}
            >
              {t}
              {t !== 'ANALYTICS' && (
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

        {/* Analytics tab */}
        {filter === 'ANALYTICS' && (
          <div style={{ padding: '16px 0' }}>
            <button className={`${styles.btn} ${styles.btnGold}`} onClick={loadInsights} disabled={insightsLoading} style={{ marginBottom: 16 }}>
              {insightsLoading ? '⏳ Analyzing…' : '🔄 Refresh Insights'}
            </button>
            {insightsLoading && <div className={styles.loading}><span className={styles.spinner} /> Analyzing trades…</div>}
            {insights && !insights.message && (
              <div style={{ display: 'grid', gap: 12 }}>
                <div className={styles.statCard} style={{ gridColumn: '1/-1' }}>
                  <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                    <span><b style={{ color: 'var(--green)' }}>Best signal:</b> {insights.best_signal}</span>
                    <span><b style={{ color: 'var(--red)' }}>Worst signal:</b> {insights.worst_signal}</span>
                    <span><b style={{ color: 'var(--gold)' }}>Best Wyckoff:</b> {insights.best_wyckoff}</span>
                    <span><b>Hold time:</b> {insights.optimal_hold_days}</span>
                    <span><b>Hype sweet spot:</b> {insights.hype_sweet_spot}</span>
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
            {insights?.message && <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>{insights.message}</div>}
          </div>
        )}

        {/* Trade list */}
        {filter !== 'ANALYTICS' && (
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
              const displayPct = isOpen ? e.current_pct : pnl;

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
                        {isOpen && e.current_price && (
                          <span style={{ color: 'var(--text-muted)' }}> → <b style={{ color: displayPct >= 0 ? 'var(--green)' : 'var(--red)' }}>${e.current_price?.toFixed(2)}</b></span>
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
                      <ProgressBar current={e.current_price} entry={e.entry_price}
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
