import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import styles from '../styles/NewPump.module.css';
import AppNav from '../components/AppNav';
import NpDrawer from '../components/NpDrawer';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REFRESH_INTERVAL = 60 * 1000;

// ── Config ────────────────────────────────────────────────────────────────────

const LABEL_CFG = {
  NEW_PUMP_FIRE:         { cls: styles.badgeFIRE,   short: 'FIRE'    },
  NEW_PUMP_STRONG:       { cls: styles.badgeSTRONG, short: 'STRONG'  },
  NEW_PUMP_SETUP:        { cls: styles.badgeSETUP,  short: 'SETUP'   },
  NEW_PUMP_TRIGGER_ONLY: { cls: styles.badgeTRIG,   short: 'TRIGGER' },
  NEW_PUMP_WEAK:         { cls: styles.badgeWEAK,   short: 'WEAK'    },
  NEW_PUMP_NONE:         { cls: styles.badgeNONE,   short: 'NONE'    },
};

const ALL_LABELS = [
  'NEW_PUMP_FIRE', 'NEW_PUMP_STRONG', 'NEW_PUMP_SETUP',
  'NEW_PUMP_TRIGGER_ONLY', 'NEW_PUMP_WEAK', 'NEW_PUMP_NONE',
];

const ALL_SEQUENCES = [
  'FULL_FRI34_G4_B2', 'FULL_L34_G4_B2',
  'CONFIRM_AFTER_G4',
  'TRIGGER_AFTER_FRI34', 'TRIGGER_AFTER_L34',
  'SETUP_ONLY_FRI34', 'SETUP_ONLY_L34',
  'ISOLATED_G4', 'ISOLATED_B2', 'NONE',
];

const SCORE_COLOR = (s) => {
  if (s >= 70) return '#ff4400';
  if (s >= 55) return '#ff8800';
  if (s >= 40) return '#ffd600';
  if (s >= 25) return '#00e5ff';
  if (s >= 10) return '#888';
  return '#444';
};

// ── NP State badge — derived purely from sequence label ───────────────────────
const NP_STATE = {
  FULL_FRI34_G4_B2:    { label: 'CONFIRMING', color: '#ff4400', bg: 'rgba(255,68,0,0.12)'   },
  FULL_L34_G4_B2:      { label: 'CONFIRMING', color: '#ff4400', bg: 'rgba(255,68,0,0.12)'   },
  CONFIRM_AFTER_G4:    { label: 'CONFIRMING', color: '#ff8800', bg: 'rgba(255,136,0,0.12)'  },
  TRIGGER_AFTER_FRI34: { label: 'ARMED',      color: '#ffd600', bg: 'rgba(255,214,0,0.10)'  },
  TRIGGER_AFTER_L34:   { label: 'ARMED',      color: '#ffd600', bg: 'rgba(255,214,0,0.10)'  },
  ISOLATED_G4:         { label: 'TRIGGERED',  color: '#00e5ff', bg: 'rgba(0,229,255,0.09)'  },
  SETUP_ONLY_FRI34:    { label: 'SETUP',      color: '#44ff88', bg: 'rgba(68,255,136,0.09)' },
  SETUP_ONLY_L34:      { label: 'SETUP',      color: '#44ff88', bg: 'rgba(68,255,136,0.09)' },
  ISOLATED_B2:         { label: 'ISOLATED',   color: '#888',    bg: 'rgba(128,128,128,0.08)'},
};

function npState(seq) {
  return NP_STATE[seq] || { label: '—', color: '#444', bg: 'transparent' };
}

