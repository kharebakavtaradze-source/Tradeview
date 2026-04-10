import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import styles from '../styles/AIAnalyst.module.css';
import AppNav from '../components/AppNav';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REFRESH_INTERVAL = 90 * 1000;

// ── Config ────────────────────────────────────────────────────────────────────

const VERDICT_CFG = {
  STRONG_WATCH:   { label: '🔥 STRONG WATCH',    color: '#00ff88', bg: 'rgba(0,255,136,0.15)' },
  WATCH:          { label: '👁 WATCH',            color: '#ffd600', bg: 'rgba(255,214,0,0.12)' },
  EARLY_INTEREST: { label: '⚡ EARLY INTEREST',  color: '#00e5ff', bg: 'rgba(0,229,255,0.12)' },
  LOW_QUALITY:    { label: '⬇ LOW QUALITY',      color: '#888',    bg: 'rgba(100,100,100,0.1)'  },
  EXTENDED:       { label: '⚠ EXTENDED',          color: '#ff8800', bg: 'rgba(255,136,0,0.12)'  },
};

const QUALITY_CFG = {
  EARLY:     { label: 'Early',     color: '#00e5ff' },
  CONFIRMED: { label: 'Confirmed', color: '#00ff88' },
  MIXED:     { label: 'Mixed',     color: '#ffd600' },
  WEAK:      { label: 'Weak',      color: '#888'    },
  LATE:      { label: 'Late',      color: '#ff8800' },
};

const CONF_CFG = {
  HIGH:   { color: '#00c864', bg: 'rgba(0,200,100,0.15)' },
  MEDIUM: { color: '#ffd600', bg: 'rgba(255,214,0,0.12)' },
  LOW:    { color: '#888',    bg: 'rgba(100,100,100,0.1)'  },
};

// ── Sub-components ────────────────────────────────────────────────────────────

