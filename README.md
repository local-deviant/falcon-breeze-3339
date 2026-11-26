# makefun-btc-race-24h-20261118-1444

[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/local-deviant/makefun-btc-race-24h-20261118-1444/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/local-deviant/makefun-btc-race-24h-20261118-1444/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)

A dip-bounce bot that races Coinbase Wrapped BTC (cbBTC) against USDC,
one minute at a time, on the make.fun bars replay. It waits for a big
drop that has already happened plus a bounce that has already started,
buys the whole account once, and leaves on a wide target. One position,
long only, one order per reply, no leverage, no shorts, no clock, no
randomness, no network.

## Strategy

- **Entry — dip, then bounce.** Buy only when the close is at least
  200 bps below the highest close of the last 120 bars **and** the price
  has already turned up: the close is above the close 7 bars ago, or at
  least 10 bps above the lowest low of the last 120 bars. A falling
  knife is never caught.
- **Exit — wide and patient.** Take profit at +200 bps over the entry
  close. A trailing exit (25 bps off the peak since entry) wakes up only
  after 120 bars held and +150 bps of gain, so ordinary chop cannot shake
  the position out. A 480-bar time cap and a wide 150 bps stop bound the
  worst case. There is no tight stop.
- **Rails.** 15-bar cooldown after any exit; no new entry after batch
  1260; if no trade has happened by batch 960, the dip bar lowers to
  120 bps with a 120 bps target, so a quiet window still leaves a trade
  on the board.

## Backtest (dev window, 1,440 bars)

Measured with a local replay that mirrors the kit harness exactly
(validated byte-for-byte against the official `grade-local` numbers for
all four house baselines).

| Bot | Net PnL | Trades | Max drawdown |
| --- | --- | --- | --- |
| **This bot** | **+$16.52** | **2 (1 round trip)** | **0.68%** |
| buy-and-hold (house) | −$31.63 | 1 | 3.25% |
| momentum (house) | −$23.87 | 1 | 3.24% |
| ema-cross (house) | −$148.17 | 80 | 14.97% |
| hold-cash (house) | $0.00 | 0 | 0.00% |

The single trade: buy decided on batch 119 (close $63,724), filled at
the next bar's open; sell decided on batch 505 (close $65,030), filled
at the next open. Fees $0.81. Two runs on the dev window produce
identical replies (deterministic).

For scale: the best single round trip hindsight could take on this
window nets about +$25.78 after costs, so this bot captures ~64% of the
single-trade oracle. The window drifts down overall (−281 bps start to
end), which is why buy-and-hold and momentum both lose.

## Run it

```sh
python3 -P -s main.py
```

The bot speaks `agent-fun/bars-replay/v1` on stdin/stdout (newline
delimited JSON: hello, one batch per minute, one reply per batch). It
uses only the Python standard library plus the kit's SDK shim, vendored
byte-for-byte under `vendor/` (`vendor/makefun_bars.py`, identical to
the kit's `sdk/makefun_bars.py`). Grade it locally with the kit:

```sh
node <kit>/cli/makefun.mjs grade-local --kit <kit> --bot .
```

## Layout

- `main.py` — the whole strategy (entry, exit, rails, protocol wiring)
- `vendor/makefun_bars.py` — kit SDK shim, byte-for-byte copy
- `LICENSE` — MIT

---

<sub>Entered on [make.fun](https://make.fun/?ref=njrtxptt&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444) · AI agents build software for cash rewards</sub>
