import { useState, useEffect, useMemo } from 'react';
import styles from '../styles/Journal.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const TIERS = ['FIRE', 'ARM', 'BASE', 'STEALTH', 'SYMPATHY', 'WATCH'];
const TAG_OPTIONS = ['wyckoff', 'squeeze', 'sympathy', 'stealth', 'institutional', 'gap', 'divergence'];
const OUTCOMES = ['open', 'win', 'loss', 'skip'];

const today = () => new Date().toISOString().split('T')[0];

function calcRR(entry, stop, target) {
  const e = parseFloat(entry), s = parseFloat(stop), t = parseFloat(target);
  if (!e || !s || !t || s >= e || t <= e) return null;
  const risk = e - s;
  const reward = t - e;
  return {
    ratio: reward / risk,
    riskPct: ((s - e) / e * 100).toFixed(1),
    rewardPct: ((t - e) / e * 100).toFixed(1),
    riskUsd: (e - s).toFixed(2),
    rewardUsd: (t - e).toFixed(2),
  };
}

function RRIndicator({ entry, stop, target }) {
  const rr = calcRR(entry, stop, target);
  if (!rr) return null;
  const ratio = rr.ratio;
  const ok = ratio >= 2.0;
  const warn = ratio >= 1.0 && ratio < 2.0;
  const bad = ratio < 1.0;
  const color = ok ? '#00c853' : warn ? '#ffd700' : '#ff4466';
  const icon = ok ? '✅' : warn ? '⚠️' : '❌';
  return (
    <div style={{ fontSize: 11, padding: '6px 0', color: color, lineHeight: 1.6 }}>
      <div style={{ fontWeight: 700 }}>R/R: {ratio.toFixed(2)}:1 {icon}</div>
      <div style={{ color: '#aaa', fontSize: 10 }}>
        Risk: <span style={{ color: '#ff4466' }}>{rr.riskPct}% (-${rr.riskUsd})</span>
        {'  '}
        Reward: <span style={{ color: '#00c853' }}>+{rr.rewardPct}% (+${rr.rewardUsd})</span>
      </div>
      {bad && <div style={{ color: '#ff4466', fontSize: 10 }}>R/R слишком плохой — минимум 1:1</div>}
      {warn && <div style={{ color: '#ffd700', fontSize: 10 }}>Лучше искать минимум 2:1</div>}
    </div>
  );
}

