/**
 * Macro Events — Trump News Bias Layer — Version Alpha
 *
 * Read-only contextual intelligence. Displays Trump-related policy events
 * classified by sector impact. NEVER affects scores, tiers, or rankings.
 */
import { useCallback, useEffect, useState } from 'react';
import Head from 'next/head';
import styles from '../styles/MacroEvents.module.css';
import AppNav from '../components/AppNav';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const REFRESH_INTERVAL = 5 * 60 * 1000; // 5 min

// ─── Constants ────────────────────────────────────────────────────────────────

const MARKET_BIAS_CONFIG = {
  BULLISH:  { icon: '🟢', color: '#00c864', label: 'Bullish' },
  BEARISH:  { icon: '🔴', color: '#ff4444', label: 'Bearish' },
  RISK_OFF: { icon: '🟠', color: '#ff8800', label: 'Risk-Off' },
  MIXED:    { icon: '🟡', color: '#ffd600', label: 'Mixed' },
  NEUTRAL:  { icon: '⚪', color: '#888',    label: 'Neutral' },
};

const VOLATILITY_CONFIG = {
  VERY_HIGH: { color: '#ff4444', label: 'Very High' },
  HIGH:      { color: '#ff8800', label: 'High' },
  MEDIUM:    { color: '#ffd600', label: 'Medium' },
  LOW:       { color: '#555',    label: 'Low' },
};

const CLASS_COLORS = {
  TARIFF_TRADE:          { bg: 'rgba(255,136,0,0.15)', color: '#ff8800' },
  CHINA_SUPPLY_CHAIN:    { bg: 'rgba(255,68,68,0.15)',  color: '#ff4444' },
  ENERGY_OIL:            { bg: 'rgba(255,214,0,0.12)',  color: '#ffd600' },
  GEOPOLITICS_SANCTIONS: { bg: 'rgba(204,68,255,0.15)', color: '#cc44ff' },
  DEFENSE_SECURITY:      { bg: 'rgba(0,200,100,0.12)',  color: '#00c864' },
  HEALTHCARE_POLICY:     { bg: 'rgba(0,229,255,0.12)',  color: '#00e5ff' },
  TECH_SEMICONDUCTOR:    { bg: 'rgba(100,180,255,0.12)',color: '#64b4ff' },
  TELECOM_INFRA:         { bg: 'rgba(180,100,255,0.12)',color: '#b464ff' },
  TAX_FISCAL:            { bg: 'rgba(0,200,100,0.12)',  color: '#00c864' },
  DOMESTIC_GROWTH_POLICY:{ bg: 'rgba(0,229,255,0.12)',  color: '#00e5ff' },
  REGULATORY_SHOCK:      { bg: 'rgba(255,136,0,0.12)',  color: '#ff8800' },
  GENERAL_POLITICAL_NOISE:{ bg: 'rgba(100,100,100,0.1)',color: '#666' },
};

const CLASS_LABELS = {
  TARIFF_TRADE:          'Tariff / Trade',
  CHINA_SUPPLY_CHAIN:    'China / Supply Chain',
  ENERGY_OIL:            'Energy / Oil',
  GEOPOLITICS_SANCTIONS: 'Geopolitics / Sanctions',
  DEFENSE_SECURITY:      'Defense / Security',
  HEALTHCARE_POLICY:     'Healthcare Policy',
  TECH_SEMICONDUCTOR:    'Tech / Semiconductor',
  TELECOM_INFRA:         'Telecom / Infra',
  TAX_FISCAL:            'Tax / Fiscal',
  DOMESTIC_GROWTH_POLICY:'Domestic Growth',
  REGULATORY_SHOCK:      'Regulatory Shock',
  GENERAL_POLITICAL_NOISE:'Political Noise',
};

