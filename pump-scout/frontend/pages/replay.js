/**
 * Replay — Historical Backdated Scan Mode
 * Research-only page. Runs the scanner pipeline on past dates with
 * strict temporal isolation (no future leakage).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import Head from 'next/head';
import AppNav from '../components/AppNav';
import styles from '../styles/Replay.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const POLL_MS  = 2000;

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n, decimals = 1) {
  if (n === null || n === undefined) return '—';
  return typeof n === 'number' ? n.toFixed(decimals) : n;
}

function pctCell(v) {
  if (v === null || v === undefined) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const color = v >= 0 ? 'var(--lime)' : 'var(--red)';
  return <span style={{ color, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{v >= 0 ? '+' : ''}{fmt(v)}%</span>;
}

const NP_LABEL_COLORS = {
  NEW_PUMP_FIRE:         '#ff4400',
  NEW_PUMP_STRONG:       '#ff8800',
  NEW_PUMP_SETUP:        '#ffd600',
  NEW_PUMP_TRIGGER_ONLY: '#00e5ff',
  NEW_PUMP_WEAK:         '#888',
  NEW_PUMP_NONE:         '#444',
};
const NP_LABEL_SHORT = {
  NEW_PUMP_FIRE:         'FIRE',
  NEW_PUMP_STRONG:       'STRONG',
  NEW_PUMP_SETUP:        'SETUP',
  NEW_PUMP_TRIGGER_ONLY: 'TRIGGER',
  NEW_PUMP_WEAK:         'WEAK',
  NEW_PUMP_NONE:         'NONE',
};
function npScoreColor(s) {
  if (s == null) return 'var(--text-muted)';
  if (s >= 70) return '#ff4400';
  if (s >= 55) return '#ff8800';
  if (s >= 40) return '#ffd600';
  if (s >= 25) return '#00e5ff';
  if (s >= 10) return '#888';
  return '#444';
}
function NpLabelBadge({ label }) {
  const color = NP_LABEL_COLORS[label] || '#444';
  const short = NP_LABEL_SHORT[label] || label || '—';
  return (
    <span style={{
      color, fontWeight: 700, fontSize: 9, letterSpacing: '0.06em',
      padding: '1px 5px', borderRadius: 3,
      background: color === '#444' ? 'transparent' : color + '18',
      border: `1px solid ${color}44`,
    }}>{short}</span>
  );
}

function TierBadge({ tier }) {
  const cls = {
    FIRE: styles.tierFire,
    ARM:  styles.tierArm,
    BASE: styles.tierBase,
    WATCH: styles.tierWatch,
  }[tier] || styles.tierOther;
  return <span className={cls} style={{ fontWeight: 700 }}>{tier || '—'}</span>;
}

function StatusBadge({ status }) {
  const cls = {
    running:   styles.statusRunning,
    completed: styles.statusCompleted,
    failed:    styles.statusFailed,
  }[status] || '';
  return <span className={`${styles.statusBadge} ${cls}`}>{status || 'unknown'}</span>;
}

const OUTCOME_COLORS = {
  SUCCESSFUL_BREAKOUT: 'var(--lime)',
  EARLY_WINNER:        'var(--cyan)',
  NO_FOLLOW_THROUGH:   'var(--text-muted)',
  LATE_SIGNAL:         'var(--amber)',
  FAILED_BREAKOUT:     'var(--red)',
  FALSE_POSITIVE:      '#ff4466',
  NO_DATA:             'var(--text-dim)',
};

function OutcomeLabel({ label }) {
  const color = OUTCOME_COLORS[label] || 'var(--text-muted)';
  const short = {
    SUCCESSFUL_BREAKOUT: 'BREAKOUT',
    EARLY_WINNER:        'EARLY WIN',
    NO_FOLLOW_THROUGH:   'NO FOLLOW',
    LATE_SIGNAL:         'LATE SIG',
    FAILED_BREAKOUT:     'FAILED',
    FALSE_POSITIVE:      'FALSE POS',
    NO_DATA:             'NO DATA',
  }[label] || label;
  return (
    <span style={{
      color, fontWeight: 700, fontSize: 9, letterSpacing: '0.06em',
      padding: '2px 7px', borderRadius: 'var(--r-pill)',
      background: `${color}18`, border: `1px solid ${color}44`,
      whiteSpace: 'nowrap',
    }}>
      {short}
    </span>
  );
}

// ── Bundle Tab component ──────────────────────────────────────────────────────

function BucketTable({ data }) {
  if (!data || data.length === 0) return <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>No data</div>;
  return (
    <table className={styles.bucketTable}>
      <thead>
        <tr>
          <th>Bucket</th>
          <th>#</th>
          <th>Avg 5d</th>
          <th>Win%</th>
          <th>Avg 10d</th>
          <th>Avg DD</th>
          <th>α/SPY 5d</th>
        </tr>
      </thead>
      <tbody>
        {data.map((b, i) => (
          <tr key={i}>
            <td className={styles.bucketName}>{b.bucket}</td>
            <td style={{ fontFamily: 'var(--font-mono)' }}>{b.count}</td>
            <td>{pctCell(b.avg_return_5d)}</td>
            <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
              {b.win_rate_5d != null ? `${b.win_rate_5d}%` : '—'}
            </td>
            <td>{pctCell(b.avg_return_10d)}</td>
            <td>{pctCell(b.avg_max_drawdown_pct)}</td>
            <td>{pctCell(b.alpha_vs_spy_5d)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function PatternReview({ review }) {
  if (!review) return null;
  const sections = [
    { key: 'what_worked',          label: 'What Worked',       itemCls: styles.patternItemWorked },
    { key: 'what_failed',          label: 'What Failed',       itemCls: styles.patternItemFailed },
    { key: 'missed_patterns',      label: 'Missed Patterns',   itemCls: styles.patternItem },
    { key: 'likely_strict_filters',label: 'Too Strict',        itemCls: styles.patternItemStrict },
    { key: 'likely_noisy_filters', label: 'Too Noisy',         itemCls: styles.patternItemStrict },
    { key: 'suggested_focus',      label: 'Suggested Focus',   itemCls: styles.patternItemFocus },
  ];
  const nonEmpty = sections.filter(s => (review[s.key] || []).length > 0);
  if (!nonEmpty.length) return <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>Insufficient data for pattern analysis.</div>;
  return (
    <div className={styles.patternGrid}>
      {nonEmpty.map(({ key, label, itemCls }) => (
        <div key={key} className={styles.patternCard}>
          <div className={styles.patternCardTitle}>{label}</div>
          {(review[key] || []).map((item, i) => (
            <div key={i} className={`${styles.patternItem} ${itemCls}`}>{item}</div>
          ))}
        </div>
      ))}
    </div>
  );
}

function ExperimentCard({ exp, idx }) {
  const confCls = {
    HIGH:   styles.confHigh,
    MEDIUM: styles.confMedium,
    LOW:    styles.confLow,
  }[exp.confidence] || styles.confLow;
  return (
    <div className={`${styles.experimentCard} ${confCls}`}>
      <div className={styles.experimentTitle}>{idx}. {exp.title}</div>
      <div className={styles.experimentMeta}>
        <span className={styles.experimentType}>{exp.experiment_type}</span>
        <span className={styles.experimentConf}>{exp.confidence}</span>
      </div>
      <div className={styles.experimentDesc}>{exp.description}</div>
      {exp.evidence && <div className={styles.experimentEvidence}>Evidence: {exp.evidence}</div>}
    </div>
  );
}

// Compact decision summary derived from bundle data
function DecisionSummary({ bundle }) {
  if (!bundle) return null;

  const npLabelRows  = bundle.performance_by_new_pump_label    || [];
  const npSeqRows    = bundle.performance_by_new_pump_sequence || [];
  const exps         = bundle.suggested_experiments            || [];
  const fps          = bundle.false_positives                  || [];
  const mm           = bundle.missed_movers                    || [];

  const nonTrivial   = r => (r?.count ?? 0) >= 3 && r?.bucket && r.bucket !== 'NEW_PUMP_NONE';
  const byReturn     = rows => [...rows].filter(nonTrivial)
                                .sort((a, b) => (b.avg_return_5d ?? -999) - (a.avg_return_5d ?? -999));

  const lblRanked    = byReturn(npLabelRows);
  const seqRanked    = byReturn(npSeqRows);
  const bestLabel    = lblRanked[0];
  const worstLabel   = lblRanked[lblRanked.length - 1];
  const bestSeq      = seqRanked[0];
  const worstSeq     = seqRanked[seqRanked.length - 1];

  const topExps      = exps.slice(0, 2);

  const Block = ({ color, title, children }) => (
    <div style={{
      borderTop: `3px solid ${color}`,
      padding: '10px 12px',
      background: 'var(--bg-elev)',
      borderRadius: 'var(--r-sm)',
    }}>
      <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.07em',
                    color, textTransform: 'uppercase', marginBottom: 6 }}>
        {title}
      </div>
      {children}
    </div>
  );

  const Item = ({ label, value, sub }) => (
    <div style={{ fontSize: 11, lineHeight: 1.45, marginBottom: 4 }}>
      <span style={{ color: 'var(--text-muted)' }}>{label}: </span>
      <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{value}</span>
      {sub != null && (
        <span style={{ color: 'var(--text-dim)', fontSize: 9, marginLeft: 6 }}>{sub}</span>
      )}
    </div>
  );

  const fmtReturn = r => {
    if (r?.avg_return_5d == null) return '—';
    const v = Number(r.avg_return_5d).toFixed(2);
    return `${r.bucket} · ${v >= 0 ? '+' : ''}${v}% avg 5d`;
  };

  return (
    <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12, marginTop: 4 }}>
      <div style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em',
                    color: 'var(--accent)', textTransform: 'uppercase', marginBottom: 10 }}>
        ◈ Decision Summary
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
        <Block color="var(--lime)" title="Works Better">
          <Item label="Best label"    value={bestLabel ? fmtReturn(bestLabel) : '—'}
                sub={bestLabel ? `n=${bestLabel.count}` : null} />
          <Item label="Best sequence" value={bestSeq   ? fmtReturn(bestSeq)   : '—'}
                sub={bestSeq   ? `n=${bestSeq.count}`   : null} />
        </Block>
        <Block color="var(--red)" title="Looks Weak">
          <Item label="Weakest label"    value={worstLabel && worstLabel !== bestLabel ? fmtReturn(worstLabel) : '—'}
                sub={worstLabel && worstLabel !== bestLabel ? `n=${worstLabel.count}` : null} />
          <Item label="Weakest sequence" value={worstSeq   && worstSeq   !== bestSeq   ? fmtReturn(worstSeq)   : '—'}
                sub={worstSeq   && worstSeq   !== bestSeq   ? `n=${worstSeq.count}`   : null} />
          <Item label="False positives"  value={`${fps.length}`} sub={`missed movers ${mm.length}`} />
        </Block>
        <Block color="var(--cyan)" title="Try Next">
          {topExps.length === 0 ? (
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>No suggestions — insufficient data.</div>
          ) : topExps.map((e, i) => (
            <div key={i} style={{ fontSize: 11, lineHeight: 1.35, marginBottom: 4 }}>
              <span style={{ fontWeight: 700 }}>{i + 1}. </span>
              <span>{e.title}</span>
              <span style={{ color: 'var(--text-dim)', fontSize: 9, marginLeft: 4 }}>
                [{e.experiment_type} · {e.confidence}]
              </span>
            </div>
          ))}
        </Block>
      </div>
    </div>
  );
}

// ── D/WLNBB Combination Winrate Matrix ───────────────────────────────────────

const DW_FAMILIES  = ['ALL','SAME_BAR_L34','SAME_BAR_L43','SAME_BAR_BEUP','L34_THEN_D','L43_THEN_D','D_THEN_BEUP','TRIPLE_D_L34_BEUP'];
const DW_DSIGS     = ['ALL','D1','D3','D4','D6','D9','D11'];
const DW_WLNBB     = ['ALL','L34','L43','BE_UP'];
const DW_TIMINGS   = ['ALL','SAME_BAR','BASE_THEN_D_3B','D_THEN_BEUP_5B'];
const DW_MINCOUNTS = [1,3,5,10];
const DW_SORT_KEYS = ['count','win_rate_5d','avg_return_5d','avg_return_10d','false_positive_rate','avg_max_drawdown_pct'];

const DW_HEATMAP_ROWS = ['D1','D3','D4','D6','D9','D11'];
const DW_HEATMAP_COLS = [
  {label:'L34 SAME', sig_d:null, sig_w:'L34',   timing:'SAME_BAR'},
  {label:'L43 SAME', sig_d:null, sig_w:'L43',   timing:'SAME_BAR'},
  {label:'BE SAME',  sig_d:null, sig_w:'BE_UP',  timing:'SAME_BAR'},
  {label:'L34→D',    sig_d:null, sig_w:'L34',   timing:'BASE_THEN_D_3B'},
  {label:'L43→D',    sig_d:null, sig_w:'L43',   timing:'BASE_THEN_D_3B'},
  {label:'D→BE',     sig_d:null, sig_w:'BE_UP',  timing:'D_THEN_BEUP_5B'},
];

function dwRowColor(row) {
  if (!row || row.count < 5) return '#2a2a2a';
  const wr = row.win_rate_5d ?? 0;
  const ar = row.avg_return_5d ?? 0;
  if (wr >= 60 && ar > 0)  return 'rgba(76,175,80,0.18)';
  if (wr < 40  || ar < 0)  return 'rgba(244,67,54,0.14)';
  if (ar > 0.5 && row.count < 10) return 'rgba(255,193,7,0.14)';
  return 'transparent';
}

function fmt(v, decimals=1) {
  if (v == null) return '—';
  return Number(v).toFixed(decimals);
}

function DWlnbbMatrix({ bundle }) {
  const matrix  = bundle.d_wlnbb_combination_matrix  ?? [];
  const summary = bundle.d_wlnbb_combination_summary  ?? {};

  const [familyFilter,  setFamilyFilter]  = useState('ALL');
  const [dFilter,       setDFilter]       = useState('ALL');
  const [wFilter,       setWFilter]       = useState('ALL');
  const [timingFilter,  setTimingFilter]  = useState('ALL');
  const [minCount,      setMinCount]      = useState(1);
  const [sortKey,       setSortKey]       = useState('count');
  const [sortDir,       setSortDir]       = useState(-1);
  const [viewMode,      setViewMode]      = useState('table');
  const [expanded,      setExpanded]      = useState(false);

  if (!matrix.length) return null;

  function toggleSort(key) {
    if (sortKey === key) setSortDir(d => -d);
    else { setSortKey(key); setSortDir(-1); }
  }

  const filtered = matrix
    .filter(r =>
      (familyFilter === 'ALL' || r.family      === familyFilter) &&
      (dFilter      === 'ALL' || r.signal_d    === dFilter)      &&
      (wFilter      === 'ALL' || r.signal_wlnbb=== wFilter)      &&
      (timingFilter === 'ALL' || r.timing      === timingFilter)  &&
      r.count >= minCount
    )
    .sort((a,b) => {
      const av = a[sortKey] ?? (sortDir > 0 ? Infinity : -Infinity);
      const bv = b[sortKey] ?? (sortDir > 0 ? Infinity : -Infinity);
      return sortDir * (bv - av);
    });

  // Heatmap lookup
  function heatCell(dsig, col) {
    return matrix.find(r =>
      r.signal_d     === dsig &&
      r.signal_wlnbb === col.sig_w &&
      r.timing       === col.timing
    );
  }

  const selClass = s => ({ background: s ? '#1e1e40' : '#13132a', border: `1px solid ${s ? '#5c6bc0' : '#242438'}`, borderRadius: 3, color: s ? '#fff' : '#666', cursor:'pointer', fontSize:10, fontFamily:'inherit', padding:'3px 8px' });

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:8, flexWrap:'wrap' }}>
        <span style={{ fontSize:10, color:'#888', fontWeight:700, letterSpacing:'0.5px', textTransform:'uppercase' }}>View</span>
        {['table','heatmap'].map(m => (
          <button key={m} style={selClass(viewMode===m)} onClick={() => setViewMode(m)}>{m}</button>
        ))}
        <span style={{ fontSize:10, color:'#444', marginLeft:8 }}>Family:</span>
        <select value={familyFilter} onChange={e => setFamilyFilter(e.target.value)} style={{ background:'#13132a', border:'1px solid #242438', color:'#aaa', fontSize:10, borderRadius:3, padding:'2px 6px', fontFamily:'inherit' }}>
          {DW_FAMILIES.map(f => <option key={f} value={f}>{f}</option>)}
        </select>
        <span style={{ fontSize:10, color:'#444' }}>D:</span>
        <select value={dFilter} onChange={e => setDFilter(e.target.value)} style={{ background:'#13132a', border:'1px solid #242438', color:'#aaa', fontSize:10, borderRadius:3, padding:'2px 6px', fontFamily:'inherit' }}>
          {DW_DSIGS.map(d => <option key={d} value={d}>{d}</option>)}
        </select>
        <span style={{ fontSize:10, color:'#444' }}>WLNBB:</span>
        <select value={wFilter} onChange={e => setWFilter(e.target.value)} style={{ background:'#13132a', border:'1px solid #242438', color:'#aaa', fontSize:10, borderRadius:3, padding:'2px 6px', fontFamily:'inherit' }}>
          {DW_WLNBB.map(w => <option key={w} value={w}>{w}</option>)}
        </select>
        <span style={{ fontSize:10, color:'#444' }}>Timing:</span>
        <select value={timingFilter} onChange={e => setTimingFilter(e.target.value)} style={{ background:'#13132a', border:'1px solid #242438', color:'#aaa', fontSize:10, borderRadius:3, padding:'2px 6px', fontFamily:'inherit' }}>
          {DW_TIMINGS.map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <span style={{ fontSize:10, color:'#444' }}>Min n:</span>
        <select value={minCount} onChange={e => setMinCount(Number(e.target.value))} style={{ background:'#13132a', border:'1px solid #242438', color:'#aaa', fontSize:10, borderRadius:3, padding:'2px 6px', fontFamily:'inherit' }}>
          {DW_MINCOUNTS.map(n => <option key={n} value={n}>{n}</option>)}
        </select>
      </div>

      {viewMode === 'heatmap' ? (
        <div style={{ overflowX:'auto' }}>
          <table style={{ borderCollapse:'collapse', fontSize:11, whiteSpace:'nowrap' }}>
            <thead>
              <tr>
                <th style={{ padding:'6px 10px', color:'#555', textAlign:'left', borderBottom:'1px solid #242438' }}>D \ WLNBB</th>
                {DW_HEATMAP_COLS.map(col => (
                  <th key={col.label} style={{ padding:'6px 10px', color:'#777', borderBottom:'1px solid #242438', textAlign:'center', fontSize:10 }}>{col.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {DW_HEATMAP_ROWS.map(dsig => (
                <tr key={dsig}>
                  <td style={{ padding:'6px 10px', color:'#bbb', fontWeight:700 }}>{dsig}</td>
                  {DW_HEATMAP_COLS.map(col => {
                    const cell = heatCell(dsig, col);
                    const bg   = dwRowColor(cell);
                    return (
                      <td key={col.label} style={{ padding:'6px 8px', background:bg, textAlign:'center', border:'1px solid #1a1a2e', minWidth:72 }}>
                        {cell ? (
                          <>
                            <div style={{ fontSize:12, fontWeight:700, color: (cell.win_rate_5d ?? 0) >= 55 ? '#81c784' : (cell.win_rate_5d ?? 0) < 40 ? '#e57373' : '#ccc' }}>
                              {fmt(cell.win_rate_5d)}%
                            </div>
                            <div style={{ fontSize:9, color:'#555' }}>n={cell.count}</div>
                          </>
                        ) : <span style={{ color:'#333' }}>—</span>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div style={{ overflowX:'auto', border:'1px solid #242438', borderRadius:6 }}>
          <table style={{ width:'100%', borderCollapse:'collapse', fontSize:11, whiteSpace:'nowrap' }}>
            <thead>
              <tr>
                {[
                  ['combination','Combination'],
                  ['family','Family'],
                  ['signal_d','D'],
                  ['signal_wlnbb','WLNBB'],
                  ['timing','Timing'],
                  ['count','n'],
                  ['win_rate_1d','WR1d%'],
                  ['win_rate_3d','WR3d%'],
                  ['win_rate_5d','WR5d%'],
                  ['win_rate_10d','WR10d%'],
                  ['avg_return_1d','Avg1d%'],
                  ['avg_return_3d','Avg3d%'],
                  ['avg_return_5d','Avg5d%'],
                  ['avg_return_10d','Avg10d%'],
                  ['median_return_5d','Med5d%'],
                  ['avg_max_gain_pct','MaxGain%'],
                  ['avg_max_drawdown_pct','MaxDD%'],
                  ['alpha_vs_spy_5d','α5d'],
                  ['alpha_vs_spy_10d','α10d'],
                  ['false_positive_count','FP#'],
                  ['false_positive_rate','FP%'],
                  ['failed_breakout_count','FB#'],
                  ['no_follow_through_count','NFT#'],
                ].map(([key, label]) => {
                  const sortable = DW_SORT_KEYS.includes(key);
                  return (
                    <th key={key}
                      onClick={sortable ? () => toggleSort(key) : undefined}
                      style={{ padding:'7px 10px', background:'#10101e', color: sortKey===key ? '#9fa8da' : '#666', textAlign: ['combination','family','signal_d','signal_wlnbb','timing'].includes(key) ? 'left' : 'right', borderBottom:'1px solid #242438', cursor: sortable ? 'pointer' : 'default', fontWeight:600, userSelect:'none', fontSize:10 }}>
                      {label}{sortable && sortKey===key ? (sortDir > 0 ? ' ↑' : ' ↓') : ''}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {filtered.map((row, i) => {
                const bg = dwRowColor(row);
                return (
                  <tr key={row.combination} style={{ background: i%2===0 ? bg : bg, borderBottom:'1px solid #18182c', cursor: expanded===row.combination ? 'default' : 'pointer' }}
                    onClick={() => setExpanded(expanded===row.combination ? null : row.combination)}>
                    <td style={{ padding:'7px 10px', fontWeight:700, color:'#fff' }}>{row.combination}</td>
                    <td style={{ padding:'7px 10px', color:'#888', fontSize:10 }}>{row.family}</td>
                    <td style={{ padding:'7px 10px', color:'#aaa' }}>{row.signal_d}</td>
                    <td style={{ padding:'7px 10px', color:'#aaa' }}>{row.signal_wlnbb}</td>
                    <td style={{ padding:'7px 10px', color:'#666', fontSize:10 }}>{row.timing}</td>
                    <td style={{ padding:'7px 10px', textAlign:'right', color: row.count < 5 ? '#666' : '#ccc', fontWeight: row.count >= 10 ? 700 : 500 }}>{row.count}</td>
                    {[
                      ['win_rate_1d',  v => `${fmt(v)}%`, v => v >= 55 ? '#81c784' : v < 40 ? '#e57373' : '#ccc'],
                      ['win_rate_3d',  v => `${fmt(v)}%`, v => v >= 55 ? '#81c784' : v < 40 ? '#e57373' : '#ccc'],
                      ['win_rate_5d',  v => `${fmt(v)}%`, v => v >= 55 ? '#81c784' : v < 40 ? '#e57373' : '#ccc'],
                      ['win_rate_10d', v => `${fmt(v)}%`, v => v >= 55 ? '#81c784' : v < 40 ? '#e57373' : '#ccc'],
                      ['avg_return_1d',  v => `${fmt(v)}%`, v => v > 0 ? '#81c784' : '#e57373'],
                      ['avg_return_3d',  v => `${fmt(v)}%`, v => v > 0 ? '#81c784' : '#e57373'],
                      ['avg_return_5d',  v => `${fmt(v)}%`, v => v > 0 ? '#81c784' : '#e57373'],
                      ['avg_return_10d', v => `${fmt(v)}%`, v => v > 0 ? '#81c784' : '#e57373'],
                      ['median_return_5d', v => `${fmt(v)}%`, v => v > 0 ? '#81c784' : '#e57373'],
                      ['avg_max_gain_pct',     v => `${fmt(v)}%`, () => '#9fa8da'],
                      ['avg_max_drawdown_pct', v => `${fmt(v)}%`, v => v < -3 ? '#e57373' : '#ccc'],
                      ['alpha_vs_spy_5d',  v => `${fmt(v)}%`, v => v > 0 ? '#81c784' : '#e57373'],
                      ['alpha_vs_spy_10d', v => `${fmt(v)}%`, v => v > 0 ? '#81c784' : '#e57373'],
                      ['false_positive_count', v => v, () => '#ccc'],
                      ['false_positive_rate',  v => `${fmt(v)}%`, v => v > 30 ? '#e57373' : v < 15 ? '#81c784' : '#ccc'],
                      ['failed_breakout_count',      v => v, () => '#ccc'],
                      ['no_follow_through_count',    v => v, () => '#ccc'],
                    ].map(([key, display, color]) => {
                      const v = row[key];
                      return (
                        <td key={key} style={{ padding:'7px 10px', textAlign:'right', color: v != null ? color(v) : '#333', fontWeight:500 }}>
                          {v != null ? display(v) : '—'}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {filtered.length === 0 && <div style={{ padding:'20px', color:'#555', textAlign:'center', fontSize:11 }}>No combinations match the current filters.</div>}
        </div>
      )}

      {/* Summary block */}
      {summary.best_by_5d_return?.length > 0 && (
        <div style={{ display:'flex', gap:20, flexWrap:'wrap', marginTop:14 }}>
          {[
            ['Best Avg5d Return (n≥3)',  summary.best_by_5d_return,  r => `${fmt(r.avg_return_5d)}%`,  '#81c784'],
            ['Best WinRate5d (n≥3)',     summary.best_by_win_rate_5d, r => `${fmt(r.win_rate_5d)}%`,   '#9fa8da'],
            ['Worst Avg5d Return (n≥3)', summary.worst_by_5d_return, r => `${fmt(r.avg_return_5d)}%`, '#e57373'],
          ].map(([title, rows, valFn, col]) => (
            <div key={title} style={{ background:'#13132a', border:'1px solid #1e1e38', borderRadius:6, padding:'10px 14px', minWidth:180, flex:'1 1 180px' }}>
              <div style={{ fontSize:9, color:'#555', textTransform:'uppercase', letterSpacing:'0.5px', marginBottom:8, fontWeight:700 }}>{title}</div>
              {rows.map((r, i) => (
                <div key={r.combination} style={{ display:'flex', justifyContent:'space-between', gap:10, fontSize:11, marginBottom:3 }}>
                  <span style={{ color:'#bbb', fontWeight:600 }}>{i+1}. {r.combination}</span>
                  <span style={{ color:col, fontWeight:700 }}>{valFn(r)}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
      {summary.min_sample_threshold_note && (
        <div style={{ fontSize:9, color:'#444', marginTop:8 }}>{summary.min_sample_threshold_note}</div>
      )}
    </div>
  );
}

function BundleTab({ bundle, loading, runId, onReload, apiUrl }) {
  const [copied, setCopied] = useState(false);

  async function copyMarkdown() {
    try {
      const r = await fetch(`${apiUrl}/api/replay/${runId}/research-bundle/markdown`);
      if (r.ok) {
        await navigator.clipboard.writeText(await r.text());
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch (_) {}
  }

  function downloadJSON() {
    window.open(`${apiUrl}/api/replay/${runId}/research-bundle/download?format=json`);
  }

  function downloadMarkdown() {
    window.open(`${apiUrl}/api/replay/${runId}/research-bundle/download?format=markdown`);
  }

  if (loading) return <div className={styles.statusMsg}>Building research bundle…</div>;
  if (!bundle) return (
    <div className={styles.emptyMsg}>
      Research bundle not loaded.
      <div className={styles.emptyHint}>
        <button className={styles.runBtn} style={{ width: 'auto', marginTop: 8 }} onClick={onReload}>
          Build Bundle
        </button>
      </div>
    </div>
  );

  const s    = bundle.summary || {};
  const pr   = bundle.pattern_review || {};
  const exps = bundle.suggested_experiments || [];
  const fps  = bundle.false_positives || [];
  const mm   = bundle.missed_movers || [];
  const lc   = s.outcome_label_counts || {};

  return (
    <div className={styles.bundleWrap}>
      {/* Export bar */}
      <div className={styles.exportRow}>
        <div className={styles.researchWarning}>⚠ Research Only — No auto-apply</div>
        <button className={`${styles.exportBtn} ${styles.exportBtnPrimary}`} onClick={copyMarkdown}>
          {copied ? '✓ Copied' : 'Copy Markdown'}
        </button>
        <button className={styles.exportBtn} onClick={downloadJSON}>Download JSON</button>
        <button className={styles.exportBtn} onClick={downloadMarkdown}>Download .md</button>
        <button className={styles.exportBtn} onClick={onReload}>Rebuild</button>
      </div>

      {/* Summary KPIs */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Replay Overview</div>
        <div className={styles.summaryGrid}>
          <div className={styles.summaryKPI}>
            <div className={styles.kpiValue}>{s.total_candidates ?? 0}</div>
            <div className={styles.kpiLabel}>Candidates</div>
          </div>
          <div className={styles.summaryKPI}>
            <div className={styles.kpiValue}>{s.total_outcomes_5d ?? 0}</div>
            <div className={styles.kpiLabel}>5d Outcomes</div>
          </div>
          <div className={styles.summaryKPI}>
            <div className={styles.kpiValue}>{s.total_missed_movers ?? 0}</div>
            <div className={styles.kpiLabel}>Missed Movers</div>
          </div>
          {s.avg_return_5d != null && (
            <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
              <div className={`${styles.kpiValue} ${s.avg_return_5d >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                {s.avg_return_5d >= 0 ? '+' : ''}{fmt(s.avg_return_5d)}%
              </div>
              <div className={styles.kpiLabel}>Avg 5d Return</div>
            </div>
          )}
          {s.win_rate_5d != null && (
            <div className={styles.summaryKPI}>
              <div className={styles.kpiValue}>{fmt(s.win_rate_5d)}%</div>
              <div className={styles.kpiLabel}>Win Rate 5d</div>
            </div>
          )}
          {s.avg_alpha_vs_spy_5d != null && (
            <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
              <div className={`${styles.kpiValue} ${s.avg_alpha_vs_spy_5d >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                {s.avg_alpha_vs_spy_5d >= 0 ? '+' : ''}{fmt(s.avg_alpha_vs_spy_5d)}%
              </div>
              <div className={styles.kpiLabel}>α vs SPY 5d</div>
            </div>
          )}
        </div>

        {/* Outcome label pills */}
        {s.total_outcomes_5d > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
            {[
              ['SUCCESSFUL_BREAKOUT', lc.SUCCESSFUL_BREAKOUT, 'var(--lime)'],
              ['EARLY_WINNER',        lc.EARLY_WINNER,        'var(--cyan)'],
              ['NO_FOLLOW_THROUGH',   lc.NO_FOLLOW_THROUGH,   'var(--text-muted)'],
              ['LATE_SIGNAL',         lc.LATE_SIGNAL,         'var(--amber)'],
              ['FAILED_BREAKOUT',     lc.FAILED_BREAKOUT,     'var(--red)'],
              ['FALSE_POSITIVE',      lc.FALSE_POSITIVE,      '#ff4466'],
            ].filter(([, v]) => v > 0).map(([label, count, color]) => (
              <span key={label} style={{
                fontSize: 9, fontWeight: 700, letterSpacing: '0.05em',
                padding: '2px 8px', borderRadius: 'var(--r-pill)',
                background: `${color}18`, border: `1px solid ${color}44`, color,
              }}>
                {label.replace('_', ' ')}: {count}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* Decision Summary — what works, what looks weak, next experiments */}
      <DecisionSummary bundle={bundle} />

      {/* Performance by Tier */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Performance by Tier</div>
        <BucketTable data={bundle.performance_by_tier} />
      </div>

      {/* Performance by Signal Combo */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Performance by Signal Combination</div>
        <BucketTable data={bundle.performance_by_source} />
      </div>

      {/* ── New Pump Engine ─────────────────────────────────────────────────── */}
      <div className={styles.bundleSection} style={{ borderTop: '1px solid var(--border)', paddingTop: 12, marginTop: 4 }}>
        <div className={styles.bundleSectionTitle} style={{ color: '#ff8800' }}>
          ◈ New Pump Engine — Performance by Label
        </div>
        <BucketTable data={bundle.performance_by_new_pump_label} />
      </div>

      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle} style={{ color: '#ff8800' }}>
          ◈ New Pump Engine — Performance by Sequence
        </div>
        <BucketTable data={bundle.performance_by_new_pump_sequence} />
      </div>

      {/* Triple D + L34 + BE_UP */}
      {(bundle.performance_by_d_l34_beup_same?.length ?? 0) > 0 && (
        <div className={styles.bundleSection} style={{ borderTop: '1px solid var(--border)', paddingTop: 12, marginTop: 4 }}>
          <div className={styles.bundleSectionTitle} style={{ color: '#9c6bde' }}>
            ⬡ Triple D + L34 + BE_UP
          </div>
          <div style={{ fontSize: 9, color: '#555', marginBottom: 8 }}>
            Research only — same-bar D + L34 + BE_UP confluence. Does not affect scoring or routing.
          </div>
          <BucketTable data={bundle.performance_by_d_l34_beup_same} />
          {(bundle.performance_by_triple_inside_decision?.length ?? 0) > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 9, color: '#555', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 700, marginBottom: 6 }}>
                Triple × Decision
              </div>
              <BucketTable data={bundle.performance_by_triple_inside_decision} />
            </div>
          )}
          {(bundle.performance_by_triple_inside_structure_phase?.length ?? 0) > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 9, color: '#555', textTransform: 'uppercase', letterSpacing: '0.5px', fontWeight: 700, marginBottom: 6 }}>
                Triple × Structure Phase
              </div>
              <BucketTable data={bundle.performance_by_triple_inside_structure_phase} />
            </div>
          )}
        </div>
      )}

      {/* False Positives */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Top False Positives / Failures</div>
        {fps.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>No significant false positives in this run.</div>
        ) : (
          <table className={styles.fpTable}>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Date</th>
                <th>Tier</th>
                <th>Score</th>
                <th>3d Ret</th>
                <th>5d Ret</th>
                <th>Max DD</th>
                <th>Label</th>
              </tr>
            </thead>
            <tbody>
              {fps.slice(0, 15).map((fp, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>{fp.symbol}</td>
                  <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>{fp.scan_date || '—'}</td>
                  <td><TierBadge tier={fp.tier} /></td>
                  <td style={{ fontFamily: 'var(--font-mono)' }}>{fp.total_score != null ? fmt(fp.total_score, 1) : '—'}</td>
                  <td>{pctCell(fp.return_3d)}</td>
                  <td>{pctCell(fp.return_5d)}</td>
                  <td>{pctCell(fp.max_drawdown_pct)}</td>
                  <td>{fp.outcome_label ? <OutcomeLabel label={fp.outcome_label} /> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Missed Movers */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Top Missed Movers</div>
        {mm.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>No significant missed movers in this run.</div>
        ) : (
          <table className={styles.fpTable}>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Date</th>
                <th>Price</th>
                <th>3d Ret</th>
                <th>5d Ret</th>
                <th>10d Ret</th>
                <th>Why Missed</th>
                <th>Pre-filtered</th>
              </tr>
            </thead>
            <tbody>
              {mm.slice(0, 15).map((m, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>{m.symbol}</td>
                  <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>{m.scan_date || '—'}</td>
                  <td style={{ fontFamily: 'var(--font-mono)' }}>{m.price_on_date != null ? `$${fmt(m.price_on_date, 2)}` : '—'}</td>
                  <td>{pctCell(m.future_return_3d)}</td>
                  <td>{pctCell(m.future_return_5d)}</td>
                  <td>{pctCell(m.future_return_10d)}</td>
                  <td><span className={styles.whyMissed}>{m.why_missed || '—'}</span></td>
                  <td style={{ color: m.was_filtered_pre_score ? 'var(--amber)' : 'var(--text-muted)', fontSize: 10 }}>
                    {m.was_filtered_pre_score ? 'Yes' : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pattern Review */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Pattern Review</div>
        <PatternReview review={pr} />
      </div>

      {/* Suggested Experiments */}
      <div className={styles.bundleSection}>
        <div className={styles.bundleSectionTitle}>Suggested Experiments</div>
        <div className={styles.researchWarning}>⚠ Proposals only — not auto-applied</div>
        {exps.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>No experiments suggested — run may have insufficient data.</div>
        ) : (
          <div className={styles.experimentsGrid}>
            {exps.map((exp, i) => <ExperimentCard key={i} exp={exp} idx={i + 1} />)}
          </div>
        )}
      </div>

      {/* D/WLNBB Combination Winrate Matrix */}
      {(bundle.d_wlnbb_combination_matrix?.length ?? 0) > 0 && (
        <div className={styles.bundleSection}>
          <div className={styles.bundleSectionTitle}>D / WLNBB Combination Winrate Matrix</div>
          <div className={styles.researchWarning}>⚠ Research only — does not affect scoring, routing, or D formulas</div>
          <DWlnbbMatrix bundle={bundle} />
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ReplayPage() {
  // ── Form state ──────────────────────────────────────────────────────────────
  const [mode, setMode]               = useState('single_day');  // single_day | date_range
  const [singleDate, setSingleDate]   = useState('');
  const [startDate, setStartDate]     = useState('');
  const [endDate, setEndDate]         = useState('');
  const [universeMode, setUniverseMode] = useState('approx');

  // ── Run state ───────────────────────────────────────────────────────────────
  const [launching, setLaunching]     = useState(false);
  const [progress, setProgress]       = useState(null);
  const pollRef                       = useRef(null);

  // ── History + detail ────────────────────────────────────────────────────────
  const [history, setHistory]         = useState([]);
  const [activeRun, setActiveRun]     = useState(null);   // run object
  const [tab, setTab]                 = useState('candidates'); // candidates | outcomes | missed | summary | bundle

  const [candidates, setCandidates]   = useState([]);
  const [outcomes, setOutcomes]       = useState([]);
  const [missed, setMissed]           = useState([]);
  const [summary, setSummary]         = useState(null);
  const [bundle, setBundle]           = useState(null);
  const [bundleLoading, setBundleLoading] = useState(false);

  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError]             = useState('');

  // ── Delete state ────────────────────────────────────────────────────────────
  const [deleteTarget,   setDeleteTarget]   = useState(null);   // run object to confirm
  const [deleting,       setDeleting]       = useState(false);
  const [deleteError,    setDeleteError]    = useState('');

  // ── Polling ─────────────────────────────────────────────────────────────────

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      try {
        const r = await fetch(`${API_URL}/api/replay/status`);
        if (!r.ok) return;
        const p = await r.json();
        setProgress(p);
        if (!p.running) {
          stopPolling();
          // Refresh history + reload active run detail
          loadHistory();
          if (p.run_id) {
            loadRunDetail(p.run_id);
          }
        }
      } catch (_) {}
    }, POLL_MS);
  }, [stopPolling]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  // ── Data loaders ─────────────────────────────────────────────────────────────

  async function loadHistory() {
    try {
      const r = await fetch(`${API_URL}/api/replay/history?limit=20`);
      if (r.ok) {
        const data = await r.json();
        setHistory(Array.isArray(data) ? data : (data.runs || []));
      }
    } catch (_) {}
  }

  async function handleDeleteConfirm() {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError('');
    try {
      const res = await fetch(`${API_URL}/api/replay/${deleteTarget.id}`, { method: 'DELETE' });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${res.status}`);
      }
      // Clear selection if deleted run was active
      if (activeRun?.id === deleteTarget.id) {
        setActiveRun(null);
        setCandidates([]);
        setOutcomes([]);
        setMissed([]);
        setSummary(null);
        setBundle(null);
        stopPolling();
      }
      setHistory(prev => prev.filter(r => r.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch (err) {
      setDeleteError(err.message || 'Delete failed');
    } finally {
      setDeleting(false);
    }
  }

  async function loadRunDetail(runId) {
    setLoadingDetail(true);
    try {
      const [runR, candR, summR] = await Promise.all([
        fetch(`${API_URL}/api/replay/${runId}`),
        fetch(`${API_URL}/api/replay/${runId}/candidates?limit=200`),
        fetch(`${API_URL}/api/replay/${runId}/summary`),
      ]);
      if (runR.ok)  setActiveRun(await runR.json());
      if (candR.ok) {
        const data = await candR.json();
        setCandidates(Array.isArray(data) ? data : (data.candidates || []));
      }
      if (summR.ok) setSummary(await summR.json());
    } catch (_) {}
    setLoadingDetail(false);
  }

  async function loadOutcomes(runId) {
    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}/outcomes?limit=500`);
      if (r.ok) {
        const data = await r.json();
        setOutcomes(Array.isArray(data) ? data : (data.outcomes || []));
      }
    } catch (_) {}
  }

  async function loadMissed(runId) {
    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}/missed?limit=100`);
      if (r.ok) {
        const data = await r.json();
        setMissed(Array.isArray(data) ? data : (data.missed_movers || []));
      }
    } catch (_) {}
  }

  // Initial load
  useEffect(() => {
    loadHistory();
    // Check if a replay is already running
    fetch(`${API_URL}/api/replay/status`)
      .then(r => r.ok ? r.json() : null)
      .then(p => {
        if (p) {
          setProgress(p);
          if (p.running) startPolling();
        }
      })
      .catch(() => {});
  }, []);

  async function loadBundle(runId) {
    setBundleLoading(true);
    try {
      const r = await fetch(`${API_URL}/api/replay/${runId}/research-bundle`);
      if (r.ok) setBundle(await r.json());
    } catch (_) {}
    setBundleLoading(false);
  }

  // Load outcomes/missed/bundle lazily on tab change
  useEffect(() => {
    if (!activeRun) return;
    if (tab === 'outcomes' && outcomes.length === 0) loadOutcomes(activeRun.id);
    if (tab === 'missed'   && missed.length   === 0) loadMissed(activeRun.id);
    if (tab === 'bundle'   && !bundle)               loadBundle(activeRun.id);
  }, [tab, activeRun]);

  // ── Actions ──────────────────────────────────────────────────────────────────

  async function handleRun() {
    setError('');
    const body = mode === 'single_day'
      ? { mode: 'single_day', as_of_date: singleDate, universe_mode: universeMode }
      : { mode: 'date_range',  start_date: startDate, end_date: endDate, universe_mode: universeMode };

    if (mode === 'single_day' && !singleDate) { setError('Select a date.'); return; }
    if (mode === 'date_range' && (!startDate || !endDate)) { setError('Select start and end dates.'); return; }

    setLaunching(true);
    try {
      const r = await fetch(`${API_URL}/api/replay/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) {
        setError(data.detail || 'Failed to start replay.');
        return;
      }
      // Immediately start polling
      const pollStatus = await fetch(`${API_URL}/api/replay/status`);
      if (pollStatus.ok) setProgress(await pollStatus.json());
      startPolling();
      // Refresh history
      setTimeout(loadHistory, 500);
    } catch (e) {
      setError(String(e));
    } finally {
      setLaunching(false);
    }
  }

  function handleSelectRun(run) {
    setActiveRun(run);
    setCandidates([]);
    setOutcomes([]);
    setMissed([]);
    setSummary(null);
    setBundle(null);
    setTab('candidates');
    loadRunDetail(run.id);
  }

  // ── Derived ───────────────────────────────────────────────────────────────────

  const isRunning   = progress?.running === true;
  const runBtnLabel = launching ? 'Launching…' : isRunning ? 'Running…' : 'Run Replay';

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <>
      <Head>
        <title>Replay · Pump Scout</title>
      </Head>
      <AppNav />

      <div className={styles.page}>
        <div className={styles.header}>
          <div className={styles.advisory}>⏪ HISTORICAL REPLAY — RESEARCH ONLY</div>
          <h1 className={styles.title}>Backdated Scan Replay</h1>
          <p className={styles.subtitle}>
            Run the scanner pipeline on past dates with strict temporal isolation.
            No future data is used during the scan.
          </p>
        </div>

        <div className={styles.layout}>
          {/* ── Left: Run panel ─────────────────────────────────────────────── */}
          <div className={styles.runPanel}>
            <div className={styles.runPanelTitle}>CONFIGURE REPLAY</div>

            {/* Mode toggle */}
            <div className={styles.modeToggle}>
              <button
                className={`${styles.modeBtn} ${mode === 'single_day' ? styles.modeBtnActive : ''}`}
                onClick={() => setMode('single_day')}
              >
                Single Day
              </button>
              <button
                className={`${styles.modeBtn} ${mode === 'date_range' ? styles.modeBtnActive : ''}`}
                onClick={() => setMode('date_range')}
              >
                Date Range
              </button>
            </div>

            {/* Date input(s) */}
            {mode === 'single_day' ? (
              <div className={styles.formGroup}>
                <label className={styles.formLabel}>Scan Date</label>
                <input
                  type="date"
                  className={styles.formInput}
                  value={singleDate}
                  onChange={e => setSingleDate(e.target.value)}
                  max={new Date(Date.now() - 86400000).toISOString().slice(0, 10)}
                />
                <div className={styles.formHint}>The scanner will only see data up to this date.</div>
              </div>
            ) : (
              <>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>Start Date</label>
                  <input
                    type="date"
                    className={styles.formInput}
                    value={startDate}
                    onChange={e => setStartDate(e.target.value)}
                    max={endDate || new Date(Date.now() - 86400000).toISOString().slice(0, 10)}
                  />
                </div>
                <div className={styles.formGroup}>
                  <label className={styles.formLabel}>End Date</label>
                  <input
                    type="date"
                    className={styles.formInput}
                    value={endDate}
                    onChange={e => setEndDate(e.target.value)}
                    min={startDate}
                    max={new Date(Date.now() - 86400000).toISOString().slice(0, 10)}
                  />
                  <div className={styles.formHint}>Weekends are skipped automatically.</div>
                </div>
              </>
            )}

            {/* Universe mode */}
            <div className={styles.formGroup}>
              <label className={styles.formLabel}>Universe Mode</label>
              <select
                className={styles.formSelect}
                value={universeMode}
                onChange={e => setUniverseMode(e.target.value)}
              >
                <option value="approx">Approx (recommended)</option>
                <option value="strict">Strict (fallback to approx)</option>
              </select>
              <div className={styles.formHint}>
                Approx uses grouped-daily snapshot for the date.
                Strict mode requires a historical ticker reference (not yet available — falls back to approx).
              </div>
            </div>

            {error && (
              <div style={{ color: 'var(--red)', fontSize: 11, marginBottom: 10 }}>{error}</div>
            )}

            <button
              className={styles.runBtn}
              onClick={handleRun}
              disabled={launching || isRunning}
            >
              {runBtnLabel}
            </button>

            {/* Progress */}
            {progress && (
              <div className={styles.progressWrap}>
                <div className={styles.progressRow}>
                  <span className={styles.progressLabel}>Status</span>
                  <StatusBadge status={progress.running ? 'running' : (progress.error ? 'failed' : 'completed')} />
                </div>
                {progress.mode === 'date_range' && (
                  <div className={styles.progressRow}>
                    <span className={styles.progressLabel}>Days</span>
                    <span className={styles.progressValue}>
                      {progress.days_completed} / {progress.days_total}
                    </span>
                  </div>
                )}
                {progress.current_date && (
                  <div className={styles.progressRow}>
                    <span className={styles.progressLabel}>Date</span>
                    <span className={styles.progressValue}>{progress.current_date}</span>
                  </div>
                )}
                <div className={styles.progressRow}>
                  <span className={styles.progressLabel}>Candidates</span>
                  <span className={styles.progressValue}>{progress.candidates_found ?? 0}</span>
                </div>
                <div className={styles.progressRow}>
                  <span className={styles.progressLabel}>Outcomes</span>
                  <span className={styles.progressValue}>{progress.outcomes_computed ?? 0}</span>
                </div>
                {progress.mode === 'date_range' && progress.days_total > 0 && (
                  <>
                    <div className={styles.progressTrack}>
                      <div
                        className={styles.progressFill}
                        style={{ width: `${Math.round((progress.days_completed / progress.days_total) * 100)}%` }}
                      />
                    </div>
                  </>
                )}
                {progress.error && (
                  <div style={{ color: 'var(--red)', fontSize: 10, marginTop: 6 }}>
                    {progress.error}
                  </div>
                )}
                {progress.elapsed_secs > 0 && (
                  <div className={styles.progressRow}>
                    <span className={styles.progressLabel}>Elapsed</span>
                    <span className={styles.progressValue}>{progress.elapsed_secs}s</span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Right: Main panel ───────────────────────────────────────────── */}
          <div className={styles.mainPanel}>

            {/* Run history */}
            <div>
              <div className={styles.sectionTitle}>Run History</div>
              {history.length === 0 ? (
                <div className={styles.emptyMsg}>
                  No replay runs yet.
                  <div className={styles.emptyHint}>Configure a date above and click Run Replay.</div>
                </div>
              ) : (
                <table className={styles.historyTable}>
                  <thead>
                    <tr className={styles.historyHead}>
                      <th>ID</th>
                      <th>Mode</th>
                      <th>Date(s)</th>
                      <th>Candidates</th>
                      <th>Outcomes</th>
                      <th>Status</th>
                      <th>Started</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map(run => (
                      <tr
                        key={run.id}
                        className={`${styles.historyRow} ${activeRun?.id === run.id ? styles.historyRowActive : ''}`}
                        onClick={() => handleSelectRun(run)}
                      >
                        <td><span className={styles.runId}>#{run.id}</span></td>
                        <td><span className={styles.runMode}>{run.mode}</span></td>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>
                          {run.mode === 'single_day'
                            ? run.as_of_date
                            : `${run.start_date} → ${run.end_date}`}
                        </td>
                        <td style={{ fontFamily: 'var(--font-mono)' }}>{run.total_candidates ?? 0}</td>
                        <td style={{ fontFamily: 'var(--font-mono)' }}>{run.outcomes_computed ?? 0}</td>
                        <td><StatusBadge status={run.status} /></td>
                        <td style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                          {run.created_at ? new Date(run.created_at).toLocaleString() : '—'}
                        </td>
                        <td onClick={e => e.stopPropagation()}>
                          <button
                            className={styles.btnDanger}
                            style={{ padding: '3px 10px', fontSize: 10 }}
                            onClick={() => { setDeleteTarget(run); setDeleteError(''); }}
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            {/* Detail panel */}
            {activeRun && (
              <div>
                <div className={styles.sectionTitle}>
                  Run #{activeRun.id} — {activeRun.mode === 'single_day'
                    ? activeRun.as_of_date
                    : `${activeRun.start_date} → ${activeRun.end_date}`}
                </div>

                {/* Tabs */}
                <div className={styles.tabRow}>
                  {['candidates', 'outcomes', 'missed', 'summary', 'bundle'].map(t => (
                    <button
                      key={t}
                      className={`${styles.tab} ${tab === t ? styles.tabActive : ''}`}
                      onClick={() => setTab(t)}
                    >
                      {t === 'candidates' && `Candidates (${candidates.length})`}
                      {t === 'outcomes'   && `Outcomes (${outcomes.length})`}
                      {t === 'missed'     && `Missed Movers (${missed.length})`}
                      {t === 'summary'    && 'Summary'}
                      {t === 'bundle'     && 'Research Bundle'}
                    </button>
                  ))}
                </div>

                {loadingDetail && (
                  <div className={styles.statusMsg}>Loading…</div>
                )}

                {/* ── Candidates tab ─────────────────────────────────────── */}
                {tab === 'candidates' && !loadingDetail && (
                  candidates.length === 0 ? (
                    <div className={styles.emptyMsg}>No candidates for this run.</div>
                  ) : (
                    <table className={styles.candidateTable}>
                      <thead>
                        <tr>
                          <th>Symbol</th>
                          <th>Date</th>
                          <th>Price</th>
                          <th>Tier</th>
                          <th>Score</th>
                          <th>NP Score</th>
                          <th>NP Label</th>
                          <th>NP Sequence</th>
                          <th>Wyckoff</th>
                          <th>Sector</th>
                        </tr>
                      </thead>
                      <tbody>
                        {candidates.map(c => (
                          <tr key={c.id}>
                            <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>
                              {c.symbol}
                            </td>
                            <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                              {c.scan_date}
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)' }}>
                              {c.price != null ? `$${fmt(c.price, 2)}` : '—'}
                            </td>
                            <td><TierBadge tier={c.tier} /></td>
                            <td style={{ fontFamily: 'var(--font-mono)' }}>{c.total_score ?? '—'}</td>
                            <td style={{ fontFamily: 'var(--font-mono)', color: npScoreColor(c.new_pump_score) }}>
                              {c.new_pump_score != null ? Number(c.new_pump_score).toFixed(1) : '—'}
                            </td>
                            <td style={{ fontSize: 9 }}>
                              <NpLabelBadge label={c.new_pump_label} />
                            </td>
                            <td style={{ fontSize: 9, color: 'var(--text-muted)', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {c.new_pump_sequence_label || '—'}
                            </td>
                            <td style={{ fontSize: 9, color: 'var(--text-muted)' }}>
                              {c.wyckoff_state || '—'}
                            </td>
                            <td style={{ fontSize: 9, color: 'var(--text-dim)' }}>
                              {c.sector || '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )
                )}

                {/* ── Outcomes tab ───────────────────────────────────────── */}
                {tab === 'outcomes' && (
                  outcomes.length === 0 ? (
                    <div className={styles.emptyMsg}>
                      {loadingDetail ? 'Loading…' : 'No outcomes data yet.'}
                    </div>
                  ) : (
                    <table className={styles.candidateTable}>
                      <thead>
                        <tr>
                          <th>Symbol</th>
                          <th>Date</th>
                          <th>Horizon</th>
                          <th>Entry</th>
                          <th>Exit</th>
                          <th>Return</th>
                          <th>Max Gain</th>
                          <th>Max DD</th>
                          <th>α vs SPY</th>
                          <th>Outcome</th>
                        </tr>
                      </thead>
                      <tbody>
                        {outcomes.map((o, i) => (
                          <tr key={i}>
                            <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>
                              {o.symbol}
                            </td>
                            <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>
                              {o.scan_date}
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-dim)' }}>
                              {o.horizon}
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)' }}>
                              {o.entry_price != null ? `$${fmt(o.entry_price, 2)}` : '—'}
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)' }}>
                              {o.exit_price != null ? `$${fmt(o.exit_price, 2)}` : '—'}
                            </td>
                            <td>{pctCell(o.return_pct)}</td>
                            <td>{pctCell(o.max_gain_pct)}</td>
                            <td>{pctCell(o.max_drawdown_pct)}</td>
                            <td>{pctCell(o.alpha_vs_spy)}</td>
                            <td>
                              {o.outcome_label
                                ? <OutcomeLabel label={o.outcome_label} />
                                : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )
                )}

                {/* ── Missed Movers tab ──────────────────────────────────── */}
                {tab === 'missed' && (
                  missed.length === 0 ? (
                    <div className={styles.emptyMsg}>
                      {loadingDetail ? 'Loading…' : 'No missed movers data yet.'}
                    </div>
                  ) : (
                    <table className={styles.missedTable}>
                      <thead>
                        <tr>
                          <th>Symbol</th>
                          <th>Date</th>
                          <th>Price</th>
                          <th>3d Return</th>
                          <th>5d Return</th>
                          <th>10d Return</th>
                          <th>Why Missed</th>
                        </tr>
                      </thead>
                      <tbody>
                        {missed.map((m, i) => (
                          <tr key={i}>
                            <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>
                              {m.symbol}
                            </td>
                            <td style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 9 }}>
                              {m.scan_date}
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)' }}>
                              {m.price_on_date != null ? `$${fmt(m.price_on_date, 2)}` : '—'}
                            </td>
                            <td>{pctCell(m.future_return_3d)}</td>
                            <td>{pctCell(m.future_return_5d)}</td>
                            <td>{pctCell(m.future_return_10d)}</td>
                            <td><span className={styles.whyMissed}>{m.why_missed || '—'}</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )
                )}

                {/* ── Summary tab ────────────────────────────────────────── */}
                {tab === 'summary' && (
                  !summary ? (
                    <div className={styles.emptyMsg}>No summary available yet.</div>
                  ) : (
                    <>
                      {/* KPI grid — keys match API: total_candidates, total_outcomes, missed_movers, avg_returns */}
                      <div className={styles.summaryGrid}>
                        <div className={styles.summaryKPI}>
                          <div className={styles.kpiValue}>{summary.total_candidates ?? 0}</div>
                          <div className={styles.kpiLabel}>Candidates</div>
                        </div>
                        <div className={styles.summaryKPI}>
                          <div className={styles.kpiValue}>{summary.total_outcomes ?? 0}</div>
                          <div className={styles.kpiLabel}>Outcomes</div>
                        </div>
                        <div className={styles.summaryKPI}>
                          <div className={styles.kpiValue}>{summary.missed_movers ?? 0}</div>
                          <div className={styles.kpiLabel}>Missed Movers</div>
                        </div>
                        {summary.avg_returns?.['5d'] != null && (
                          <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
                            <div className={`${styles.kpiValue} ${summary.avg_returns['5d'] >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                              {summary.avg_returns['5d'] >= 0 ? '+' : ''}{fmt(summary.avg_returns['5d'])}%
                            </div>
                            <div className={styles.kpiLabel}>Avg 5d Return</div>
                          </div>
                        )}
                        {summary.avg_returns?.['1d'] != null && (
                          <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
                            <div className={`${styles.kpiValue} ${summary.avg_returns['1d'] >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                              {summary.avg_returns['1d'] >= 0 ? '+' : ''}{fmt(summary.avg_returns['1d'])}%
                            </div>
                            <div className={styles.kpiLabel}>Avg 1d Return</div>
                          </div>
                        )}
                        {summary.avg_returns?.['10d'] != null && (
                          <div className={`${styles.summaryKPI} ${styles.returnKPI}`}>
                            <div className={`${styles.kpiValue} ${summary.avg_returns['10d'] >= 0 ? styles.returnPositive : styles.returnNegative}`}>
                              {summary.avg_returns['10d'] >= 0 ? '+' : ''}{fmt(summary.avg_returns['10d'])}%
                            </div>
                            <div className={styles.kpiLabel}>Avg 10d Return</div>
                          </div>
                        )}
                      </div>

                      {/* Outcome distribution — API key: outcome_labels */}
                      {summary.outcome_labels && Object.keys(summary.outcome_labels).length > 0 && (
                        <div className={styles.outcomeSection}>
                          <div className={styles.sectionTitle} style={{ marginBottom: 10 }}>
                            Outcome Distribution
                          </div>
                          <div className={styles.outcomeGrid}>
                            <div className={styles.outcomeBlock}>
                              <div className={styles.outcomeBlockTitle}>Label Counts</div>
                              {Object.entries(summary.outcome_labels).map(([label, count]) => (
                                <div key={label} className={styles.outcomeRow}>
                                  <span className={styles.outcomeLabel}>
                                    <OutcomeLabel label={label} />
                                  </span>
                                  <span className={styles.outcomeCount}>{count}</span>
                                </div>
                              ))}
                            </div>

                            {summary.best_5?.length > 0 && (
                              <div className={styles.outcomeBlock}>
                                <div className={styles.outcomeBlockTitle}>Best Performers (5d)</div>
                                {summary.best_5.map((r, i) => (
                                  <div key={i} className={styles.outcomeRow}>
                                    <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 10 }}>
                                      {r.symbol}
                                    </span>
                                    <span>{pctCell(r.return_5d)}</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        </div>
                      )}

                      {/* Tier distribution */}
                      {summary.tier_distribution && Object.keys(summary.tier_distribution).length > 0 && (
                        <div className={styles.outcomeSection} style={{ marginTop: 12 }}>
                          <div className={styles.sectionTitle} style={{ marginBottom: 10 }}>
                            Tier Breakdown
                          </div>
                          <div className={styles.outcomeGrid}>
                            <div className={styles.outcomeBlock}>
                              <div className={styles.outcomeBlockTitle}>Candidate Tiers</div>
                              {Object.entries(summary.tier_distribution).map(([tier, count]) => (
                                <div key={tier} className={styles.outcomeRow}>
                                  <span className={styles.outcomeLabel}>
                                    <TierBadge tier={tier} />
                                  </span>
                                  <span className={styles.outcomeCount}>{count}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      )}
                    </>
                  )
                )}

                {/* ── Research Bundle tab ───────────────────────────────── */}
                {tab === 'bundle' && <BundleTab
                  bundle={bundle}
                  loading={bundleLoading}
                  runId={activeRun.id}
                  onReload={() => { setBundle(null); loadBundle(activeRun.id); }}
                  apiUrl={API_URL}
                />}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Delete confirmation modal ──────────────────────────────────────── */}
      {deleteTarget && (
        <div className={styles.modalOverlay} onClick={() => !deleting && setDeleteTarget(null)}>
          <div className={styles.modalBox} onClick={e => e.stopPropagation()}>
            <div className={styles.modalTitle}>Permanently Delete Run #{deleteTarget.id}?</div>
            <div className={styles.modalBody}>
              This will remove the run and <strong>all linked DB rows</strong>:
              candidates, outcomes, missed movers, and any AI summaries.
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
    </>
  );
}
