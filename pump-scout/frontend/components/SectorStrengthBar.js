import styles from '../styles/SectorStrengthBar.module.css';

export default function SectorStrengthBar({ sectors, onSectorClick, activeFilter }) {
  if (!sectors || sectors.length === 0) return null;

  const maxScore = Math.max(...sectors.map(s => s.avg_score || 0), 1);

  return (
    <div className={styles.container}>
      {sectors.map(s => {
        const pct = Math.round((s.avg_score / maxScore) * 100);
        const isActive = activeFilter === s.sector;
        return (
          <div
            key={s.sector}
            className={`${styles.row} ${isActive ? styles.rowActive : ''}`}
            onClick={() => onSectorClick && onSectorClick(isActive ? null : s.sector)}
            title={`${s.ticker_count} tickers — leader: ${s.leader_symbol}`}
          >
            <span className={styles.name}>{s.sector}</span>
            <div className={styles.barWrap}>
              <div className={styles.barFill} style={{ width: `${pct}%` }} />
            </div>
            <span className={styles.score}>{(s.avg_score || 0).toFixed(0)}</span>
            <span className={styles.leader}>{s.leader_symbol || '—'}</span>
          </div>
        );
      })}
      {activeFilter && (
        <button className={styles.clearBtn} onClick={() => onSectorClick && onSectorClick(null)}>
          ✕ clear filter
        </button>
      )}
    </div>
  );
}
