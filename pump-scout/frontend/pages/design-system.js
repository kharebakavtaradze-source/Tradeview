/**
 * Design System — Material Design 3 Style Guide
 * Single source of truth for all tokens, components, and patterns.
 * Edit globals.css or DesignSystem.module.css here to change the system.
 */
import Head from 'next/head';
import AppNav from '../components/AppNav';
import styles from '../styles/DesignSystem.module.css';

// ── Data ──────────────────────────────────────────────────────────────────────

const MD3_COLORS = [
  { name: 'Primary',               hex: '#cfbcff', var: '--md-primary',              on: '#381e72' },
  { name: 'On Primary',            hex: '#381e72', var: '--md-on-primary',            on: '#cfbcff' },
  { name: 'Primary Container',     hex: '#4f378b', var: '--md-primary-container',     on: '#ecdcff' },
  { name: 'On Primary Container',  hex: '#ecdcff', var: '--md-on-primary-container',  on: '#381e72' },
  { name: 'Secondary',             hex: '#80d8ec', var: '--md-secondary',             on: '#003640' },
  { name: 'On Secondary',          hex: '#003640', var: '--md-on-secondary',          on: '#80d8ec' },
  { name: 'Sec. Container',        hex: '#004e5c', var: '--md-secondary-container',   on: '#b6eeff' },
  { name: 'Tertiary',              hex: '#f9bd48', var: '--md-tertiary',              on: '#3f2e00' },
  { name: 'Tert. Container',       hex: '#5a4200', var: '--md-tertiary-container',    on: '#ffdea1' },
  { name: 'Error',                 hex: '#ffb4ab', var: '--md-error',                 on: '#690005' },
  { name: 'Error Container',       hex: '#93000a', var: '--md-error-container',       on: '#ffdad6' },
];

const MD3_SURFACES = [
  { name: 'Surface Dim',              hex: '#07070f', var: '--md-surface-dim' },
  { name: 'Surface',                  hex: '#0d0d1e', var: '--md-surface' },
  { name: 'Surface Container Low',    hex: '#0d0d1e', var: '--md-surface-container-low' },
  { name: 'Surface Container',        hex: '#121228', var: '--md-surface-container' },
  { name: 'Surface Container High',   hex: '#181836', var: '--md-surface-container-high' },
  { name: 'Surface Container Highest',hex: '#1e1e42', var: '--md-surface-container-highest' },
  { name: 'Surface Bright',           hex: '#1e1e38', var: '--md-surface-bright' },
  { name: 'On Surface',               hex: '#eaeaf6', var: '--md-on-surface' },
  { name: 'On Surface Variant',       hex: '#9898c0', var: '--md-on-surface-variant' },
  { name: 'Outline',                  hex: '#222246', var: '--md-outline' },
  { name: 'Outline Variant',          hex: '#1a1a32', var: '--md-outline-variant' },
];

const SIGNAL_COLORS = [
  { name: 'Lime',   hex: '#28d971', var: '--lime',   use: 'Bullish · Positive · Long · Base tier' },
  { name: 'Cyan',   hex: '#00d4f5', var: '--cyan',   use: 'Informational · ARM tier' },
  { name: 'Gold',   hex: '#f5c518', var: '--gold',   use: 'FIRE tier · Highest momentum' },
  { name: 'Amber',  hex: '#f5a623', var: '--amber',  use: 'Watch · Warning · Caution' },
  { name: 'Red',    hex: '#f03e5c', var: '--red',    use: 'Danger · Bearish · Loss' },
  { name: 'Violet', hex: '#c084fc', var: '--violet', use: 'Stealth · Special signals' },
];