// ── Market regime colors ──────────────────────────────────────────────────────
const REGIME_CFG = {
  RISK_ON:  { color: '#00e676', bg: 'rgba(0,230,118,0.10)', label: 'RISK ON'  },
  RISK_OFF: { color: '#ff5252', bg: 'rgba(255,82,82,0.10)', label: 'RISK OFF' },
  FEAR:     { color: '#ff6d00', bg: 'rgba(255,109,0,0.10)', label: 'FEAR'     },
  ROTATION: { color: '#ffd740', bg: 'rgba(255,215,64,0.10)',label: 'ROTATION' },
  NEUTRAL:  { color: '#888',    bg: 'rgba(128,128,128,0.08)', label: 'NEUTRAL'},
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n, d = 1) { return n == null ? '—' : Number(n).toFixed(d); }
function fmtVol(n) {
  if (n == null) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(0)}K`;
  return String(n);
}
function fmtAge(a) { return a == null ? '—' : String(a); }

function LabelBadge({ label }) {
  const cfg = LABEL_CFG[label] || LABEL_CFG.NEW_PUMP_NONE;
  return <span className={`${styles.badge} ${cfg.cls}`}>{cfg.short}</span>;
}

function Pill({ on, label }) {
  return (
    <span className={`${styles.pill} ${on ? styles.pillOn : styles.pillOff}`}>
      {label}
    </span>
  );
}

function NpStateBadge({ seq }) {
  const s = npState(seq);
  if (s.label === '—') return <span style={{ color: '#444', fontSize: 9 }}>—</span>;
  return (
    <span style={{
      display: 'inline-block', padding: '2px 6px', borderRadius: 3,
      fontSize: 8, fontWeight: 800, letterSpacing: '0.06em',
      color: s.color, background: s.bg, border: `1px solid ${s.color}44`,
    }}>
      {s.label}
    </span>
  );
}

// ── Count how many rows per label ─────────────────────────────────────────────

function labelCounts(results) {
  const c = {};
  for (const r of results) {
    const lbl = r.new_pump_label || 'NEW_PUMP_NONE';
    c[lbl] = (c[lbl] || 0) + 1;
  }
  return c;
}

// ── Live price cell ───────────────────────────────────────────────────────────

function LivePriceCell({ sym, eodPrice, livePrices }) {
  const lp = livePrices[sym];
  if (!lp) {
    return <span style={{ color: '#555' }}>{eodPrice != null ? `$${fmt(eodPrice, 2)}` : '—'}</span>;
  }
  const chg = lp.change_pct;
  const dollar = lp.prev_close != null ? lp.price - lp.prev_close : null;
  const color = chg == null ? '#888' : chg > 0 ? '#00ff88' : chg < 0 ? '#ff4444' : '#888';
  return (
    <>
      <span style={{ color: '#e0e0e0', fontVariantNumeric: 'tabular-nums' }}>
        ${fmt(lp.price, 2)}
      </span>
      {chg != null && (
        <span style={{ color, fontSize: 10, marginLeft: 4 }}>
          {chg > 0 ? '+' : ''}{fmt(chg, 2)}%
        </span>
      )}
      {dollar != null && (
        <span style={{ color, fontSize: 9, marginLeft: 3, opacity: 0.75 }}>
          {dollar >= 0 ? '+' : ''}${Math.abs(dollar).toFixed(2)}
        </span>
      )}
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function NewPumpPage() {
  const [data,         setData]         = useState(null);
  const [loading,      setLoading]      = useState(true);
  const [error,        setError]        = useState(null);
  const [minScore,     setMinScore]     = useState(0);
  const [labelF,       setLabelF]       = useState('');
  const [seqF,         setSeqF]         = useState('');
  const [scanning,     setScanning]     = useState(false);
  const [scanStatus,   setScanStatus]   = useState(null);
  const [regime,       setRegime]       = useState(null);
  const [drawerSym,    setDrawerSym]    = useState(null);
  const [drawerData,   setDrawerData]   = useState({});
  const [drawerLoading,setDrawerLoading]= useState(false);
  const [drawerError,  setDrawerError]  = useState(null);
  const [livePrices,   setLivePrices]   = useState({});
  const [liveUpdated,  setLiveUpdated]  = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (minScore > 0) params.set('min_score', minScore);
      if (labelF)       params.set('label', labelF);
      if (seqF)         params.set('sequence', seqF);
      const res = await fetch(`${API_URL}/api/new-pump/latest?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
      setScanStatus({
        universe: json.universe,
        elapsed:  json.elapsed_secs,
        scanned_at: json.scanned_at,
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [minScore, labelF, seqF]);

  const triggerScan = useCallback(async () => {
    if (scanning) return;
    setScanning(true);
    try {
      await fetch(`${API_URL}/api/new-pump/run`, { method: 'POST' });
      for (let i = 0; i < 120; i++) {
        await new Promise(r => setTimeout(r, 3000));
        const st = await fetch(`${API_URL}/api/new-pump/status`).then(r => r.json());
        if (!st.running && st.has_data) break;
      }
      await fetchData();
    } catch (e) {
      setError(e.message);
    } finally {
      setScanning(false);
    }
  }, [scanning, fetchData]);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, REFRESH_INTERVAL);
    return () => clearInterval(iv);
  }, [fetchData]);

  // Fetch market regime once on mount
  useEffect(() => {
    fetch(`${API_URL}/api/market-regime`)
      .then(r => r.json())
      .then(setRegime)
      .catch(() => {});
  }, []);

  // Live price polling — starts immediately when scan data loads, refreshes every 30s
  useEffect(() => {
    const syms = (data?.results || []).map(r => r.symbol);
    if (!syms.length) return;
    setLivePrices({});  // clear stale prices on new scan data
    const poll = async () => {
      try {
        const res = await fetch(`${API_URL}/api/prices/live?symbols=${syms.join(',')}`);
        if (!res.ok) return;
        const json = await res.json();
        setLivePrices(json);
        setLiveUpdated(new Date());
      } catch {}
    };
    poll();
    const iv = setInterval(poll, 30_000);
    return () => clearInterval(iv);
  }, [data]);

  const openDrawer = useCallback(async (sym) => {
    setDrawerSym(sym);
    setDrawerError(null);
    if (drawerData[sym]) return;
    setDrawerLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/new-pump/ticker/${sym}`);
      const json = await res.json();
      setDrawerData(prev => ({ ...prev, [sym]: json }));
    } catch (e) {
      setDrawerError(e.message);
    } finally {
      setDrawerLoading(false);
    }
  }, [drawerData]);

  // ESC to close drawer
  useEffect(() => {
    if (!drawerSym) return;
    const handler = (e) => { if (e.key === 'Escape') setDrawerSym(null); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [drawerSym]);

  const results = data?.results || [];
  const counts  = labelCounts(results);
  const regCfg  = REGIME_CFG[regime?.regime] || REGIME_CFG.NEUTRAL;

  return (
    <>
      <Head><title>New Pump — Pump Scout</title></Head>
      <AppNav />

      <div className={styles.page}>
        {/* Header */}
        <div className={styles.header}>
          <h1 className={styles.title}>New Pump</h1>
          <p className={styles.subtitle}>
            STRUCTURED SETUP → TRIGGER → CONFIRMATION ENGINE · L34 / FRI34 / G4 / B2
          </p>
          {data?.scanned_at && (
            <div className={styles.scanTime}>
              Last scan: {new Date(data.scanned_at).toLocaleString()}
            </div>
          )}
        </div>

        {/* Market regime banner — context only, not scoring */}
        {regime && (
          <div className={styles.regimeBanner} style={{ borderColor: regCfg.color + '44', background: regCfg.bg }}>
            <span className={styles.regimeLabel} style={{ color: regCfg.color }}>
              {regCfg.label}
            </span>
            {regime.strong_sectors?.length > 0 && (
              <span className={styles.regimeSectors}>
                <span className={styles.regimeSectorsHdr}>Strong:</span>
                {regime.strong_sectors.slice(0, 4).join(' · ')}
              </span>
            )}
            {regime.weak_sectors?.length > 0 && (
              <span className={styles.regimeSectors} style={{ color: '#ff5252' }}>
                <span className={styles.regimeSectorsHdr} style={{ color: '#ff5252' }}>Weak:</span>
                {regime.weak_sectors.slice(0, 4).join(' · ')}
              </span>
            )}
            {regime.recommendation && (
              <span className={styles.regimeRec}>{regime.recommendation}</span>
            )}
          </div>
        )}

        {/* Summary bar */}
        {results.length > 0 && (
          <div className={styles.summaryBar}>
            {ALL_LABELS.map(lbl => (
              <div key={lbl} className={styles.summaryItem}>
                <span className={styles.summaryNum}>{counts[lbl] || 0}</span>
                <span className={styles.summaryLbl}>{LABEL_CFG[lbl]?.short || lbl}</span>
              </div>
            ))}
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum}>{results.length}</span>
              <span className={styles.summaryLbl}>Total</span>
            </div>
          </div>
        )}

        {/* Scan meta */}
        {scanStatus && (
          <div className={styles.scanMeta}>
            <span>Universe: <strong>{scanStatus.universe?.toLocaleString()}</strong> tickers</span>
            {scanStatus.elapsed != null && (
              <span>Elapsed: <strong>{scanStatus.elapsed}s</strong></span>
            )}
            {liveUpdated && (
              <span className={styles.liveUpdated}>
                Live prices: <strong>{liveUpdated.toLocaleTimeString()}</strong>
              </span>
            )}
          </div>
        )}

        {/* Controls */}
        <div className={styles.controls}>
          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Min Score</span>
            <select
              className={styles.select}
              value={minScore}
              onChange={e => setMinScore(Number(e.target.value))}
            >
              {[0, 10, 25, 40, 55, 70].map(v => (
                <option key={v} value={v}>{v === 0 ? 'All' : `${v}+`}</option>
              ))}
            </select>
          </div>

          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Label</span>
            <select
              className={styles.select}
              value={labelF}
              onChange={e => setLabelF(e.target.value)}
            >
              <option value="">All</option>
              {ALL_LABELS.map(l => (
                <option key={l} value={l}>{LABEL_CFG[l]?.short || l}</option>
              ))}
            </select>
          </div>

          <div className={styles.filterGroup}>
            <span className={styles.filterLabel}>Sequence</span>
            <select
              className={styles.select}
              value={seqF}
              onChange={e => setSeqF(e.target.value)}
            >
              <option value="">All</option>
              {ALL_SEQUENCES.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>

          <button
            className={styles.refreshBtn}
            onClick={fetchData}
            disabled={loading}
          >
            {loading ? '…' : '⟳ Refresh'}
          </button>

          <button
            className={styles.scanBtn}
            onClick={triggerScan}
            disabled={scanning || loading}
          >
            {scanning ? '⏳ Scanning…' : '▶ Run Scan'}
          </button>
        </div>

        {/* Body */}
        {error ? (
          <div className={styles.error}>Error: {error}</div>
        ) : loading && !data ? (
          <div className={styles.loading}>Loading New Pump data…</div>
        ) : !data ? (
          <div className={styles.empty}>
            No scan data yet. Click <strong>▶ Run Scan</strong> to start.
          </div>
        ) : results.length === 0 ? (
          <div className={styles.empty}>
            No tickers match the current filters.
          </div>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>State</th>
                  <th>Score</th>
                  <th>Label</th>
                  <th>Sequence</th>
                  <th>L34</th>
                  <th>FRI34</th>
                  <th>G4</th>
                  <th>B2</th>
                  <th>Age L34</th>
                  <th>Age FRI34</th>
                  <th>Age G4</th>
                  <th>Age B2</th>
                  <th>Setup</th>
                  <th>Trigger</th>
                  <th>Confirm</th>
                  <th>Mod</th>
                  <th>Signal Date</th>
                  <th>Price / Live</th>
                  <th>Volume</th>
                  <th>Sector</th>
                </tr>
              </thead>
              <tbody>
                {results.map(r => {
                  const isNone = r.new_pump_label === 'NEW_PUMP_NONE';
                  return (
                    <tr
                      key={r.symbol}
                      className={isNone ? styles.rowDim : ''}
                      onClick={() => openDrawer(r.symbol)}
                      style={{ cursor: 'pointer' }}
                    >
                      <td className={styles.symbolCell} onClick={e => e.stopPropagation()}>
                        <Link href={`/ticker/${r.symbol}`} className={styles.symLink}>
                          {r.symbol}
                        </Link>
                      </td>
                      <td><NpStateBadge seq={r.new_pump_sequence_label} /></td>
                      <td className={styles.scoreCell}
                          style={{ color: SCORE_COLOR(r.new_pump_score) }}>
                        {fmt(r.new_pump_score)}
                      </td>
                      <td><LabelBadge label={r.new_pump_label} /></td>
                      <td className={styles.seqCell}>{r.new_pump_sequence_label || '—'}</td>
                      <td><Pill on={r.has_l34}   label="L34"   /></td>
                      <td><Pill on={r.has_fri34} label="FRI34" /></td>
                      <td><Pill on={r.has_g4}    label="G4"    /></td>
                      <td><Pill on={r.has_b2}    label="B2"    /></td>
                      <td className={styles.ageCell}>{fmtAge(r.age_l34)}</td>
                      <td className={styles.ageCell}>{fmtAge(r.age_fri34)}</td>
                      <td className={styles.ageCell}>{fmtAge(r.age_g4)}</td>
                      <td className={styles.ageCell}>{fmtAge(r.age_b2)}</td>
                      <td className={styles.ageCell}>{fmt(r.new_pump_setup_score,   0)}</td>
                      <td className={styles.ageCell}>{fmt(r.new_pump_trigger_score, 0)}</td>
                      <td className={styles.ageCell}>{fmt(r.new_pump_confirm_score, 0)}</td>
                      <td className={styles.ageCell}>{fmt(r.new_pump_modifier_score,0)}</td>
                      <td className={styles.sigDateCell}>{r.signal_date || '—'}</td>
                      <td><LivePriceCell sym={r.symbol} eodPrice={r.price} livePrices={livePrices} /></td>
                      <td>{fmtVol(r.volume_today)}</td>
                      <td className={styles.sectorCell}>{r.sector || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <NpDrawer
        sym={drawerSym}
        dataCache={drawerData}
        loading={drawerLoading}
        error={drawerError}
        onClose={() => setDrawerSym(null)}
      />
    </>
  );
}
