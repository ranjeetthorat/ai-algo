# Writing a Strategy

## What the host expects from a file

- A plain Python script that runs with `python file.py`. No required function,
  class or entry point.
- It **keeps running** as long as it should be active. When it exits, the run
  is over and it is not restarted that day.
- Configuration comes from environment variables (`OPENALGO_API_KEY`,
  `HOST_SERVER`, `WEBSOCKET_URL`, `STRATEGY_ID`, `STRATEGY_NAME`,
  `OPENALGO_STRATEGY_EXCHANGE`). The script does not read `.env` itself; the
  host copies the server's environment, which already contains `.env`.
- Output goes to stdout with `flush=True` (the host also passes `-u`). What is
  printed is exactly what the Logs page shows.
- Run outside the host (from a terminal), no API key is injected and `.env` is
  not loaded; test through `/python`.

## The run model

- Every Start is a new process running the file from the top.
- Nothing in memory survives a stop. A strategy that must continue after a
  restart has to save what it needs to a file and check it against the broker.
- Stop on Linux sends SIGTERM (5 s grace); on Windows the process is killed
  immediately.
- The scheduled stop ends the run at `schedule_stop` whatever it is doing.

## Rules

1. **Check `status` on every SDK call.** Nothing raises.
2. **Subscribe to order updates before placing orders.**
3. **Confirm fills.** `placeorder` success means accepted. Take entry prices
   from the fill (`average_price`), not from the LTP at order time.
4. **Never retry an order blindly.** A timeout on `placeorder` does not prove
   the order did not reach the broker.
5. **Resolve option strikes once** and derive the other side from the same
   strike.
6. **Keep WebSocket callbacks tiny.** Store the value; decide in the main loop.
7. **Keep the main thread alive** with a loop; the feed thread is a daemon.
8. **Do not poll REST quotes in a loop.** Use the WebSocket feed or
   `get_ltp()`.
9. **Never call `closeposition()` to exit one strategy.** It closes the whole
   account. Buy back or sell each leg.
10. **Record the Analyze/Live mode at entry** (`analyzerstatus()`). Orders follow
    the platform switch at send time, so a switch flipped mid-run sends exits
    to the sandbox while real positions stay open. Treat a change as a fault.
11. **Watch for a silent feed.** During the session, an index such as NIFTY
    ticks about every second; prolonged silence means the broker feed is down
    even if the socket looks connected.
12. **Busy loops die on Linux** (1 hour CPU limit). Sleep between checks.
13. **Mind memory.** `import openalgo` loads pandas and numpy: about 99 MB
    resident before any work; a simple strategy runs at about 107 MB.

## The strategy kit (recommended)

`strategies/lib/strategy_kit.py` gives every strategy the same settings, saved
state, resume rule, order handling and clean stop. The host puts it on
`PYTHONPATH`, so a strategy just imports it. Reference example:
`strategies/examples/sanity_test.py`.

```python
from strategy_kit import Strategy

PARAMS = {
    "start_mode": {"type": "choice", "default": "new", "options": ["new", "old"], "label": "Start mode"},
    "lots":    {"type": "int",    "default": 1,  "min": 1, "label": "Lots per leg"},
    "expiry":  {"type": "str",    "default": "09NOV26",    "label": "Expiry (DDMMMYY)"},
    "product": {"type": "choice", "default": "MIS", "options": ["MIS", "NRML"]},
}

def main(s):
    if s.resume() == "fresh":
        fill = s.order("NIFTY09NOV2624550CE", "NFO", "SELL", 65 * s.params["lots"],
                       product=s.params["product"])
        s.state["entry"] = fill.average_price
        s.save_state()
    elif not s.open_positions():
        return                                   # today's work already done
    s.watch_feed()                               # stop if the feed dies in session
    s.subscribe([("NFO", "NIFTY09NOV2624550CE")])
    while s.sleep(1):                            # False once the host asks to stop
        price = s.ltp("NFO", "NIFTY09NOV2624550CE")
        if price is not None and price >= 1.3 * s.state["entry"]:
            s.order("NIFTY09NOV2624550CE", "NFO", "BUY", 65 * s.params["lots"],
                    product=s.params["product"])
            return

Strategy(PARAMS).run(main)
```

