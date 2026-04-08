import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import styles from '../styles/Ignition.module.css';
import JournalModal from '../components/JournalModal';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REFRESH_INTERVAL = 60 * 1000;

const SIGNAL_CONFIG = {
  IGNITION_CONFIRMED: { label: '🔥 CONFIRMED', color: '#ff8800', bg: 'rgba(255,136,0,0.15)' },
  EARLY_IGNITION:     { label: '⚡ EARLY',     color: '#ffd600', bg: 'rgba(255,214,0,0.12)' },
  IGNITION_WATCH:     { label: '🔍 WATCH',     color: '#cc44ff', bg: 'rgba(204,68,255,0.12)' },
  NO_IGNITION:        { label: '─ NONE',        color: '#555',    bg: 'rgba(80,80,80,0.08)'  },
};

const BUCKET_CONFIG = {
  RIBBON_LED: { label: '📐 Ribbon',   color: '#00e5ff' },
  PRICE_LED:  { label: '📈 Price',    color: '#00c864' },
  RS_LED:     { label: '🏅 RS',       color: '#ffd600' },
  VOLUME_LED: { label: '📊 Volume',   color: '#ff8800' },
  THEME_LED:  { label: '🌊 Theme',    color: '#cc44ff' },
  MIXED:      { label: '🔀 Mixed',    color: '#aaa'    },
  NONE:       { label: '─ None',      color: '#555'    },
};

const TIER_COLORS = {
  FIRE: '#ffd700', ARM: '#00e5ff', BASE: '#00c853',
  STEALTH: '#cc44ff', SYMPATHY: '#00e5ff', WATCH: '#ff8800', SKIP: '#666',
};

const MODE_TABS = [
  { key: 'watch',     label: '🔍 All Signals',  desc: 'confirmed + early + watch' },
  { key: 'confirmed', label: '🔥 Confirmed',     desc: 'IGNITION_CONFIRMED only'   },
  { key: 'early',     label: '⚡ Early',          desc: 'confirmed + early'          },
  { key: 'all',       label: '─ All',             desc: 'including no signal'        },
];

const VOL_OPTIONS = [
  { label: '200K', value: 200000 },
  { label: '500K', value: 500000 },
  { label: '1M',   value: 1000000 },
];

const QUALITY_OPTIONS = [
  { label: 'Any', value: 0  },
  { label: '20+', value: 20 },
  { label: '40+', value: 40 },
  { label: '60+', value: 60 },
];

function fmt(n, d = 2) {
  if (n == null) return '—';
  return Number(n).toFixed(d);
}

function slopeArrow(slope) {
  if (slope === 'RISING')  return <span style={{ color: '#00c864' }}>↑</span>;
  if (slope === 'FALLING') return <span style={{ color: '#ff4444' }}>↓</span>;
  return <span style={{ color: '#666' }}>→</span>;
}

function QualityBar({ value }) {
  const pct = Math.min(100, Math.max(0, value || 0));
  const color = pct >= 60 ? '#ff8800' : pct >= 40 ? '#ffd600' : pct >= 22 ? '#cc44ff' : '#555';
  return (
    <div className={styles.qualityRow}>
      <span className={styles.qualityLabel}>Quality</span>
      <div className={styles.qualityTrack}>
        <div className={styles.qualityFill} style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className={styles.qualityScore} style={{ color }}>{pct}/100</span>
    </div>
  );
}

function MetricChip({ label, value, color }) {
  return (
    <span className={styles.metricChip} style={{ '--chip-color': color || '#666' }}>
      <span className={styles.metricLabel}>{label}</span>
      <span className={styles.metricValue} style={{ color: color || '#ccc' }}>{value}</span>
    </span>
  );
}

