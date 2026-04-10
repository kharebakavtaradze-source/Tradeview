import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import styles from '../styles/Ignition.module.css';
import AppNav from '../components/AppNav';
import JournalModal from '../components/JournalModal';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REFRESH_INTERVAL = 60 * 1000;

// ── Config maps ───────────────────────────────────────────────────────────────

const SIGNAL_CFG = {
  IGNITION_CONFIRMED: { label: '🔥 CONFIRMED', color: '#ff8800', bg: 'rgba(255,136,0,0.15)' },
  EARLY_IGNITION:     { label: '⚡ EARLY',     color: '#ffd600', bg: 'rgba(255,214,0,0.12)' },
  IGNITION_WATCH:     { label: '🔍 WATCH',     color: '#cc44ff', bg: 'rgba(204,68,255,0.12)' },
  NO_IGNITION:        { label: '─ NONE',        color: '#555',    bg: 'rgba(80,80,80,0.08)'  },
};

const UNIFIED_CFG = {
  STRONG_BUY: { label: '🚀 STRONG BUY', color: '#00ff88', bg: 'rgba(0,255,136,0.15)' },
  BUY:        { label: '✅ BUY',         color: '#00c864', bg: 'rgba(0,200,100,0.12)' },
  WATCH:      { label: '🔍 WATCH',       color: '#ffd600', bg: 'rgba(255,214,0,0.12)' },
  NEUTRAL:    { label: '─ NEUTRAL',      color: '#888',    bg: 'rgba(128,128,128,0.1)' },
  AVOID:      { label: '🚫 AVOID',       color: '#ff4444', bg: 'rgba(255,68,68,0.1)'  },
};

const BUCKET_CFG = {
  RIBBON_LED: { label: '📐 Ribbon',  color: '#00e5ff' },
  PRICE_LED:  { label: '📈 Price',   color: '#00c864' },
  RS_LED:     { label: '🏅 RS',      color: '#ffd600' },
  VOLUME_LED: { label: '📊 Volume',  color: '#ff8800' },
  THEME_LED:  { label: '🌊 Theme',   color: '#cc44ff' },
  MIXED:      { label: '🔀 Mixed',   color: '#aaa'    },
  NONE:       { label: '─ None',     color: '#555'    },
};

const SECTOR_CLASS_CFG = {
  A: { label: 'A', color: '#00c864' }, B: { label: 'B', color: '#7ec850' },
  C: { label: 'C', color: '#888' },    D: { label: 'D', color: '#ff8800' },
  F: { label: 'F', color: '#ff4444' },
};

const HYPE_TIER_CFG = {
  VIRAL: { label: '🔥 VIRAL', color: '#ff4400' },
  HOT:   { label: '♨️ HOT',   color: '#ff8800' },
  WARM:  { label: '🌤 WARM',  color: '#ffd600' },
  COLD:  { label: '❄️ COLD',  color: '#555'    },
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

const VOL_OPTIONS     = [{ label:'200K', value:200000 }, { label:'500K', value:500000 }, { label:'1M', value:1000000 }];
const QUALITY_OPTIONS = [{ label:'Any', value:0 }, { label:'20+', value:20 }, { label:'40+', value:40 }, { label:'60+', value:60 }];

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n, d = 2) { return n == null ? '—' : Number(n).toFixed(d); }

