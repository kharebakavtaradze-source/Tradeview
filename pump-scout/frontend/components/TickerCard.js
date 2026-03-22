import { useState } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import AIAnalysis from './AIAnalysis';
import JournalModal from './JournalModal';
import styles from '../styles/TickerCard.module.css';

const Chart = dynamic(() => import('./Chart'), { ssr: false });

const TIER_EMOJI = {
  FIRE: '🔥', ARM: '👁', BASE: '📦', STEALTH: '🕵',
  STEALTH_BASE: '🕵', STEALTH_ARM: '🕵', WATCH: '⚡',
  SYMPATHY: '🔗', SKIP: '',
};
const TIER_LABEL = {
  STEALTH: 'STEALTH', STEALTH_BASE: 'STEALTH', STEALTH_ARM: 'STEALTH',
};

function getBadgeClass(tier) {
  const map = {
    FIRE: styles.badgeFire,
    ARM: styles.badgeArm,
    BASE: styles.badgeBase,
    STEALTH: styles.badgeStealth,
    STEALTH_BASE: styles.badgeStealth,
    STEALTH_ARM: styles.badgeStealth,
    WATCH: styles.badgeWatch,
    SYMPATHY: styles.badgeSympathy,
  };
  return map[tier] || styles.badgeNone;
}