### Settings

- `PARAMS` maps a setting name to `type` (`int`, `float`, `str`, `bool`,
  `choice`), `default`, and optionally `min`, `max`, `options` (for `choice`),
  `label`, `help`. Any other key is an error.
- The user edits them from the **settings icon** on the strategy card. The form
  is generated from `PARAMS` (number fields with min and max, text, switches,
  drop-downs), labels come from `label`, and `help` is shown under the field.
  Saved values apply at the next start.
- `s.params` holds the values: saved values from `OPENALGO_STRATEGY_PARAMS`
  merged over the defaults.
- `PARAMS` must be a plain literal (no variables or function calls), because the
  host reads it without running the script. A value saved before the
  declaration changed (for example a lower `max`) is flagged in the form and
  replaced by the default.
- An invalid declaration or value stops the run before `main` with the reason.

### Saved state and resume

- `s.state` is the strategy's own dictionary; `s.save_state()` writes it to
  `strategies/state/<STRATEGY_ID>.json` atomically. The key `_kit` belongs to the
  kit; do not edit it.
- The kit records every filled order, and a pending record before each order
  is sent.
- `s.resume()`, called once at start, follows the **Start mode** the user picks
  on the card. Declare it in `PARAMS` so it appears there:

  ```python
  "start_mode": {"type": "choice", "default": "new", "options": ["new", "old"],
                 "label": "Start mode"},
  ```

  | Start mode | Saved state | Result | Log |
  | --- | --- | --- | --- |
  | new | any | `"fresh"`; the old state is renamed to `<id>.set-aside-<time>.json`, never deleted | `Starting in NEW mode: fresh start` |
  | old | present | `"continue"` with `s.state` exactly as saved, any day | `Starting in OLD mode: continuing the saved state last used on <date>. Open: ...` |
  | old | none | `"fresh"` | `Starting in OLD mode, but there is no saved state: fresh start.` |

- **The broker is never asked.** With old, the user is responsible for the saved
  state matching their positions. A leg closed by hand at the broker is still
  "open" in the saved state, so the strategy will later try to buy it back,
  which opens a new position. Close by hand, then start with new.
- With old, an order that was in flight when the last run ended is logged as a
  WARNING and treated as not filled; a change between Analyze and Live since the
  saved orders is logged as a WARNING. A switch during the run still stops it.
- `s.open_positions()` nets the recorded fills per contract. Fills are kept
  until a new start, so positions carried to another day with old are known.
  A strategy with a per-day limit resets its own counter on a new day
  (`short_straddle_window.py` keeps a `day` in its state).

### Orders

`s.order(symbol, exchange, action, quantity, price_type="MARKET", price=None,
trigger_price=None, product=None, timeout=None)` returns a `Fill`
(`order_id`, `quantity`, `average_price`, ...) once the order is complete. It
stops the run when:

