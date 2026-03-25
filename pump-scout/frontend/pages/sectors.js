import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import MarketRegimeBanner from '../components/MarketRegimeBanner';
import styles from '../styles/Sectors.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function fmt(val, plus = true) {
  if (val == null) return '—';
  const sign = val >= 0 && plus ? '+' : '';
  return `${sign}${Number(val).toFixed(1)}%`;
}

function EtfBox({ symbol, pct }) {
  const color = pct > 0.5 ? '#00c864' : pct < -0.5 ? '#ff4466' : '#ff8800';
  const bg = pct > 0.5
    ? 'rgba(0,200,100,0.08)'
    : pct < -0.5 ? 'rgba(255,68,102,0.08)' : 'rgba(255,136,0,0.06)';
  return (
    <div className={styles.etfBox} style={{ background: bg, borderColor: color + '44' }}>
      <span className={styles.etfSymbol}>{symbol}</span>
      <span className={styles.etfPct} style={{ color }}>{fmt(pct)}</span>
    </div>
  );
}

export default function Sectors() {
  const [regime, setRegime] = useState(null);
  const [sectors, setSectors] = useState([]);
  const [selectedSector, setSelectedSector] = useState(null);
  const [sectorDetail, setSectorDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [regRes, secRes] = await Promise.all([
        fetch(`${API_URL}/api/market-regime`),
        fetch(`${API_URL}/api/sector-strength`),
      ]);
      if (regRes.ok) setRegime(await regRes.json());
      if (secRes.ok) {
        const d = await secRes.json();
        setSectors(d.sectors || []);
      }
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const loadSectorDetail = useCallback(async (sector) => {
    if (selectedSector === sector) {
      setSelectedSector(null);
      setSectorDetail(null);
      return;
    }
    setSelectedSector(sector);
    setLoadingDetail(true);
    try {
      const res = await fetch(`${API_URL}/api/sector-strength/${encodeURIComponent(sector)}`);
      if (res.ok) setSectorDetail(await res.json());
    } catch { /* silent */ }
    finally { setLoadingDetail(false); }
  }, [selectedSector]);

  const maxScore = Math.max(...sectors.map(s => s.avg_score || 0), 1);
  const etf = regime?.etf_details || {};

  return (
    <>
      <Head>
        <title>Pump Scout — Sectors</title>
      </Head>

      <div className={styles.container}>
        <header className={styles.header}>
          <Link href="/" className={styles.back}>← Scanner</Link>
          <h1 className={styles.title}>🗂 Sector Intelligence</h1>
        </header>

        {/* Market Regime */}
        {regime && <MarketRegimeBanner regime={regime} />}

        {/* ETF Heatmap */}
        {regime && (
          <div className={styles.etfGrid}>
            <EtfBox symbol="SPY" pct={etf.SPY?.pct_1d ?? regime.spy_pct} />
            <EtfBox symbol="QQQ" pct={etf.QQQ?.pct_1d ?? regime.qqq_pct} />
            <EtfBox symbol="XLE" pct={etf.XLE?.pct_1d ?? regime.xle_pct} />
            <EtfBox symbol="XLV" pct={etf.XLV?.pct_1d ?? regime.xlv_pct} />
            <EtfBox symbol="XLU" pct={etf.XLU?.pct_1d ?? regime.xlu_pct} />
            <EtfBox symbol="GLD" pct={etf.GLD?.pct_1d ?? regime.gld_pct} />
          </div>
        )}

        {/* Sector Table */}
        {loading ? (
          <div className={styles.loading}>Loading sector data…</div>
        ) : sectors.length === 0 ? (
          <div className={styles.empty}>No sector data yet. Run a scan first.</div>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Sector</th>
                  <th>Score</th>
                  <th>CMF</th>
                  <th>Momentum</th>
                  <th>Leader</th>
                  <th>Tickers</th>
                </tr>
              </thead>
              <tbody>
                {sectors.map(s => {
                  const pct = Math.round((s.avg_score / maxScore) * 100);
                  const isWeak = regime?.weak_sectors?.includes(s.sector);
                  const isStrong = regime?.strong_sectors?.includes(s.sector);
                  const isSelected = selectedSector === s.sector;
                  return (
                    <>
                      <tr
                        key={s.sector}
                        className={`${styles.row} ${isSelected ? styles.rowSelected : ''}`}
                        onClick={() => loadSectorDetail(s.sector)}
                      >
                        <td className={styles.sectorName}>
                          {s.sector}
                          {isStrong && <span className={styles.strongTag}>💪</span>}
                          {isWeak && <span className={styles.weakTag}>⚠</span>}
                        </td>
                        <td>
                          <div className={styles.scoreCell}>
                            <div className={styles.scoreBar} style={{ width: `${pct}%` }} />
                            <span>{(s.avg_score || 0).toFixed(0)}</span>
                          </div>
                        </td>
                        <td>{s.avg_cmf_pctl != null ? `${s.avg_cmf_pctl.toFixed(0)}%ile` : '—'}</td>
                        <td style={{ color: (s.momentum_pct || 0) >= 0 ? '#00c864' : '#ff4466' }}>
                          {fmt(s.momentum_pct)}
                        </td>
                        <td className={styles.leader}>{s.leader_symbol || '—'}</td>
                        <td style={{ color: 'var(--text-muted)' }}>{s.ticker_count || 0}</td>
                      </tr>
                      {isSelected && (
                        <tr key={`${s.sector}-detail`}>
                          <td colSpan={6} className={styles.detailCell}>
                            {loadingDetail ? (
                              <div className={styles.detailLoading}>Loading…</div>
                            ) : sectorDetail ? (
                              <div className={styles.tickerGrid}>
                                {(sectorDetail.tickers_detail || []).map(t => (
                                  <div key={t.symbol} className={styles.tickerRow}>
                                    <span className={styles.tickerSym}>{t.symbol}</span>
                                    <span className={styles.tickerTier}>{t.tier}</span>
                                    <span className={styles.tickerScore}>{t.score?.toFixed(0)}</span>
                                    <span style={{ color: (t.price_change_pct || 0) >= 0 ? '#00c864' : '#ff4466', fontSize: 10 }}>
                                      {fmt(t.price_change_pct)}
                                    </span>
                                    <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                                      CMF {t.cmf_pctl?.toFixed(0)}%ile
                                    </span>
                                    {t.sympathy?.is_sympathy && (
                                      <span className={styles.sympathyTag}>
                                        🔗 lag {t.sympathy.lag_pct?.toFixed(1)}%
                                      </span>
                                    )}
                                  </div>
                                ))}
                                {(sectorDetail.tickers_detail || []).length === 0 && (
                                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                    No tickers with detail in this sector from the latest scan.
                                  </span>
                                )}
                              </div>
                            ) : null}
                          </td>
                        </tr>
                      )}
                    </>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        <div className={styles.footer}>
          <button className={styles.refreshBtn} onClick={fetchData}>⟳ Refresh</button>
          <span className={styles.footerNote}>Sector data updates after each scan · Regime detects at 7:55 AM ET</span>
        </div>
      </div>
    </>
  );
}
