import { useState } from 'react';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import AIAnalysis from './AIAnalysis';
import styles from '../styles/TickerCard.module.css';

const Chart = dynamic(() => import('./Chart'), { ssr: false });

const TIER_EMOJI = { FIRE: '🔥', ARM: '👁', BASE: '📦', WATCH: '⚡', SKIP: '' };

function getBadgeClass(tier) {
  const map = {
    FIRE: styles.badgeFire,
    ARM: styles.badgeArm,
    BASE: styles.badgeBase,
    WATCH: styles.badgeWatch,
  };
  return map[tier] || styles.badgeNone;
}

function getCardClass(tier) {
  const map = {
    FIRE: styles.cardFire,
    ARM: styles.cardArm,
    BASE: styles.cardBase,
    WATCH: styles.cardWatch,
  };
  return map[tier] || '';
}

export default function TickerCard({ data }) {
  const [expanded, setExpanded] = useState(false);

  const { symbol, price, indicators = {}, regime = {}, score = {}, candles, ai_analysis } = data;

  const tier = score.tier || 'WATCH';
  const totalScore = score.total_score || 0;
  const anomalyRatio = indicators.anomaly_ratio ?? null;
  const sqzBars = indicators.bb_sqz_bars || 0;
  const cmfPctl = indicators.cmf_pctl || 0;
  const priceChangePct = indicators.price_change_pct || 0;
  const state = regime.state || 'NONE';

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
            {TIER_EMOJI[tier]} {tier}
          </span>
        </div>
        <span className={styles.score}>{totalScore.toFixed(0)}</span>
      </div>

      {/* Body */}
      <div className={styles.body} onClick={() => setExpanded(!expanded)} style={{ cursor: 'pointer' }}>
        <div className={styles.priceRow}>
          <span className={styles.price}>${price?.toFixed(2) ?? '—'}</span>
          <span className={`${styles.priceChange} ${priceChangeClass}`}>
            {priceSign}{priceChangePct.toFixed(2)}%
          </span>
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
            <span className={styles.metricLabel}>CMF%</span>
            <span className={styles.metricValue}>{cmfPctl.toFixed(0)}</span>
          </div>
          <div className={styles.metric}>
            <span className={styles.metricLabel}>STATE</span>
            <span className={`${styles.metricValue} ${styles.metricHighlight}`}>{state}</span>
          </div>
        </div>
      </div>

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
    </div>
  );
}
