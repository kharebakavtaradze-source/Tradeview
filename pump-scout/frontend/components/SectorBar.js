import styles from '../styles/SectorBar.module.css';

export default function SectorBar({ data }) {
  if (!data || Object.keys(data).length === 0) return null;

  const sectors = Object.entries(data).sort((a, b) => b[1].change_pct - a[1].change_pct);
  const maxAbs = Math.max(...sectors.map(([, d]) => Math.abs(d.change_pct)), 0.1);

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.title}>Sector Performance</span>
        <span className={styles.source}>Finviz</span>
      </div>
      <div className={styles.grid}>
        {sectors.map(([name, d]) => {
          const barPct = Math.round((Math.abs(d.change_pct) / maxAbs) * 100);
          const isUp = d.change_pct >= 0;
          return (
            <div key={name} className={styles.row}>
              <span className={styles.name} title={name}>
                {name.replace('Consumer ', 'Con. ').replace('Communication Services', 'Comm.')}
              </span>
              <div className={styles.barWrap}>
                <div
                  className={`${styles.bar} ${isUp ? styles.barUp : styles.barDown}`}
                  style={{ width: `${barPct}%` }}
                />
              </div>
              <span className={`${styles.pct} ${isUp ? styles.pctUp : styles.pctDown}`}>
                {d.change_pct > 0 ? '+' : ''}{d.change_pct.toFixed(2)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
