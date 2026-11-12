#!/usr/bin/env python
"""
Short Straddle Window (built on the strategy kit)

Sells the ATM call and put of one expiry, then watches both:

  1. Entry     - SELL lots of a CE and a PE. With ATM offset 0 both are the
                 nearest strike; offset N moves the CE N strikes up and the PE
                 N strikes down (option_strikes.py, the Node app's rounding).
  2. Watch     - each leg against its own sell price.
  3. Window    - when either leg's price RISES by the window percent above its
                 sell price, BUY BACK BOTH legs.
  4. Repeat    - sell a fresh pair at the new ATM strike, up to the cycle limit.
  5. Square off - at the square-off time, buy back whatever is open and stop.

Example: window 20%, CE sold at 100 and PE at 90. The cycle closes when the CE
reaches 120 or the PE reaches 108, whichever comes first.

Settings are edited from the strategy card. Every order waits for its fill; a
rejection or an unclear order stops the run with the reason on the card and
leaves the position for you to handle.

Start mode (a setting): "new" starts fresh and sets the saved state aside;
"old" continues the saved state as it is, including legs left open, without
asking the broker. With "old" you are responsible for it matching your
positions: close a leg by hand and "old" will still try to buy it back.
"""

from datetime import date, datetime, time

from option_strikes import option_strike, option_symbol, strike_step
from strategy_kit import IST, Strategy

PARAMS = {
    "start_mode": {
        "type": "choice",
        "default": "new",
        "options": ["new", "old"],
        "label": "Start mode",
        "help": "new: start fresh; the saved state is set aside. old: continue the saved "
        "state as it is. With old, you make sure it matches your positions.",
    },
    "underlying": {
        "type": "choice",
        "default": "NIFTY",
        "options": ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"],
        "label": "Underlying",
    },
    "expiry": {
        "type": "str",
        "default": "",
        "label": "Expiry (DDMMMYY)",
        "help": "Leave empty for the nearest expiry, e.g. 10NOV26.",
    },
    "atm_offset": {
        "type": "int",
        "default": 0,
        "min": 0,
        "max": 10,
        "label": "ATM offset (strikes)",
        "help": "0 sells the ATM strike. 1 sells one strike out of the money on each side: call up, put down.",
    },
    "lots": {"type": "int", "default": 1, "min": 1, "max": 10, "label": "Lots per leg"},
    "product": {"type": "choice", "default": "MIS", "options": ["MIS", "NRML"], "label": "Product"},
    "window_percent": {
        "type": "float",
        "default": 20.0,
        "min": 1.0,
        "max": 500.0,
        "label": "Window percent",
        "help": "Buy back both legs when either rises this much above its sell price.",
    },
    "max_cycles": {
        "type": "int",
        "default": 5,
        "min": 1,
        "max": 50,
        "label": "Cycles per day",
        "help": "No new pair is sold after this many cycles.",
    },
    "first_entry": {
        "type": "str",
        "default": "09:20",
        "label": "First entry after (HH:MM)",
        "help": "No pair is sold before this time.",
    },
    "squareoff_time": {
        "type": "str",
        "default": "15:15",
        "label": "Square off at (HH:MM)",
        "help": "Open legs are bought back and the run ends at this time.",
    },
}

#: Index -> (index exchange, options exchange, exchange whose session it trades in)
MARKETS = {
    "NIFTY": ("NSE_INDEX", "NFO", "NFO"),
    "BANKNIFTY": ("NSE_INDEX", "NFO", "NFO"),
    "FINNIFTY": ("NSE_INDEX", "NFO", "NFO"),
    "MIDCPNIFTY": ("NSE_INDEX", "NFO", "NFO"),
    "SENSEX": ("BSE_INDEX", "BFO", "BFO"),
    "BANKEX": ("BSE_INDEX", "BFO", "BFO"),
}

#: How often the open legs are written to the log, in seconds.
STATUS_EVERY = 60


def now_ist():
    return datetime.now(IST)


def parse_clock(s, name):
    text = s.params[name].strip()
    try:
        hour, minute = (int(part) for part in text.split(":"))
        return time(hour, minute)
    except ValueError:
        s.stop(f"{PARAMS[name]['label']} must be a time like 09:20, not '{text}'.")


def nearest_expiry(s, underlying, options_exchange, today):
    """The first listed options expiry on or after today, as DDMMMYY."""
    response = s.read(
        s.client.expiry,
        symbol=underlying,
        exchange=options_exchange,
        instrumenttype="options",
        what=f"the {underlying} expiry dates",
    )
    dates = []
    for text in response.get("data") or []:
        try:
            dates.append(datetime.strptime(text, "%d-%b-%y").date())
        except (TypeError, ValueError):
            continue
    upcoming = sorted(d for d in dates if d >= today)
    if not upcoming:
        s.stop(f"No upcoming {underlying} options expiry is listed. Download the master contract.")
    return upcoming[0].strftime("%d%b%y").upper()