function slopeArrow(slope) {
  if (slope === 'RISING')  return <span style={{ color:'#00c864' }}>↑</span>;
  if (slope === 'FALLING') return <span style={{ color:'#ff4444' }}>↓</span>;
  return <span style={{ color:'#666' }}>→</span>;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function ScoreBar({ label, value, max, color }) {
  const pct = Math.min(100, Math.max(0, Math.round((value / max) * 100)));
  return (
    <div className={styles.scoreBarRow}>
      <span className={styles.scoreBarLabel}>{label}</span>
      <div className={styles.scoreBarTrack}>
        <div className={styles.scoreBarFill} style={{ width:`${pct}%`, background: color }} />
      </div>
      <span className={styles.scoreBarVal} style={{ color }}>{value}<span style={{ opacity:0.5 }}>/{max}</span></span>
    </div>
  );
}

function QualityBar({ label, value, max = 100 }) {
  const pct   = Math.min(100, Math.max(0, value || 0));
  const color = pct >= 60 ? '#ff8800' : pct >= 40 ? '#ffd600' : pct >= 22 ? '#cc44ff' : '#555';
  return (
    <div className={styles.qualityRow}>
      <span className={styles.qualityLabel}>{label || 'Quality'}</span>
      <div className={styles.qualityTrack}>
        <div className={styles.qualityFill} style={{ width:`${pct}%`, background: color }} />
      </div>
      <span className={styles.qualityScore} style={{ color }}>{value}/{max}</span>
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

function ContextRow({ icon, label, value, sub, color }) {
  return (
    <div className={styles.ctxRow}>
      <span className={styles.ctxIcon}>{icon}</span>
      <span className={styles.ctxLabel}>{label}</span>
      <span className={styles.ctxValue} style={{ color: color || '#ccc' }}>{value}</span>
      {sub && <span className={styles.ctxSub}>{sub}</span>}
    </div>
  );
}

function AiSignalPanel({ ai }) {
  if (!ai) return null;
  const cfg = UNIFIED_CFG[ai.signal] || UNIFIED_CFG.NEUTRAL;
  return (
    <div className={styles.aiSignalPanel}>
      <div className={styles.aiSignalHeader}>
        <span className={styles.aiSignalBadge} style={{ background: cfg.bg, color: cfg.color, borderColor: cfg.color }}>
          🤖 {cfg.label}
        </span>
        <span className={styles.aiConfidence}>{ai.confidence}% conf.</span>
        {ai.catalyst_type && (
          <span className={styles.aiCatalyst}>{ai.catalyst_type.replace(/_/g, ' ')}</span>
        )}
      </div>
      {ai.entry_thesis && <div className={styles.aiThesis}>💡 {ai.entry_thesis}</div>}
      {ai.key_risk     && <div className={styles.aiRisk}>⚠️ {ai.key_risk}</div>}
    </div>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

function IgnitionCard({ ticker }) {
  const [expanded,   setExpanded]   = useState(false);
  const [showJournal, setShowJournal] = useState(false);

  const sig       = SIGNAL_CFG[ticker.ignition_signal]  || SIGNAL_CFG.NO_IGNITION;
  const uni       = UNIFIED_CFG[ticker.unified_signal]  || UNIFIED_CFG.NEUTRAL;
  const bucket    = BUCKET_CFG[ticker.ignition_bucket]  || BUCKET_CFG.NONE;
  const tierColor = TIER_COLORS[ticker.tier]            || '#888';

  const sc  = ticker.sector_context  || {};
  const hc  = ticker.hype_context    || {};
  const mc  = ticker.macro_context   || {};
  const ai  = ticker.ai_signal;

  const scCls   = SECTOR_CLASS_CFG[sc.sector_class] || SECTOR_CLASS_CFG.C;
  const hypeTier = HYPE_TIER_CFG[hc.hype_tier]     || HYPE_TIER_CFG.COLD;

  const anomalyColor = ticker.anomaly_ratio >= 1.8 ? '#ff8800' : ticker.anomaly_ratio >= 1.2 ? '#ffd600' : '#888';
  const cmfColor     = ticker.cmf_pctl >= 70 ? '#00c864' : ticker.cmf_pctl >= 50 ? '#ffd600' : '#ff4444';
  const rsColor      = ticker.rs_score > 5 ? '#00c864' : ticker.rs_score > 0 ? '#ffd600' : ticker.rs_score < -5 ? '#ff4444' : '#888';
  const macroColor   = mc.market_bias === 'BULLISH' ? '#00c864' : mc.market_bias === 'BEARISH' ? '#ff4444' : mc.market_bias === 'RISK_OFF' ? '#ff8800' : '#888';
  const sectorImpactColor = mc.sector_impact === 'BULLISH' ? '#00c864' : mc.sector_impact === 'BEARISH' ? '#ff4444' : '#888';

  const journalPrefill = {
    symbol:          ticker.symbol,
    entry_price:     ticker.price,
    tier:            ticker.tier || undefined,
    entry_cmf_pctl:  ticker.cmf_pctl || undefined,
    entry_vol_ratio: ticker.anomaly_ratio || undefined,
    notes: `Unified: ${ticker.unified_signal} (${ticker.unified_score}) | Ignition: ${ticker.ignition_signal} Q:${ticker.ignition_quality} | ${ticker.ignition_reason || ''}`,
  };

  return (
    <div className={styles.card} data-signal={ticker.ignition_signal} data-unified={ticker.unified_signal}>

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
          {/* Unified signal — primary badge */}
          <span className={styles.unifiedBadge} style={{ background: uni.bg, color: uni.color, borderColor: uni.color }}>
            {uni.label}
          </span>
          {/* Ignition signal */}
          <span className={styles.signalBadge} style={{ background: sig.bg, color: sig.color, borderColor: sig.color }}>
            {sig.label}
          </span>
          <span className={styles.bucketBadge} style={{ color: bucket.color, borderColor: `${bucket.color}44` }}>
            {bucket.label}
          </span>
        </div>
      </div>

      {/* ── ROW 2: Unified score bar ── */}
      <QualityBar label="Unified" value={ticker.unified_score || 0} max={100} />

      {/* ── ROW 3: Score breakdown (collapsible) ── */}
      <button className={styles.expandBtn} onClick={() => setExpanded(v => !v)}>
        {expanded ? '▲ Score breakdown' : '▼ Score breakdown'}
      </button>

      {expanded && (
        <div className={styles.scoreBreakdown}>
          <ScoreBar label="Ribbon"   value={ticker.ribbon_score   || 0} max={35} color="#00e5ff" />
          <ScoreBar label="Ignition" value={ticker.ignition_score || 0} max={25} color="#ff8800" />
          <ScoreBar label="Sector"   value={ticker.sector_score   || 0} max={15} color="#00c864" />
          <ScoreBar label="Hype"     value={ticker.hype_score_pts || 0} max={15} color="#cc44ff" />
          <ScoreBar label="Macro"    value={ticker.macro_score    || 0} max={10} color="#ffd600" />
          {ticker.score_factors?.length > 0 && (
            <div className={styles.factorTags}>
              {ticker.score_factors.map((f, i) => <span key={i} className={styles.factorTag}>{f}</span>)}
            </div>
          )}
        </div>
      )}

      {/* ── ROW 4: Ignition quality ── */}
      <QualityBar label="Ignition" value={ticker.ignition_quality || 0} max={100} />

      {ticker.ignition_reason && <div className={styles.reason}>{ticker.ignition_reason}</div>}

      {/* ── ROW 5: Technical metrics ── */}
      <div className={styles.metrics}>
        <MetricChip label="Vol"    value={`${fmt(ticker.anomaly_ratio,1)}x`} color={anomalyColor} />
        <MetricChip label="CMF"    value={ticker.cmf_pctl != null ? `${Math.round(ticker.cmf_pctl)}%ile` : '—'} color={cmfColor} />
        <MetricChip label="OBV"    value={ticker.obv_strength || '—'} color={ticker.obv_strength === 'STRONG' ? '#00c864' : '#888'} />
        <MetricChip label="RS"     value={ticker.rs_score != null ? `${ticker.rs_score>0?'+':''}${fmt(ticker.rs_score,1)}%` : '—'} color={rsColor} />
        <MetricChip label="Ribbon" value={ticker.ribbon_compression || 'NONE'} color={ticker.ribbon_compression === 'STRONG' ? '#ff4400' : ticker.ribbon_compression === 'MEDIUM' ? '#ffd600' : '#555'} />
        <MetricChip label="Slope"  value={<>{slopeArrow(ticker.ema8_slope)} {ticker.ema8_slope || '?'}</>} color="#aaa" />
        {ticker.ema_spread_pct != null && (
          <MetricChip label="Spread" value={`${fmt(ticker.ema_spread_pct,1)}%`} color={ticker.ema_spread_pct < 1.5 ? '#ff8800' : ticker.ema_spread_pct < 3 ? '#ffd600' : '#888'} />
        )}
        {ticker.bb_sqz_bars > 0 && (
          <MetricChip label="BB Sqz" value={`${ticker.bb_sqz_bars}d`} color="#cc44ff" />
        )}
      </div>

      {/* ── ROW 6: Context layer (sector · hype · macro) ── */}
      <div className={styles.contextGrid}>
        {/* Sector context */}
        <div className={styles.ctxBlock}>
          <div className={styles.ctxBlockTitle}>Sector</div>
          <ContextRow
            icon="📊" label="Class"
            value={sc.sector_class || 'C'}
            sub={`vs SPY ${sc.sector_vs_spy != null ? (sc.sector_vs_spy > 0 ? '+' : '') + fmt(sc.sector_vs_spy, 1) + '%' : '—'}`}
            color={scCls.color}
          />
          {sc.is_sympathy && (
            <ContextRow icon="🔗" label="Sympathy" value={sc.sympathy_leader || '?'} sub={`score ${sc.sympathy_score}`} color="#00e5ff" />
          )}
        </div>

        {/* Hype context */}
        <div className={styles.ctxBlock}>
          <div className={styles.ctxBlockTitle}>Social Hype</div>
          <ContextRow
            icon="📣" label="Tier"
            value={hypeTier.label}
            sub={hc.hype_index != null ? `idx ${hc.hype_index}` : ''}
            color={hypeTier.color}
          />
          {hc.velocity_2h > 0 && (
            <ContextRow icon="⚡" label="Velocity" value={`${fmt(hc.velocity_2h, 1)}x`} color={hc.velocity_2h >= 3 ? '#ff8800' : '#ffd600'} />
          )}
          {hc.divergence && (
            <ContextRow icon="⚠️" label={hc.divergence.type?.replace(/_/g, ' ')} value={hc.divergence.severity || ''} color="#ff4444" />
          )}
        </div>

        {/* Macro context */}
        <div className={styles.ctxBlock}>
          <div className={styles.ctxBlockTitle}>Macro / News</div>
          <ContextRow icon="🌍" label="Market" value={mc.market_bias || 'NEUTRAL'} color={macroColor} />
          {mc.sector_impact && mc.sector_impact !== 'NEUTRAL' && (
            <ContextRow icon="🎯" label="Sector" value={mc.sector_impact} color={sectorImpactColor} />
          )}
          {mc.volatility_bias && mc.volatility_bias !== 'LOW' && (
            <ContextRow icon="🌪" label="Vol env" value={mc.volatility_bias} color="#ff8800" />
          )}
          {mc.active_events > 0 && (
            <ContextRow icon="📰" label="Events" value={mc.active_events} color="#888" />
          )}
        </div>
      </div>

      {/* ── ROW 7: Confirmations / Warnings ── */}
      {ticker.ignition_confirmations?.length > 0 && (
        <div className={styles.confirmList}>
          {ticker.ignition_confirmations.map((c, i) => <div key={i} className={styles.confirmItem}>✅ {c}</div>)}
        </div>
      )}
      {ticker.ignition_warnings?.length > 0 && (
        <div className={styles.warnList}>
          {ticker.ignition_warnings.map((w, i) => <div key={i} className={styles.warnItem}>⚠️ {w}</div>)}
        </div>
      )}

      {/* ── ROW 8: AI signal ── */}
      {ai && <AiSignalPanel ai={ai} />}

      {/* ── ROW 9: Footer ── */}
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
          <button className={styles.journalBtn} onClick={() => setShowJournal(true)}>+ Journal</button>
        </div>
      </div>

      {showJournal && (
        <JournalModal
          prefill={journalPrefill}
          onClose={() => setShowJournal(false)}
          onSaved={() => setShowJournal(false)}
        />
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function IgnitionPage() {
  const [data,        setData]        = useState(null);
  const [loading,     setLoading]     = useState(true);
  const [error,       setError]       = useState(null);
  const [mode,        setMode]        = useState('watch');
  const [minVolume,   setMinVolume]   = useState(200000);
  const [minQuality,  setMinQuality]  = useState(0);
  const [bullishOnly, setBullishOnly] = useState(false);
  const [withAi,      setWithAi]      = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const params = new URLSearchParams({
        mode,
        min_volume:  minVolume,
        min_quality: minQuality,
        bullish_only: bullishOnly,
        max_results: 150,
        with_ai:     withAi,
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
  }, [mode, minVolume, minQuality, bullishOnly, withAi]);

  useEffect(() => {
    setLoading(true);
    fetchData();
    const iv = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(iv);
  }, [fetchData]);

  const summary  = data?.summary  || {};
  const results  = data?.results  || [];
  const scanTime = data?.scanned_at ? new Date(data.scanned_at).toLocaleTimeString() : null;
  const weights  = summary.scoring_weights || {};

  return (
    <>
      <Head><title>⚡ Ignition — Pump Scout</title></Head>
      <div className={styles.page}>
        <AppNav />

        {/* ── Header ── */}
        <header className={styles.header}>
          <h1 className={styles.title}>⚡ Ignition Engine</h1>
          <p className={styles.subtitle}>
            Ribbon · Ignition · Sector · Hype · Macro
            {weights.ribbon && (
              <span className={styles.weightHint}>
                ({weights.ribbon}+{weights.ignition}+{weights.sector}+{weights.hype}+{weights.macro} pts)
              </span>
            )}
          </p>
          {scanTime && <div className={styles.scanTime}>Scan data: {scanTime}</div>}
        </header>

        {/* ── Summary bar ── */}
        {summary.total > 0 && (
          <div className={styles.summaryBar}>
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum}>{summary.total}</span>
              <span className={styles.summaryLbl}>Total</span>
            </div>
            {summary.strong_buy > 0 && (
              <div className={styles.summaryItem}>
                <span className={styles.summaryNum} style={{ color:'#00ff88' }}>{summary.strong_buy}</span>
                <span className={styles.summaryLbl}>🚀 Strong Buy</span>
              </div>
            )}
            {summary.buy > 0 && (
              <div className={styles.summaryItem}>
                <span className={styles.summaryNum} style={{ color:'#00c864' }}>{summary.buy}</span>
                <span className={styles.summaryLbl}>✅ Buy</span>
              </div>
            )}
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum} style={{ color:'#ff8800' }}>{summary.confirmed}</span>
              <span className={styles.summaryLbl}>🔥 Confirmed</span>
            </div>
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum} style={{ color:'#ffd600' }}>{summary.early}</span>
              <span className={styles.summaryLbl}>⚡ Early</span>
            </div>
            <div className={styles.summaryDivider} />
            {summary.sympathy_plays > 0 && (
              <div className={styles.summaryItem}>
                <span className={styles.summaryNum} style={{ color:'#00e5ff' }}>{summary.sympathy_plays}</span>
                <span className={styles.summaryLbl}>🔗 Sympathy</span>
              </div>
            )}
            {summary.hype_enriched > 0 && (
              <div className={styles.summaryItem}>
                <span className={styles.summaryNum} style={{ color:'#cc44ff' }}>{summary.hype_enriched}</span>
                <span className={styles.summaryLbl}>🔥 Hype</span>
              </div>
            )}
            {summary.macro_enriched > 0 && (
              <div className={styles.summaryItem}>
                <span className={styles.summaryNum} style={{ color:'#ffd600' }}>{summary.macro_enriched}</span>
                <span className={styles.summaryLbl}>🌍 Macro</span>
              </div>
            )}
            {summary.ai_analyzed > 0 && (
              <div className={styles.summaryItem}>
                <span className={styles.summaryNum} style={{ color:'#00ff88' }}>{summary.ai_analyzed}</span>
                <span className={styles.summaryLbl}>🤖 AI</span>
              </div>
            )}
          </div>
        )}

        {/* ── Mode tabs ── */}
        <div className={styles.tabs}>
          {MODE_TABS.map(t => (
            <button key={t.key}
              className={`${styles.tab} ${mode === t.key ? styles.tabActive : ''}`}
              onClick={() => setMode(t.key)} title={t.desc}>
              {t.label}
            </button>
          ))}
        </div>

        {/* ── Filters ── */}
        <div className={styles.filters}>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Min Vol:</span>
            {VOL_OPTIONS.map(o => (
              <button key={o.value}
                className={`${styles.filterBtn} ${minVolume === o.value ? styles.filterBtnActive : ''}`}
                onClick={() => setMinVolume(o.value)}>{o.label}</button>
            ))}
          </div>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Quality:</span>
            {QUALITY_OPTIONS.map(o => (
              <button key={o.value}
                className={`${styles.filterBtn} ${minQuality === o.value ? styles.filterBtnActive : ''}`}
                onClick={() => setMinQuality(o.value)}>{o.label}</button>
            ))}
          </div>
          <div className={styles.filterGroup}>
            <label className={styles.checkLabel}>
              <input type="checkbox" checked={bullishOnly} onChange={e => setBullishOnly(e.target.checked)} className={styles.checkInput} />
              Bullish only
            </label>
          </div>
          <div className={styles.filterGroup}>
            <label className={`${styles.checkLabel} ${withAi ? styles.aiActive : ''}`}>
              <input type="checkbox" checked={withAi} onChange={e => setWithAi(e.target.checked)} className={styles.checkInput} />
              🤖 AI signals
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
              <div className={styles.emptyHint}>Try switching to "All Signals" or lowering quality filter</div>
            </div>
          )}
          {!loading && results.length > 0 && (
            <>
              <div className={styles.resultsHeader}>
                {results.length} signal{results.length !== 1 ? 's' : ''} · sorted by unified score
              </div>
              <div className={styles.grid}>
                {results.map(t => <IgnitionCard key={t.symbol} ticker={t} />)}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
