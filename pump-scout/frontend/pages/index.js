import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import TickerCard from '../components/TickerCard';
import Scanner from '../components/Scanner';
import styles from '../styles/Home.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REFRESH_INTERVAL = 60 * 1000; // 60 seconds
const VERSION = 'v3.3';
const TIERS = ['FIRE', 'ARM', 'BASE', 'STEALTH', 'WATCH', 'GOGA'];
const TIER_LABELS = { FIRE: '🔥 FIRE', ARM: '👁 ARM', BASE: '📦 BASE', STEALTH: '🕵 STEALTH', WATCH: '⚡ WATCH', GOGA: '🐂 GOGA' };

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

  useEffect(() => {
    fetchLatest();
    setMarketOpen(isMarketOpen());

    const interval = setInterval(() => {
      fetchLatest();
      setMarketOpen(isMarketOpen());
    }, REFRESH_INTERVAL);

    return () => clearInterval(interval);
  }, [fetchLatest]);

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
  const gogaResults = results.filter((r) => (r.indicators?.stealth?.vol_ratio ?? 0) >= 2.0);
  const filtered = activeTab === 'GOGA'
    ? gogaResults
    : results.filter((r) => r.score?.tier === activeTab);

  // Auto-select first non-empty tab
  useEffect(() => {
    if (!scanData) return;
    const tierCounts = scanData.tier_counts || {};
    for (const tier of TIERS) {
      if (tier === 'GOGA') continue; // skip GOGA in auto-select
      if (tierCounts[tier] > 0) {
        setActiveTab(tier);
        break;
      }
    }
  }, [scanData]);

  const tierCounts = { ...(scanData?.tier_counts || {}), GOGA: gogaResults.length };

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
                  <TickerCard key={ticker.symbol} data={ticker} />
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
