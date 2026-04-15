/**
 * Pump Study — 4× Historical Pump Research
 * Phase 5A: page shell + runs list + run selection.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import Head from 'next/head';
import AppNav from '../components/AppNav';
import styles from '../styles/PumpStudy.module.css';

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
  const ms = Date.now() - new Date(s).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 1)  return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const cls = {
    running:             styles.statusRunning,
    detecting:           styles.statusRunning,
    enriching:           styles.statusRunning,
    completed:           styles.statusCompleted,
    comparison_complete: styles.statusComplete2,
    failed:              styles.statusFailed,
  }[status] || '';
  return (
    <span className={`${styles.statusBadge} ${cls}`}>{status || 'unknown'}</span>
  );
}

// ── Runs list ─────────────────────────────────────────────────────────────────

function RunsList({ runs, selectedId, onSelect, loading }) {
  if (loading) {
    return <div className={styles.statusMsg}>Loading runs…</div>;
  }
  if (!runs.length) {
    return (
      <div className={styles.emptyMsg}>
        No runs found.
        <div className={styles.emptyHint}>
          Pump studies are launched via the backend API.<br />
          POST /api/replay/pump-study/run
        </div>
      </div>
    );
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className={styles.historyTable}>
        <thead>
          <tr className={styles.historyHead}>
            <th>ID</th>
            <th>Created</th>
            <th>Status</th>
            <th>Range</th>
            <th title="Raw detections before clustering">Raws</th>
            <th title="Merged clusters">Clust</th>
            <th title="4× episodes after dedup">Eps</th>
            <th title="Daily indicator snapshots">Snaps</th>
            <th title="Timeline milestone events">Events</th>
            <th>Min ×</th>
          </tr>
        </thead>
        <tbody>
          {runs.map(r => (
            <tr
              key={r.id}
              className={`${styles.historyRow} ${selectedId === r.id ? styles.historyRowActive : ''}`}
              onClick={() => onSelect(r.id)}
            >
              <td>
                <span className={styles.runId}>#{r.id}</span>
              </td>
              <td style={{ fontSize: 10, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>
                {fmtDate(r.created_at)}<br />
                <span style={{ color: 'var(--text-muted)', fontSize: 9 }}>{ago(r.created_at)}</span>
              </td>
              <td><StatusBadge status={r.status} /></td>
              <td style={{ fontSize: 10, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>
                {fmtDate(r.start_date)}<br />
                <span style={{ color: 'var(--text-muted)', fontSize: 9 }}>→ {fmtDate(r.end_date)}</span>
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                {fmtNum(r.raw_detection_count)}
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                {fmtNum(r.cluster_count)}
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700 }}>
                {fmtNum(r.episode_count)}
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                {fmtNum(r.snapshot_count)}
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                {fmtNum(r.event_count)}
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)' }}>
                {r.min_multiple != null ? `${r.min_multiple}×` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Run detail header (Phase 5A only — no tabs/content yet) ──────────────────

function RunDetailHeader({ run }) {
  if (!run) return null;

  const isRunning = ['running', 'detecting', 'enriching'].includes(run.status);

  const kpis = [
    { label: 'Raw Detections', value: fmtNum(run.raw_detection_count) },
    { label: 'Clusters',       value: fmtNum(run.cluster_count) },
    { label: 'Episodes',       value: fmtNum(run.episode_count) },
    { label: 'Snapshots',      value: fmtNum(run.snapshot_count) },
    { label: 'Events',         value: fmtNum(run.event_count) },
    { label: 'Window',         value: run.window_days != null ? `${run.window_days}d` : '—' },
    { label: 'Min Multiple',   value: run.min_multiple != null ? `${run.min_multiple}×` : '—' },
    { label: 'Min Volume',     value: run.min_volume != null ? fmtNum(run.min_volume) : '—' },
  ];

  return (
    <div className={styles.bundleSection}>
      {/* Status row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
        <StatusBadge status={run.status} />
        {isRunning && <span className={styles.pulsingDot} />}
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-dim)' }}>
          Run #{run.id}
        </span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
          {fmtDate(run.start_date)} → {fmtDate(run.end_date)}
        </span>
        <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 'auto' }}>
          Created {ago(run.created_at)}
        </span>
      </div>

      {/* KPI grid */}
      <div className={styles.summaryGrid}>
        {kpis.map(k => (
          <div key={k.label} className={styles.summaryKPI}>
            <div className={styles.kpiValue}>{k.value}</div>
            <div className={styles.kpiLabel}>{k.label}</div>
          </div>
        ))}
      </div>

      {/* Notes */}
      {run.notes?.run_summary && (
        <div className={styles.notesBlock} style={{ marginTop: 12 }}>
          {run.notes.run_summary}
        </div>
      )}

      {/* Placeholder for future tabs */}
      <div style={{
        marginTop: 16,
        padding: '14px 16px',
        background: 'var(--surface2)',
        border: '1px dashed var(--border2)',
        borderRadius: 'var(--r-md)',
        color: 'var(--text-muted)',
        fontSize: 11,
        textAlign: 'center',
      }}>
        Episodes, comparisons, clusters and timeline coming in Phase 5B+
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PumpStudyPage() {
  const [runs,        setRuns]        = useState([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [selectedId,  setSelectedId]  = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const [runLoading,  setRunLoading]  = useState(false);
  const pollRef = useRef(null);

  // ── Load runs list ────────────────────────────────────────────────────────

  const loadRuns = useCallback(async () => {
    setRunsLoading(true);
    try {
      const res  = await fetch(`${API_URL}/api/replay/pump-study/runs?limit=30`);
      const data = await res.json();
      setRuns(data.runs || []);
    } catch {
      // network failure — leave existing list intact
    } finally {
      setRunsLoading(false);
    }
  }, []);

  // ── Load single run detail ────────────────────────────────────────────────

  const loadRun = useCallback(async (runId) => {
    if (!runId) return;
    setRunLoading(true);
    try {
      const res  = await fetch(`${API_URL}/api/replay/pump-study/${runId}`);
      const data = await res.json();
      setSelectedRun(data.run || data);
    } catch {
      setSelectedRun(null);
    } finally {
      setRunLoading(false);
    }
  }, []);

  // ── Initial load ──────────────────────────────────────────────────────────

  useEffect(() => { loadRuns(); }, [loadRuns]);

  // ── Poll while run is active ──────────────────────────────────────────────

  useEffect(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }

    if (!selectedId) return;

    loadRun(selectedId);

    const isActive = !selectedRun ||
      ['running', 'detecting', 'enriching'].includes(selectedRun?.status);

    if (isActive) {
      pollRef.current = setInterval(() => {
        loadRun(selectedId);
        loadRuns();
      }, POLL_MS);
    }

    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [selectedId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Stop polling once run reaches terminal state
  useEffect(() => {
    const terminal = ['completed', 'comparison_complete', 'failed'];
    if (selectedRun && terminal.includes(selectedRun.status)) {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    }
  }, [selectedRun?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  function handleSelectRun(runId) {
    if (selectedId === runId) return; // already selected
    setSelectedId(runId);
    setSelectedRun(null);
  }

  return (
    <>
      <Head><title>Pump Study — Pump Scout</title></Head>
      <AppNav />

      <div className={styles.page}>
        {/* ── Header ──────────────────────────────────────────────────────── */}
        <div className={styles.header}>
          <div className={styles.advisory}>RESEARCH ONLY — NOT INVESTMENT ADVICE</div>
          <h1 className={styles.title}>4× Pump Study</h1>
          <p className={styles.subtitle}>
            Retrospective analysis of historical 4× moves — episode classification,
            signal attribution, and comparison groups.
          </p>
        </div>

        {/* ── Body ────────────────────────────────────────────────────────── */}
        <div style={{ padding: '0 var(--page-px)', display: 'flex', flexDirection: 'column', gap: 20 }}>

          {/* Runs section */}
          <div className={styles.bundleSection}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <div className={styles.bundleSectionTitle} style={{ margin: 0, border: 'none', padding: 0 }}>
                PUMP STUDY RUNS
              </div>
              <button
                className={styles.exportBtn}
                onClick={loadRuns}
                disabled={runsLoading}
              >
                {runsLoading ? 'Refreshing…' : 'Refresh'}
              </button>
            </div>
            <div style={{ height: 1, background: 'var(--border)', margin: '10px 0 14px' }} />
            <RunsList
              runs={runs}
              selectedId={selectedId}
              onSelect={handleSelectRun}
              loading={runsLoading}
            />
          </div>

          {/* Selected run detail */}
          {selectedId && (
            <div>
              {runLoading && !selectedRun && (
                <div className={styles.statusMsg}>Loading run #{selectedId}…</div>
              )}
              {selectedRun && <RunDetailHeader run={selectedRun} />}
            </div>
          )}

        </div>
      </div>
    </>
  );
}