const VIEW_TABS = [
  { key: 'active',    label: '⚡ Active Bias' },
  { key: 'latest',   label: '📰 Latest' },
  { key: 'history',  label: '📅 History (7d)' },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function timeAgo(isoStr) {
  if (!isoStr) return '—';
  const diff = Date.now() - new Date(isoStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1)   return 'just now';
  if (mins < 60)  return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)   return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function fmtDate(isoStr) {
  if (!isoStr) return '—';
  try {
    return new Date(isoStr).toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch { return isoStr.slice(0, 16).replace('T', ' '); }
}

// ─── Bias Badge ───────────────────────────────────────────────────────────────

function BiasBadge({ bias }) {
  const cfg = MARKET_BIAS_CONFIG[bias] || MARKET_BIAS_CONFIG.NEUTRAL;
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 4,
      background: `${cfg.color}22`, color: cfg.color,
      border: `1px solid ${cfg.color}44`, letterSpacing: '0.06em',
    }}>
      {cfg.icon} {cfg.label}
    </span>
  );
}

function VolBadge({ vol }) {
  const cfg = VOLATILITY_CONFIG[vol] || VOLATILITY_CONFIG.LOW;
  return (
    <span style={{
      fontSize: 10, fontWeight: 600, padding: '2px 6px', borderRadius: 4,
      color: cfg.color, border: `1px solid ${cfg.color}44`,
      background: `${cfg.color}11`,
    }}>
      ⚡ {cfg.label} Vol
    </span>
  );
}

// ─── Active Bias Panel ────────────────────────────────────────────────────────

