import { useCallback, useState } from 'react';
import Head from 'next/head';
import AppNav from '../components/AppNav';
import styles from '../styles/SignalAnatomy.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ── Helpers ───────────────────────────────────────────────────────────────────

function buildAiPacket(report) {
  const recentBars = (report.bar_anatomy || [])
    .filter((b) => b.bars_ago <= 14)
    .map((b) => ({
      bars_ago: b.bars_ago,
      close: b.close,
      volume_z: b.volume_z,
      rsi_range3: b.rsi_range3,
      v_ratio: b.v_ratio,
      signals: {
        l34: b.l34,
        fri34: b.fri34,
        g4: b.g4,
        b2: b.b2,
        g4_armed: b.g4_armed,
      },
      l34_conditions: b.l34_conditions,
      l34_near_miss: b.l34_near_miss,
      t_signals_fired: b.t_signals_fired || [],
      z_signals_fired: b.z_signals_fired || [],
    }));

  return {
    packet_type: 'pump_scout_signal_anatomy_ai_packet',
    prompt: [
      'You are analyzing a small-cap momentum setup using Pump Scout Signal Anatomy data.',
      'Explain why the New Pump Engine did or did not fire.',
      'Judge whether the setup is improving, stale, invalid, or actionable.',
      'Name the exact missing confirmation and the main risk.',
      'Do not invent market data. Use only the JSON fields in this packet.',
    ].join(' '),
    symbol: report.symbol,
    n_candles: report.n_candles || report.n_bars,
    final_engine_result: {
      label: report.final?.new_pump_label || null,
      score: report.final?.new_pump_score ?? null,
      sequence: report.final?.new_pump_sequence_label || null,
      is_no_signal: report.is_no_signal,
    },
    signal_history: report.signal_analysis || {},
    diagnosis: report.diagnosis || [],
    l34_near_misses_30: report.l34_near_misses_30 || [],
    recent_bar_anatomy: recentBars,
    full_report: report,
  };
}

function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function SignalPill({ on, label }) {
  return (
    <span className={on ? styles.pillOn : styles.pillOff}>{label}</span>
  );
}

function VzBadge({ vz }) {
  if (vz == null) return <span style={{ color: '#555' }}>—</span>;
  const ok = vz >= 1.1;
  return (
    <span style={{ color: ok ? '#00ff88' : '#888', fontVariantNumeric: 'tabular-nums' }}>
      {vz.toFixed(2)}
    </span>
  );
}

function RsiBadge({ rr }) {
  if (rr == null) return <span style={{ color: '#555' }}>—</span>;
  const ok = rr <= 5.0;
  return (
    <span style={{ color: ok ? '#00ff88' : '#ff6644', fontVariantNumeric: 'tabular-nums' }}>
      {rr.toFixed(2)}
    </span>
  );
}

function CondDot({ pass }) {
  return <span style={{ color: pass ? '#00ff88' : '#ff4444' }}>{pass ? '✓' : '✗'}</span>;
}

// ── Bar timeline ──────────────────────────────────────────────────────────────

