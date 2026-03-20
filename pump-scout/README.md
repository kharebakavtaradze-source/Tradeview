# Pump Scout

Automated morning scanner that finds small-cap stocks with anomalous volume but price hasn't moved yet — the moment smart money is quietly accumulating.

## Features

- **Finviz scraper** — scans 800+ small-caps daily (no API key needed)
- **Yahoo Finance OHLCV** — 6 months of daily candle data per ticker
- **Technical indicators** — Bollinger Bands squeeze, Chaikin Money Flow, Volume Z-score, ATR, EMA
- **Wyckoff regime detection** — identifies accumulation ranges, selling climax, spring patterns
- **Composite scoring** — ranks tickers by volume anomaly + accumulation evidence + quiet factor
- **AI analysis** — Claude Sonnet provides structured setup analysis for top 20 tickers
- **Auto-scheduler** — runs scans at 8:00 AM, 9:30 AM, and 12:00 PM EST on weekdays
- **Dark terminal UI** — Next.js dashboard with live charts and expandable cards

## Deploy to Railway

```bash
# 1. Push to GitHub
git push origin main

# 2. Login to Railway
railway login

# 3. Deploy
railway up

# 4. Add environment variables in Railway dashboard:
#    ANTHROPIC_API_KEY = sk-ant-...

# 5. Add PostgreSQL plugin in Railway dashboard

# Done! Scans run automatically at 8AM, 9:30AM, 12PM EST weekdays
```

## Local Development

### Backend

```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your ANTHROPIC_API_KEY
uvicorn main:app --reload --port 8000
```

The backend will use SQLite locally if `DATABASE_URL` is not set.

### Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check + scan status |
| GET | `/api/scan/latest` | Latest scan results |
| GET | `/api/scan/history` | Last 30 days of scans |
| GET | `/api/ticker/{symbol}` | Full data for one ticker |
| POST | `/api/scan/run` | Trigger manual scan |
| GET | `/api/watchlist` | List watchlist |
| POST | `/api/watchlist/{symbol}` | Add to watchlist |
| DELETE | `/api/watchlist/{symbol}` | Remove from watchlist |

## Tier System

| Tier | Score | Meaning |
|------|-------|---------|
| 🔥 FIRE | >80 | Wyckoff breakout with volume confirmation |
| 👁 ARM | >60 | Near TR high, squeezing, positive CMF |
| 📦 BASE | >40 | In accumulation range with BB squeeze |
| ⚡ WATCH | >25 | Early signals, needs confirmation |

## Architecture

```
pump-scout/
├── backend/
│   ├── main.py              FastAPI app + routes
│   ├── database.py          SQLAlchemy async (PostgreSQL/SQLite)
│   ├── scheduler.py         APScheduler cron jobs
│   └── scanner/
│       ├── finviz.py        Finviz HTML scraper
│       ├── yahoo.py         Yahoo Finance OHLCV fetcher
│       ├── indicators.py    Pure math: BB, CMF, ATR, EMA
│       ├── wyckoff.py       Wyckoff regime detection
│       ├── scoring.py       Composite scoring engine
│       ├── ai_analyst.py    Claude AI analysis
│       └── runner.py        Scan orchestrator
├── frontend/
│   ├── pages/
│   │   ├── index.js         Main dashboard
│   │   └── ticker/[symbol].js  Ticker detail page
│   └── components/
│       ├── TickerCard.js    Card with expandable chart + AI
│       ├── Chart.js         Lightweight Charts candlestick
│       ├── Scanner.js       Header with scan controls
│       └── AIAnalysis.js    Formatted AI analysis display
└── railway.toml             Railway deployment config
```
