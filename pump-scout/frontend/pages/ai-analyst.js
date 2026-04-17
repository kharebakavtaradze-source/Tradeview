import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import styles from '../styles/AIAnalyst.module.css';
import AppNav from '../components/AppNav';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REFRESH_INTERVAL = 90 * 1000;

// ── Config ────────────────────────────────────────────────────────────────────

const VERDICT_CFG = {
  STRONG_WATCH:   { label: '🔥 STRONG WATCH',   color: '#00ff88', bg: 'rgba(0,255,136,0.15)' },
  WATCH:          { label: '👁 WATCH',           color: '#ffd600', bg: 'rgba(255,214,0,0.12)' },
  EARLY_INTEREST: { label: '⚡ EARLY',           color: '#00e5ff', bg: 'rgba(0,229,255,0.12)' },
  LOW_QUALITY:    { label: '⬇ LOW QUALITY',     color: '#888',    bg: 'rgba(100,100,100,0.1)'  },
  EXTENDED:       { label: '⚠ EXTENDED',         color: '#ff8800', bg: 'rgba(255,136,0,0.12)'  },
};

const QUALITY_CFG = {
  EARLY:     { label: 'Early',     color: '#00e5ff' },
  CONFIRMED: { label: 'Confirmed', color: '#00ff88' },
  MIXED:     { label: 'Mixed',     color: '#ffd600' },
  WEAK:      { label: 'Weak',      color: '#888'    },
  LATE:      { label: 'Late',      color: '#ff8800' },
};

const CONF_CFG = {
  HIGH:   { color: '#00c864', bg: 'rgba(0,200,100,0.12)' },
  MEDIUM: { color: '#ffd600', bg: 'rgba(255,214,0,0.10)' },
  LOW:    { color: '#888',    bg: 'rgba(100,100,100,0.08)' },
};

// ── Chip extraction ───────────────────────────────────────────────────────────
// Maps common AI-generated phrases → compact chip labels.
// Falls back to first ~20 chars if no rule matches.

const _CHIP_RULES = [
  [/ribbon.*(compres|squeez|coil)/i,       'Ribbon Coiled'],
  [/ribbon.*(bullish|above)/i,             'Ribbon Bullish'],
  [/ribbon.*(bear|below|break)/i,          'Ribbon Bear'],
  [/no.*ignit|ignit.*(not|absent|miss)/i,  'No Ignition'],
  [/ignit.*confirm/i,                      'Ignition ✓'],
  [/cmf.*(strong|support|positive|high)/i, 'CMF+'],
  [/cmf.*(weak|negative|low)/i,            'CMF−'],
  [/obv.*(strong|rising|support)/i,        'OBV+'],
  [/obv.*(weak|declin)/i,                  'OBV−'],
  [/rsi.*(extend|overb|high)/i,            'RSI Ext.'],
  [/rsi.*(diverge)/i,                      'RSI Div.'],
  [/volume.*(confirm|spike|surge)/i,       'Vol+'],
  [/volume.*(weak|low|absent|thin)/i,      'Vol−'],
  [/(sector|industry).*(strong|lead)/i,    'Sector+'],
  [/(sector|industry).*(weak|drag|lag)/i,  'Sector−'],
  [/(late|extend|mature)\s*(setup|stage)/i,'Late Setup'],
  [/sympathy|related\s+move/i,             'Sympathy'],
  [/macro.*(bull|support|tail)/i,          'Macro+'],
  [/macro.*(bear|headwind|drag)/i,         'Macro−'],
  [/hype|social|reddit|mention/i,          'Hype'],
  [/early\s*(stage|setup|ignit)|pre.ignit/i,'Early Setup'],
  [/bb\s*(squeeze|sqz)/i,                  'BB Squeeze'],
  [/accumul/i,                             'Accumulation'],
];

function _textToChip(text) {
  for (const [re, label] of _CHIP_RULES) {
    if (re.test(text)) return label;
  }
  return text.length > 21 ? text.slice(0, 19) + '…' : text;
}

