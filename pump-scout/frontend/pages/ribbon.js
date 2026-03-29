import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import styles from '../styles/Ribbon.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REFRESH_INTERVAL = 60 * 1000;

const TIER_COLORS = {
  FIRE: '#ffd700', ARM: '#00e5ff', BASE: '#00c853', STEALTH: '#cc44ff',
  SYMPATHY: '#00e5ff', WATCH: '#ff8800', SKIP: '#666',
};

const SIGNAL_CONFIG = {
  COMPRESSION_BREAKOUT: { label: '🚀 ПРОБОЙ',    color: '#ff8800', bg: 'rgba(255,136,0,0.15)' },
  COMPRESSION_ALIGNED:  { label: '⚡ ВЫРОВНЕН',  color: '#ffd600', bg: 'rgba(255,214,0,0.12)' },
  BULLISH_STACK:        { label: '📈 СТЕК',       color: '#00c864', bg: 'rgba(0,200,100,0.12)' },
  COMPRESSION_WATCH:    { label: '🔮 СЖАТИЕ',     color: '#cc44ff', bg: 'rgba(204,68,255,0.12)' },
  BEARISH_STACK:        { label: '⚠️ МЕДВЕЖИЙ',   color: '#ff4444', bg: 'rgba(255,68,68,0.12)' },
  NEUTRAL:              { label: '～ НЕЙТРАЛЬ',   color: '#888',    bg: 'rgba(128,128,128,0.08)' },
};

const EMA_COLORS = {
  8: '#00ff88', 13: '#22dd77', 21: '#44cc66',
  34: '#ffcc00', 55: '#ff8800', 89: '#ff4400', 200: '#cc0000',
};

const COMP_CONFIG = {
  STRONG: { label: '🔥 STRONG', color: '#ff4400' },
  MEDIUM: { label: '⚡ MEDIUM', color: '#ffcc00' },
  WEAK:   { label: '💡 WEAK',   color: '#4488ff' },
  NONE:   { label: '─ NONE',    color: '#555'    },
};

const MODE_TABS = [
  { key: 'all',         label: 'Все',            summaryKey: 'total' },
  { key: 'breakout',    label: '🚀 Пробой',       summaryKey: 'breakouts' },
  { key: 'stack',       label: '📈 Тренд',        summaryKey: 'stacks' },
  { key: 'compression', label: '🔮 Сжатие',       summaryKey: 'compression' },
];

const SPREAD_OPTIONS = [
  { label: '1%',  value: 1.0 },
  { label: '2.5%', value: 2.5 },
  { label: '5%',  value: 5.0 },
];

const VOL_OPTIONS = [
  { label: '200K', value: 200000 },
  { label: '500K', value: 500000 },
  { label: '1M',   value: 1000000 },
];

function slopeArrow(slope) {
  if (slope === 'RISING')  return <span style={{ color: '#00c864' }}>↑</span>;
  if (slope === 'FALLING') return <span style={{ color: '#ff4444' }}>↓</span>;
  return <span style={{ color: '#666' }}>→</span>;
}

function QualityBar({ value }) {
  const color = value >= 70 ? '#00c864' : value >= 40 ? '#ffd600' : '#ff4444';
  return (
    <div className={styles.qualityRow}>
      <span className={styles.qualityLabel}>Качество:</span>
      <div className={styles.qualityBarWrap}>
        <div className={styles.qualityBarFill} style={{ width: `${value}%`, background: color }} />
      </div>
      <span className={styles.qualityScore} style={{ color }}>{value}/100</span>
    </div>
  );
}

