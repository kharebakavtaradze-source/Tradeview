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

export default function TickerCard({ data }) {
  const [expanded, setExpanded] = useState(false);
  const [showJournal, setShowJournal] = useState(false);

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
