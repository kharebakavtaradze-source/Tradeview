import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import styles from '../styles/AIReview.module.css';
import AppNav from '../components/AppNav';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REFRESH_INTERVAL = 120 * 1000;

// ── Config ────────────────────────────────────────────────────────────────────

const REVIEW_TABS = [
  { key: 'daily',    label: '📅 Daily',    endpoint: '/api/ai/reviewer/daily',    runType: 'DAILY'    },
  { key: 'weekly',   label: '📆 Weekly',   endpoint: '/api/ai/reviewer/weekly',   runType: 'WEEKLY'   },
  { key: 'missed',   label: '🎯 Missed',   endpoint: '/api/ai/reviewer/missed',   runType: 'MISSED'   },
  { key: 'failures', label: '🚫 Failures', endpoint: '/api/ai/reviewer/failures', runType: 'FAILURES' },
];

const CONF_CFG = {
  HIGH:   { color: '#00c864', bg: 'rgba(0,200,100,0.12)' },
  MEDIUM: { color: '#ffd600', bg: 'rgba(255,214,0,0.1)'  },
  LOW:    { color: '#888',    bg: 'rgba(100,100,100,0.08)' },
};

const QUALITY_CFG = {
  SUFFICIENT: { color: '#00c864' },
  SPARSE:     { color: '#ffd600' },
  MINIMAL:    { color: '#888'    },
};

// ── Sub-components ────────────────────────────────────────────────────────────

function SectionBlock({ title, items, titleClass }) {
  return (
    <div className={styles.sectionBlock}>
      <div className={`${styles.sectionTitle} ${titleClass}`}>{title}</div>
      {items?.length > 0
        ? items.map((item, i) => <div key={i} className={styles.sectionItem}>{item}</div>)
        : <div className={styles.empty}>—</div>
      }
    </div>
  );
}

function ReviewCard({ review }) {
  const conf    = CONF_CFG[review.confidence] || CONF_CFG.LOW;
  const quality = QUALITY_CFG[review.data_quality] || QUALITY_CFG.MINIMAL;

  return (
    <div className={styles.reviewCard}>
      {/* Meta row */}
      <div className={styles.cardMeta}>
        <span className={styles.reviewTypeBadge}>{review.review_type?.replace(/_/g, ' ')}</span>
        <span className={styles.reviewDate}>{review.review_date}</span>
        {review.data_quality && (
          <span className={styles.qualityBadge} style={{ color: quality.color }}>
            {review.data_quality}
          </span>
        )}
        <span
          className={styles.confBadge}
          style={{ color: conf.color, background: conf.bg }}
        >
          {review.confidence} CONF
        </span>
      </div>

      {/* Summary */}
      {review.summary && (
        <div className={styles.summary}>{review.summary}</div>
      )}

      {/* Worked / Failed */}
      <div className={styles.sectionGrid}>
        <SectionBlock
          title="✓ What Worked"
          items={review.what_worked}
          titleClass={styles.workedTitle}
        />
        <SectionBlock
          title="✕ What Failed"
          items={review.what_failed}
          titleClass={styles.failedTitle}
        />
      </div>

      {/* Missed / Focus */}
      <div className={styles.sectionGrid}>
        <SectionBlock
          title="◎ Missed Patterns"
          items={review.missed_patterns}
          titleClass={styles.missedTitle}
        />
        <div className={styles.sectionBlock}>
          <div className={`${styles.sectionTitle} ${styles.focusTitle}`}>
            → Suggested Focus
          </div>
          {review.suggested_focus?.length > 0
            ? review.suggested_focus.map((item, i) => (
                <div key={i} className={styles.focusItem}>
                  <span className={styles.focusNum}>{i + 1}.</span>
                  <span>{item}</span>
                </div>
              ))
            : <div className={styles.empty}>—</div>
          }
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function AIReviewPage() {
  const [tab,     setTab]     = useState('daily');
  const [data,    setData]    = useState({});
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [runMsg,  setRunMsg]  = useState('');
  const [error,   setError]   = useState(null);

  const currentTab = REVIEW_TABS.find(t => t.key === tab) || REVIEW_TABS[0];

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}${currentTab.endpoint}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const d = await res.json();
      setData(prev => ({ ...prev, [tab]: d.results || [] }));
      setError(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [tab, currentTab.endpoint]);

  useEffect(() => {
    if (!data[tab]) fetchData();
    else setLoading(false);
    const iv = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(iv);
  }, [tab]); // eslint-disable-line

  async function handleRun() {
    setRunning(true);
    setRunMsg('');
    try {
      const res = await fetch(
        `${API_URL}/api/ai/reviewer/run?review_type=${currentTab.runType}`,
        { method: 'POST' }
      );
      const d = await res.json();
      setRunMsg(d.message || 'Review started');
      setTimeout(() => {
        setData(prev => ({ ...prev, [tab]: undefined }));
        fetchData();
      }, 10000);
    } catch (e) {
      setRunMsg(`Error: ${e.message}`);
    } finally {
      setRunning(false);
    }
  }

  const reviews = data[tab] || [];

  return (
    <>
      <Head><title>📋 AI Review — Pump Scout</title></Head>
      <div className={styles.page}>
        <AppNav />

        <header className={styles.header}>
          <div className={styles.advisory}>Advisory · Read-Only · Does Not Affect Scores</div>
          <h1 className={styles.title}>📋 AI Reviewer</h1>
          <p className={styles.subtitle}>
            Retrospective analysis of trades, setups, and missed opportunities
          </p>
        </header>

        {/* Tabs */}
        <div className={styles.tabs}>
          {REVIEW_TABS.map(t => (
            <button
              key={t.key}
              className={`${styles.tab} ${tab === t.key ? styles.tabActive : ''}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Controls */}
        <div className={styles.controls}>
          <button
            className={styles.runBtn}
            onClick={handleRun}
            disabled={running}
          >
            {running ? '⏳ Running...' : `▶ Generate ${currentTab.label.split(' ')[1]} Review`}
          </button>
          <button className={styles.refreshBtn} onClick={fetchData}>⟳ Refresh</button>
          {runMsg && <span style={{ fontSize: 10, color: 'var(--text-muted)', fontStyle: 'italic' }}>{runMsg}</span>}
        </div>

        {/* Content */}
        <div className={styles.content}>
          {loading && <div className={styles.statusMsg}>Loading review...</div>}
          {error   && <div className={styles.statusMsg} style={{ color: 'var(--red)' }}>Error: {error}</div>}

          {!loading && reviews.length === 0 && (
            <div className={styles.emptyMsg}>
              <div>No {currentTab.label.split(' ')[1].toLowerCase()} review yet</div>
              <div className={styles.emptyHint}>
                Click ▶ Generate to create a new review. Requires journal entries and scan history.
              </div>
            </div>
          )}

          {reviews.map((r, i) => <ReviewCard key={r.id || i} review={r} />)}
        </div>
      </div>
    </>
  );
}
