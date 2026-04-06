import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import styles from '../styles/Sectors.module.css';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function fmt(val, plus = true) {
  if (val == null) return '—';
  const sign = val >= 0 && plus ? '+' : '';
  return `${sign}${Number(val).toFixed(1)}%`;
}

function pctColor(v) {
  if (v == null) return 'var(--text-muted)';
  if (v > 0.5) return '#00c864';
  if (v > 0) return '#69f0ae';
  if (v < -1.5) return '#ff4466';
  if (v < 0) return '#ff8866';
  return '#ffd740';
}

const CLASS_COLOR = { A: '#00c864', B: '#69f0ae', C: '#ffd740', D: '#ff8866', F: '#ff4466' };
const CLASS_BG    = { A: 'rgba(0,200,100,0.12)', B: 'rgba(105,240,174,0.08)', C: 'rgba(255,215,64,0.08)', D: 'rgba(255,136,102,0.08)', F: 'rgba(255,68,102,0.12)' };

const CYCLE_EMOJI = {
  RISK_ON_GROWTH: '🚀', LATE_CYCLE: '⚡', STAGFLATION: '⚠️',
  RISK_OFF: '🛡', FEAR: '😱', NEUTRAL: '😐',
};
const CYCLE_COLOR = {
  RISK_ON_GROWTH: '#00c864', LATE_CYCLE: '#ffd740', STAGFLATION: '#ff8800',
  RISK_OFF: '#4488ff', FEAR: '#ff4466', NEUTRAL: 'rgba(255,255,255,0.5)',
};
const REGIME_COLOR = {
  RISK_ON: '#00c864', NEUTRAL: '#ffd740', RISK_OFF: '#ff8800', FEAR: '#ff4466',
};

const SC_EMOJI  = { LEADING: '🔺', LAGGING: '🔻', NEUTRAL: '⚪' };
const SC_COLOR  = { LEADING: '#00c864', LAGGING: '#ff4466', NEUTRAL: 'rgba(255,255,255,0.4)' };

const RETENTION_ICON = { RETAINING: '✅', RECOVERING: '🔄', FADING: '⚠️', NEUTRAL: '' };

function EtfBox({ symbol, pct, label }) {
  const color = pct > 0.5 ? '#00c864' : pct < -0.5 ? '#ff4466' : pct > 0 ? '#69f0ae' : '#ff8866';
  const bg    = pct > 0.5
    ? 'rgba(0,200,100,0.08)' : pct < -0.5 ? 'rgba(255,68,102,0.08)'
    : pct > 0 ? 'rgba(105,240,174,0.05)' : 'rgba(255,136,102,0.05)';
  return (
    <div className={styles.etfBox} style={{ background: bg, borderColor: color + '40' }}>
      <span className={styles.etfSymbol}>{symbol}</span>
      {label && <span className={styles.etfLabel}>{label}</span>}
      <span className={styles.etfPct} style={{ color }}>{fmt(pct)}</span>
    </div>
  );
}

function ClassBadge({ cls }) {
  if (!cls) return null;
  return (
    <span style={{
      fontSize: 9, fontWeight: 800, letterSpacing: '0.04em',
      background: CLASS_BG[cls] || 'rgba(255,255,255,0.06)',
      color: CLASS_COLOR[cls] || '#888',
      border: `1px solid ${CLASS_COLOR[cls] || '#888'}44`,
      borderRadius: 3, padding: '1px 5px',
    }}>{cls}</span>
  );
}

function SectorClassBar({ classData }) {
  // classData: { A, B, C, D, F } counts or list of sector classes
  const grades = ['A', 'B', 'C', 'D', 'F'];
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
      {grades.map(g => classData[g] != null && (
        <span key={g} style={{
          fontSize: 9, fontWeight: 700,
          background: CLASS_BG[g], color: CLASS_COLOR[g],
          border: `1px solid ${CLASS_COLOR[g]}44`,
          borderRadius: 3, padding: '1px 6px',
        }}>{g}: {classData[g]}</span>
      ))}
    </div>
  );
}

