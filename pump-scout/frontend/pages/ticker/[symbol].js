import { useRouter } from 'next/router';
import { useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import AIAnalysis from '../../components/AIAnalysis';
import styles from '../../styles/Ticker.module.css';

const Chart = dynamic(() => import('../../components/Chart'), { ssr: false });

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

const TIER_EMOJI = { FIRE: '🔥', ARM: '👁', BASE: '📦', WATCH: '⚡' };

function getBadgeClass(tier) {
  const map = {
    FIRE: styles.badgeFire,
    ARM: styles.badgeArm,
    BASE: styles.badgeBase,
    WATCH: styles.badgeWatch,
  };
  return map[tier] || styles.badgeNone;
}

function StatBox({ label, value, sub, color }) {
  const colorClass = color ? styles[`statValue${color}`] : '';
  return (
    <div className={styles.statBox}>
      <div className={styles.statLabel}>{label}</div>
      <div className={`${styles.statValue} ${colorClass}`}>{value}</div>
      {sub && <div className={styles.statSub}>{sub}</div>}
    </div>
  );
}

function formatVol(v) {
  if (!v) return '—';
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M';
  if (v >= 1_000) return (v / 1_000).toFixed(0) + 'K';
  return String(v);
}

export default function TickerPage() {
  const router = useRouter();
  const { symbol } = router.query;

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [notes, setNotes] = useState('');
  const [notesSaved, setNotesSaved] = useState(false);

  useEffect(() => {
    if (!symbol) return;

    const fetchTicker = async () => {
      setLoading(true);
      try {
        const res = await fetch(`${API_URL}/api/ticker/${symbol}`);
        if (!res.ok) throw new Error(`${symbol} not found (${res.status})`);
        const json = await res.json();
        setData(json);
        setError(null);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchTicker();
  }, [symbol]);

  const handleSaveNotes = async () => {
    if (!symbol) return;
    try {
      await fetch(`${API_URL}/api/watchlist/${symbol}?notes=${encodeURIComponent(notes)}`, {
        method: 'POST',
      });
      setNotesSaved(true);
      setTimeout(() => setNotesSaved(false), 2000);
    } catch {
      // Silent fail
    }
  };

  if (loading) {
    return (
      <div className={styles.container}>
        <div className={styles.loading}>
          <div className={styles.loadingSpinner} />
          <div>Loading {symbol}...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={styles.container}>
        <nav className={styles.nav}>
          <Link href="/" className={styles.backLink}>← Back</Link>
        </nav>
        <div className={styles.error}>⚠ {error}</div>
      </div>
    );
  }

  if (!data) return null;

  const { indicators = {}, regime = {}, score = {}, candles, ai_analysis } = data;
  const tier = score.tier || 'WATCH';
  const priceChangePct = indicators.price_change_pct || 0;
  const priceSign = priceChangePct >= 0 ? '+' : '';
  const priceClass = priceChangePct >= 0.5 ? styles.priceUp : priceChangePct <= -0.5 ? styles.priceDown : '';

  return (
    <>
      <Head>
        <title>{symbol} — Pump Scout</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>

      <div className={styles.container}>
        {/* Nav */}
        <nav className={styles.nav}>
          <Link href="/" className={styles.backLink}>
            ← Dashboard
          </Link>
          <span className={styles.navSymbol}>{symbol}</span>
        </nav>

        {/* Hero */}
        <div className={styles.hero}>
          <div className={styles.heroLeft}>
            <div className={styles.symbolTitle}>{symbol}</div>
            <div className={styles.priceRow}>
              <span className={styles.price}>${data.price?.toFixed(2) ?? '—'}</span>
              <span className={`${styles.priceChange} ${priceClass}`}>
                {priceSign}{priceChangePct.toFixed(2)}%
              </span>
            </div>
          </div>
          <div className={styles.heroRight}>
            <span className={`${styles.badge} ${getBadgeClass(tier)}`}>
              {TIER_EMOJI[tier]} {tier}
            </span>
            <div className={styles.scoreRow}>
              Score: <span className={styles.scoreValue}>{score.total_score?.toFixed(0) ?? 0}</span>
              /100
            </div>
          </div>
        </div>

        {/* Chart */}
        <div className={styles.section}>
          <div className={styles.sectionTitle}>PRICE CHART (LAST 100 BARS)</div>
          {candles && candles.length > 0 ? (
            <Chart
              candles={candles}
              bbData={{ upper: indicators.bb_upper, lower: indicators.bb_lower }}
              ema50={indicators.ema50}
            />
          ) : (
            <div style={{ color: 'var(--text-muted)', padding: '20px', fontSize: 12 }}>
              No chart data available
            </div>
          )}
        </div>

        {/* Volume Stats */}
        <div className={styles.section}>
          <div className={styles.sectionTitle}>VOLUME ANALYSIS</div>
          <div className={styles.grid3}>
            <StatBox
              label="VOL ANOMALY"
              value={`${indicators.anomaly_ratio?.toFixed(1) ?? '0'}x`}
              sub={`Today: ${formatVol(indicators.today_vol)}`}
              color={indicators.anomaly_ratio >= 5 ? 'Gold' : indicators.anomaly_ratio >= 2 ? 'Cyan' : null}
            />
            <StatBox
              label="VOL Z-SCORE"
              value={indicators.vol_z?.toFixed(1) ?? '0'}
              sub={`Avg 20d: ${formatVol(indicators.avg_vol_20)}`}
              color={indicators.vol_z >= 2 ? 'Green' : null}
            />
            <StatBox
              label="QUIET FACTOR"
              value={`${score.quiet_factor?.toFixed(1) ?? '1.0'}x`}
              sub={indicators.is_quiet ? 'Quiet accumulation ✓' : 'Price moving with vol'}
              color={indicators.is_quiet ? 'Green' : null}
            />
          </div>
        </div>

        {/* Indicators */}
        <div className={styles.section}>
          <div className={styles.sectionTitle}>TECHNICAL INDICATORS</div>
          <div className={styles.grid3}>
            <StatBox
              label="BB SQUEEZE"
              value={`${indicators.bb_sqz_bars ?? 0} bars`}
              sub={indicators.bb_squeeze ? 'In squeeze ✓' : 'Not squeezing'}
              color={indicators.bb_sqz_bars >= 5 ? 'Cyan' : null}
            />
            <StatBox
              label="BB WIDTH %ILE"
              value={`${indicators.bb_pctl?.toFixed(0) ?? 50}th`}
              sub={indicators.bb_pctl < 25 ? 'Tight (squeeze zone)' : 'Normal range'}
              color={indicators.bb_pctl < 25 ? 'Cyan' : null}
            />
            <StatBox
              label="CMF"
              value={indicators.cmf?.toFixed(3) ?? '0.000'}
              sub={`${indicators.cmf_pctl?.toFixed(0) ?? 50}th percentile`}
              color={indicators.cmf > 0.1 ? 'Green' : indicators.cmf < -0.1 ? 'Red' : null}
            />
            <StatBox
              label="EMA 20"
              value={`$${indicators.ema20?.toFixed(2) ?? '—'}`}
              sub={indicators.above_ema20 ? 'Price above ✓' : 'Price below'}
              color={indicators.above_ema20 ? 'Green' : 'Red'}
            />
            <StatBox
              label="EMA 50"
              value={`$${indicators.ema50?.toFixed(2) ?? '—'}`}
              sub={indicators.above_ema50 ? 'Price above ✓' : 'Price below'}
              color={indicators.above_ema50 ? 'Green' : 'Red'}
            />
            <StatBox
              label="ATR"
              value={`${indicators.atr_pct?.toFixed(1) ?? '0'}%`}
              sub={`$${indicators.atr?.toFixed(3) ?? '0'} · ratio ${indicators.atr_ratio?.toFixed(2) ?? '1'}`}
            />
          </div>
        </div>

        {/* Wyckoff Regime */}
        <div className={styles.section}>
          <div className={styles.sectionTitle}>WYCKOFF REGIME</div>
          <div className={styles.grid2}>
            <StatBox
              label="STATE"
              value={regime.state || 'NONE'}
              sub={`Confidence: ${regime.confidence ?? 0}%`}
              color={regime.state === 'FIRE' ? 'Gold' : regime.state === 'ARM' ? 'Cyan' : regime.state === 'BASE' ? 'Green' : null}
            />
            <StatBox
              label="TR HIGH / LOW"
              value={`$${regime.tr_high?.toFixed(2) ?? '—'} / $${regime.tr_low?.toFixed(2) ?? '—'}`}
              sub={`Mid: $${regime.tr_mid?.toFixed(2) ?? '—'}`}
              color="Gold"
            />
            <StatBox
              label="ACCUMULATION"
              value={regime.in_acc ? 'YES' : 'NO'}
              sub={regime.sc ? 'SC detected' : 'No SC detected'}
              color={regime.in_acc ? 'Green' : null}
            />
            <StatBox
              label="DISTRIBUTION"
              value={regime.in_dist ? 'YES' : 'NO'}
              sub={regime.bc ? 'BC detected' : 'No BC detected'}
              color={regime.in_dist ? 'Orange' : null}
            />
          </div>
        </div>

        {/* Score Breakdown */}
        <div className={styles.section}>
          <div className={styles.sectionTitle}>SCORE BREAKDOWN</div>
          <div className={styles.grid3}>
            <StatBox label="VOL SCORE" value={score.vol_score ?? 0} sub="Volume anomaly component" color="Cyan" />
            <StatBox label="ACCUM SCORE" value={score.accum_score ?? 0} sub="Accumulation component" color="Green" />
            <StatBox label="TOTAL SCORE" value={score.total_score?.toFixed(1) ?? 0} sub={`Tier: ${tier}`} color="Gold" />
          </div>
        </div>

        {/* AI Analysis */}
        <div className={styles.section}>
          <div className={styles.sectionTitle}>AI ANALYSIS (CLAUDE)</div>
          <AIAnalysis analysis={ai_analysis} loading={false} />
        </div>

        {/* Watchlist Notes */}
        <div className={styles.section}>
          <div className={styles.notesBox}>
            <div className={styles.notesTitle}>WATCHLIST NOTES</div>
            <textarea
              className={styles.notesTextarea}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add notes about this setup..."
            />
            <button className={styles.notesBtn} onClick={handleSaveNotes}>
              {notesSaved ? '✓ Saved' : 'Save to Watchlist'}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