function RibbonVisual({ ticker }) {
  const emaValues = [
    { period: 8,   val: ticker.ema8   },
    { period: 13,  val: ticker.ema13  },
    { period: 21,  val: ticker.ema21  },
    { period: 34,  val: ticker.ema34  },
    { period: 50,  val: ticker.ema50  },
    { period: 55,  val: ticker.ema55  },
    { period: 89,  val: ticker.ema89  },
    { period: 200, val: ticker.ema200 },
  ].filter(e => e.val != null);

  const priceColor = ticker.bullish_stack ? '#00c864' : ticker.bearish_stack ? '#ff4444' : '#ccc';
  const comp = COMP_CONFIG[ticker.ribbon_compression] || COMP_CONFIG.NONE;

  return (
    <div className={styles.ribbonVisual}>
      {emaValues.map(({ period, val }) => {
        const color = EMA_COLORS[period] || '#aaa';
        return (
          <div key={period} className={styles.ribbonRow}>
            <span className={styles.ribbonPeriod} style={{ color }}>EMA{period}</span>
            <span className={styles.ribbonVal}  style={{ color }}>${val.toFixed(4)}</span>
            {period === 8 && <span className={styles.ribbonSlope}>{slopeArrow(ticker.ema8_slope)}</span>}
          </div>
        );
      })}
      <div className={styles.ribbonPriceRow}>
        <span className={styles.ribbonPeriod} style={{ color: priceColor, fontWeight: 800 }}>Цена</span>
        <span className={styles.ribbonVal} style={{ color: priceColor, fontWeight: 800 }}>${ticker.price?.toFixed(4)}</span>
      </div>
      <div className={styles.spreadRow}>
        <span className={styles.spreadLabel}>Spread: {ticker.ema_spread_pct?.toFixed(2)}%</span>
        <span style={{ color: comp.color, fontWeight: 700, fontSize: 10 }}>{comp.label}</span>
      </div>
    </div>
  );
}

function StackStatus({ ticker }) {
  if (ticker.compression_and_bullish) {
    return <div className={styles.stackStatus} style={{ color: '#ff8800' }}>🚀 Сжатие + alignment — готов к взрыву</div>;
  }
  if (ticker.bullish_stack) {
    return <div className={styles.stackStatus} style={{ color: '#00c864' }}>✅ Bullish alignment — цена выше всех EMA</div>;
  }
  if (ticker.bearish_stack) {
    return <div className={styles.stackStatus} style={{ color: '#ff4444' }}>❌ Bearish alignment — цена ниже всех EMA</div>;
  }
  return <div className={styles.stackStatus} style={{ color: '#888' }}>～ Mixed — нет чёткого направления</div>;
}

function Confirmations({ ticker }) {
  const items = [];

  // CMF
  if (ticker.cmf_pctl != null) {
    const icon = ticker.cmf_pctl > 70 ? '✅' : ticker.cmf_pctl > 50 ? '⚡' : '⚠️';
    const color = ticker.cmf_pctl > 70 ? '#00c864' : ticker.cmf_pctl > 50 ? '#ffd600' : '#ff8800';
    items.push({ key: 'cmf', icon, label: `CMF ${Math.round(ticker.cmf_pctl)}%ile`, color });
  }

  // Volume
  if (ticker.anomaly_ratio != null) {
    const icon = ticker.anomaly_ratio >= 3 ? '✅' : ticker.anomaly_ratio >= 1.8 ? '⚡' : '⚠️';
    const color = ticker.anomaly_ratio >= 3 ? '#00c864' : ticker.anomaly_ratio >= 1.8 ? '#ffd600' : '#ff8800';
    items.push({ key: 'vol', icon, label: `Vol ${ticker.anomaly_ratio.toFixed(1)}x`, color });
  }

  // BB Squeeze
  if (ticker.bb_squeeze) {
    const icon = ticker.bb_sqz_bars >= 5 ? '✅' : '⚡';
    items.push({ key: 'bb', icon, label: `BB Squeeze ${ticker.bb_sqz_bars}d`, color: '#cc44ff' });
  }

  // OBV
  if (ticker.obv_strength) {
    const map = { STRONG: ['✅', '#00c864'], MEDIUM: ['⚡', '#ffd600'], NEGATIVE: ['❌', '#ff4444'] };
    const [icon, color] = map[ticker.obv_strength] || ['⚡', '#888'];
    items.push({ key: 'obv', icon, label: `OBV ${ticker.obv_strength}`, color });
  }

  // RS vs SPY
  if (ticker.rs_score != null) {
    const sign = ticker.rs_score > 0 ? '+' : '';
    const icon = ticker.rs_score > 5 ? '✅' : ticker.rs_score > 0 ? '⚡' : '⚠️';
    const color = ticker.rs_score > 5 ? '#00c864' : ticker.rs_score > 0 ? '#ffd600' : '#ff8800';
    items.push({ key: 'rs', icon, label: `RS ${sign}${ticker.rs_score.toFixed(1)}%`, color });
  }

  // Earnings
  const earnColor = ticker.earnings_risk === 'HIGH' ? '#ff4444' : ticker.earnings_risk === 'MEDIUM' ? '#ff8800' : '#00c864';
  const earnIcon  = ticker.earnings_risk === 'HIGH' ? '🚨' : ticker.earnings_risk === 'MEDIUM' ? '⚠️' : '✅';
  const earnLabel = ticker.earnings_risk === 'HIGH' ? 'Earnings риск — HIGH'
    : ticker.earnings_risk === 'MEDIUM' ? 'Earnings риск — MEDIUM' : 'Earnings: нет риска';
  items.push({ key: 'earn', icon: earnIcon, label: earnLabel, color: earnColor });

  return (
    <div className={styles.confirmations}>
      {items.map(({ key, icon, label, color }) => (
        <span key={key} className={styles.confirmItem} style={{ color }}>
          {icon} {label}
        </span>
      ))}
    </div>
  );
}

