import styles from '../styles/MarketRegimeBanner.module.css';

const REGIME_CONFIG = {
  RISK_ON: { emoji: '📈', label: 'RISK ON', className: 'riskOn' },
  RISK_OFF: { emoji: '🛡', label: 'RISK OFF', className: 'riskOff' },
  FEAR: { emoji: '😱', label: 'FEAR', className: 'fear' },
  ROTATION_ENERGY: { emoji: '🔄', label: 'ROTATION: ENERGY', className: 'rotation' },
  ROTATION_DEFENSIVE: { emoji: '🔄', label: 'ROTATION: DEFENSIVE', className: 'rotation' },
  NEUTRAL: { emoji: '⚖', label: 'NEUTRAL', className: 'neutral' },
};

function fmt(val) {
  if (val == null) return '—';
  const sign = val >= 0 ? '+' : '';
  return `${sign}${val.toFixed(1)}%`;
}

export default function MarketRegimeBanner({ regime }) {
  if (!regime) return null;

  const cfg = REGIME_CONFIG[regime.regime] || REGIME_CONFIG.NEUTRAL;
  const strong = regime.strong_sectors || [];
  const weak = regime.weak_sectors || [];

  const etf = regime.etf_details || {};
  const spy = etf.SPY?.pct_1d ?? regime.spy_pct;
  const qqq = etf.QQQ?.pct_1d ?? regime.qqq_pct;
  const xle = etf.XLE?.pct_1d ?? regime.xle_pct;
  const gld = etf.GLD?.pct_1d ?? regime.gld_pct;

  return (
    <div className={`${styles.banner} ${styles[cfg.className]}`}>
      <div className={styles.topRow}>
        <span className={styles.regimeLabel}>
          {cfg.emoji} {cfg.label}
        </span>
        <span className={styles.etfRow}>
          <span>SPY {fmt(spy)}</span>
          <span>QQQ {fmt(qqq)}</span>
          {xle != null && <span>XLE {fmt(xle)}</span>}
          {gld != null && <span>GLD {fmt(gld)}</span>}
        </span>
      </div>

      {(strong.length > 0 || weak.length > 0) && (
        <div className={styles.sectorsRow}>
          {strong.length > 0 && (
            <span className={styles.strong}>
              💪 Strong: {strong.join('  ')}
            </span>
          )}
          {weak.length > 0 && (
            <span className={styles.weak}>
              {regime.regime === 'FEAR' ? '🚨' : '⚠'} Weak: {weak.join('  ')}
            </span>
          )}
        </div>
      )}

      {regime.recommendation && (
        <div className={styles.rec}>{regime.recommendation}</div>
      )}
    </div>
  );
}