const TYPE_SCALE = [
  { role: 'display-lg',  label: 'Display Large',   size: '30px', weight: '400', tracking: '-0.02em', sample: 'Market Scanner' },
  { role: 'display-md',  label: 'Display Medium',  size: '24px', weight: '400', tracking: '0',       sample: 'Market Scanner' },
  { role: 'display-sm',  label: 'Display Small',   size: '20px', weight: '400', tracking: '0',       sample: 'Market Scanner' },
  { role: 'headline-lg', label: 'Headline Large',  size: '22px', weight: '800', tracking: '-0.01em', sample: 'Ticker Watchlist' },
  { role: 'headline-md', label: 'Headline Medium', size: '18px', weight: '700', tracking: '0',       sample: 'Ticker Watchlist' },
  { role: 'headline-sm', label: 'Headline Small',  size: '15px', weight: '700', tracking: '0',       sample: 'Ticker Watchlist' },
  { role: 'title-lg',    label: 'Title Large',     size: '14px', weight: '600', tracking: '0.01em',  sample: 'Scan Candidates · 42 results' },
  { role: 'title-md',    label: 'Title Medium',    size: '13px', weight: '600', tracking: '0.01em',  sample: 'Scan Candidates · 42 results' },
  { role: 'title-sm',    label: 'Title Small',     size: '11px', weight: '600', tracking: '0.04em',  sample: 'Scan Candidates · 42 results' },
  { role: 'body-lg',     label: 'Body Large',      size: '13px', weight: '400', tracking: '0.02em',  sample: 'Volume confirms breakout, ribbon coiled, OBV rising.' },
  { role: 'body-md',     label: 'Body Medium',     size: '11px', weight: '400', tracking: '0.025em', sample: 'Volume confirms breakout, ribbon coiled, OBV rising.' },
  { role: 'body-sm',     label: 'Body Small',      size: '9px',  weight: '400', tracking: '0.04em',  sample: 'Volume confirms breakout, ribbon coiled, OBV rising.' },
  { role: 'label-lg',    label: 'Label Large',     size: '12px', weight: '700', tracking: '0.07em',  sample: 'STRONG WATCH' },
  { role: 'label-md',    label: 'Label Medium',    size: '10px', weight: '700', tracking: '0.07em',  sample: 'STRONG WATCH' },
  { role: 'label-sm',    label: 'Label Small',     size: '9px',  weight: '700', tracking: '0.08em',  sample: 'STRONG WATCH' },
];

const SHAPES = [
  { label: 'None',   token: '--md-corner-none', px: '0px',    size: 56 },
  { label: 'XS',     token: '--md-corner-xs',   px: '4px',    size: 56 },
  { label: 'SM',     token: '--md-corner-sm',   px: '8px',    size: 64 },
  { label: 'MD',     token: '--md-corner-md',   px: '12px',   size: 72 },
  { label: 'LG',     token: '--md-corner-lg',   px: '16px',   size: 72 },
  { label: 'XL',     token: '--md-corner-xl',   px: '28px',   size: 80 },
  { label: 'Full',   token: '--md-corner-full', px: '9999px', size: 56 },
];

const ELEVATIONS = [
  { level: 0, name: 'Level 0',  desc: 'Default surface. No tint.',           tint: 'none',          bg: '#0d0d1e' },
  { level: 1, name: 'Level 1',  desc: 'Menus, cards. 5% primary tint.',      tint: '5% primary',    bg: '#0f0e22' },
  { level: 2, name: 'Level 2',  desc: 'Floating panels. 8% primary tint.',   tint: '8% primary',    bg: '#111025' },
  { level: 3, name: 'Level 3',  desc: 'Modal dialogs. 11% primary tint.',    tint: '11% primary',   bg: '#131127' },
  { level: 4, name: 'Level 4',  desc: 'Navigation bars. 12% primary tint.',  tint: '12% primary',   bg: '#141228' },
  { level: 5, name: 'Level 5',  desc: 'Tooltips, FAB. 14% primary tint.',    tint: '14% primary',   bg: '#16132a' },
];

