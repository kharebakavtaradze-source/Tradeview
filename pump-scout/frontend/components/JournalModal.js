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
    entry_date: today(),
    tier: prefill.tier || '',
    score: prefill.score || '',
    stop_loss: prefill.stop_loss || '',
    target_price: prefill.target_price || '',
    notes: '',
    outcome: 'open',
    tags: [],
    indicators_snapshot: prefill.indicators_snapshot || null,
    // Extended fields pre-filled from scan data
    entry_wyckoff: prefill.entry_wyckoff || '',
    entry_cmf_pctl: prefill.entry_cmf_pctl || '',
    entry_vol_ratio: prefill.entry_vol_ratio || '',
    entry_hype: prefill.entry_hype || 0,
    catalyst: prefill.catalyst || '',
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
        score: form.score ? parseFloat(form.score) : null,
        stop_loss: form.stop_loss ? parseFloat(form.stop_loss) : null,
        target_price: form.target_price ? parseFloat(form.target_price) : null,
        entry_cmf_pctl: form.entry_cmf_pctl ? parseFloat(form.entry_cmf_pctl) : null,
        entry_vol_ratio: form.entry_vol_ratio ? parseFloat(form.entry_vol_ratio) : null,
        entry_hype: form.entry_hype ? parseInt(form.entry_hype) : 0,
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
          {/* Row 1: Symbol + Tier */}
          <div>
            <label className={styles.label}>SYMBOL *</label>
            <input className={styles.input} value={form.symbol}
              onChange={e => set('symbol', e.target.value.toUpperCase())} placeholder="e.g. BATL" />
          </div>
          <div>
            <label className={styles.label}>TIER</label>
            <select className={styles.select} value={form.tier} onChange={e => set('tier', e.target.value)}>
              <option value="">— select —</option>
              {TIERS.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>

          {/* Row 2: Entry price + date */}
          <div>
            <label className={styles.label}>ENTRY PRICE *</label>
            <input className={styles.input} type="number" step="0.01" value={form.entry_price}
              onChange={e => set('entry_price', e.target.value)} placeholder="0.00" />
          </div>
          <div>
            <label className={styles.label}>ENTRY DATE</label>
            <input className={styles.input} type="date" value={form.entry_date}
              onChange={e => set('entry_date', e.target.value)} />
          </div>

          {/* Row 3: Stop loss + Target (required for auto-close) */}
          <div>
            <label className={styles.label}>STOP LOSS</label>
            <input className={styles.input} type="number" step="0.01" value={form.stop_loss}
              onChange={e => set('stop_loss', e.target.value)}
              placeholder={prefill.stop_loss ? `$${prefill.stop_loss}` : 'e.g. TR Low'} />
          </div>
          <div>
            <label className={styles.label}>TARGET PRICE</label>
            <input className={styles.input} type="number" step="0.01" value={form.target_price}
              onChange={e => set('target_price', e.target.value)}
              placeholder={prefill.target_price ? `$${prefill.target_price}` : 'e.g. TR High'} />
          </div>

          {/* Row 4: Score + Catalyst */}
          <div>
            <label className={styles.label}>SCORE</label>
            <input className={styles.input} type="number" step="0.1" value={form.score}
              onChange={e => set('score', e.target.value)} placeholder="0–100" />
          </div>
          <div>
            <label className={styles.label}>CATALYST</label>
            <input className={styles.input} value={form.catalyst}
              onChange={e => set('catalyst', e.target.value)}
              placeholder="e.g. SILENT_VOLUME" />
          </div>

          {/* Signal context row (pre-filled from scan, read-only display) */}
          {(form.entry_wyckoff || form.entry_cmf_pctl || form.entry_vol_ratio) && (
            <div className={styles.formFull} style={{ fontSize: 10, color: 'var(--text-muted)', display: 'flex', gap: 12, flexWrap: 'wrap', padding: '4px 0' }}>
              {form.entry_wyckoff && <span>Wyckoff: <b>{form.entry_wyckoff}</b></span>}
              {form.entry_cmf_pctl && <span>CMF: <b>{form.entry_cmf_pctl}%ile</b></span>}
              {form.entry_vol_ratio && <span>Vol: <b>{form.entry_vol_ratio}x</b></span>}
              {form.entry_hype > 0 && <span>Hype: <b>{form.entry_hype}/100</b></span>}
            </div>
          )}

          <div className={styles.formFull}>
            <label className={styles.label}>NOTES</label>
            <textarea className={styles.textarea} value={form.notes}
              onChange={e => set('notes', e.target.value)} placeholder="Why this setup? What to watch..." />
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
