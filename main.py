"""Dip-bounce bot for the make.fun BTC race (agent-fun/bars-replay/v1).

Idea, in one paragraph: Bitcoin's one-minute price spends most of a day
chopping sideways, then now and then drops hard and climbs back. This bot
does nothing for hours at a time and waits for exactly one shape: a big
drop that has already happened, plus a bounce that has already started.
It buys the whole account once, holds through the chop, and leaves on a
wide target, a mature trailing exit, a time cap, or a wide stop. One
position, long only, one order per reply, full size, no leverage, no
shorts, no clock, no randomness, no network: every decision is integer
math on the bars the harness has already sent, so two runs on the same
window answer byte for byte.

Entry (both halves must hold on the bar that just closed):
  * the drop: the close sits at least DIP_BPS below the highest close of
    the last DIP_WINDOW bars; and
  * the bounce: the close is above the close BOUNCE_LOOKBACK bars ago, or
    at least BOUNCE_LOW_BPS above the lowest low of the last DIP_WINDOW
    bars. A falling knife is never caught: the buy waits until the price
    has already turned up.

Exit (first rule that fires, checked in this order):
  * take profit: the close is TAKE_PROFIT_BPS above the entry close;
  * trailing: once the position is at least TRAIL_MIN_HELD bars old and
    already up TRAIL_MIN_GAIN_BPS, a pullback of TRAIL_DROP_BPS from the
    highest close since entry sells. The trail stays asleep while the
    rally is young, so ordinary chop cannot shake the position out;
  * time cap: MAX_HOLD_BARS bars after entry, whatever the price;
  * wide stop: STOP_BPS below the entry close. There is no tight stop:
    a 1-2% wobble on the way up is normal, not a reason to leave.

Safety rails:
  * after any exit, COOLDOWN_BARS bars pass before a new entry;
  * no entry is opened after NO_ENTRY_AFTER_SEQ: a trade started that
    late has no room left to reach its target before the window ends;
  * if no trade has happened at all by FALLBACK_AFTER_SEQ, the dip bar
    lowers to FALLBACK_DIP_BPS with a narrower FALLBACK_TAKE_PROFIT_BPS.
    A quiet window with no 2% dip must still leave the bot with a trade
    on the board, or it cannot meet the race's minimum bar at all.

All thresholds are in basis points (1 bp = 0.01%) and all prices are the
harness's integer closes, so the strategy is exact and reproducible.
"""

import os
import sys
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# --- entry: how big a drop, and what counts as a bounce ---
DIP_WINDOW = 120            # bars of history the drop is measured over
DIP_BPS = 200               # close this far below the window's highest close
BOUNCE_LOOKBACK = 7         # bounce test one: close above the close this far back
BOUNCE_LOW_BPS = 10         # bounce test two: this far above the window's lowest low

# --- exit: wide target, mature trail, time cap, wide stop ---
TAKE_PROFIT_BPS = 200       # close this far above the entry close
TRAIL_DROP_BPS = 25         # pullback from the peak since entry that sells
TRAIL_MIN_HELD = 120        # trail wakes up only after this many bars held
TRAIL_MIN_GAIN_BPS = 150    # ... and only once the position is this far up
MAX_HOLD_BARS = 480         # time cap: bars held, then out whatever the price
STOP_BPS = 150              # wide stop below the entry close

# --- rails ---
COOLDOWN_BARS = 15          # bars to wait after an exit before re-entering
NO_ENTRY_AFTER_SEQ = 1260   # no new entry on or after this batch
FALLBACK_AFTER_SEQ = 960    # with no trade yet, lower the dip bar from here
FALLBACK_DIP_BPS = 120      # fallback dip bar
FALLBACK_TAKE_PROFIT_BPS = 120  # fallback target

MAX_SLIPPAGE_BPS = 150      # cap on the fill's move from the latest close