function buildChips(strengths = [], weaknesses = []) {
  const chips = [];
  for (const s of strengths.slice(0, 3)) {
    chips.push({ label: _textToChip(s), type: 'pos' });
  }
  for (const w of weaknesses.slice(0, 2)) {
    chips.push({ label: _textToChip(w), type: 'neg' });
  }
  // Deduplicate by label
  const seen = new Set();
  return chips.filter(c => {
    if (seen.has(c.label)) return false;
    seen.add(c.label);
    return true;
  }).slice(0, 5);
}

function firstSentence(text) {
  if (!text) return '';
  const m = text.match(/^[^.!?]+[.!?]/);
  if (m) return m[0].trim();
  return text.length > 110 ? text.slice(0, 108) + '…' : text;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Chip({ label, type }) {
  return (
    <span
      className={`${styles.chip} ${type === 'pos' ? styles.chipPos : styles.chipNeg}`}
    >
      {label}
    </span>
  );
}

function DetailList({ items, itemClass }) {
  if (!items?.length) return null;
  return (
    <>
      {items.map((item, i) => (
        <div key={i} className={`${styles.detailItem} ${itemClass || ''}`}>{item}</div>
      ))}
    </>
  );
}

function AnalystCard({ result }) {
  const [expanded, setExpanded] = useState(false);

  const verdict  = VERDICT_CFG[result.verdict]      || VERDICT_CFG.WATCH;
  const quality  = QUALITY_CFG[result.quality_view] || QUALITY_CFG.MIXED;
  const conf     = CONF_CFG[result.confidence]       || CONF_CFG.LOW;
  const chips    = buildChips(result.strengths, result.weaknesses);
  const sentence = firstSentence(result.explanation);
  const topStr   = result.strengths?.[0]   || '';
  const mainRisk = result.weaknesses?.[0]  || '';
  const ts       = result.created_at
    ? new Date(result.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : '';

  const hasDetail = (
    result.strengths?.length > 1     ||
    result.weaknesses?.length > 1    ||
    result.what_confirms?.length     ||
    result.what_invalidates?.length
  );

  return (
    <div className={styles.card} data-verdict={result.verdict}>

      {/* ── Row 1: Header ── */}
      <div className={styles.cardHeader}>
        <span className={styles.symbol}>{result.symbol}</span>
        <div className={styles.badges}>
          <span
            className={styles.verdictBadge}
            style={{ color: verdict.color, borderColor: verdict.color, background: verdict.bg }}
          >
            {verdict.label}
          </span>
          <span className={styles.qualityBadge} style={{ color: quality.color }}>
            {quality.label}
          </span>
          <span className={styles.confBadge} style={{ color: conf.color, background: conf.bg }}>
            {result.confidence}
          </span>
        </div>
      </div>

      {/* ── Row 2: One-sentence summary ── */}
      {sentence && <div className={styles.summary}>{sentence}</div>}

      {/* ── Row 3: Top strength / Main risk ── */}
      {(topStr || mainRisk) && (
        <div className={styles.topRow}>
          {topStr   && <div className={styles.topStrength}>↑ {topStr}</div>}
          {mainRisk && <div className={styles.mainRisk}>↓ {mainRisk}</div>}
        </div>
      )}

      {/* ── Row 4: Chips ── */}
      {chips.length > 0 && (
        <div className={styles.chips}>
          {chips.map((c, i) => <Chip key={i} label={c.label} type={c.type} />)}
        </div>
      )}

      {/* ── Row 5: Expand toggle + timestamp ── */}
      <div className={styles.cardFooter}>
        {hasDetail ? (
          <button className={styles.expandToggle} onClick={() => setExpanded(v => !v)}>
            {expanded ? '▲ Hide' : '▼ Analysis'}
          </button>
        ) : <span />}
        <span className={styles.timestamp}>{ts}</span>
      </div>

      {/* ── Expanded detail ── */}
      {expanded && (
        <div className={styles.expandedSection}>
          <div className={styles.detailGrid}>
            {result.strengths?.length > 0 && (
              <div className={styles.detailBlock}>
                <div className={`${styles.detailTitle} ${styles.dtPos}`}>Strengths</div>
                <DetailList items={result.strengths} itemClass={styles.diPos} />
              </div>
            )}
            {result.weaknesses?.length > 0 && (
              <div className={styles.detailBlock}>
                <div className={`${styles.detailTitle} ${styles.dtNeg}`}>Weaknesses</div>
                <DetailList items={result.weaknesses} itemClass={styles.diNeg} />
              </div>
            )}
            {result.what_confirms?.length > 0 && (
              <div className={styles.detailBlock}>
                <div className={`${styles.detailTitle} ${styles.dtPos}`}>✓ Confirms</div>
                <DetailList items={result.what_confirms} itemClass={styles.diPos} />
              </div>
            )}
            {result.what_invalidates?.length > 0 && (
              <div className={styles.detailBlock}>
                <div className={`${styles.detailTitle} ${styles.dtNeg}`}>✕ Invalidates</div>
                <DetailList items={result.what_invalidates} itemClass={styles.diNeg} />
              </div>
            )}
          </div>
          {result.explanation && result.explanation.length > sentence.length + 5 && (
            <div className={styles.fullExplanation}>{result.explanation}</div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AIAnalystPage() {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [runMsg,  setRunMsg]  = useState('');
  const [error,   setError]   = useState(null);
  const [rpRuns,  setRpRuns]  = useState([]);
  const [rpRunId, setRpRunId] = useState('');

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

  useEffect(() => {
    fetch(`${API_URL}/api/replay/raw-pattern-study/runs?limit=20`)
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setRpRuns(d.runs || []); })
      .catch(() => {});
  }, []);

  async function handleRun() {
    setRunning(true);
    setRunMsg('');
    try {
      const qs  = rpRunId ? `?raw_pattern_run_id=${rpRunId}` : '';
      const res = await fetch(`${API_URL}/api/ai/analyst/run${qs}`, { method: 'POST' });
      const d   = await res.json();
      setRunMsg(d.message || 'Analysis started');
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
  };

  return (
    <>
      <Head><title>🔬 AI Analyst — Pump Scout</title></Head>
      <div className={styles.page}>
        <AppNav />

        <header className={styles.header}>
          <div className={styles.advisory}>Advisory · Read-Only · Does Not Affect Scores</div>
          <h1 className={styles.title}>🔬 AI Analyst</h1>
          <p className={styles.subtitle}>AI shortlist — click ▼ Analysis to expand any card</p>
        </header>

        <div className={styles.controls}>
          <button className={styles.runBtn} onClick={handleRun} disabled={running}>
            {running ? '⏳ Running…' : '▶ Run AI Analysis'}
          </button>
          <button className={styles.refreshBtn} onClick={fetchData}>⟳ Refresh</button>
          {rpRuns.filter(r => r.status === 'complete').length > 0 && (
            <select
              className={styles.contextSelect}
              value={rpRunId}
              onChange={e => setRpRunId(e.target.value)}
              title="Optionally inject Raw Pattern Study research findings into every ticker's AI prompt"
            >
              <option value="">No research context</option>
              {rpRuns.filter(r => r.status === 'complete').map(r => (
                <option key={r.id} value={r.id}>
                  Research #{r.id} ({r.start_date?.slice(0,7)} → {r.end_date?.slice(0,7)})
                </option>
              ))}
            </select>
          )}
          {runMsg && <span className={styles.statusNote}>{runMsg}</span>}
        </div>

        <div className={styles.content}>
          {loading && <div className={styles.statusMsg}>Loading…</div>}
          {error   && <div className={styles.statusMsg} style={{ color: 'var(--red)' }}>Error: {error}</div>}

          {!loading && results.length === 0 && (
            <div className={styles.emptyMsg}>
              <div className={styles.emptyIcon}>🔬</div>
              <div>No AI analysis yet</div>
              <div className={styles.emptyHint}>
                Click ▶ Run AI Analysis to generate a shortlist from current scan candidates.
              </div>
            </div>
          )}

          {results.length > 0 && (
            <>
              <div className={styles.resultsHeader}>
                {results.length} tickers ·{' '}
                {counts.STRONG_WATCH > 0  && `🔥 ${counts.STRONG_WATCH} strong · `}
                {counts.WATCH > 0         && `👁 ${counts.WATCH} watch · `}
                {counts.EARLY_INTEREST > 0 && `⚡ ${counts.EARLY_INTEREST} early`}
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
