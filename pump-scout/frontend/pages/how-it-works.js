import Head from 'next/head';
import Link from 'next/link';
import styles from '../styles/HowItWorks.module.css';

function Section({ id, title, children }) {
  return (
    <section className={styles.section} id={id}>
      <h2 className={styles.sectionTitle}>{title}</h2>
      {children}
    </section>
  );
}

function Block({ title, color, children }) {
  return (
    <div className={styles.block} style={{ borderLeftColor: color || 'var(--border2)' }}>
      {title && <div className={styles.blockTitle} style={{ color: color || 'var(--text-dim)' }}>{title}</div>}
      {children}
    </div>
  );
}

function TierRow({ emoji, name, color, score, description, conditions }) {
  return (
    <div className={styles.tierRow}>
      <div className={styles.tierHeader}>
        <span className={styles.tierBadge} style={{ color, borderColor: color, background: color + '18' }}>
          {emoji} {name}
        </span>
        <span className={styles.tierScore} style={{ color: 'var(--text-muted)' }}>score: {score}</span>
      </div>
      <p className={styles.tierDesc}>{description}</p>
      <ul className={styles.tierConditions}>
        {conditions.map((c, i) => <li key={i}>{c}</li>)}
      </ul>
    </div>
  );
}

function Indicator({ name, formula, meaning }) {
  return (
    <div className={styles.indicator}>
      <div className={styles.indicatorName}>{name}</div>
      <div className={styles.indicatorFormula}>{formula}</div>
      <div className={styles.indicatorMeaning}>{meaning}</div>
    </div>
  );
}

