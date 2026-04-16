/**
 * Raw Pattern Study — Feature Discovery
 * Phase 5A: page shell + runs list + launch form + run selection + run header.
 * Phase 5B (future): episode features table with group filters.
 * Phase 5C (future): comparison charts.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import Head from 'next/head';
import AppNav from '../components/AppNav';
import styles from '../styles/RawPatternStudy.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const POLL_MS = 3000;

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtDate(s) {
  if (!s) return '—';
  return String(s).slice(0, 10);
}

function fmtNum(n) {
  if (n == null) return '—';
  return Number(n).toLocaleString();
}

function ago(s) {
  if (!s) return '';
  const ms   = Date.now() - new Date(s).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1)  return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const MAP = {
    pending:  styles.statusPending,
    running:  styles.statusRunning,
    complete: styles.statusComplete,
    error:    styles.statusError,
  };
  return (
    <span className={`${styles.statusBadge} ${MAP[status] || styles.statusPending}`}>
      {status || 'unknown'}
    </span>
  );
}

// ── Run header card ───────────────────────────────────────────────────────────

function RunHeader({ run }) {
  const isRunning = run.status === 'running';
  return (
    <div className={styles.runHeader}>
      <div className={styles.runHeaderTop}>
        <span className={styles.runIdLabel}>Run #{run.id}</span>
        <StatusBadge status={run.status} />
        {isRunning && <span className={styles.pulsingDot} />}
      </div>

      <div className={styles.runMeta}>
        <span>{fmtDate(run.start_date)} → {fmtDate(run.end_date)}</span>
        {run.pump_study_run_id != null && (
          <span>Pump Study #{run.pump_study_run_id}</span>
        )}
        {run.created_at && <span>{ago(run.created_at)}</span>}
        {run.finished_at && <span>Finished {ago(run.finished_at)}</span>}
      </div>

      <div className={styles.runCounts}>
        <div className={styles.countItem}>
          <span className={styles.countVal}>{fmtNum(run.raw_daily_count)}</span>
          <span className={styles.countLabel}>Daily Features</span>
        </div>
        <div className={styles.countItem}>
          <span className={styles.countVal}>{fmtNum(run.episode_feature_count)}</span>
          <span className={styles.countLabel}>Episodes</span>
        </div>
        <div className={styles.countItem}>
          <span className={styles.countVal}>{fmtNum(run.comparison_count)}</span>
          <span className={styles.countLabel}>Comparisons</span>
        </div>
      </div>

      {run.notes && (
        <div className={styles.runNotes}>{run.notes}</div>
      )}
      {run.error_message && (
        <div className={styles.errorMsg}>{run.error_message}</div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function RawPatternStudy() {
  // Runs list
  const [runs,        setRuns]        = useState([]);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [runsError,   setRunsError]   = useState('');

  // Selected run detail
  const [selectedId,  setSelectedId]  = useState(null);
  const [run,         setRun]         = useState(null);
  const [loadingRun,  setLoadingRun]  = useState(false);

  // Launch form
  const [psRunId,   setPsRunId]   = useState('');
  const [notes,     setNotes]     = useState('');
  const [launching, setLaunching] = useState(false);
  const [launchErr, setLaunchErr] = useState('');

  const pollRef = useRef(null);

  // ── Fetch runs list ────────────────────────────────────────────────────────
  const loadRuns = useCallback(async () => {
    setLoadingRuns(true);
    setRunsError('');
    try {
      const r    = await fetch(`${API_URL}/api/replay/raw-pattern-study/runs?limit=40`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setRuns(data.runs || []);
    } catch (e) {
      setRunsError(String(e));
    } finally {
      setLoadingRuns(false);
    }
  }, []);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  // ── Fetch one run detail ───────────────────────────────────────────────────
  const loadRun = useCallback(async (id) => {
    setLoadingRun(true);
    try {
      const r    = await fetch(`${API_URL}/api/replay/raw-pattern-study/${id}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const data = await r.json();
      setRun(data.run || null);
    } catch {
      setRun(null);
    } finally {
      setLoadingRun(false);
    }
  }, []);

  // ── Poll if selected run is still running ──────────────────────────────────
  useEffect(() => {
    clearInterval(pollRef.current);
    if (!selectedId) return;
    loadRun(selectedId);
    if (run?.status === 'running') {
      pollRef.current = setInterval(() => {
        loadRun(selectedId);
        loadRuns();
      }, POLL_MS);
    }
    return () => clearInterval(pollRef.current);
  }, [selectedId, run?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Launch ─────────────────────────────────────────────────────────────────
  const handleLaunch = async () => {
    if (!psRunId) { setLaunchErr('Pump Study Run ID is required'); return; }
    setLaunching(true);
    setLaunchErr('');
    try {
      const r = await fetch(`${API_URL}/api/replay/raw-pattern-study/run`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          pump_study_run_id: Number(psRunId),
          ...(notes ? { notes } : {}),
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
      setSelectedId(data.raw_run_id);
      setPsRunId('');
      setNotes('');
      await loadRuns();
    } catch (e) {
      setLaunchErr(String(e));
    } finally {
      setLaunching(false);
    }
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <>
      <Head><title>Raw Pattern Study — Pump Scout</title></Head>
      <div className={styles.page}>
        <AppNav />

        <div className={styles.header}>
          <div className={styles.advisory}>Research</div>
          <h1 className={styles.title}>Raw Pattern Study</h1>
          <p className={styles.subtitle}>
            Feature discovery across 4× pump / normal winner / false positive / missed mover groups
          </p>
        </div>

        <div className={styles.layout}>
          {/* ── Left side panel ─────────────────────────────────────────── */}
          <div className={styles.sidePanel}>

            {/* Launch form */}
            <div className={styles.runPanel}>
              <div className={styles.runPanelTitle}>Launch New Run</div>
              {launchErr && <div className={styles.errorMsg}>{launchErr}</div>}
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Pump Study Run ID</label>
                <input
                  className={styles.formInput}
                  type="number"
                  min="1"
                  placeholder="e.g. 42"
                  value={psRunId}
                  onChange={e => setPsRunId(e.target.value)}
                />
              </div>
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Notes (optional)</label>
                <input
                  className={styles.formInput}
                  type="text"
                  placeholder="e.g. baseline v1"
                  value={notes}
                  onChange={e => setNotes(e.target.value)}
                />
              </div>
              <button
                className={styles.runBtn}
                disabled={launching}
                onClick={handleLaunch}
              >
                {launching ? 'Launching…' : 'Launch Run'}
              </button>
            </div>

            {/* Runs list */}
            <div className={styles.runsWrap}>
              <div className={styles.sectionTitle}>
                <span>Runs</span>
                <button className={styles.refreshBtn} onClick={loadRuns} title="Refresh">↻</button>
              </div>

              {loadingRuns && <div className={styles.statusMsg}>Loading…</div>}
              {runsError  && <div className={styles.errorMsg}>{runsError}</div>}
              {!loadingRuns && !runsError && runs.length === 0 && (
                <div className={styles.statusMsg}>No runs yet — launch one above.</div>
              )}

              {runs.length > 0 && (
                <table className={styles.historyTable}>
                  <thead>
                    <tr className={styles.historyHead}>
                      <th>ID</th>
                      <th>Status</th>
                      <th>Range</th>
                      <th>Daily</th>
                      <th>Eps</th>
                      <th>Cmp</th>
                      <th>Age</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map(r => (
                      <tr
                        key={r.id}
                        className={`${styles.historyRow}${selectedId === r.id ? ' ' + styles.historyRowActive : ''}`}
                        onClick={() => setSelectedId(r.id)}
                      >
                        <td><span className={styles.runId}>#{r.id}</span></td>
                        <td><StatusBadge status={r.status} /></td>
                        <td style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', lineHeight: 1.5 }}>
                          {fmtDate(r.start_date)}<br />{fmtDate(r.end_date)}
                        </td>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{fmtNum(r.raw_daily_count)}</td>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{fmtNum(r.episode_feature_count)}</td>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{fmtNum(r.comparison_count)}</td>
                        <td style={{ fontSize: 9, color: 'var(--text-muted)' }}>{ago(r.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>

          {/* ── Main panel ──────────────────────────────────────────────── */}
          <div className={styles.mainPanel}>
            {!selectedId && (
              <div className={styles.emptyState}>
                Select a run from the list, or launch a new one above.
              </div>
            )}

            {selectedId && loadingRun && (
              <div className={styles.statusMsg}>Loading run #{selectedId}…</div>
            )}

            {selectedId && !loadingRun && run && (
              <RunHeader run={run} />
            )}

            {selectedId && !loadingRun && !run && (
              <div className={styles.errorMsg}>
                Could not load run #{selectedId}.
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
