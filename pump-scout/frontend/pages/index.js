import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import TickerCard from '../components/TickerCard';
import Scanner from '../components/Scanner';
import MarketRegimeBanner from '../components/MarketRegimeBanner';
import SectorStrengthBar from '../components/SectorStrengthBar';
import SectorBar from '../components/SectorBar';
import styles from '../styles/Home.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REFRESH_INTERVAL = 60 * 1000; // 60 seconds
const VERSION = 'v20.0';
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

function getEtOffset(now) {
  const year = now.getUTCFullYear();
  const dstStart = (() => {
    const d = new Date(Date.UTC(year, 2, 1));
    const secondSun = 1 + (7 - d.getUTCDay()) % 7 + 7;
    return new Date(Date.UTC(year, 2, secondSun, 7)); // 2am EST = 7am UTC
  })();
  const dstEnd = (() => {
    const d = new Date(Date.UTC(year, 10, 1));
    const firstSun = 1 + (7 - d.getUTCDay()) % 7;
    return new Date(Date.UTC(year, 10, firstSun, 6)); // 2am EDT = 6am UTC
  })();
  return now >= dstStart && now < dstEnd ? 4 : 5;
}

function isMarketOpen() {
  const now = new Date();
  const day = now.getUTCDay();
  if (day === 0 || day === 6) return false;
  const offsetHours = getEtOffset(now);
  const etMinutes = (now.getUTCHours() * 60 + now.getUTCMinutes() - offsetHours * 60 + 1440) % 1440;
  return etMinutes >= 9 * 60 + 30 && etMinutes < 16 * 60;
}

