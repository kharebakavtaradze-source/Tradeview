import styles from '../styles/NpDrawer.module.css';

// ── Local helpers (self-contained, no import from page) ───────────────────────

function fmt(n, d = 2) { return n == null ? '—' : Number(n).toFixed(d); }
function fmtM(n) {
  if (n == null) return '—';
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toLocaleString()}`;
}
function fmtVol(n) {
  if (n == null) return '—';
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}K`;
  return String(n);
}

const LABEL_COLOR = {
  NEW_PUMP_FIRE:         { color: '#ff4400', bg: 'rgba(255,68,0,0.14)' },
  NEW_PUMP_STRONG:       { color: '#ff8800', bg: 'rgba(255,136,0,0.12)' },
  NEW_PUMP_SETUP:        { color: '#ffd600', bg: 'rgba(255,214,0,0.10)' },
  NEW_PUMP_TRIGGER_ONLY: { color: '#00e5ff', bg: 'rgba(0,229,255,0.09)' },
  NEW_PUMP_WEAK:         { color: '#888',    bg: 'rgba(128,128,128,0.08)' },
  NEW_PUMP_NONE:         { color: '#444',    bg: 'transparent' },
};
const LABEL_SHORT = {
  NEW_PUMP_FIRE: 'FIRE', NEW_PUMP_STRONG: 'STRONG', NEW_PUMP_SETUP: 'SETUP',
  NEW_PUMP_TRIGGER_ONLY: 'TRIGGER', NEW_PUMP_WEAK: 'WEAK', NEW_PUMP_NONE: 'NONE',
};
const SCORE_COLOR = (s) => {
  if (s >= 62) return '#ff4400';
  if (s >= 46) return '#ff8800';
  if (s >= 34) return '#ffd600';
  if (s >= 22) return '#00e5ff';
  if (s >= 8)  return '#888';
  return '#444';
};
const VERDICT_CFG = {
  strong_setup: { color: '#00e676', label: 'STRONG SETUP' },
  interesting:  { color: '#ffd740', label: 'INTERESTING'  },
  watch:        { color: '#00b0ff', label: 'WATCH'        },
  too_late:     { color: '#ff9800', label: 'TOO LATE'     },
  avoid:        { color: '#ff5252', label: 'AVOID'        },
};
const FLAG_CFG = {
  dilution_risk:          { color: '#ff5252', label: 'Dilution Risk'   },
  reverse_split_risk:     { color: '#ff5252', label: 'Reverse Split'   },
  late_confirm_sequence:  { color: '#ff9800', label: 'Late Confirm'    },
  stale_setup:            { color: '#ff9800', label: 'Stale Setup'     },
  isolated_signal:        { color: '#ff9800', label: 'Isolated Signal' },
  low_liquidity:          { color: '#ffd740', label: 'Low Liquidity'   },
  micro_cap:              { color: '#ffd740', label: 'Micro Cap'       },
  no_setup_signal:        { color: '#888',    label: 'No Setup'        },
  no_catalyst:            { color: '#888',    label: 'No Catalyst'     },
};
const REGIME_COLOR = {
  RISK_ON:  '#00e676', RISK_OFF: '#ff5252', FEAR: '#ff6d00',
  ROTATION: '#ffd740', NEUTRAL:  '#888',
};
const PHASE_COLOR = {
  CONFIRMED_STRUCTURE:  { color: '#00e676', label: 'CONFIRMED'       },
  TRIGGERED_STRUCTURE:  { color: '#ff8800', label: 'TRIGGERED'       },
  EARLY_STRUCTURE:      { color: '#ffd600', label: 'EARLY STRUCTURE' },
  SETUP_PHASE:          { color: '#00b0ff', label: 'SETUP PHASE'     },
  IMPULSE_ONLY:         { color: '#e040fb', label: 'IMPULSE ONLY'    },
  BROKEN:               { color: '#ff9800', label: 'BROKEN SETUP'    },
  NO_STRUCTURE_IMPULSE: { color: '#888',    label: 'NO STR / IMPULSE'},
  TRUE_NONE:            { color: '#555',    label: 'TRUE NONE'       },
  DEGRADED:             { color: '#ff5252', label: 'DEGRADED'        },
};
const ADVISORY_LABEL = {
  moderate_setup_age_strength: 'Mod-Age Setup',
  np_weak_with_setup_context:  'Early Structure',
  np_l34_pure_strength:        'L34 Pure',
  np_moderate_freshness:       'Mod Freshness',
  np_fresh_early:              'Fresh Entry',
  np_weak_elevated:            'NP Weak↑',
  np_none_caution:             'NP None ⚠',
  watch_fri34_setup_strength:  'FRI34 Strength',
  bq_medium_bucket:            'BQ Mid',
  ce_compressed_base_caution:  'Compressed ⚠',
  ce_expansion_start_weak:     'Exp Start (weak)',
  borderline_high_ftr:         'High FTR',
};