const MOTIONS = [
  {
    name: 'Emphasized',
    desc: 'Standard in-screen transitions',
    token: '--md-ease-emphasized',
    curve: 'cubic-bezier(0.2, 0, 0, 1)',
    ballClass: 'motionBallEmph',
    dur: '300ms',
  },
  {
    name: 'Emphasized Decelerate',
    desc: 'Elements entering the screen',
    token: '--md-ease-emphasized-decel',
    curve: 'cubic-bezier(0.05, 0.7, 0.1, 1.0)',
    ballClass: 'motionBallDecel',
    dur: '350ms',
  },
  {
    name: 'Emphasized Accelerate',
    desc: 'Elements exiting the screen',
    token: '--md-ease-emphasized-accel',
    curve: 'cubic-bezier(0.3, 0.0, 0.8, 0.15)',
    ballClass: 'motionBallAccel',
    dur: '200ms',
  },
  {
    name: 'Standard',
    desc: 'Quick UI interactions',
    token: '--md-ease-standard',
    curve: 'cubic-bezier(0.2, 0, 0, 1)',
    ballClass: 'motionBallStd',
    dur: '200ms',
  },
];

const DURATIONS = [
  { name: 'Short 1', token: '--md-dur-short1',  ms: '50ms'  },
  { name: 'Short 2', token: '--md-dur-short2',  ms: '100ms' },
  { name: 'Short 3', token: '--md-dur-short3',  ms: '150ms' },
  { name: 'Short 4', token: '--md-dur-short4',  ms: '200ms' },
  { name: 'Medium 1',token: '--md-dur-medium1', ms: '250ms' },
  { name: 'Medium 2',token: '--md-dur-medium2', ms: '300ms' },
  { name: 'Medium 3',token: '--md-dur-medium3', ms: '350ms' },
  { name: 'Medium 4',token: '--md-dur-medium4', ms: '400ms' },
  { name: 'Long 1',  token: '--md-dur-long1',   ms: '450ms' },
  { name: 'Long 2',  token: '--md-dur-long2',   ms: '500ms' },
  { name: 'Long 3',  token: '--md-dur-long3',   ms: '550ms' },
  { name: 'Long 4',  token: '--md-dur-long4',   ms: '600ms' },
];

const STATE_LAYERS = [
  { label: 'Hover',   opacity: '8%',  css: '0.08' },
  { label: 'Pressed', opacity: '12%', css: '0.12' },
  { label: 'Focused', opacity: '12%', css: '0.12' },
  { label: 'Dragged', opacity: '16%', css: '0.16' },
];

const TIERS = [
  { name: 'FIRE', color: '#f5c518', bg: 'rgba(245,197,24,0.12)', border: 'rgba(245,197,24,0.3)',  vars: '--fire · --gold · --gold-dim · --gold-border',  desc: 'Highest momentum. Multi-confirmation ignition.' },
  { name: 'ARM',  color: '#00d4f5', bg: 'rgba(0,212,245,0.10)',  border: 'rgba(0,212,245,0.28)',  vars: '--arm · --cyan · --cyan-dim · --cyan-border',   desc: 'Active regime momentum. Strong ribbon.' },
  { name: 'BASE', color: '#28d971', bg: 'rgba(40,217,113,0.10)', border: 'rgba(40,217,113,0.28)', vars: '--base · --lime · --lime-dim · --lime-border',  desc: 'Confirmed bullish structure. Primary long.' },
  { name: 'WATCH',color: '#f5a623', bg: 'rgba(245,166,35,0.10)', border: 'rgba(245,166,35,0.28)', vars: '--watch · --amber · --amber-dim · --amber-border', desc: 'Caution. Mixed or early signals.' },
  { name: 'LOW',  color: '#888888', bg: 'rgba(100,100,100,0.10)',border: 'rgba(100,100,100,0.25)',vars: '--text-muted · --border2',                       desc: 'Low quality. Insufficient confirmation.' },
];

// ── Section anchor nav items ──────────────────────────────────────────────────

const NAV_ITEMS = [
  { href: '#colors',      label: 'Colors' },
  { href: '#typography',  label: 'Typography' },
  { href: '#shape',       label: 'Shape' },
  { href: '#elevation',   label: 'Elevation' },
  { href: '#motion',      label: 'Motion' },
  { href: '#states',      label: 'State Layers' },
  { href: '#components',  label: 'Components' },
  { href: '#tiers',       label: 'Tier System' },
];

// ── Sub-components ────────────────────────────────────────────────────────────

