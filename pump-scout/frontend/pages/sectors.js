import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import styles from '../styles/Sectors.module.css';
import AppNav from '../components/AppNav';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// ── Constants ─────────────────────────────────────────────────────────────────
const SECTOR_ORDER = ['XLC','XLY','XLP','XLE','XLF','XLV','XLI','XLB','XLRE','XLK','XLU'];

const METRICS = [
  { key: 'ret_1d',    label: '1D'        },
  { key: 'ret_5d',    label: '5D'        },
  { key: 'ret_20d',   label: '20D'       },
  { key: 'ret_50d',   label: '50D'       },
  { key: 'vs_spy_1d', label: 'vs SPY 1D' },
  { key: 'vs_spy_5d', label: 'vs SPY 5D' },
  { key: 'vs_spy_20d',label: 'vs SPY 20D'},
];

const TABLE_COLS = [
  { key: 'etf',        label: 'ETF',        sortable: false },
  { key: 'name',       label: 'Sector',     sortable: false },
  { key: 'ret_1d',     label: '1D %',       sortable: true  },
  { key: 'ret_5d',     label: '5D %',       sortable: true  },
  { key: 'ret_20d',    label: '20D %',      sortable: true  },
  { key: 'vs_spy_1d',  label: '1D vs SPY',  sortable: true  },
  { key: 'vs_spy_5d',  label: '5D vs SPY',  sortable: true  },
  { key: 'trend_label',label: 'Trend',      sortable: true  },
  { key: 'rs_trend',   label: 'RS vs SPY',  sortable: false },
];

const RISK_COLORS = {
  RISK_ON:  '#00c853',
  RISK_OFF: '#f44336',
  NEUTRAL:  '#ff9800',
};

const QUADRANT_COLORS = {
  LEADING:   '#00c853',
  IMPROVING: '#2196f3',
  LAGGING:   '#f44336',
  WEAKENING: '#ff9800',
};

