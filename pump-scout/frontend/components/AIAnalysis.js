import styles from '../styles/AIAnalysis.module.css';

/**
 * Parse raw AI analysis text into structured sections.
 * Each line like "SECTION: content" becomes a section object.
 */
function parseAnalysis(text) {
  if (!text) return null;

  const sections = [];
  const lines = text.split('\n');
  let current = null;

  for (const line of lines) {
    const colonIdx = line.indexOf(':');
    if (colonIdx > 0 && colonIdx < 25) {
      const label = line.slice(0, colonIdx).trim().toUpperCase();
      const content = line.slice(colonIdx + 1).trim();
      if (label && content) {
        if (current) sections.push(current);
        current = { label, content };
        continue;
      }
    }
    if (current && line.trim()) {
      current.content += ' ' + line.trim();
    }
  }
  if (current) sections.push(current);

  return sections.length > 0 ? sections : null;
}

function getSectionStyle(label) {
  const s = styles;
  switch (label) {
    case 'REGIME': return s.sectionRegime;
    case 'VERDICT': return s.sectionVerdict;
    case 'KEY LEVELS': return s.sectionLevels;
    default: return '';
  }
}

function VerdictContent({ content }) {
  const upper = content.toUpperCase();
  let cls = styles.verdictWatch;
  if (upper.includes('STRONG BUY')) cls = styles.verdictStrong;
  else if (upper.includes('AVOID')) cls = styles.verdictAvoid;

  return (
    <div className={styles.sectionContent}>
      <span className={cls}>{content.split('—')[0].trim()}</span>
      {content.includes('—') && (
        <span> — {content.split('—').slice(1).join('—').trim()}</span>
      )}
    </div>
  );
}

export default function AIAnalysis({ analysis, loading }) {
  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.loading}>
          <span className={styles.loadingDots}>Analyzing</span>
        </div>
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className={styles.container}>
        <div className={styles.noAnalysis}>No AI analysis available for this ticker</div>
      </div>
    );
  }

  const sections = parseAnalysis(analysis);

  if (!sections) {
    return (
      <div className={styles.container}>
        <pre className={styles.raw}>{analysis}</pre>
      </div>
    );
  }

  return (
    <div className={styles.container}>
      {sections.map((sec) => (
        <div key={sec.label} className={`${styles.section} ${getSectionStyle(sec.label)}`}>
          <div className={styles.sectionLabel}>{sec.label}</div>
          {sec.label === 'VERDICT' ? (
            <VerdictContent content={sec.content} />
          ) : sec.label === 'KEY LEVELS' ? (
            <div className={styles.sectionContent}>
              {sec.content.split('|').map((part, i) => (
                <span key={i} style={{ marginRight: 16 }}>
                  <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                    {part.split('$')[0].trim()}{' '}
                  </span>
                  <span style={{ color: 'var(--gold)', fontWeight: 700 }}>
                    {part.includes('$') ? '$' + part.split('$')[1] : part.trim()}
                  </span>
                </span>
              ))}
            </div>
          ) : (
            <div className={styles.sectionContent}>{sec.content}</div>
          )}
        </div>
      ))}
    </div>
  );
}
