import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import TickerCard from '../components/TickerCard';
import Scanner from '../components/Scanner';
import styles from '../styles/Home.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REFRESH_INTERVAL = 60 * 1000; // 60 seconds
const VERSION = 'v9.11';
const TIERS = ['FIRE', 'ARM', 'BASE', 'STEALTH', 'SYMPATHY', 'FLOW', 'SILENT', 'HYPE', 'WATCH'];
const TIER_LABELS = {
  FIRE: '🔥 FIRE', ARM: '👁 ARM', BASE: '📦 BASE', STEALTH: '🕵 STEALTH',
  SYMPATHY: '🔗 SYMPATHY', FLOW: '🏦 FLOW',
  SILENT: '🔇 SILENT', HYPE: '🚀 HYPE', WATCH: '⚡ WATCH',
};

function isPerfectStorm(r) {
  const conditions = [
    r.indicators?.stealth?.is_stealth,
    r.indicators?.institutional_flow?.is_institutional,
    r.sympathy?.is_sympathy,
    ['ARM', 'FIRE', 'STEALTH_ARM'].includes(r.regime?.state),
  ];
  return conditions.filter(Boolean).length >= 2;
}

function isMarketOpen() {
  const now = new Date();
  const day = now.getUTCDay(); // 0=Sun, 6=Sat
  if (day === 0 || day === 6) return false;
  // EST = UTC-5 (ignoring DST for simplicity)
  const estHour = (now.getUTCHours() - 5 + 24) % 24;
  const estMin = now.getUTCMinutes();
  const minutes = estHour * 60 + estMin;
  return minutes >= 9 * 60 + 30 && minutes < 16 * 60;
}