export default function Sectors() {
  const [regime, setRegime]             = useState(null);
  const [sectors, setSectors]           = useState([]);
  const [momentum, setMomentum]         = useState({});
  const [selectedSector, setSelectedSector] = useState(null);
  const [sectorDetail, setSectorDetail] = useState(null);
  const [loading, setLoading]           = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [lastUpdated, setLastUpdated]   = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [regRes, secRes, momRes] = await Promise.all([
        fetch(`${API_URL}/api/market-regime`),
        fetch(`${API_URL}/api/sector-strength`),
        fetch(`${API_URL}/api/sector-momentum`),
      ]);
      if (regRes.ok) setRegime(await regRes.json());
      if (secRes.ok) {
        const d = await secRes.json();
        setSectors(d.sectors || []);
      }
      if (momRes.ok) setMomentum(await momRes.json());
      setLastUpdated(new Date());
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
  const etf      = regime?.etf_details || {};
  const cyclePhase    = regime?.cycle_phase || 'NEUTRAL';
  const indLeaders    = regime?.industry_leaders || [];
  const indLaggards   = regime?.industry_laggards || [];
  const smallCapReg   = regime?.small_cap_regime || 'NEUTRAL';
  const iwmVsSpy      = regime?.iwm_vs_spy ?? null;
  const iwmPct        = etf?.IWM?.pct_1d ?? regime?.iwm_pct ?? null;

  // Merge sector scan data with Finviz momentum data
  const momentumByGics = {};
  Object.entries(momentum).forEach(([fvName, d]) => {
    const gics = d.gics_name || fvName;
    momentumByGics[gics] = d;
  });

  // Build class distribution summary
  const classCount = { A: 0, B: 0, C: 0, D: 0, F: 0 };
  Object.values(momentum).forEach(d => {
    const c = d.sector_class;
    if (c && classCount[c] != null) classCount[c]++;
  });

  const allSectorEtfs = ['XLK','XLV','XLF','XLY','XLP','XLE','XLI','XLB','XLRE','XLC','XLU'];
  const industryEtfs  = [
    { sym: 'SMH', label: 'Semiconductors' },
    { sym: 'XBI', label: 'Biotech' },
    { sym: 'ITA', label: 'Aerospace' },
    { sym: 'TAN', label: 'Solar' },
    { sym: 'KRE', label: 'Reg. Banks' },
    { sym: 'XME', label: 'Metals' },
    { sym: 'IYT', label: 'Transport' },
  ];

  return (
    <>
      <Head><title>Pump Scout — Sector Intelligence</title></Head>
      <div className={styles.container}>

        {/* ── Header ── */}
        <header className={styles.header}>
          <Link href="/" className={styles.back}>← Scanner</Link>
          <h1 className={styles.title}>🗂 Sector Intelligence</h1>
          {lastUpdated && (
            <span className={styles.timestamp}>
              {lastUpdated.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </header>

        {/* ── Regime + Cycle Phase Banner ── */}
        {regime && (
          <div className={styles.regimeBanner}>
            <div className={styles.regimeLeft}>
              <span className={styles.regimeLabel}
                style={{ color: REGIME_COLOR[regime.regime] || '#ffd740' }}>
                {regime.regime}
              </span>
              <span className={styles.regimeEtfs}>
                SPY <b style={{ color: pctColor(regime.spy_pct) }}>{fmt(regime.spy_pct)}</b>
                {' '} QQQ <b style={{ color: pctColor(regime.qqq_pct) }}>{fmt(regime.qqq_pct)}</b>
                {etf.XLE && <>{' '} XLE <b style={{ color: pctColor(etf.XLE.pct_1d) }}>{fmt(etf.XLE.pct_1d)}</b></>}
                {etf.GLD && <>{' '} GLD <b style={{ color: pctColor(etf.GLD.pct_1d) }}>{fmt(etf.GLD.pct_1d)}</b></>}
              </span>
            </div>
            <div className={styles.cycleBlock}>
              <span style={{
                fontSize: 11, fontWeight: 800, letterSpacing: '0.05em',
                color: CYCLE_COLOR[cyclePhase] || '#fff',
              }}>
                {CYCLE_EMOJI[cyclePhase]} {cyclePhase.replace(/_/g, ' ')}
              </span>
            </div>
          </div>
        )}

        {/* Strong/Weak tags from regime */}
        {regime && (
          <div className={styles.rotationRow}>
            {(regime.strong_sectors || []).length > 0 && (
              <div className={styles.rotIn}>
                <span className={styles.rotTag} style={{ color: '#00c864' }}>▲ IN</span>
                {regime.strong_sectors.slice(0, 4).map(s => (
                  <span key={s} className={styles.rotSector} style={{ color: '#00c864', borderColor: '#00c86430', background: 'rgba(0,200,100,0.07)' }}>{s}</span>
                ))}
              </div>
            )}
            {(regime.weak_sectors || []).length > 0 && (
              <div className={styles.rotOut}>
                <span className={styles.rotTag} style={{ color: '#ff4466' }}>▼ OUT</span>
                {regime.weak_sectors.slice(0, 4).map(s => (
                  <span key={s} className={styles.rotSector} style={{ color: '#ff4466', borderColor: '#ff446630', background: 'rgba(255,68,102,0.07)' }}>{s}</span>
                ))}
              </div>
            )}
            {/* Class distribution summary */}
            {Object.values(classCount).some(v => v > 0) && (
              <div style={{ marginLeft: 'auto' }}>
                <SectorClassBar classData={classCount} />
              </div>
            )}
          </div>
        )}

        {/* ── Sector ETF Heatmap ── */}
        {regime && (
          <section className={styles.section}>
            <div className={styles.sectionLabel}>SECTOR ETFs</div>
            <div className={styles.etfGrid}>
              {allSectorEtfs.map(sym => (
                <EtfBox key={sym} symbol={sym} pct={etf[sym]?.pct_1d} />
              ))}
            </div>
          </section>
        )}

        {/* ── Industry ETF + IWM ── */}
        {regime && (
          <section className={styles.section}>
            <div className={styles.sectionLabel} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              INDUSTRY ETFs
              {iwmPct != null && (
                <span style={{ fontWeight: 400, color: SC_COLOR[smallCapReg] || 'rgba(255,255,255,0.45)', fontSize: 9 }}>
                  {SC_EMOJI[smallCapReg]} IWM (Small Cap) {fmt(iwmPct)}
                  {iwmVsSpy != null && <span style={{ color: 'rgba(255,255,255,0.35)', marginLeft: 4 }}>vs SPY {fmt(iwmVsSpy)}</span>}
                </span>
              )}
            </div>
            <div className={styles.etfGrid} style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
              <EtfBox symbol="IWM" pct={iwmPct} label="Small Cap" />
              {industryEtfs.map(({ sym, label }) => (
                <EtfBox key={sym} symbol={sym} pct={etf[sym]?.pct_1d} label={label} />
              ))}
            </div>
            {/* Leaders / Laggards */}
            {(indLeaders.length > 0 || indLaggards.length > 0) && (
              <div className={styles.indRow}>
                {indLeaders.length > 0 && (
                  <div>
                    <span style={{ fontSize: 9, color: '#00c864', fontWeight: 700, marginRight: 6 }}>↑ Leaders</span>
                    {indLeaders.slice(0, 4).map(e => (
                      <span key={e.symbol || e.name} style={{
                        fontSize: 9, fontWeight: 700, color: '#00c864',
                        background: 'rgba(0,200,100,0.1)', border: '1px solid rgba(0,200,100,0.25)',
                        borderRadius: 3, padding: '1px 5px', marginRight: 4,
                      }}>
                        {e.symbol} {fmt(e.pct_1d)}
                        {e.name && <span style={{ opacity: 0.55, marginLeft: 3 }}>· {e.name}</span>}
                      </span>
                    ))}
                  </div>
                )}
                {indLaggards.length > 0 && (
                  <div style={{ marginTop: 4 }}>
                    <span style={{ fontSize: 9, color: '#ff4466', fontWeight: 700, marginRight: 6 }}>↓ Laggards</span>
                    {indLaggards.slice(0, 4).map(e => (
                      <span key={e.symbol || e.name} style={{
                        fontSize: 9, fontWeight: 700, color: '#ff4466',
                        background: 'rgba(255,68,102,0.1)', border: '1px solid rgba(255,68,102,0.25)',
                        borderRadius: 3, padding: '1px 5px', marginRight: 4,
                      }}>
                        {e.symbol} {fmt(e.pct_1d)}
                        {e.name && <span style={{ opacity: 0.55, marginLeft: 3 }}>· {e.name}</span>}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {/* ── Finviz Live Momentum ── */}
        {Object.keys(momentum).length > 0 && (
          <section className={styles.section}>
            <div className={styles.sectionLabel}>LIVE SECTOR FLOW (FINVIZ)</div>
            <div className={styles.momentumGrid}>
              {Object.entries(momentum)
                .sort((a, b) => (a[1].rank_1d || 99) - (b[1].rank_1d || 99))
                .map(([name, d]) => {
                  const pct = d.change_pct;
                  const sc  = d.sector_class;
                  const ret = d.retention;
                  const trending = d.trending;
                  const color = pctColor(pct);
                  return (
                    <div key={name} className={styles.momCard}
                      style={{
                        borderColor: trending ? '#ffd74040' : 'rgba(255,255,255,0.07)',
                        background: trending ? 'rgba(255,215,64,0.04)' : 'rgba(255,255,255,0.02)',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 4 }}>
                        <span style={{ fontSize: 10, fontWeight: 700, color: '#e0e0e0', lineHeight: 1.2 }}>
                          {trending && '🔥 '}{d.gics_name || name}
                        </span>
                        <ClassBadge cls={sc} />
                      </div>
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginTop: 4 }}>
                        <span style={{ fontSize: 15, fontWeight: 800, color }}>{fmt(pct)}</span>
                        {d.vs_spy_1d != null && (
                          <span style={{ fontSize: 9, color: d.vs_spy_1d > 0 ? '#69f0ae' : 'rgba(255,100,100,0.7)' }}>
                            {d.vs_spy_1d > 0 ? '▲' : '▼'} SPY {fmt(d.vs_spy_1d)}
                          </span>
                        )}
                      </div>
                      {ret && ret !== 'NEUTRAL' && (
                        <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.4)', marginTop: 2 }}>
                          {RETENTION_ICON[ret]} {ret}
                        </div>
                      )}
                      <div style={{ fontSize: 9, color: 'rgba(255,255,255,0.25)', marginTop: 2 }}>
                        #{d.rank_1d}
                      </div>
                    </div>
                  );
                })}
            </div>
          </section>
        )}

        {/* ── Sector Scan Table (from scan data) ── */}
        <section className={styles.section}>
          <div className={styles.sectionLabel}>SCAN-BASED STRENGTH</div>
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
                    <th>Grade</th>
                    <th>Score</th>
                    <th>CMF</th>
                    <th>1D Flow</th>
                    <th>vs SPY</th>
                    <th>Leader</th>
                    <th>Count</th>
                  </tr>
                </thead>
                <tbody>
                  {sectors.map(s => {
                    const pct    = Math.round((s.avg_score / maxScore) * 100);
                    const isWeak   = regime?.weak_sectors?.includes(s.sector);
                    const isStrong = regime?.strong_sectors?.includes(s.sector);
                    const isSelected = selectedSector === s.sector;
                    // Try to enrich with Finviz momentum
                    const mom = momentumByGics[s.sector] || null;
                    const sc  = mom?.sector_class || null;
                    // Prefer Finviz momentum; fall back to scan avg price-change (treat 0 as no data)
                    const flowPct = mom?.change_pct ?? (s.momentum_pct || null);
                    const vsSpyPct = mom?.vs_spy_1d ?? null;
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
                            {isWeak   && <span className={styles.weakTag}>⚠</span>}
                            {mom?.trending && <span style={{ marginLeft: 5, fontSize: 9 }}>🔥</span>}
                          </td>
                          <td><ClassBadge cls={sc} /></td>
                          <td>
                            <div className={styles.scoreCell}>
                              <div className={styles.scoreBar} style={{ width: `${pct}%` }} />
                              <span>{(s.avg_score || 0).toFixed(0)}</span>
                            </div>
                          </td>
                          <td style={{ color: 'rgba(255,255,255,0.6)' }}>
                            {s.avg_cmf_pctl != null ? `${s.avg_cmf_pctl.toFixed(0)}%ile` : '—'}
                          </td>
                          <td style={{ color: pctColor(flowPct), fontWeight: 700 }}>
                            {fmt(flowPct)}
                          </td>
                          <td style={{ color: vsSpyPct != null ? (vsSpyPct > 0 ? '#69f0ae' : '#ff8866') : 'var(--text-muted)' }}>
                            {vsSpyPct != null ? fmt(vsSpyPct) : '—'}
                          </td>
                          <td className={styles.leader}>{s.leader_symbol || '—'}</td>
                          <td style={{ color: 'var(--text-muted)' }}>{s.ticker_count || 0}</td>
                        </tr>
                        {isSelected && (
                          <tr key={`${s.sector}-detail`}>
                            <td colSpan={8} className={styles.detailCell}>
                              {loadingDetail ? (
                                <div className={styles.detailLoading}>Loading…</div>
                              ) : sectorDetail ? (
                                <div className={styles.tickerGrid}>
                                  {(sectorDetail.tickers_detail || []).map(t => (
                                    <div key={t.symbol} className={styles.tickerRow}>
                                      <span className={styles.tickerSym}>{t.symbol}</span>
                                      <span className={styles.tickerTier}>{t.tier}</span>
                                      <span className={styles.tickerScore}>{t.score?.toFixed(0)}</span>
                                      <span style={{ color: pctColor(t.price_change_pct), fontSize: 10 }}>
                                        {fmt(t.price_change_pct)}
                                      </span>
                                      <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                                        CMF {t.cmf_pctl?.toFixed(0)}%ile
                                      </span>
                                      {t.setup_quality?.quality && (
                                        <span style={{
                                          fontSize: 9, fontWeight: 700,
                                          color: { PRIME: '#00c864', STRONG: '#69f0ae', MODERATE: '#ffd740', WEAK: '#ff8866', AVOID: '#ff4466' }[t.setup_quality.quality] || '#888',
                                          background: 'rgba(255,255,255,0.05)', borderRadius: 3, padding: '1px 5px',
                                        }}>
                                          {t.setup_quality.quality}
                                        </span>
                                      )}
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
        </section>

        {/* ── Footer ── */}
        <div className={styles.footer}>
          <button className={styles.refreshBtn} onClick={fetchData}>⟳ Refresh</button>
          <span className={styles.footerNote}>
            Sector data updates after each scan · Regime detects at 7:55 AM ET
          </span>
        </div>
      </div>
    </>
  );
}
