# Writing a FastAlgo strategy with an AI assistant

This guide is for an AI assistant (Claude, ChatGPT, or similar) that has been
asked to build a FastAlgo Python strategy for its user. It defines how to behave:
what to settle before writing, how to write it so the platform's standard
features are present, and how the user runs it. Follow it in order.

If you are reaching FastAlgo over MCP, you also have `search_docs` and `get_doc`.
**Read the real reference before you write** - the kit's exact API and the SDK
call signatures live in the docs, and reading the installed version beats
recalling an older one:

- `get_doc('strategycontext/writing-strategies.md')` - the kit, settings, resume,
  orders, the feed watch, strike selection, and how a run ends.
- `get_doc('strategycontext/sdk.md')` - every SDK call and its arguments.
- The worked examples: `strategies/examples/sanity_test.py` and
  `strategies/examples/short_straddle_window.py` (a repeating multi-cycle options
  strategy).

## The flow

1. **Clarify** the specification until nothing load-bearing is left to assume.
2. **Restate** it in one place and let the user confirm.
3. **Write** the strategy on the strategy kit, with every adjustable value in a
   `PARAMS` block.
4. **Show** the user the full source.
5. The user **saves** it and **uploads** it on the FastAlgo `/python` page, then
   **starts** it there themselves.

You never run the strategy. A hosted strategy runs as a process with the user's
live API key and places real orders, so starting it is always a deliberate human
action on `/python`, never something you do.

## Step 1: clarify before you assume

A hosted strategy trades real money unattended, so getting the specification
right matters more than answering quickly. Do **not** assume a detail the user did
not give. If any of the following is missing or ambiguous, ask one short question
that lists the choices, and wait for the answer:

- **Underlying / symbol and its exchange.** NIFTY on NSE_INDEX? a stock on NSE? a
  commodity on MCX?
- **Entry:** which side (buy/sell), how many legs, and what triggers it - on
  start, at a price level, on an indicator, on a signal.
- **Exit:**
  - the **stop-loss**: how far, in which direction, and whether that percent or
    amount is **fixed in the code** or an **adjustable setting**;
  - any **target**;
  - what happens **after an exit** - stop for the day, or run the **next cycle**.
- **Expiry** (for options): **new-expiry or old-expiry mode**, and which expiry.
- **Quantity**, in lots.
- **Product**: MIS (intraday) or NRML (carry).

Worked example. The user says: *"sell ATM, 10% stoploss, then next cycle."* That
is under-specified. Ask, in one message:

> A few things to pin down first:
> 1. 10% move in which direction - the premium rising 10% (a loss on a short), or
>    a 10% move in the underlying?
> 2. Fixed 10% in the code, or adjustable from the strategy's settings?
> 3. Which underlying and expiry, and new-expiry or old-expiry mode?
> 4. How many lots, and MIS or NRML?

Then restate the whole thing and let them confirm:

> So: short the ATM CE and PE on NIFTY, <expiry>, <n> lots, MIS. Square off a leg
> when its premium rises 10% above entry; after both are out, re-enter the next
> cycle at the new ATM until the schedule stops. Stop-loss adjustable from
> settings. Confirm and I'll write it.

## Step 2: write it on the strategy kit

Use the kit (`from strategy_kit import Strategy`), not a raw loop. The kit gives
every strategy the standard features you would otherwise hand-roll and get subtly
wrong:

- **logging** (`s.log(...)`, and whatever you `print`),
- **saved state and resume** with new/old modes (`s.resume()`, `s.state`,
  `s.save_state()`),
- **orders that stop the run on a rejection or timeout instead of retrying**
  (`s.order(...)` returns a `Fill`), because a blind retry can double a live
  position,
- **a feed watch** that stops the run if the market feed goes silent
  (`s.watch_feed()`),
- **a stop-aware sleep** (`s.sleep(seconds)` returns False when the host asks to
  stop) and **a clean stop with a reason** (`s.stop(reason)`).

The proven skeleton (from `writing-strategies.md` - read it for the full API):

```python
from strategy_kit import Strategy

PARAMS = {
    "start_mode": {"type": "choice", "default": "new", "options": ["new", "old"], "label": "Start mode"},
    "lots":    {"type": "int",    "default": 1, "min": 1, "label": "Lots per leg"},
    "expiry":  {"type": "str",    "default": "13NOV26",   "label": "Expiry (DDMMMYY)"},
    "product": {"type": "choice", "default": "MIS", "options": ["MIS", "NRML"], "label": "Product"},
}

def main(s):
    if s.resume() == "fresh":
        fill = s.order("NIFTY13NOV2624550CE", "NFO", "SELL", 75 * s.params["lots"],
                       product=s.params["product"])
        s.state["entry"] = fill.average_price
        s.save_state()
    elif not s.open_positions():
        return
    s.watch_feed()
    s.subscribe([("NFO", "NIFTY13NOV2624550CE")])
    while s.sleep(1):
        price = s.ltp("NFO", "NIFTY13NOV2624550CE")
        if price is not None and price >= 1.1 * s.state["entry"]:   # 10% stop on a short
            s.order("NIFTY13NOV2624550CE", "NFO", "BUY", 75 * s.params["lots"],
                    product=s.params["product"])
            return

Strategy(PARAMS).run(main)
```

For a multi-leg or multi-cycle strategy (the ATM straddle above), follow
`strategies/examples/short_straddle_window.py`: resolve the strike once, derive
both legs from it, record each leg's entry premium in `s.state`, and keep a `day`
counter in the state so a per-day limit resets on a new day. Resolve strikes with
`option_strikes` (`from option_strikes import option_strike, option_symbol,
strike_step`). Read that example with `get_doc` or ask the user to open it.

## Step 3: settings go in PARAMS

Every value the user might want to change - the underlying, the expiry, the lots,
the product, the start mode, **and the stop-loss** if you offered it as
adjustable - goes in the `PARAMS` dict, so the `/python` settings form shows it as
a field instead of burying it in the code. Each entry is
`{"type": ..., "default": ..., "label": ...}` with `type` one of `int`, `float`,
`str`, `bool`, `choice` (add `options` for `choice`, `min`/`max` for numbers,
`help` for a hint). `PARAMS` must be a plain literal, because the host reads it
without running the file. `s.params` holds the user's saved values merged over the
defaults.

## The rules that keep it safe

These come from `writing-strategies.md`; the ones that most often go wrong:

- **Credentials come from the environment**, never a literal. The host injects
  `OPENALGO_API_KEY`, `HOST_SERVER` and `WEBSOCKET_URL`; read them with
  `os.getenv` (the kit does this for you).
- **Confirm fills.** A `placeorder` success means accepted, not filled; take the
  entry price from the fill's `average_price`. The kit's `s.order` already waits
  for the final status.
- **Never retry an order blindly** after a timeout - it may have reached the
  broker. The kit stops the run instead; let it.
- **Resolve option strikes once** and derive the other leg from the same strike.
- **Keep feed callbacks tiny** - store the tick, decide in the main loop.
- **Never call `closeposition()` to exit one strategy** - it squares off the whole
  account. Buy back or sell each leg.
- **Sleep between checks** - a busy loop is killed on Linux (1 hour CPU limit).
  Keep the loop on `s.sleep()` so the feed watch runs.

## Step 4 and 5: hand it over

Show the full source in your reply. Tell the user to save it as a `.py` file,
upload it on the FastAlgo `/python` page, set the options from the settings icon
on the card, and press Start. The strategy then runs on their server with its
logs, schedule, start/stop and error handling provided by the host.
