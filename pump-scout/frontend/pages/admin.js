import { useState, useEffect, useRef } from 'react';
import Head from 'next/head';
import AppNav from '../components/AppNav';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';


export default function AdminPage() {
  const [symbol, setSymbol] = useState('AAPL');
  const [massiveResult, setMassiveResult] = useState(null);
  const [enrichResult, setEnrichResult] = useState(null);
  const [regimeResult, setRegimeResult] = useState(null);
  const [loading, setLoading] = useState({});
  const [error, setError] = useState({});
  const [replayRunId, setReplayRunId] = useState('');
  const [recalcResult, setRecalcResult] = useState(null);
  const [rebuildResult, setRebuildResult] = useState(null);
  const [refreshSectorResult, setRefreshSectorResult] = useState(null);
  const [refreshSectorStatus, setRefreshSectorStatus] = useState(null);
  const sectorRefreshPollRef = useRef(null);

  // ── Clean DB state ──────────────────────────────────────────────────────────
  const [dbResults, setDbResults]             = useState({});
  const [dbConfirm, setDbConfirm]             = useState({});
  const [rawKeepN, setRawKeepN]               = useState('0');
  const [rawDryRun, setRawDryRun]             = useState(true);
  const [rawVacuum, setRawVacuum]             = useState(false);
  const [delReplayId, setDelReplayId]         = useState('');
  const [delPumpId, setDelPumpId]             = useState('');
  const [delRawId, setDelRawId]               = useState('');
  // cleanup-all
  const [allKeepN, setAllKeepN]               = useState('3');
  const [allCandleDays, setAllCandleDays]     = useState('200');
  const [allDryRun, setAllDryRun]             = useState(true);
  // candle cache
  const [candleDays, setCandleDays]           = useState('200');
  const [candleDryRun, setCandleDryRun]       = useState(true);
  // replay bulk
  const [replayKeepN, setReplayKeepN]         = useState('3');
  const [replayBulkDryRun, setReplayBulkDryRun] = useState(true);
  // pump study bulk
  const [pumpKeepN, setPumpKeepN]             = useState('3');
  const [pumpBulkDryRun, setPumpBulkDryRun]   = useState(true);

  // ── Demand Scanner state ────────────────────────────────────────────────────
  const [scanStatus,    setScanStatus]    = useState(null);   // progress dict
  const [scanLaunching, setScanLaunching] = useState(false);
  const [scanError,     setScanError]     = useState('');
  const scanPollRef = useRef(null);

  const SCAN_PHASE_LABEL = {
    idle:               'Idle — not running',
    fetching_universe:  'Fetching universe from Massive…',
    filtering:          'Filtering by price / volume / type…',
    fetching_candles:   'Fetching candles for candidates…',
    analyzing:          'Running Demand Engine on tickers…',
    enriching:          'Enriching: sector / hype / regime…',
    enriching_context:  'Enriching: macro context…',
    demand_composite:   'Computing demand composite scores…',
    done:               'Scan complete',
    error:              'Error',
  };

  const fetchScanStatus = async () => {
    try {
      const res = await fetch(`${API_URL}/api/demand-scanner/status`);
      const data = await res.json();
      setScanStatus(data);
      if (!data.running && scanPollRef.current) {
        clearInterval(scanPollRef.current);
        scanPollRef.current = null;
      }
    } catch (_) {}
  };

  useEffect(() => {
    fetchScanStatus();
    return () => { if (scanPollRef.current) clearInterval(scanPollRef.current); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const startScanPoll = () => {
    if (scanPollRef.current) return;
    scanPollRef.current = setInterval(fetchScanStatus, 2500);
  };

  const handleRunScan = async () => {
    setScanLaunching(true);
    setScanError('');
    try {
      const res = await fetch(`${API_URL}/api/demand-scanner/run`, { method: 'POST' });
      const data = await res.json();
      if (data.status === 'already_running') {
        setScanError('Scan already in progress — check status below');
      }
      await fetchScanStatus();
      startScanPoll();
    } catch (e) {
      setScanError(e.message);
    } finally {
      setScanLaunching(false);
    }
  };

  const startSectorRefreshPolling = () => {
    if (sectorRefreshPollRef.current) return;
    sectorRefreshPollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_URL}/api/admin/refresh-sector-data/status`);
        const data = await res.json();
        setRefreshSectorStatus(data);
        if (!data.running) {
          clearInterval(sectorRefreshPollRef.current);
          sectorRefreshPollRef.current = null;
        }
      } catch (_) {}
    }, 4000);
  };


  async function call(key, url, method = 'GET') {
    setLoading(l => ({ ...l, [key]: true }));
    setError(e => ({ ...e, [key]: null }));
    try {
      const res = await fetch(url, method !== 'GET' ? { method } : undefined);
      const data = await res.json();
      if (key === 'massive')        setMassiveResult(data);
      if (key === 'enrich')         setEnrichResult(data);
      if (key === 'regime')         setRegimeResult(data);
      if (key === 'refresh_sector') {
        setRefreshSectorResult(data);
        setTimeout(() => {
          fetch(`${API_URL}/api/admin/refresh-sector-data/status`)
            .then(r => r.json()).then(d => { setRefreshSectorStatus(d); if (d.running) startSectorRefreshPolling(); })
            .catch(() => {});
        }, 1000);
      }
    } catch (err) {
      setError(e => ({ ...e, [key]: err.message }));
    } finally {
      setLoading(l => ({ ...l, [key]: false }));
    }
  }

  async function callPost(key, url, setter) {
    setLoading(l => ({ ...l, [key]: true }));
    setError(e => ({ ...e, [key]: null }));
    try {
      const res = await fetch(url, { method: 'POST' });
      const data = await res.json();
      if (setter) setter(data);
    } catch (err) {
      setError(e => ({ ...e, [key]: err.message }));
    } finally {
      setLoading(l => ({ ...l, [key]: false }));
    }
  }

  // ── Clean DB helpers ────────────────────────────────────────────────────────
  async function dbCall(key, url, method = 'GET', body = null) {
    setLoading(l => ({ ...l, [key]: true }));
    setError(e => ({ ...e, [key]: null }));
    setDbResults(r => ({ ...r, [key]: null }));
    try {
      const opts = { method };
      if (body !== null) { opts.headers = { 'Content-Type': 'application/json' }; opts.body = JSON.stringify(body); }
      const res = await fetch(url, opts);
      const data = await res.json();
      setDbResults(r => ({ ...r, [key]: data }));
    } catch (err) {
      setError(e => ({ ...e, [key]: err.message }));
    } finally {
      setLoading(l => ({ ...l, [key]: false }));
      setDbConfirm(c => ({ ...c, [key]: false }));
    }
  }

  function requireConfirm(key) {
    if (!dbConfirm[key]) { setDbConfirm(c => ({ ...c, [key]: true })); return false; }
    return true;
  }

  const card = { marginBottom: 24, background: '#0d0d1e', border: '1px solid #1a1a32', borderRadius: 8, padding: '20px 20px' };
  const label = { margin: '0 0 12px', fontSize: 11, fontWeight: 700, letterSpacing: '0.09em', color: '#56567a', textTransform: 'uppercase' };
  const pre = { margin: '12px 0 0', fontSize: 10, color: '#28d971', background: 'rgba(0,0,0,0.4)', borderRadius: 4, padding: 10, overflowX: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: "'SF Mono', monospace" };

  return (
    <>
      <Head>
        <title>Admin — Pump Scout</title>
        <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }`}</style>
      </Head>
      <div style={{ padding: '0 0 60px', minHeight: '100vh', background: '#07070f', color: '#eaeaf6', fontFamily: "'Inter', system-ui, sans-serif" }}>

        <AppNav />
        <div style={{ padding: '24px 28px 12px', display: 'flex', alignItems: 'center', gap: 12 }}>
          <h1 style={{ margin: 0, fontSize: 16, fontWeight: 800, letterSpacing: '0.08em', color: '#eaeaf6' }}>ADMIN PANEL</h1>
          <span style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', background: 'rgba(124,90,245,0.12)', border: '1px solid rgba(124,90,245,0.35)', borderRadius: 4, padding: '2px 7px', color: '#c084fc' }}>GMT+4</span>
            <span style={{ fontSize: 10, color: '#56567a' }}>{API_URL}</span>
          </span>
        </div>
        <div style={{ padding: '0 28px' }}>

        {/* ── Demand Scanner ── */}
        {(() => {
          const s = scanStatus;
          const isRunning = s?.running;
          const phase = s?.phase || 'idle';
          const isDone = phase === 'done';
          const isError = phase === 'error';

          const pct = (() => {
            if (!s || phase === 'idle') return 0;
            if (isDone) return 100;
            if (phase === 'fetching_universe') return 5;
            if (phase === 'filtering') return 12;
            if (phase === 'fetching_candles') return 25;
            if (phase === 'analyzing') {
              const total = s.universe_size || 1;
              const done  = s.analyzed_count || 0;
              return Math.round(25 + (done / total) * 50);
            }
            if (phase === 'enriching') return 80;
            if (phase === 'enriching_context') return 88;
            if (phase === 'demand_composite') return 94;
            return 0;
          })();

          const fmtSecs = (s) => {
            if (!s) return '—';
            if (s < 60) return `${s}s`;
            return `${Math.floor(s / 60)}m ${s % 60}s`;
          };

          const statBox = (label, value, color = '#eaeaf6') => (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 70, padding: '8px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 6, border: '1px solid #1a1a32' }}>
              <span style={{ fontSize: 18, fontWeight: 800, color, fontFamily: 'var(--font-mono, monospace)', lineHeight: 1 }}>{value ?? '—'}</span>
              <span style={{ fontSize: 9, color: '#56567a', marginTop: 4, textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</span>
            </div>
          );

          const tierChip = (label, count, color) => count > 0 ? (
            <span style={{ fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 4, background: color + '22', border: `1px solid ${color}44`, color }}>
              {label} {count}
            </span>
          ) : null;

          return (
            <div style={{ ...card, marginBottom: 24, border: isRunning ? '1px solid rgba(0,212,245,0.3)' : isError ? '1px solid rgba(248,113,113,0.3)' : '1px solid #1a1a32' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                <p style={{ ...label, margin: 0 }}>⚡ Demand Scanner</p>
                {isRunning && (
                  <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: '0.1em', background: 'rgba(0,212,245,0.12)', border: '1px solid rgba(0,212,245,0.35)', borderRadius: 4, padding: '2px 7px', color: '#00d4f5', animation: 'pulse 1.5s infinite' }}>
                    RUNNING
                  </span>
                )}
                {isDone && (
                  <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: '0.1em', background: 'rgba(40,217,113,0.12)', border: '1px solid rgba(40,217,113,0.35)', borderRadius: 4, padding: '2px 7px', color: '#28d971' }}>
                    COMPLETE
                  </span>
                )}
                {isError && (
                  <span style={{ fontSize: 9, fontWeight: 800, letterSpacing: '0.1em', background: 'rgba(248,113,113,0.12)', border: '1px solid rgba(248,113,113,0.35)', borderRadius: 4, padding: '2px 7px', color: '#f87171' }}>
                    ERROR
                  </span>
                )}
                {s?.scanned_at && (
                  <span style={{ fontSize: 10, color: '#56567a', marginLeft: 'auto' }}>
                    Last scan: {new Date(s.scanned_at).toLocaleString()}
                  </span>
                )}
              </div>

              {/* Phase + progress bar */}
              <div style={{ marginBottom: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
                  <span style={{ fontSize: 11, color: isError ? '#f87171' : isRunning ? '#00d4f5' : isDone ? '#28d971' : '#56567a' }}>
                    {SCAN_PHASE_LABEL[phase] || phase}
                    {isRunning && phase === 'analyzing' && s?.analyzed_count != null && s?.universe_size != null && (
                      <span style={{ color: '#56567a' }}> — {s.analyzed_count} / {s.universe_size}</span>
                    )}
                  </span>
                  <span style={{ fontSize: 10, color: '#56567a', fontFamily: 'monospace' }}>
                    {isRunning || isDone ? `${pct}%` : ''}
                    {s?.elapsed_secs ? `  ${fmtSecs(s.elapsed_secs)}` : ''}
                  </span>
                </div>
                {(isRunning || isDone) && (
                  <div style={{ height: 4, background: '#1a1a32', borderRadius: 2, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${pct}%`, background: isError ? '#f87171' : isDone ? '#28d971' : '#00d4f5', borderRadius: 2, transition: 'width 0.5s ease' }} />
                  </div>
                )}
                {isError && s?.last_error && (
                  <div style={{ fontSize: 10, color: '#f87171', marginTop: 6 }}>{s.last_error}</div>
                )}
              </div>

              {/* Stats row */}
              {s && (s.universe_size > 0 || isDone) && (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
                  {statBox('Universe',  s.universe_size,  '#eaeaf6')}
                  {statBox('Fetched',   s.fetched_count,  '#9898c0')}
                  {statBox('Analyzed',  s.analyzed_count, '#9898c0')}
                  {statBox('Skipped',   s.skipped_count,  '#56567a')}
                  {statBox('Elapsed',   fmtSecs(s.elapsed_secs), '#56567a')}
                  {statBox('Excluded',  s.excluded_non_common_stock_count, '#56567a')}
                </div>
              )}

              {/* NP signal counts */}
              {s && (s.fire_count > 0 || s.strong_count > 0 || s.setup_count > 0) && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: '#56567a', textTransform: 'uppercase', marginBottom: 6 }}>NP Structure</div>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {tierChip('FIRE',   s.fire_count,   '#f43f5e')}
                    {tierChip('STRONG', s.strong_count, '#f59e0b')}
                    {tierChip('SETUP',  s.setup_count,  '#3b82f6')}
                  </div>
                </div>
              )}

              {/* Demand tier counts */}
              {s && (s.demand_prime_count > 0 || s.demand_high_count > 0 || s.demand_watch_count > 0) && (
                <div style={{ marginBottom: 14 }}>
                  <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: '#56567a', textTransform: 'uppercase', marginBottom: 6 }}>Demand Tiers</div>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {tierChip('PRIME',    s.demand_prime_count, '#28d971')}
                    {tierChip('HIGH',     s.demand_high_count,  '#00d4f5')}
                    {tierChip('WATCH',    s.demand_watch_count, '#f59e0b')}
                    {tierChip('ATS_PRIME',s.ats_prime_count,    '#c084fc')}
                  </div>
                </div>
              )}

              {/* Run button */}
              <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                <button
                  onClick={handleRunScan}
                  disabled={scanLaunching || isRunning}
                  style={{ background: 'rgba(0,212,245,0.12)', border: '1px solid rgba(0,212,245,0.35)', borderRadius: 4, padding: '7px 20px', color: '#00d4f5', cursor: (scanLaunching || isRunning) ? 'not-allowed' : 'pointer', fontSize: 11, fontFamily: 'inherit', fontWeight: 700, opacity: (scanLaunching || isRunning) ? 0.5 : 1 }}
                >
                  {scanLaunching ? '⏳ Starting…' : isRunning ? '⏳ Running…' : '▶ Run Scan'}
                </button>
                <button
                  onClick={fetchScanStatus}
                  style={{ background: 'transparent', border: '1px solid #2a2a4a', borderRadius: 4, padding: '7px 14px', color: '#56567a', cursor: 'pointer', fontSize: 11, fontFamily: 'inherit' }}
                >
                  ↻ Refresh
                </button>
                {scanError && <span style={{ fontSize: 10, color: '#f87171' }}>{scanError}</span>}
              </div>
            </div>
          );
        })()}

        {/* ── Automation Flow ── */}
        <div style={{ ...card, marginBottom: 24 }}>
          <p style={{ ...label, marginBottom: 16 }}>⚙ Automation Flow — Schedule &amp; Functions</p>
          <p style={{ margin: '0 0 14px', fontSize: 10, color: 'rgba(255,255,255,0.3)' }}>
            All times shown in GMT+4 · Mon–Fri unless noted · U.S. market session shown in local GMT+4 time
          </p>

          {[
            // PRE-MARKET
            { group: 'PRE-MARKET', items: [
              { gmt4: '16:00', et: '08:00', color: '#44aaff', tag: 'PIPELINE 2', name: 'Pre-Market Intraday Scan', desc: 'Yahoo Finance: fetches OHLCV for yesterday\'s FIRE/ARM candidates + open journal positions. Computes indicators, scores, saves scan to DB.' },
              { gmt4: '17:00', et: '09:00', color: '#ffd740', tag: 'BRIEF', name: 'Morning Brief (Telegram)', desc: 'Sends Telegram message with top FIRE/ARM tickers from latest scan, market regime, and sector rotation summary.' },
              { gmt4: '17:10', et: '09:10', color: '#ff8844', tag: 'HYPE', name: 'Hype Monitor #1', desc: 'Fetches social/news volume for all scanned tickers. Detects SILENT_VOLUME, HYPE_NO_VOLUME, PEAK_FADING divergences.' },
              { gmt4: '17:15', et: '09:15', color: '#cc44ff', tag: 'AI PORT', name: 'AI Decisions (pre-open)', desc: 'Claude AI reviews FIRE/ARM candidates from latest EOD scan + open positions. Makes BUY/SELL/HOLD decisions. Runs before market open so decisions are ready at the bell. Max 5 positions, 2% risk per trade, ATR-based sizing.' },
            ]},
            // MARKET OPEN
            { group: 'MARKET OPEN', items: [
              { gmt4: '17:30', et: '09:30', color: '#44aaff', tag: 'PIPELINE 2', name: 'Market Open Intraday Scan', desc: 'Same as 16:00 scan but with live market-open prices. Key scan — FIRE/ARM here are today\'s actionable setups.' },
              { gmt4: '17:30–00:00', et: '09:30–16:00', color: '#44cc88', tag: 'EVERY 30m', name: 'AI Portfolio Price Update', desc: 'Updates current price, P&L%, max gain/loss for all open AI positions. Auto-closes on ATR stop or target hit.' },
              { gmt4: '17:30–00:00', et: '09:30–16:00', color: '#44cc88', tag: 'EVERY 30m', name: 'Journal Live Prices', desc: 'Persists live prices to journal DB (current_price, current_pct). Used by journal page to show real-time P&L without calling Yahoo Finance every page load.' },
              { gmt4: '17:30–00:00', et: '09:30–16:00', color: '#ff8844', tag: 'EVERY 30m', name: 'Price Alerts', desc: 'Checks all open journal positions — sends Telegram alert if price is within 3% of stop or target.' },
              { gmt4: '20:00', et: '12:00', color: '#44aaff', tag: 'PIPELINE 2', name: 'Midday Intraday Scan', desc: 'Midday re-check of yesterday\'s candidates with updated intraday data. Refreshes tier scores and sector strength.' },
              { gmt4: '20:10', et: '12:10', color: '#ff8844', tag: 'HYPE', name: 'Hype Monitor #2', desc: 'Second hype cycle check. Catches momentum shifts since morning.' },
              { gmt4: '23:20', et: '15:20', color: '#ff8844', tag: 'HYPE', name: 'Hype Monitor #3', desc: 'Pre-close hype check. Detects PEAK_FADING and SILENT_VOLUME ahead of tomorrow — last chance for next-day preparation before EOD.' },
            ]},
            // POST-CLOSE
            { group: 'POST-CLOSE', items: [
              { gmt4: '00:10', et: '16:10', color: '#44cc88', tag: 'JOURNAL', name: 'Journal Auto-Close', desc: 'Fetches closing prices for all open journal entries. Auto-closes if stop or target was hit. Computes P&L%, alpha vs SPY, days held, max gain/loss. Runs slightly after close to allow final prices to settle.' },
              { gmt4: '00:15', et: '16:15', color: '#44cc88', tag: 'JOURNAL', name: 'Fill Candidate Prices', desc: 'Fills historical exit prices for FIRE/ARM scan candidates (used in backtest stats and pattern streaks).' },
              { gmt4: '00:20', et: '16:20', color: '#ffd740', tag: 'REGIME', name: 'Market Regime Detection', desc: 'Fetches all sector ETF prices (SPY, QQQ, XLK, XLE, XLV, GLD, IWM, SMH, XBI…). Detects RISK_ON / RISK_OFF / FEAR / ROTATION / NEUTRAL. Saves etf_details, cycle phase, industry leaders/laggards.' },
              { gmt4: '00:25', et: '16:25', color: '#ffd740', tag: 'REGIME', name: 'Finviz Sector Performance', desc: 'Refreshes Finviz sector momentum cache (11 sectors: change%, rank, A/B/C/D/F class). Used for sector bonus in scoring and sector flow bar on home page.' },
              { gmt4: '00:30', et: '16:30', color: '#cc44ff', tag: 'AI PORT', name: 'AI Portfolio Daily Report', desc: 'Claude AI generates a daily portfolio report in Russian: P&L summary, best position, concerns, tomorrow plan. Sends to Telegram.' },
              { gmt4: '00:35', et: '16:35', color: '#888888', tag: 'EOD LOG', name: 'EOD Log Generator', desc: 'Generates a markdown summary of the full trading day: top signals, regime, sector rotation, portfolio status. Available via "EOD Log" button on home page.' },
            ]},
            // WEEKLY
            { group: 'WEEKLY', items: [
              { gmt4: 'Sun 10:00', et: 'Sun 02:00', color: '#888888', tag: 'MAINT', name: 'Data Rotation', desc: 'Deletes old scan rows, ribbon candidates, hype results, and position snapshots older than 90 days to prevent DB bloat.' },
            ]},
          ].map(({ group, items }) => (
            <div key={group} style={{ marginBottom: 20 }}>
              <div style={{ fontSize: 9, fontWeight: 800, letterSpacing: '0.12em', color: '#56567a', marginBottom: 8, borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: 4 }}>
                {group}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {items.map((item, i) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '80px 56px 1fr', gap: 8, alignItems: 'start', padding: '7px 10px', background: '#0d0d1e', borderRadius: 4, border: `1px solid ${item.color}18` }}>
                    {/* Time (GMT+4 primary) */}
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 700, color: item.color, whiteSpace: 'nowrap' }}>{item.gmt4}</div>
                      <div style={{ fontSize: 9, color: '#56567a', whiteSpace: 'nowrap' }}>{item.et} ET</div>
                    </div>
                    {/* Tag */}
                    <div style={{ paddingTop: 1 }}>
                      <span style={{ fontSize: 8, fontWeight: 800, letterSpacing: '0.05em', background: item.color + '22', color: item.color, border: `1px solid ${item.color}44`, borderRadius: 3, padding: '2px 5px', whiteSpace: 'nowrap' }}>
                        {item.tag}
                      </span>
                    </div>
                    {/* Name + desc */}
                    <div>
                      <div style={{ fontSize: 11, fontWeight: 700, color: '#eaeaf6', marginBottom: 2 }}>{item.name}</div>
                      <div style={{ fontSize: 10, color: '#9898c0', lineHeight: 1.5 }}>{item.desc}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>


        {/* ── Test Massive Connection ── */}
        <div style={card}>
          <p style={label}>Test Massive / Polygon Connection</p>
          <p style={{ margin: '0 0 12px', fontSize: 11, color: 'rgba(255,255,255,0.4)', lineHeight: 1.6 }}>
            Calls <code style={{ color: '#ccc' }}>fetch_grouped_daily(yesterday)</code> and returns a sample of 5 tickers.<br />
            If <code style={{ color: '#ccc' }}>universe_count = 0</code> check the debug log in Railway for the breakdown.
          </p>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              value={symbol}
              onChange={e => setSymbol(e.target.value.toUpperCase())}
              placeholder="Symbol for ticker details"
              style={{ flex: 1, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4, padding: '6px 10px', color: '#e0e0e0', fontFamily: 'inherit', fontSize: 11 }}
            />
            <button
              onClick={() => call('massive', `${API_URL}/api/admin/test-massive?symbol=${symbol}`)}
              disabled={loading.massive}
              style={{ background: 'rgba(255,200,50,0.12)', border: '1px solid rgba(255,200,50,0.35)', borderRadius: 4, padding: '7px 18px', color: '#ffc832', cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', fontWeight: 700 }}
            >
              {loading.massive ? '⏳ Testing…' : '🔌 Test Connection'}
            </button>
          </div>
          {error.massive && <div style={{ color: '#ff6b6b', fontSize: 11, marginTop: 8 }}>Error: {error.massive}</div>}
          {massiveResult && (
            <pre style={pre}>{JSON.stringify(massiveResult, null, 2)}</pre>
          )}
        </div>

        {/* ── Enrich Sectors ── */}
        <div style={card}>
          <p style={label}>Enrich Sector Cache</p>
          <p style={{ margin: '0 0 12px', fontSize: 11, color: 'rgba(255,255,255,0.4)' }}>
            Fills missing sector/industry for symbols with no data. Rate-limited: 1 call per 15s. Runs in background.
          </p>
          <button
            onClick={() => call('enrich', `${API_URL}/api/admin/enrich-sectors`)}
            disabled={loading.enrich}
            style={{ background: 'rgba(68,255,100,0.1)', border: '1px solid rgba(68,255,100,0.3)', borderRadius: 4, padding: '7px 18px', color: '#44ff64', cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', fontWeight: 700 }}
          >
            {loading.enrich ? '⏳ Starting…' : '🔄 Enrich Sectors'}
          </button>
          {error.enrich && <div style={{ color: '#ff6b6b', fontSize: 11, marginTop: 8 }}>Error: {error.enrich}</div>}
          {enrichResult && (
            <pre style={pre}>{JSON.stringify(enrichResult, null, 2)}</pre>
          )}
        </div>

        {/* ── Refresh & Apply All Sector Data ── */}
        <div style={card}>
          <p style={label}>Refresh &amp; Apply All Sector Data</p>
          <p style={{ margin: '0 0 12px', fontSize: 11, color: 'rgba(255,255,255,0.4)', lineHeight: 1.6 }}>
            Two-step sector refresh:<br />
            <strong style={{ color: 'rgba(255,255,255,0.6)' }}>1. Universe cache sync</strong> — pulls fresh type / SIC code / SIC description from Massive for all CS/ADR/ADRC tickers.<br />
            <strong style={{ color: 'rgba(255,255,255,0.6)' }}>2. GICS normalization</strong> — converts raw SIC descriptions in SectorCache to proper GICS sector names using the sector resolver.<br />
            Runs in background. Use after initial setup or when sector column shows raw SIC text.
          </p>
          <button
            onClick={() => call('refresh_sector', `${API_URL}/api/admin/refresh-sector-data`, 'POST')}
            disabled={loading.refresh_sector || refreshSectorStatus?.running}
            style={{ background: 'rgba(255,160,50,0.12)', border: '1px solid rgba(255,160,50,0.4)', borderRadius: 4, padding: '7px 18px', color: '#ffa030', cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', fontWeight: 700, opacity: (loading.refresh_sector || refreshSectorStatus?.running) ? 0.6 : 1 }}
          >
            {(loading.refresh_sector || refreshSectorStatus?.running) ? '⏳ Running…' : '🗂 Refresh & Apply Sectors'}
          </button>
          {error.refresh_sector && <div style={{ color: '#ff6b6b', fontSize: 11, marginTop: 8 }}>Error: {error.refresh_sector}</div>}
          {refreshSectorStatus && refreshSectorStatus.phase !== 'idle' && (
            <div style={{ marginTop: 10, fontSize: 11, color: 'rgba(255,255,255,0.55)', lineHeight: 1.8 }}>
              <div>Phase: <strong style={{ color: '#ffa030' }}>{refreshSectorStatus.phase}</strong>{refreshSectorStatus.running ? ' ⏳' : ''}</div>
              {refreshSectorStatus.universe_synced > 0 && <div>Universe synced: <strong style={{ color: '#eaeaf6' }}>{refreshSectorStatus.universe_synced}</strong> tickers</div>}
              {refreshSectorStatus.phase === 'done' && (
                <>
                  <div>GICS normalized: <strong style={{ color: '#44ff64' }}>{refreshSectorStatus.normalized}</strong> sectors updated</div>
                  <div>Already GICS: <strong style={{ color: '#56567a' }}>{refreshSectorStatus.already_gics}</strong> unchanged</div>
                </>
              )}
              {refreshSectorStatus.last_error && <div style={{ color: '#ff6b6b' }}>Error: {refreshSectorStatus.last_error}</div>}
              {refreshSectorStatus.finished_at && <div style={{ color: '#56567a' }}>Finished: {refreshSectorStatus.finished_at}</div>}
            </div>
          )}
          {refreshSectorResult && refreshSectorResult.error && (
            <div style={{ color: '#ff6b6b', fontSize: 11, marginTop: 8 }}>{refreshSectorResult.error}</div>
          )}
        </div>

        {/* ── Refresh Market Regime ── */}
        <div style={card}>
          <p style={label}>Refresh Market Regime &amp; ETF Data</p>
          <p style={{ margin: '0 0 12px', fontSize: 11, color: 'rgba(255,255,255,0.4)', lineHeight: 1.6 }}>
            Re-fetches all ETF prices from Yahoo Finance and recalculates regime, cycle phase, industry leaders.<br />
            Scheduled: 00:20 GMT+4 Mon–Fri (= 16:20 ET). Use this to refresh after a holiday or if ETF boxes show "—".
          </p>
          <button
            onClick={() => call('regime', `${API_URL}/api/market-regime/refresh`)}
            disabled={loading.regime}
            style={{ background: 'rgba(180,100,255,0.12)', border: '1px solid rgba(180,100,255,0.35)', borderRadius: 4, padding: '7px 18px', color: '#c87fff', cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', fontWeight: 700 }}
          >
            {loading.regime ? '⏳ Refreshing…' : '📡 Refresh Regime'}
          </button>
          {error.regime && <div style={{ color: '#ff6b6b', fontSize: 11, marginTop: 8 }}>Error: {error.regime}</div>}
          {regimeResult && (
            <pre style={pre}>{JSON.stringify(regimeResult, null, 2)}</pre>
          )}
        </div>

        {/* ── Replay Recalculation ── */}
        <div style={card}>
          <p style={label}>Replay Recalculation — Fast Refresh (No Full Rescan)</p>
          <p style={{ margin: '0 0 14px', fontSize: 11, color: 'rgba(255,255,255,0.4)', lineHeight: 1.6 }}>
            Refresh derived outputs for an existing replay run without re-scanning the universe.<br />
            <strong style={{ color: 'rgba(255,255,255,0.6)' }}>Recalculate Derived Fields</strong> — re-runs <code style={{ fontSize: 10 }}>_decide()</code> on every candidate using current logic, then rebuilds the research bundle. Rewrites <code style={{ fontSize: 10 }}>np_decision</code> / <code style={{ fontSize: 10 }}>np_decision_reason</code>.<br />
            <strong style={{ color: 'rgba(255,255,255,0.6)' }}>Rebuild Research Bundle</strong> — rebuilds summary &amp; performance buckets only, no candidate edits.<br />
            <span style={{ color: 'rgba(255,100,100,0.7)' }}>Full replay still required</span> for: state/quality/expansion engine changes, scanner gates, candidate generation.
          </p>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
            <label style={{ fontSize: 11, color: '#56567a', whiteSpace: 'nowrap' }}>Run ID</label>
            <input
              type="number"
              value={replayRunId}
              onChange={e => setReplayRunId(e.target.value)}
              placeholder="e.g. 17"
              style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid #1a1a32', borderRadius: 4, padding: '5px 10px', color: '#eaeaf6', fontSize: 12, fontFamily: 'inherit', width: 90 }}
            />
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button
              onClick={() => {
                if (!replayRunId) return;
                setRecalcResult(null);
                callPost('recalc', `${API_URL}/api/replay/${replayRunId}/recalculate-derived-fields`, setRecalcResult);
              }}
              disabled={loading.recalc || !replayRunId}
              style={{ background: 'rgba(0,212,245,0.1)', border: '1px solid rgba(0,212,245,0.3)', borderRadius: 4, padding: '7px 18px', color: '#00d4f5', cursor: replayRunId ? 'pointer' : 'not-allowed', fontSize: 11, fontFamily: 'inherit', fontWeight: 700, opacity: replayRunId ? 1 : 0.5 }}
            >
              {loading.recalc ? '⏳ Recalculating…' : '⚡ Recalculate Derived Fields'}
            </button>
            <button
              onClick={() => {
                if (!replayRunId) return;
                setRebuildResult(null);
                callPost('rebuild', `${API_URL}/api/replay/${replayRunId}/rebuild-research-bundle`, setRebuildResult);
              }}
              disabled={loading.rebuild || !replayRunId}
              style={{ background: 'rgba(68,255,100,0.08)', border: '1px solid rgba(68,255,100,0.25)', borderRadius: 4, padding: '7px 18px', color: '#44ff64', cursor: replayRunId ? 'pointer' : 'not-allowed', fontSize: 11, fontFamily: 'inherit', fontWeight: 700, opacity: replayRunId ? 1 : 0.5 }}
            >
              {loading.rebuild ? '⏳ Rebuilding…' : '📊 Rebuild Research Bundle'}
            </button>
          </div>
          {error.recalc  && <div style={{ color: '#ff6b6b', fontSize: 11, marginTop: 8 }}>Error: {error.recalc}</div>}
          {error.rebuild && <div style={{ color: '#ff6b6b', fontSize: 11, marginTop: 8 }}>Error: {error.rebuild}</div>}
          {recalcResult  && <pre style={pre}>{JSON.stringify(recalcResult,  null, 2)}</pre>}
          {rebuildResult && <pre style={pre}>{JSON.stringify(rebuildResult, null, 2)}</pre>}
        </div>

        {/* ── Clean DB ── */}
        {(() => {
          const sectionLabel = { fontSize: 9, fontWeight: 800, letterSpacing: '0.1em', color: '#56567a', textTransform: 'uppercase', marginBottom: 12 };
          const row = { display: 'flex', flexDirection: 'column', gap: 8, padding: '14px 0', borderBottom: '1px solid #13132a' };
          const rowTitle = { fontSize: 12, fontWeight: 700, color: '#c8c8e8', marginBottom: 2 };
          const rowDesc = { fontSize: 10, color: '#56567a', marginBottom: 8, lineHeight: 1.5 };
          const inputStyle = { background: '#07070f', border: '1px solid #2a2a4a', borderRadius: 4, color: '#eaeaf6', fontSize: 11, padding: '4px 8px', width: 80 };
          const btn = (danger) => ({
            padding: '5px 14px', borderRadius: 4, border: 'none', cursor: 'pointer', fontSize: 11, fontWeight: 700,
            background: danger ? 'rgba(239,68,68,0.15)' : 'rgba(124,90,245,0.15)',
            color: danger ? '#f87171' : '#c084fc',
            border: `1px solid ${danger ? 'rgba(239,68,68,0.35)' : 'rgba(124,90,245,0.35)'}`,
          });
          const confirmBtn = { padding: '5px 14px', borderRadius: 4, border: '1px solid rgba(239,68,68,0.7)', cursor: 'pointer', fontSize: 11, fontWeight: 700, background: 'rgba(239,68,68,0.25)', color: '#fca5a5' };
          const cancelBtn = { padding: '5px 10px', borderRadius: 4, border: '1px solid #2a2a4a', cursor: 'pointer', fontSize: 11, background: 'transparent', color: '#56567a' };
          const resultPre = (isDryRun) => ({ margin: '8px 0 0', fontSize: 10, color: isDryRun ? '#00d4f5' : '#f87171', background: 'rgba(0,0,0,0.4)', borderRadius: 4, padding: 10, overflowX: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontFamily: "'SF Mono', monospace" });

          const CleanRow = ({ id, title, desc, danger = true, children, onRun }) => (
            <div style={row}>
              <div style={rowTitle}>{title}</div>
              <div style={rowDesc}>{desc}</div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                {children}
                {dbConfirm[id]
                  ? <>
                      <span style={{ fontSize: 11, color: '#f87171', fontWeight: 600 }}>Sure?</span>
                      <button style={confirmBtn} onClick={onRun}>Yes, delete</button>
                      <button style={cancelBtn} onClick={() => setDbConfirm(c => ({ ...c, [id]: false }))}>Cancel</button>
                    </>
                  : <button style={btn(danger)} disabled={loading[id]} onClick={() => { if (danger) { setDbConfirm(c => ({ ...c, [id]: true })); } else { onRun(); } }}>
                      {loading[id] ? 'Running…' : danger ? 'Run' : 'Run'}
                    </button>
                }
                {error[id] && <span style={{ fontSize: 10, color: '#f87171' }}>{error[id]}</span>}
              </div>
              {dbResults[id] && (
                <pre style={resultPre(dbResults[id].dry_run !== false && (dbResults[id].dry_run === true || dbResults[id].dry_run === undefined))}>
                  {JSON.stringify(dbResults[id], null, 2)}
                </pre>
              )}
            </div>
          );

          return (
            <div style={{ ...card, marginBottom: 24 }}>
              <p style={{ ...sectionLabel, marginBottom: 16 }}>Clean DB</p>

              {/* 0a. Full DB Cleanup — all at once */}
              <CleanRow
                id="cleanupAll"
                title="Full DB Cleanup — All at Once"
                desc="Runs all cleanup ops in one call: delete old replay runs, raw-pattern runs, pump-study runs, prune candle cache, then VACUUM ANALYZE all major tables. Set dry_run=on first to preview."
                onRun={() => {
                  const n = parseInt(allKeepN, 10);
                  const d = parseInt(allCandleDays, 10);
                  const params = new URLSearchParams({
                    keep_last_n: isNaN(n) ? 3 : n,
                    keep_candle_days: isNaN(d) ? 200 : d,
                    dry_run: allDryRun,
                  });
                  dbCall('cleanupAll', `${API_URL}/api/admin/cleanup-all?${params}`, 'POST');
                }}
              >
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#c8c8e8' }}>
                  Keep last <input type="number" min="0" value={allKeepN} onChange={e => setAllKeepN(e.target.value)} style={{ ...inputStyle, width: 50 }} /> runs
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#c8c8e8' }}>
                  Candle days <input type="number" min="30" value={allCandleDays} onChange={e => setAllCandleDays(e.target.value)} style={{ ...inputStyle, width: 60 }} />
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: allDryRun ? '#00d4f5' : '#f87171' }}>
                  <input type="checkbox" checked={allDryRun} onChange={e => setAllDryRun(e.target.checked)} />
                  Dry run
                </label>
              </CleanRow>

              {/* 0b. Candle Cache Prune */}
              <CleanRow
                id="candlePrune"
                title="Candle Cache — Prune Old Bars"
                desc="Delete candle_cache rows older than N days. Does not touch run data. Dry run shows count without deleting."
                onRun={() => {
                  const d = parseInt(candleDays, 10);
                  const params = new URLSearchParams({
                    keep_last_n: 9999,
                    keep_candle_days: isNaN(d) ? 200 : d,
                    dry_run: candleDryRun,
                  });
                  dbCall('candlePrune', `${API_URL}/api/admin/cleanup-all?${params}`, 'POST');
                }}
              >
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#c8c8e8' }}>
                  Keep days <input type="number" min="30" value={candleDays} onChange={e => setCandleDays(e.target.value)} style={{ ...inputStyle, width: 60 }} />
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: candleDryRun ? '#00d4f5' : '#f87171' }}>
                  <input type="checkbox" checked={candleDryRun} onChange={e => setCandleDryRun(e.target.checked)} />
                  Dry run
                </label>
              </CleanRow>

              {/* 0c. Replay bulk cleanup */}
              <CleanRow
                id="replayBulk"
                title="Replay — Bulk Cleanup"
                desc="Delete old complete replay runs (+ signal candidates, outcomes, missed movers). Keep the N most recent. Dry run first."
                onRun={() => {
                  const n = parseInt(replayKeepN, 10);
                  dbCall('replayBulk', `${API_URL}/api/replay/cleanup`, 'POST', {
                    keep_last_n: isNaN(n) ? 3 : n,
                    dry_run: replayBulkDryRun,
                  });
                }}
              >
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#c8c8e8' }}>
                  Keep last <input type="number" min="0" value={replayKeepN} onChange={e => setReplayKeepN(e.target.value)} style={{ ...inputStyle, width: 50 }} /> runs
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: replayBulkDryRun ? '#00d4f5' : '#f87171' }}>
                  <input type="checkbox" checked={replayBulkDryRun} onChange={e => setReplayBulkDryRun(e.target.checked)} />
                  Dry run
                </label>
              </CleanRow>

              {/* 0d. Pump study bulk cleanup */}
              <CleanRow
                id="pumpBulk"
                title="Pump Study — Bulk Cleanup"
                desc="Delete old complete pump-study runs (episodes, snapshots, events, clusters, comparisons, AI summaries). Keep the N most recent. Dry run first."
                onRun={() => {
                  const n = parseInt(pumpKeepN, 10);
                  dbCall('pumpBulk', `${API_URL}/api/replay/pump-study/cleanup`, 'POST', {
                    keep_last_n: isNaN(n) ? 3 : n,
                    dry_run: pumpBulkDryRun,
                  });
                }}
              >
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#c8c8e8' }}>
                  Keep last <input type="number" min="0" value={pumpKeepN} onChange={e => setPumpKeepN(e.target.value)} style={{ ...inputStyle, width: 50 }} /> runs
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: pumpBulkDryRun ? '#00d4f5' : '#f87171' }}>
                  <input type="checkbox" checked={pumpBulkDryRun} onChange={e => setPumpBulkDryRun(e.target.checked)} />
                  Dry run
                </label>
              </CleanRow>

              {/* 1. Rotate old data */}
              <CleanRow
                id="rotate"
                title="Rotate Old Data"
                danger={false}
                desc="Delete rows older than retention limits: scans (30d), scan_candidates (60d), position_snapshots (60d), eod_logs (90d), ribbon_candidates (14d). Journal, watchlist, market_regime are never touched."
                onRun={() => dbCall('rotate', `${API_URL}/api/admin/rotate-data`)}
              />

              {/* 2. Raw pattern bulk cleanup */}
              <CleanRow
                id="rawBulk"
                title="Raw Pattern Study — Bulk Cleanup"
                desc="Delete old complete raw-pattern-study runs (+ all child rows: daily features, episode features, discovered patterns, AI summaries, comparisons). Keep the N most recent. Run dry-run first to preview."
                onRun={() => {
                  const n = parseInt(rawKeepN, 10);
                  dbCall('rawBulk', `${API_URL}/api/replay/raw-pattern-study/cleanup`, 'POST', {
                    keep_last_n: isNaN(n) ? 0 : n,
                    dry_run: rawDryRun,
                    vacuum: rawVacuum && !rawDryRun,
                  });
                }}
              >
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#c8c8e8' }}>
                  Keep last <input type="number" min="0" value={rawKeepN} onChange={e => setRawKeepN(e.target.value)} style={{ ...inputStyle, width: 50 }} /> runs
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: rawDryRun ? '#00d4f5' : '#f87171' }}>
                  <input type="checkbox" checked={rawDryRun} onChange={e => setRawDryRun(e.target.checked)} />
                  Dry run
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, color: '#c8c8e8' }}>
                  <input type="checkbox" checked={rawVacuum} onChange={e => setRawVacuum(e.target.checked)} disabled={rawDryRun} />
                  Vacuum (SQLite only)
                </label>
              </CleanRow>

              {/* 3. Delete single raw pattern run */}
              <CleanRow
                id="rawSingle"
                title="Raw Pattern Study — Delete Single Run"
                desc="Hard-delete one raw-pattern-study run by ID, including all child records."
                onRun={() => { if (!delRawId) return; dbCall('rawSingle', `${API_URL}/api/replay/raw-pattern-study/${delRawId}`, 'DELETE'); }}
              >
                <input type="number" placeholder="Run ID" value={delRawId} onChange={e => setDelRawId(e.target.value)} style={inputStyle} />
              </CleanRow>

              {/* 4. Delete single pump study run */}
              <CleanRow
                id="pumpSingle"
                title="Pump Study — Delete Single Run"
                desc="Hard-delete one pump-study run by ID (episodes, snapshots, events, clusters, comparisons, AI summaries)."
                onRun={() => { if (!delPumpId) return; dbCall('pumpSingle', `${API_URL}/api/replay/pump-study/${delPumpId}`, 'DELETE'); }}
              >
                <input type="number" placeholder="Run ID" value={delPumpId} onChange={e => setDelPumpId(e.target.value)} style={inputStyle} />
              </CleanRow>

              {/* 5. Delete single replay run */}
              <CleanRow
                id="replaySingle"
                title="Replay Run — Delete Single Run"
                desc="Hard-delete one replay run by ID (signal candidates, outcomes, missed movers)."
                onRun={() => { if (!delReplayId) return; dbCall('replaySingle', `${API_URL}/api/replay/${delReplayId}`, 'DELETE'); }}
              >
                <input type="number" placeholder="Run ID" value={delReplayId} onChange={e => setDelReplayId(e.target.value)} style={inputStyle} />
              </CleanRow>

              {/* 6. Journal reset */}
              <CleanRow
                id="journal"
                title="Journal Reset"
                desc="Delete ALL journal entries and position snapshots. Irreversible."
                onRun={() => dbCall('journal', `${API_URL}/api/journal/reset`, 'DELETE')}
              />

            </div>
          );
        })()}

        {/* ── Quick Links ── */}
        <div style={card}>
          <p style={label}>Direct Backend Links</p>
          {[
            {
              group: 'Admin / Scanner',
              links: [
                ['/api/admin/test-massive?symbol=' + symbol, 'Test Massive connection'],
                ['/api/admin/enrich-sectors', 'Trigger sector enrichment (missing only)'],
                ['/api/admin/refresh-sector-data/status', 'Sector refresh status'],
                ['/api/market-regime/refresh', 'Refresh ETF / market regime (background)'],
                ['/api/market-regime', 'Latest market regime'],
                ['/api/demand-scanner/latest', 'Latest demand scanner results'],
                ['/api/replay/history', 'Replay run history'],
                ['/health', 'Health check'],
              ],
            },
            {
              group: 'Raw Pattern Study',
              links: [
                ['/api/replay/raw-pattern-study/runs', 'List all raw-pattern-study runs'],
                ['/api/replay/pump-study/runs', 'List all pump-study runs'],
                ['/api/replay/raw-pattern-study/100', 'Run 100 detail (change ID in URL)'],
                ['/api/replay/raw-pattern-study/100/episodes', 'Run 100 — episode features'],
                ['/api/replay/raw-pattern-study/100/daily-features', 'Run 100 — daily bar features (PRE/POST)'],
                ['/api/replay/raw-pattern-study/100/comparisons', 'Run 100 — ticker comparisons'],
              ],
            },
            {
              group: 'Pattern Discovery',
              links: [
                ['/api/replay/raw-pattern-study/100/discover/status', 'Discovery progress for run 100'],
                ['/api/replay/raw-pattern-study/100/discover/results', 'Discovered patterns for run 100'],
                ['/api/replay/raw-pattern-study/100/discover/export-full', 'Full discovery export JSON for run 100 (all patterns + episodes)'],
                ['/api/replay/raw-pattern-study/100/pump-watch', 'Pump Watch scores for run 100'],
                ['/api/replay/signal-registry', 'Discovered signal registry (JSON)'],
              ],
            },
          ].map(({ group, links }) => (
            <div key={group} style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 9, fontWeight: 800, letterSpacing: '0.1em', color: '#56567a', marginBottom: 6, textTransform: 'uppercase' }}>
                {group}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                {links.map(([path, desc]) => (
                  <div key={path} style={{ display: 'flex', gap: 10, alignItems: 'baseline' }}>
                    <a href={`${API_URL}${path}`} target="_blank" rel="noreferrer"
                      style={{ fontSize: 10, color: '#00d4f5', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                      {path}
                    </a>
                    <span style={{ fontSize: 10, color: '#56567a' }}>— {desc}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        </div>
      </div>
    </>
  );
}