function ActiveBiasPanel({ bias, loading }) {
  if (loading) return <div className={styles.loadingState}>Computing active bias…</div>;
  if (!bias)   return null;

  const biasConf = MARKET_BIAS_CONFIG[bias.overall_market_bias] || MARKET_BIAS_CONFIG.NEUTRAL;
  const volConf  = VOLATILITY_CONFIG[bias.overall_volatility]   || VOLATILITY_CONFIG.LOW;

  return (
    <div className={styles.biasPanel}>
      <div className={styles.biasPanelHeader}>
        <span className={styles.biasPanelTitle}>Active Macro Bias</span>
        <span className={styles.biasComputedAt}>
          {bias.event_count} event{bias.event_count !== 1 ? 's' : ''} · computed {timeAgo(bias.computed_at)}
        </span>
      </div>

      {bias.event_count === 0 ? (
        <div className={styles.emptyBias}>
          No active Trump policy events detected in the last 3 days.
          <br/>Bias is neutral — no macro context to display.
        </div>
      ) : (
        <>
          <div className={styles.biasSummaryRow}>
            <div className={styles.biasStat}>
              <div className={styles.biasStatVal} style={{ color: biasConf.color }}>
                {biasConf.icon} {biasConf.label}
              </div>
              <div className={styles.biasStatLbl}>Market Bias</div>
            </div>
            <div className={styles.biasStat}>
              <div className={styles.biasStatVal} style={{ color: volConf.color }}>
                {volConf.label}
              </div>
              <div className={styles.biasStatLbl}>Volatility</div>
            </div>
            <div className={styles.biasStat}>
              <div className={styles.biasStatVal}>{bias.event_count}</div>
              <div className={styles.biasStatLbl}>Active Events</div>
            </div>
            <div className={styles.biasStat}>
              <div className={styles.biasStatVal}>{(bias.active_classes || []).length}</div>
              <div className={styles.biasStatLbl}>Categories</div>
            </div>
          </div>

          {bias.regime_summary && (
            <div className={styles.biasRegimeSummary}>{bias.regime_summary}</div>
          )}

          {(bias.top_bullish_sectors?.length > 0 || bias.top_bearish_sectors?.length > 0) && (
            <div className={styles.biasSectors}>
              {bias.top_bullish_sectors?.length > 0 && (
                <div className={styles.biasSectorGroup}>
                  <div className={styles.biasSectorLabel}>Macro-Supported Sectors</div>
                  <div className={styles.biasSectorPills}>
                    {bias.top_bullish_sectors.map(s => (
                      <span key={s} className={`${styles.sectorPill} ${styles.bullSectorPill}`}>{s}</span>
                    ))}
                  </div>
                </div>
              )}
              {bias.top_bearish_sectors?.length > 0 && (
                <div className={styles.biasSectorGroup}>
                  <div className={styles.biasSectorLabel}>Macro-Pressured Sectors</div>
                  <div className={styles.biasSectorPills}>
                    {bias.top_bearish_sectors.map(s => (
                      <span key={s} className={`${styles.sectorPill} ${styles.bearSectorPill}`}>{s}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {(bias.active_classes || []).length > 0 && (
            <div className={styles.activeClassesRow}>
              {bias.active_classes.map(cls => {
                const cfg = CLASS_COLORS[cls] || CLASS_COLORS.GENERAL_POLITICAL_NOISE;
                return (
                  <span key={cls} className={styles.classPill}
                    style={{ background: cfg.bg, color: cfg.color, borderColor: `${cfg.color}44` }}>
                    {CLASS_LABELS[cls] || cls}
                  </span>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ─── Event Card ───────────────────────────────────────────────────────────────

function EventCard({ event }) {
  const biasConf = MARKET_BIAS_CONFIG[event.market_bias] || MARKET_BIAS_CONFIG.NEUTRAL;
  const clsCfg   = CLASS_COLORS[event.primary_class]     || CLASS_COLORS.GENERAL_POLITICAL_NOISE;
  const volConf  = VOLATILITY_CONFIG[event.volatility_bias] || VOLATILITY_CONFIG.LOW;

  const biasLabel = {
    'NEUTRAL':  'NEUTRAL',
    'BULLISH':  'BULLISH',
    'BEARISH':  'BEARISH',
    'RISK_OFF': 'RISK-OFF',
    'MIXED':    'MIXED',
  }[event.market_bias] || event.market_bias;

  return (
    <div className={styles.eventCard}>
      <div className={styles.eventCardHeader}>
        <span className={styles.biasIcon}>{biasConf.icon}</span>
        <div className={styles.eventTitle}>
          {event.source_url
            ? <a href={event.source_url} target="_blank" rel="noreferrer"
                style={{ color: 'inherit', textDecoration: 'none' }}>
                {event.title}
              </a>
            : event.title}
        </div>
      </div>

      <div className={styles.eventMeta}>
        <span className={styles.primaryClassBadge}
          style={{ background: clsCfg.bg, color: clsCfg.color }}>
          {CLASS_LABELS[event.primary_class] || event.primary_class}
        </span>
        <BiasBadge bias={event.market_bias} />
        <span className={styles.eventTime}>{fmtDate(event.published_at)}</span>
        {event.source_url && (
          <a href={event.source_url} target="_blank" rel="noreferrer"
            className={styles.sourceLink}>↗ source</a>
        )}
      </div>

      <div className={styles.eventMetrics}>
        <span className={styles.metricChip} style={{ '--chip-color': '#ffd600' }}>
          <span className={styles.metricChipLabel}>relevance</span>
          <span className={styles.metricChipVal}>{event.relevance_score}/100</span>
        </span>
        <span className={styles.metricChip} style={{ '--chip-color': '#cc44ff' }}>
          <span className={styles.metricChipLabel}>confidence</span>
          <span className={styles.metricChipVal}>{event.confidence}/100</span>
        </span>
        <span className={styles.metricChip} style={{ '--chip-color': '#ff8800' }}>
          <span className={styles.metricChipLabel}>surprise</span>
          <span className={styles.metricChipVal}>{event.surprise_level}/100</span>
        </span>
        <span className={styles.metricChip} style={{ '--chip-color': volConf.color }}>
          <span className={styles.metricChipLabel}>vol bias</span>
          <span className={styles.metricChipVal}>{volConf.label}</span>
        </span>
        {event.time_horizon && (
          <span className={styles.metricChip} style={{ '--chip-color': '#888' }}>
            <span className={styles.metricChipLabel}>horizon</span>
            <span className={styles.metricChipVal}>{event.time_horizon}</span>
          </span>
        )}
        {event.oil_bias && event.oil_bias !== 'NEUTRAL' && (
          <span className={styles.metricChip}
            style={{ '--chip-color': event.oil_bias === 'BULLISH' ? '#00c864' : '#ff4444' }}>
            <span className={styles.metricChipLabel}>oil</span>
            <span className={styles.metricChipVal}>{event.oil_bias}</span>
          </span>
        )}
        {event.rates_bias && event.rates_bias !== 'NEUTRAL' && (
          <span className={styles.metricChip}
            style={{ '--chip-color': event.rates_bias === 'BULLISH' ? '#00c864' : '#ff4444' }}>
            <span className={styles.metricChipLabel}>rates</span>
            <span className={styles.metricChipVal}>{event.rates_bias}</span>
          </span>
        )}
        {event.dollar_bias && event.dollar_bias !== 'NEUTRAL' && (
          <span className={styles.metricChip}
            style={{ '--chip-color': event.dollar_bias === 'BULLISH' ? '#00c864' : '#ff4444' }}>
            <span className={styles.metricChipLabel}>$USD</span>
            <span className={styles.metricChipVal}>{event.dollar_bias}</span>
          </span>
        )}
      </div>

      {((event.bullish_sectors || []).length > 0 || (event.bearish_sectors || []).length > 0) && (
        <div className={styles.sectorImpactRow}>
          {(event.bullish_sectors || []).length > 0 && (
            <div className={styles.sectorGroup}>
              <div className={styles.sectorGroupLabel}>🟢 Macro-Supported</div>
              <div className={styles.sectorTags}>
                {event.bullish_sectors.map(s => (
                  <span key={s} className={`${styles.sectorTag} ${styles.sectorTagBull}`}>{s}</span>
                ))}
              </div>
            </div>
          )}
          {(event.bearish_sectors || []).length > 0 && (
            <div className={styles.sectorGroup}>
              <div className={styles.sectorGroupLabel}>🔴 Macro-Pressured</div>
              <div className={styles.sectorTags}>
                {event.bearish_sectors.map(s => (
                  <span key={s} className={`${styles.sectorTag} ${styles.sectorTagBear}`}>{s}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function MacroEventsPage() {
  const [activeTab,    setActiveTab]    = useState('active');
  const [bias,         setBias]         = useState(null);
  const [events,       setEvents]       = useState([]);
  const [biasLoading,  setBiasLoading]  = useState(true);
  const [eventsLoading,setEventsLoading]= useState(false);
  const [refreshing,   setRefreshing]   = useState(false);
  const [statusMsg,    setStatusMsg]    = useState('');
  const [error,        setError]        = useState('');
  const [lastFetch,    setLastFetch]    = useState(null);

  // ── Data Fetchers ──────────────────────────────────────────────────────────

  const fetchBias = useCallback(async () => {
    try {
      setBiasLoading(true);
      const res = await fetch(`${API_URL}/api/events/trump/active-bias?max_age_days=3`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setBias(data);
    } catch (e) {
      console.error('fetchBias failed:', e);
    } finally {
      setBiasLoading(false);
    }
  }, []);

  const fetchEvents = useCallback(async (tab) => {
    setEventsLoading(true);
    setError('');
    try {
      let url;
      if (tab === 'active') {
        url = `${API_URL}/api/events/trump/active-bias?max_age_days=3`;
      } else if (tab === 'latest') {
        url = `${API_URL}/api/events/trump/latest?limit=30`;
      } else {
        url = `${API_URL}/api/events/trump/history?days=7&limit=100`;
      }
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const evs = tab === 'active' ? (data.recent_events || []) : (data.events || []);
      setEvents(evs);
      setLastFetch(new Date());
    } catch (e) {
      setError(`Failed to load events: ${e.message}`);
    } finally {
      setEventsLoading(false);
    }
  }, []);

  const handleRefresh = async () => {
    setRefreshing(true);
    setStatusMsg('Fetching news…');
    try {
      const res = await fetch(`${API_URL}/api/events/trump/refresh`, { method: 'POST' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatusMsg('News refresh started. Reloading in 8s…');
      setTimeout(() => {
        fetchBias();
        fetchEvents(activeTab);
        setStatusMsg('');
      }, 8000);
    } catch (e) {
      setStatusMsg(`Refresh failed: ${e.message}`);
    } finally {
      setRefreshing(false);
    }
  };

  // ── Effects ────────────────────────────────────────────────────────────────

  useEffect(() => { fetchBias(); }, [fetchBias]);

  useEffect(() => {
    fetchEvents(activeTab);
  }, [activeTab, fetchEvents]);

  useEffect(() => {
    const t = setInterval(() => {
      fetchBias();
      fetchEvents(activeTab);
    }, REFRESH_INTERVAL);
    return () => clearInterval(t);
  }, [activeTab, fetchBias, fetchEvents]);

  // ── Counts for summary bar ─────────────────────────────────────────────────

  const bullishCount = events.filter(e => e.market_bias === 'BULLISH').length;
  const bearishCount = events.filter(e => ['BEARISH', 'RISK_OFF'].includes(e.market_bias)).length;
  const highVolCount = events.filter(e => ['HIGH', 'VERY_HIGH'].includes(e.volatility_bias)).length;

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <>
      <Head>
        <title>Macro Events — Pump Scout</title>
      </Head>
      <div className={styles.page}>

        <AppNav />

        {/* Header */}
        <div className={styles.header}>
          <div className={styles.titleRow}>
            <h1 className={styles.title}>Macro Events</h1>
            <span className={styles.alphaTag}>Alpha</span>
          </div>
          <p className={styles.subtitle}>Trump Policy News → Structured Market Context</p>
          {lastFetch && (
            <span className={styles.scanTime}>Updated {timeAgo(lastFetch.toISOString())}</span>
          )}
        </div>

        <div className={styles.disclaimer}>
          ⚠️ Read-only context layer. Does NOT affect scan scores, tiers, or rankings.
          For informational awareness only — not a trading signal.
        </div>

        {/* Toolbar */}
        <div className={styles.toolbar}>
          <button className={styles.refreshBtn} onClick={handleRefresh}
            disabled={refreshing}>
            {refreshing ? '↻ Fetching…' : '↻ Refresh News'}
          </button>
          {statusMsg && <span className={styles.statusMsg}>{statusMsg}</span>}
        </div>

        {/* Active Bias Panel — always visible */}
        <ActiveBiasPanel bias={bias} loading={biasLoading} />

        {/* Tabs */}
        <div className={styles.tabs}>
          {VIEW_TABS.map(t => (
            <button key={t.key}
              className={`${styles.tab} ${activeTab === t.key ? styles.tabActive : ''}`}
              onClick={() => setActiveTab(t.key)}>
              {t.label}
            </button>
          ))}
        </div>

        {/* Summary Bar */}
        {!eventsLoading && events.length > 0 && (
          <div className={styles.summaryBar}>
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum}>{events.length}</span>
              <span className={styles.summaryLbl}>Events</span>
            </div>
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum} style={{ color: '#00c864' }}>{bullishCount}</span>
              <span className={styles.summaryLbl}>Bullish</span>
            </div>
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum} style={{ color: '#ff4444' }}>{bearishCount}</span>
              <span className={styles.summaryLbl}>Bearish/Risk-Off</span>
            </div>
            <div className={styles.summaryItem}>
              <span className={styles.summaryNum} style={{ color: '#ff8800' }}>{highVolCount}</span>
              <span className={styles.summaryLbl}>High Vol Events</span>
            </div>
          </div>
        )}

        {/* Event List */}
        {eventsLoading ? (
          <div className={styles.loadingState}>Loading events…</div>
        ) : error ? (
          <div className={styles.errorState}>{error}</div>
        ) : events.length === 0 ? (
          <div className={styles.emptyState}>
            {activeTab === 'active'
              ? 'No active Trump policy events detected in the last 3 days. Click Refresh News to fetch latest.'
              : 'No events found. Click Refresh News to fetch latest news from RSS feeds.'}
          </div>
        ) : (
          <div className={styles.eventList}>
            {events.map(ev => (
              <EventCard key={ev.event_id || ev.id} event={ev} />
            ))}
          </div>
        )}
      </div>
    </>
  );
}