function TickerCard({ ticker, apiUrl }) {
  const [aiOpen, setAiOpen] = useState(false);
  const sig = SIGNAL_CONFIG[ticker.ribbon_signal] || SIGNAL_CONFIG.NEUTRAL;
  const tierColor = TIER_COLORS[ticker.tier] || '#888';

  return (
    <div className={styles.card}>
      {/* ROW 1 — Header */}
      <div className={styles.cardHeader}>
        <div className={styles.symbolBlock}>
          <span className={styles.symbol}>{ticker.symbol}</span>
          <span className={styles.price}>${ticker.price?.toFixed(2)}</span>
        </div>
        <div className={styles.badgesBlock}>
          {ticker.tier && (
            <span className={styles.tierBadge} style={{ borderColor: tierColor, color: tierColor }}>
              {ticker.tier}
            </span>
          )}
          <span
            className={styles.signalBadge}
            style={{ background: sig.bg, color: sig.color, borderColor: sig.color }}
          >
            {sig.label}
          </span>
        </div>
      </div>

      {/* ROW 2 — Quality bar */}
      <QualityBar value={ticker.ribbon_quality} />

      {/* ROW 3 — EMA Ribbon visualization */}
      <RibbonVisual ticker={ticker} />

      {/* ROW 4 — Stack status */}
      <StackStatus ticker={ticker} />

      {/* ROW 5 — Confirmations */}
      <Confirmations ticker={ticker} />

      {/* ROW 6 — Context */}
      <div className={styles.context}>
        <span>Сектор: {ticker.sector || '—'}</span>
        <span>Ribbon: {ticker.ribbon_periods_count || '—'}/7 EMA</span>
        {ticker.ribbon_position != null && (
          <span>Позиция: {ticker.ribbon_position.toFixed(0)}%</span>
        )}
      </div>

      {/* ROW 7 — Actions */}
      <div className={styles.actions}>
        <a
          href={`/journal?add=${ticker.symbol}&price=${ticker.price}`}
          className={styles.journalBtn}
        >
          + Journal
        </a>
        {ticker.ai_analysis && (
          <button className={styles.aiBtn} onClick={() => setAiOpen(v => !v)}>
            AI Анализ {aiOpen ? '▲' : '▼'}
          </button>
        )}
      </div>

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

export default function RibbonPage() {
  const [data, setData]             = useState(null);
  const [loading, setLoading]       = useState(true);
  const [error, setError]           = useState(null);
  const [mode, setMode]             = useState('all');
  const [maxSpread, setMaxSpread]   = useState(5.0);
  const [minVol, setMinVol]         = useState(200000);
  const [bullishOnly, setBullishOnly] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        mode,
        max_spread: maxSpread,
        min_volume: minVol,
        bullish_only: bullishOnly,
      });
      const res = await fetch(`${API_URL}/api/scan/ribbon?${params}`);
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const json = await res.json();
      setData(json);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [mode, maxSpread, minVol, bullishOnly]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(interval);
  }, [fetchData]);

  const summary = data?.summary || {};
  const results = data?.results || [];

  const scannedAt = data?.scanned_at
    ? new Date(data.scanned_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
    : null;

  return (
    <>
      <Head>
        <title>EMA Ribbon Scanner — Pump Scout</title>
        <meta name="robots" content="noindex" />
      </Head>

      <div className={styles.page}>
        {/* Nav */}
        <div className={styles.nav}>
          <Link href="/" className={styles.navLink}>← Dashboard</Link>
          <Link href="/journal" className={styles.navLink}>📔 Journal</Link>
          <Link href="/sectors" className={styles.navLink}>🗂 Sectors</Link>
        </div>

        {/* Header */}
        <div className={styles.header}>
          <h1 className={styles.title}>🎀 EMA Ribbon Scanner</h1>
          <p className={styles.subtitle}>Fibonacci: 8 · 13 · 21 · 34 · 55 · 89 · 200</p>
          {scannedAt && <span className={styles.scanTime}>Последний скан: {scannedAt}</span>}
        </div>

        {/* Summary bar */}
        <div className={styles.summaryBar}>
          <div className={styles.summaryItem}>
            <span className={styles.summaryIcon}>🚀</span>
            <span className={styles.summaryNum}>{summary.breakouts ?? 0}</span>
            <span className={styles.summaryLabel}>Пробои</span>
          </div>
          <div className={styles.summaryItem}>
            <span className={styles.summaryIcon}>📈</span>
            <span className={styles.summaryNum}>{summary.stacks ?? 0}</span>
            <span className={styles.summaryLabel}>Тренды</span>
          </div>
          <div className={styles.summaryItem}>
            <span className={styles.summaryIcon}>🔮</span>
            <span className={styles.summaryNum}>{summary.compression ?? 0}</span>
            <span className={styles.summaryLabel}>Сжатия</span>
          </div>
          <div className={styles.summaryItem}>
            <span className={styles.summaryIcon}>⚠️</span>
            <span className={styles.summaryNum}>{summary.bearish ?? 0}</span>
            <span className={styles.summaryLabel}>Медвежьи</span>
          </div>
        </div>

        {/* Mode tabs */}
        <div className={styles.tabs}>
          {MODE_TABS.map(tab => (
            <button
              key={tab.key}
              className={`${styles.tab} ${mode === tab.key ? styles.tabActive : ''}`}
              onClick={() => setMode(tab.key)}
            >
              {tab.label}
              <span className={styles.tabCount}>
                {summary[tab.summaryKey] ?? 0}
              </span>
            </button>
          ))}
        </div>

        {/* Filters */}
        <div className={styles.filters}>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Spread max:</span>
            {SPREAD_OPTIONS.map(o => (
              <button
                key={o.value}
                className={`${styles.filterBtn} ${maxSpread === o.value ? styles.filterBtnActive : ''}`}
                onClick={() => setMaxSpread(o.value)}
              >
                {o.label}
              </button>
            ))}
          </div>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Объём min:</span>
            {VOL_OPTIONS.map(o => (
              <button
                key={o.value}
                className={`${styles.filterBtn} ${minVol === o.value ? styles.filterBtnActive : ''}`}
                onClick={() => setMinVol(o.value)}
              >
                {o.label}
              </button>
            ))}
          </div>
          <div className={styles.filterGroup}>
            <button
              className={`${styles.filterBtn} ${bullishOnly ? styles.filterBtnActive : ''}`}
              onClick={() => setBullishOnly(v => !v)}
            >
              {bullishOnly ? '✓ ' : ''}Только бычьи
            </button>
          </div>
        </div>

        {/* Content */}
        {loading && <div className={styles.loading}>Загрузка...</div>}
        {error && <div className={styles.error}>Ошибка: {error}</div>}

        {!loading && !error && results.length === 0 && (
          <div className={styles.empty}>
            <div className={styles.emptyIcon}>🎀</div>
            <div className={styles.emptyTitle}>
              Нет тикеров с EMA ribbon «{mode}» при текущих фильтрах.
            </div>
            <div className={styles.emptyHint}>
              Попробуй увеличить Spread max или дождись следующего скана.
            </div>
          </div>
        )}

        {!loading && results.length > 0 && (
          <div className={styles.grid}>
            {results.map(ticker => (
              <TickerCard key={ticker.symbol} ticker={ticker} apiUrl={API_URL} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
