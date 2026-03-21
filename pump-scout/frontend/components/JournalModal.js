import { useState } from 'react';
import styles from '../styles/Journal.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const TIERS = ['FIRE', 'ARM', 'BASE', 'STEALTH', 'SYMPATHY', 'WATCH'];
const TAG_OPTIONS = ['wyckoff', 'squeeze', 'sympathy', 'stealth', 'institutional', 'gap', 'divergence'];
const OUTCOMES = ['open', 'win', 'loss', 'skip'];

const today = () => new Date().toISOString().split('T')[0];

export default function JournalModal({ prefill = {}, onClose, onSaved }) {
  const [form, setForm] = useState({
    symbol: prefill.symbol || '',
    entry_price: prefill.entry_price || '',
    entry_date: prefill.entry_date || today(),
    exit_price: '',
    exit_date: '',
    tier: prefill.tier || '',
    score: prefill.score || '',
    notes: '',
    outcome: 'open',
    tags: [],
    indicators_snapshot: prefill.indicators_snapshot || null,
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');

  function set(field, value) {
    setForm(f => ({ ...f, [field]: value }));
  }

  function toggleTag(tag) {
    setForm(f => ({
      ...f,
      tags: f.tags.includes(tag) ? f.tags.filter(t => t !== tag) : [...f.tags, tag],
    }));
  }

  async function handleSave() {
    if (!form.symbol || !form.entry_price) {
      setErr('Symbol and entry price are required.');
      return;
    }
    setSaving(true);
    setErr('');
    try {
      const body = {
        ...form,
        entry_price: parseFloat(form.entry_price),
        exit_price: form.exit_price ? parseFloat(form.exit_price) : null,
        score: form.score ? parseFloat(form.score) : null,
      };
      const res = await fetch(`${API_URL}/api/journal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const data = await res.json();
      onSaved?.(data.entry);
      onClose();
    } catch (e) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={styles.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={styles.modal}>
        <div className={styles.modalTitle}>📔 ADD TO JOURNAL</div>

        <div className={styles.formGrid}>
          <div>
            <label className={styles.label}>SYMBOL *</label>
            <input
              className={styles.input}
              value={form.symbol}
              onChange={e => set('symbol', e.target.value.toUpperCase())}
              placeholder="e.g. BATL"
            />
          </div>
          <div>
            <label className={styles.label}>TIER</label>
            <select className={styles.select} value={form.tier} onChange={e => set('tier', e.target.value)}>
              <option value="">— select —</option>
              {TIERS.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          <div>
            <label className={styles.label}>ENTRY PRICE *</label>
            <input
              className={styles.input}
              type="number"
              step="0.01"
              value={form.entry_price}
              onChange={e => set('entry_price', e.target.value)}
              placeholder="0.00"
            />
          </div>
          <div>
            <label className={styles.label}>ENTRY DATE</label>
            <input
              className={styles.input}
              type="date"
              value={form.entry_date}
              onChange={e => set('entry_date', e.target.value)}
            />
          </div>

          <div>
            <label className={styles.label}>EXIT PRICE</label>
            <input
              className={styles.input}
              type="number"
              step="0.01"
              value={form.exit_price}
              onChange={e => set('exit_price', e.target.value)}
              placeholder="optional"
            />
          </div>
          <div>
            <label className={styles.label}>EXIT DATE</label>
            <input
              className={styles.input}
              type="date"
              value={form.exit_date}
              onChange={e => set('exit_date', e.target.value)}
            />
          </div>

          <div>
            <label className={styles.label}>SCORE</label>
            <input
              className={styles.input}
              type="number"
              step="0.1"
              value={form.score}
              onChange={e => set('score', e.target.value)}
              placeholder="0–100"
            />
          </div>
          <div>
            <label className={styles.label}>OUTCOME</label>
            <select className={styles.select} value={form.outcome} onChange={e => set('outcome', e.target.value)}>
              {OUTCOMES.map(o => <option key={o} value={o}>{o.toUpperCase()}</option>)}
            </select>
          </div>

          <div className={styles.formFull}>
            <label className={styles.label}>NOTES</label>
            <textarea
              className={styles.textarea}
              value={form.notes}
              onChange={e => set('notes', e.target.value)}
              placeholder="Why this setup? What to watch..."
            />
          </div>

          <div className={styles.formFull}>
            <label className={styles.label}>TAGS</label>
            <div className={styles.tagsGrid}>
              {TAG_OPTIONS.map(tag => (
                <label key={tag} className={styles.tagCheck}>
                  <input
                    type="checkbox"
                    checked={form.tags.includes(tag)}
                    onChange={() => toggleTag(tag)}
                  />
                  {tag}
                </label>
              ))}
            </div>
          </div>
        </div>

        {err && <div style={{ color: 'var(--red)', fontSize: 11, marginTop: 8 }}>{err}</div>}

        <div className={styles.modalFooter}>
          <button className={styles.btn} onClick={onClose}>Cancel</button>
          <button className={`${styles.btn} ${styles.btnPrimary}`} onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save Trade'}
          </button>
        </div>
      </div>
    </div>
  );
}
