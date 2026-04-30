import { useState, useEffect, useRef } from 'react';
import Head from 'next/head';
import AppNav from '../components/AppNav';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const PHASE_LABELS = {
  idle:              'Idle — not running',
  fetching_universe: 'Fetching universe from Polygon…',
  filtering_etf:     'Loading ETF exclusion list… (first run only, cached 7 days)',
  filtering:         'Applying price/volume filters…',
  scoring:           'Scoring candidates…',
  enriching:         'Enriching sector data…',
  saving:            'Saving results to database…',
  done:              'Done',
  error:             'Failed',
};

// Rough expected duration per phase in seconds (shown as hint when no ETA available)
const PHASE_HINTS = {
  fetching_universe: '~5–15s',
  filtering_etf:     '~5–30s (then cached for 7 days)',
  filtering:         '~2s',
  scoring:           '~4–6 min for 3000 candidates (40 concurrent)',
  enriching:         '~2–5 min',
  saving:            '~5s',
};

function fmtSecs(s) {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

export default function AdminPage() {
  const [symbol, setSymbol] = useState('AAPL');
  const [scanDate, setScanDate] = useState('');
  const [massiveResult, setMassiveResult] = useState(null);
  const [enrichResult, setEnrichResult] = useState(null);
  const [universeResult, setUniverseResult] = useState(null);
  const [regimeResult, setRegimeResult] = useState(null);
  const [scanStatus, setScanStatus] = useState(null);
  const [npScanStatus, setNpScanStatus] = useState(null);
  const [loading, setLoading] = useState({});
  const [error, setError] = useState({});
  const [replayRunId, setReplayRunId] = useState('');
  const [recalcResult, setRecalcResult] = useState(null);
  const [rebuildResult, setRebuildResult] = useState(null);
  const [refreshSectorResult, setRefreshSectorResult] = useState(null);
  const [refreshSectorStatus, setRefreshSectorStatus] = useState(null);
  const pollRef = useRef(null);
  const npPollRef = useRef(null);
  const sectorRefreshPollRef = useRef(null);

  // Poll /api/admin/universe-scan/status every 5s
  const startPolling = () => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_URL}/api/admin/universe-scan/status`);
        const data = await res.json();
        setScanStatus(data);
        if (!data.running) stopPolling();
      } catch (_) {}
    }, 5000);
  };

  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  };

  const startNpPolling = () => {
    if (npPollRef.current) return;
    npPollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_URL}/api/admin/new-pump-scan/status`);
        const data = await res.json();
        setNpScanStatus(data);
        if (!data.running) stopNpPolling();
      } catch (_) {}
    }, 5000);
  };
  const stopNpPolling = () => {
    if (npPollRef.current) { clearInterval(npPollRef.current); npPollRef.current = null; }
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

  // Fetch status once on mount, start polling if already running
  useEffect(() => {
    fetch(`${API_URL}/api/admin/universe-scan/status`)
      .then(r => r.json())
      .then(data => {
        setScanStatus(data);
        if (data.running) startPolling();
      })
      .catch(() => {});
    fetch(`${API_URL}/api/admin/new-pump-scan/status`)
      .then(r => r.json())
      .then(data => {
        setNpScanStatus(data);
        if (data.running) startNpPolling();
      })
      .catch(() => {});
    return () => { stopPolling(); stopNpPolling(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
      if (key === 'universe') {
        setUniverseResult(data);
        // Begin polling status after triggering
        setTimeout(() => {
          fetch(`${API_URL}/api/admin/universe-scan/status`)
            .then(r => r.json()).then(d => { setScanStatus(d); if (d.running) startPolling(); })
            .catch(() => {});
        }, 1500);
      }
      if (key === 'newpump') {
        setTimeout(() => {
          fetch(`${API_URL}/api/admin/new-pump-scan/status`)
            .then(r => r.json()).then(d => { setNpScanStatus(d); if (d.running) startNpPolling(); })
            .catch(() => {});
        }, 1500);
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
            // NIGHT
            { group: 'NIGHT', items: [
              { gmt4: '06:00', et: '22:00', color: '#ff4466', tag: 'PIPELINE 1 ★', name: 'Massive EOD Universe Scan', desc: 'Main daily scan. One Polygon API call → all US stocks (~8000). Filters by price ($1.50–$500) and volume (>200K). Top 3000 by dollar-volume (40 concurrent batches) → full indicator scoring (RSI, CMF, Wyckoff, OBV, ATR, EMA ribbon…) → FIRE/ARM/BASE tiers. ~4–6 min.' },
              { gmt4: 'after EOD ↑', et: '—', color: '#888888', tag: 'ENRICH', name: 'Sector/Industry Enrichment', desc: 'Runs automatically after successful universe scan completion. Fills missing sector & industry data for scanned symbols via Massive Reference Data API. Rate-limited to 1 call per 15s. Triggered by scan success — not a fixed clock time.' },
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

        {/* ── Run Universe Scan ── */}
        <div style={card}>
          <p style={label}>Run Universe Scan (Massive EOD)</p>
          <p style={{ margin: '0 0 12px', fontSize: 11, color: '#9898c0', lineHeight: 1.6 }}>
            Fetches all US stocks (~5–8K) from Polygon → filters by price ($1.50–$500) and volume (&gt;200K) → takes top 3000 by dollar volume → full indicator scoring.<br />
            <span style={{ color: '#56567a' }}>Batched 40 concurrent Polygon calls. Covers virtually the entire filtered universe (~2,500–3,000 stocks) in ~4–6 min.</span><br />
            Scheduled: 06:00 GMT+4 Mon–Fri (= 22:00 ET). Sector enrichment runs automatically after.
          </p>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              value={scanDate}
              onChange={e => setScanDate(e.target.value)}
              placeholder="Date YYYY-MM-DD (blank = today)"
              style={{ flex: 1, minWidth: 200, background: 'rgba(255,255,255,0.06)', border: '1px solid #1a1a32', borderRadius: 4, padding: '6px 10px', color: '#eaeaf6', fontFamily: 'inherit', fontSize: 11 }}
            />
            <button
              onClick={() => {
                const url = scanDate
                  ? `${API_URL}/api/admin/run-universe-scan?date=${scanDate}`
                  : `${API_URL}/api/admin/run-universe-scan`;
                call('universe', url);
              }}
              disabled={loading.universe}
              style={{ background: 'rgba(0,212,245,0.15)', border: '1px solid rgba(0,212,245,0.4)', borderRadius: 4, padding: '7px 18px', color: '#00d4f5', cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', fontWeight: 700, whiteSpace: 'nowrap' }}
            >
              {loading.universe ? '⏳ Starting…' : '📊 Run Universe Scan'}
            </button>
            <a
              href={`${API_URL}/api/scan/universe/latest`}
              target="_blank"
              rel="noreferrer"
              style={{ fontSize: 10, color: '#56567a', textDecoration: 'none' }}
            >
              view results ↗
            </a>
          </div>
          {error.universe && <div style={{ color: '#ff6b6b', fontSize: 11, marginTop: 8 }}>Error: {error.universe}</div>}
          {universeResult && (
            <pre style={pre}>{JSON.stringify(universeResult, null, 2)}</pre>
          )}

          {/* ── Live progress widget ── */}
          {scanStatus && scanStatus.phase !== 'idle' && (
            <div style={{ marginTop: 14, background: 'rgba(0,0,0,0.3)', borderRadius: 6, padding: '12px 14px', border: `1px solid ${scanStatus.running ? 'rgba(0,212,245,0.3)' : scanStatus.phase === 'done' ? 'rgba(40,217,113,0.25)' : 'rgba(255,100,100,0.25)'}` }}>
              {/* Phase + running indicator */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                {scanStatus.running && <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#00d4f5', boxShadow: '0 0 6px #00d4f5', display: 'inline-block', animation: 'pulse 1.2s infinite' }} />}
                {!scanStatus.running && scanStatus.phase === 'done' && <span style={{ color: '#44ff64', fontSize: 13 }}>✓</span>}
                {!scanStatus.running && scanStatus.phase === 'error' && <span style={{ color: '#ff6b6b', fontSize: 13 }}>✗</span>}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: '#eaeaf6' }}>
                    {PHASE_LABELS[scanStatus.phase] || scanStatus.phase}
                  </span>
                  {PHASE_HINTS[scanStatus.phase] && scanStatus.candidates_total === 0 && (
                    <span style={{ fontSize: 10, color: '#56567a', fontStyle: 'italic' }}>
                      Expected: {PHASE_HINTS[scanStatus.phase]}
                    </span>
                  )}
                </div>
                {scanStatus.target_date && (
                  <span style={{ marginLeft: 'auto', fontSize: 10, color: '#56567a', flexShrink: 0 }}>
                    {scanStatus.target_date}
                  </span>
                )}
              </div>

              {/* Candidate scoring progress — shown as soon as candidates_total is known */}
              {scanStatus.candidates_total > 0 && (() => {
                const total     = scanStatus.candidates_total;
                const done      = scanStatus.candidates_done;
                const remaining = Math.max(0, total - done);
                const pct       = Math.min(100, Math.round((done / total) * 100));
                const barColor  = scanStatus.running ? '#00d4f5' : '#28d971';
                return (
                  <div style={{ marginBottom: 4 }}>
                    {/* Big 3 numbers */}
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, marginBottom: 8 }}>
                      {[
                        { label: 'Started',   val: total.toLocaleString(),     color: '#aaa'    },
                        { label: 'Scanned',   val: done.toLocaleString(),      color: barColor  },
                        { label: 'Remaining', val: remaining.toLocaleString(), color: remaining === 0 ? '#28d971' : '#ffd700' },
                      ].map(({ label, val, color }) => (
                        <div key={label} style={{ background: '#0d0d1e', borderRadius: 5, padding: '7px 10px', textAlign: 'center', border: `1px solid ${color}22` }}>
                          <div style={{ fontSize: 9, color: '#56567a', marginBottom: 3, letterSpacing: '0.07em', textTransform: 'uppercase' }}>{label}</div>
                          <div style={{ fontSize: 18, fontWeight: 800, color, lineHeight: 1 }}>{val}</div>
                        </div>
                      ))}
                    </div>
                    {/* Progress bar */}
                    <div style={{ height: 6, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden', marginBottom: 4 }}>
                      <div style={{ height: '100%', borderRadius: 3, background: barColor, width: `${pct}%`, transition: 'width 0.5s ease' }} />
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'rgba(255,255,255,0.3)' }}>
                      <span>Scoring candidates</span>
                      <span>{pct}% complete</span>
                    </div>
                  </div>
                );
              })()}

              {/* Stats grid */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginTop: 4 }}>
                {[
                  ['Universe', scanStatus.universe_raw > 0 ? scanStatus.universe_raw.toLocaleString() : '—'],
                  ['Filtered', scanStatus.universe_filtered > 0 ? scanStatus.universe_filtered.toLocaleString() : '—'],
                  ['Results', scanStatus.results_count || '—'],
                  ['🔥 FIRE', scanStatus.fire_count || '—'],
                  ['💪 ARM', scanStatus.arm_count || '—'],
                  ['Errors', scanStatus.errors || '0'],
                  ['Elapsed', fmtSecs(scanStatus.elapsed_secs)],
                  ['ETA', scanStatus.running ? fmtSecs(scanStatus.eta_secs) : '—'],
                ].map(([label, val]) => (
                  <div key={label} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 4, padding: '5px 8px', textAlign: 'center' }}>
                    <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.35)', marginBottom: 2 }}>{label}</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: '#e0e0e0' }}>{val}</div>
                  </div>
                ))}
              </div>

              {scanStatus.last_error && (
                <div style={{ marginTop: 8, fontSize: 10, color: '#ff8888' }}>Error: {scanStatus.last_error}</div>
              )}
            </div>
          )}
        </div>

        {/* ── New Pump Universe Scan ── */}
        <div style={card}>
          <p style={label}>New Pump Universe Scan (Massive / Polygon)</p>
          <p style={{ margin: '0 0 12px', fontSize: 11, color: '#9898c0', lineHeight: 1.6 }}>
            Standalone New Pump pipeline — no old-scanner input, no Finviz, no Yahoo.<br />
            <span style={{ color: '#56567a' }}>Fetches all US stocks via Polygon grouped daily → neutral price/vol filter → 200-bar candle history → new_pump_engine.analyze() per ticker → ranks by score.</span>
          </p>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              onClick={() => call('newpump', `${API_URL}/api/admin/run-new-pump-scan`)}
              disabled={loading.newpump || npScanStatus?.running}
              style={{ background: 'rgba(255,68,0,0.12)', border: '1px solid rgba(255,68,0,0.4)', borderRadius: 4, padding: '7px 18px', color: '#ff6622', cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', fontWeight: 700, whiteSpace: 'nowrap' }}
            >
              {loading.newpump || npScanStatus?.running ? '⏳ Scanning…' : '🔥 Run New Pump Scan'}
            </button>
            <a
              href="/new-pump"
              style={{ fontSize: 10, color: '#56567a', textDecoration: 'none' }}
            >
              view results ↗
            </a>
          </div>
          {error.newpump && <div style={{ color: '#ff6b6b', fontSize: 11, marginTop: 8 }}>Error: {error.newpump}</div>}

          {/* Live progress */}
          {npScanStatus && npScanStatus.phase !== 'idle' && (
            <div style={{ marginTop: 14, background: 'rgba(0,0,0,0.3)', borderRadius: 6, padding: '12px 14px', border: `1px solid ${npScanStatus.running ? 'rgba(255,100,0,0.3)' : npScanStatus.phase === 'done' ? 'rgba(40,217,113,0.25)' : 'rgba(255,100,100,0.25)'}` }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                {npScanStatus.running && <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#ff6622', boxShadow: '0 0 6px #ff6622', display: 'inline-block', animation: 'pulse 1.2s infinite' }} />}
                {!npScanStatus.running && npScanStatus.phase === 'done' && <span style={{ color: '#44ff64', fontSize: 13 }}>✓</span>}
                {!npScanStatus.running && npScanStatus.phase === 'error' && <span style={{ color: '#ff6b6b', fontSize: 13 }}>✗</span>}
                <span style={{ fontSize: 11, fontWeight: 700, color: '#eaeaf6' }}>
                  {{
                    fetching_universe: 'Fetching universe from Polygon…',
                    filtering:         'Applying neutral prefilters…',
                    fetching_candles:  'Fetching 200-bar candle history…',
                    analyzing:         'Running new_pump_engine.analyze()…',
                    done:              'Scan complete',
                    error:             'Scan failed',
                  }[npScanStatus.phase] || npScanStatus.phase}
                </span>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                {[
                  ['Universe', npScanStatus.universe_size || '—'],
                  ['Fetched',  npScanStatus.fetched_count || '—'],
                  ['Analyzed', npScanStatus.analyzed_count || '—'],
                  ['Skipped',  npScanStatus.skipped_count ?? '—'],
                  ['🔥 FIRE',  npScanStatus.fire_count   || '—'],
                  ['💪 STRONG',npScanStatus.strong_count || '—'],
                  ['📐 SETUP', npScanStatus.setup_count  || '—'],
                  ['Elapsed',  npScanStatus.elapsed_secs != null ? `${npScanStatus.elapsed_secs}s` : '—'],
                ].map(([lbl, val]) => (
                  <div key={lbl} style={{ background: 'rgba(255,255,255,0.04)', borderRadius: 4, padding: '5px 8px', textAlign: 'center' }}>
                    <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.35)', marginBottom: 2 }}>{lbl}</div>
                    <div style={{ fontSize: 13, fontWeight: 700, color: '#e0e0e0' }}>{val}</div>
                  </div>
                ))}
              </div>
              {npScanStatus.last_error && (
                <div style={{ marginTop: 8, fontSize: 10, color: '#ff8888' }}>Error: {npScanStatus.last_error}</div>
              )}
            </div>
          )}
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

        {/* ── Quick Links ── */}
        <div style={card}>
          <p style={label}>Direct Backend Links</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {[
              ['/api/admin/test-massive?symbol=' + symbol, 'Test Massive connection'],
              ['/api/admin/run-universe-scan', 'Trigger universe scan (background)'],
              ['/api/admin/universe-scan/status', 'Live scan progress'],
              ['/api/admin/enrich-sectors', 'Trigger sector enrichment (missing only)'],
              ['/api/admin/refresh-sector-data/status', 'Sector refresh status'],
              ['/api/market-regime/refresh', 'Refresh ETF / market regime (background)'],
              ['/api/market-regime', 'Latest market regime'],
              ['/api/scan/universe/latest', 'Latest EOD universe scan results'],
              ['/api/scan/intraday/latest', 'Latest intraday scan results'],
              ['/api/scan/latest', 'Latest scan (any type)'],
              ['/api/replay/history', 'Replay run history'],
              ['/health', 'Health check'],
            ].map(([path, desc]) => (
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

        </div>
      </div>
    </>
  );
}
