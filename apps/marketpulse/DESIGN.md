# MarketPulse: design

Two companion apps for a **Gen 1 Tidbyt** (64×32, whole animation ≤ 15 s):

| App | Folder | Installation ID (planned) | Content |
|---|---|---|---|
| MarketPulse | `apps/marketpulse/` | `marketpulse` | Market ETFs: overview + one detail chart |
| MarketPulse Stocks (manifest name "MarketPulse 6") | `apps/marketpulse_stocks/` | `marketpulsestocks` | Six stocks with pixel-art logos, 3 per refresh (alternating) |

Prices and movement only, with no buy/sell suggestions.

## Screens

**MarketPulse** (2 screens × 7.2 s = 14.4 s, 144 frames at 100 ms)
1. *Overview.* Header `ETFs` · status chip · clock. Then 3 rows (SPY, QQQ, DIA), each with ticker, ▲/▼ arrow,
   daily % (first half of the screen), then price (second half), and a 17×7 sparkline. Sparklines draw in over 1 s.
2. *Detail* (default SPY; setting `detail` = SPY/QQQ/DIA). Ticker in the corner shows the ETF label
   ("S&P500 ETF") for the first half, then status and clock. Big price (6x13), arrow with % and $ change, and a 64×11
   sparkline with a dotted line at yesterday's close.

SPY / QQQ / DIA are **ETF proxies** for the S&P 500, Nasdaq-100 and Dow; the app always labels them as ETFs.

**MarketPulse Stocks** (3 cards × 5 s = 15.0 s per refresh; the two sets of 3 alternate)
- 16×16 logo · ticker · status chip (then clock) · big price · arrow, % and change · 35×12 sparkline with baseline.
- Logos: AAPL (rainbow apple), MSFT (4 squares), NVDA (green eye), AMZN ("a" + smile), GOOGL ("G"), HPQ (hp disc).
  Any other ticker gets a letter tile. The watchlist is settings `stock1`…`stock6`.
- Six stocks at 5 s each would be 30 s, over the Gen 1 cap, so each render shows one **page** of 3.
  The push script passes `page=0` / `page=1` on alternate pushes. Without it, the page follows the clock and changes every 5 min.
  Order: AAPL, MSFT, NVDA, then AMZN, GOOGL, HPQ.
- Tickers with no data are skipped.

Colours: up `#33dd66`, down `#ff4a4a`, flat `#9aa4b0`, PRE/POST amber `#ffb000`, labels `#7d8794`.
All are above the Gen 1 dim threshold.

## Data

Source: Yahoo Finance spark endpoint, which is unofficial and needs no key. One request covers every symbol:

```
https://query1.finance.yahoo.com/v7/finance/spark?symbols=SPY,QQQ,DIA,AAPL,MSFT,NVDA,AMZN,GOOGL,HPQ&range=1d&interval=5m
```

- It needs a browser `User-Agent` header; without one it returns HTTP 429.
- Per symbol `meta` gives `regularMarketPrice`, `chartPreviousClose`, `regularMarketTime` and
  `currentTradingPeriod` (pre / regular / post start and end). It also returns about 79 five-minute closes for the sparkline.
- **Status:** now inside `regular` → OPEN, `pre` → PRE, `post` → POST, otherwise CLOSED.

### Snapshot / offline design
Yahoo has taken 12 s to answer, and Pixlet can't catch an `http.get` timeout (the render dies).
So production renders **don't fetch**. The push script fetches instead:

1. The push script requests the URL above (with retries), normalises the response to the compact shape below, and
   saves it to `%USERPROFILE%\.tidbyt\marketpulse_snapshot.json` **only if it parsed OK**.
2. It renders both apps with `snapshot=<that JSON>` (about 6 KB), so a failed fetch re-renders the **last good** data.
3. **STALE:** a session is running (status ≠ CLOSED) and `now − fetched_at > 15 min`. The chip blinks red.

```json
{"fetched_at": 1763050000,
 "quotes": {"SPY": {"price": 754.37, "prev": 757.12, "time": 1763049900,
                    "closes": [757.0, 756.2, ...],
                    "periods": {"pre": [s, e], "regular": [s, e], "post": [s, e]}}}}
```

With no `snapshot`, the apps fetch live themselves (fine for `pixlet serve` previews).
Fixture: `fixtures/sample_snapshot.json`.

Preview switches: `demo_status=OPEN|PRE|POST|CLOSED`, `demo_stale=true`.

## Intelligent refresh (installed 2026-11-13)

The scheduled task **"Tidbyt - MarketPulse"** runs every 5 min:
`wscript tools/push_marketpulse.vbs` → `tools/push_marketpulse.ps1`.
The script decides by New York time whether to do any work:

| When (ET) | Action |
|---|---|
| Mon–Fri 09:30–16:00 (regular) | fetch + push every run (5 min) |
| Mon–Fri 04:00–09:30, 16:00–20:00 (pre/post) | runs starting :00–:04, :15–:19 and so on (every 15 min) |
| Nights, weekends | runs starting :00–:04 (hourly) |

- Each working run fetches all 9 symbols in one request and saves `%USERPROFILE%\.tidbyt\marketpulse_snapshot.json`
  (only when at least 3 quotes parsed). It renders both apps with `snapshot=<json>` and pushes with `--background`.
- If the fetch fails it renders the saved snapshot, so the apps show STALE.
- The stocks app's `page` alternates 0/1 each push (`marketpulse_page.txt`).
- Manual run: `pwsh -File tools/push_marketpulse.ps1 -Force [-Foreground]`.
- Installation IDs: `marketpulse`, `marketpulsestocks`. Log: `%USERPROFILE%\.tidbyt\push.log` (`[marketpulse]`).

Market holidays fall out naturally: Yahoo's `currentTradingPeriod` has no open session, so the status reads CLOSED.