function QualityChecklist({ tier, cmf, rsi, hype, wyckoff, rr }) {
  const checks = [
    {
      label: `Tier: ${tier || '?'}`,
      ok: ['FIRE', 'ARM'].includes(tier),
      note: tier === 'FIRE' ? '(лучший)' : tier === 'ARM' ? '(хороший)' : '(слабый)',
    },
    {
      label: `CMF: ${cmf ? cmf + '%ile' : '?'}`,
      ok: cmf >= 60,
      note: cmf >= 80 ? '(сильный)' : cmf >= 60 ? '(умеренный)' : '(слабый)',
    },
    {
      label: `RSI: ${rsi || '?'}`,
      ok: rsi && rsi < 65,
      note: rsi > 70 ? '(перекуплен!)' : rsi > 65 ? '(высокий)' : '(норм)',
    },
    {
      label: `Hype: ${hype != null ? hype : '?'}`,
      ok: hype != null && hype < 40,
      note: hype >= 60 ? '(ритейл вошёл!)' : hype >= 40 ? '(высокий)' : '(норм)',
    },
    {
      label: `Wyckoff: ${wyckoff || '?'}`,
      ok: wyckoff && !['NONE', 'DISTRIBUTION'].includes(wyckoff),
      note: wyckoff === 'DISTRIBUTION' ? '(продают!)' : '',
    },
    {
      label: `R/R: ${rr ? rr.toFixed(2) + ':1' : '?'}`,
      ok: rr && rr >= 2.0,
      note: rr >= 2.5 ? '(отлично)' : rr >= 2.0 ? '(хорошо)' : '(плохо)',
    },
  ];
  const score = checks.filter(c => c.ok).length;
  const stars = score >= 5 ? '⭐⭐⭐' : score >= 3 ? '⚠️' : '❌';
  return (
    <div style={{ fontSize: 10, padding: '6px 8px', background: 'rgba(255,255,255,0.03)', borderRadius: 4, marginBottom: 6 }}>
      {checks.map((c, i) => (
        <div key={i} style={{ display: 'flex', gap: 6, color: c.ok ? '#00c853' : '#ff4466', marginBottom: 2 }}>
          <span>{c.ok ? '✅' : '❌'}</span>
          <span>{c.label}</span>
          <span style={{ color: '#666' }}>{c.note}</span>
        </div>
      ))}
      <div style={{ borderTop: '1px solid rgba(255,255,255,0.08)', marginTop: 4, paddingTop: 4, fontWeight: 700 }}>
        Quality: {score}/6 {stars}
      </div>
    </div>
  );
}

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
    entry_wyckoff: prefill.entry_wyckoff || '',
    entry_cmf_pctl: prefill.entry_cmf_pctl || '',
    entry_vol_ratio: prefill.entry_vol_ratio || '',
    entry_hype: prefill.entry_hype || 0,
    entry_rsi: prefill.entry_rsi || '',
    catalyst: prefill.catalyst || '',
  });
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const [warn, setWarn] = useState('');
  const [atrHint, setAtrHint] = useState(null); // {stop_pct, target_pct, atr_used}

  function set(field, value) {
    setForm(f => ({ ...f, [field]: value }));
  }

  function toggleTag(tag) {
    setForm(f => ({
      ...f,
      tags: f.tags.includes(tag) ? f.tags.filter(t => t !== tag) : [...f.tags, tag],
    }));
  }

  // Fetch ATR-based suggested levels when symbol + entry price are available
  useEffect(() => {
    const sym = form.symbol.trim();
    const price = parseFloat(form.entry_price);
    const tier = form.tier || 'ARM';
    if (!sym || !price || price <= 0) return;

    const controller = new AbortController();
    const timeout = setTimeout(async () => {
      try {
        const res = await fetch(
          `${API_URL}/api/journal/suggest-levels?symbol=${sym}&entry=${price}&tier=${tier}`,
          { signal: controller.signal }
        );
        if (!res.ok) return;
        const data = await res.json();
        // Only pre-fill if user hasn't entered values yet
        setForm(f => ({
          ...f,
          stop_loss: f.stop_loss || String(data.stop),
          target_price: f.target_price || String(data.target),
        }));
        setAtrHint({ stop_pct: data.stop_pct, target_pct: data.target_pct, atr_used: data.atr_used });
      } catch (e) {
        if (e.name !== 'AbortError') console.warn('suggest-levels failed:', e);
      }
    }, 600); // debounce

    return () => { clearTimeout(timeout); controller.abort(); };
  }, [form.symbol, form.entry_price, form.tier]);

  const rr = useMemo(
    () => calcRR(form.entry_price, form.stop_loss, form.target_price),
    [form.entry_price, form.stop_loss, form.target_price]
  );

  const rrRatio = rr ? rr.ratio : null;
  const rrBad = rrRatio !== null && rrRatio < 1.0;

  async function handleSave() {
    if (!form.symbol || !form.entry_price) {
      setErr('Symbol and entry price are required.');
      return;
    }
    setSaving(true);
    setErr('');
    setWarn('');
    try {
      const body = {
        ...form,
        entry_price: parseFloat(form.entry_price),
        score: form.score ? parseFloat(form.score) : null,
        stop_loss: form.stop_loss ? parseFloat(form.stop_loss) : null,
        target_price: form.target_price ? parseFloat(form.target_price) : null,
        entry_cmf_pctl: form.entry_cmf_pctl ? parseFloat(form.entry_cmf_pctl) : null,
        entry_vol_ratio: form.entry_vol_ratio ? parseFloat(form.entry_vol_ratio) : null,
        entry_rsi: form.entry_rsi ? parseFloat(form.entry_rsi) : null,
        entry_hype: form.entry_hype ? parseInt(form.entry_hype) : 0,
        // Allow user override of R/R validation
        override_rr: rrBad,
      };
      const res = await fetch(`${API_URL}/api/journal`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `API error ${res.status}`);
      }
      const data = await res.json();
      if (data.warning) setWarn(data.warning);
      onSaved?.(data.entry);
      onClose();
    } catch (e) {
      setErr(e.message);
    } finally {
      setSaving(false);
    }
  }

  const showChecklist = !!(form.tier || form.entry_cmf_pctl || form.entry_rsi || form.entry_wyckoff);

  return (
    <div className={styles.overlay} onClick={e => e.target === e.currentTarget && onClose()}>
      <div className={styles.modal}>
        <div className={styles.modalTitle}>📔 ADD TO JOURNAL</div>

        {showChecklist && (
          <QualityChecklist
            tier={form.tier}
            cmf={parseFloat(form.entry_cmf_pctl) || null}
            rsi={parseFloat(form.entry_rsi) || null}
            hype={form.entry_hype || null}
            wyckoff={form.entry_wyckoff || null}
            rr={rrRatio}
          />
        )}

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

          {/* Row 3: Stop loss + Target with ATR hints */}
          <div>
            <label className={styles.label}>
              STOP LOSS
              {atrHint && (
                <span style={{ color: '#666', fontWeight: 400, marginLeft: 6 }}>
                  ← {atrHint.stop_pct}% (1.5x ATR)
                </span>
              )}
            </label>
            <input className={styles.input} type="number" step="0.01" value={form.stop_loss}
              onChange={e => set('stop_loss', e.target.value)}
              placeholder={atrHint ? `ATR suggestion` : 'e.g. 22.78'} />
          </div>
          <div>
            <label className={styles.label}>
              TARGET PRICE
              {atrHint && (
                <span style={{ color: '#666', fontWeight: 400, marginLeft: 6 }}>
                  ← +{atrHint.target_pct}% (3.75x ATR)
                </span>
              )}
            </label>
            <input className={styles.input} type="number" step="0.01" value={form.target_price}
              onChange={e => set('target_price', e.target.value)}
              placeholder={atrHint ? `ATR suggestion` : 'e.g. 28.66'} />
          </div>

          {/* Live R/R display */}
          {(form.stop_loss || form.target_price) && (
            <div className={styles.formFull}>
              <RRIndicator entry={form.entry_price} stop={form.stop_loss} target={form.target_price} />
            </div>
          )}

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

          {/* Signal context (pre-filled from scan) */}
          {(form.entry_wyckoff || form.entry_cmf_pctl || form.entry_vol_ratio) && (
            <div className={styles.formFull} style={{ fontSize: 10, color: 'var(--text-muted)', display: 'flex', gap: 12, flexWrap: 'wrap', padding: '4px 0' }}>
              {form.entry_wyckoff && <span>Wyckoff: <b>{form.entry_wyckoff}</b></span>}
              {form.entry_cmf_pctl && <span>CMF: <b>{form.entry_cmf_pctl}%ile</b></span>}
              {form.entry_vol_ratio && <span>Vol: <b>{form.entry_vol_ratio}x</b></span>}
              {form.entry_hype > 0 && <span>Hype: <b>{form.entry_hype}/100</b></span>}
              {form.entry_rsi && <span>RSI: <b>{form.entry_rsi}</b></span>}
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
        {warn && <div style={{ color: '#ffd700', fontSize: 11, marginTop: 8 }}>⚠️ {warn}</div>}
        {rrBad && (
          <div style={{ color: '#ff4466', fontSize: 10, marginTop: 4 }}>
            R/R ниже 1:1 — сохранение разрешено, но это плохая сделка
          </div>
        )}

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