- the server refuses the order (validation, broker rejection at placement);
- the order is rejected or cancelled (the broker's reason is in the message);
- the order has no final status within the timeout (15 s default);
- placing it ended in a timeout, network error or server error, so it may or
  may not have reached the broker. It is never retried.

It also stops if the platform's Analyze/Live mode changes during the run. A
resting LIMIT order that should wait longer than the timeout is not a fit for
`s.order`; use `s.client` directly and manage it yourself.

### Reads, prices and the feed watch

- `s.read(s.client.<method>, ..., what="...")` retries network errors three
  times over about 5 s, then stops the run. Server error answers are not
  retried. Never use it for orders.
- `s.positions()`: net quantity per `EXCHANGE:SYMBOL:PRODUCT` from the broker.
- `s.subscribe([("NFO", "SYMBOL"), ...])`, then `s.ltp(exchange, symbol)` and
  `s.ltp_age(exchange, symbol)`.
- `s.watch_feed(heartbeat=("NSE_INDEX", "NIFTY"), max_silence=20, max_link_down=30)`:
  during the exchange session only, stops the run when the heartbeat index has
  been silent, or the link to the platform down, longer than the limits.
  Checked from `s.sleep()`, so keep the main loop on `s.sleep()`.

### Choosing strikes

`strategies/lib/option_strikes.py` picks strikes with the Node app's rounding
(`getNearestNiftyStrikePrice`), for any underlying:

```python
from option_strikes import option_strike, option_symbol, strike_step

step = strike_step("NIFTY")                          # 50; BANKNIFTY and SENSEX 100
ce = option_strike(spot, "CE", offset=1, step=step)  # nearest strike, 1 step up
pe = option_strike(spot, "PE", offset=1, step=step)  # nearest strike, 1 step down
symbol = option_symbol("NIFTY", "13NOV26", ce, "CE") # NIFTY13NOV2624600CE
```

- Paise are dropped, then a remainder of half a step or more rounds up: 24,524
  gives 24,500 and 24,525 gives 24,550. The platform's `optionsymbol` picks the
  lower strike at an exact midpoint, so use this module where a strategy must
  match the Node app.
- Offset 0 is the nearest strike for both legs; offset N moves a call N steps up
  and a put N steps down.
- Check the contract exists before ordering (`s.read(s.client.symbol, ...)`), which
  also gives its `lotsize`. `short_straddle_window.py` shows the pattern.

### How a run ends

| Exit code | When | Log |
| --- | --- | --- |
| 0 | `main` returned, or the host asked the strategy to stop | `Strategy finished.` |
| 3 | `s.stop(reason)` or any kit stop above | `FATAL: <reason>` |
| 4 | An exception in the strategy's own code | `FATAL: <type>: <message>` and the traceback |

The host shows the `FATAL:` reason on the strategy card as "Stopped: ...", and
the strategy then waits for the user to press Start instead of starting on its
next scheduled day. Positions are never closed by the kit when a run stops.

## Template without the kit

```python
#!/usr/bin/env python
import os, signal, sys, threading, time
from datetime import datetime
from openalgo import api

API_KEY  = os.getenv("OPENALGO_API_KEY", "")
API_HOST = os.getenv("HOST_SERVER") or os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")
WS_URL   = os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8765")
STRATEGY = os.getenv("STRATEGY_NAME", "My Strategy")
stop = threading.Event()

def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)

def fatal(reason):
    log(f"FATAL: {reason}")
    sys.exit(3)

def main():
    if not API_KEY:
        fatal("OPENALGO_API_KEY is not set. Start this strategy from /python.")
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    client = api(api_key=API_KEY, host=API_HOST, ws_url=WS_URL)

    latest = {}
    if not client.connect():
        fatal("Could not connect to the market feed")
    try:
        client.subscribe_orders(on_order_update=lambda m: log(f"ORDER {m}"))
        client.subscribe_ltp([{"exchange": "NSE_INDEX", "symbol": "NIFTY"}],
                             on_data_received=lambda m: latest.__setitem__(m["symbol"], m["data"]["ltp"]))
        while not stop.is_set():
            # decide here using latest[...]; place orders with client.placeorder(...)
            stop.wait(1)
    finally:
        client.disconnect()

if __name__ == "__main__":
    main()
```

## Debugging checklist

| Symptom | Look at |
| --- | --- |
| Strategy will not start | Platform log `log/errors.jsonl`: master contract not ready, file missing |
| Starts, then stops at once | The run log in `log/strategies/`: traceback or `FATAL:` line |
| "Invalid openalgo apikey" | Generate a key at `/apikey`; the host injects it at the next start |
| Orders rejected | `orderstatus` / order stream `rejection_reason`; market hours; margin; tick size; lot multiple |
| No ticks | Market closed? `client.authenticated`? Same symbol on `/websocket/test` |
| Card says Running but nothing happens | The process may be stuck rather than ended; check the log. Exits show on the card within 60 s |
| "Stopped: ..." and it did not start next morning | Intended: an errored strategy waits for Start. Read the reason, then press Start |
| Sold twice after a restart | Started with new while positions from the last run were open. Use old to continue them |
| Bought a leg it had already closed by hand | Started with old after closing positions by hand. Close by hand, then start with new |
| `ModuleNotFoundError: strategy_kit` | The script was run outside the host; start it from `/python`, or set `PYTHONPATH=strategies/lib` |
| Settings icon shows "PARAMS must be a plain dictionary" | `PARAMS` uses a variable or function call; write the values out literally |
