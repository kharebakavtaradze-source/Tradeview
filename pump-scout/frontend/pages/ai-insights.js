import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import styles from '../styles/AIInsights.module.css';
import AppNav from '../components/AppNav';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REFRESH_INTERVAL = 120 * 1000;

// ── Config ────────────────────────────────────────────────────────────────────

const TYPE_CFG = {
  PATTERN:        { label: 'Pattern',        color: '#00c864', dot: '#00c864' },
  FILTER_WARNING: { label: 'Filter Warning',  color: '#ff8800', dot: '#ff8800' },
  MISSED_EDGE:    { label: 'Missed Edge',     color: '#ffd600', dot: '#ffd600' },
  BEHAVIORAL:     { label: 'Behavioral',      color: '#cc44ff', dot: '#cc44ff' },
  MODEL_NOTE:     { label: 'Model Note',      color: '#00e5ff', dot: '#00e5ff' },
};

const CONF_CFG = {
  HIGH:   { color: '#00c864', bg: 'rgba(0,200,100,0.12)' },
  MEDIUM: { color: '#ffd600', bg: 'rgba(255,214,0,0.10)' },
  LOW:    { color: '#888',    bg: 'rgba(100,100,100,0.08)' },
};

const LEGEND = Object.entries(TYPE_CFG).map(([k, v]) => ({ key: k, ...v }));

// ── Sub-components ────────────────────────────────────────────────────────────

function TypeBadge({ type }) {
  const cfg = TYPE_CFG[type] || TYPE_CFG.MODEL_NOTE;
  return (
    <span
      className={styles.typeBadge}
      style={{ color: cfg.color, borderColor: `${cfg.color}66`, background: `${cfg.color}18` }}
    >
      {cfg.label}
    </span>
  );
}

function ConfBadge({ conf }) {
  const cfg = CONF_CFG[conf] || CONF_CFG.LOW;
  return (
    <span className={styles.confBadge} style={{ color: cfg.color, background: cfg.bg }}>
      {conf} CONF
    </span>
  );
}

function InsightCard({ insight }) {
  const ts = insight.created_at
    ? new Date(insight.created_at).toLocaleDateString()
    : '';

  return (
    <div className={styles.insightCard} data-type={insight.insight_type}>
      {/* Header */}
      <div className={styles.cardHeader}>
        <TypeBadge type={insight.insight_type} />
        <ConfBadge conf={insight.confidence} />
      </div>

      {/* Title */}
      {insight.title && (
        <div className={styles.insightTitle}>{insight.title}</div>
      )}

      {/* Description */}
      {insight.description && (
        <div className={styles.description}>{insight.description}</div>
      )}

      {/* Evidence */}
      {insight.evidence?.length > 0 && (
        <div className={styles.evidenceBlock}>
          <div className={styles.evidenceTitle}>Evidence</div>
          {insight.evidence.map((e, i) => (
            <div key={i} className={styles.evidenceItem}>{e}</div>
          ))}
        </div>
      )}

      {/* Suggested experiment */}
      {insight.suggested_experiment && (
        <div className={styles.experimentBlock}>
          <div className={styles.experimentLabel}>Suggested Experiment</div>
          <div className={styles.experimentText}>{insight.suggested_experiment}</div>
        </div>
      )}

      {/* Footer */}
      <div className={styles.cardFooter}>
        <span className={styles.timestamp}>{ts}</span>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AIInsightsPage() {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [runMsg,  setRunMsg]  = useState('');
  const [error,   setError]   = useState(null);
  const [filter,  setFilter]  = useState('ALL');

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/ai/insights/history?limit=50`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(iv);
  }, [fetchData]);

  async function handleRun() {
    setRunning(true);
    setRunMsg('');
    try {
      const res = await fetch(`${API_URL}/api/ai/insights/run`, { method: 'POST' });
      const d   = await res.json();
      setRunMsg(d.message || 'Insight engine started');
      setTimeout(fetchData, 12000);
    } catch (e) {
      setRunMsg(`Error: ${e.message}`);
    } finally {
      setRunning(false);
    }
  }

  const allResults = data?.results || [];
  const results    = filter === 'ALL'
    ? allResults
    : allResults.filter(r => r.insight_type === filter);

  return (
    <>
      <Head><title>💡 AI Insights — Pump Scout</title></Head>
      <div className={styles.page}>
        <AppNav />

        <header className={styles.header}>
          <div className={styles.advisory}>Advisory · Suggestions Only · No Auto-Apply</div>
          <h1 className={styles.title}>💡 AI Insights</h1>
          <p className={styles.subtitle}>
            Pattern observations and suggested experiments from historical data
          </p>
        </header>

        {/* Type legend */}
        <div className={styles.legend}>
          {LEGEND.map(l => (
            <div key={l.key} className={styles.legendItem}>
              <div className={styles.legendDot} style={{ background: l.dot }} />
              <span>{l.label}</span>
            </div>
          ))}
        </div>

        {/* Controls */}
        <div className={styles.controls}>
          <button
            className={styles.runBtn}
            onClick={handleRun}
            disabled={running}
          >
            {running ? '⏳ Running...' : '▶ Run Insight Engine'}
          </button>
          <button className={styles.refreshBtn} onClick={fetchData}>⟳ Refresh</button>

          {/* Filter */}
          <select
            value={filter}
            onChange={e => setFilter(e.target.value)}
            style={{
              background: 'var(--surface2)', border: '1px solid var(--border)',
              color: 'var(--text-muted)', borderRadius: 'var(--r-sm)',
              fontSize: 11, padding: '4px 8px', cursor: 'pointer',
            }}
          >
            <option value="ALL">All types</option>
            {LEGEND.map(l => <option key={l.key} value={l.key}>{l.label}</option>)}
          </select>

          {runMsg && <span className={styles.insightCount}>{runMsg}</span>}
          {!runMsg && results.length > 0 && (
            <span className={styles.insightCount}>{results.length} insights</span>
          )}
        </div>

        {/* Content */}
        <div className={styles.content}>
          {loading && <div className={styles.statusMsg}>Loading insights...</div>}
          {error   && <div className={styles.statusMsg} style={{ color: 'var(--red)' }}>Error: {error}</div>}

          {!loading && results.length === 0 && (
            <div className={styles.emptyMsg}>
              <div>No insights yet</div>
              <div className={styles.emptyHint}>
                Click ▶ Run Insight Engine to analyze historical patterns.
                Requires 10+ scan candidates and 3+ closed journal trades.
              </div>
            </div>
          )}

          {results.map((ins, i) => (
            <InsightCard key={ins.id || i} insight={ins} />
          ))}
        </div>
      </div>
    </>
  );
}
