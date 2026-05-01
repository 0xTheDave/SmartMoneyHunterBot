# Smart Money Hunter

A Solana copy-trading research bot that discovers consistently profitable wallets ("smart money"), monitors them in real time, and pushes high-quality buy signals to a Telegram channel.

The bot is built around the idea that on-chain data already reveals which wallets win — the job is to (1) find them, (2) filter out bots / wash traders / insiders, and (3) react when they buy something new.

> ⚠️ **Disclaimer:** This is research / educational software. It does **not** execute trades. Signals are produced from on-chain analysis and are not financial advice. Use at your own risk.

---

## What the bot actually does

The pipeline runs in three loops:

1. **Discovery loop** (every ~2 days) — find candidate wallets and rank them.
2. **Monitoring loop** (every 5 minutes) — watch the top-ranked wallets and emit buy signals.
3. **Validation loop** (hourly) — check whether past signals actually pumped, and re-score wallets accordingly.

### Module-by-module breakdown

| File | Role |
|---|---|
| [src/main.py](smart_money_hunter/src/main.py) | Orchestrator. Wires discovery → analysis → ranking → monitoring → Telegram. |
| [src/run.py](smart_money_hunter/src/run.py) | Tiny entry point: `python run.py`. |
| [src/config.py](smart_money_hunter/src/config.py) | Loads `.env`, exposes thresholds (min score 85, max 150 monitored wallets, etc.). |
| [src/database.py](smart_money_hunter/src/database.py) | SQLAlchemy models: `SmartWallet`, `Transaction`, `Signal`, `TelegramUser`, `APIUsage`, `TokenCache`. SQLite by default. |
| [src/api_client.py](smart_money_hunter/src/api_client.py) | Async HTTP client for Helius (Solana txs) and Birdeye (prices), with daily rate-limit guards. |
| [src/discovery.py](smart_money_hunter/src/discovery.py) | Finds candidate wallets: early buyers, consistent traders, leader wallets. Filters out MEV bots, wash traders and insider patterns. |
| [src/analyzer.py](smart_money_hunter/src/analyzer.py) | Pulls real Helius transactions and computes win rate, average ROI, timing score, consistency, and recent activity for each candidate. |
| [src/ranker.py](smart_money_hunter/src/ranker.py) | Maps metrics → score (0-100) → tier: **S** (90+), **A** (80+), **B** (70+), **C** (<70). Persists to DB. |
| [src/monitor.py](smart_money_hunter/src/monitor.py) | Polls the top-150 active wallets, parses new SWAP transactions, and emits a buy signal if the trade scores ≥ `MIN_SIGNAL_SCORE` (85). Caps at 10 signals/day. |
| [src/telegram_bot.py](smart_money_hunter/src/telegram_bot.py) | Telegram interface. Commands: `/start`, `/help`, `/top`, `/signals`, `/stats`, `/wallet <address>`. Broadcasts signals to all registered users. |
| [src/risk_scoring.py](smart_money_hunter/src/risk_scoring.py) | Wraps each signal with a 0-100 risk score across 5 dimensions: wallet, token, market, timing, social proof. Maps to `VERY_LOW … VERY_HIGH`. |
| [src/social_proof.py](smart_money_hunter/src/social_proof.py) | Detects leader/follower coordination — does this wallet *lead* others into a token, or follow? Confidence score from 0-100. |
| [src/advanced_filtering.py](smart_money_hunter/src/advanced_filtering.py) | Deeper anti-bot heuristics: sandwich attacks, wash trading (alternating buy/sell with low volume variance), pump-group clustering, coordinated buying. |
| [src/historical_validation.py](smart_money_hunter/src/historical_validation.py) | After a signal ages, fetches current price, computes 1h / 24h / 7d returns, marks signals successful or failed, and adjusts the source wallet's score (deactivates poor performers). |
| [src/portfolio_tracking.py](smart_money_hunter/src/portfolio_tracking.py) | Virtual portfolio: opens a $100 paper position per signal, tracks PnL, auto-closes after 30 days, computes win-rate-per-tier and per-recommendation-type. |
| [src/webhook_integration.py](smart_money_hunter/src/webhook_integration.py) | Posts signals / portfolio updates / alerts to external HTTP endpoints with retry + delivery logging. |
| [src/performance_monitoring.py](smart_money_hunter/src/performance_monitoring.py) | Tracks bot-internal error rates and emits alerts above a threshold. |

### Signal scoring (high level)

A wallet's `BUY` becomes a signal when its score, computed in [monitor.py](smart_money_hunter/src/monitor.py), clears 85/100. Components:

- **Wallet tier** (S/A/B/C): up to 35 pts
- **Wallet score**: up to 30 pts
- **Trade size** (SOL amount): up to 20 pts
- **Social proof** (other smart wallets buying same token in last 24h): up to 15 pts

