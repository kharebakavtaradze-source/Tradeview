import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import styles from '../styles/PumpEngine.module.css';
import AppNav from '../components/AppNav';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REFRESH_INTERVAL = 60 * 1000;

// ── Config maps ───────────────────────────────────────────────────────────────

const PUMP_SIGNAL_CFG = {
  PUMP_ACTIVE:      { label: '🚀 ACTIVE',       color: '#ff4400', bg: 'rgba(255,68,0,0.18)'   },
  PUMP_BUILDING:    { label: '📈 BUILDING',      color: '#ff8800', bg: 'rgba(255,136,0,0.15)' },
  PUMP_EARLY:       { label: '⚡ EARLY',          color: '#ffd600', bg: 'rgba(255,214,0,0.12)' },
  PUMP_SPECULATIVE: { label: '🔍 SPECULATIVE',   color: '#cc44ff', bg: 'rgba(204,68,255,0.12)'},
  NO_PUMP_SIGNAL:   { label: '─ NO SIGNAL',      color: '#555',    bg: 'rgba(80,80,80,0.08)'  },
};

const TOXICITY_CFG = {
  LOW:     { color: '#00c864', label: 'LOW'     },
  MEDIUM:  { color: '#ffd600', label: 'MEDIUM'  },
  HIGH:    { color: '#ff8800', label: 'HIGH'    },
  EXTREME: { color: '#ff4444', label: 'EXTREME' },
};

const RIBBON_CFG = {
  RIBBON_CONFIRMED:    { color: '#00ff88', label: '✓ CONFIRMED'    },
  RIBBON_CONSTRUCTIVE: { color: '#00e5ff', label: '◉ CONSTRUCTIVE' },
  RIBBON_EARLY:        { color: '#ffd600', label: '◑ EARLY'        },
  RIBBON_WEAK:         { color: '#888',    label: '◌ WEAK'         },
  RIBBON_NONE:         { color: '#444',    label: '─ NONE'         },
};

const TIER_COLORS = {
  FIRE: '#ffd700', ARM: '#00e5ff', BASE: '#00c853',
  STEALTH: '#cc44ff', WATCH: '#ff8800', SKIP: '#666',
};

const MODE_TABS = [
  { key: 'active',      label: '🚀 Active',      desc: 'PUMP_ACTIVE only'                 },
  { key: 'building',    label: '📈 Building',     desc: 'active + building'                },
  { key: 'early',       label: '⚡ Early',         desc: 'active + building + early'        },
  { key: 'speculative', label: '🔍 Speculative',  desc: 'all signals incl. speculative'    },
  { key: 'all',         label: '─ All',           desc: 'all including no signal'          },
];

const VOL_OPTIONS = [
  { label: '100K', value: 100000  },
  { label: '200K', value: 200000  },
  { label: '500K', value: 500000  },
  { label: '1M',   value: 1000000 },
];
const QUALITY_OPTIONS = [
  { label: 'Any', value: 0  },
  { label: '20+', value: 20 },
  { label: '40+', value: 40 },
  { label: '60+', value: 60 },
];
const TOXICITY_OPTIONS = [
  { label: 'All',      value: 100 },
  { label: 'No Ext',   value: 69  },
  { label: 'Low only', value: 19  },
];

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n, d = 2) { return n == null ? '—' : Number(n).toFixed(d); }
function fmtVol(n) {
  if (!n) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}

// ── Sub-components ────────────────────────────────────────────────────────────

function QualityBar({ value, max = 100 }) {
  const pct   = Math.min(100, Math.max(0, value || 0));
  const color = pct >= 60 ? '#ff4400'
              : pct >= 40 ? '#ff8800'
              : pct >= 20 ? '#ffd600'
              : '#555';
  return (
    <div className={styles.qualityRow}>
      <span className={styles.qualityLabel}>Pump Quality</span>
      <div className={styles.qualityTrack}>
        <div className={styles.qualityFill} style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className={styles.qualityScore} style={{ color }}>{value}/{max}</span>
    </div>
  );
}