function getCardClass(tier) {
  const map = {
    FIRE: styles.cardFire,
    ARM: styles.cardArm,
    BASE: styles.cardBase,
    STEALTH: styles.cardStealth,
    STEALTH_BASE: styles.cardStealth,
    STEALTH_ARM: styles.cardStealth,
    WATCH: styles.cardWatch,
    SYMPATHY: styles.cardSympathy,
  };
  return map[tier] || '';
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function TickerCard({ data, hypeData }) {
  const [expanded, setExpanded] = useState(false);
  const [showJournal, setShowJournal] = useState(false);
  const [showHype, setShowHype] = useState(false);
  const [hypeDetail, setHypeDetail] = useState(null);
  const [fetchingHype, setFetchingHype] = useState(false);

  const { symbol, price, indicators = {}, regime = {}, score = {}, candles, ai_analysis, premarket, sympathy = {}, sector } = data;

  const tier = score.tier || 'WATCH';
  const totalScore = score.total_score || 0;
  const anomalyRatio = indicators.anomaly_ratio ?? null;
  const sqzBars = indicators.bb_sqz_bars || 0;
  const cmfPctl = indicators.cmf_pctl || 0;
  const priceChangePct = indicators.price_change_pct || 0;
  const state = regime.state || 'NONE';
  const stealth = indicators.stealth || {};
  const instFlow = indicators.institutional_flow || {};
  const isStealth = tier === 'STEALTH' || stealth.is_stealth;

  // Hype monitor data — hypeDetail overrides hypeData when fetched on click
  const activeHype = hypeDetail || hypeData;
  const hypeScore = activeHype?.hype_score || null;
  const hypeDivergences = activeHype?.divergences || [];
  const hypeVelocity = activeHype?.velocity || null;

  // News/SEC badges visible before clicking (from bulk props)
  const propNews = hypeData?.news || {};
  const newsCount24h = propNews.count_24h || 0;
  const hasSec = propNews.has_sec_filing || false;
  const rsiData = indicators.rsi || {};
  const gapData = indicators.gap || {};
  const hasGap = gapData.gap_type && gapData.gap_type !== 'NONE';
  const hasPremarket = premarket?.has_premarket && Math.abs(premarket.premarket_pct || 0) >= 1.0;

  const priceChangeClass =
    priceChangePct > 0.5
      ? styles.priceUp
      : priceChangePct < -0.5
      ? styles.priceDown
      : styles.priceFlat;

  const priceSign = priceChangePct >= 0 ? '+' : '';

  return (
    <div className={`${styles.card} ${getCardClass(tier)}`}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.symbolRow}>
          <span className={styles.symbol}>{symbol}</span>
          <span className={`${styles.badge} ${getBadgeClass(tier)}`}>
            {TIER_EMOJI[tier]} {TIER_LABEL[tier] || tier}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className={styles.score}>{totalScore.toFixed(0)}</span>
          {hasSec && (
            <span title="SEC Filing detected" style={{
              fontSize: 9, fontWeight: 700, color: '#ffd700',
              background: 'rgba(255,215,0,0.12)', border: '1px solid rgba(255,215,0,0.4)',
              borderRadius: 3, padding: '1px 4px',
            }}>⚠ SEC</span>
          )}
          {!hasSec && newsCount24h > 0 && (
            <span title={`${newsCount24h} news articles in last 24h`} style={{
              fontSize: 9, fontWeight: 700, color: 'var(--text-muted)',
              background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.15)',
              borderRadius: 3, padding: '1px 4px',
            }}>📰{newsCount24h}</span>
          )}
          {hypeScore && (
            <button
              onClick={async e => {
                e.stopPropagation();
                if (!showHype) {
                  setShowHype(true);
                  if (!hypeDetail) {
                    setFetchingHype(true);
                    try {
                      const res = await fetch(`${API_URL}/api/hype/${symbol}`);
                      if (res.ok) setHypeDetail(await res.json());
                    } catch { /* silent */ }
                    finally { setFetchingHype(false); }
                  }
                } else {
                  setShowHype(false);
                }
              }}
              title={`Hype: ${hypeScore.hype_index}/100 (${hypeScore.hype_tier})`}
              style={{
                background: hypeScore.hype_tier === 'VIRAL' ? 'rgba(255,68,102,0.15)'
                  : hypeScore.hype_tier === 'HOT' ? 'rgba(255,136,0,0.12)'
                  : 'none',
                border: hypeScore.hype_tier === 'COLD' ? 'none' : '1px solid rgba(170,0,255,0.3)',
                borderRadius: 3,
                cursor: 'pointer',
                fontSize: 10,
                fontWeight: 700,
                padding: '1px 5px',
                color: hypeScore.hype_tier === 'VIRAL' ? '#ff4466'
                  : hypeScore.hype_tier === 'HOT' ? '#ff8800'
                  : hypeScore.hype_tier === 'WARM' ? '#cc44ff'
                  : 'var(--text-muted)',
              }}
            >
              {hypeScore.hype_tier === 'VIRAL' ? '🔥' : hypeScore.hype_tier === 'HOT' ? '🚀' : hypeScore.hype_tier === 'WARM' ? '📈' : ''}
              {hypeScore.hype_index.toFixed(0)}
            </button>
          )}
          <button
            onClick={e => { e.stopPropagation(); setShowJournal(true); }}
            title="Add to Journal"
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              fontSize: 14, opacity: 0.5, padding: '0 2px',
              lineHeight: 1, transition: 'opacity 0.15s',
            }}
            onMouseEnter={e => (e.target.style.opacity = 1)}
            onMouseLeave={e => (e.target.style.opacity = 0.5)}
          >📔</button>
        </div>
      </div>

      {/* Body */}
      <div className={styles.body} onClick={() => setExpanded(!expanded)} style={{ cursor: 'pointer' }}>
        <div className={styles.priceRow}>
          <span className={styles.price}>${price?.toFixed(2) ?? '—'}</span>
          <span className={`${styles.priceChange} ${priceChangeClass}`}>
            {priceSign}{priceChangePct.toFixed(2)}%
          </span>
          {hasPremarket && (
            <span className={`${styles.premarketBadge} ${premarket.premarket_pct >= 0 ? styles.premarketUp : styles.premarketDown}`}>
              {premarket.session === 'pre' ? 'PRE' : 'AH'} {premarket.premarket_pct >= 0 ? '+' : ''}{premarket.premarket_pct?.toFixed(1)}%
            </span>
          )}
        </div>

        <div className={styles.metrics}>
          <div className={styles.metric}>
            <span className={styles.metricLabel}>VOL</span>
            <span className={`${styles.metricValue} ${anomalyRatio != null && anomalyRatio >= 3 ? styles.metricGold : styles.metricHighlight}`}>
              {anomalyRatio != null ? `${anomalyRatio.toFixed(1)}x` : 'N/A'}
            </span>
          </div>
          <div className={styles.metric}>
            <span className={styles.metricLabel}>SQZ</span>
            <span className={`${styles.metricValue} ${sqzBars >= 5 ? styles.metricHighlight : ''}`}>
              {sqzBars}b
            </span>
          </div>
          <div className={styles.metric}>
            <span className={styles.metricLabel}>RSI</span>
            <span className={`${styles.metricValue} ${rsiData.oversold ? styles.metricGreen : rsiData.overbought ? styles.metricRed : ''}`}>
              {rsiData.value ?? '—'}
              {rsiData.has_divergence && <span className={styles.divDot} title="Bullish RSI Divergence">↗</span>}
            </span>
          </div>
          <div className={styles.metric}>
            <span className={styles.metricLabel}>STATE</span>
            <span className={`${styles.metricValue} ${isStealth ? styles.metricStealth : styles.metricHighlight}`}>{state}</span>
          </div>
        </div>

        {/* Signal badges row */}
        {(rsiData.has_divergence || hasGap || isStealth) && (
          <div className={styles.signalsRow}>
            {rsiData.has_divergence && (
              <span className={styles.badgeDiv}>↗ RSI DIV</span>
            )}
            {hasGap && (
              <span className={`${styles.badgeGap} ${gapData.is_gap_up ? styles.badgeGapUp : styles.badgeGapDown}`}>
                {gapData.is_gap_up ? '▲' : '▼'} GAP {gapData.gap_pct > 0 ? '+' : ''}{gapData.gap_pct}%
              </span>
            )}
            {isStealth && (
              <span className={styles.badgeStealth2}>
                🕵 {stealth.vol_ratio?.toFixed(1) ?? '?'}x · {stealth.price_change_pct?.toFixed(1) ?? '?'}%
                {stealth.strength === 'STRONG' && ' STRONG'}
              </span>
            )}
          </div>
        )}

      </div>

      {/* Sympathy banner */}
      {sympathy?.is_sympathy && (
        <div className={styles.sympathyBanner}>
          <span className={styles.sympathyLabel}>🔗 SYMPATHY</span>
          <span>Following: {sympathy.leaders?.join(', ')}</span>
          {sector && <span>{sector}</span>}
          <span>Leader +{sympathy.leader_change?.toFixed(0)}%</span>
          <span>Score: {sympathy.sympathy_score}/100</span>
          <span style={{ opacity: 0.6 }}>{sympathy.window}</span>
        </div>
      )}

      {/* Institutional flow banner */}
      {instFlow?.is_institutional && (
        <div className={styles.instFlowBanner}>
          <span className={styles.instFlowLabel}>🏦 INST FLOW</span>
          <span>{instFlow.days}d streak</span>
          <span>avg {instFlow.avg_vol_ratio}x vol</span>
          <span className={
            instFlow.strength === 'STRONG' ? styles.flowStrengthStrong
            : instFlow.strength === 'MEDIUM' ? styles.flowStrengthMedium
            : styles.flowStrengthEarly
          }>{instFlow.strength}</span>
        </div>
      )}

      {/* Hype detail panel */}
      {showHype && hypeScore && (
        <div className={styles.hypePanel}>
          <div className={styles.hypePanelTitle}>
            🔮 HYPE MONITOR
            <span style={{ marginLeft: 6, fontWeight: 400, color: 'var(--text-muted)' }}>
              {hypeScore.hype_index.toFixed(0)}/100 · {hypeScore.hype_tier}
            </span>
            {fetchingHype && <span style={{ marginLeft: 8, fontSize: 9, opacity: 0.5 }}>loading…</span>}
          </div>
          <div className={styles.hypeMetrics}>
            <span>24h mentions: {hypeScore.mention_counts?.total ?? 0}</span>
            <span>ST: {hypeScore.mention_counts?.stocktwits ?? 0}</span>
            <span>Reddit: {hypeScore.mention_counts?.reddit ?? 0}</span>
            <span>News: {hypeScore.mention_counts?.news ?? 0}</span>
            {hypeVelocity && <span>Vel 2h: {hypeVelocity.combined_velocity_2h?.toFixed(1)}x</span>}
          </div>
          {hypeDivergences.length > 0 && (
            <div style={{ marginTop: 6 }}>
              {hypeDivergences.map((d) => (
                <div key={d.type} className={`${styles.hypeDivergence} ${
                  d.type === 'SILENT_VOLUME' ? styles.divSilent
                  : d.type === 'VELOCITY_SPIKE' ? styles.divVelocity
                  : d.type === 'PEAK_FADING' ? styles.divPeak
                  : styles.divHype
                }`}>
                  <span className={styles.divLabel}>{d.label}</span>
                  <span className={styles.divSeverity}>{d.severity}</span>
                </div>
              ))}
            </div>
          )}
          {/* News headlines — 24h first, fall back to 7d if nothing today */}
          {(() => {
            const news = activeHype?.news;
            if (!news) return null;
            const has24h = (news.headlines?.length || 0) > 0;
            const shown = has24h ? news.headlines : (news.headlines_7d?.slice(0, 3) || []);
            const is7dFallback = !has24h && shown.length > 0;
            if (shown.length === 0 && !news.has_sec_filing) return (
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 6, opacity: 0.5 }}>
                No recent news
              </div>
            );
            return (
              <div style={{ marginTop: 6 }}>
                {news.has_sec_filing && (
                  <div style={{ fontSize: 10, color: '#ffd700', fontWeight: 700, marginBottom: 3 }}>
                    ⚠ SEC FILING DETECTED
                  </div>
                )}
                {is7dFallback && (
                  <div style={{ fontSize: 9, color: 'var(--text-muted)', opacity: 0.6, marginBottom: 2 }}>
                    Recent (last 7d):
                  </div>
                )}
                {shown.slice(0, 3).map((h, i) => {
                  const typeBadgeStyle = {
                    fontSize: 9, fontWeight: 700, borderRadius: 2,
                    padding: '1px 4px', marginRight: 5, whiteSpace: 'nowrap',
                    ...(h.type === 'sec'
                      ? { background: 'rgba(255,215,0,0.2)', color: '#ffd700' }
                      : h.type === 'real'
                      ? { background: 'rgba(0,200,100,0.15)', color: 'var(--green)' }
                      : { background: 'rgba(255,255,255,0.08)', color: 'var(--text-muted)' }
                    ),
                  };
                  const typeLabel = h.type === 'sec' ? 'SEC' : h.type === 'real' ? 'REAL' : h.type === 'pr' ? 'PR' : '?';
                  return (
                    <div key={i} style={{ fontSize: 10, color: 'var(--text-dim)', marginTop: 3, lineHeight: 1.35, display: 'flex', alignItems: 'baseline', gap: 0 }}>
                      <span style={{ opacity: 0.45, marginRight: 5, whiteSpace: 'nowrap' }}>{h.hours_ago}h ago</span>
                      <span style={typeBadgeStyle}>[{typeLabel}]</span>
                      <span>{h.title.length > 70 ? h.title.slice(0, 70) + '…' : h.title}</span>
                    </div>
                  );
                })}
                {news.count_2_7d > 0 && !has24h && (
                  <div style={{ fontSize: 9, color: 'var(--text-muted)', opacity: 0.5, marginTop: 3 }}>
                    +{news.count_2_7d} more articles this week
                  </div>
                )}
              </div>
            );
          })()}

          {activeHype?.ai_analysis?.summary && (
            <div className={styles.hypeAI}>
              🤖 {activeHype.ai_analysis.summary}
              <div style={{ marginTop: 4, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {activeHype.ai_analysis.recommendation && (() => {
                  const rec = activeHype.ai_analysis.recommendation;
                  const recColor = rec === 'ENTER' ? { background: 'rgba(0,200,100,0.15)', color: '#00c864', border: '1px solid rgba(0,200,100,0.3)' }
                    : rec === 'WATCH' ? { background: 'rgba(255,200,0,0.12)', color: '#ffc800', border: '1px solid rgba(255,200,0,0.35)' }
                    : { background: 'rgba(255,68,68,0.12)', color: '#ff4444', border: '1px solid rgba(255,68,68,0.3)' };
                  return (
                    <span style={{ fontSize: 9, fontWeight: 700, borderRadius: 3, padding: '2px 6px', ...recColor }}>
                      {rec}
                    </span>
                  );
                })()}
                {activeHype.ai_analysis.risk_level && (
                  <span style={{
                    fontSize: 9, fontWeight: 700, borderRadius: 3, padding: '2px 6px',
                    background: 'rgba(255,255,255,0.06)', color: 'var(--text-muted)',
                    border: '1px solid rgba(255,255,255,0.12)',
                  }}>
                    RISK: {activeHype.ai_analysis.risk_level}
                  </span>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Expand button */}
      <button className={styles.expandBtn} onClick={() => setExpanded(!expanded)}>
        <span>{expanded ? 'Hide' : 'Chart + AI'}</span>
        <span className={`${styles.expandIcon} ${expanded ? styles.expandIconOpen : ''}`}>▼</span>
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className={styles.expanded}>
          {candles && candles.length > 0 && (
            <Chart
              candles={candles}
              bbData={{ upper: indicators.bb_upper, lower: indicators.bb_lower }}
              ema50={indicators.ema50}
            />
          )}
          {ai_analysis && <AIAnalysis analysis={ai_analysis} loading={false} />}
          <Link href={`/ticker/${symbol}`} className={styles.detailLink}>
            Full Analysis → {symbol}
          </Link>
        </div>
      )}

      {showJournal && (
        <JournalModal
          prefill={{
            symbol,
            entry_price: price?.toFixed(2) || '',
            tier,
            score: totalScore,
            indicators_snapshot: {
              bb_sqz_bars: indicators.bb_sqz_bars,
              cmf_pctl: indicators.cmf_pctl,
              vol_z: indicators.vol_z,
              anomaly_ratio: indicators.anomaly_ratio,
              stealth_score: stealth.stealth_score,
              state: regime.state,
            },
          }}
          onClose={() => setShowJournal(false)}
          onSaved={() => setShowJournal(false)}
        />
      )}
    </div>
  );
}