function ColorSwatch({ name, hex, varName, on }) {
  return (
    <div className={styles.colorSwatch}>
      <div
        className={styles.swatchBlock}
        style={{ background: hex }}
      >
        <span className={styles.swatchBlockLabel}>{hex}</span>
      </div>
      <div className={styles.swatchMeta}>
        <div className={styles.swatchName}>{name}</div>
        <div className={styles.swatchHex}>{varName}</div>
      </div>
    </div>
  );
}

function TypeRow({ role, label, size, weight, tracking, sample }) {
  const cls = `md-${role}`;
  return (
    <div className={styles.typeRow}>
      <span className={styles.typeRole}>.{cls}</span>
      <span className={styles.typeSample} style={{ fontSize: size, fontWeight: weight, letterSpacing: tracking }}>
        {sample}
      </span>
      <span className={styles.typeMeta}>{size}</span>
      <span className={styles.typeMeta}>{weight}</span>
      <span className={styles.typeMeta} style={{ fontFamily: 'var(--font-mono)', fontSize: 9 }}>{tracking}</span>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function DesignSystemPage() {
  return (
    <>
      <Head><title>Design System · Pump Scout</title></Head>
      <div className={styles.page}>
        <AppNav />

        {/* Hero */}
        <div className={styles.hero}>
          <div className={styles.heroEyebrow}>Pump Scout</div>
          <h1 className={styles.heroTitle}>Design System</h1>
          <p className={styles.heroSub}>
            Material Design 3 dark scheme — tokens, components, motion, and patterns.
            Edit <code>globals.css</code> or <code>DesignSystem.module.css</code> to change the system globally.
          </p>
        </div>

        {/* In-page section nav */}
        <nav className={styles.sectionNav}>
          {NAV_ITEMS.map(n => (
            <a key={n.href} href={n.href} className={styles.sectionNavLink}>{n.label}</a>
          ))}
        </nav>

        <div className={styles.content}>

          {/* ══ COLORS ══════════════════════════════════════════════════════ */}
          <section id="colors" className={styles.section}>
            <h2 className={styles.sectionTitle}>Color System</h2>
            <p className={styles.sectionDesc}>
              MD3 color roles — dark scheme. All UI components reference these tokens.
              Changing a token here cascades through the entire app.
            </p>

            <div className={styles.colorGroupLabel}>Color Roles</div>
            <div className={styles.colorGrid}>
              {MD3_COLORS.map(c => (
                <ColorSwatch key={c.var} name={c.name} hex={c.hex} varName={c.var} on={c.on} />
              ))}
            </div>

            <div className={styles.colorGroupLabel}>Surface Scale</div>
            <div className={styles.colorGrid}>
              {MD3_SURFACES.map(c => (
                <ColorSwatch key={c.var} name={c.name} hex={c.hex} varName={c.var} />
              ))}
            </div>

            <div className={styles.colorGroupLabel}>Signal Colors — Trading Domain</div>
            <div className={styles.signalGrid}>
              {SIGNAL_COLORS.map(s => (
                <div key={s.var} className={styles.signalChip}>
                  <div className={styles.signalDot} style={{ background: s.hex }} />
                  <div className={styles.signalInfo}>
                    <div className={styles.signalName} style={{ color: s.hex }}>{s.name}</div>
                    <div className={styles.signalVar}>{s.var}</div>
                    <div className={styles.signalVar} style={{ marginTop: 2, opacity: 0.7 }}>{s.use}</div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* ══ TYPOGRAPHY ══════════════════════════════════════════════════ */}
          <section id="typography" className={styles.section}>
            <h2 className={styles.sectionTitle}>Typography Scale</h2>
            <p className={styles.sectionDesc}>
              13 type roles from Display to Label. Use <code>.md-[role]</code> utility classes
              or reference token vars directly. Trading-density adapted from MD3 spec.
            </p>

            <div className={styles.typeRowHead}>
              <span className={styles.typeColHead}>Class</span>
              <span className={styles.typeColHead}>Sample</span>
              <span className={styles.typeColHead}>Size</span>
              <span className={styles.typeColHead}>Wt</span>
              <span className={styles.typeColHead}>Track</span>
            </div>
            {TYPE_SCALE.map(t => <TypeRow key={t.role} {...t} />)}
          </section>

          {/* ══ SHAPE ═══════════════════════════════════════════════════════ */}
          <section id="shape" className={styles.section}>
            <h2 className={styles.sectionTitle}>Shape Scale</h2>
            <p className={styles.sectionDesc}>
              MD3 corner radius scale. Maps to legacy <code>--r-*</code> tokens for backward compat.
              Hover a swatch to see filled state.
            </p>
            <div className={styles.shapeGrid}>
              {SHAPES.map(s => (
                <div key={s.label} className={styles.shapeItem}>
                  <div
                    className={styles.shapeBox}
                    style={{
                      width: s.size,
                      height: s.size,
                      borderRadius: s.px,
                    }}
                  >
                    {s.px}
                  </div>
                  <div className={styles.shapeLabel}>{s.label}</div>
                  <div className={styles.tokenValue}>{s.token}</div>
                </div>
              ))}
            </div>
          </section>

          {/* ══ ELEVATION ═══════════════════════════════════════════════════ */}
          <section id="elevation" className={styles.section}>
            <h2 className={styles.sectionTitle}>Elevation</h2>
            <p className={styles.sectionDesc}>
              MD3 dark theme conveys elevation via a primary-color tint overlay on the surface,
              not shadow depth. Higher levels = more violet tint. Hover cards to see lift.
            </p>
            <div className={styles.elevGrid}>
              {ELEVATIONS.map(e => (
                <div
                  key={e.level}
                  className={styles.elevCard}
                  style={{
                    background: `linear-gradient(rgba(124,90,245,${e.level * 0.025}), rgba(124,90,245,${e.level * 0.025})), ${e.bg}`,
                    boxShadow: e.level >= 3 ? 'var(--shadow-sm)' : 'none',
                  }}
                >
                  <div className={styles.elevLevel}>{e.level}</div>
                  <div className={styles.elevName}>{e.name}</div>
                  <div className={styles.elevDesc}>{e.desc}</div>
                  <div className={styles.elevTint}>.md-elev-{e.level} · {e.tint}</div>
                </div>
              ))}
            </div>
          </section>

          {/* ══ MOTION ══════════════════════════════════════════════════════ */}
          <section id="motion" className={styles.section}>
            <h2 className={styles.sectionTitle}>Motion</h2>
            <p className={styles.sectionDesc}>
              MD3 easing curves and duration scale. Hover the demo tracks to see the ball
              traverse with each easing function. All <code>--t-fast/std/slow</code> tokens now
              use MD3 curves — every existing component gets MD3 motion automatically.
            </p>

            <div className={styles.motionGrid}>
              {MOTIONS.map(m => (
                <div key={m.name} className={styles.motionCard}>
                  <div className={styles.motionName}>{m.name}</div>
                  <div className={styles.motionDesc}>{m.desc}</div>
                  <div className={styles.motionToken}>{m.token}</div>
                  <div className={styles.motionToken} style={{ marginBottom: 10 }}>{m.curve}</div>
                  <div
                    className={styles.motionDemoWrap}
                    style={{ '--ball-dur': m.dur }}
                  >
                    <div
                      className={`${styles.motionBall} ${styles[m.ballClass]}`}
                      style={{ transitionDuration: m.dur }}
                    />
                  </div>
                </div>
              ))}
            </div>

            <div className={styles.colorGroupLabel}>Duration Scale</div>
            <div className={styles.durationGrid}>
              {DURATIONS.map(d => (
                <div key={d.token} className={styles.durationItem}>
                  <div className={styles.durationMs}>{d.ms}</div>
                  <div className={styles.durationName}>{d.name}</div>
                  <div className={styles.tokenValue}>{d.token}</div>
                </div>
              ))}
            </div>
          </section>

          {/* ══ STATE LAYERS ════════════════════════════════════════════════ */}
          <section id="states" className={styles.section}>
            <h2 className={styles.sectionTitle}>State Layers</h2>
            <p className={styles.sectionDesc}>
              MD3 interactive states overlay primary color at defined opacities.
              Hover and click the cards below to see each state in action.
            </p>
            <div className={styles.stateGrid}>
              {STATE_LAYERS.map(s => (
                <div key={s.label} className={styles.stateCard}>
                  <div className={styles.stateLabel}>{s.label}</div>
                  <div className={styles.stateOpacity}>{s.opacity} primary</div>
                  <div className={styles.tokenValue} style={{ marginTop: 6, position: 'relative' }}>
                    opacity: {s.css}
                  </div>
                </div>
              ))}
              <div className={styles.stateCard}>
                <div className={styles.stateLabel}>Disabled</div>
                <div className={styles.stateOpacity} style={{ color: 'var(--text-muted)' }}>38% on-surface</div>
                <div className={styles.tokenValue} style={{ marginTop: 6, position: 'relative' }}>
                  opacity: 0.38
                </div>
              </div>
            </div>
          </section>

          {/* ══ COMPONENTS ══════════════════════════════════════════════════ */}
          <section id="components" className={styles.section}>
            <h2 className={styles.sectionTitle}>Components</h2>
            <p className={styles.sectionDesc}>
              All components use MD3 tokens. Use the global classes directly or compose
              them with CSS Modules. Every button has a built-in state layer.
            </p>

            {/* Buttons */}
            <div className={styles.componentGroup}>
              <div className={styles.componentGroupLabel}>Buttons</div>
              <div className={styles.btnRow}>
                <button className="md-btn md-btn-filled">Filled</button>
                <button className="md-btn md-btn-elevated">Elevated</button>
                <button className="md-btn md-btn-tonal">Tonal</button>
                <button className="md-btn md-btn-outlined">Outlined</button>
                <button className="md-btn md-btn-text">Text</button>
                <button className="md-btn md-btn-filled" disabled>Disabled</button>
              </div>
            </div>

            {/* Chips */}
            <div className={styles.componentGroup}>
              <div className={styles.componentGroupLabel}>Chips</div>
              <div className={styles.chipRow}>
                <button className="md-chip">Assist</button>
                <button className="md-chip md-chip-selected">Filter ✓</button>
                <button className="md-chip">Ribbon Coiled</button>
                <button className="md-chip md-chip-selected">Vol+ ✓</button>
                <button className="md-chip">CMF+</button>
                <button className="md-chip">Ignition ✓</button>
                <button className="md-chip">Early Setup</button>
                <button className="md-chip">BB Squeeze</button>
              </div>
            </div>

            {/* Badges */}
            <div className={styles.componentGroup}>
              <div className={styles.componentGroupLabel}>Badges</div>
              <div className={styles.badgeRow}>
                <span className={styles.demoBadge} style={{ color: '#00ff88', borderColor: 'rgba(0,255,136,0.4)', background: 'rgba(0,255,136,0.12)' }}>🔥 STRONG WATCH</span>
                <span className={styles.demoBadge} style={{ color: '#ffd600', borderColor: 'rgba(255,214,0,0.4)',  background: 'rgba(255,214,0,0.10)' }}>👁 WATCH</span>
                <span className={styles.demoBadge} style={{ color: '#00e5ff', borderColor: 'rgba(0,229,255,0.4)',  background: 'rgba(0,229,255,0.10)' }}>⚡ EARLY</span>
                <span className={styles.demoBadge} style={{ color: '#ff8800', borderColor: 'rgba(255,136,0,0.4)',  background: 'rgba(255,136,0,0.10)' }}>⚠ EXTENDED</span>
                <span className={styles.demoBadge} style={{ color: '#888',    borderColor: 'rgba(150,150,150,0.3)',background: 'rgba(100,100,100,0.10)' }}>⬇ LOW QUALITY</span>
                <span className={styles.demoBadge} style={{ color: 'var(--md-primary)', borderColor: 'var(--accent-border)', background: 'var(--accent-dim)' }}>HIGH CONF</span>
                <span className={styles.demoBadge} style={{ color: '#ffd600', borderColor: 'rgba(255,214,0,0.3)',  background: 'rgba(255,214,0,0.08)' }}>MEDIUM CONF</span>
                <span className={styles.demoBadge} style={{ color: '#888',    borderColor: 'rgba(150,150,150,0.25)',background: 'rgba(100,100,100,0.08)' }}>LOW CONF</span>
              </div>
            </div>

            {/* Cards */}
            <div className={styles.componentGroup}>
              <div className={styles.componentGroupLabel}>Cards</div>
              <div className={styles.cardDemoRow}>
                <div className={styles.demoCardElevated}>
                  <div className={styles.demoCardLabel}>Elevated</div>
                  <div className={styles.demoCardTitle}>AAPL · 🔥 STRONG WATCH</div>
                  <div className={styles.demoCardBody}>
                    Ribbon tightly coiled. Volume confirms breakout. OBV rising steadily.
                  </div>
                </div>
                <div className={styles.demoCardFilled}>
                  <div className={styles.demoCardLabel}>Filled</div>
                  <div className={styles.demoCardTitle}>TSLA · 👁 WATCH</div>
                  <div className={styles.demoCardBody}>
                    Early ignition detected. CMF positive. Confirm on volume expansion.
                  </div>
                </div>
                <div className={styles.demoCardOutlined}>
                  <div className={styles.demoCardLabel}>Outlined</div>
                  <div className={styles.demoCardTitle}>NVDA · ⚡ EARLY</div>
                  <div className={styles.demoCardBody}>
                    Pre-ignition setup forming. Ribbon compressing. RSI mid-range.
                  </div>
                </div>
              </div>
            </div>

            {/* Progress indicators */}
            <div className={styles.componentGroup}>
              <div className={styles.componentGroupLabel}>Progress Indicators</div>
              <div className={styles.progressWrap}>
                {[
                  { label: 'Primary',   color: 'var(--md-primary, var(--accent))',   pct: '72%' },
                  { label: 'Lime',      color: 'var(--lime)',                         pct: '88%' },
                  { label: 'Gold',      color: 'var(--gold)',                         pct: '55%' },
                  { label: 'Error',     color: 'var(--md-error, var(--red))',          pct: '30%' },
                ].map(p => (
                  <div key={p.label} className={styles.progressRow}>
                    <span className={styles.progressLabel}>{p.label}</span>
                    <div className={styles.progressTrack}>
                      <div
                        className={styles.progressFill}
                        style={{ width: p.pct, background: p.color }}
                      />
                    </div>
                    <span className={styles.tokenValue}>{p.pct}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Spinners */}
            <div className={styles.componentGroup}>
              <div className={styles.componentGroupLabel}>Circular Progress</div>
              <div className={styles.spinnerRow}>
                <div className={`${styles.spinnerDemo}`} style={{ borderTopColor: 'var(--md-primary, var(--accent))' }} />
                <div className={`${styles.spinnerDemo}`} style={{ borderTopColor: 'var(--lime)', width: 32, height: 32, borderWidth: 3 }} />
                <div className={`${styles.spinnerDemo} ${styles.spinnerSm}`} style={{ borderTopColor: 'var(--gold)' }} />
                <span className="md-body-md" style={{ color: 'var(--text-dim)' }}>
                  Use <code>.spinner-sm</code> or <code>styles.spinnerDemo</code>
                </span>
              </div>
            </div>
          </section>

          {/* ══ TIER SYSTEM ═════════════════════════════════════════════════ */}
          <section id="tiers" className={styles.section}>
            <h2 className={styles.sectionTitle}>Tier System</h2>
            <p className={styles.sectionDesc}>
              Trading-domain color tiers. Each tier maps to a signal color and provides
              three CSS tokens: base, dim background, and border.
            </p>
            <div className={styles.tierGrid}>
              {TIERS.map(t => (
                <div
                  key={t.name}
                  className={styles.tierCard}
                  style={{
                    background: t.bg,
                    borderColor: t.border,
                    boxShadow: `0 0 0 0 ${t.color}`,
                  }}
                >
                  <div className={styles.tierName} style={{ color: t.color }}>{t.name}</div>
                  <div className={styles.tierDesc}>{t.desc}</div>
                  <div className={styles.tierVars} style={{ color: t.color }}>{t.vars}</div>
                </div>
              ))}
            </div>
          </section>

        </div>
      </div>
    </>
  );
}