function BarTimeline({ bars }) {
  const [hovered, setHovered] = useState(null);
  if (!bars || !bars.length) return null;

  return (
    <div className={styles.timelineWrap}>
      <div className={styles.timelineLegend}>
        <span className={styles.legendFired}>signal fired</span>
        <span className={styles.legendNearMiss}>near-miss</span>
        <span className={styles.legendArmed}>G4 armed</span>
        <span className={styles.legendNone}>nothing</span>
      </div>
      <div className={styles.timeline}>
        {[...bars].reverse().map((b) => {
          const fired = b.l34 || b.fri34 || b.g4 || b.b2;
          const nearMiss = !b.l34 && b.l34_near_miss;
          let cellCls = styles.barCell;
          if (b.g4)     cellCls = styles.barCellG4;
          else if (b.b2) cellCls = styles.barCellB2;
          else if (b.fri34) cellCls = styles.barCellFri34;
          else if (b.l34)   cellCls = styles.barCellL34;
          else if (nearMiss) cellCls = styles.barCellNearMiss;
          else if (b.g4_armed) cellCls = styles.barCellArmed;

          const label = `bar-${b.bars_ago}`;
          return (
            <div
              key={b.bar_idx}
              className={cellCls}
              onMouseEnter={() => setHovered(b)}
              onMouseLeave={() => setHovered(null)}
              title={label}
            />
          );
        })}
      </div>
      {hovered && (
        <div className={styles.timelineTooltip}>
          <div className={styles.ttHeader}>
            bars ago: <strong>{hovered.bars_ago}</strong> &nbsp; close: <strong>{hovered.close}</strong>
          </div>
          <div className={styles.ttRow}>
            <SignalPill on={hovered.l34}   label="L34"   />
            <SignalPill on={hovered.fri34} label="FRI34" />
            <SignalPill on={hovered.g4}    label="G4"    />
            <SignalPill on={hovered.b2}    label="B2"    />
            {hovered.g4_armed && <span className={styles.armedTag}>G4-ARMED</span>}
          </div>
          <div className={styles.ttRow}>
            <span style={{ color: '#888' }}>vol_z:</span> <VzBadge vz={hovered.volume_z} />
            <span style={{ color: '#888', marginLeft: 8 }}>rsi_r3:</span> <RsiBadge rr={hovered.rsi_range3} />
            {hovered.v_ratio != null && (
              <span style={{ color: '#888', marginLeft: 8 }}>v/v1: {hovered.v_ratio}</span>
            )}
          </div>
          {hovered.l34_near_miss && (
            <div className={styles.ttNearMiss}>
              near-miss — failed: <strong style={{ color: '#ff8800' }}>{hovered.l34_near_miss.failed}</strong>
            </div>
          )}
          {hovered.l34_conditions && (
            <div className={styles.ttConds}>
              {Object.entries(hovered.l34_conditions).map(([k, v]) => (
                <span key={k} style={{ marginRight: 6 }}>
                  <CondDot pass={v} /> {k}
                </span>
              ))}
            </div>
          )}
          {hovered.t_signals_fired && hovered.t_signals_fired.length > 0 && (
            <div className={styles.ttSigs}>T: {hovered.t_signals_fired.join(' ')}</div>
          )}
          {hovered.z_signals_fired && hovered.z_signals_fired.length > 0 && (
            <div className={styles.ttSigs}>Z: {hovered.z_signals_fired.join(' ')}</div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Signal stats table ────────────────────────────────────────────────────────

function SignalStats({ sa }) {
  if (!sa) return null;
  const rows = [
    { sig: 'L34',   d: sa.l34,   desc: 'quiet bull setup'       },
    { sig: 'FRI34', d: sa.fri34, desc: 'L34 + BLUE volume'      },
    { sig: 'G4',    d: sa.g4,    desc: 'bearish rest → trigger'  },
    { sig: 'B2',    d: sa.b2,    desc: 'confirmation pattern'   },
  ];
  return (
    <table className={styles.statsTable}>
      <thead>
        <tr>
          <th>Signal</th>
          <th>Description</th>
          <th>All Fires</th>
          <th>Recent</th>
          <th>Near-miss</th>
          <th>Last (bars ago)</th>
          {sa.g4 && <th>Arms / Consumed</th>}
        </tr>
      </thead>
      <tbody>
        {rows.map(({ sig, d, desc }) => (
          <tr key={sig} className={(d?.fires_recent ?? 0) > 0 ? styles.rowActive : ''}>
            <td className={styles.sigName}>{sig}</td>
            <td className={styles.sigDesc}>{desc}</td>
            <td className={styles.num}>{d?.fires_all ?? '—'}</td>
            <td className={styles.num} style={{ color: (d?.fires_recent ?? 0) > 0 ? '#00ff88' : '#888' }}>
              {d?.fires_recent ?? '—'}
            </td>
            <td className={styles.num} style={{ color: (d?.near_misses_30 ?? 0) > 0 ? '#ff8800' : '#555' }}>
              {d?.near_misses_30 ?? '—'}
            </td>
            <td className={styles.num} style={{ color: d?.last_fire_bars_ago != null ? '#aaa' : '#555' }}>
              {d?.last_fire_bars_ago ?? '—'}
            </td>
            {sa.g4 && (
              <td className={styles.num} style={{ color: '#888' }}>
                {sig === 'G4' ? `${d?.arm_events_all ?? 0} / ${d?.consumed_events ?? 0}` : ''}
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Near-miss breakdown ───────────────────────────────────────────────────────

function NearMissBreakdown({ nms }) {
  if (!nms || !nms.length) return (
    <p className={styles.emptyNote}>No L34 near-misses in last 30 bars.</p>
  );

  const counts = {};
  nms.forEach((n) => { counts[n.failed] = (counts[n.failed] || 0) + 1; });
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);

  const EXPLANATIONS = {
    c_le_h1: 'Close broke above prior high — stock too strong / gapping up',
    v_gt_v1: 'Volume did not increase vs prior bar',
    c_ge_o:  'Bear candle (close < open)',
    c_gt_c1: 'Close did not improve vs prior close',
  };

  return (
    <div className={styles.nmSection}>
      <div className={styles.nmBar}>
        {sorted.map(([cond, cnt]) => (
          <div key={cond} className={styles.nmItem}>
            <span className={styles.nmCond}>{cond}</span>
            <span className={styles.nmCount}>{cnt}×</span>
            <span className={styles.nmExpl}>{EXPLANATIONS[cond] || cond}</span>
          </div>
        ))}
      </div>
      <details className={styles.nmDetails}>
        <summary className={styles.nmDetailsSummary}>Show per-bar near-misses ({nms.length})</summary>
        <table className={styles.nmTable}>
          <thead><tr><th>Bars Ago</th><th>Failed</th><th>v&gt;v1</th><th>c&gt;c1</th><th>c≤h1</th><th>c≥o</th></tr></thead>
          <tbody>
            {nms.map((n, i) => (
              <tr key={i}>
                <td>{n.bars_ago}</td>
                <td style={{ color: '#ff8800', fontWeight: 700 }}>{n.failed}</td>
                <td><CondDot pass={n.passed.includes('v_gt_v1')} /></td>
                <td><CondDot pass={n.passed.includes('c_gt_c1')} /></td>
                <td><CondDot pass={n.passed.includes('c_le_h1')} /></td>
                <td><CondDot pass={n.passed.includes('c_ge_o')}  /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

// ── G4 arm/consume detail ─────────────────────────────────────────────────────

function G4Detail({ sa }) {
  const g4 = sa?.g4;
  if (!g4 || (!g4.arm_detail?.length && !g4.consumed_detail?.length)) return null;
  return (
    <div className={styles.g4Section}>
      {g4.arm_detail?.length > 0 && (
        <div>
          <div className={styles.g4SubHdr}>Last arm events (Z10/Z11/Z12)</div>
          <table className={styles.nmTable}>
            <thead><tr><th>Bars Ago</th><th>Z Signals</th></tr></thead>
            <tbody>
              {g4.arm_detail.map((e, i) => (
                <tr key={i}>
                  <td>{e.bars_ago}</td>
                  <td style={{ color: '#00e5ff' }}>{e.z_signals?.join(' ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {g4.consumed_detail?.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className={styles.g4SubHdr}>Last consumed (T1/T1G/T6 consumed arm before T4)</div>
          <table className={styles.nmTable}>
            <thead><tr><th>Bars Ago</th><th>Consumed By</th></tr></thead>
            <tbody>
              {g4.consumed_detail.map((e, i) => (
                <tr key={i}>
                  <td>{e.bars_ago}</td>
                  <td style={{ color: '#ff8800' }}>{e.consumed_by?.join(' ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Final result badge ────────────────────────────────────────────────────────

const LABEL_COLOR = {
  NEW_PUMP_FIRE:         '#ff4400',
  NEW_PUMP_STRONG:       '#ff8800',
  NEW_PUMP_SETUP:        '#ffd600',
  NEW_PUMP_TRIGGER_ONLY: '#00e5ff',
  NEW_PUMP_WEAK:         '#888',
  NEW_PUMP_NONE:         '#444',
};

const STATE_COLOR = {
  CONFIRMED:    '#ff4400',
  TRIGGERED:    '#ff8800',
  PRE_TRIGGER:  '#ffd600',
  FAILED_SETUP: '#888',
  BROKEN_SETUP: '#666',
  OVEREXTENDED: '#c084fc',
  IMPULSE:      '#00e5ff',
  NEUTRAL:      '#555',
};

function FinalBadge({ result }) {
  if (!result) return null;
  const lbl = result.new_pump_label || 'NEW_PUMP_NONE';
  const col = LABEL_COLOR[lbl] || '#444';
  return (
    <div className={styles.finalBadge} style={{ borderColor: col, color: col }}>
      <span className={styles.finalLabel}>{lbl.replace('NEW_PUMP_', '')}</span>
      {result.new_pump_score != null && (
        <span className={styles.finalScore}>{result.new_pump_score}</span>
      )}
      {result.new_pump_sequence_label && (
        <span className={styles.finalSeq}>{result.new_pump_sequence_label}</span>
      )}
    </div>
  );
}

function StateRow({ result }) {
  if (!result) return null;
  const state = result.state || 'NEUTRAL';
  const path  = result.engine_path || 'structure';
  const col   = STATE_COLOR[state] || '#555';
  return (
    <div className={styles.stateRow}>
      <span className={styles.stateChip} style={{ color: col, borderColor: `${col}55`, background: `${col}14` }}>
        {state}
      </span>
      <span className={styles.pathChip} style={{ color: path === 'impulse' ? '#00e5ff' : '#8f8fba' }}>
        {path === 'impulse' ? '⚡ IMPULSE PATH' : '⬡ STRUCTURE PATH'}
      </span>
      {result.missing_piece && (
        <span className={styles.missingChip}>
          missing: <strong>{result.missing_piece}</strong>
        </span>
      )}
      {result.main_risk && (
        <span className={styles.riskChip}>
          risk: <strong>{result.main_risk}</strong>
        </span>
      )}
    </div>
  );
}

function ImpulseBlock({ result }) {
  if (!result || !result.impulse_score) return null;
  const score = result.impulse_score;
  const lbl   = result.impulse_label;
  if (score < 1) return null;
  const col = lbl === 'IMPULSE_STRONG' ? '#00e5ff' : '#8f8fba';
  return (
    <div className={styles.impulseBlock} style={{ borderColor: `${col}44` }}>
      <span className={styles.impulseLabel} style={{ color: col }}>
        {lbl || 'IMPULSE'} ⚡
      </span>
      <span className={styles.impulseScore}>score: {score}</span>
      <span className={styles.impulseNote}>
        Explosive volume/price move detected on the parallel impulse path.
        {!lbl && ' Score below threshold — not labeled.'}
      </span>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function SignalAnatomy() {
  const [input, setInput]     = useState('');
  const [loading, setLoading] = useState(false);
  const [report, setReport]   = useState(null);
  const [error, setError]     = useState(null);

  const analyze = useCallback(async () => {
    const sym = input.trim().toUpperCase();
    if (!sym) return;
    setLoading(true);
    setReport(null);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/new-pump/anatomy/${sym}`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
      } else {
        setReport(data);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [input]);

  const onKey = useCallback((e) => {
    if (e.key === 'Enter') analyze();
  }, [analyze]);

  const downloadAiPacket = useCallback(() => {
    if (!report) return;
    const sym = (report.symbol || input || 'signal').toUpperCase();
    const stamp = new Date().toISOString().slice(0, 10);
    downloadJson(`${sym}-signal-anatomy-ai-packet-${stamp}.json`, buildAiPacket(report));
  }, [input, report]);

  return (
    <>
      <Head><title>Signal Anatomy — Pump Scout</title></Head>
      <AppNav />
      <div className={styles.page}>
        <div className={styles.header}>
          <h1 className={styles.title}>Signal Anatomy</h1>
          <p className={styles.subtitle}>WHY DID THE NEW PUMP ENGINE NOT FIRE?</p>
        </div>

        <div className={styles.inputRow}>
          <input
            className={styles.symInput}
            value={input}
            onChange={(e) => setInput(e.target.value.toUpperCase())}
            onKeyDown={onKey}
            placeholder="Enter ticker…"
            spellCheck={false}
            autoCapitalize="characters"
          />
          <button className={styles.analyzeBtn} onClick={analyze} disabled={loading || !input.trim()}>
            {loading ? 'Analyzing…' : 'Analyze'}
          </button>
        </div>

        {error && <div className={styles.errorBox}>{error}</div>}

        {report && (
          <div className={styles.report}>

            {/* ── Final result ── */}
            <div className={styles.section}>
              <div className={styles.resultHeader}>
                <div className={styles.sectionHdr}>Engine Result</div>
                <button className={styles.downloadBtn} onClick={downloadAiPacket}>
                  Download AI Packet
                </button>
              </div>
              <FinalBadge result={report.final} />
              <StateRow result={report.final} />
              <ImpulseBlock result={report.final} />
              <div className={styles.metaRow}>
                <span className={styles.metaItem}>bars: <strong>{report.n_candles}</strong></span>
                {report.final?.new_pump_score != null && (
                  <span className={styles.metaItem}>score: <strong>{report.final.new_pump_score}</strong></span>
                )}
                {report.is_no_signal && (
                  <span className={styles.noSigBadge}>NO STRUCTURAL SIGNAL</span>
                )}
              </div>
            </div>

            {/* ── Diagnosis ── */}
            <div className={styles.section}>
              <div className={styles.sectionHdr}>Diagnosis</div>
              <ul className={styles.diagList}>
                {(report.diagnosis || []).map((d, i) => (
                  <li key={i} className={styles.diagItem}>{d}</li>
                ))}
              </ul>
            </div>

            {/* ── Signal stats ── */}
            <div className={styles.section}>
              <div className={styles.sectionHdr}>Signal Fire History</div>
              <SignalStats sa={report.signal_analysis} />
            </div>

            {/* ── 30-bar timeline ── */}
            <div className={styles.section}>
              <div className={styles.sectionHdr}>Last 30 Bars (hover for detail)</div>
              <BarTimeline bars={report.bar_anatomy} />
            </div>

            {/* ── L34 near-misses ── */}
            <div className={styles.section}>
              <div className={styles.sectionHdr}>
                L34 Near-Misses — Last 30 Bars
                <span className={styles.sectionNote}>(3 of 4 conditions passed)</span>
              </div>
              <NearMissBreakdown nms={report.l34_near_misses_30} />
            </div>

            {/* ── G4 arm/consume ── */}
            {(report.signal_analysis?.g4?.arm_events_all > 0) && (
              <div className={styles.section}>
                <div className={styles.sectionHdr}>G4 Arm / Consume History</div>
                <G4Detail sa={report.signal_analysis} />
              </div>
            )}

            {/* ── Raw bar detail ── */}
            <div className={styles.section}>
              <div className={styles.sectionHdr}>Per-Bar Detail — Last 30 Bars</div>
              <div className={styles.tableWrap}>
                <table className={styles.barTable}>
                  <thead>
                    <tr>
                      <th>Ago</th>
                      <th>Close</th>
                      <th>V/V1</th>
                      <th>Vol Z</th>
                      <th>RSI R3</th>
                      <th>L34</th>
                      <th>FRI34</th>
                      <th>G4</th>
                      <th>B2</th>
                      <th>Armed</th>
                      <th>v&gt;v1</th>
                      <th>c&gt;c1</th>
                      <th>c≤h1</th>
                      <th>c≥o</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(report.bar_anatomy || []).map((b) => {
                      const conds = b.l34_conditions || {};
                      const nm = b.l34_near_miss;
                      return (
                        <tr key={b.bar_idx} className={nm ? styles.nmRow : ''}>
                          <td className={styles.agoCell}>{b.bars_ago}</td>
                          <td className={styles.numCell}>{b.close}</td>
                          <td className={styles.numCell}>{b.v_ratio ?? '—'}</td>
                          <td><VzBadge vz={b.volume_z} /></td>
                          <td><RsiBadge rr={b.rsi_range3} /></td>
                          <td><SignalPill on={b.l34}   label="L34"   /></td>
                          <td><SignalPill on={b.fri34} label="FRI34" /></td>
                          <td><SignalPill on={b.g4}    label="G4"    /></td>
                          <td><SignalPill on={b.b2}    label="B2"    /></td>
                          <td>{b.g4_armed ? <span className={styles.armedTag}>ARM</span> : ''}</td>
                          <td><CondDot pass={conds.v_gt_v1} /></td>
                          <td><CondDot pass={conds.c_gt_c1} /></td>
                          <td><CondDot pass={conds.c_le_h1} /></td>
                          <td><CondDot pass={conds.c_ge_o}  /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

          </div>
        )}
      </div>
    </>
  );
}