function getMarketCountdown() {
  const now = new Date();
  const offsetHours = getEtOffset(now);
  const offsetMs = offsetHours * 60 * 60 * 1000;
  const etNow = new Date(now.getTime() - offsetMs);
  const day = etNow.getUTCDay();

  // Market open/close in ET minutes from midnight
  const OPEN = 9 * 60 + 30;
  const CLOSE = 16 * 60;
  const etMinutes = etNow.getUTCHours() * 60 + etNow.getUTCMinutes();
  const etSeconds = etNow.getUTCSeconds();

  const isWeekend = day === 0 || day === 6;
  const open = !isWeekend && etMinutes >= OPEN && etMinutes < CLOSE;

  let targetMs;
  if (open) {
    // Time until close today
    const closeMs = new Date(Date.UTC(
      etNow.getUTCFullYear(), etNow.getUTCMonth(), etNow.getUTCDate(),
      16, 0, 0
    )).getTime() + offsetMs;
    targetMs = closeMs - now.getTime();
  } else {
    // Time until next open (Mon-Fri 9:30 ET)
    let daysUntilOpen = 0;
    if (!isWeekend && etMinutes < OPEN) {
      daysUntilOpen = 0;
    } else {
      // find next weekday
      let d = day;
      do {
        daysUntilOpen++;
        d = (d + 1) % 7;
      } while (d === 0 || d === 6);
    }
    const openMs = new Date(Date.UTC(
      etNow.getUTCFullYear(), etNow.getUTCMonth(), etNow.getUTCDate() + daysUntilOpen,
      9, 30, 0
    )).getTime() + offsetMs;
    targetMs = openMs - now.getTime();
  }

  const totalSec = Math.max(0, Math.floor(targetMs / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  const pad = n => String(n).padStart(2, '0');
  return { open, label: `${pad(h)}:${pad(m)}:${pad(s)}` };
}

export default function Home() {
  const [scanData, setScanData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [activeTab, setActiveTab] = useState('FIRE');
  const [scanning, setScanning] = useState(false);
  const [marketOpen, setMarketOpen] = useState(true);
  const [marketTimer, setMarketTimer] = useState({ open: true, label: '00:00:00' });
  const [marketRegime, setMarketRegime] = useState(null);
  const [sectorStrength, setSectorStrength] = useState([]);
  const [sectorFilter, setSectorFilter] = useState(null);
  const [hypeStatus, setHypeStatus] = useState(null);
  const [hypeResults, setHypeResults] = useState([]);
  const [hypeRunning, setHypeRunning] = useState(false);
  const [streaks, setStreaks] = useState([]);
  const [sectorPerf, setSectorPerf] = useState({});

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

  const fetchRegime = useCallback(async () => {
    try {
      const [regimeRes, strengthRes, perfRes] = await Promise.all([
        fetch(`${API_URL}/api/market-regime`),
        fetch(`${API_URL}/api/sector-strength`),
        fetch(`${API_URL}/api/sector-performance/latest`),
      ]);
      if (regimeRes.ok) setMarketRegime(await regimeRes.json());
      if (strengthRes.ok) {
        const d = await strengthRes.json();
        setSectorStrength(d.sectors || []);
      }
      if (perfRes.ok) setSectorPerf(await perfRes.json());
    } catch {
      // regime is optional — silent fail
    }
  }, []);

  const fetchStreaks = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/streaks/active?min_days=2`);
      if (res.ok) {
        const d = await res.json();
        setStreaks(d.streaks || []);
      }
    } catch {
      // streaks are optional — silent fail
    }
  }, []);

  useEffect(() => {
    fetchLatest();
    fetchHype();
    fetchRegime();
    fetchStreaks();
    setMarketOpen(isMarketOpen());

    const interval = setInterval(() => {
      fetchLatest();
      fetchHype();
      fetchRegime();
      fetchStreaks();
      setMarketOpen(isMarketOpen());
    }, REFRESH_INTERVAL);

    return () => clearInterval(interval);
  }, [fetchLatest, fetchHype, fetchRegime, fetchStreaks]);

  useEffect(() => {
    const tick = () => {
      const t = getMarketCountdown();
      setMarketTimer(t);
      setMarketOpen(t.open);
    };
    tick();
    const timer = setInterval(tick, 1000);
    return () => clearInterval(timer);
  }, []);

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

  // Streak lookup by symbol
  const streakBySymbol = Object.fromEntries(streaks.map((s) => [s.symbol, s.streak_days]));
  const highStreakResults = streaks.filter((s) => s.streak_days >= 3);
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

  const filteredBase =
    activeTab === 'SYMPATHY' ? sympathyResults
    : activeTab === 'FLOW' ? flowResults
    : activeTab === 'SILENT' ? silentVolumeResults
    : activeTab === 'HYPE' ? hypeNoVolumeResults
    : results.filter((r) => r.score?.tier === activeTab);

  const filtered = sectorFilter
    ? filteredBase.filter((r) => r.sector === sectorFilter)
    : filteredBase;

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

  // Download current tab's tickers as TradingView watchlist .txt
  const downloadWatchlist = () => {
    if (filtered.length === 0) return;
    const tabLabel = TIER_LABELS[activeTab]?.replace(/[^A-Z]/g, '') || activeTab;
    const date = new Date().toISOString().slice(0, 10);
    const lines = filtered.map((r) => r.symbol).join('\n');
    const blob = new Blob([lines], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pump-scout-${tabLabel.toLowerCase()}-${date}.txt`;
    a.click();
    URL.revokeObjectURL(url);
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
            <Link href="/sectors" className={styles.howLink}>🗂 sectors</Link>
            <button
              className={styles.eodLogBtn}
              onClick={() => window.open(`${API_URL}/api/eod-log/latest`, '_blank')}
              title="Download today's end-of-day log for Claude analysis"
            >
              📋 EOD Log
            </button>
          </div>
          <Scanner
            scanData={scanData}
            scanning={scanning}
            onRescan={handleRescan}
            lastUpdated={scanData?.scanned_at}
          />
        </header>

        {/* Market status banner */}
        <div className={marketOpen ? styles.marketOpen : styles.marketClosed}>
          {marketOpen
            ? `MARKET OPEN — Closes in ${marketTimer.label}`
            : `MARKET CLOSED — Opens in ${marketTimer.label}. Showing last scan data.`}
        </div>

        {/* Market Regime Banner */}
        {marketRegime && <MarketRegimeBanner regime={marketRegime} />}

        {/* Live Sector Performance Bar (Finviz) */}
        {Object.keys(sectorPerf).length > 0 && <SectorBar data={sectorPerf} />}

        {/* Sector Strength Bar (scan-based) */}
        {sectorStrength.length > 0 && (
          <SectorStrengthBar
            sectors={sectorStrength}
            onSectorClick={setSectorFilter}
            activeFilter={sectorFilter}
          />
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

        {/* Pattern Streaks banner */}
        {!loading && highStreakResults.length > 0 && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
            padding: '6px 12px', marginBottom: 4,
            background: 'rgba(255,215,0,0.05)',
            border: '1px solid rgba(255,215,0,0.18)',
            borderRadius: 6, fontSize: 11,
          }}>
            <span style={{ fontWeight: 700, color: '#ffd700', whiteSpace: 'nowrap' }}>
              🔁 STREAKS
            </span>
            {highStreakResults.map((s) => (
              <span
                key={s.symbol}
                title={`${s.streak_days}-day streak | avg score ${s.avg_score} | ${s.tier}`}
                style={{
                  color: s.streak_days >= 5 ? '#ff4466' : '#ffd700',
                  fontWeight: 700, cursor: 'default',
                }}
              >
                {s.symbol}
                <span style={{ color: 'rgba(255,255,255,0.4)', fontWeight: 400, marginLeft: 2 }}>
                  ×{s.streak_days}
                </span>
              </span>
            ))}
            <span style={{ fontSize: 10, color: 'rgba(255,255,255,0.35)', marginLeft: 4 }}>
              ARM+ сигнал несколько дней подряд
            </span>
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
              {filtered.length > 0 && (
                <button
                  className={styles.tvDownload}
                  onClick={downloadWatchlist}
                  title={`Download ${filtered.length} tickers as TradingView watchlist`}
                >
                  ⬇ TV ({filtered.length})
                </button>
              )}
            </div>

            {/* Grid — Sympathy tab shows grouped by sector */}
            {filtered.length > 0 ? (
              activeTab === 'SYMPATHY' ? (
                <div className="fade-in">
                  {Object.entries(
                    filtered.reduce((acc, r) => {
                      const s = r.sector || 'Unknown';
                      if (!acc[s]) acc[s] = [];
                      acc[s].push(r);
                      return acc;
                    }, {})
                  )
                  .sort(([, a], [, b]) => b[0].sympathy?.sympathy_score - a[0].sympathy?.sympathy_score)
                  .map(([sector, tickers]) => {
                    const leader = tickers[0]?.sympathy?.leader || tickers[0]?.sympathy?.leaders?.[0];
                    const leaderScore = tickers[0]?.sympathy?.leader_score;
                    const leaderChange = tickers[0]?.sympathy?.leader_change_pct ?? tickers[0]?.sympathy?.leader_change;
                    return (
                      <div key={sector} style={{ marginBottom: 20 }}>
                        <div style={{ fontSize: 11, fontWeight: 700, color: '#4488ff', padding: '6px 0 4px', borderBottom: '1px solid rgba(68,136,255,0.2)', marginBottom: 8 }}>
                          {sector}
                          {leader && <span style={{ color: 'var(--text-muted)', fontWeight: 400, marginLeft: 10 }}>
                            Лидер: {leader}{leaderScore != null ? ` · score ${leaderScore.toFixed(0)}` : ''}{leaderChange != null ? ` · ${leaderChange >= 0 ? '+' : ''}${leaderChange.toFixed(1)}%` : ''}
                          </span>}
                        </div>
                        <div className={styles.grid}>
                          {tickers.map(ticker => (
                            <TickerCard key={ticker.symbol} data={ticker} hypeData={hypeByTicker[ticker.symbol]} streakDays={streakBySymbol[ticker.symbol] || 0} />
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
              <div className={`${styles.grid} fade-in`}>
                {filtered.map((ticker) => (
                  <TickerCard key={ticker.symbol} data={ticker} hypeData={hypeByTicker[ticker.symbol]} streakDays={streakBySymbol[ticker.symbol] || 0} />
                ))}
              </div>
              )
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