export default function Home() {
  const [scanData, setScanData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('FIRE');
  const [scanning, setScanning] = useState(false);
  const [marketOpen, setMarketOpen] = useState(true);
  const [hypeStatus, setHypeStatus] = useState(null);
  const [hypeResults, setHypeResults] = useState([]);
  const [hypeRunning, setHypeRunning] = useState(false);

  const fetchLatest = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/scan/latest`);
      if (!res.ok) throw new Error(`API error ${res.status}`);
      const data = await res.json();
      setScanData(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchHype = useCallback(async () => {
    try {
      const [statusRes, resultsRes] = await Promise.all([
        fetch(`${API_URL}/api/hype/status`),
        fetch(`${API_URL}/api/hype/results`),
      ]);
      if (statusRes.ok) setHypeStatus(await statusRes.json());
      if (resultsRes.ok) {
        const d = await resultsRes.json();
        setHypeResults(d.results || []);
      }
    } catch {
      // hype monitor is optional — silent fail
    }
  }, []);

  useEffect(() => {
    fetchLatest();
    fetchHype();
    setMarketOpen(isMarketOpen());

    const interval = setInterval(() => {
      fetchLatest();
      fetchHype();
      setMarketOpen(isMarketOpen());
    }, REFRESH_INTERVAL);

    return () => clearInterval(interval);
  }, [fetchLatest, fetchHype]);

  const handleRescan = async () => {
    setScanning(true);
    try {
      await fetch(`${API_URL}/api/scan/run`, { method: 'POST' });
      // Poll for completion — stop as soon as scanned_at changes
      const prevTs = scanData?.scanned_at || null;
      let attempts = 0;
      const poll = setInterval(async () => {
        attempts++;
        const res = await fetch(`${API_URL}/api/scan/latest`);
        if (res.ok) {
          const data = await res.json();
          setScanData(data);
          setError(null);
          if (data.scanned_at && data.scanned_at !== prevTs) {
            clearInterval(poll);
            setScanning(false);
            return;
          }
        }
        if (attempts >= 60) {
          clearInterval(poll);
          setScanning(false);
        }
      }, 5000);
      setTimeout(() => {
        clearInterval(poll);
        setScanning(false);
      }, 5 * 60 * 1000);
    } catch (err) {
      setError(err.message);
      setScanning(false);
    }
  };

  // Filter results by active tab
  const results = scanData?.results || [];
  const sympathyResults = results.filter((r) => r.sympathy?.is_sympathy);
  const flowResults = results.filter((r) => r.indicators?.institutional_flow?.is_institutional);
  const perfectStormResults = results.filter(isPerfectStorm);

  // Hype divergence filters (based on hype monitor results)
  const hypeByTicker = Object.fromEntries(hypeResults.map((r) => [r.ticker, r]));
  const silentVolumeResults = results.filter((r) => {
    const h = hypeByTicker[r.symbol];
    return h?.divergences?.some((d) => d.type === 'SILENT_VOLUME');
  });
  const hypeNoVolumeResults = results.filter((r) => {
    const h = hypeByTicker[r.symbol];
    return h?.divergences?.some((d) => d.type === 'HYPE_NO_VOLUME' || d.type === 'VELOCITY_SPIKE');
  });
  const smartMoneyResults = silentVolumeResults; // alias for banner
  const exitSignalResults = results.filter((r) => {
    const h = hypeByTicker[r.symbol];
    return h?.divergences?.some((d) => d.type === 'PEAK_FADING');
  });

  const filtered =
    activeTab === 'SYMPATHY' ? sympathyResults
    : activeTab === 'FLOW' ? flowResults
    : activeTab === 'SILENT' ? silentVolumeResults
    : activeTab === 'HYPE' ? hypeNoVolumeResults
    : results.filter((r) => r.score?.tier === activeTab);

  // Auto-select first non-empty tab
  useEffect(() => {
    if (!scanData) return;
    const tc = scanData.tier_counts || {};
    for (const tier of TIERS) {
      if (tier === 'SYMPATHY' && sympathyResults.length > 0) { setActiveTab(tier); return; }
      if (['FLOW', 'SILENT', 'HYPE'].includes(tier)) continue;
      if (tc[tier] > 0) { setActiveTab(tier); return; }
    }
  }, [scanData]); // eslint-disable-line react-hooks/exhaustive-deps

  const tierCounts = {
    ...(scanData?.tier_counts || {}),
    SYMPATHY: sympathyResults.length,
    FLOW: flowResults.length,
    SILENT: silentVolumeResults.length,
    HYPE: hypeNoVolumeResults.length,
  };

  return (
    <>
      <Head>
        <title>Pump Scout — Volume Anomaly Scanner</title>
        <meta name="description" content="Small-cap volume anomaly scanner — find quiet accumulation before the pump" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🔍</text></svg>" />
      </Head>

      <div className={styles.container}>
        {/* Header */}
        <header className={styles.header}>
          <div className={styles.logo}>
            <span className={styles.logoIcon}>🔍</span>
            PUMP SCOUT
            <span className={styles.version}>{VERSION}</span>
            <Link href="/how-it-works" className={styles.howLink}>how it works</Link>
            <Link href="/journal" className={styles.howLink}>📔 journal</Link>
          </div>
          <Scanner
            scanData={scanData}
            scanning={scanning}
            onRescan={handleRescan}
            lastUpdated={scanData?.scanned_at}
          />
        </header>

        {/* Market closed banner */}
        {!marketOpen && (
          <div className={styles.marketClosed}>
            MARKET CLOSED — Showing last scan data. Next scan runs at market open.
          </div>
        )}

        {/* Scanning progress banner */}
        {scanning && (
          <div className={styles.scanningBanner}>
            <span className={styles.spinner} /> Scan in progress — fetching ~800 tickers and calculating signals. This takes 2–4 minutes…
          </div>
        )}

        {/* Error */}
        {error && (
          <div className={styles.error}>
            ⚠ Error loading scan data: {error}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className={styles.loading}>
            <div className={styles.loadingSpinner} />
            <div>Loading scan data...</div>
          </div>
        )}

        {/* Hype Monitor status bar */}
        <div className={styles.hypeBar}>
          <span className={styles.hypeBarLabel}>🔮 HYPE MONITOR</span>
          {(hypeStatus?.hot_tickers || []).slice(0, 6).map((t) => (
            <span key={t} className={styles.hypeBarTicker} onClick={() => setActiveTab('SILENT')}>{t}</span>
          ))}
          <span className={styles.hypeBarMeta}>
            {hypeStatus
              ? `${hypeStatus.tickers_monitored} watched · ${hypeStatus.total_divergences} signals${hypeStatus.last_run_at ? ` · ${new Date(hypeStatus.last_run_at).toLocaleTimeString()}` : ''}`
              : 'auto-runs every 30min during market hours'}
          </span>
          <button
            disabled={hypeRunning}
            onClick={async () => {
              setHypeRunning(true);
              await fetch(`${API_URL}/api/hype/run`, { method: 'POST' });
              // Poll for result — hype monitor takes ~15-30s
              let attempts = 0;
              const poll = setInterval(async () => {
                attempts++;
                await fetchHype();
                if (attempts >= 8) {
                  clearInterval(poll);
                  setHypeRunning(false);
                }
              }, 5000);
            }}
            style={{
              marginLeft: 'auto',
              background: hypeRunning ? 'rgba(170,0,255,0.06)' : 'rgba(170,0,255,0.12)',
              border: '1px solid rgba(170,0,255,0.35)',
              color: hypeRunning ? 'rgba(204,68,255,0.5)' : '#cc44ff',
              borderRadius: 4,
              fontSize: 10,
              fontWeight: 700,
              padding: '2px 10px',
              cursor: hypeRunning ? 'not-allowed' : 'pointer',
              letterSpacing: '0.05em',
              whiteSpace: 'nowrap',
              transition: 'all 0.2s',
            }}
          >
            {hypeRunning ? '⏳ SCANNING…' : '▶ RUN HYPE'}
          </button>
        </div>

        {/* Smart Money (SILENT_VOLUME) banner */}
        {!loading && smartMoneyResults.length > 0 && (
          <div className={styles.smartMoneyBanner}>
            <span className={styles.smartMoneyLabel}>💰 SMART MONEY</span>
            {smartMoneyResults.map((r) => (
              <span key={r.symbol} className={styles.smartMoneyTicker}>{r.symbol}</span>
            ))}
            <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 4 }}>
              High vol, low social hype
            </span>
          </div>
        )}

        {/* Exit Signals (PEAK_FADING) banner */}
        {!loading && exitSignalResults.length > 0 && (
          <div className={styles.exitBanner}>
            <span className={styles.exitBannerLabel}>🚨 EXIT SIGNALS</span>
            {exitSignalResults.map((r) => (
              <span key={r.symbol} className={styles.exitBannerTicker}>{r.symbol}</span>
            ))}
            <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 4 }}>
              Hype fading, price not moved
            </span>
          </div>
        )}

        {/* Perfect Storm banner */}
        {!loading && perfectStormResults.length > 0 && (
          <div className={styles.perfectStorm}>
            <span className={styles.perfectStormLabel}>⚡ PERFECT STORM</span>
            {perfectStormResults.map((r) => (
              <span key={r.symbol} className={styles.perfectStormTicker}>{r.symbol}</span>
            ))}
          </div>
        )}

        {/* Tabs */}
        {!loading && (
          <>
            <div className={styles.tabs}>
              {TIERS.map((tier) => (
                <button
                  key={tier}
                  className={[
                    styles.tab,
                    styles[`tab${tier.charAt(0) + tier.slice(1).toLowerCase()}`] || '',
                    activeTab === tier ? styles.tabActive : '',
                  ].join(' ')}
                  onClick={() => setActiveTab(tier)}
                >
                  {TIER_LABELS[tier]}
                  {tierCounts[tier] > 0 && (
                    <span style={{ marginLeft: 6, opacity: 0.7 }}>({tierCounts[tier]})</span>
                  )}
                </button>
              ))}
            </div>

            {/* Grid */}
            {filtered.length > 0 ? (
              <div className={`${styles.grid} fade-in`}>
                {filtered.map((ticker) => (
                  <TickerCard key={ticker.symbol} data={ticker} hypeData={hypeByTicker[ticker.symbol]} />
                ))}
              </div>
            ) : (
              <div className={styles.empty}>
                <span className={styles.emptyIcon}>📭</span>
                {results.length === 0 ? (
                  <>
                    No scan data yet.{' '}
                    <button
                      onClick={handleRescan}
                      disabled={scanning}
                      style={{
                        background: 'var(--fire)',
                        color: '#fff',
                        border: 'none',
                        borderRadius: 6,
                        padding: '4px 12px',
                        cursor: scanning ? 'not-allowed' : 'pointer',
                        fontWeight: 700,
                      }}
                    >
                      {scanning ? '⏳ Scanning…' : '▶ SCAN NOW'}
                    </button>
                  </>
                ) : (
                  `No ${activeTab} tier tickers in the latest scan.`
                )}
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}