export default function HowItWorks() {
  return (
    <>
      <Head>
        <title>How It Works — Pump Scout</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      </Head>

      <div className={styles.container}>
        {/* Nav */}
        <nav className={styles.nav}>
          <Link href="/" className={styles.backLink}>← Back to Scanner</Link>
          <span className={styles.navTitle}>HOW IT WORKS</span>
        </nav>

        <div className={styles.hero}>
          <h1 className={styles.heroTitle}>🔍 PUMP SCOUT</h1>
          <p className={styles.heroSub}>
            Automated small-cap volume anomaly scanner.<br />
            Finds quiet accumulation before the pump using Wyckoff methodology + technical indicators.
          </p>
        </div>

        {/* TOC */}
        <nav className={styles.toc}>
          {[
            ['#data-sources', '1. Data Sources'],
            ['#scan-schedule', '2. Scan Schedule'],
            ['#indicators', '3. Indicators'],
            ['#tiers', '4. Signal Tiers'],
            ['#scoring', '5. Scoring Formula'],
            ['#wyckoff', '6. Wyckoff Regime'],
            ['#hype-monitor', '7. Hype Monitor'],
            ['#filters', '8. Filters & AI'],
          ].map(([href, label]) => (
            <a key={href} href={href} className={styles.tocLink}>{label}</a>
          ))}
        </nav>

        {/* 1. Data Sources */}
        <Section id="data-sources" title="1. Data Sources">
          <Block title="TICKER LIST" color="var(--cyan)">
            <p>Tickers are pulled in priority order:</p>
            <ol className={styles.ol}>
              <li>
                <strong>Finviz Screener</strong> — scrapes HTML from{' '}
                <code>finviz.com/screener.ashx</code> with filters:
                <ul className={styles.ul}>
                  <li>Cap: Small (under $2B market cap)</li>
                  <li>Geography: USA only</li>
                  <li>Avg Volume: over 300K</li>
                  <li>Price: $1 – $50</li>
                </ul>
                Paginated, fetches up to 500 tickers per scan.
              </li>
              <li>
                <strong>Yahoo Finance Screener</strong> — API fallback if Finviz is blocked.
                Queries <code>small_cap_gainers</code> predefined screen.
              </li>
              <li>
                <strong>Static List</strong> — curated small-cap US stocks (biotech, crypto miners,
                EV, energy, meme stocks) used if both live sources fail.
              </li>
            </ol>
          </Block>

          <Block title="OHLCV PRICE DATA" color="var(--green)">
            <p>
              Daily candles fetched from <strong>Yahoo Finance v8 API</strong> —
              6 months of history (≈125 trading days) per ticker.
            </p>
            <ul className={styles.ul}>
              <li>Concurrency: 5 tickers at a time to avoid rate limits</li>
              <li>Retry: up to 3 attempts per ticker on 429/timeout</li>
              <li>Minimum required: 60 candles — tickers with less are skipped</li>
            </ul>
          </Block>

          <Block title="PRE-MARKET / AFTER-HOURS" color="var(--gold)">
            <p>
              After scoring, all passing tickers are queried via <strong>Yahoo Finance v7 Quote API</strong>{' '}
              in batches of 50. Returns pre-market price and % change (4am–9:30am EST)
              or after-hours data (4pm–8pm EST). Shown on cards as{' '}
              <code className={styles.codePre}>PRE +2.1%</code> or <code className={styles.codePre}>AH -1.5%</code>.
            </p>
          </Block>
        </Section>

        {/* 2. Scan Schedule */}
        <Section id="scan-schedule" title="2. Scan Schedule">
          <Block color="var(--arm)">
            <div className={styles.scheduleGrid}>
              <div className={styles.scheduleItem}>
                <div className={styles.scheduleTime}>8:00 AM ET</div>
                <div className={styles.scheduleDesc}>Pre-market scan — catches overnight volume and gap setups before open</div>
              </div>
              <div className={styles.scheduleItem}>
                <div className={styles.scheduleTime}>9:30 AM ET</div>
                <div className={styles.scheduleDesc}>Market open scan — first confirmed volume of the session</div>
              </div>
              <div className={styles.scheduleItem}>
                <div className={styles.scheduleTime}>12:00 PM ET</div>
                <div className={styles.scheduleDesc}>Midday scan — volume patterns solidify, accumulation more visible</div>
              </div>
              <div className={styles.scheduleItem}>
                <div className={styles.scheduleTime}>▶ RESCAN</div>
                <div className={styles.scheduleDesc}>Manual trigger — runs immediately in background (~2–4 min)</div>
              </div>
            </div>
          </Block>

          <Block title="HYPE MONITOR SCHEDULE" color="#cc44ff">
            <div className={styles.scheduleGrid}>
              <div className={styles.scheduleItem}>
                <div className={styles.scheduleTime} style={{ color: '#cc44ff' }}>Every 30 min</div>
                <div className={styles.scheduleDesc}>Mon–Fri 8:00 AM – 5:00 PM ET. Watches top 30 tickers from the latest scan for social sentiment changes.</div>
              </div>
              <div className={styles.scheduleItem}>
                <div className={styles.scheduleTime} style={{ color: '#cc44ff' }}>▶ RUN HYPE</div>
                <div className={styles.scheduleDesc}>Manual trigger button in the 🔮 HYPE MONITOR bar — fires immediately, results appear in ~15s.</div>
              </div>
            </div>
            <p style={{ marginTop: 10, color: 'var(--text-muted)', fontSize: 11 }}>
              Outside market hours the dashboard shows the last saved scan data. "MARKET CLOSED" banner
              appears on weekends and before 9:30am / after 4pm ET.
            </p>
          </Block>
        </Section>

        {/* 3. Indicators */}
        <Section id="indicators" title="3. Technical Indicators">
          <p className={styles.lead}>
            All indicators are computed purely from OHLCV data — no external feeds needed.
          </p>

          <div className={styles.indicatorGrid}>
            <Indicator
              name="VOL ANOMALY"
              formula="Today's volume ÷ 20-day avg volume"
              meaning="Core signal. 2x = notable, 5x = strong, 10x+ = extreme. High volume with quiet price = stealth accumulation."
            />
            <Indicator
              name="VOL RATIO (day-over-day)"
              formula="Today's volume ÷ Yesterday's volume"
              meaning="Short-term volume surge. Used in STEALTH and GOGA detection. 2x+ yesterday with flat price = someone is accumulating quietly."
            />
            <Indicator
              name="VOL Z-SCORE"
              formula="(Today_vol − Avg20) ÷ StdDev20"
              meaning="How many standard deviations above normal. Z > 2 is statistically significant. Less sensitive to absolute size than ratio."
            />
            <Indicator
              name="BB SQUEEZE"
              formula="Bollinger Band width percentile vs last 125 bars"
              meaning="Width below 25th percentile = squeeze. Price coils like a spring — breakout incoming. Bars in squeeze = consecutive days of compression."
            />
            <Indicator
              name="CMF (Chaikin Money Flow)"
              formula="Sum(MFV, 20) ÷ Sum(Vol, 20) — range −1 to +1"
              meaning="Measures buying vs selling pressure. Positive = accumulation. 97th percentile = very strong institutional buying."
            />
            <Indicator
              name="EMA 20 / EMA 50"
              formula="Exponential Moving Averages"
              meaning="Price above both EMAs = uptrend context. Used as trend filter — accumulation above EMA50 is healthier."
            />
            <Indicator
              name="ATR (Average True Range)"
              formula="14-day avg of max(H−L, |H−PrevC|, |L−PrevC|)"
              meaning="Volatility measure. ATR% = ATR as % of price. High ATR ratio = vol expanding, potential breakout starting."
            />
            <Indicator
              name="RSI (14)"
              formula="100 − 100 ÷ (1 + AvgGain14 ÷ AvgLoss14)"
              meaning="Momentum. Below 35 = oversold (green). Above 70 = overbought (red). Arrow ↗ = bullish divergence detected."
            />
            <Indicator
              name="RSI DIVERGENCE"
              formula="Price lower low + RSI higher low in last 35 bars"
              meaning="Hidden strength. Price falling but RSI rising = selling exhausting itself. +10–20 bonus to accumulation score."
            />
            <Indicator
              name="GAP"
              formula="(Today Open − Yesterday Close) ÷ Yesterday Close × 100"
              meaning="Gap Up 2–5% = bullish momentum (+8 vol score). Gap Up 5%+ = strong (+15). Gap Down penalizes score. Shown as ▲/▼ badge."
            />
            <Indicator
              name="STEALTH SCORE"
              formula="Composite: vol_ratio × vol_vs_avg × price_quiet (0–100)"
              meaning="Smart money detector. Volume 2x+ yesterday AND 1.5x+ 20d avg, price moves less than 7%. Bearish close halves the score. 70+ = STRONG."
            />
          </div>
        </Section>

        {/* 4. Tiers */}
        <Section id="tiers" title="4. Signal Tiers">
          <p className={styles.lead}>
            Each ticker is assigned one tier. Score determines the base tier first (pass 1).
            Wyckoff regime state can then <strong>upgrade</strong> the tier but never downgrade it (pass 2).
            SYMPATHY and FLOW are virtual tabs — tickers keep their original tier but also appear there.
          </p>

          <div className={styles.tierList}>
            <TierRow
              emoji="🔥" name="FIRE" color="#ffd700" score="> 80  or  Wyckoff state = FIRE"
              description="Highest conviction. Breakout from accumulation with volume confirmation. Act fast — these move."
              conditions={[
                'Score exceeds 80, OR Wyckoff state = FIRE',
                'Wyckoff FIRE: breakout above 20-bar high with vol Z > 1 and squeeze ≥ 3 bars',
                'Wyckoff state always upgrades to FIRE if score alone did not reach it',
              ]}
            />
            <TierRow
              emoji="👁" name="ARM" color="#00e5ff" score="> 60  or  Wyckoff state = ARM"
              description="Ready to fire. Near top of trading range with squeeze building. Watch for the trigger candle."
              conditions={[
                'Score exceeds 60, OR Wyckoff state = ARM',
                'Wyckoff ARM: price in upper 35% of range, squeeze ≥ 3 bars, CMF positive',
                'Strong institutional flow (≥ 5 days, score ≥ 70) can upgrade BASE/WATCH → ARM',
              ]}
            />
            <TierRow
              emoji="📦" name="BASE" color="#00c853" score="> 40  or  Wyckoff state = BASE"
              description="Building the base. In accumulation range, squeeze forming, early signals. Still needs time."
              conditions={[
                'Score exceeds 40, OR Wyckoff state = BASE',
                'In accumulation (in_acc = true), squeeze ≥ 2 bars, CMF positive',
              ]}
            />
            <TierRow
              emoji="🕵" name="STEALTH" color="#cc44ff" score="stealth_score ≥ 50"
              description="Volume spiked quietly — smart money moving in without tipping off the market. High risk / high reward."
              conditions={[
                'Volume ≥ 2x yesterday AND ≥ 1.5x 20-day avg',
                'Price change < 7% absolute (quiet price action)',
                'Stealth score ≥ 50 (bearish close halves the score)',
                'Wyckoff STEALTH_BASE / STEALTH_ARM = stealth + accumulation combo (strongest)',
              ]}
            />
            <TierRow
              emoji="🔗" name="SYMPATHY" color="#00e5ff" score="virtual tab (any score)"
              description="Tickers in the same sector as a recent leader (10%+ gain, 3x vol) that haven't moved yet. Sector momentum plays."
              conditions={[
                'At least one sector leader found: +10% price AND ≥ 3x average volume',
                'Ticker is in the same sector but has not yet moved significantly',
                'Sympathy score 0–100: based on leader strength + ticker own volume + proximity',
                'Sectors fetched from Yahoo Finance assetProfile (cached per ticker)',
              ]}
            />
            <TierRow
              emoji="🏦" name="FLOW" color="#aa00ff" score="virtual tab (institutional flow)"
              description="Quiet multi-day institutional accumulation — consecutive days of above-average volume with flat price."
              conditions={[
                'Volume ≥ 1.3x 20-day avg for 2+ consecutive days',
                'Price change < 5% per day (institutions hiding their hand)',
                'Close in upper 40%+ of the day\'s bar range (buyers absorbing)',
                'STRONG: ≥ 5 days + score ≥ 70 (gold). MEDIUM: ≥ 3 days (cyan). EARLY: 2 days (purple)',
              ]}
            />
            <TierRow
              emoji="⚡" name="WATCH" color="#ff8800" score="25–40"
              description="On the radar. Some signals present but not enough confirmation. Monitor daily."
              conditions={[
                'Score between 25 and 40',
                'Some volume or accumulation signal present but no tier qualifier met',
              ]}
            />
          </div>

          <Block title="PERFECT STORM ⚡" color="#ffd700">
            <p>A ticker qualifies as Perfect Storm when it hits <strong>≥ 2 of these 4 conditions simultaneously:</strong></p>
            <ul className={styles.ul} style={{ marginTop: 8 }}>
              <li>Stealth accumulation active (<code>is_stealth = true</code>)</li>
              <li>Institutional flow active (<code>is_institutional = true</code>)</li>
              <li>Sector sympathy confirmed (<code>is_sympathy = true</code>)</li>
              <li>Wyckoff state = ARM, FIRE, or STEALTH_ARM</li>
            </ul>
            <p style={{ marginTop: 8, color: 'var(--text-muted)', fontSize: 11 }}>
              Perfect Storm tickers appear in a gold banner above the tabs on the dashboard.
            </p>
          </Block>
        </Section>

        {/* 5. Scoring */}
        <Section id="scoring" title="5. Scoring Formula">
          <Block color="var(--gold)">
            <div className={styles.formula}>
              <div className={styles.formulaLine}>
                <span className={styles.formulaVar} style={{ color: 'var(--gold)' }}>Total Score</span>
                <span className={styles.formulaOp}>=</span>
                <span>(</span>
                <span className={styles.formulaVar} style={{ color: 'var(--arm)' }}>Vol Score</span>
                <span> × 0.4 + </span>
                <span className={styles.formulaVar} style={{ color: 'var(--green)' }}>Accum Score</span>
                <span> × 0.3 + </span>
                <span className={styles.formulaVar} style={{ color: '#cc44ff' }}>Stealth Bonus</span>
                <span> × 0.3)</span>
                <span> × </span>
                <span className={styles.formulaVar} style={{ color: 'var(--gold)' }}>Quiet Factor</span>
              </div>
            </div>

            <div className={styles.scoreBreakdown}>
              <div className={styles.scoreItem}>
                <div className={styles.scoreLabel} style={{ color: 'var(--arm)' }}>VOL SCORE (0–100)</div>
                <div className={styles.scoreRules}>
                  <span>2x 20d avg → 40</span>
                  <span>3x 20d avg → 60</span>
                  <span>5x 20d avg → 80</span>
                  <span>10x+ 20d avg → 100</span>
                  <span>Gap Up → +8–15</span>
                  <span>Gap Down → −10–20</span>
                </div>
              </div>
              <div className={styles.scoreItem}>
                <div className={styles.scoreLabel} style={{ color: 'var(--green)' }}>ACCUM SCORE (0–100)</div>
                <div className={styles.scoreRules}>
                  <span>CMF 60th pctl → +20</span>
                  <span>CMF 80th pctl → +30</span>
                  <span>SQZ 3–5 bars → +10–20</span>
                  <span>SQZ 10+ bars → +30</span>
                  <span>in_acc = true → +30</span>
                  <span>RSI divergence → +10–20</span>
                </div>
              </div>
              <div className={styles.scoreItem}>
                <div className={styles.scoreLabel} style={{ color: '#cc44ff' }}>STEALTH BONUS (0–30)</div>
                <div className={styles.scoreRules}>
                  <span>stealth_score × 0.3</span>
                  <span>Max 30 pts contribution</span>
                  <span>Floor: min 25 if is_stealth</span>
                </div>
              </div>
              <div className={styles.scoreItem}>
                <div className={styles.scoreLabel} style={{ color: 'var(--gold)' }}>QUIET FACTOR (×)</div>
                <div className={styles.scoreRules}>
                  <span>Price {'<'}1% + Vol {'>'} 3x → ×1.5</span>
                  <span>Price {'<'}3% + Vol {'>'} 2x → ×1.2</span>
                  <span>Otherwise → ×1.0</span>
                </div>
              </div>
            </div>

            <p style={{ marginTop: 14, color: 'var(--text-muted)', fontSize: 11 }}>
              After computing the score, the Wyckoff regime state is applied as a second pass.
              State can only <strong>upgrade</strong> the tier (e.g. state=ARM bumps a BASE-score ticker to ARM),
              never downgrade (a score-81 ticker stays FIRE regardless of state).
            </p>
          </Block>
        </Section>

        {/* 6. Wyckoff */}
        <Section id="wyckoff" title="6. Wyckoff Regime Detection">
          <p className={styles.lead}>
            Richard Wyckoff's method (1930s) maps institutional accumulation and distribution cycles.
            The scanner detects these phases automatically from price/volume patterns.
          </p>

          <div className={styles.wyckoffGrid}>
            <Block title="SELLING CLIMAX (SC)" color="var(--red)">
              <p>High-volume bearish bar within 0.1% of the 60-bar low. Panic selling = smart money absorbs supply.
              Marks the beginning of accumulation phase.</p>
              <code>is_bearish AND vol {'>'} 2× avg AND bar_low ≤ 60d_low × 1.001</code>
            </Block>
            <Block title="BUYING CLIMAX (BC)" color="var(--gold)">
              <p>High-volume bullish bar within 0.1% of the 60-bar high. Institutions distributing to retail buyers.
              Marks the beginning of distribution phase.</p>
              <code>is_bullish AND vol {'>'} 2× avg AND bar_high ≥ 60d_high × 0.999</code>
            </Block>
            <Block title="TRADING RANGE (TR)" color="var(--arm)">
              <p>40-bar high/low defines the trading range. Price consolidating between TR High and TR Low.
              The longer the range, the more powerful the eventual breakout.</p>
              <code>TR High = max(highs, 40 bars) | TR Low = min(lows, 40 bars)</code>
            </Block>
            <Block title="ACCUMULATION DETECTION" color="var(--green)">
              <p>Confirmed when SC is found AND price is consolidating in range (5+ bars after SC).
              Also detected heuristically: price near 60-bar lows with volume contracting over the last 10 vs 30 bars.</p>
              <code>bars_since_sc ≥ 5 AND price within TR</code>
              <br />
              <code>OR: near 60-bar bottom (bottom 40%) AND 10-bar avg vol {'<'} 30-bar avg vol</code>
            </Block>
          </div>

          <Block title="STATE MACHINE" color="var(--purple)">
            <div className={styles.stateMachine}>
              <div className={styles.stateFlow}>
                <span className={styles.state} style={{ color: 'var(--text-muted)' }}>NONE</span>
                <span className={styles.arrow}>→</span>
                <span className={styles.state} style={{ color: 'var(--base)' }}>BASE</span>
                <span className={styles.arrow}>→</span>
                <span className={styles.state} style={{ color: 'var(--arm)' }}>ARM</span>
                <span className={styles.arrow}>→</span>
                <span className={styles.state} style={{ color: 'var(--fire)' }}>FIRE</span>
              </div>
              <div className={styles.stateFlow} style={{ marginTop: 8 }}>
                <span className={styles.state} style={{ color: 'var(--text-muted)' }}>NONE</span>
                <span className={styles.arrow}>→</span>
                <span className={styles.state} style={{ color: '#cc44ff' }}>STEALTH</span>
                <span className={styles.stateNote}>(vol 2x yesterday, price quiet, stealth_score ≥ 50)</span>
              </div>
              <div className={styles.stateFlow} style={{ marginTop: 8 }}>
                <span className={styles.state} style={{ color: 'var(--base)' }}>BASE</span>
                <span className={styles.arrow}>+</span>
                <span className={styles.state} style={{ color: '#cc44ff' }}>stealth</span>
                <span className={styles.arrow}>→</span>
                <span className={styles.state} style={{ color: '#cc44ff' }}>STEALTH_BASE</span>
              </div>
              <div className={styles.stateFlow} style={{ marginTop: 8 }}>
                <span className={styles.state} style={{ color: 'var(--arm)' }}>ARM</span>
                <span className={styles.arrow}>+</span>
                <span className={styles.state} style={{ color: '#cc44ff' }}>stealth</span>
                <span className={styles.arrow}>→</span>
                <span className={styles.state} style={{ color: '#cc44ff' }}>STEALTH_ARM</span>
                <span className={styles.stateNote}>(strongest signal in the system)</span>
              </div>
            </div>
          </Block>
        </Section>

        {/* 7. Hype Monitor */}
        <Section id="hype-monitor" title="7. Hype Monitor (v10.0)">
          <p className={styles.lead}>
            A completely independent service running every <strong>30 minutes</strong> during market hours.
            It watches the top 30 tickers from the latest scan for social sentiment vs price/volume divergence.
          </p>

          <Block title="DATA SOURCES" color="#cc44ff">
            <p>Three sources fetched concurrently per ticker (12s timeout, silent fail):</p>
            <ul className={styles.ul} style={{ marginTop: 8 }}>
              <li><strong>StockTwits</strong> — last ~30 stream messages with bullish/bearish sentiment tags (40% weight)</li>
              <li><strong>Yahoo Finance News</strong> — last 15 headlines with publish timestamps (30% weight)</li>
              <li><strong>Reddit</strong> — r/wallstreetbets + r/pennystocks + r/smallcapstocks, filtered to posts that mention the ticker (30% weight)</li>
            </ul>
          </Block>

          <Block title="VELOCITY" color="var(--arm)">
            <p>Mentions are bucketed into time windows to measure <em>acceleration</em> (not just total count):</p>
            <div className={styles.indicatorGrid} style={{ marginTop: 10 }}>
              <Indicator
                name="VELOCITY 2H"
                formula="(2h mention rate) ÷ (24h baseline rate)"
                meaning="Primary acceleration signal. 3x+ = VELOCITY_SPIKE divergence. Shows if attention is building rapidly right now."
              />
              <Indicator
                name="VELOCITY 6H"
                formula="(6h mention rate) ÷ (24h baseline rate)"
                meaning="Medium-term trend. Confirms whether the 2h spike is sustained or a single burst."
              />
              <Indicator
                name="COMBINED"
                formula="Twits × 0.4 + Reddit × 0.3 + News × 0.3"
                meaning="Weighted cross-source velocity. Used for the velocity bonus in hype index and for VELOCITY_SPIKE detection."
              />
            </div>
          </Block>

          <Block title="HYPE INDEX (0–100)" color="var(--gold)">
            <div className={styles.scoreBreakdown}>
              <div className={styles.scoreItem}>
                <div className={styles.scoreLabel} style={{ color: 'var(--gold)' }}>BASE SCORE</div>
                <div className={styles.scoreRules}>
                  <span>3 mentions → 10</span>
                  <span>15 mentions → 35</span>
                  <span>60 mentions → 65</span>
                  <span>200 mentions → 90</span>
                  <span>Weighted by source</span>
                </div>
              </div>
              <div className={styles.scoreItem}>
                <div className={styles.scoreLabel} style={{ color: '#cc44ff' }}>SENTIMENT BONUS</div>
                <div className={styles.scoreRules}>
                  <span>StockTwits only</span>
                  <span>Bull ratio → +10</span>
                  <span>Bear ratio → −10</span>
                  <span>Min 3 tagged msgs</span>
                </div>
              </div>
              <div className={styles.scoreItem}>
                <div className={styles.scoreLabel} style={{ color: 'var(--arm)' }}>VELOCITY BONUS</div>
                <div className={styles.scoreRules}>
                  <span>vel_2h 1–2x → +5</span>
                  <span>vel_2h 2–4x → +10</span>
                  <span>vel_2h 4x+ → +15</span>
                </div>
              </div>
              <div className={styles.scoreItem}>
                <div className={styles.scoreLabel} style={{ color: 'var(--green)' }}>TIERS</div>
                <div className={styles.scoreRules}>
                  <span>0–25 → COLD</span>
                  <span>25–50 → WARM 📈</span>
                  <span>50–75 → HOT 🚀</span>
                  <span>75–100 → VIRAL 🔥</span>
                </div>
              </div>
            </div>
          </Block>

          <Block title="DIVERGENCE SIGNALS" color="var(--red)">
            <p>The core insight — when hype and price/volume tell different stories:</p>
            <div className={styles.wyckoffGrid} style={{ marginTop: 10 }}>
              <Block title="🔇 SILENT VOLUME" color="var(--green)">
                <p><strong>Volume ≥ 2.5x normal but hype index ≤ 30.</strong></p>
                <p style={{ color: 'var(--text-muted)', fontSize: 11 }}>Smart money is moving without retail noticing. Strongest bullish divergence — institutions accumulate quietly before public awareness.</p>
                <p style={{ marginTop: 6 }}><strong>→ SILENT tab on dashboard</strong> · 2h Telegram cooldown</p>
              </Block>
              <Block title="🚀 VELOCITY SPIKE" color="var(--arm)">
                <p><strong>2h mention velocity ≥ 3x baseline.</strong></p>
                <p style={{ color: 'var(--text-muted)', fontSize: 11 }}>Retail attention accelerating rapidly. Could be a catalyst, news, or beginning of FOMO. Enter early or wait for volume confirmation.</p>
                <p style={{ marginTop: 6 }}><strong>→ HYPE tab on dashboard</strong> · 1h Telegram cooldown</p>
              </Block>
              <Block title="📉 PEAK FADING" color="var(--red)">
                <p><strong>Hype dropped ≥ 15 pts + price flat ({'<'}3%).</strong></p>
                <p style={{ color: 'var(--text-muted)', fontSize: 11 }}>Social interest collapsing while price hasn't moved — sentiment exhaustion. Distribution phase may be starting. Exit signal.</p>
                <p style={{ marginTop: 6 }}><strong>→ EXIT SIGNALS banner</strong> · 3h Telegram cooldown</p>
              </Block>
              <Block title="⚠ HYPE, NO VOLUME" color="var(--watch)">
                <p><strong>Hype ≥ 50 but volume {'<'} 1.5x normal.</strong></p>
                <p style={{ color: 'var(--text-muted)', fontSize: 11 }}>Social buzz without institutional participation. Potential pump attempt. Real money is not buying — be cautious.</p>
                <p style={{ marginTop: 6 }}><strong>→ HYPE tab on dashboard</strong> · 2h Telegram cooldown</p>
              </Block>
            </div>
          </Block>

          <Block title="AI ANALYSIS (Claude Sonnet)" color="var(--purple)">
            <p>
              Only fires when divergences are detected. Returns structured JSON: summary, signals,
              divergence interpretation, risk level (LOW/MEDIUM/HIGH), and recommendation (WATCH/ENTER/AVOID/EXIT).
            </p>
            <p style={{ marginTop: 8, color: 'var(--text-muted)', fontSize: 11 }}>
              Results cached <strong>45 minutes per ticker</strong> to limit API calls.
              Visible in the hype panel on each card (click the hype badge to expand).
            </p>
          </Block>

          <Block title="SMART MONEY vs EXIT SIGNALS BANNERS" color="var(--green)">
            <ul className={styles.ul}>
              <li><strong>💰 SMART MONEY</strong> — tickers with SILENT_VOLUME divergence (high vol, low hype). Best trade setup.</li>
              <li><strong>🚨 EXIT SIGNALS</strong> — tickers with PEAK_FADING divergence. Review open positions.</li>
              <li><strong>🔮 HYPE MONITOR bar</strong> — always visible. Shows HOT/VIRAL tickers and last run time. Click ▶ RUN HYPE to trigger manually.</li>
            </ul>
          </Block>
        </Section>

        {/* 8. Filters */}
        <Section id="filters" title="8. Filters & Quality Gates">
          <Block color="var(--red)">
            <p>Tickers are dropped at each stage if they fail:</p>
            <ul className={styles.ul} style={{ marginTop: 10 }}>
              <li><strong>Minimum 60 candles</strong> — need history for reliable indicators</li>
              <li><strong>Last-day volume ≥ 200,000</strong> — illiquid stocks skipped (can't trade the signal)</li>
              <li><strong>Vol anomaly ≥ 2x 20-day avg</strong> — must have a meaningful volume event</li>
              <li><strong>Score tier ≠ SKIP</strong> — score below 25 with no GOGA signal discarded</li>
              <li><strong>Price $1–$50</strong> — applied at Finviz screener stage</li>
            </ul>
          </Block>

          <Block title="AI ANALYSIS (Claude)" color="var(--purple)">
            <p>After scoring, the top 20 tickers by score get a Claude AI analysis (up to 3 concurrent).
            The model receives indicators, regime data, and score breakdown and returns:</p>
            <ul className={styles.ul} style={{ marginTop: 8 }}>
              <li><strong>REGIME</strong> — state interpretation in plain English</li>
              <li><strong>PHASE</strong> — Wyckoff A/B/C/D/E phase assessment</li>
              <li><strong>VOLUME</strong> — what the vol anomaly means (absorption / climax / interest)</li>
              <li><strong>KEY LEVELS</strong> — TR High / TR Low reference</li>
              <li><strong>CATALYST NEEDED</strong> — what price action would confirm the setup</li>
              <li><strong>INVALIDATION</strong> — what would kill the setup</li>
              <li><strong>VERDICT</strong> — STRONG BUY SETUP / WATCH / AVOID</li>
            </ul>
            <p style={{ marginTop: 8, color: 'var(--text-muted)', fontSize: 11 }}>
              Requires ANTHROPIC_API_KEY set in environment variables. Uses claude-haiku-4-5 model with claude-3-5-haiku / claude-3-haiku fallback.
            </p>
          </Block>
        </Section>

        <div className={styles.footer}>
          <Link href="/" className={styles.backLink}>← Back to Scanner</Link>
        </div>
      </div>
    </>
  );
}
