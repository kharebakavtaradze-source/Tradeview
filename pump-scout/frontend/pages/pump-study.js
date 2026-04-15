/**
 * Pump Study — 4× Historical Pump Research
 * Phase 5A: page shell + runs list + run selection.
 * Phase 5B: episodes table with filters + row selection.
 * Phase 5C: episode detail panel.
 * Phase 5D: global summary — family distribution, comparison groups, pre-pump signals.
 * Phase 6:  AI recommendation layer.
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

function fmtX(n) {
  if (n == null) return '—';
  return `${Number(n).toFixed(2)}×`;
}

function fmtPct(n, sign = false) {
  if (n == null) return '—';
  const v = Number(n);
  return `${sign && v > 0 ? '+' : ''}${v.toFixed(1)}%`;
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

// ── Pump-type badge ───────────────────────────────────────────────────────────

const PUMP_TYPE_CFG = {
  ACCUMULATION_TO_EXPANSION: { short: 'ACC→EXP',   color: '#00e5ff' },
  POST_COMPRESSION_BREAKOUT: { short: 'POST-COMP',  color: '#00ff88' },
  CATALYST_IGNITION:         { short: 'CATALYST',   color: '#ffd600' },
  GAP_AND_GO:                { short: 'GAP&GO',     color: '#ff8800' },
  LOW_FLOAT_VELOCITY:        { short: 'LO-FLOAT',   color: '#ff4400' },
  CHAOTIC_SPECULATIVE:       { short: 'CHAOTIC',    color: '#cc44ff' },
  SECTOR_SYMPATHY:           { short: 'SYMPATHY',   color: '#80aaff' },
  UNKNOWN:                   { short: 'UNKNOWN',    color: '#555555' },
};

function PumpTypeBadge({ type }) {
  if (!type) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const cfg   = PUMP_TYPE_CFG[type] || { short: type, color: '#888' };
  const color = cfg.color;
  return (
    <span style={{
      color,
      fontWeight: 700,
      fontSize: 9,
      letterSpacing: '0.05em',
      padding: '2px 6px',
      borderRadius: 'var(--r-pill)',
      background: `${color}18`,
      border: `1px solid ${color}44`,
      whiteSpace: 'nowrap',
      fontFamily: 'var(--font-mono)',
    }}>
      {cfg.short}
    </span>
  );
}

// ── Phase tag ─────────────────────────────────────────────────────────────────

const PHASE_COLOR = { PRE: 'var(--cyan)', PUMP: 'var(--lime)', POST: 'var(--amber)' };

function PhaseTag({ phase }) {
  const color = PHASE_COLOR[phase] || 'var(--text-muted)';
  return (
    <span style={{
      color, fontWeight: 700, fontSize: 9, letterSpacing: '0.07em',
      padding: '1px 6px', borderRadius: 'var(--r-sm)',
      border: `1px solid ${color}55`, background: `${color}18`,
      whiteSpace: 'nowrap',
    }}>{phase}</span>
  );
}

// ── Event type config ─────────────────────────────────────────────────────────

const EVENT_CFG = {
  first_abnormal_volume_day:     { color: 'var(--amber)',  label: 'ABNORMAL VOL'    },
  first_compression_day:         { color: 'var(--cyan)',   label: 'BB COMPRESSION'  },
  first_ribbon_constructive_day: { color: 'var(--lime)',   label: 'RIBBON QUAL'     },
  first_ignition_day:            { color: '#ffd600',       label: 'IGNITION'        },
  first_accumulation_like_day:   { color: 'var(--accent)', label: 'ACCUMULATION'    },
  first_spring_test_lps_day:     { color: '#80aaff',       label: 'SPRING/LPS'      },
  breakout_day:                  { color: 'var(--lime)',   label: 'BREAKOUT'        },
  retest_day:                    { color: 'var(--amber)',  label: 'RETEST'          },
  first_vertical_expansion_day:  { color: '#ff8800',       label: 'VERT EXPANSION'  },
  peak_day:                      { color: 'var(--red)',    label: 'PEAK'            },
  fade_day:                      { color: 'var(--red)',    label: 'FADE'            },
  dump_day:                      { color: '#ff4444',       label: 'DUMP'            },
};

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

// ── Episode Detail (Phase 5C) ─────────────────────────────────────────────────

function EpisodeDetail({ runId, episodeId, onClose }) {
  const [ep,       setEp]       = useState(null);
  const [snaps,    setSnaps]    = useState([]);
  const [events,   setEvents]   = useState([]);
  const [cluster,  setCluster]  = useState(null);
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState('');
  const [innerTab, setInnerTab] = useState('events');

  useEffect(() => {
    if (!runId || !episodeId) return;
    setLoading(true);
    setError('');
    setEp(null); setSnaps([]); setEvents([]); setCluster(null);

    Promise.all([
      fetch(`${API_URL}/api/replay/pump-study/${runId}/episodes/${episodeId}`)
        .then(r => r.ok ? r.json() : Promise.reject(`HTTP ${r.status}`)),
      fetch(`${API_URL}/api/replay/pump-study/${runId}/daily-snapshots?episode_id=${episodeId}&limit=300`)
        .then(r => r.ok ? r.json() : { snapshots: [] }),
      fetch(`${API_URL}/api/replay/pump-study/${runId}/timeline?episode_id=${episodeId}`)
        .then(r => r.ok ? r.json() : { events: [] }),
    ])
      .then(([epData, snapData, evData]) => {
        const episode = epData.episode || epData;
        setEp(episode);
        setSnaps(snapData.snapshots || []);
        setEvents(evData.events || []);
        // Cluster is returned directly by the episode detail endpoint
        setCluster(epData.cluster || null);
      })
      .catch(err => setError(String(err)))
      .finally(() => setLoading(false));
  }, [runId, episodeId]);

  if (loading) {
    return (
      <div className={styles.episodeDetail}>
        <div className={styles.statusMsg}>Loading episode #{episodeId}…</div>
      </div>
    );
  }
  if (error) {
    return (
      <div className={styles.episodeDetail}>
        <div className={styles.errorMsg}>{error}</div>
        <button className={styles.closeBtn} onClick={onClose}>Close</button>
      </div>
    );
  }
  if (!ep) return null;

  // ── Section A: build KPI list ───────────────────────────────────────────────
  const caught = ep.caught_by_scanner;
  const summaryKPIs = [
    { label: 'Multiple',      val: fmtX(ep.pump_multiple),                           color: 'var(--lime)' },
    { label: 'Return',        val: ep.pump_return_pct != null ? fmtPct(ep.pump_return_pct, true) : '—', color: 'var(--lime)' },
    { label: 'Days to Peak',  val: ep.pump_days_to_peak ?? '—' },
    { label: 'Days to 2×',    val: ep.days_to_double ?? '—' },
    { label: 'Caught',        val: caught == null ? '—' : caught ? 'CAUGHT' : 'MISSED',
                              color: caught == null ? null : caught ? 'var(--lime)' : 'var(--red)' },
    { label: 'Ribbon',        val: ep.had_ribbon ? 'YES' : 'NO',
                              color: ep.had_ribbon ? 'var(--lime)' : 'var(--text-muted)' },
    { label: 'Ignition',      val: ep.had_ignition ? 'YES' : 'NO',
                              color: ep.had_ignition ? 'var(--cyan)' : 'var(--text-muted)' },
    { label: 'Wyckoff',       val: ep.strongest_wyckoff_state || '—' },
    { label: 'Max Gap',       val: ep.largest_gap_pct != null ? fmtPct(ep.largest_gap_pct) : '—' },
    { label: 'Max Vol',       val: ep.max_volume_anomaly != null ? `${Number(ep.max_volume_anomaly).toFixed(1)}×` : '—',
                              color: ep.max_volume_anomaly >= 3 ? 'var(--amber)' : null },
    { label: 'Ignition Q',    val: ep.ignition_quality ?? '—' },
    { label: 'Ign Bucket',    val: ep.ignition_bucket || '—' },
    { label: 'Avg Tox PRE',   val: ep.avg_toxicity_pre != null ? Number(ep.avg_toxicity_pre).toFixed(0) : '—' },
    { label: 'Max Tox PRE',   val: ep.max_toxicity_pre != null ? Number(ep.max_toxicity_pre).toFixed(0) : '—' },
  ];

  // Phase counts
  const phaseCounts = { PRE: 0, PUMP: 0, POST: 0 };
  snaps.forEach(s => { if (phaseCounts[s.window_phase] != null) phaseCounts[s.window_phase]++; });

  const INNER_TABS = [
    { key: 'events',    label: `Events (${events.length})` },
    { key: 'snapshots', label: `Snapshots (${snaps.length})` },
    { key: 'cluster',   label: 'Cluster' },
  ];

  return (
    <div className={styles.episodeDetail}>

      {/* ── Header row ─────────────────────────────────────────────────────── */}
      <div className={styles.detailHeader}>
        <div>
          <span className={styles.detailSymbol}>{ep.symbol}</span>
          <span className={styles.detailMeta}>
            {fmtDate(ep.pump_start_date)} → {fmtDate(ep.pump_peak_date)}
          </span>
          <PumpTypeBadge type={ep.pump_type} />
        </div>
        <button className={styles.closeBtn} onClick={onClose}>✕ Close</button>
      </div>

      {/* ── Section A: KPI summary ─────────────────────────────────────────── */}
      <div className={styles.detailKPIGrid}>
        {summaryKPIs.map(k => (
          <div key={k.label} className={styles.detailKPI}>
            <div className={styles.kpiLabel}>{k.label}</div>
            <div className={styles.kpiValue}
              style={{ fontSize: 15, color: k.color || 'var(--text)', fontFamily: 'var(--font-mono)' }}>
              {k.val}
            </div>
          </div>
        ))}
      </div>

      {/* Phase bar */}
      <div className={styles.phaseBar}>
        {['PRE', 'PUMP', 'POST'].map(ph => (
          <span key={ph} className={styles.phaseSegment}>
            <PhaseTag phase={ph} />
            <span style={{ fontFamily: 'var(--font-mono)', marginLeft: 5, fontSize: 11, fontWeight: 700 }}>
              {phaseCounts[ph]}d
            </span>
          </span>
        ))}
        {ep.worst_post_return_from_start != null && (
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text-muted)' }}>
            worst POST from start:&nbsp;
            <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--amber)', fontWeight: 700 }}>
              {fmtPct(ep.worst_post_return_from_start, true)}
            </span>
          </span>
        )}
      </div>

      {/* ── Inner tabs ────────────────────────────────────────────────────── */}
      <div className={styles.tabRow}>
        {INNER_TABS.map(t => (
          <button key={t.key}
            className={`${styles.tab} ${innerTab === t.key ? styles.tabActive : ''}`}
            onClick={() => setInnerTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Section B: Timeline events ─────────────────────────────────────── */}
      {innerTab === 'events' && (
        <div className={styles.eventsWrap}>
          {events.length === 0 && <div className={styles.emptyMsg}>No timeline events recorded.</div>}
          {events.map((ev, i) => {
            const cfg   = EVENT_CFG[ev.event_type] || { color: 'var(--text-muted)', label: ev.event_type };
            const color = cfg.color;
            return (
              <div key={i} className={styles.eventCard} style={{ borderLeftColor: color }}>
                <div className={styles.eventTop}>
                  <span className={styles.eventType} style={{ color }}>{cfg.label}</span>
                  <span className={styles.eventDate}>{fmtDate(ev.event_date)}</span>
                  {ev.days_before_pump != null && (
                    <span className={styles.eventDays}>
                      {ev.days_before_pump < 0
                        ? `+${Math.abs(ev.days_before_pump)}d after start`
                        : ev.days_before_pump === 0 ? 'start day'
                        : `${ev.days_before_pump}d before start`}
                    </span>
                  )}
                  {ev.event_value != null && (
                    <span className={styles.eventVal} style={{ color, marginLeft: 'auto' }}>
                      {typeof ev.event_value === 'number'
                        ? Number(ev.event_value).toFixed(2)
                        : ev.event_value}
                    </span>
                  )}
                </div>
                {ev.event_note && (
                  <div className={styles.eventNote}>{ev.event_note}</div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ── Section C: Daily snapshots ─────────────────────────────────────── */}
      {innerTab === 'snapshots' && (
        <div style={{ overflowX: 'auto' }}>
          {snaps.length === 0 && <div className={styles.emptyMsg}>No snapshot data.</div>}
          {snaps.length > 0 && (
            <table className={styles.snapTable}>
              <thead>
                <tr>
                  <th>Phase</th>
                  <th>Date</th>
                  <th title="Relative to pump start">Day</th>
                  <th title="Relative to peak">↑Peak</th>
                  <th>Close</th>
                  <th>Vol</th>
                  <th title="Overnight gap %">Gap%</th>
                  <th title="Daily return">Day%</th>
                  <th title="Cumulative return from start">Cum%</th>
                  <th>Ribbon</th>
                  <th>Wyckoff</th>
                  <th title="Ignition signal">Ign</th>
                  <th title="Sequence type">Seq</th>
                  <th title="Structural bias">Bias</th>
                  <th title="Toxicity score">Tox</th>
                </tr>
              </thead>
              <tbody>
                {snaps.map((s, i) => {
                  const bg = s.window_phase === 'PUMP' ? 'rgba(0,255,136,0.025)'
                           : s.window_phase === 'POST' ? 'rgba(255,180,0,0.025)' : undefined;
                  const dayNum  = s.relative_day_from_start;
                  const peakNum = s.relative_day_from_peak;
                  // Extended fields — try direct first, then snapshot sub-dict
                  const sd      = s.snapshot_data || s.snapshot || {};
                  const ign     = s.ignition_signal ?? sd.ignition?.ignition_signal ?? sd.ignition_signal ?? '—';
                  const seqType = s.sequence_type   ?? sd.regime?.sequence_type    ?? '—';
                  const bias    = s.structural_bias ?? sd.regime?.structural_bias  ?? '—';
                  const tox     = s.toxicity_score  ?? sd.toxicity?.toxicity_score ?? null;
                  const ribbon  = (s.ribbon_class || '—').replace('RIBBON_', '');
                  return (
                    <tr key={i} className={styles.snapRow} style={{ background: bg }}>
                      <td><PhaseTag phase={s.window_phase} /></td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10, whiteSpace: 'nowrap' }}>
                        {fmtDate(s.date)}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)', textAlign: 'right' }}>
                        {dayNum != null ? (dayNum >= 0 ? `+${dayNum}` : dayNum) : '—'}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', textAlign: 'right' }}>
                        {peakNum != null ? (peakNum >= 0 ? `+${peakNum}` : peakNum) : '—'}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                        {s.close != null ? `$${Number(s.close).toFixed(2)}` : '—'}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
                        {s.volume != null ? fmtNum(s.volume) : '—'}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)',
                                   color: s.gap_pct > 0 ? 'var(--lime)' : s.gap_pct < 0 ? 'var(--red)' : 'var(--text-muted)' }}>
                        {s.gap_pct != null ? fmtPct(s.gap_pct, true) : '—'}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)',
                                   color: s.daily_return_pct > 0 ? 'var(--lime)' : s.daily_return_pct < 0 ? 'var(--red)' : 'var(--text-muted)' }}>
                        {s.daily_return_pct != null ? fmtPct(s.daily_return_pct, true) : '—'}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700,
                                   color: (s.cum_return_pct || s.cumulative_return_from_start) > 0 ? 'var(--lime)' : 'var(--red)' }}>
                        {(s.cum_return_pct ?? s.cumulative_return_from_start) != null
                          ? fmtPct(s.cum_return_pct ?? s.cumulative_return_from_start, true) : '—'}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 9,
                                   color: ribbon !== '—' && ribbon !== 'NONE' ? 'var(--lime)' : 'var(--text-muted)' }}>
                        {ribbon}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)' }}>
                        {s.wyckoff_state || '—'}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)' }}>
                        {String(ign).replace('_IGNITION', '').replace('IGNITION_', '')}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)' }}>
                        {seqType !== '—' ? String(seqType).slice(0, 8) : '—'}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)' }}>
                        {bias !== '—' ? String(bias).slice(0, 6) : '—'}
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 9,
                                   color: tox >= 45 ? 'var(--red)' : tox >= 20 ? 'var(--amber)' : 'var(--text-muted)' }}>
                        {tox != null ? tox : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* ── Section D: Cluster info ─────────────────────────────────────────── */}
      {innerTab === 'cluster' && (
        <div>
          {!cluster && (
            <div className={styles.emptyMsg}>
              No cluster match found for this episode.
              <div className={styles.emptyHint}>
                cluster_id: {ep.cluster_id ?? '—'} · symbol: {ep.symbol}
              </div>
            </div>
          )}
          {cluster && (
            <div className={styles.clusterCard}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)',
                            letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 4 }}>
                Cluster
              </div>
              {[
                ['Cluster ID',     cluster.cluster_id ?? '—'],
                ['Symbol',         cluster.symbol],
                ['Cluster Start',  fmtDate(cluster.cluster_start_date)],
                ['Cluster End',    fmtDate(cluster.cluster_end_date)],
                ['Canonical Start', fmtDate(cluster.canonical_start_date)],
                ['Canonical Peak',  fmtDate(cluster.canonical_peak_date)],
                ['Raw Detections', Array.isArray(cluster.raw_detections)
                                    ? cluster.raw_detections.length
                                    : (cluster.raw_detection_count ?? '—')],
              ].map(([label, val]) => (
                <div key={label} className={styles.clusterRow}>
                  <span className={styles.clusterRowLabel}>{label}</span>
                  <span className={styles.clusterRowVal}>{val}</span>
                </div>
              ))}

              {/* Raw detections sub-table */}
              {Array.isArray(cluster.raw_detections) && cluster.raw_detections.length > 0 && (
                <>
                  <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)',
                                letterSpacing: '0.06em', textTransform: 'uppercase', marginTop: 10 }}>
                    Raw Detections ({cluster.raw_detections.length})
                  </div>
                  <div style={{ overflowX: 'auto' }}>
                    <table className={styles.rawDetTable}>
                      <thead>
                        <tr>
                          <th>Start</th>
                          <th>Peak</th>
                          <th>Multiple</th>
                          <th>Return</th>
                          <th>Days</th>
                        </tr>
                      </thead>
                      <tbody>
                        {cluster.raw_detections.map((d, i) => (
                          <tr key={i}>
                            <td>{fmtDate(d.window_start_date)}</td>
                            <td>{fmtDate(d.window_peak_date)}</td>
                            <td style={{ color: 'var(--lime)', fontWeight: 700 }}>{fmtX(d.multiple)}</td>
                            <td>{d.return_pct != null ? fmtPct(d.return_pct, true) : '—'}</td>
                            <td>{d.days_to_peak ?? '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </div>
          )}
        </div>
      )}

    </div>
  );
}

