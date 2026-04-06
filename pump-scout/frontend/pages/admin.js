import { useState, useEffect, useRef } from 'react';
import Head from 'next/head';
import Link from 'next/link';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const PHASE_LABELS = {
  idle:              'Idle — not running',
  fetching_universe: 'Fetching universe from Polygon…',
  filtering:         'Applying price/volume filters…',
  scoring:           'Scoring candidates…',
  enriching:         'Enriching sector data…',
  saving:            'Saving results to database…',
  done:              'Done',
  error:             'Failed',
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
  const [scanStatus, setScanStatus] = useState(null);
  const [loading, setLoading] = useState({});
  const [error, setError] = useState({});
  const pollRef = useRef(null);

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

  // Fetch status once on mount, start polling if already running
  useEffect(() => {
    fetch(`${API_URL}/api/admin/universe-scan/status`)
      .then(r => r.json())
      .then(data => {
        setScanStatus(data);
        if (data.running) startPolling();
      })
      .catch(() => {});
    return stopPolling;
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function call(key, url) {
    setLoading(l => ({ ...l, [key]: true }));
    setError(e => ({ ...e, [key]: null }));
    try {
      const res = await fetch(url);
      const data = await res.json();
      if (key === 'massive')  setMassiveResult(data);
      if (key === 'enrich')   setEnrichResult(data);
      if (key === 'universe') {
        setUniverseResult(data);
        // Begin polling status after triggering
        setTimeout(() => {
          fetch(`${API_URL}/api/admin/universe-scan/status`)
            .then(r => r.json()).then(d => { setScanStatus(d); if (d.running) startPolling(); })
            .catch(() => {});
        }, 1500);
      }
    } catch (err) {
      setError(e => ({ ...e, [key]: err.message }));
    } finally {
      setLoading(l => ({ ...l, [key]: false }));
    }
  }

  const card = { marginBottom: 24, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: 16 };
  const label = { margin: '0 0 10px', fontSize: 11, fontWeight: 700, letterSpacing: '0.09em', color: 'rgba(255,255,255,0.45)', textTransform: 'uppercase' };
  const pre = { margin: '12px 0 0', fontSize: 10, color: '#a0e0a0', background: 'rgba(0,0,0,0.35)', borderRadius: 4, padding: 10, overflowX: 'auto', whiteSpace: 'pre-wrap', wordBreak: 'break-word' };

  return (
    <>
      <Head>
        <title>Admin — Pump Scout</title>
        <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }`}</style>
      </Head>
      <div style={{ maxWidth: 820, margin: '0 auto', padding: '24px 16px', fontFamily: "'JetBrains Mono', monospace", color: '#e0e0e0', background: '#0a0a0f', minHeight: '100vh' }}>

        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 28 }}>
          <Link href="/" style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)', textDecoration: 'none' }}>← back</Link>
          <h1 style={{ margin: 0, fontSize: 15, fontWeight: 800, letterSpacing: '0.08em' }}>ADMIN PANEL</h1>
          <span style={{ marginLeft: 'auto', fontSize: 10, color: 'rgba(255,255,255,0.25)' }}>{API_URL}</span>
        </div>

        {/* ── Run Universe Scan ── */}
        <div style={card}>
          <p style={label}>Run Universe Scan (Massive EOD)</p>
          <p style={{ margin: '0 0 12px', fontSize: 11, color: 'rgba(255,255,255,0.4)', lineHeight: 1.6 }}>
            Fetches all US stocks from Polygon grouped daily → scores top 600.<br />
            Scheduled: 22:00 ET Mon–Fri (= 06:00 next day Tbilisi).<br />
            This button triggers it immediately in the background.
          </p>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input
              value={scanDate}
              onChange={e => setScanDate(e.target.value)}
              placeholder="Date YYYY-MM-DD (blank = yesterday)"
              style={{ flex: 1, minWidth: 200, background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 4, padding: '6px 10px', color: '#e0e0e0', fontFamily: 'inherit', fontSize: 11 }}
            />
            <button
              onClick={() => {
                const url = scanDate
                  ? `${API_URL}/api/admin/run-universe-scan?date=${scanDate}`
                  : `${API_URL}/api/admin/run-universe-scan`;
                call('universe', url);
              }}
              disabled={loading.universe}
              style={{ background: 'rgba(68,170,255,0.15)', border: '1px solid rgba(68,170,255,0.4)', borderRadius: 4, padding: '7px 18px', color: '#44aaff', cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', fontWeight: 700, whiteSpace: 'nowrap' }}
            >
              {loading.universe ? '⏳ Starting…' : '📊 Run Universe Scan'}
            </button>
            <a
              href={`${API_URL}/api/scan/universe/latest`}
              target="_blank"
              rel="noreferrer"
              style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', textDecoration: 'none' }}
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
            <div style={{ marginTop: 14, background: 'rgba(0,0,0,0.3)', borderRadius: 6, padding: '12px 14px', border: `1px solid ${scanStatus.running ? 'rgba(68,170,255,0.3)' : scanStatus.phase === 'done' ? 'rgba(68,255,100,0.25)' : 'rgba(255,100,100,0.25)'}` }}>
              {/* Phase + running indicator */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                {scanStatus.running && <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#44aaff', boxShadow: '0 0 6px #44aaff', display: 'inline-block', animation: 'pulse 1.2s infinite' }} />}
                {!scanStatus.running && scanStatus.phase === 'done' && <span style={{ color: '#44ff64', fontSize: 13 }}>✓</span>}
                {!scanStatus.running && scanStatus.phase === 'error' && <span style={{ color: '#ff6b6b', fontSize: 13 }}>✗</span>}
                <span style={{ fontSize: 11, fontWeight: 700, color: '#ddd' }}>
                  {PHASE_LABELS[scanStatus.phase] || scanStatus.phase}
                </span>
                {scanStatus.target_date && (
                  <span style={{ marginLeft: 'auto', fontSize: 10, color: 'rgba(255,255,255,0.3)' }}>
                    {scanStatus.target_date}
                  </span>
                )}
              </div>

              {/* Progress bar (scoring phase) */}
              {scanStatus.candidates_total > 0 && (
                <div style={{ marginBottom: 10 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'rgba(255,255,255,0.4)', marginBottom: 4 }}>
                    <span>Scoring candidates</span>
                    <span>{scanStatus.candidates_done} / {scanStatus.candidates_total}</span>
                  </div>
                  <div style={{ height: 5, background: 'rgba(255,255,255,0.08)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{
                      height: '100%', borderRadius: 3,
                      background: scanStatus.running ? '#44aaff' : '#44ff64',
                      width: `${Math.round((scanStatus.candidates_done / scanStatus.candidates_total) * 100)}%`,
                      transition: 'width 0.5s ease',
                    }} />
                  </div>
                </div>
              )}

              {/* Stats grid */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                {[
                  ['Universe', scanStatus.universe_raw > 0 ? scanStatus.universe_raw.toLocaleString() : '—'],
                  ['Filtered', scanStatus.universe_filtered > 0 ? scanStatus.universe_filtered.toLocaleString() : '—'],
                  ['Results', scanStatus.results_count],
                  ['🔥 FIRE', scanStatus.fire_count],
                  ['💪 ARM', scanStatus.arm_count],
                  ['Errors', scanStatus.errors],
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

        {/* ── Quick Links ── */}
        <div style={card}>
          <p style={label}>Direct Backend Links</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {[
              ['/api/admin/test-massive?symbol=' + symbol, 'Test Massive connection'],
              ['/api/admin/run-universe-scan', 'Trigger universe scan (background)'],
              ['/api/admin/universe-scan/status', 'Live scan progress'],
              ['/api/admin/enrich-sectors', 'Trigger sector enrichment'],
              ['/api/scan/universe/latest', 'Latest EOD universe scan results'],
              ['/api/scan/intraday/latest', 'Latest intraday scan results'],
              ['/api/scan/latest', 'Latest scan (any type)'],
              ['/health', 'Health check'],
            ].map(([path, desc]) => (
              <div key={path} style={{ display: 'flex', gap: 10, alignItems: 'baseline' }}>
                <a href={`${API_URL}${path}`} target="_blank" rel="noreferrer"
                  style={{ fontSize: 10, color: '#4488ff', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                  {path}
                </a>
                <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.25)' }}>— {desc}</span>
              </div>
            ))}
          </div>
        </div>

      </div>
    </>
  );
}