function SecCard({ title, children }) {
  return (
    <div className={styles.secCard}>
      <div className={styles.secTitle}>{title}</div>
      {children}
    </div>
  );
}

function ScorePip({ label, value, color }) {
  return (
    <div className={styles.scorePip}>
      <span className={styles.scorePipVal} style={{ color }}>{fmt(value, 0)}</span>
      <span className={styles.scorePipLbl}>{label}</span>
    </div>
  );
}

function SigChip({ label, exists, age, maxFresh }) {
  const fresh  = exists && age != null && age <= maxFresh;
  const stale  = exists && age != null && age > maxFresh;
  const absent = !exists;
  return (
    <div className={styles.sigChip} data-state={absent ? 'absent' : fresh ? 'fresh' : 'stale'}>
      <span className={styles.sigChipLabel}>{label}</span>
      {exists && <span className={styles.sigChipAge}>-{age}</span>}
      <span className={styles.sigChipDot} />
    </div>
  );
}

// ── Section renderers ─────────────────────────────────────────────────────────

function S1_Identity({ identity, np }) {
  const lbl   = np?.new_pump_label || 'NEW_PUMP_NONE';
  const lcfg  = LABEL_COLOR[lbl] || LABEL_COLOR.NEW_PUMP_NONE;
  const score = np?.new_pump_score;
  const seq   = np?.new_pump_sequence_label;
  return (
    <div className={styles.identity}>
      <div className={styles.identityTop}>
        <div>
          <span className={styles.symbolBig}>{identity?.symbol}</span>
          {identity?.exchange && (
            <span className={styles.exchangeTag}>{identity.exchange}</span>
          )}
        </div>
        <div className={styles.identityScoreBlock}>
          <span className={styles.scoreNum} style={{ color: SCORE_COLOR(score) }}>
            {fmt(score, 1)}
          </span>
          <span className={styles.labelBadge} style={{ color: lcfg.color, background: lcfg.bg }}>
            {LABEL_SHORT[lbl] || lbl}
          </span>
        </div>
      </div>
      {identity?.company_name && (
        <div className={styles.companyName}>{identity.company_name}</div>
      )}
      <div className={styles.identityMeta}>
        {identity?.sector   && <span>{identity.sector}</span>}
        {identity?.industry && <span>{identity.industry}</span>}
        {identity?.country  && <span>{identity.country}</span>}
      </div>
      <div className={styles.identityPriceRow}>
        {identity?.current_price != null && (
          <span className={styles.priceTag}>${fmt(identity.current_price, 2)}</span>
        )}
        {identity?.market_cap && (
          <span className={styles.mcapTag}>{fmtM(identity.market_cap)}</span>
        )}
        {seq && (
          <span className={styles.seqBadge}>{seq.replace(/_/g, ' ')}</span>
        )}
      </div>
    </div>
  );
}

function S2_WhyRanked({ np }) {
  if (!np) return null;
  const { new_pump_setup_score: setup, new_pump_trigger_score: trig,
          new_pump_confirm_score: conf, new_pump_modifier_score: mod,
          explanation } = np;
  const total = np.new_pump_score || 0;
  return (
    <SecCard title="Why New Pump Ranked It">
      <div className={styles.scoreRow}>
        <ScorePip label="Setup"   value={setup} color="#44ff88" />
        <ScorePip label="Trigger" value={trig}  color="#ffd600" />
        <ScorePip label="Confirm" value={conf}  color="#00e5ff" />
        <ScorePip label="Mod"     value={mod}   color="#aaa"    />
        <ScorePip label="TOTAL"   value={total} color={SCORE_COLOR(total)} />
      </div>
      {explanation?.length > 0 && (
        <ul className={styles.explList}>
          {explanation.map((e, i) => <li key={i}>{e}</li>)}
        </ul>
      )}
    </SecCard>
  );
}