class DipBounceBot:
    """One position, full size, driven only by the bars already received."""

    def __init__(self):
        self.closes = deque(maxlen=DIP_WINDOW)   # closes, oldest first
        self.lows = deque(maxlen=DIP_WINDOW)     # lows, oldest first
        self.holding = False
        self.entry_close = 0      # close of the bar the buy was decided on
        self.entry_seq = 0        # batch the buy was decided on
        self.entry_fallback = False  # this position entered on the fallback bar
        self.peak_close = 0       # highest close seen while holding
        self.last_exit_seq = -10 ** 9
        self.ever_traded = False  # a buy has filled at least once
        self.buy_pending = False  # a buy was sent, fill not yet confirmed

    # -- helpers ---------------------------------------------------------
    def _bps_move(self, now, ref):
        """(now - ref) in basis points of ref, integer math, truncating."""
        return (now - ref) * 10000 // ref

    def _drop_bps(self):
        """How far the latest close sits below the window's highest close."""
        return self._bps_move(self.closes[-1], max(self.closes))

    def _bounced(self):
        """True once the price has already turned up after the drop."""
        close = self.closes[-1]
        if len(self.closes) > BOUNCE_LOOKBACK and close > self.closes[-1 - BOUNCE_LOOKBACK]:
            return True
        lowest_low = min(self.lows)
        return self._bps_move(close, lowest_low) >= BOUNCE_LOW_BPS

    # -- main callback ---------------------------------------------------
    def on_batch(self, state, batch):
        if state.warming_up:
            return []
        bars = [b for b in batch["bars"] if b["symbol"] == SYMBOL]
        if not bars:
            return []
        bar = bars[0]
        close = int(bar["c"])
        low = int(bar["l"])
        seq = batch["seq"]
        self.closes.append(close)
        self.lows.append(low)

        holding = state.positions.get(SYMBOL)
        qty = holding.qty if holding is not None else 0

        # A buy sent on an earlier batch: confirm it only once the
        # position actually shows up; a rejected buy clears the entry.
        if self.buy_pending:
            if qty > 0:
                self.buy_pending = False
                self.holding = True
                self.ever_traded = True
                if close > self.peak_close:
                    self.peak_close = close
            elif seq > self.entry_seq:
                self.buy_pending = False
                self.holding = False
                self.entry_close = 0

        if self.holding and qty == 0:
            # The position is gone (a sell filled): re-arm after cooldown.
            self.holding = False
            self.last_exit_seq = seq
        elif qty > 0:
            self.holding = True

        if self.holding:
            return self._maybe_exit(state, seq, close, qty)
        return self._maybe_enter(state, seq, close)

    def _maybe_exit(self, state, seq, close, qty):
        """Sell the whole position when the first exit rule fires."""
        if close > self.peak_close:
            self.peak_close = close
        held = seq - self.entry_seq
        gain = self._bps_move(close, self.entry_close)
        target = (FALLBACK_TAKE_PROFIT_BPS if self.entry_fallback
                  else TAKE_PROFIT_BPS)
        if gain >= target:
            return self._sell(qty)
        if (held >= TRAIL_MIN_HELD and gain >= TRAIL_MIN_GAIN_BPS
                and self._bps_move(close, self.peak_close) <= -TRAIL_DROP_BPS):
            return self._sell(qty)
        if held >= MAX_HOLD_BARS:
            return self._sell(qty)
        if gain <= -STOP_BPS:
            return self._sell(qty)
        return []

    def _maybe_enter(self, state, seq, close):
        """Buy the whole account once the dip and the bounce both hold."""
        if seq >= NO_ENTRY_AFTER_SEQ:
            return []
        if seq - self.last_exit_seq < COOLDOWN_BARS:
            return []
        if len(self.closes) < DIP_WINDOW:
            return []
        dip_bar = (FALLBACK_DIP_BPS if self._fallback_armed(seq) else DIP_BPS)
        if self._drop_bps() > -dip_bar:
            return []
        if not self._bounced():
            return []
        self.entry_close = close
        self.entry_seq = seq
        self.entry_fallback = self._fallback_armed(seq)
        self.peak_close = close
        self.buy_pending = True
        return [{"side": "buy", "symbol": SYMBOL,
                 "notional_quote_units": state.cash,
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]

    def _fallback_armed(self, seq):
        """True once the window is old and no trade has happened yet."""
        return not self.ever_traded and seq >= FALLBACK_AFTER_SEQ

    @staticmethod
    def _sell(qty):
        return [{"side": "sell", "symbol": SYMBOL,
                 "qty": str(qty),
                 "max_slippage_bps": MAX_SLIPPAGE_BPS}]


def main():
    bot = DipBounceBot()
    makefun_bars.run(bot.on_batch)


if __name__ == "__main__":
    main()