function IgnitionCard({ ticker, apiUrl }) {
  const [aiOpen, setAiOpen]       = useState(false);
  const [showJournal, setShowJournal] = useState(false);

  const sig    = SIGNAL_CONFIG[ticker.ignition_signal] || SIGNAL_CONFIG.NO_IGNITION;
  const bucket = BUCKET_CONFIG[ticker.ignition_bucket] || BUCKET_CONFIG.NONE;
  const tierColor = TIER_COLORS[ticker.tier] || '#888';

  // Derived display values
  const anomalyColor = ticker.anomaly_ratio >= 1.8 ? '#ff8800'
    : ticker.anomaly_ratio >= 1.2 ? '#ffd600'
    : ticker.anomaly_ratio >= 0.8 ? '#cc44ff' : '#555';

  const cmfColor = ticker.cmf_pctl >= 70 ? '#00c864'
    : ticker.cmf_pctl >= 50 ? '#ffd600'
    : ticker.cmf_pctl >= 25 ? '#ff8800' : '#ff4444';

  const obvColor = ticker.obv_strength === 'STRONG' ? '#00c864'
    : ticker.obv_strength === 'MEDIUM' ? '#ffd600'
    : ticker.obv_strength === 'NEGATIVE' ? '#ff4444' : '#888';

  const rsColor = ticker.rs_score > 5 ? '#00c864'
    : ticker.rs_score > 0 ? '#ffd600'
    : ticker.rs_score < -5 ? '#ff4444' : '#888';

  const rsLabel = ticker.rs_score != null
    ? `${ticker.rs_score > 0 ? '+' : ''}${fmt(ticker.rs_score, 1)}%` : '—';

  const spreadColor = ticker.ema_spread_pct < 1.5 ? '#ff8800'
    : ticker.ema_spread_pct < 3 ? '#ffd600' : '#888';

  const journalPrefill = {
    symbol:            ticker.symbol,
    entry_price:       ticker.price,
    tier:              ticker.tier || undefined,
    entry_cmf_pctl:    ticker.cmf_pctl || undefined,
    entry_vol_ratio:   ticker.anomaly_ratio || undefined,
    notes: `Ignition: ${ticker.ignition_signal} | ${ticker.ignition_bucket} | Q:${ticker.ignition_quality} | ${ticker.ignition_reason || ''}`,
  };

  return (
    <div className={styles.card} data-signal={ticker.ignition_signal}>
      {/* ROW 1 — Header */}
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
          {ticker.total_score != null && (
            <span className={styles.scoreBadge}>{fmt(ticker.total_score, 0)}</span>
          )}
          <span
            className={styles.signalBadge}
            style={{ background: sig.bg, color: sig.color, borderColor: sig.color }}
          >
            {sig.label}
          </span>
          <span
            className={styles.bucketBadge}
            style={{ color: bucket.color, borderColor: `${bucket.color}44` }}
          >
            {bucket.label}
          </span>
        </div>
      </div>

      {/* ROW 2 — Quality bar */}
      <QualityBar value={ticker.ignition_quality} />

      {/* ROW 3 — Reason */}
      {ticker.ignition_reason && (
        <div className={styles.reason}>{ticker.ignition_reason}</div>
      )}

      {/* ROW 4 — Key metrics */}
      <div className={styles.metrics}>
        <MetricChip label="Vol" value={`${fmt(ticker.anomaly_ratio, 1)}x`} color={anomalyColor} />
        <MetricChip label="CMF" value={ticker.cmf_pctl != null ? `${Math.round(ticker.cmf_pctl)}%ile` : '—'} color={cmfColor} />
        <MetricChip label="OBV" value={ticker.obv_strength || '—'} color={obvColor} />
        <MetricChip label="RS"  value={rsLabel} color={rsColor} />
        <MetricChip
          label="Ribbon"
          value={ticker.ribbon_compression || 'NONE'}
          color={ticker.ribbon_compression === 'STRONG' ? '#ff4400' : ticker.ribbon_compression === 'MEDIUM' ? '#ffd600' : '#555'}
        />
        <MetricChip label="Slope" value={<>{slopeArrow(ticker.ema8_slope)} {ticker.ema8_slope || '?'}</>} color="#aaa" />
        {ticker.ema_spread_pct != null && (
          <MetricChip label="Spread" value={`${fmt(ticker.ema_spread_pct, 1)}%`} color={spreadColor} />
        )}
        {ticker.bb_sqz_bars > 0 && (
          <MetricChip label="BB Sqz" value={`${ticker.bb_sqz_bars}d`} color="#cc44ff" />
        )}
      </div>

      {/* ROW 5a — Confirmations */}
      {ticker.ignition_confirmations?.length > 0 && (
        <div className={styles.confirmList}>
          {ticker.ignition_confirmations.map((c, i) => (
            <div key={i} className={styles.confirmItem}>✅ {c}</div>
          ))}
        </div>
      )}

      {/* ROW 5b — Warnings */}
      {ticker.ignition_warnings?.length > 0 && (
        <div className={styles.warnList}>
          {ticker.ignition_warnings.map((w, i) => (
            <div key={i} className={styles.warnItem}>⚠️ {w}</div>
          ))}
        </div>
      )}

      {/* ROW 6 — Context + actions */}
      <div className={styles.footer}>
        <div className={styles.footerLeft}>
          <span className={styles.sourceBadge}>
            {ticker.source === 'ribbon_pass' ? '🔍 Ribbon' : '📊 Main scan'}
          </span>
          {ticker.earnings_risk && ticker.earnings_risk !== 'NONE' && (
            <span className={styles.earningsBadge} data-risk={ticker.earnings_risk}>
              {ticker.earnings_risk === 'HIGH' ? '🚨' : '⚠️'} Earnings {ticker.earnings_risk}
            </span>
          )}
        </div>
        <div className={styles.footerRight}>
          <button className={styles.journalBtn} onClick={() => setShowJournal(true)}>
            + Journal
          </button>
          {ticker.ai_analysis && (
            <button className={styles.aiBtn} onClick={() => setAiOpen(v => !v)}>
              AI {aiOpen ? '▲' : '▼'}
            </button>
          )}
        </div>
      </div>

      {showJournal && (
        <JournalModal
          prefill={journalPrefill}
          onClose={() => setShowJournal(false)}
          onSaved={() => setShowJournal(false)}
        />
      )}

      {aiOpen && ticker.ai_analysis && (
        <div className={styles.aiPanel}>
          {typeof ticker.ai_analysis === 'string'
            ? ticker.ai_analysis
            : ticker.ai_analysis.summary || JSON.stringify(ticker.ai_analysis, null, 2)}
        </div>
      )}
    </div>
  );
}