function VerdictBadge({ verdict }) {
  const cfg = VERDICT_CFG[verdict] || VERDICT_CFG.WATCH;
  return (
    <span
      className={styles.verdictBadge}
      style={{ color: cfg.color, borderColor: cfg.color, background: cfg.bg }}
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

function ListBlock({ title, items, className, itemClassName }) {
  if (!items?.length) return null;
  return (
    <div className={className}>
      <div className={styles.swTitle}>{title}</div>
      {items.map((item, i) => (
        <div key={i} className={`${styles.swItem} ${itemClassName || ''}`}>{item}</div>
      ))}
    </div>
  );
}

function AnalystCard({ result }) {
  const verdict  = VERDICT_CFG[result.verdict]  || VERDICT_CFG.WATCH;
  const quality  = QUALITY_CFG[result.quality_view] || QUALITY_CFG.MIXED;
  const ts       = result.created_at
    ? new Date(result.created_at).toLocaleTimeString()
    : '';

  return (
    <div className={styles.card} data-verdict={result.verdict}>
      {/* Header */}
      <div className={styles.cardHeader}>
        <span className={styles.symbol}>{result.symbol}</span>
        <div className={styles.badges}>
          <VerdictBadge verdict={result.verdict} />
          <span className={styles.qualityBadge} style={{ color: quality.color }}>
            {quality.label}
          </span>
          <ConfBadge conf={result.confidence} />
        </div>
      </div>

      {/* Explanation */}
      {result.explanation && (
        <div className={styles.explanation}>{result.explanation}</div>
      )}

      {/* Strengths / Weaknesses */}
      {(result.strengths?.length > 0 || result.weaknesses?.length > 0) && (
        <div className={styles.swGrid}>
          <ListBlock
            title="Strengths"
            items={result.strengths}
            className={styles.swBlock}
          />
          <ListBlock
            title="Weaknesses"
            items={result.weaknesses}
            className={styles.swBlock}
          />
        </div>
      )}

      {/* Confirms / Invalidates */}
      {(result.what_confirms?.length > 0 || result.what_invalidates?.length > 0) && (
        <div className={styles.ciGrid}>
          <div className={styles.ciBlock}>
            <div className={`${styles.ciTitle} ${styles.confirmTitle}`}>
              ✓ What Confirms
            </div>
            {(result.what_confirms || []).map((c, i) => (
              <div key={i} className={`${styles.ciItem} ${styles.confirmItem}`}>{c}</div>
            ))}
          </div>
          <div className={styles.ciBlock}>
            <div className={`${styles.ciTitle} ${styles.invalidateTitle}`}>
              ✕ What Invalidates
            </div>
            {(result.what_invalidates || []).map((c, i) => (
              <div key={i} className={`${styles.ciItem} ${styles.invalidateItem}`}>{c}</div>
            ))}
          </div>
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

export default function AIAnalystPage() {
  const [data,     setData]     = useState(null);
  const [loading,  setLoading]  = useState(true);
  const [running,  setRunning]  = useState(false);
  const [runMsg,   setRunMsg]   = useState('');
  const [error,    setError]    = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/ai/analyst/latest?limit=60`);
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
      const res = await fetch(`${API_URL}/api/ai/analyst/run`, { method: 'POST' });
      const d   = await res.json();
      setRunMsg(d.message || 'Analysis started');
      // Poll after delay to catch results
      setTimeout(fetchData, 8000);
    } catch (e) {
      setRunMsg(`Error: ${e.message}`);
    } finally {
      setRunning(false);
    }
  }

  const results = data?.results || [];
  const counts  = {
    STRONG_WATCH:   results.filter(r => r.verdict === 'STRONG_WATCH').length,
    WATCH:          results.filter(r => r.verdict === 'WATCH').length,
    EARLY_INTEREST: results.filter(r => r.verdict === 'EARLY_INTEREST').length,
    EXTENDED:       results.filter(r => r.verdict === 'EXTENDED').length,
    LOW_QUALITY:    results.filter(r => r.verdict === 'LOW_QUALITY').length,
  };

  return (
    <>
      <Head><title>🔬 AI Analyst — Pump Scout</title></Head>
      <div className={styles.page}>
        <AppNav />

        <header className={styles.header}>
          <div className={styles.advisory}>Advisory · Read-Only · Does Not Affect Scores</div>
          <h1 className={styles.title}>🔬 AI Analyst</h1>
          <p className={styles.subtitle}>
            Structured commentary on current scan candidates
          </p>
        </header>

        <div className={styles.controls}>
          <button
            className={styles.runBtn}
            onClick={handleRun}
            disabled={running}
          >
            {running ? '⏳ Running...' : '▶ Run AI Analysis'}
          </button>
          <button className={styles.refreshBtn} onClick={fetchData}>⟳ Refresh</button>
          {runMsg && <span className={styles.statusNote}>{runMsg}</span>}
        </div>

        <div className={styles.content}>
          {loading && <div className={styles.statusMsg}>Loading AI analyst results...</div>}
          {error   && <div className={styles.statusMsg} style={{ color: 'var(--red)' }}>Error: {error}</div>}

          {!loading && results.length === 0 && (
            <div className={styles.emptyMsg}>
              <div className={styles.emptyIcon}>🔬</div>
              <div>No AI analysis yet</div>
              <div className={styles.emptyHint}>
                Click ▶ Run AI Analysis to generate commentary on the current scan candidates.
              </div>
            </div>
          )}

          {results.length > 0 && (
            <>
              <div className={styles.resultsHeader}>
                {results.length} analyses ·{' '}
                {counts.STRONG_WATCH > 0 && `🔥 ${counts.STRONG_WATCH} strong watch · `}
                {counts.WATCH > 0 && `👁 ${counts.WATCH} watch · `}
                {counts.EARLY_INTEREST > 0 && `⚡ ${counts.EARLY_INTEREST} early interest`}
              </div>
              <div className={styles.grid}>
                {results.map(r => <AnalystCard key={`${r.symbol}-${r.id}`} result={r} />)}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
