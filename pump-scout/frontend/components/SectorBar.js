import styles from '../styles/SectorBar.module.css';

const CYCLE_PHASE_CONFIG = {
  RISK_ON_GROWTH: { emoji: '🚀', label: 'RISK ON GROWTH', color: '#00c864', tip: 'Tech + Growth leading. Избегай Utilities/Staples.' },
  LATE_CYCLE:     { emoji: '⚡', label: 'LATE CYCLE',     color: '#ffd600', tip: 'Energy + Materials leading. Осторожно с Growth.' },
  STAGFLATION:    { emoji: '⚠️', label: 'STAGFLATION',    color: '#ff8800', tip: 'Energy + Staples. Избегай Tech и Consumer Discr.' },
  RISK_OFF:       { emoji: '🛡', label: 'RISK OFF',       color: '#00e5ff', tip: 'Utilities + Healthcare. Держи кэш.' },
  FEAR:           { emoji: '😱', label: 'FEAR',           color: '#ff4444', tip: 'Только Materials. Максимальный кэш.' },
  NEUTRAL:        { emoji: '😐', label: 'NEUTRAL',        color: '#888',    tip: 'Нет чёткого направления.' },
};

export default function SectorBar({ data, cyclePhase }) {
  if (!data || Object.keys(data).length === 0) return null;

  const sectors = Object.entries(data).sort((a, b) => b[1].change_pct - a[1].change_pct);
  const maxAbs = Math.max(...sectors.map(([, d]) => Math.abs(d.change_pct)), 0.1);
  const phase = cyclePhase ? CYCLE_PHASE_CONFIG[cyclePhase] : null;

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <span className={styles.title}>Sector Performance</span>
        {phase && (
          <span
            title={phase.tip}
            style={{
              fontSize: 11, fontWeight: 700, padding: '2px 8px', borderRadius: 4,
              background: phase.color + '22', color: phase.color,
              border: `1px solid ${phase.color}44`, cursor: 'help',
            }}
          >
            {phase.emoji} {phase.label}
          </span>
        )}
        <span className={styles.source}>Finviz</span>
      </div>
      <div className={styles.grid}>
        {sectors.map(([name, d]) => {
          const barPct = Math.round((Math.abs(d.change_pct) / maxAbs) * 100);
          const isUp = d.change_pct >= 0;
          const isTrending = d.trending === true;
          const shortName = name
            .replace('Consumer ', 'Con. ')
            .replace('Communication Services', 'Comm. Svcs')
            .replace('Information Technology', 'Technology');
          return (
            <div key={name} className={styles.row} style={isTrending ? { background: 'rgba(0,200,100,0.06)' } : {}}>
              <span className={styles.name} title={name}>
                {isTrending && <span style={{ fontSize: 9, marginRight: 3 }}>🔥</span>}
                {shortName}
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
