import styles from '../styles/Home.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function Scanner({ scanData, scanning, onRescan, lastUpdated }) {
  const tierCounts = scanData?.tier_counts || {};
  const total = scanData?.total || 0;

  const formatTime = (isoStr) => {
    if (!isoStr) return 'Never';
    try {
      const d = new Date(isoStr + 'Z');
      return d.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: true,
      });
    } catch {
      return 'Unknown';
    }
  };

  return (
    <div className={styles.headerMeta}>
      <span className={styles.lastScan}>
        Last scan: {lastUpdated ? formatTime(lastUpdated) : 'No data'}
        {total > 0 && ` · ${total} tickers`}
      </span>

      <div className={styles.tierCounts}>
        {tierCounts.FIRE > 0 && (
          <span className={`${styles.tierBadge} ${styles.tierFire}`}>
            🔥{tierCounts.FIRE}
          </span>
        )}
        {tierCounts.ARM > 0 && (
          <span className={`${styles.tierBadge} ${styles.tierArm}`}>
            👁{tierCounts.ARM}
          </span>
        )}
        {tierCounts.BASE > 0 && (
          <span className={`${styles.tierBadge} ${styles.tierBase}`}>
            📦{tierCounts.BASE}
          </span>
        )}
        {tierCounts.STEALTH > 0 && (
          <span className={`${styles.tierBadge} ${styles.tierStealth}`}>
            🕵{tierCounts.STEALTH}
          </span>
        )}
        {tierCounts.WATCH > 0 && (
          <span className={`${styles.tierBadge} ${styles.tierWatch}`}>
            ⚡{tierCounts.WATCH}
          </span>
        )}
      </div>

      <button
        className={styles.rescanBtn}
        onClick={onRescan}
        disabled={scanning}
        title="Trigger a manual scan"
      >
        {scanning && <span className={styles.spinner} />}
        {scanning ? 'Scanning...' : '▶ RESCAN'}
      </button>
    </div>
  );
}
