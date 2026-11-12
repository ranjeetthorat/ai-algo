#!/usr/bin/env python
"""
Sanity Test Strategy (built on the strategy kit)

Checks the Python strategy host end to end:

  1. Settings  - read from the strategy card (PARAMS below)
  2. Resume    - Start mode: new starts fresh, old continues the saved position
  3. Feed      - live NIFTY spot from the shared feed, with the feed watch on
  4. Orders    - SELL 1 lot ATM CE and 1 lot ATM PE on one expiry, fills confirmed
  5. Stream    - live prices for both legs for STREAM_SECONDS, then finish

Both legs use one strike: the ATM strike is resolved once, for the CE, and the
PE is derived from it.

The positions are left open when the test finishes. With MIS they are squared
off at the exchange's intraday cut-off. Any rejection or unclear order stops
the run with the reason shown on the strategy card.
"""

from strategy_kit import Strategy

PARAMS = {
    "start_mode": {
        "type": "choice",
        "default": "new",
        "options": ["new", "old"],
        "label": "Start mode",
        "help": "new: start fresh; the saved state is set aside. old: continue the saved "
        "state as it is. With old, you make sure it matches your positions.",
    },
    "expiry": {"type": "str", "default": "09NOV26", "label": "Expiry (DDMMMYY)"},
    "lots": {"type": "int", "default": 1, "min": 1, "max": 5, "label": "Lots per leg"},
    "product": {"type": "choice", "default": "MIS", "options": ["MIS", "NRML"], "label": "Product"},
    "stream_seconds": {
        "type": "int",
        "default": 300,
        "min": 10,
        "label": "Stream prices for (seconds)",
    },
}

UNDERLYING = "NIFTY"
INDEX_EXCHANGE = "NSE_INDEX"
OPTION_EXCHANGE = "NFO"


def spot(s):
    """NIFTY spot from the live feed, falling back to one REST quote outside market hours."""
    for _ in range(50):
        price = s.ltp(INDEX_EXCHANGE, UNDERLYING)
        if price is not None:
            return price, "live feed"
        if not s.sleep(0.2):
            return None, ""
    quote = s.read(
        s.client.quotes, symbol=UNDERLYING, exchange=INDEX_EXCHANGE, what="the NIFTY quote"
    )
    return float(quote["data"]["ltp"]), "quote"


def resolve_legs(s):
    resp = s.read(
        s.client.optionsymbol,
        underlying=UNDERLYING,
        exchange=INDEX_EXCHANGE,
        expiry_date=s.params["expiry"].upper(),
        offset="ATM",
        option_type="CE",
        what=f"the ATM call for {s.params['expiry']}",
    )
    ce = resp["symbol"]
    if not ce.endswith("CE"):
        s.stop(f"Unexpected option symbol {ce}")
    pe = ce[:-2] + "PE"
    s.read(s.client.symbol, symbol=pe, exchange=OPTION_EXCHANGE, what=f"contract details for {pe}")
    return ce, pe, int(resp["lotsize"])


def main(s):
    mode = s.resume()
    s.watch_feed(heartbeat=(INDEX_EXCHANGE, UNDERLYING))

    price, source = spot(s)
    if price is None:
        return
    s.log(f"PASS  {UNDERLYING} spot {price} ({source}), nearest 50 strike {round(price / 50) * 50}")

    if mode == "fresh":
        ce, pe, lot_size = resolve_legs(s)
        s.state["legs"] = [ce, pe]
        s.save_state()
        s.log(f"PASS  legs {ce} / {pe}, lot size {lot_size}")
        quantity = lot_size * s.params["lots"]
        for symbol in (ce, pe):
            fill = s.order(symbol, OPTION_EXCHANGE, "SELL", quantity, product=s.params["product"])
            s.log(f"PASS  sold {fill.quantity} {fill.symbol} @ {fill.average_price}")
    else:
        if not s.open_positions():
            s.log("Today's test already finished and its positions are closed. Nothing to do.")
            return
        ce, pe = s.state["legs"]
        s.log(f"PASS  continuing with {ce} / {pe}: {s.open_positions()}")

    s.subscribe([(OPTION_EXCHANGE, ce), (OPTION_EXCHANGE, pe)])
    s.log(f"Streaming prices for {s.params['stream_seconds']}s")
    for second in range(s.params["stream_seconds"]):
        if not s.sleep(1):
            return
        if second % 5 == 0:
            s.log(
                f"TICK  {UNDERLYING} {s.ltp(INDEX_EXCHANGE, UNDERLYING)}  "
                f"CE {s.ltp(OPTION_EXCHANGE, ce)}  PE {s.ltp(OPTION_EXCHANGE, pe)}"
            )
    s.log("Sanity test finished. Positions are left open.")


Strategy(PARAMS, product="MIS").run(main)