class Straddle:
    """The cycle logic. ``s.state`` holds everything a restart needs."""

    def __init__(self, s, today: date | None = None):
        self.s = s
        self.p = s.params
        self.underlying = self.p["underlying"]
        self.index_exchange, self.options_exchange, self.session = MARKETS[self.underlying]
        self.interval = strike_step(self.underlying)
        self.first_entry = parse_clock(s, "first_entry")
        self.squareoff = parse_clock(s, "squareoff_time")
        if self.first_entry >= self.squareoff:
            s.stop("First entry must be earlier than the square-off time.")
        self.window = self.p["window_percent"] / 100.0
        self.today = today or now_ist().date()
        self.expiry = None
        self.last_status = 0.0
        self.waiting_logged = False
        state = s.state
        state.setdefault("cycles", 0)  # completed cycles today
        state.setdefault("legs", {})  # symbol -> sell price, for the open cycle
        day = self.today.isoformat()
        if state.get("day") not in (None, day) and state["cycles"]:
            # Old mode carried the state into a new day: the limit is per day.
            s.log(f"New trading day: the cycle count restarts (was {state['cycles']}).")
            state["cycles"] = 0
        state["day"] = day

    # -- helpers ------------------------------------------------------------

    @property
    def legs(self) -> dict:
        return self.s.state["legs"]

    def _open_key(self, symbol):
        return f"{self.options_exchange}:{symbol}:{self.p['product']}".upper()

    def is_open(self, symbol) -> bool:
        return self.s.open_positions().get(self._open_key(symbol), 0) != 0

    def trigger(self, symbol) -> float:
        return self.legs[symbol] * (1 + self.window)

    def spot(self):
        """The underlying's price from the live feed, or one quote if no tick has arrived yet."""
        s = self.s
        for _ in range(25):
            price = s.ltp(self.index_exchange, self.underlying)
            if price is not None:
                return price
            if not s.sleep(0.2):
                s.stop("Stopped while waiting for the first price.")
        quote = s.read(
            s.client.quotes,
            symbol=self.underlying,
            exchange=self.index_exchange,
            what=f"the {self.underlying} quote",
        )
        return float(quote["data"]["ltp"])

    def resolve_pair(self):
        """The call and put to sell: strikes from option_strikes, contracts checked as listed."""
        s = self.s
        if self.expiry is None:
            given = self.p["expiry"].strip().upper()
            self.expiry = given or nearest_expiry(
                s, self.underlying, self.options_exchange, self.today
            )
            s.log(f"Expiry {self.expiry}")
        price = self.spot()
        offset = self.p["atm_offset"]
        legs = []
        for kind in ("CE", "PE"):
            strike = option_strike(price, kind, offset, self.interval)
            symbol = option_symbol(self.underlying, self.expiry, strike, kind)
            contract = s.read(
                s.client.symbol,
                symbol=symbol,
                exchange=self.options_exchange,
                what=f"contract {symbol} (strike {strike} may not be listed for {self.expiry})",
            )
            legs.append((symbol, int(float(contract["data"]["lotsize"]))))
        (ce, ce_lot), (pe, pe_lot) = legs
        if ce_lot != pe_lot:
            s.stop(f"{ce} and {pe} have different lot sizes ({ce_lot} and {pe_lot}).")
        s.log(f"{self.underlying} {price}: offset {offset} gives {ce} and {pe}")
        return ce, pe, ce_lot

    # -- the cycle ----------------------------------------------------------

    def open_cycle(self):
        s = self.s
        ce, pe, lot_size = self.resolve_pair()
        quantity = lot_size * self.p["lots"]
        number = s.state["cycles"] + 1
        s.log(f"Cycle {number}: selling {quantity} {ce} and {quantity} {pe}")
        for symbol in (ce, pe):
            fill = s.order(
                symbol, self.options_exchange, "SELL", quantity, product=self.p["product"]
            )
            # Saved per leg, so a restart between the two orders knows the first.
            self.legs[symbol] = fill.average_price
            s.state["lot_quantity"] = quantity
            s.save_state()
        s.subscribe([(self.options_exchange, ce), (self.options_exchange, pe)])
        s.log(
            f"Cycle {number} open: {ce} @ {self.legs[ce]} (exit at {self.trigger(ce):.2f}), "
            f"{pe} @ {self.legs[pe]} (exit at {self.trigger(pe):.2f})"
        )

    def close_cycle(self, why):
        """Buy back every open leg, then count the cycle."""
        s = self.s
        number = s.state["cycles"] + 1
        s.log(f"Cycle {number}: {why}. Buying back both legs.")
        for symbol in list(self.legs):
            if self.is_open(symbol):
                quantity = -s.open_positions()[self._open_key(symbol)]
                fill = s.order(
                    symbol, self.options_exchange, "BUY", quantity, product=self.p["product"]
                )
                s.log(f"Bought back {symbol} @ {fill.average_price} (sold @ {self.legs[symbol]})")
            del self.legs[symbol]
            s.save_state()
        s.state["cycles"] = number
        s.save_state()
        s.log(f"Cycle {number} closed. {number} of {self.p['max_cycles']} cycles done today.")

    def breached(self):
        """The first leg whose price has risen past its exit level, with its price, or None."""
        for symbol in self.legs:
            price = self.s.ltp(self.options_exchange, symbol)
            if price is not None and price >= self.trigger(symbol):
                return symbol, price
        return None

    def log_status(self, clock: float):
        if clock - self.last_status < STATUS_EVERY:
            return
        self.last_status = clock
        parts = []
        for symbol, sold in self.legs.items():
            price = self.s.ltp(self.options_exchange, symbol)
            parts.append(
                f"{symbol} {price if price is not None else '-'} (sold {sold}, exit {self.trigger(symbol):.2f})"
            )
        self.s.log("Watching: " + "; ".join(parts))

    def finish(self, message):
        # Nothing is saved: whether the day is done is worked out again on every
        # start, from the cycles done, the current limit and the clock, so a
        # raised "Cycles per day" takes effect the same day.
        self.s.log(message)

    def done_for_today(self, now: datetime) -> str | None:
        """Why no more cycles can run today, or None. Only meaningful with nothing open."""
        if now.time() >= self.squareoff:
            return f"Past the square-off time ({self.squareoff:%H:%M}). Done for today."
        cycles, limit = self.s.state["cycles"], self.p["max_cycles"]
        if cycles >= limit:
            return (
                f"{cycles} of {limit} cycles are already done today. Raise Cycles per day "
                "in the strategy settings to run more."
            )
        return None

    # -- one tick of the main loop ---------------------------------------------

    def step(self, now: datetime, clock: float) -> bool:
        """Act on the time and prices once. Returns False when the run is over."""
        s = self.s
        wall = now.time()
        if wall >= self.squareoff:
            if self.legs:
                self.close_cycle("square-off time reached")
            self.finish("Square-off time reached. Done for today.")
            return False
        if self.legs:
            hit = self.breached()
            if hit:
                symbol, price = hit
                self.close_cycle(
                    f"{symbol} rose to {price}, past {self.trigger(symbol):.2f} "
                    f"({self.p['window_percent']:g}% above its sell price {self.legs[symbol]})"
                )
            else:
                self.log_status(clock)
            return True
        if s.state["cycles"] >= self.p["max_cycles"]:
            self.finish(f"All {self.p['max_cycles']} cycles for today are done.")
            return False
        if wall < self.first_entry:
            if not self.waiting_logged:
                s.log(f"Waiting for {self.first_entry:%H:%M} to sell the first pair.")
                self.waiting_logged = True
            return True
        self.open_cycle()
        return True

    def recover(self, mode):
        """After a restart: continue a full pair, or close a half-opened one."""
        s = self.s
        if mode == "fresh":
            s.state.update({"cycles": 0, "legs": {}})
            s.save_state()
            return
        # The recorded fills are the strategy's own record of what it holds (the
        # broker is not asked; the user chose Old). Drop legs the fills show as
        # closed, and add a leg that filled just before the last run ended,
        # before its sell price was saved here.
        for symbol in [x for x in self.legs if not self.is_open(x)]:
            del self.legs[symbol]
        fills = (s.state.get("_kit") or {}).get("fills") or []
        for key in s.open_positions():
            exchange, symbol, product = key.split(":")
            if exchange == self.options_exchange and product == self.p["product"].upper():
                if symbol not in self.legs:
                    sold = [
                        f["average_price"]
                        for f in fills
                        if f["symbol"].upper() == symbol and f["action"] == "SELL"
                    ]
                    self.legs[symbol] = sold[-1] if sold else 0.0
        if len(self.legs) == 1:
            self.close_cycle("only one leg was sold before the last run ended")
        elif self.legs:
            s.subscribe([(self.options_exchange, x) for x in self.legs])
            s.log(
                f"Continuing cycle {s.state['cycles'] + 1}: "
                + ", ".join(f"{k} @ {v}" for k, v in self.legs.items())
            )
        s.save_state()


def market_open_today(s, exchange) -> bool:
    response = s.read(
        s.client.timings, date=now_ist().date().isoformat(), what="today's market timings"
    )
    return any(
        str(row.get("exchange", "")).upper() == exchange for row in response.get("data") or []
    )


def main(s):
    mode = s.resume()
    straddle = Straddle(s)
    if mode == "continue":
        s.log(f"Today so far: {s.state['cycles']} of {s.params['max_cycles']} cycles done.")
    if not s.open_positions():
        reason = straddle.done_for_today(now_ist())
        if reason:
            s.log(reason)
            return
    if not s.open_positions() and not market_open_today(s, straddle.session):
        s.log(f"{straddle.session} is closed today. Nothing to do.")
        return
    s.watch_feed(
        heartbeat=(straddle.index_exchange, straddle.underlying), session_exchange=straddle.session
    )
    straddle.recover(mode)
    clock = 0.0
    while s.sleep(1):
        clock += 1
        if not straddle.step(now_ist(), clock):
            return


if __name__ == "__main__":
    Strategy(PARAMS, product="MIS").run(main)