const TREND_COLORS = {
  LEADING:   '#00c853',
  IMPROVING: '#69f0ae',
  NEUTRAL:   '#607d8b',
  WEAKENING: '#ff9800',
  LAGGING:   '#f44336',
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function fmtPct(v, decimals = 2) {
  if (v == null) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${Number(v).toFixed(decimals)}%`;
}

function retColor(v) {
  if (v == null) return '#607d8b';
  if (v >  2)    return '#00c853';
  if (v >  1)    return '#00e676';
  if (v >  0.3)  return '#69f0ae';
  if (v > -0.3)  return '#607d8b';
  if (v > -1)    return '#ff5252';
  if (v > -2)    return '#f44336';
  return '#b71c1c';
}

function retBg(v) {
  if (v == null) return 'rgba(96,125,139,0.10)';
  if (v >  2)    return 'rgba(0,200,83,0.22)';
  if (v >  1)    return 'rgba(0,200,83,0.14)';
  if (v >  0.3)  return 'rgba(0,200,83,0.07)';
  if (v > -0.3)  return 'rgba(96,125,139,0.07)';
  if (v > -1)    return 'rgba(244,67,54,0.07)';
  if (v > -2)    return 'rgba(244,67,54,0.14)';
  return 'rgba(244,67,54,0.22)';
}

// ── RRG SVG ───────────────────────────────────────────────────────────────────
function RRGPlot({ sectors }) {
  const SIZE  = 360;
  const CTR   = 180;
  const SCALE = 8; // px per unit (1 std-dev = 10 units → ±80px from center)

  function toSvg(x, y) {
    return {
      sx: Math.max(12, Math.min(SIZE - 12, CTR + (x - 100) * SCALE)),
      sy: Math.max(12, Math.min(SIZE - 12, CTR - (y - 100) * SCALE)),
    };
  }

  const entries = Object.entries(sectors || {});

  return (
    <svg
      width={SIZE}
      height={SIZE}
      style={{ background: '#13132a', borderRadius: 8, display: 'block' }}
      aria-label="Relative Rotation Graph"
    >
      {/* Quadrant backgrounds */}
      <rect x={CTR} y={0}   width={CTR} height={CTR} fill="rgba(0,200,83,0.05)"  />
      <rect x={CTR} y={CTR} width={CTR} height={CTR} fill="rgba(255,152,0,0.05)" />
      <rect x={0}   y={CTR} width={CTR} height={CTR} fill="rgba(244,67,54,0.05)" />
      <rect x={0}   y={0}   width={CTR} height={CTR} fill="rgba(33,150,243,0.05)"/>
      {/* Axes */}
      <line x1={CTR} y1={4} x2={CTR} y2={SIZE - 4} stroke="#333" strokeWidth={1} />
      <line x1={4} y1={CTR} x2={SIZE - 4} y2={CTR} stroke="#333" strokeWidth={1} />
      {/* Quadrant labels */}
      <text x={CTR + 6} y={14}         fill="#00c853" fontSize={9} fontFamily="monospace">LEADING</text>
      <text x={CTR + 6} y={SIZE - 4}   fill="#ff9800" fontSize={9} fontFamily="monospace">WEAKENING</text>
      <text x={4}       y={14}         fill="#2196f3" fontSize={9} fontFamily="monospace">IMPROVING</text>
      <text x={4}       y={SIZE - 4}   fill="#f44336" fontSize={9} fontFamily="monospace">LAGGING</text>
      {/* Axis labels */}
      <text x={SIZE - 68} y={CTR - 5}  fill="#555" fontSize={8} fontFamily="monospace">RS-Ratio →</text>
      <text x={CTR + 4}   y={SIZE - 18} fill="#555" fontSize={8} fontFamily="monospace" writingMode="tb">Momentum ↑</text>
      {/* Sector dots */}
      {entries.map(([etf, d]) => {
        const { sx, sy } = toSvg(d.x ?? 100, d.y ?? 100);
        const col = QUADRANT_COLORS[d.quadrant] || '#ccc';
        return (
          <g key={etf}>
            <circle cx={sx} cy={sy} r={7}  fill={col} opacity={0.25} />
            <circle cx={sx} cy={sy} r={4}  fill={col} opacity={0.9} />
            <text   x={sx + 7} y={sy + 4} fill={col} fontSize={9} fontFamily="monospace" fontWeight="bold">
              {etf}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ── Subsector strength color map ──────────────────────────────────────────────
const SUBSECTOR_COLORS = {
  SUBSECTOR_LEADING:   '#00c853',
  SUBSECTOR_IMPROVING: '#69f0ae',
  SUBSECTOR_NEUTRAL:   '#607d8b',
  SUBSECTOR_WEAKENING: '#ff9800',
  SUBSECTOR_LAGGING:   '#f44336',
  SUBSECTOR_UNKNOWN:   '#333',
};

// ── Subsector drill-down panel ────────────────────────────────────────────────
function SubsectorPanel({ etf }) {
  const [data,            setData]            = useState(null);
  const [loading,         setLoading]         = useState(true);
  const [selectedSub,     setSelectedSub]     = useState(null);
  const [subDetail,       setSubDetail]       = useState(null);
  const [subDetailLoading,setSubDetailLoading]= useState(false);

  useEffect(() => {
    if (!etf) return;
    setLoading(true);
    setData(null);
    setSelectedSub(null);
    setSubDetail(null);
    fetch(`${API_URL}/api/sectors/${etf}/subsectors`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [etf]);

  const handleSubClick = (sub) => {
    if (selectedSub === sub.name) {
      setSelectedSub(null);
      setSubDetail(null);
      return;
    }
    setSelectedSub(sub.name);
    setSubDetail(null);
    setSubDetailLoading(true);
    fetch(`${API_URL}/api/sectors/${etf}/subsectors/${encodeURIComponent(sub.name)}`)
      .then(r => r.json())
      .then(d => { setSubDetail(d); setSubDetailLoading(false); })
      .catch(() => setSubDetailLoading(false));
  };

  if (loading) return <div className={styles.detailLoading} style={{ marginTop: 8 }}>Loading subsectors…</div>;
  if (!data?.subsectors?.length) return null;

  return (
    <div style={{ marginTop: 16 }}>
      <div className={styles.detailSectionTitle} style={{ marginBottom: 8 }}>Subsectors</div>

      {/* Mini subsector heatmap */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
        {data.subsectors.map(sub => {
          const col = SUBSECTOR_COLORS[sub.subsector_strength] || '#555';
          const isSelected = selectedSub === sub.name;
          return (
            <div
              key={sub.name}
              onClick={() => handleSubClick(sub)}
              style={{
                background: `${col}12`,
                border: `1px solid ${isSelected ? col : col + '44'}`,
                borderRadius: 6,
                padding: '7px 12px',
                cursor: 'pointer',
                minWidth: 120,
                outline: isSelected ? `2px solid ${col}` : 'none',
                transition: 'opacity 0.1s',
              }}
            >
              <div style={{ fontSize: 11, fontWeight: 700, color: '#ccc', marginBottom: 3 }}>
                {sub.name}
              </div>
              <div style={{ fontSize: 9, color: col, fontWeight: 700, letterSpacing: '0.4px' }}>
                {sub.subsector_strength.replace('SUBSECTOR_', '')}
              </div>
              <div style={{ fontSize: 9, color: '#555', marginTop: 2 }}>
                {sub.active_count}/{sub.ticker_count} active
              </div>
            </div>
          );
        })}
      </div>

      {/* Subsector detail: top active tickers */}
      {selectedSub && (
        <div style={{ background: '#0e0e20', border: '1px solid #2a2a4e', borderRadius: 6, padding: '10px 14px' }}>
          <div className={styles.detailSectionTitle} style={{ marginBottom: 8 }}>
            {selectedSub} — Active Tickers
          </div>
          {subDetailLoading && <div className={styles.detailLoading}>Loading…</div>}
          {subDetail && (
            <>
              {subDetail.top_active?.length > 0 ? (
                <div className={styles.moversList}>
                  {subDetail.top_active.map(m => (
                    <div key={m.symbol} className={styles.moverRow}>
                      <span className={styles.moverSymbol}>{m.symbol}</span>
                      <span className={styles.moverTier} style={{ color: m.tier === 'A' ? '#00c853' : m.tier === 'B' ? '#69f0ae' : '#ff9800' }}>
                        {m.tier || '—'}
                      </span>
                      <span className={styles.moverScore}>{m.score != null ? m.score.toFixed(1) : '—'}</span>
                      <span style={{ color: retColor(m.price_change_pct) }}>{fmtPct(m.price_change_pct)}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: 11, color: '#555' }}>No active scan candidates in this subsector.</div>
              )}
              {/* All tickers in subsector */}
              {subDetail.tickers?.length > 0 && (
                <div style={{ marginTop: 10 }}>
                  <div className={styles.detailSectionTitle} style={{ marginBottom: 6 }}>All Tickers</div>
                  <div className={styles.holdingsList}>
                    {subDetail.tickers.map(t => (
                      <span key={t} className={styles.holdingChip}>{t}</span>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ── Detail Panel ──────────────────────────────────────────────────────────────
function DetailPanel({ etf, onClose }) {
  const [detail,  setDetail]  = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!etf) return;
    setLoading(true);
    setDetail(null);
    fetch(`${API_URL}/api/sectors/${etf}`)
      .then(r => r.json())
      .then(d => { setDetail(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [etf]);

  if (!etf) return null;

  return (
    <div className={styles.detailPanel}>
      <div className={styles.detailHeader}>
        <span className={styles.detailTitle}>{etf} — {detail?.name || '...'}</span>
        <button className={styles.closeBtn} onClick={onClose}>✕</button>
      </div>

      {loading && <div className={styles.detailLoading}>Loading...</div>}

      {!loading && detail && (
        <>
          {/* Return grid */}
          <div className={styles.detailSection}>
            <div className={styles.detailSectionTitle}>Returns</div>
            <div className={styles.detailMetaGrid}>
              {[['1D',{v:detail.ret_1d}],['5D',{v:detail.ret_5d}],['20D',{v:detail.ret_20d}],
                ['50D',{v:detail.ret_50d}],['200D',{v:detail.ret_200d}],
                ['vs SPY 1D',{v:detail.vs_spy_1d}],['vs SPY 5D',{v:detail.vs_spy_5d}]
              ].map(([label, {v}]) => (
                <div key={label} className={styles.detailMeta}>
                  <div className={styles.detailMetaLabel}>{label}</div>
                  <div style={{ color: retColor(v), fontWeight: 700 }}>{fmtPct(v)}</div>
                </div>
              ))}
            </div>
          </div>

          {/* EMA stack */}
          {detail.ema_20 != null && (
            <div className={styles.detailSection}>
              <div className={styles.detailSectionTitle}>EMA Stack · Trend: <span style={{ color: TREND_COLORS[detail.trend_label] || '#aaa' }}>{detail.trend_label}</span></div>
              <div className={styles.detailMetaGrid}>
                {[['EMA 20', detail.ema_20],['EMA 50', detail.ema_50],['EMA 200', detail.ema_200]].map(([label, v]) => (
                  <div key={label} className={styles.detailMeta}>
                    <div className={styles.detailMetaLabel}>{label}</div>
                    <div className={styles.detailMetaValue}>{v != null ? `$${v.toFixed(2)}` : '—'}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Holdings */}
          <div className={styles.detailSection}>
            <div className={styles.detailSectionTitle}>Top Holdings</div>
            <div className={styles.holdingsList}>
              {(detail.top_holdings || []).map(sym => (
                <span key={sym} className={styles.holdingChip}>{sym}</span>
              ))}
            </div>
          </div>

          {/* Top movers from scan */}
          {detail.top_movers?.length > 0 && (
            <div className={styles.detailSection}>
              <div className={styles.detailSectionTitle}>Top Movers (Latest Scan)</div>
              <div className={styles.moversList}>
                {detail.top_movers.map(m => (
                  <div key={m.symbol} className={styles.moverRow}>
                    <span className={styles.moverSymbol}>{m.symbol}</span>
                    <span className={styles.moverTier} style={{ color: m.tier === 'A' ? '#00c853' : m.tier === 'B' ? '#69f0ae' : '#ff9800' }}>{m.tier || '—'}</span>
                    <span className={styles.moverScore}>{m.score != null ? m.score.toFixed(1) : '—'}</span>
                    <span style={{ color: retColor(m.price_change_pct) }}>{fmtPct(m.price_change_pct)}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Subsector drill-down */}
          <SubsectorPanel etf={etf} />
        </>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function Sectors() {
  const [overview,     setOverview]     = useState(null);
  const [rrg,          setRrg]          = useState(null);
  const [loading,      setLoading]      = useState(true);
  const [error,        setError]        = useState(null);
  const [heatMetric,   setHeatMetric]   = useState('ret_1d');
  const [sortKey,      setSortKey]      = useState('ret_1d');
  const [sortDir,      setSortDir]      = useState(-1);
  const [selectedEtf,  setSelectedEtf]  = useState(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API_URL}/api/sectors/overview`).then(r => r.json()),
      fetch(`${API_URL}/api/sectors/rrg`).then(r => r.json()),
    ])
      .then(([ov, rr]) => { setOverview(ov); setRrg(rr); setLoading(false); })
      .catch(e => { setError(String(e)); setLoading(false); });
  }, []);

  const handleSort = useCallback((key) => {
    setSortKey(prev => {
      if (prev === key) setSortDir(d => -d);
      else { setSortDir(-1); }
      return key;
    });
  }, []);

  const sectorRows = overview
    ? SECTOR_ORDER.map(etf => ({ etf, ...overview.sectors?.[etf] })).filter(r => r.name)
    : [];

  const sortedRows = [...sectorRows].sort((a, b) => {
    const av = a[sortKey], bv = b[sortKey];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return typeof av === 'string' ? sortDir * av.localeCompare(bv) : sortDir * (av - bv);
  });

  const riskMode = overview?.risk_mode || 'NEUTRAL';

  return (
    <>
      <Head><title>Sector Rotation — Pump Scout</title></Head>
      <AppNav />
      <div className={styles.page}>
        <h1 className={styles.pageTitle}>Sector Rotation</h1>

        {loading && <div className={styles.loading}>Loading sector data…</div>}
        {error   && <div className={styles.error}>Error: {error}</div>}

        {!loading && overview && (
          <>
            {/* ① Benchmarks */}
            <section className={styles.section}>
              <div className={styles.benchmarkGrid}>
                {['SPY','QQQ','IWM','DIA'].map(sym => {
                  const d = overview.benchmarks?.[sym] || {};
                  return (
                    <div key={sym} className={styles.benchmarkCard}>
                      <div className={styles.benchmarkSym}>{sym}</div>
                      <div className={styles.benchmarkName}>{d.name || sym}</div>
                      <div className={styles.benchmarkClose}>{d.close != null ? `$${d.close.toFixed(2)}` : '—'}</div>
                      <div className={styles.benchmarkReturns}>
                        <span style={{ color: retColor(d.ret_1d) }}>{fmtPct(d.ret_1d)}</span>
                        <span className={styles.retSep}>/</span>
                        <span style={{ color: retColor(d.ret_5d) }}>{fmtPct(d.ret_5d)}</span>
                        <span className={styles.retSep}>/</span>
                        <span style={{ color: retColor(d.ret_20d) }}>{fmtPct(d.ret_20d)}</span>
                      </div>
                      <div className={styles.benchmarkLabels}>1D / 5D / 20D</div>
                    </div>
                  );
                })}
              </div>
            </section>

            {/* ② Risk mode banner */}
            <section className={styles.section}>
              <div
                className={styles.riskBanner}
                style={{ borderColor: RISK_COLORS[riskMode], background: `${RISK_COLORS[riskMode]}18` }}
              >
                <span className={styles.riskBadge} style={{ background: RISK_COLORS[riskMode] }}>
                  {riskMode.replace('_', ' ')}
                </span>
                <span className={styles.riskDetail}>
                  Growth avg:&nbsp;
                  <b style={{ color: retColor(overview.risk_detail?.growth_avg) }}>
                    {fmtPct(overview.risk_detail?.growth_avg)}
                  </b>
                  &nbsp;·&nbsp;Defensive avg:&nbsp;
                  <b style={{ color: retColor(overview.risk_detail?.defensive_avg) }}>
                    {fmtPct(overview.risk_detail?.defensive_avg)}
                  </b>
                  &nbsp;·&nbsp;Spread:&nbsp;
                  <b style={{ color: retColor(overview.risk_score) }}>
                    {overview.risk_score > 0 ? '+' : ''}{overview.risk_score?.toFixed(2)}%
                  </b>
                  &nbsp;(5D basis)
                </span>
              </div>
            </section>

            {/* ③ Heatmap */}
            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>Sector Heatmap</span>
                <div className={styles.metricToggle}>
                  {METRICS.map(m => (
                    <button
                      key={m.key}
                      className={`${styles.metricBtn} ${heatMetric === m.key ? styles.metricBtnActive : ''}`}
                      onClick={() => setHeatMetric(m.key)}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
              </div>
              <div className={styles.heatmapGrid}>
                {SECTOR_ORDER.map(etf => {
                  const d   = overview.sectors?.[etf] || {};
                  const val = d[heatMetric];
                  return (
                    <div
                      key={etf}
                      className={`${styles.heatBox} ${selectedEtf === etf ? styles.heatBoxSelected : ''}`}
                      style={{ background: retBg(val), borderColor: retColor(val) }}
                      onClick={() => setSelectedEtf(etf === selectedEtf ? null : etf)}
                    >
                      <div className={styles.heatEtf}>{etf}</div>
                      <div className={styles.heatName}>{d.name?.split(' ').slice(-1)[0] || ''}</div>
                      <div className={styles.heatVal} style={{ color: retColor(val) }}>{fmtPct(val)}</div>
                      {d.rrg_quadrant && (
                        <div className={styles.heatQuadrant} style={{ color: QUADRANT_COLORS[d.rrg_quadrant] }}>
                          {d.rrg_quadrant}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>

            {/* ④ Sortable overview table */}
            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>Overview Table</span>
                <span className={styles.sectionSub}>click row to expand · click header to sort</span>
              </div>
              <div className={styles.tableWrap}>
                <table className={styles.overviewTable}>
                  <thead>
                    <tr>
                      {TABLE_COLS.map(col => (
                        <th
                          key={col.key}
                          className={col.sortable ? styles.thSortable : styles.th}
                          onClick={col.sortable ? () => handleSort(col.key) : undefined}
                        >
                          {col.label}
                          {col.sortable && sortKey === col.key && (
                            <span className={styles.sortArrow}>{sortDir > 0 ? ' ↑' : ' ↓'}</span>
                          )}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sortedRows.map(row => (
                      <tr
                        key={row.etf}
                        className={`${styles.tableRow} ${selectedEtf === row.etf ? styles.tableRowSelected : ''}`}
                        onClick={() => setSelectedEtf(row.etf === selectedEtf ? null : row.etf)}
                      >
                        <td className={styles.tdEtf}>{row.etf}</td>
                        <td className={styles.tdName}>{row.name}</td>
                        <td style={{ color: retColor(row.ret_1d)    }}>{fmtPct(row.ret_1d)}</td>
                        <td style={{ color: retColor(row.ret_5d)    }}>{fmtPct(row.ret_5d)}</td>
                        <td style={{ color: retColor(row.ret_20d)   }}>{fmtPct(row.ret_20d)}</td>
                        <td style={{ color: retColor(row.vs_spy_1d) }}>{fmtPct(row.vs_spy_1d)}</td>
                        <td style={{ color: retColor(row.vs_spy_5d) }}>{fmtPct(row.vs_spy_5d)}</td>
                        <td>
                          <span
                            className={styles.trendChip}
                            style={{
                              background: `${TREND_COLORS[row.trend_label] || '#607d8b'}1e`,
                              color: TREND_COLORS[row.trend_label] || '#607d8b',
                            }}
                          >
                            {row.trend_label || '—'}
                          </span>
                        </td>
                        <td>
                          <span
                            className={styles.rsTrendText}
                            style={{ color: row.rs_trend === 'OUTPERFORMING' ? '#00c853' : row.rs_trend === 'UNDERPERFORMING' ? '#f44336' : '#ff9800' }}
                          >
                            {row.rs_trend === 'OUTPERFORMING' ? '↑ OUT' : row.rs_trend === 'UNDERPERFORMING' ? '↓ UNDER' : '= NEUT'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {/* ⑤ Detail panel */}
            {selectedEtf && (
              <DetailPanel etf={selectedEtf} onClose={() => setSelectedEtf(null)} />
            )}

            {/* ⑥ RRG scatter */}
            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>Relative Rotation Graph</span>
                <span className={styles.sectionSub}>x = RS-Ratio (100 = SPY neutral) · y = RS-Momentum · normalized across sectors</span>
              </div>
              <div className={styles.rrgContainer}>
                <RRGPlot sectors={rrg?.sectors ?? overview.sectors} />
                <div className={styles.rrgLegend}>
                  {Object.entries(QUADRANT_COLORS).map(([q, col]) => (
                    <div key={q} className={styles.legendItem}>
                      <span className={styles.legendDot} style={{ background: col }} />
                      <span>{q}</span>
                    </div>
                  ))}
                </div>
              </div>
            </section>

            {/* ⑦ Macro context placeholder */}
            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <span className={styles.sectionTitle}>Macro Context</span>
                <span className={styles.sectionSub}>coming soon</span>
              </div>
              <div className={styles.macroGrid}>
                {['10Y Treasury Yield','VIX','USD Index (DXY)','Fed Rate Expectations','Gold (GLD)','Oil (USO)'].map(label => (
                  <div key={label} className={styles.macroCard}>
                    <div className={styles.macroLabel}>{label}</div>
                    <div className={styles.macroValue}>—</div>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}
      </div>
    </>
  );
}
