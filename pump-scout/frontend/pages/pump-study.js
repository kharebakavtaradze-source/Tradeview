/**
 * Pump Study — 4× Historical Pump Research
 * Phase 5A: page shell + runs list + run selection.
 * Phase 5B: episodes table with filters + row selection.
 * Phase 5C: episode detail panel.
 * Phase 5D: global summary — family distribution, comparison groups, pre-pump signals.
 * Phase 6:  AI recommendation layer.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import PumpLayout from '../components/PumpLayout';
import BarLabels from '../components/BarLabels';
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

// ── NP structural badges ──────────────────────────────────────────────────────

const NP_PHASE_COLOR = {
  CONFIRMED_STRUCTURE: '#86efac',
  TRIGGERED_STRUCTURE: '#22d3ee',
  EARLY_STRUCTURE:     '#60a5fa',
  SETUP_PHASE:         '#a8a29e',
  IMPULSE_ONLY:        '#6b7280',
  DEGRADED:            '#fbbf24',
  BROKEN_STRUCTURE:    '#fb7185',
};
const NP_PHASE_SHORT = {
  CONFIRMED_STRUCTURE: 'CONFIRMED',
  TRIGGERED_STRUCTURE: 'TRIGGERED',
  EARLY_STRUCTURE:     'EARLY',
  SETUP_PHASE:         'SETUP',
  IMPULSE_ONLY:        'IMPULSE',
  DEGRADED:            'DEGRADED',
  BROKEN_STRUCTURE:    'BROKEN',
};
function NPPhaseBadge({ phase }) {
  if (!phase) return <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>—</span>;
  const color = NP_PHASE_COLOR[phase] || '#6b7280';
  return (
    <span style={{
      color, fontWeight: 700, fontSize: 9, letterSpacing: '0.04em',
      padding: '2px 6px', borderRadius: 'var(--r-pill)',
      background: `${color}1a`, border: `1px solid ${color}44`,
      whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)',
    }}>{NP_PHASE_SHORT[phase] || phase}</span>
  );
}

const NP_DECISION_COLOR = { BUY_CANDIDATE: '#86efac', WATCH: '#22d3ee', AVOID: '#fbbf24' };
const NP_DECISION_SHORT = { BUY_CANDIDATE: 'BUY', WATCH: 'WATCH', AVOID: 'AVOID' };
function NPDecisionBadge({ decision }) {
  if (!decision) return <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>—</span>;
  const color = NP_DECISION_COLOR[decision] || '#6b7280';
  return (
    <span style={{
      color, fontWeight: 700, fontSize: 9, letterSpacing: '0.04em',
      padding: '2px 6px', borderRadius: 'var(--r-pill)',
      background: `${color}1a`, border: `1px solid ${color}44`,
      whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)',
    }}>{NP_DECISION_SHORT[decision] || decision}</span>
  );
}

// ── Demand Engine badges ──────────────────────────────────────────────────────

const DEMAND_TIER_CFG = {
  PRIME_BUY:    { short: 'PRIME',   color: '#86efac' },
  HIGH_CONF_BUY:{ short: 'HIGH',    color: '#22d3ee' },
  BUY_WATCH:    { short: 'WATCH',   color: '#60a5fa' },
  SETUP_MONITOR:{ short: 'SETUP',   color: '#a8a29e' },
  SKIP:         { short: 'SKIP',    color: '#6b7280' },
};
function DemandTierBadge({ tier }) {
  if (!tier) return <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>—</span>;
  const cfg = DEMAND_TIER_CFG[tier] || { short: tier, color: '#888' };
  return (
    <span style={{
      color: cfg.color, fontWeight: 700, fontSize: 9, letterSpacing: '0.04em',
      padding: '2px 6px', borderRadius: 'var(--r-pill)',
      background: `${cfg.color}1a`, border: `1px solid ${cfg.color}44`,
      whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)',
    }}>{cfg.short}</span>
  );
}

const ATS_CFG = {
  ATS_PRIME: { short: 'PRIME', color: '#86efac' },
  ATS_SETUP: { short: 'SETUP', color: '#60a5fa' },
  ATS_WATCH: { short: 'WATCH', color: '#a8a29e' },
  ATS_NONE:  { short: 'NONE',  color: '#6b7280' },
};
function AtsBadge({ ats }) {
  if (!ats) return <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>—</span>;
  const cfg = ATS_CFG[ats] || { short: ats, color: '#888' };
  return (
    <span style={{
      color: cfg.color, fontWeight: 700, fontSize: 9, letterSpacing: '0.04em',
      padding: '2px 6px', borderRadius: 'var(--r-pill)',
      background: `${cfg.color}1a`, border: `1px solid ${cfg.color}44`,
      whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)',
    }}>{cfg.short}</span>
  );
}

function TzSignalBadge({ signal }) {
  if (!signal) return <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>—</span>;
  const isBullish = signal.startsWith('T');
  const color = isBullish ? '#86efac' : '#fb7185';
  return (
    <span style={{
      color, fontWeight: 700, fontSize: 9, letterSpacing: '0.04em',
      padding: '2px 5px', borderRadius: 'var(--r-pill)',
      background: `${color}1a`, border: `1px solid ${color}44`,
      whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)',
    }}>{signal}</span>
  );
}

// ── Event type config ─────────────────────────────────────────────────────────

const EVENT_CFG = {
  first_abnormal_volume_day:     { color: 'var(--amber)',  label: 'ABNORMAL VOL'    },
  first_compression_day:         { color: 'var(--cyan)',   label: 'BB COMPRESSION'  },
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
    { label: 'Max Gap',       val: ep.largest_gap_pct != null ? fmtPct(ep.largest_gap_pct) : '—' },
    { label: 'Max Vol',       val: ep.max_volume_anomaly != null ? `${Number(ep.max_volume_anomaly).toFixed(1)}×` : '—',
                              color: ep.max_volume_anomaly >= 3 ? 'var(--amber)' : null },
    { label: 'Avg Tox PRE',   val: ep.avg_toxicity_pre != null ? Number(ep.avg_toxicity_pre).toFixed(0) : '—' },
    { label: 'Max Tox PRE',   val: ep.max_toxicity_pre != null ? Number(ep.max_toxicity_pre).toFixed(0) : '—' },
  ];

  // Demand Engine badges for detail panel
  const demandTier  = ep.demand_tier_at_breakout;
  const atsSignal   = ep.ats_at_breakout;
  const readiness   = ep.readiness_tier_at_breakout;
  const tzSignal    = ep.tz_t_signal_at_breakout || ep.tz_z_signal_at_breakout;
  const preupToken  = ep.preup_token_at_breakout;
  const line5Token  = ep.line5_at_breakout;
  const hasDemand   = demandTier || atsSignal || tzSignal;

  // Phase counts
  const phaseCounts = { PRE: 0, PUMP: 0, POST: 0 };
  snaps.forEach(s => { if (phaseCounts[s.window_phase] != null) phaseCounts[s.window_phase]++; });

  const INNER_TABS = [
    { key: 'events',    label: `Events (${events.length})` },
    { key: 'snapshots', label: `Snapshots (${snaps.length})` },
    { key: 'cluster',   label: 'Cluster' },
    { key: 'labels',    label: 'Bar Labels' },
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

      {/* ── Demand Engine row ─────────────────────────────────────────────────── */}
      {hasDemand && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, padding: '6px 0', alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', marginRight: 4 }}>Demand@breakout:</span>
          <DemandTierBadge tier={demandTier} />
          <AtsBadge ats={atsSignal} />
          {readiness && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)' }}>
              Readiness: {readiness}
            </span>
          )}
          {ep.demand_score_at_breakout != null && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)' }}>
              Score: {Number(ep.demand_score_at_breakout).toFixed(1)}
            </span>
          )}
          {tzSignal && (
            <>
              <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 8 }}>TZ:</span>
              <TzSignalBadge signal={tzSignal} />
            </>
          )}
          {ep.best_tz_t_signal_15bar && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--cyan)' }}>
              TZ15: {ep.best_tz_t_signal_15bar}
            </span>
          )}
          {preupToken && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--cyan)' }}>
              {preupToken}
            </span>
          )}
          {line5Token && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-dim)' }}>
              Line5: {line5Token}
            </span>
          )}
        </div>
      )}

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
                  const sd        = s.snapshot_data || s.snapshot || {};
                  const seqType   = s.sequence_type   ?? sd.regime?.sequence_type    ?? '—';
                  const bias      = s.structural_bias ?? sd.regime?.structural_bias  ?? '—';
                  const tox       = s.toxicity_score  ?? sd.toxicity?.toxicity_score ?? null;
                  const np        = sd.new_pump || {};
                  const npPhase   = np.structure_phase   ?? null;
                  const npScore   = np.structure_score   ?? null;
                  const ceRaw     = np.compression_expansion_state ?? null;
                  const ceShort   = ceRaw === 'accumulation_ready'   ? 'ACC'
                                  : ceRaw === 'expansion_start'      ? 'EXP'
                                  : ceRaw === 'overheated_expansion'  ? 'OVR'
                                  : ceRaw ? String(ceRaw).slice(0, 5) : null;
                  const ceColor   = ceRaw === 'accumulation_ready'   ? '#86efac'
                                  : ceRaw === 'expansion_start'      ? '#22d3ee'
                                  : ceRaw === 'overheated_expansion'  ? '#fb7185'
                                  : 'var(--text-muted)';
                  const npDecision = np.decision ?? null;
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

      {/* ── Section E: Bar Labels ─────────────────────────────────────────────── */}
      {innerTab === 'labels' && (
        <div style={{ padding: '12px 0' }}>
          <BarLabels symbol={ep.symbol} />
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

function computeStatGroups(episodes, field) {
  const groups = {};
  for (const ep of episodes) {
    const key = ep[field] || 'NONE';
    if (!groups[key]) groups[key] = [];
    groups[key].push(ep);
  }
  return Object.entries(groups)
    .map(([bucket, eps]) => {
      const mults = eps.map(e => e.pump_multiple).filter(v => v != null);
      const rets  = eps.map(e => e.pump_return_pct).filter(v => v != null);
      return {
        bucket,
        count:          eps.length,
        avg_multiple:   mults.length ? mults.reduce((a, b) => a + b, 0) / mults.length : null,
        win2x_rate:     mults.length ? mults.filter(v => v >= 2).length / mults.length : null,
        win4x_rate:     mults.length ? mults.filter(v => v >= 4).length / mults.length : null,
        avg_return_pct: rets.length  ? rets.reduce((a, b) => a + b, 0)  / rets.length  : null,
      };
    })
    .sort((a, b) => b.count - a.count);
}

function computeCombos(episodes, fieldA, fieldB) {
  const groups = {};
  for (const ep of episodes) {
    const key = `${ep[fieldA] || 'NONE'} × ${ep[fieldB] || 'NONE'}`;
    if (!groups[key]) groups[key] = [];
    groups[key].push(ep);
  }
  return Object.entries(groups)
    .filter(([, eps]) => eps.length >= 3)
    .map(([bucket, eps]) => {
      const mults = eps.map(e => e.pump_multiple).filter(v => v != null);
      const rets  = eps.map(e => e.pump_return_pct).filter(v => v != null);
      return {
        bucket,
        count:          eps.length,
        avg_multiple:   mults.length ? mults.reduce((a, b) => a + b, 0) / mults.length : null,
        win2x_rate:     mults.length ? mults.filter(v => v >= 2).length / mults.length : null,
        win4x_rate:     mults.length ? mults.filter(v => v >= 4).length / mults.length : null,
        avg_return_pct: rets.length  ? rets.reduce((a, b) => a + b, 0)  / rets.length  : null,
      };
    })
    .sort((a, b) => b.count - a.count)
    .slice(0, 25);
}

function SigTable({ title, rows }) {
  if (!rows || rows.length === 0) return null;
  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', marginBottom: 5,
                    letterSpacing: '0.08em', textTransform: 'uppercase' }}>{title}</div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 10 }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {['Bucket','N','Avg×','2× Rate','4× Rate','Avg Ret%'].map(h => (
                <th key={h} style={{ padding: '3px 8px', textAlign: h === 'Bucket' ? 'left' : 'right',
                                     color: 'var(--text-muted)', fontWeight: 600, whiteSpace: 'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.bucket} style={{ borderBottom: '1px solid var(--border-faint, #2a2a2a)' }}>
                <td style={{ padding: '3px 8px', fontFamily: 'var(--font-mono)', fontWeight: 700,
                              fontSize: 9, whiteSpace: 'nowrap' }}>{r.bucket}</td>
                <td style={{ padding: '3px 8px', textAlign: 'right' }}>{r.count}</td>
                <td style={{ padding: '3px 8px', textAlign: 'right', fontFamily: 'var(--font-mono)',
                              color: r.avg_multiple >= 3 ? '#86efac' : r.avg_multiple >= 2 ? '#fbbf24' : undefined,
                              fontWeight: r.avg_multiple >= 3 ? 700 : undefined }}>
                  {r.avg_multiple != null ? `${r.avg_multiple.toFixed(2)}×` : '—'}
                </td>
                <td style={{ padding: '3px 8px', textAlign: 'right', fontFamily: 'var(--font-mono)',
                              color: r.win2x_rate >= 0.6 ? '#86efac' : r.win2x_rate >= 0.4 ? '#fbbf24' : undefined,
                              fontWeight: r.win2x_rate >= 0.6 ? 700 : undefined }}>
                  {r.win2x_rate != null ? `${(r.win2x_rate * 100).toFixed(0)}%` : '—'}
                </td>
                <td style={{ padding: '3px 8px', textAlign: 'right', fontFamily: 'var(--font-mono)',
                              color: r.win4x_rate >= 0.4 ? '#86efac' : r.win4x_rate >= 0.2 ? '#fbbf24' : undefined,
                              fontWeight: r.win4x_rate >= 0.4 ? 700 : undefined }}>
                  {r.win4x_rate != null ? `${(r.win4x_rate * 100).toFixed(0)}%` : '—'}
                </td>
                <td style={{ padding: '3px 8px', textAlign: 'right', fontFamily: 'var(--font-mono)',
                              color: r.avg_return_pct >= 100 ? '#86efac' : undefined }}>
                  {r.avg_return_pct != null ? `${r.avg_return_pct.toFixed(0)}%` : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SignalStats({ episodes }) {
  const withDemand = (episodes || []).filter(e => e.demand_tier_at_breakout);
  if (!withDemand.length) return (
    <div style={{ color: 'var(--text-muted)', fontSize: 11, padding: '12px 0' }}>
      No demand scores yet — run demand scoring phase first.
    </div>
  );
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
        <SigTable title="By Demand Tier"     rows={computeStatGroups(withDemand, 'demand_tier_at_breakout')} />
        <SigTable title="By ATS Signal"       rows={computeStatGroups(withDemand, 'ats_at_breakout')} />
        <SigTable title="By Readiness Tier"   rows={computeStatGroups(withDemand, 'readiness_tier_at_breakout')} />
        <SigTable title="By Best TZ Signal (15 bars)" rows={computeStatGroups(withDemand, 'best_tz_t_signal_15bar')} />
        <SigTable title="By PREUP Token"      rows={computeStatGroups(withDemand, 'preup_token_at_breakout')} />
        <SigTable title="By Line5"            rows={computeStatGroups(withDemand, 'line5_at_breakout')} />
      </div>
      <SigTable title="Best TZ (15-bar) × Demand Tier (min 3 episodes)"
        rows={computeCombos(withDemand, 'best_tz_t_signal_15bar', 'demand_tier_at_breakout')} />
      <SigTable title="Best TZ (15-bar) × ATS Signal (min 3 episodes)"
        rows={computeCombos(withDemand, 'best_tz_t_signal_15bar', 'ats_at_breakout')} />
      <SigTable title="Demand Tier × ATS Signal (min 3 episodes)"
        rows={computeCombos(withDemand, 'demand_tier_at_breakout', 'ats_at_breakout')} />
    </div>
  );
}

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
                <th title="Demand Engine composite tier at breakout">Demand</th>
                <th title="ATS signal at breakout">ATS</th>
                <th title="TZ bar label at breakout">TZ</th>
                <th title="Best TZ signal in last 15 bars before breakout">TZ 15bar</th>
                <th title="PREUP token at breakout">PREUP</th>
                <th title="Largest gap up % in PRE+PUMP window">Max Gap</th>
                <th title="Max volume vs 20-day average">Max Vol</th>
              </tr>
            </thead>
            <tbody>
              {episodes.map(ep => {
                const caught = ep.caught_by_scanner;
                const npLabel = ep.new_pump_label;
                const npLabelColor = npLabel === 'FIRE'   ? 'var(--lime)'
                                   : npLabel === 'STRONG' ? 'var(--cyan)'
                                   : npLabel === 'WATCH'  ? 'var(--amber)'
                                   : 'var(--text-muted)';
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
                    <td><DemandTierBadge tier={ep.demand_tier_at_breakout} /></td>
                    <td><AtsBadge ats={ep.ats_at_breakout} /></td>
                    <td><TzSignalBadge signal={ep.tz_t_signal_at_breakout || ep.tz_z_signal_at_breakout} /></td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: ep.best_tz_t_signal_15bar ? 'var(--cyan)' : 'var(--text-muted)' }}>
                      {ep.best_tz_t_signal_15bar || '—'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: ep.preup_token_at_breakout ? 'var(--cyan)' : 'var(--text-muted)' }}>
                      {ep.preup_token_at_breakout || '—'}
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
  const [minMultiple,    setMinMultiple]    = useState(2.0);
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
            <option value={2.0}>2×</option>
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

function RunsList({ runs, selectedId, onSelect, loading, error, onRetry, onDelete }) {
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
            <th></th>
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
              <td onClick={e => e.stopPropagation()}>
                <button
                  className={styles.btnDanger}
                  style={{ padding: '3px 10px', fontSize: 10 }}
                  onClick={() => onDelete && onDelete(r.id)}
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Global Summary helpers (Phase 5D — placeholder, terminal statuses kept for run checks) ──

const TERMINAL_STATUSES = new Set(['completed', 'comparison_complete']);

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
  { key: 'max_volume_anomaly',       label: 'Max Vol Anomaly (avg)', stat: 'mean', fmt: v => v != null ? `${Number(v).toFixed(1)}×` : '—' },
  { key: 'max_volume_anomaly',       label: 'Max Vol Anomaly (p90)', stat: 'p90',  fmt: v => v != null ? `${Number(v).toFixed(1)}×` : '—' },
  { key: 'largest_gap_pct',          label: 'Largest Gap (avg)',   stat: 'mean',   fmt: v => fmtPct(v) },
  { key: 'largest_gap_pct',          label: 'Largest Gap (p90)',   stat: 'p90',    fmt: v => fmtPct(v) },
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

function RunDetailHeader({ run, onScoreDemand, scoringDemand, scoreDemandMsg }) {
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

  const base = `${API_URL}/api/replay/pump-study/${run.id}/export`;

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
        {/* Export buttons */}
        <button className={styles.exportBtn}
          onClick={() => window.open(`${base}?format=json`)}
          title="Download full structured bundle (run + episodes + clusters + timeline)">
          ↓ JSON
        </button>
        <button className={styles.exportBtn}
          onClick={() => window.open(`${base}?format=csv`)}
          title="Download flat CSV of all episodes"
          style={{ color: 'var(--lime, #22c55e)' }}>
          ↓ CSV
        </button>
        <button className={styles.exportBtn}
          onClick={() => window.open(`${base}?format=markdown`)}
          title="Download Markdown summary"
          style={{ color: 'var(--cyan, #22d3ee)' }}>
          ↓ MD
        </button>
        <button className={styles.exportBtn}
          onClick={onScoreDemand}
          disabled={scoringDemand || isRunning}
          title="Re-run demand + TZ scoring for all episodes (requires a linked raw pattern study run)"
          style={{ color: 'var(--amber, #f59e0b)', opacity: (scoringDemand || isRunning) ? 0.5 : 1 }}>
          {scoringDemand ? '⏳ Scoring…' : '⚡ Score Demand'}
        </button>
        {scoreDemandMsg && (
          <span style={{ fontSize: 10, color: scoreDemandMsg.startsWith('Error') ? '#f87171' : '#86efac' }}>
            {scoreDemandMsg}
          </span>
        )}
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

  // Delete state
  const [deleteTarget, setDeleteTarget] = useState(null);   // run id to confirm
  const [deleting,     setDeleting]     = useState(false);
  const [deleteError,  setDeleteError]  = useState('');

  // Score demand state
  const [scoringDemand,  setScoringDemand]  = useState(false);
  const [scoreDemandMsg, setScoreDemandMsg] = useState('');

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

  // ── Delete a run ─────────────────────────────────────────────────────────

  async function handleDeleteConfirm() {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError('');
    try {
      const res = await fetch(`${API_URL}/api/replay/pump-study/${deleteTarget}`, {
        method: 'DELETE',
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      // Clear all selection state if deleted run was active
      if (selectedId === deleteTarget) {
        setSelectedId(null);
        setSelectedRun(null);
        setEpisodes([]);
        setComparisons([]);
        setSelectedEpId(null);
        setDetailEpId(null);
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      }
      setRuns(prev => prev.filter(r => r.id !== deleteTarget));
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err.message || 'Delete failed');
    } finally {
      setDeleting(false);
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
    <PumpLayout title="Pump Study">
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
              onDelete={id => { setDeleteTarget(id); setDeleteError(''); }}
            />
          </div>

          {/* Selected run detail */}
          {selectedId && (
            <div>
              {runLoading && !selectedRun && (
                <div className={styles.statusMsg}>Loading run #{selectedId}…</div>
              )}
              {selectedRun && (
                <RunDetailHeader
                  run={selectedRun}
                  scoringDemand={scoringDemand}
                  scoreDemandMsg={scoreDemandMsg}
                  onScoreDemand={async () => {
                    setScoringDemand(true);
                    setScoreDemandMsg('');
                    try {
                      const res = await fetch(`${API_URL}/api/replay/pump-study/${selectedRun.id}/score-demand`, { method: 'POST' });
                      const data = await res.json();
                      if (!res.ok) throw new Error(data.detail || 'Failed');
                      setScoreDemandMsg('Scoring started — refresh episodes in a minute');
                    } catch (e) {
                      setScoreDemandMsg(`Error: ${e.message}`);
                    } finally {
                      setScoringDemand(false);
                    }
                  }}
                />
              )}
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

          {/* Signal Combos */}
          {selectedId && episodes.length > 0 && (
            <div className={styles.bundleSection}>
              <div className={styles.bundleSectionTitle}>SIGNAL COMBINATION ANALYTICS</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 12 }}>
                {episodes.filter(e => e.demand_tier_at_breakout).length} of {episodes.length} episodes have demand scores.
                Metrics: pump_multiple and pump_return_pct. Period: {selectedRun?.start_date} → {selectedRun?.end_date}.
              </div>
              <SignalStats episodes={episodes} />
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

        </div>
      </div>

      {/* ── Delete confirmation modal ──────────────────────────────────────── */}
      {deleteTarget && (
        <div className={styles.modalOverlay} onClick={() => !deleting && setDeleteTarget(null)}>
          <div className={styles.modalBox} onClick={e => e.stopPropagation()}>
            <div className={styles.modalTitle}>Permanently Delete Run #{deleteTarget}?</div>
            <div className={styles.modalBody}>
              This will remove the run and <strong>all linked DB rows</strong>:
              episodes, snapshots, events, clusters, detections, comparison
              groups &amp; members, and any AI summaries.
              <br /><br />
              <strong>This cannot be undone.</strong>
            </div>
            {deleteError && (
              <div style={{ fontSize: 11, color: 'var(--red, #f87171)' }}>{deleteError}</div>
            )}
            <div className={styles.modalActions}>
              <button className={styles.btnCancel} onClick={() => setDeleteTarget(null)} disabled={deleting}>
                Cancel
              </button>
              <button className={styles.btnDanger} onClick={handleDeleteConfirm} disabled={deleting}>
                {deleting ? 'Deleting…' : 'Delete Permanently'}
              </button>
            </div>
          </div>
        </div>
      )}
    </PumpLayout>
  );
}
