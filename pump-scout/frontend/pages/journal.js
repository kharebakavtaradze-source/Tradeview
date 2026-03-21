import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import JournalModal from '../components/JournalModal';
import styles from '../styles/Journal.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const FILTER_TABS = ['ALL', 'OPEN', 'CLOSED', 'WIN', 'LOSS'];

const TIER_COLORS = {
  FIRE: '#ffd700', ARM: '#00e5ff', BASE: '#00c853', STEALTH: '#cc44ff',
  SYMPATHY: '#00e5ff', WATCH: '#ff8800',
};

function OutcomeBadge({ outcome }) {
  const cls = {
    win: styles.outcomeWin,
    loss: styles.outcomeLoss,
    open: styles.outcomeOpen,
    skip: styles.outcomeSkip,
  }[outcome] || styles.outcomeSkip;
  return <span className={`${styles.outcomeBadge} ${cls}`}>{outcome?.toUpperCase()}</span>;
}

function GainBadge({ gain }) {
  if (gain == null) return <span className={styles.neutral}>—</span>;
  const cls = gain >= 0 ? styles.win : styles.loss;
  return <span className={`${styles.gainBadge} ${cls}`}>{gain >= 0 ? '+' : ''}{gain.toFixed(1)}%</span>;
}

export default function Journal() {
  const [entries, setEntries] = useState([]);
  const [stats, setStats] = useState(null);
  const [filter, setFilter] = useState('ALL');
  const [showAdd, setShowAdd] = useState(false);
  const [editEntry, setEditEntry] = useState(null);
  const [insights, setInsights] = useState('');
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [showInsights, setShowInsights] = useState(false);

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
    if (filter === 'ALL') return true;
    if (filter === 'OPEN') return e.outcome === 'open';
    if (filter === 'CLOSED') return ['win', 'loss', 'skip'].includes(e.outcome);
    if (filter === 'WIN') return e.outcome === 'win';
    if (filter === 'LOSS') return e.outcome === 'loss';
    return true;
  });

  async function handleDelete(id) {
    if (!confirm('Delete this journal entry?')) return;
    await fetch(`${API_URL}/api/journal/${id}`, { method: 'DELETE' });
    loadData();
  }

  async function handleExport() {
    window.location.href = `${API_URL}/api/journal/export`;
  }

  async function handleInsights() {
    setInsightsLoading(true);
    setShowInsights(true);
    setInsights('');
    try {
      const res = await fetch(`${API_URL}/api/journal/insights`, { method: 'POST' });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const data = await res.json();
      setInsights(data.insights);
    } catch (e) {
      setInsights(`Error: ${e.message}`);
    } finally {
      setInsightsLoading(false);
    }
  }

  return (
    <>
      <Head>
        <title>Trade Journal — Pump Scout</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>

      <div className={styles.container}>
        {/* Nav */}
        <nav className={styles.nav}>
          <Link href="/" className={styles.backLink}>← Back to Scanner</Link>
          <span className={styles.navTitle}>📔 TRADE JOURNAL</span>
          <div className={styles.navActions}>
            <button className={`${styles.btn} ${styles.btnGold}`} onClick={handleInsights}>
              🤖 AI Insights
            </button>
            <button className={styles.btn} onClick={handleExport}>
              ↓ Export CSV
            </button>
            <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={() => setShowAdd(true)}>
              + Add Trade
            </button>
          </div>
        </nav>

        {/* Stats */}
        {stats && (
          <div className={styles.statsGrid}>
            <div className={styles.statCard}>
              <div className={styles.statLabel}>TOTAL TRADES</div>
              <div className={styles.statValue}>{stats.total_trades}</div>
              <div className={styles.statMeta}>{stats.open_trades} open · {stats.closed_trades} closed</div>
            </div>
            <div className={styles.statCard}>
              <div className={styles.statLabel}>WIN RATE</div>
              <div className={`${styles.statValue} ${stats.win_rate_pct >= 50 ? styles.win : styles.neutral}`}>
                {stats.win_rate_pct}%
              </div>
              <div className={styles.statMeta}>{stats.wins}W / {stats.losses}L</div>
            </div>
            <div className={styles.statCard}>
              <div className={styles.statLabel}>AVG WIN</div>
              <div className={`${styles.statValue} ${styles.win}`}>
                {stats.avg_gain_winners > 0 ? '+' : ''}{stats.avg_gain_winners}%
              </div>
            </div>
            <div className={styles.statCard}>
              <div className={styles.statLabel}>AVG LOSS</div>
              <div className={`${styles.statValue} ${styles.loss}`}>
                {stats.avg_loss_losers.toFixed(1)}%
              </div>
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
            {stats.best_score_range && (
              <div className={styles.statCard}>
                <div className={styles.statLabel}>BEST SCORE RANGE</div>
                <div className={styles.statValue} style={{ fontSize: 16 }}>{stats.best_score_range}</div>
              </div>
            )}
          </div>
        )}

        {/* Filter tabs */}
        <div className={styles.filterBar}>
          {FILTER_TABS.map(t => (
            <button
              key={t}
              className={`${styles.filterTab} ${filter === t ? styles.filterTabActive : ''}`}
              onClick={() => setFilter(t)}
            >
              {t}
              <span style={{ marginLeft: 5, opacity: 0.6 }}>
                ({t === 'ALL' ? entries.length
                  : t === 'OPEN' ? entries.filter(e => e.outcome === 'open').length
                  : t === 'CLOSED' ? entries.filter(e => ['win','loss','skip'].includes(e.outcome)).length
                  : entries.filter(e => e.outcome === t.toLowerCase()).length})
              </span>
            </button>
          ))}
        </div>

        {/* Trade list */}
        <div className={styles.tradeList}>
          {filtered.length === 0 ? (
            <div className={styles.empty}>
              {entries.length === 0
                ? 'No trades yet. Add your first trade to start tracking!'
                : `No ${filter.toLowerCase()} trades.`}
            </div>
          ) : (
            filtered.map(e => {
              const cardCls = {
                win: styles.tradeCardWin,
                loss: styles.tradeCardLoss,
                open: styles.tradeCardOpen,
                skip: styles.tradeCardSkip,
              }[e.outcome] || '';

              return (
                <div key={e.id} className={`${styles.tradeCard} ${cardCls}`}>
                  <div className={styles.tradeMeta}>
                    <span className={styles.tradeSymbol}>{e.symbol}</span>
                    {e.tier && (
                      <span
                        className={styles.tradeBadge}
                        style={{
                          color: TIER_COLORS[e.tier] || 'var(--text-muted)',
                          background: (TIER_COLORS[e.tier] || '#888') + '18',
                          border: `1px solid ${(TIER_COLORS[e.tier] || '#888')}44`,
                        }}
                      >
                        {e.tier}
                      </span>
                    )}
                    {e.score && (
                      <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                        score {e.score?.toFixed(0)}
                      </span>
                    )}
                  </div>

                  <div className={styles.tradeBody}>
                    <div className={styles.tradeRow}>
                      <span><span className={styles.tradeLabel}>Entry </span>${e.entry_price} · {e.entry_date}</span>
                      {e.exit_price && (
                        <span><span className={styles.tradeLabel}>Exit </span>${e.exit_price} · {e.exit_date}</span>
                      )}
                    </div>
                    {e.notes && <div className={styles.tradeNotes}>{e.notes}</div>}
                    {e.tags?.length > 0 && (
                      <div className={styles.tradeTags}>
                        {e.tags.map(t => <span key={t} className={styles.tradeTag}>{t}</span>)}
                      </div>
                    )}
                  </div>

                  <div className={styles.tradeActions}>
                    <GainBadge gain={e.gain_pct} />
                    <OutcomeBadge outcome={e.outcome} />
                    <div className={styles.actionBtns}>
                      <button
                        className={styles.smallBtn}
                        onClick={() => setEditEntry(e)}
                        title="Edit"
                      >✎</button>
                      <button
                        className={styles.smallBtn}
                        onClick={() => handleDelete(e.id)}
                        style={{ color: 'var(--red)' }}
                        title="Delete"
                      >✕</button>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Add trade modal */}
      {showAdd && (
        <JournalModal
          onClose={() => setShowAdd(false)}
          onSaved={() => { loadData(); setShowAdd(false); }}
        />
      )}

      {/* Edit trade modal */}
      {editEntry && (
        <EditModal
          entry={editEntry}
          onClose={() => setEditEntry(null)}
          onSaved={() => { loadData(); setEditEntry(null); }}
        />
      )}

      {/* AI Insights modal */}
      {showInsights && (
        <div className={styles.overlay} onClick={e => e.target === e.currentTarget && setShowInsights(false)}>
          <div className={styles.insightsModal}>
            <div className={styles.modalTitle}>🤖 AI TRADING INSIGHTS</div>
            {insightsLoading ? (
              <div className={styles.loading}>
                <span className={styles.spinner} /> Analyzing your journal...
              </div>
            ) : (
              <div className={styles.insightsText}>{insights}</div>
            )}
            <div className={styles.modalFooter}>
              <button className={styles.btn} onClick={() => setShowInsights(false)}>Close</button>
            </div>
          </div>
        </div>
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
  });
  const [saving, setSaving] = useState(false);

  const TAG_OPTIONS = ['wyckoff', 'squeeze', 'sympathy', 'stealth', 'institutional', 'gap', 'divergence'];

  function toggleTag(tag) {
    setForm(f => ({
      ...f,
      tags: f.tags.includes(tag) ? f.tags.filter(t => t !== tag) : [...f.tags, tag],
    }));
  }

  async function save() {
    setSaving(true);
    try {
      const body = {
        ...form,
        exit_price: form.exit_price ? parseFloat(form.exit_price) : null,
      };
      await fetch(`${API_URL}/api/journal/${entry.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      onSaved();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={styles.modal}>
        <div className={styles.modalTitle}>✎ EDIT — {entry.symbol}</div>
        <div className={styles.formGrid}>
          <div>
            <label className={styles.label}>EXIT PRICE</label>
            <input className={styles.input} type="number" step="0.01"
              value={form.exit_price} onChange={e => setForm(f => ({ ...f, exit_price: e.target.value }))} />
          </div>
          <div>
            <label className={styles.label}>EXIT DATE</label>
            <input className={styles.input} type="date"
              value={form.exit_date} onChange={e => setForm(f => ({ ...f, exit_date: e.target.value }))} />
          </div>
          <div className={styles.formFull}>
            <label className={styles.label}>OUTCOME</label>
            <select className={styles.select} value={form.outcome} onChange={e => setForm(f => ({ ...f, outcome: e.target.value }))}>
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
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
}