function ToxicityBadge({ level, score, flags }) {
  const cfg = TOXICITY_CFG[level] || TOXICITY_CFG.LOW;
  const [showFlags, setShowFlags] = useState(false);
  return (
    <span
      className={styles.toxicBadge}
      style={{ borderColor: `${cfg.color}66`, color: cfg.color }}
      title={flags?.join(', ')}
      onClick={() => setShowFlags(v => !v)}
    >
      ☣ {cfg.label} {score}
    </span>
  );
}

function RibbonBadge({ ribbonClass }) {
  const cfg = RIBBON_CFG[ribbonClass] || RIBBON_CFG.RIBBON_NONE;
  return (
    <span className={styles.ribbonBadge} style={{ color: cfg.color, borderColor: `${cfg.color}55` }}>
      {cfg.label}
    </span>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

function PumpCard({ ticker }) {
  const [expanded, setExpanded] = useState(false);

  const sig       = PUMP_SIGNAL_CFG[ticker.pump_signal]  || PUMP_SIGNAL_CFG.NO_PUMP_SIGNAL;
  const tierColor = TIER_COLORS[ticker.tier]             || '#888';
  const toxCfg    = TOXICITY_CFG[ticker.toxicity_level]  || TOXICITY_CFG.LOW;
  const ribCfg    = RIBBON_CFG[ticker.ribbon_class]      || RIBBON_CFG.RIBBON_NONE;

  const chgColor = (ticker.price_change_pct || 0) > 0 ? '#00c864'
                 : (ticker.price_change_pct || 0) < 0 ? '#ff4444' : '#888';
  const anomalyColor = (ticker.anomaly_ratio || 0) >= 3
    ? '#ff4400' : (ticker.anomaly_ratio || 0) >= 1.5 ? '#ff8800' : '#888';

  return (
    <div className={styles.card} data-signal={ticker.pump_signal}>

      {/* ── ROW 1: Header ── */}
      <div className={styles.cardHeader}>
        <div className={styles.symbolBlock}>
          <span className={styles.symbol}>{ticker.symbol}</span>
          <span className={styles.price}>${fmt(ticker.price)}</span>
          {ticker.sector && <span className={styles.sectorTag}>{ticker.sector}</span>}
        </div>
        <div className={styles.badgesBlock}>
          {ticker.tier && (
            <span className={styles.tierBadge} style={{ borderColor: tierColor, color: tierColor }}>
              {ticker.tier}
            </span>
          )}
          <span
            className={styles.pumpBadge}
            style={{ background: sig.bg, color: sig.color, borderColor: sig.color }}
          >
            {sig.label}
          </span>
        </div>
      </div>

      {/* ── ROW 2: Quality bar ── */}
      <QualityBar value={ticker.pump_quality || 0} />

      {/* ── ROW 3: Reason ── */}
      {ticker.pump_reason && (
        <div className={styles.reason}>{ticker.pump_reason}</div>
      )}

      {/* ── ROW 4: Key metrics ── */}
      <div className={styles.metrics}>
        <span className={styles.metric}>
          <span className={styles.metricLabel}>1d</span>
          <span className={styles.metricVal} style={{ color: chgColor }}>
            {(ticker.price_change_pct || 0) > 0 ? '+' : ''}{fmt(ticker.price_change_pct, 1)}%
          </span>
        </span>
        <span className={styles.metric}>
          <span className={styles.metricLabel}>Vol</span>
          <span className={styles.metricVal} style={{ color: anomalyColor }}>
            {fmt(ticker.anomaly_ratio, 1)}x
          </span>
        </span>
        <span className={styles.metric}>
          <span className={styles.metricLabel}>Today</span>
          <span className={styles.metricVal}>{fmtVol(ticker.today_vol)}</span>
        </span>
        <RibbonBadge ribbonClass={ticker.ribbon_class} />
        <ToxicityBadge
          level={ticker.toxicity_level}
          score={ticker.toxicity_score}
          flags={ticker.toxicity_flags}
        />
      </div>

      {/* ── ROW 5: Expand: confirmations / warnings / flags ── */}
      {((ticker.pump_confirmations?.length > 0) || (ticker.pump_warnings?.length > 0)) && (
        <button className={styles.expandBtn} onClick={() => setExpanded(v => !v)}>
          {expanded ? '▲ Hide details' : '▼ Details'}
        </button>
      )}

      {expanded && (
        <div className={styles.details}>
          {ticker.pump_confirmations?.length > 0 && (
            <div className={styles.confirmList}>
              {ticker.pump_confirmations.map((c, i) => (
                <div key={i} className={styles.confirmItem}>✅ {c}</div>
              ))}
            </div>
          )}
          {ticker.pump_warnings?.length > 0 && (
            <div className={styles.warnList}>
              {ticker.pump_warnings.map((w, i) => (
                <div key={i} className={styles.warnItem}>⚠️ {w}</div>
              ))}
            </div>
          )}
          {ticker.toxicity_flags?.length > 0 && (
            <div className={styles.toxicFlags}>
              {ticker.toxicity_flags.map((f, i) => (
                <span key={i} className={styles.toxicFlag}>☣ {f}</span>
              ))}
            </div>
          )}
          {ticker.pump_bucket && (
            <div className={styles.bucketNote}>
              Bucket: <strong>{ticker.pump_bucket.replace(/_/g, ' ')}</strong>
              {ticker.source && (
                <span className={styles.sourceNote}> · {ticker.source === 'ribbon_pass' ? 'Ribbon' : 'Main scan'}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PumpEnginePage() {
  const [data,        setData]        = useState(null);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState(null);
  const [mode,        setMode]        = useState('building');
  const [minVolume,   setMinVolume]   = useState(200000);
  const [maxToxicity, setMaxToxicity] = useState(80);
  const [minQuality,  setMinQuality]  = useState(0);
  const [bullishOnly, setBullishOnly] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        mode,
        min_volume:   minVolume,
        max_toxicity: maxToxicity,
        min_quality:  minQuality,
        bullish_only: bullishOnly,
        max_results:  150,
      });
      const res = await fetch(`${API_URL}/api/scan/pump?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [mode, minVolume, maxToxicity, minQuality, bullishOnly]);

  useEffect(() => {
    setLoading(true);
    fetchData();
    const iv = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(iv);
  }, [fetchData]);

  const candidates = data?.candidates || [];
  const counts     = data?.counts     || {};
  const scanTime   = data?.scanned_at ? new Date(data.scanned_at).toLocaleTimeString() : null;
  const total      = data?.total      || 0;
  const scanned    = data?.scanned    || 0;

  return (
    <>
      <Head><title>🚀 Pump Engine — Pump Scout</title></Head>
      <div className={styles.page}>
        <AppNav />

        {/* ── Header ── */}
        <header className={styles.header}>
          <h1 className={styles.title}>🚀 Pump Engine</h1>
          <p className={styles.subtitle}>
            Velocity · Volume · Behavior · Theme · Toxicity
          </p>
          <p className={styles.disclaimer}>
            Analytical engine only — additive layer, never modifies main scanner tiers or scores.
          </p>
          {scanTime && <div className={styles.scanTime}>Scan data: {scanTime}</div>}
        </header>

        {/* ── Summary bar ── */}
        {(total > 0 || scanned > 0) && (
          <div className={styles.summaryBar}>
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum}>{scanned}</span>
              <span className={styles.summaryLbl}>Scanned</span>
            </div>
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum}>{total}</span>
              <span className={styles.summaryLbl}>Scored</span>
            </div>
            <div className={styles.summaryDivider} />
            {counts.PUMP_ACTIVE > 0 && (
              <div className={styles.summaryItem}>
                <span className={styles.summaryNum} style={{ color: '#ff4400' }}>{counts.PUMP_ACTIVE}</span>
                <span className={styles.summaryLbl}>🚀 Active</span>
              </div>
            )}
            {counts.PUMP_BUILDING > 0 && (
              <div className={styles.summaryItem}>
                <span className={styles.summaryNum} style={{ color: '#ff8800' }}>{counts.PUMP_BUILDING}</span>
                <span className={styles.summaryLbl}>📈 Building</span>
              </div>
            )}
            {counts.PUMP_EARLY > 0 && (
              <div className={styles.summaryItem}>
                <span className={styles.summaryNum} style={{ color: '#ffd600' }}>{counts.PUMP_EARLY}</span>
                <span className={styles.summaryLbl}>⚡ Early</span>
              </div>
            )}
            {counts.PUMP_SPECULATIVE > 0 && (
              <div className={styles.summaryItem}>
                <span className={styles.summaryNum} style={{ color: '#cc44ff' }}>{counts.PUMP_SPECULATIVE}</span>
                <span className={styles.summaryLbl}>🔍 Speculative</span>
              </div>
            )}
            <div className={styles.summaryDivider} />
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum}>{candidates.length}</span>
              <span className={styles.summaryLbl}>Shown</span>
            </div>
          </div>
        )}

        {/* ── Mode tabs ── */}
        <div className={styles.tabs}>
          {MODE_TABS.map(t => (
            <button
              key={t.key}
              className={`${styles.tab} ${mode === t.key ? styles.tabActive : ''}`}
              onClick={() => setMode(t.key)}
              title={t.desc}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Filters ── */}
        <div className={styles.filters}>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Min Vol:</span>
            {VOL_OPTIONS.map(o => (
              <button
                key={o.value}
                className={`${styles.filterBtn} ${minVolume === o.value ? styles.filterBtnActive : ''}`}
                onClick={() => setMinVolume(o.value)}
              >{o.label}</button>
            ))}
          </div>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Quality:</span>
            {QUALITY_OPTIONS.map(o => (
              <button
                key={o.value}
                className={`${styles.filterBtn} ${minQuality === o.value ? styles.filterBtnActive : ''}`}
                onClick={() => setMinQuality(o.value)}
              >{o.label}</button>
            ))}
          </div>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Toxicity:</span>
            {TOXICITY_OPTIONS.map(o => (
              <button
                key={o.value}
                className={`${styles.filterBtn} ${maxToxicity === o.value ? styles.filterBtnActive : ''}`}
                onClick={() => setMaxToxicity(o.value)}
              >{o.label}</button>
            ))}
          </div>
          <div className={styles.filterGroup}>
            <label className={styles.checkLabel}>
              <input
                type="checkbox"
                checked={bullishOnly}
                onChange={e => setBullishOnly(e.target.checked)}
                className={styles.checkInput}
              />
              Bullish only
            </label>
          </div>
          <button className={styles.refreshBtn} onClick={fetchData}>⟳ Refresh</button>
        </div>

        {/* ── Content ── */}
        <div className={styles.content}>
          {loading && <div className={styles.statusMsg}>Loading pump engine data...</div>}
          {error   && <div className={styles.errorMsg}>Error: {error}</div>}
          {!loading && !error && candidates.length === 0 && (
            <div className={styles.emptyMsg}>
              <div className={styles.emptyIcon}>🚀</div>
              <div>No pump signals found</div>
              <div className={styles.emptyHint}>
                Try switching to "Speculative" or lowering the quality filter
              </div>
            </div>
          )}
          {!loading && candidates.length > 0 && (
            <>
              <div className={styles.resultsHeader}>
                {candidates.length} result{candidates.length !== 1 ? 's' : ''} · sorted by signal priority then quality
              </div>
              <div className={styles.grid}>
                {candidates.map(t => <PumpCard key={t.symbol} ticker={t} />)}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