// ── Episodes table (Phase 5B) ─────────────────────────────────────────────────

const PUMP_TYPES = [
  '', 'ACCUMULATION_TO_EXPANSION', 'POST_COMPRESSION_BREAKOUT',
  'CATALYST_IGNITION', 'GAP_AND_GO', 'LOW_FLOAT_VELOCITY',
  'CHAOTIC_SPECULATIVE', 'SECTOR_SYMPATHY', 'UNKNOWN',
];

function EpisodesTable({ runId, episodes, loading, error, selectedEpId, onSelectEp, onReload }) {
  // ── Local filter state ──────────────────────────────────────────────────────
  const [symInput,    setSymInput]    = useState('');
  const [typeFilter,  setTypeFilter]  = useState('');
  const [mulInput,    setMulInput]    = useState('');
  const [caughtMode,  setCaughtMode]  = useState('all'); // 'all' | 'caught' | 'missed'

  // Expose composed filter object to parent via callback when filters change
  useEffect(() => {
    onReload({ symbol: symInput.trim().toUpperCase(), pump_type: typeFilter,
               min_multiple: mulInput.trim(), caught_mode: caughtMode });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeFilter, caughtMode]);

  function applyText() {
    onReload({ symbol: symInput.trim().toUpperCase(), pump_type: typeFilter,
               min_multiple: mulInput.trim(), caught_mode: caughtMode });
  }

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <div>
      {/* Filter row */}
      <div className={styles.filterRow}>
        <input
          className={styles.filterInput}
          placeholder="Symbol…"
          value={symInput}
          onChange={e => setSymInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && applyText()}
        />
        <select
          className={styles.filterSelect}
          value={typeFilter}
          onChange={e => setTypeFilter(e.target.value)}
        >
          {PUMP_TYPES.map(t => (
            <option key={t} value={t}>{t ? (PUMP_TYPE_CFG[t]?.short || t) : 'All Types'}</option>
          ))}
        </select>
        <input
          className={styles.filterInput}
          style={{ width: 72 }}
          placeholder="Min ×"
          value={mulInput}
          onChange={e => setMulInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && applyText()}
        />
        <div className={styles.modeToggle}>
          {[['all', 'All'], ['caught', 'Caught'], ['missed', 'Missed']].map(([v, label]) => (
            <button
              key={v}
              type="button"
              className={`${styles.modeBtn} ${caughtMode === v ? styles.modeBtnActive : ''}`}
              onClick={() => setCaughtMode(v)}
            >{label}</button>
          ))}
        </div>
        <button className={styles.exportBtn} onClick={applyText}>Apply</button>
        {loading && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>Loading…</span>}
      </div>

      {/* States */}
      {error && (
        <div className={styles.errorMsg}>{error}</div>
      )}
      {!loading && !error && episodes.length === 0 && (
        <div className={styles.emptyMsg}>No episodes match the current filters.</div>
      )}

      {/* Table */}
      {episodes.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table className={styles.episodeTable}>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Start</th>
                <th>Peak</th>
                <th title="Peak / start price">Multiple</th>
                <th title="% gain from start to peak">Return</th>
                <th title="Trading days from start to peak">Days</th>
                <th>Family</th>
                <th title="Was it in scanner output on start date?">Caught</th>
                <th title="Had qualifying ribbon class in PRE window">Ribbon</th>
                <th title="Had ignition signal in PRE window">Ignition</th>
                <th title="Highest Wyckoff state reached in PRE window">Wyckoff</th>
                <th title="Largest gap up % in PRE+PUMP window">Max Gap</th>
                <th title="Max volume vs 20-day average">Max Vol</th>
              </tr>
            </thead>
            <tbody>
              {episodes.map(ep => {
                const caught = ep.caught_by_scanner;
                return (
                  <tr
                    key={ep.id}
                    className={`${styles.episodeRow} ${selectedEpId === ep.id ? styles.episodeRowActive : ''}`}
                    onClick={() => onSelectEp(ep.id)}
                  >
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--accent)' }}>
                      {ep.symbol}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10, whiteSpace: 'nowrap' }}>
                      {fmtDate(ep.pump_start_date)}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10, whiteSpace: 'nowrap' }}>
                      {fmtDate(ep.pump_peak_date)}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--lime)' }}>
                      {fmtX(ep.pump_multiple)}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--lime)' }}>
                      {ep.pump_return_pct != null ? fmtPct(ep.pump_return_pct, true) : '—'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
                      {ep.pump_days_to_peak ?? '—'}
                    </td>
                    <td><PumpTypeBadge type={ep.pump_type} /></td>
                    <td>
                      {caught == null
                        ? <span style={{ color: 'var(--text-muted)' }}>—</span>
                        : <span style={{ fontWeight: 700, fontSize: 10, color: caught ? 'var(--lime)' : 'var(--red)' }}>
                            {caught ? 'CAUGHT' : 'MISSED'}
                          </span>
                      }
                    </td>
                    <td style={{ fontWeight: 700, fontSize: 10,
                                 color: ep.had_ribbon ? 'var(--lime)' : 'var(--text-muted)' }}>
                      {ep.had_ribbon ? 'YES' : 'NO'}
                    </td>
                    <td style={{ fontWeight: 700, fontSize: 10,
                                 color: ep.had_ignition ? 'var(--cyan)' : 'var(--text-muted)' }}>
                      {ep.had_ignition ? 'YES' : 'NO'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-dim)' }}>
                      {ep.strongest_wyckoff_state || '—'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
                      {ep.largest_gap_pct != null ? fmtPct(ep.largest_gap_pct) : '—'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)',
                                 color: ep.max_volume_anomaly >= 3 ? 'var(--amber)' : 'var(--text-dim)' }}>
                      {ep.max_volume_anomaly != null ? `${Number(ep.max_volume_anomaly).toFixed(1)}×` : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', padding: '6px 2px' }}>
            {episodes.length} episode{episodes.length !== 1 ? 's' : ''}
            {selectedEpId && ' — click again to deselect'}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Launch form ───────────────────────────────────────────────────────────────

function RunLaunchForm({ onLaunch, launching, launchError }) {
  // Sensible defaults: 2-year window ending yesterday
  const yesterday  = new Date(); yesterday.setDate(yesterday.getDate() - 1);
  const twoYrAgo   = new Date(); twoYrAgo.setFullYear(twoYrAgo.getFullYear() - 2);
  const isoYday    = yesterday.toISOString().slice(0, 10);
  const iso2yr     = twoYrAgo.toISOString().slice(0, 10);

  const [startDate,      setStartDate]      = useState(iso2yr);
  const [endDate,        setEndDate]        = useState(isoYday);
  const [windowDays,     setWindowDays]     = useState(14);
  const [minMultiple,    setMinMultiple]    = useState(4.0);
  const [universeLimit,  setUniverseLimit]  = useState(0);

  function handleSubmit(e) {
    e.preventDefault();
    onLaunch({
      start_date:     startDate,
      end_date:       endDate,
      window_days:    Number(windowDays),
      min_multiple:   Number(minMultiple),
      universe_limit: Number(universeLimit),
    });
  }

  return (
    <form onSubmit={handleSubmit}>
      <div className={styles.launchFormGrid}>
        <div className={styles.formGroup} style={{ marginBottom: 0 }}>
          <label className={styles.formLabel}>Start Date</label>
          <input className={styles.formInput} type="date"
            value={startDate} onChange={e => setStartDate(e.target.value)} required />
        </div>
        <div className={styles.formGroup} style={{ marginBottom: 0 }}>
          <label className={styles.formLabel}>End Date</label>
          <input className={styles.formInput} type="date"
            value={endDate} onChange={e => setEndDate(e.target.value)} required />
        </div>
        <div className={styles.formGroup} style={{ marginBottom: 0 }}>
          <label className={styles.formLabel}>Window (days)</label>
          <select className={styles.formSelect} value={windowDays}
            onChange={e => setWindowDays(e.target.value)}>
            <option value={14}>14</option>
            <option value={30}>30</option>
            <option value={60}>60</option>
            <option value={90}>90</option>
          </select>
        </div>
        <div className={styles.formGroup} style={{ marginBottom: 0 }}>
          <label className={styles.formLabel}>Min Multiple</label>
          <select className={styles.formSelect} value={minMultiple}
            onChange={e => setMinMultiple(e.target.value)}>
            <option value={3.0}>3×</option>
            <option value={4.0}>4×</option>
            <option value={5.0}>5×</option>
          </select>
        </div>
        <div className={styles.formGroup} style={{ marginBottom: 0 }}>
          <label className={styles.formLabel} title="0 = full universe">Universe Limit</label>
          <select className={styles.formSelect} value={universeLimit}
            onChange={e => setUniverseLimit(e.target.value)}>
            <option value={0}>All</option>
            <option value={100}>100</option>
            <option value={500}>500</option>
            <option value={1000}>1000</option>
          </select>
        </div>
      </div>
      <div className={styles.launchSubmitRow}>
        <button className={styles.runBtn} type="submit" disabled={launching}
          style={{ width: 'auto', padding: '8px 24px' }}>
          {launching ? 'Launching…' : 'Run Pump Study'}
        </button>
        {launchError && (
          <span className={styles.errorMsg} style={{ padding: '4px 10px', margin: 0 }}>
            {launchError}
          </span>
        )}
      </div>
    </form>
  );
}

// ── Runs list ─────────────────────────────────────────────────────────────────

function RunsList({ runs, selectedId, onSelect, loading, error, onRetry }) {
  if (loading) {
    return <div className={styles.statusMsg}>Loading runs…</div>;
  }

  // Backend unreachable or returned an error
  if (error) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div className={styles.errorMsg}>
          Could not load runs: {error}
        </div>
        <button className={styles.exportBtn} onClick={onRetry} style={{ alignSelf: 'flex-start' }}>
          Retry
        </button>
      </div>
    );
  }

  // DB is genuinely empty
  if (!runs.length) {
    return (
      <div className={styles.emptyMsg}>
        No pump study runs yet.
        <div className={styles.emptyHint}>Use the form above to launch your first study.</div>
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
              <td><span className={styles.runId}>#{r.id}</span></td>
              <td style={{ fontSize: 10, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>
                {fmtDate(r.created_at)}<br />
                <span style={{ color: 'var(--text-muted)', fontSize: 9 }}>{ago(r.created_at)}</span>
              </td>
              <td><StatusBadge status={r.status} /></td>
              <td style={{ fontSize: 10, color: 'var(--text-dim)', whiteSpace: 'nowrap' }}>
                {fmtDate(r.start_date)}<br />
                <span style={{ color: 'var(--text-muted)', fontSize: 9 }}>→ {fmtDate(r.end_date)}</span>
              </td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{fmtNum(r.raw_detection_count)}</td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{fmtNum(r.cluster_count)}</td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700 }}>{fmtNum(r.episode_count)}</td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{fmtNum(r.snapshot_count)}</td>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{fmtNum(r.event_count)}</td>
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

// ── AI Recommendation Section (Phase 6) ──────────────────────────────────────

const TERMINAL_STATUSES = new Set(['completed', 'comparison_complete']);

function AISummarySection({ runId, runStatus }) {
  const [data,    setData]    = useState(null);
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState('');
  const [tried,   setTried]   = useState(false);

  const canGenerate = TERMINAL_STATUSES.has(runStatus);

  // Auto-fetch cached result (no generation) on mount
  useEffect(() => {
    if (!runId || !canGenerate) return;
    setData(null); setError(''); setTried(false);
    fetch(`${API_URL}/api/replay/pump-study/${runId}/ai-summary`)
      .then(r => {
        if (r.status === 404) return null;          // not generated yet — ok
        if (r.status === 409) return null;          // run not complete — ok
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(d => { if (d) { setData(d); setTried(true); } })
      .catch(err => setError(err.message));
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleGenerate() {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API_URL}/api/replay/pump-study/${runId}/ai-summary`);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      setData(await res.json());
      setTried(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  // Run not terminal
  if (!canGenerate) {
    return (
      <div className={styles.statusMsg}>
        AI summary available once run reaches completed status.
      </div>
    );
  }

  // Not yet generated
  if (!data && !tried) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {error && <div className={styles.errorMsg}>{error}</div>}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button className={styles.aiGenerateBtn} onClick={handleGenerate} disabled={loading}>
            {loading ? 'Generating…' : 'Generate AI Summary'}
          </button>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
            Analyzes stored evidence — no live data fetched
          </span>
        </div>
      </div>
    );
  }

  if (!data) return null;

  const a = data.analysis || {};
  const ev = data.evidence_summary || {};

  const SECTION_BLOCKS = [
    { key: 'patterns',             title: 'Repeated Patterns Before 4× Pumps',         items: a.patterns },
    { key: 'earliest_signals',     title: 'Earliest Appearing Signals',                 items: a.earliest_signals },
    { key: 'true_vs_false_positive', title: 'True Pumps vs False Positives',            items: a.true_vs_false_positive },
    { key: 'true_vs_normal_winner',  title: 'True 4× Pumps vs Normal Winners (1.4–3.99×)', items: a.true_vs_normal_winner },
  ];

  return (
    <div className={styles.aiSection}>

      {/* Recommendation badge */}
      {a.recommendation && (
        <div>
          <div className={styles.bundleSectionTitle} style={{ marginBottom: 8 }}>ENGINE RECOMMENDATION</div>
          <div className={styles.aiRecommendationBadge}>
            {a.recommendation}
          </div>
          {a.recommendation_rationale && (
            <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 8, lineHeight: 1.6 }}>
              {a.recommendation_rationale}
            </div>
          )}
          {a.closest_existing_engine && (
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
              Closest existing engine: <span style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                {a.closest_existing_engine}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Analysis blocks */}
      {SECTION_BLOCKS.map(({ key, title, items }) => (
        Array.isArray(items) && items.length > 0 ? (
          <div key={key} className={styles.aiBlock}>
            <div className={styles.aiBlockTitle}>{title}</div>
            {items.map((item, i) => (
              <div key={i} className={styles.aiBullet}>{item}</div>
            ))}
          </div>
        ) : null
      ))}

      {/* Limitations */}
      {Array.isArray(a.limitations) && a.limitations.length > 0 && (
        <div className={styles.aiBlock} style={{ borderColor: 'var(--amber-border)' }}>
          <div className={styles.aiBlockTitle} style={{ color: 'var(--amber)' }}>
            LIMITATIONS &amp; MISSING DATA
          </div>
          {a.limitations.map((lim, i) => (
            <div key={i} className={styles.aiLimitation}>{lim}</div>
          ))}
        </div>
      )}

      {/* Meta footer */}
      <div className={styles.aiMeta}>
        Model: {data.model_used || 'claude-haiku'}
        {ev.episodes_analyzed != null && ` · ${ev.episodes_analyzed} episodes analyzed`}
        {ev.event_types_found  != null && ` · ${ev.event_types_found} event types`}
        {ev.groups_found       != null && ` · ${ev.groups_found} comparison groups`}
        {data.cached && ' · cached result'}
        {data.generated_at && ` · ${String(data.generated_at).slice(0, 16).replace('T', ' ')}`}
      </div>

      {/* Re-generate option (only if cached) */}
      {data.cached && (
        <div>
          <button
            className={styles.exportBtn}
            onClick={() => { setData(null); setTried(false); }}
          >
            Re-generate
          </button>
        </div>
      )}

    </div>
  );
}

// ── Global Summary helpers (Phase 5D) ────────────────────────────────────────

// Safely read one stat from group_stats or stats_json
function gs(group, field, stat = 'mean') {
  const src = group?.group_stats || group?.stats_json || {};
  return src[field]?.[stat] ?? null;
}

function fmtRate(n) {
  if (n == null) return '—';
  return `${(Number(n) * 100).toFixed(0)}%`;
}

// Inline rate bar: value is 0–1 float
function RateBar({ value }) {
  if (value == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const pct   = Math.min(100, Math.max(0, Number(value) * 100));
  const color = pct >= 60 ? 'var(--lime)' : pct >= 30 ? 'var(--amber)' : 'var(--text-muted)';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 90 }}>
      <span style={{ fontFamily: 'var(--font-mono)', color, fontWeight: 700,
                     fontSize: 11, minWidth: 34, textAlign: 'right' }}>
        {fmtRate(value)}
      </span>
      <div style={{ flex: 1, height: 4, background: 'var(--border)',
                    borderRadius: 'var(--r-pill)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`,
                      background: color, borderRadius: 'var(--r-pill)' }} />
      </div>
    </div>
  );
}

const GROUP_ORDER = ['4x_pump', 'normal_winner', 'false_positive', 'missed_mover'];
const GROUP_CFG = {
  '4x_pump':      { label: '4× Pump',       color: 'var(--lime)'  },
  normal_winner:  { label: 'Normal Winner',  color: 'var(--cyan)'  },
  false_positive: { label: 'False Positive', color: 'var(--red)'   },
  missed_mover:   { label: 'Missed Mover',   color: 'var(--amber)' },
};

// Signal rows for Section C — each row is one metric×stat combination
const SIGNAL_ROWS = [
  { key: 'had_ribbon',               label: 'Had Ribbon',          stat: 'mean',   isRate: true },
  { key: 'had_ignition',             label: 'Had Ignition',        stat: 'mean',   isRate: true },
  { key: 'max_volume_anomaly',       label: 'Max Vol Anomaly (avg)', stat: 'mean', fmt: v => v != null ? `${Number(v).toFixed(1)}×` : '—' },
  { key: 'max_volume_anomaly',       label: 'Max Vol Anomaly (p90)', stat: 'p90',  fmt: v => v != null ? `${Number(v).toFixed(1)}×` : '—' },
  { key: 'largest_gap_pct',          label: 'Largest Gap (avg)',   stat: 'mean',   fmt: v => fmtPct(v) },
  { key: 'largest_gap_pct',          label: 'Largest Gap (p90)',   stat: 'p90',    fmt: v => fmtPct(v) },
  { key: 'ignition_quality',         label: 'Ign Quality (avg)',   stat: 'mean',   fmt: v => v != null ? Number(v).toFixed(0) : '—' },
  { key: 'ignition_quality',         label: 'Ign Quality (p90)',   stat: 'p90',    fmt: v => v != null ? Number(v).toFixed(0) : '—' },
  { key: 'days_to_peak',             label: 'Days to Peak (med)',  stat: 'median', fmt: v => v != null ? `${Number(v).toFixed(0)}d` : '—' },
  { key: 'max_drawdown_before_peak', label: 'Max DD Before (avg)', stat: 'mean',   fmt: v => fmtPct(v) },
  { key: 'avg_toxicity_pre',         label: 'Avg Tox PRE (avg)',   stat: 'mean',   fmt: v => v != null ? Number(v).toFixed(0) : '—' },
];

// ── Global Summary component ──────────────────────────────────────────────────

function GlobalSummary({ run, comparisons, episodes, loading, error }) {
  if (!run) return null;

  if (loading) return <div className={styles.statusMsg}>Loading summary…</div>;
  if (error)   return <div className={styles.errorMsg}>{error}</div>;

  // ── Section A: family distribution ────────────────────────────────────────
  // Prefer run.pump_type_counts; fall back to deriving from loaded episodes
  let familyCounts = {};
  if (run.pump_type_counts && Object.keys(run.pump_type_counts).length > 0) {
    familyCounts = run.pump_type_counts;
  } else {
    (episodes || []).forEach(ep => {
      const k = ep.pump_type || 'UNKNOWN';
      familyCounts[k] = (familyCounts[k] || 0) + 1;
    });
  }
  const families   = Object.entries(familyCounts).sort((a, b) => b[1] - a[1]);
  const totalFams  = families.reduce((s, [, v]) => s + v, 0);

  // ── Section B: comparison groups ──────────────────────────────────────────
  const groupMap = {};
  (comparisons || []).forEach(g => { groupMap[g.group_name] = g; });

  // ── Section C: signal table sources ───────────────────────────────────────
  const pump4x  = groupMap['4x_pump'];
  const normalW = groupMap['normal_winner'];
  const falsePo = groupMap['false_positive'];
  const hasSignals = !!pump4x;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* ── Section A: Pump family distribution ─────────────────────────── */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>PUMP FAMILY DISTRIBUTION</div>
        {families.length === 0 ? (
          <div className={styles.statusMsg}>
            No family data yet — run must reach comparison_complete status.
          </div>
        ) : (
          <table className={styles.familyTable}>
            <thead>
              <tr>
                <th>Family</th>
                <th style={{ textAlign: 'right' }}>Count</th>
                <th style={{ textAlign: 'right' }}>Share</th>
                <th style={{ minWidth: 140 }}>Bar</th>
              </tr>
            </thead>
            <tbody>
              {families.map(([fam, cnt]) => {
                const share = totalFams > 0 ? (cnt / totalFams) * 100 : 0;
                const color = (PUMP_TYPE_CFG[fam] || {}).color || '#888';
                return (
                  <tr key={fam}>
                    <td><PumpTypeBadge type={fam} /></td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, textAlign: 'right' }}>
                      {cnt}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)', textAlign: 'right' }}>
                      {share.toFixed(0)}%
                    </td>
                    <td>
                      <div style={{ height: 6, width: `${share}%`, minWidth: 2,
                                    background: color, borderRadius: 'var(--r-pill)', opacity: 0.75 }} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Section B: Comparison groups ────────────────────────────────── */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>COMPARISON GROUPS</div>
        {comparisons.length === 0 ? (
          <div className={styles.statusMsg}>
            Comparison groups not yet built — run must reach comparison_complete status.
          </div>
        ) : (
          <div className={styles.compGroups}>
            {GROUP_ORDER.map(gname => {
              const g = groupMap[gname];
              if (!g) return null;
              const cfg = GROUP_CFG[gname] || { label: gname, color: 'var(--text-muted)' };
              const rows = [
                ['Members',       g.member_count ?? '—'],
                ['Avg Multiple',  gs(g, 'pump_multiple') != null    ? fmtX(gs(g, 'pump_multiple'))                                       : '—'],
                ['Median Days',   gs(g, 'days_to_peak', 'median') != null ? `${Number(gs(g, 'days_to_peak', 'median')).toFixed(0)}d`     : '—'],
                ['Avg Max Vol',   gs(g, 'max_volume_anomaly') != null ? `${Number(gs(g, 'max_volume_anomaly')).toFixed(1)}×`              : '—'],
                ['Ribbon Rate',   gs(g, 'had_ribbon')   != null ? fmtRate(gs(g, 'had_ribbon'))   : '—'],
                ['Ignition Rate', gs(g, 'had_ignition') != null ? fmtRate(gs(g, 'had_ignition')) : '—'],
                ['Ign Quality',   gs(g, 'ignition_quality')    != null ? Number(gs(g, 'ignition_quality')).toFixed(0)    : '—'],
                ['Avg Tox PRE',   gs(g, 'avg_toxicity_pre')    != null ? Number(gs(g, 'avg_toxicity_pre')).toFixed(0)    : '—'],
              ];
              return (
                <div key={gname} className={styles.compGroupCard}
                  style={{ borderTop: `3px solid ${cfg.color}` }}>
                  <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.07em',
                                color: cfg.color, textTransform: 'uppercase', marginBottom: 10 }}>
                    {cfg.label}
                  </div>
                  <div className={styles.compGroupStats}>
                    {rows.map(([label, val]) => (
                      <div key={label} className={styles.compStatRow}>
                        <span className={styles.compStatLabel}>{label}</span>
                        <span className={styles.compStatVal}>{val}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* ── Section C: Pre-pump signals comparison table ─────────────────── */}
      {hasSignals && (
        <div className={styles.bundleSection}>
          <div className={styles.bundleSectionTitle}>
            PRE-PUMP SIGNAL FREQUENCIES — 4× PUMPS vs COMPARISON
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.signalTable}>
              <thead>
                <tr>
                  <th>Signal / Stat</th>
                  <th>4× Pump</th>
                  {normalW && <th>Normal Winner</th>}
                  {falsePo && <th>False Positive</th>}
                </tr>
              </thead>
              <tbody>
                {SIGNAL_ROWS.map((row, i) => {
                  const v4  = gs(pump4x, row.key, row.stat);
                  const vNw = normalW ? gs(normalW, row.key, row.stat) : undefined;
                  const vFp = falsePo ? gs(falsePo, row.key, row.stat) : undefined;
                  const fmtFn = row.fmt || (v => v != null ? String(v) : '—');
                  return (
                    <tr key={`${row.key}-${row.stat}-${i}`}>
                      <td className={styles.signalLabel}>{row.label}</td>
                      <td className={styles.signalVal4x}>
                        {row.isRate
                          ? <RateBar value={v4} />
                          : <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700,
                                           color: 'var(--lime)' }}>{fmtFn(v4)}</span>}
                      </td>
                      {normalW !== undefined && (
                        <td className={styles.signalValAlt}>
                          {row.isRate
                            ? <RateBar value={vNw} />
                            : <span style={{ fontFamily: 'var(--font-mono)',
                                             color: 'var(--text-dim)' }}>{fmtFn(vNw)}</span>}
                        </td>
                      )}
                      {falsePo !== undefined && (
                        <td className={styles.signalValAlt}>
                          {row.isRate
                            ? <RateBar value={vFp} />
                            : <span style={{ fontFamily: 'var(--font-mono)',
                                             color: 'var(--text-muted)' }}>{fmtFn(vFp)}</span>}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 8, lineHeight: 1.5 }}>
            Rates are % of members with the feature. All values derived deterministically from stored group stats.
            n=4×: {pump4x.member_count ?? '?'}
            {normalW ? ` · n=normal: ${normalW.member_count ?? '?'}` : ''}
            {falsePo ? ` · n=fp: ${falsePo.member_count ?? '?'}` : ''}
          </div>
        </div>
      )}

    </div>
  );
}

// ── Run detail header ─────────────────────────────────────────────────────────

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

    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PumpStudyPage() {
  const [runs,        setRuns]        = useState([]);
  const [runsLoading, setRunsLoading] = useState(false);
  const [runsError,   setRunsError]   = useState('');
  const [selectedId,  setSelectedId]  = useState(null);
  const [selectedRun, setSelectedRun] = useState(null);
  const [runLoading,  setRunLoading]  = useState(false);
  const pollRef = useRef(null);

  // Launch form state
  const [launching,   setLaunching]   = useState(false);
  const [launchError, setLaunchError] = useState('');

  // Episodes state
  const [episodes,    setEpisodes]    = useState([]);
  const [epLoading,   setEpLoading]   = useState(false);
  const [epError,     setEpError]     = useState('');
  const [selectedEpId, setSelectedEpId] = useState(null);
  const epFiltersRef = useRef({ symbol: '', pump_type: '', min_multiple: '', caught_mode: 'all' });

  // Episode detail state (Phase 5C)
  const [detailEpId, setDetailEpId] = useState(null);

  // Global summary state (Phase 5D)
  const [comparisons,  setComparisons]  = useState([]);
  const [cmpLoading,   setCmpLoading]   = useState(false);
  const [cmpError,     setCmpError]     = useState('');

  // ── Load runs list ────────────────────────────────────────────────────────

  const loadRuns = useCallback(async () => {
    setRunsLoading(true);
    setRunsError('');
    try {
      const res  = await fetch(`${API_URL}/api/replay/pump-study/runs?limit=30`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRuns(data.runs || []);
    } catch (err) {
      setRunsError(err.message || 'Failed to load runs');
    } finally {
      setRunsLoading(false);
    }
  }, []);

  // ── Launch a new run ──────────────────────────────────────────────────────

  async function handleLaunch(params) {
    setLaunching(true);
    setLaunchError('');
    try {
      const res = await fetch(`${API_URL}/api/replay/pump-study/run`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(params),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      // Refresh list and auto-select the new run
      await loadRuns();
      if (data.run_id) setSelectedId(data.run_id);
    } catch (err) {
      setLaunchError(err.message || 'Launch failed');
    } finally {
      setLaunching(false);
    }
  }

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

  // ── Load episodes ─────────────────────────────────────────────────────────

  const loadEpisodes = useCallback(async (runId, filters = {}) => {
    if (!runId) return;
    epFiltersRef.current = { ...epFiltersRef.current, ...filters };
    const f = epFiltersRef.current;
    setEpLoading(true);
    setEpError('');
    try {
      const params = new URLSearchParams({ limit: 500 });
      if (f.symbol)       params.set('symbol',       f.symbol);
      if (f.pump_type)    params.set('pump_type',    f.pump_type);
      if (f.min_multiple) params.set('min_multiple', f.min_multiple);
      if (f.caught_mode === 'caught') params.set('caught_only', 'true');
      if (f.caught_mode === 'missed') params.set('missed_only', 'true');
      const res  = await fetch(`${API_URL}/api/replay/pump-study/${runId}/episodes?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setEpisodes(data.episodes || []);
    } catch (err) {
      setEpError(err.message || 'Failed to load episodes');
      setEpisodes([]);
    } finally {
      setEpLoading(false);
    }
  }, []);

  // ── Load comparisons ─────────────────────────────────────────────────────

  const loadComparisons = useCallback(async (runId) => {
    if (!runId) return;
    setCmpLoading(true);
    setCmpError('');
    try {
      const res  = await fetch(`${API_URL}/api/replay/pump-study/${runId}/comparisons`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setComparisons(data.groups || []);
    } catch (err) {
      setCmpError(err.message || 'Failed to load comparisons');
      setComparisons([]);
    } finally {
      setCmpLoading(false);
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

  // Load episodes + comparisons whenever a run is selected (reset all sub-state)
  useEffect(() => {
    if (!selectedId) {
      setEpisodes([]);
      setComparisons([]);
      return;
    }
    epFiltersRef.current = { symbol: '', pump_type: '', min_multiple: '', caught_mode: 'all' };
    setSelectedEpId(null);
    setDetailEpId(null);
    loadEpisodes(selectedId);
    loadComparisons(selectedId);
  }, [selectedId, loadEpisodes, loadComparisons]);

  function handleSelectRun(runId) {
    if (selectedId === runId) return;
    setSelectedId(runId);
    setSelectedRun(null);
    setDetailEpId(null);
  }

  function handleSelectEp(epId) {
    // Toggle: clicking the same row closes detail; new row opens it
    setSelectedEpId(prev => prev === epId ? null : epId);
    setDetailEpId(prev => prev === epId ? null : epId);
  }

  function handleEpReload(filters) {
    loadEpisodes(selectedId, filters);
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

          {/* Launch form */}
          <div className={styles.bundleSection}>
            <div className={styles.bundleSectionTitle}>LAUNCH NEW STUDY</div>
            <RunLaunchForm
              onLaunch={handleLaunch}
              launching={launching}
              launchError={launchError}
            />
          </div>

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
              error={runsError}
              onRetry={loadRuns}
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

          {/* Global Summary (Phase 5D) */}
          {selectedId && (
            <div className={styles.bundleSection}>
              <div className={styles.bundleSectionTitle}>GLOBAL SUMMARY</div>
              <GlobalSummary
                run={selectedRun}
                comparisons={comparisons}
                episodes={episodes}
                loading={cmpLoading}
                error={cmpError}
              />
            </div>
          )}

          {/* Episodes table */}
          {selectedId && (
            <div className={styles.bundleSection}>
              <div className={styles.bundleSectionTitle}>EPISODES</div>
              <EpisodesTable
                runId={selectedId}
                episodes={episodes}
                loading={epLoading}
                error={epError}
                selectedEpId={selectedEpId}
                onSelectEp={handleSelectEp}
                onReload={handleEpReload}
              />
            </div>
          )}

          {/* Episode detail (Phase 5C) */}
          {selectedId && detailEpId && (
            <EpisodeDetail
              runId={selectedId}
              episodeId={detailEpId}
              onClose={() => { setDetailEpId(null); setSelectedEpId(null); }}
            />
          )}

          {/* AI Recommendation (Phase 6) */}
          {selectedId && (
            <div className={styles.bundleSection}>
              <div className={styles.bundleSectionTitle}>AI RECOMMENDATION</div>
              <AISummarySection
                runId={selectedId}
                runStatus={selectedRun?.status}
              />
            </div>
          )}

        </div>
      </div>
    </>
  );
}