export default function IgnitionPage() {
  const [data,       setData]       = useState(null);
  const [loading,    setLoading]    = useState(true);
  const [error,      setError]      = useState(null);
  const [mode,       setMode]       = useState('watch');
  const [minVolume,  setMinVolume]  = useState(200000);
  const [minQuality, setMinQuality] = useState(0);
  const [bullishOnly, setBullishOnly] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        mode,
        min_volume:  minVolume,
        min_quality: minQuality,
        bullish_only: bullishOnly,
        max_results: 150,
      });
      const res = await fetch(`${API_URL}/api/scan/ignition?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [mode, minVolume, minQuality, bullishOnly]);

  useEffect(() => {
    setLoading(true);
    fetchData();
    const iv = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(iv);
  }, [fetchData]);

  const summary  = data?.summary  || {};
  const results  = data?.results  || [];
  const scanTime = data?.scanned_at
    ? new Date(data.scanned_at).toLocaleTimeString()
    : null;

  return (
    <>
      <Head>
        <title>⚡ Early Ignition — Pump Scout</title>
      </Head>
      <div className={styles.page}>
        {/* ── Nav ── */}
        <nav className={styles.nav}>
          <Link href="/" className={styles.navLink}>Dashboard</Link>
          <Link href="/ribbon" className={styles.navLink}>Ribbon</Link>
          <Link href="/ignition" className={`${styles.navLink} ${styles.navLinkActive}`}>⚡ Ignition</Link>
          <Link href="/sectors" className={styles.navLink}>Sectors</Link>
          <Link href="/journal" className={styles.navLink}>Journal</Link>
          <Link href="/admin" className={styles.navLink}>Admin</Link>
        </nav>

        {/* ── Header ── */}
        <header className={styles.header}>
          <h1 className={styles.title}>⚡ Early Ignition</h1>
          <p className={styles.subtitle}>Early strength before full breakout confirmation</p>
          {scanTime && <div className={styles.scanTime}>Scan data: {scanTime}</div>}
        </header>

        {/* ── Summary bar ── */}
        {summary.total > 0 && (
          <div className={styles.summaryBar}>
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum}>{summary.total}</span>
              <span className={styles.summaryLbl}>Total</span>
            </div>
            <div className={styles.summaryItem} style={{ '--accent': '#ff8800' }}>
              <span className={styles.summaryNum} style={{ color: '#ff8800' }}>{summary.confirmed}</span>
              <span className={styles.summaryLbl}>🔥 Confirmed</span>
            </div>
            <div className={styles.summaryItem} style={{ '--accent': '#ffd600' }}>
              <span className={styles.summaryNum} style={{ color: '#ffd600' }}>{summary.early}</span>
              <span className={styles.summaryLbl}>⚡ Early</span>
            </div>
            <div className={styles.summaryItem} style={{ '--accent': '#cc44ff' }}>
              <span className={styles.summaryNum} style={{ color: '#cc44ff' }}>{summary.watch}</span>
              <span className={styles.summaryLbl}>🔍 Watch</span>
            </div>
            <div className={styles.summaryDivider} />
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum}>{summary.from_main}</span>
              <span className={styles.summaryLbl}>Main scan</span>
            </div>
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum}>{summary.from_ribbon}</span>
              <span className={styles.summaryLbl}>Ribbon pass</span>
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
              >
                {o.label}
              </button>
            ))}
          </div>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Quality:</span>
            {QUALITY_OPTIONS.map(o => (
              <button
                key={o.value}
                className={`${styles.filterBtn} ${minQuality === o.value ? styles.filterBtnActive : ''}`}
                onClick={() => setMinQuality(o.value)}
              >
                {o.label}
              </button>
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
          {loading && <div className={styles.statusMsg}>Loading ignition data...</div>}
          {error   && <div className={styles.errorMsg}>Error: {error}</div>}

          {!loading && !error && results.length === 0 && (
            <div className={styles.emptyMsg}>
              <div className={styles.emptyIcon}>⚡</div>
              <div>No ignition signals found</div>
              <div className={styles.emptyHint}>
                Try switching to "All Signals" or lowering quality filter
              </div>
            </div>
          )}

          {!loading && results.length > 0 && (
            <>
              <div className={styles.resultsHeader}>
                {results.length} signal{results.length !== 1 ? 's' : ''} · sorted by ignition quality
              </div>
              <div className={styles.grid}>
                {results.map(t => (
                  <IgnitionCard key={t.symbol} ticker={t} apiUrl={API_URL} />
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