function S3_SignalTimeline({ signal_timeline: tl, np }) {
  if (!tl && !np) return null;
  const age_l34   = (tl || np)?.l34?.age   ?? np?.age_l34;
  const age_fri34 = (tl || np)?.fri34?.age ?? np?.age_fri34;
  const age_g4    = (tl || np)?.g4?.age    ?? np?.age_g4;
  const age_b2    = (tl || np)?.b2?.age    ?? np?.age_b2;
  const has_l34   = (tl || np)?.l34?.exists ?? np?.has_l34;
  const has_fri34 = (tl || np)?.fri34?.exists ?? np?.has_fri34;
  const has_g4    = (tl || np)?.g4?.exists ?? np?.has_g4;
  const has_b2    = (tl || np)?.b2?.exists ?? np?.has_b2;
  const notes     = tl?.notes || [];
  return (
    <SecCard title="Signal Timeline">
      <div className={styles.sigStrip}>
        <SigChip label="L34"   exists={has_l34}   age={age_l34}   maxFresh={10} />
        <div className={styles.sigArrow}>→</div>
        <SigChip label="FRI34" exists={has_fri34} age={age_fri34} maxFresh={10} />
        <div className={styles.sigArrow}>→</div>
        <SigChip label="G4"    exists={has_g4}    age={age_g4}    maxFresh={5}  />
        <div className={styles.sigArrow}>→</div>
        <SigChip label="B2"    exists={has_b2}    age={age_b2}    maxFresh={5}  />
      </div>
      {notes.length > 0 && (
        <ul className={styles.notesList}>
          {notes.map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      )}
    </SecCard>
  );
}

function S4_CompanySummary({ company_summary: cs }) {
  if (!cs?.sector && !cs?.industry && !cs?.description) return null;
  return (
    <SecCard title="Company">
      {cs.description && <p className={styles.companyDesc}>{cs.description}</p>}
      <div className={styles.identityMeta}>
        {cs.sector   && <span>{cs.sector}</span>}
        {cs.industry && <span>{cs.industry}</span>}
      </div>
    </SecCard>
  );
}

function S5_News({ news }) {
  if (!news) return null;
  const { headlines, catalyst_summary, verdict, has_real_news, count_7d } = news;
  const verdictColor = {
    strong_catalyst:       '#00e676', mixed_catalyst:       '#ffd740',
    no_meaningful_catalyst:'#888',    negative_catalyst:    '#ff5252',
  }[verdict] || '#888';
  return (
    <SecCard title="News / Catalyst">
      <div className={styles.newsMeta}>
        <span style={{ color: verdictColor, fontWeight: 700, fontSize: 10, letterSpacing: '0.06em' }}>
          {verdict?.replace(/_/g, ' ').toUpperCase()}
        </span>
        {catalyst_summary && (
          <span className={styles.catalystSummary}>{catalyst_summary}</span>
        )}
        {!has_real_news && count_7d === 0 && (
          <span className={styles.noNews}>No meaningful news found</span>
        )}
      </div>
      {headlines?.length > 0 && (
        <div className={styles.headlineList}>
          {headlines.slice(0, 5).map((h, i) => (
            <div key={i} className={styles.headline}>
              <div className={styles.headlineMeta}>
                {h.tag && (
                  <span className={styles.headlineTag}>{h.tag}</span>
                )}
                <span className={styles.headlineSource}>{h.source}</span>
                {h.hours_ago != null && (
                  <span className={styles.headlineAge}>
                    {h.hours_ago < 24 ? `${h.hours_ago}h ago` : `${Math.round(h.hours_ago / 24)}d ago`}
                  </span>
                )}
                <span className={`${styles.sentDot} ${styles['sent_' + (h.sentiment || 'neutral')]}`} />
              </div>
              {h.url ? (
                <a href={h.url} target="_blank" rel="noreferrer" className={styles.headlineTitle}>
                  {h.title}
                </a>
              ) : (
                <div className={styles.headlineTitle}>{h.title}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </SecCard>
  );
}

function S6_Technical({ technical_context: tc }) {
  if (!tc || Object.keys(tc).length === 0) return null;
  const stackColor = {
    full_bull: '#00e676', partial_bull: '#aed581',
    mixed: '#ffd740', partial_bear: '#ff9800', full_bear: '#ff5252',
  }[tc.ema_stack] || '#888';

  const rows = [
    ['EMA Stack',       tc.ema_stack?.replace(/_/g, ' ') || '—', stackColor],
    ['EMA Spread',      tc.ema_spread_pct != null ? `${tc.ema_spread_pct > 0 ? '+' : ''}${tc.ema_spread_pct}%` : '—', tc.ema_spread_pct > 30 ? '#ff9800' : '#ccc'],
    ['vs EMA50',        tc.above_ema50  != null ? (tc.above_ema50  ? 'Above' : 'Below') : '—', tc.above_ema50  ? '#00e676' : '#ff5252'],
    ['vs EMA200',       tc.above_ema200 != null ? (tc.above_ema200 ? 'Above' : 'Below') : '—', tc.above_ema200 ? '#00e676' : '#ff5252'],
    ['Vol Z-Score',     tc.volume_z     != null ? fmt(tc.volume_z, 2) : '—', Math.abs(tc.volume_z || 0) > 2 ? '#ffd740' : '#ccc'],
    ['Avg $-Volume',    tc.avg_dv_20d   != null ? fmtM(tc.avg_dv_20d) : '—', '#ccc'],
    ['DV Ratio',        tc.dv_ratio     != null ? `${fmt(tc.dv_ratio, 2)}×` : '—', (tc.dv_ratio || 0) >= 2 ? '#ffd600' : '#ccc'],
  ];
  return (
    <SecCard title="Technical Context">
      <div className={styles.techGrid}>
        {rows.map(([lbl, val, col]) => (
          <div key={lbl} className={styles.techRow}>
            <span className={styles.techLbl}>{lbl}</span>
            <span className={styles.techVal} style={{ color: col }}>{val}</span>
          </div>
        ))}
      </div>
    </SecCard>
  );
}

function S7_Market({ market_context: mc }) {
  if (!mc?.regime) return null;
  const regColor = REGIME_COLOR[mc.regime] || '#888';
  return (
    <SecCard title="Market Context">
      <div className={styles.regimeRow}>
        <span style={{ color: regColor, fontWeight: 800, fontSize: 11, letterSpacing: '0.07em' }}>
          {mc.regime?.replace(/_/g, ' ')}
        </span>
        {mc.recommendation && (
          <span className={styles.regimeRec}>{mc.recommendation}</span>
        )}
      </div>
      {mc.strong_sectors?.length > 0 && (
        <div className={styles.sectorRow}>
          <span className={styles.sectorHdr} style={{ color: '#00e676' }}>Strong</span>
          {mc.strong_sectors.slice(0, 4).map(s => <span key={s} className={styles.sectorPill}>{s}</span>)}
        </div>
      )}
      {mc.weak_sectors?.length > 0 && (
        <div className={styles.sectorRow}>
          <span className={styles.sectorHdr} style={{ color: '#ff5252' }}>Weak</span>
          {mc.weak_sectors.slice(0, 4).map(s => <span key={s} className={styles.sectorPill}>{s}</span>)}
        </div>
      )}
    </SecCard>
  );
}

function S8_AI({ ai_analysis: ai }) {
  if (!ai) return (
    <SecCard title="AI Analysis">
      <span className={styles.dimText}>No AI analysis available for this ticker.</span>
    </SecCard>
  );
  const fields = [
    ['Bull Case',       ai.bull_case,        '#00e676'],
    ['Bear Case',       ai.bear_case,        '#ff5252'],
    ['Main Risk',       ai.main_risk,        '#ff9800'],
    ['Confirms',        ai.what_confirms,    '#aed581'],
    ['Invalidates',     ai.what_invalidates, '#ff7043'],
  ];
  return (
    <SecCard title="AI Analysis">
      {fields.map(([lbl, val, col]) => val ? (
        <div key={lbl} className={styles.aiRow}>
          <span className={styles.aiLbl} style={{ color: col }}>{lbl}</span>
          <span className={styles.aiVal}>{val}</span>
        </div>
      ) : null)}
    </SecCard>
  );
}

function S9_RedFlags({ red_flags: flags }) {
  if (!flags?.length) return null;
  return (
    <SecCard title="Red Flags">
      <div className={styles.flagsRow}>
        {flags.map(f => {
          const cfg = FLAG_CFG[f] || { color: '#888', label: f.replace(/_/g, ' ') };
          return (
            <span key={f} className={styles.flagPill} style={{ color: cfg.color, borderColor: cfg.color + '55', background: cfg.color + '14' }}>
              {cfg.label}
            </span>
          );
        })}
      </div>
    </SecCard>
  );
}

function S10_Verdict({ final_verdict: fv }) {
  if (!fv) return null;
  const cfg = VERDICT_CFG[fv.verdict] || { color: '#888', label: fv.verdict?.toUpperCase() };
  return (
    <div className={styles.verdictBlock} style={{ borderColor: cfg.color + '55', background: cfg.color + '0d' }}>
      <div className={styles.verdictTop}>
        <span className={styles.verdictLabel} style={{ color: cfg.color }}>{cfg.label}</span>
        <span className={styles.verdictReason}>{fv.short_reason}</span>
      </div>
      {fv.key_confirmation_note && (
        <div className={styles.verdictNote}>
          <span className={styles.verdictNoteHdr} style={{ color: '#00e676' }}>Confirm: </span>
          {fv.key_confirmation_note}
        </div>
      )}
      {fv.invalidation_note && (
        <div className={styles.verdictNote}>
          <span className={styles.verdictNoteHdr} style={{ color: '#ff5252' }}>Invalidate: </span>
          {fv.invalidation_note}
        </div>
      )}
    </div>
  );
}

function S11_StructurePhase({ np }) {
  if (!np) return null;
  const phase    = np.structure_phase;
  const score    = np.structure_score;
  const advisory = np.structure_advisory || [];
  const dflags   = np.decision_flags    || [];
  const allFlags = [...advisory, ...dflags].filter(Boolean);
  if (!phase && !allFlags.length) return null;
  const pcfg = PHASE_COLOR[phase] || { color: '#888', label: phase || '—' };
  const scoreColor = score >= 70 ? '#00e676' : score >= 40 ? '#ffd600' : '#888';
  return (
    <SecCard title="Structure Phase">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: allFlags.length ? 8 : 0 }}>
        <span style={{
          padding: '2px 10px', borderRadius: 4, fontSize: 11, fontWeight: 700,
          color: pcfg.color, background: pcfg.color + '1a', letterSpacing: '0.05em',
        }}>{pcfg.label}</span>
        {score != null && (
          <span style={{ fontSize: 12, color: '#888' }}>
            score <span style={{ color: scoreColor, fontWeight: 600 }}>{score}</span>
          </span>
        )}
      </div>
      {allFlags.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
          {allFlags.map((f, i) => (
            <span key={i} style={{
              fontSize: 10, padding: '2px 6px', borderRadius: 3,
              background: '#ffffff0c', color: '#aaa',
            }}>{ADVISORY_LABEL[f] || f.replace(/_/g, ' ')}</span>
          ))}
        </div>
      )}
    </SecCard>
  );
}

// ── Main drawer ───────────────────────────────────────────────────────────────

export default function NpDrawer({ sym, dataCache, loading, error, onClose }) {
  if (!sym) return null;
  const payload = dataCache?.[sym];

  return (
    <>
      <div className={styles.overlay} onClick={onClose} />
      <div className={styles.drawer}>
        <div className={styles.drawerHeader}>
          <span className={styles.drawerSym}>{sym}</span>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className={styles.drawerBody}>
          {loading && !payload && (
            <div className={styles.stateMsg}>Loading {sym}…</div>
          )}
          {error && !payload && (
            <div className={styles.stateError}>Error: {error}</div>
          )}
          {payload && !payload.ok && (
            <div className={styles.stateError}>{payload.error || 'Symbol not available'}</div>
          )}
          {payload?.ok && (
            <>
              <S1_Identity identity={payload.identity} np={payload.new_pump} />
              <S2_WhyRanked np={payload.new_pump} />
              <S11_StructurePhase np={payload.new_pump} />
              <S3_SignalTimeline signal_timeline={payload.signal_timeline} np={payload.new_pump} />
              <S4_CompanySummary company_summary={payload.company_summary} />
              <S5_News news={payload.news} />
              <S6_Technical technical_context={payload.technical_context} />
              <S7_Market market_context={payload.market_context} />
              <S8_AI ai_analysis={payload.ai_analysis} />
              <S9_RedFlags red_flags={payload.red_flags} />
              <S10_Verdict final_verdict={payload.final_verdict} />
            </>
          )}
        </div>
      </div>
    </>
  );
}