Recommendation buckets: `HOT_BUY` (≥95), `STRONG_BUY` (≥85), `WATCH` (below).

---

## Tech stack

- **Python 3.11+** (3.13 tested)
- `aiohttp` — async HTTP
- `python-telegram-bot` 20.x
- `SQLAlchemy` 1.4 + SQLite
- `python-dotenv`
- APIs: [Helius](https://helius.xyz) (Solana RPC + parsed transactions) and [Birdeye](https://birdeye.so) (token prices, top movers)

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/<your-user>/smart-money-hunter.git
cd smart-money-hunter/smart_money_hunter
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
```

### 2. Configure secrets

Copy the template and fill it in:

```bash
copy .env.example .env          # Windows
# cp .env.example .env          # Linux / macOS
```

Edit `.env`:

```
TELEGRAM_TOKEN=...              # from @BotFather
HELIUS_API_KEY=...              # from helius.xyz dashboard
BIRDEYE_API_KEY=...             # from birdeye.so dashboard
DATABASE_URL=sqlite:///smart_money.db
```

`.env` is git-ignored — your keys never leave your machine.

### 3. Run

```bash
cd src
python run.py
```

On startup the bot:

1. Initialises the SQLite database (drops & recreates tables — see note below).
2. Connects to Telegram and starts polling.
3. Runs an initial discovery pass.
4. Enters the monitor + validation loop.

Open Telegram, find your bot, send `/start`, then `/help`.

---

## Configuration knobs

All in [src/config.py](smart_money_hunter/src/config.py):

| Setting | Default | Meaning |
|---|---|---|
| `MIN_SIGNAL_SCORE` | 85 | Minimum signal score to emit |
| `MAX_MONITORED_WALLETS` | 150 | Hard cap on watched wallets |
| `MONITOR_INTERVAL` | 300 s | How often to poll for new trades |
| `DISCOVERY_INTERVAL` | 172 800 s (2d) | How often to re-discover wallets |
| `MIN_WALLET_TRADES` | 10 | Min trades for a wallet to be analysed |
| `MIN_WIN_RATE` | 60 | Min win rate to keep a wallet |
| `MIN_VOLUME_SOL` | 1.0 | Trades smaller than this are ignored |
| `MAX_SIGNALS_PER_DAY` | 10 | Daily signal cap |
| `HELIUS_DAILY_LIMIT` | 3000 | API budget — stop calling above this |
| `BIRDEYE_DAILY_LIMIT` | 90 | Same |

---

## Project layout

```
Smart Money Hunter/
├── .gitignore
├── README.md
├── opis.txt                       # original Polish design notes
└── smart_money_hunter/
    ├── .env                       # local secrets (git-ignored)
    ├── .env.example               # template for new clones
    ├── requirements.txt
    └── src/
        ├── run.py                 # entry point
        ├── main.py                # orchestrator
        ├── config.py
        ├── database.py
        ├── api_client.py
        ├── discovery.py
        ├── analyzer.py
        ├── ranker.py
        ├── monitor.py
        ├── telegram_bot.py
        ├── risk_scoring.py
        ├── social_proof.py
        ├── advanced_filtering.py
        ├── historical_validation.py
        ├── portfolio_tracking.py
        ├── webhook_integration.py
        └── performance_monitoring.py
```

---

## Known caveats / things to clean up

The code base is a working prototype. A few things you should know before depending on it:

- **`discovery.py` currently returns 4 hard-coded test wallets** (lines 24-32). The full discovery flow (`_discover_early_buyers`, `_discover_consistent_traders`, `_discover_influencer_wallets`) is implemented but disabled until `_get_recent_dex_swaps` has a real DEX-log source.
- **`database.py` calls `Base.metadata.drop_all(engine)` on import.** Every restart wipes the DB. Remove that call before running in production.
- **`risk_scoring.py` imports `SocialProofAnalyzer`** but the actual class in [src/social_proof.py](smart_money_hunter/src/social_proof.py) is `EnhancedSocialProofAnalyzer` — rename one of them before risk scoring will work.
- **`historical_validation.py` references `SignalPerformanceDB`** and `webhook_integration.py` imports `WebhookLogDB` / `WebhookConfigDB` — these models are declared inside their own modules but not registered with the shared `Base` in `database.py`. Move them into `database.py` so the tables actually get created.
- **`telegram_bot.py` `/signals`** uses `signal.smart_wallets_count` and `signal.total_volume`, fields that don't exist on the `Signal` model — should be `similar_wallets` and `sol_amount`.
- The bot only **records** signals — it does not place trades. If you want auto-execution, plug a Solana wallet adapter into `monitor._analyze_buy_signal`.
- API keys live in `.env`; rotate any key that has ever been committed in plaintext (this repo's history was sanitised before publishing).

---

## License

[MIT](LICENSE) © 2026 0xTheDave
