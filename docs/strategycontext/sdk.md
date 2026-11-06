# The `openalgo` SDK, as Used by Strategies

Package: `openalgo` (pinned; 2.0.5 at the time of writing). The package name
stays `openalgo` in FastAlgo; client scripts depend on it.

## The client

```python
import os
from openalgo import api

client = api(
    api_key=os.getenv("OPENALGO_API_KEY"),
    host=os.getenv("HOST_SERVER") or os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000"),
    ws_url=os.getenv("WEBSOCKET_URL", "ws://127.0.0.1:8765"),
    verbose=False,          # 1: connection logs, 2: every tick
    auto_reconnect=True,
)
```

- `api` combines every section (orders, data, account, options, feed,
  Telegram, utilities) in one object.
- **Construction makes no network call.** A wrong key or a stopped server shows
  up on the first real call. `client.analyzerstatus()` is a cheap first check.
- One pooled HTTP connection is reused by every REST call.

## Responses and errors

Every REST call returns a dict and never raises:

```python
{"status": "success", ...}
{"status": "error", "message": "...", "code": 403, "error_type": "http_error"}
{"status": "error", "message": "Failed to connect to the server...", "error_type": "connection_error"}
{"status": "error", "message": "Request timed out...", "error_type": "timeout_error"}
```

`error_type` is one of `connection_error`, `timeout_error`, `http_error`,
`api_error`. Check `status` after every call.

## Orders

Quantity is in units, not lots (NIFTY: 1 lot = 65 at the time of writing; read
`lotsize` from `symbol()`). All arguments are keyword-only.

```python
# Market
client.placeorder(strategy="My Strategy", symbol="NIFTY09NOV2624550CE", exchange="NFO",
                  action="SELL", price_type="MARKET", product="MIS", quantity=65)
# {"status": "success", "orderid": "..."}   (+ "mode": "analyze" in Analyze mode)

# Limit
client.placeorder(..., price_type="LIMIT", price=182.50)

# Stop-loss limit and stop-loss market
client.placeorder(..., action="BUY", price_type="SL",   trigger_price=240, price=242)
client.placeorder(..., action="BUY", price_type="SL-M", trigger_price=240)
```

- `price_type`: `MARKET`, `LIMIT`, `SL`, `SL-M`. `product`: `MIS`, `NRML`,
  `CNC` (options take MIS or NRML only). `action`: `BUY`, `SELL`.
- **The platform does not check that LIMIT has a price.** A missing price is
  sent as 0 and the broker rejects it.
- Prices must be multiples of the tick size (0.05 for NIFTY options).
- **Success means accepted, not filled.** Confirm with `orderstatus` or the
  order stream.
- Other order calls: `modifyorder`, `cancelorder`, `cancelallorder`,
  `basketorder`, `splitorder`, `placesmartorder`.
- **`closeposition()` squares off the whole account**, not one strategy.

## Account and positions

| Call | Returns |
| --- | --- |
| `orderstatus(order_id=..., strategy=...)` | `data.order_status` (`complete`, `open`, `rejected`, `cancelled`), `average_price`, `quantity` |
| `openposition(strategy=..., symbol=..., exchange=..., product=...)` | `quantity` held in that contract and product |
| `positionbook()` | `data` rows: `symbol`, `exchange`, `product`, `quantity` (negative for short), `average_price`, `pnl` |
| `orderbook()`, `tradebook()`, `funds()`, `holdings()` | as named |
| `analyzerstatus()` | `data.analyze_mode` (True in Analyze mode) |

## Market data over REST

These go to the broker's REST API. Do not call them in a loop.

| Call | Use |
| --- | --- |
| `quotes(symbol=..., exchange=...)` | One quote (`data.ltp`) |
| `multiquotes(symbols=[...])` | Several at once |
| `depth(...)`, `history(...)` | Order book, candles |
| `symbol(symbol=..., exchange=...)` | Contract details: `lotsize`, `tick_size`, expiry; also proves a symbol exists |
| `expiry(symbol=..., exchange=..., instrumenttype=...)` | Listed expiries |
| `timings(date=...)`, `holidays(year=...)` | Exchange session times and holidays |

## Option helpers

```python
client.optionsymbol(underlying="NIFTY", exchange="NSE_INDEX", expiry_date="09NOV26",
                    offset="ATM", option_type="CE")
# {"status": "success", "symbol": "NIFTY09NOV2624550CE", "lotsize": 65,
#  "tick_size": 0.05, "underlying_ltp": 24536.6, ...}

client.optionsorder(underlying="NIFTY", exchange="NSE_INDEX", expiry_date="09NOV26",
                    offset="ATM", option_type="CE", action="SELL", quantity=65,
                    price_type="MARKET", product="MIS", strategy="My Strategy")
```

- `offset`: `ATM`, `ITM1`-`ITM50`, `OTM1`-`OTM50`. The server picks the listed
  strike nearest to the underlying's price (for NIFTY, the nearest 50).
- `strike_int` is deprecated; omit it so the server uses real listed strikes.
- Resolving the CE and PE separately can land on different strikes if the
  underlying moves between calls. Resolve once and derive the other by swapping
  the `CE`/`PE` suffix, then confirm it with `symbol()`.
- Also: `optionsmultiorder`, `optionchain`, `optiongreeks`, `syntheticfuture`.

Symbol format: `[Base][DDMMMYY][Strike][CE|PE]`, e.g. `NIFTY09NOV2624550PE`;
futures `[Base][DDMMMYY]FUT`. Exchanges: `NSE_INDEX` for index spot, `NFO` for
NSE options.

## Live prices: the WebSocket feed

```python
latest = {}

def on_ltp(msg):
    # {"type": "market_data", "symbol": "NIFTY09NOV2624550CE", "exchange": "NFO",
    #  "mode": 1, "data": {"ltp": 182.4, "timestamp": 1762667412000}}
    latest[msg["symbol"]] = msg["data"]["ltp"]

if not client.connect():                      # True only when connected AND authenticated
    raise SystemExit("could not reach the market feed")
client.subscribe_ltp([{"exchange": "NFO", "symbol": "NIFTY09NOV2624550CE"},
                      {"exchange": "NFO", "symbol": "NIFTY09NOV2624550PE"}],
                     on_data_received=on_ltp)
...
client.unsubscribe_ltp([...]); client.disconnect()
```

What `connect()` does:

1. Opens a socket to the proxy (`ws_url`), not to the broker.
2. Starts a daemon thread that owns the socket, with a ping every 20 s and a
   10 s pong timeout so a dead socket is noticed.
3. Sends `{"action": "authenticate", "api_key": ...}`; the proxy replies
   `{"type": "auth", "status": "success", "broker": ..., "user_id": ...}`.
4. Waits up to 5 s to connect and 5 s to authenticate, then returns a boolean.

Two ways to read prices:

- **Callback:** runs on the SDK's socket thread for every tick. Keep it to
  storing values. A slow callback (an HTTP call, a sleep) delays every later
  tick.
- **Cache:** `client.get_ltp(exchange=..., symbol=...)` reads the SDK's own
  memory: `{"ltp": {"NFO": {"NIFTY09NOV2624550CE": {"ltp": 182.4, "timestamp": ...}}}}`.
  **No network call**, safe to poll.

Other streams, same pattern: `subscribe_quote` (OHLC, volume, best bid and
ask), `subscribe_depth` (5 levels), `subscribe_orders(on_order_update=fn)` for
the account's own order updates:
`{"type": "order_update", "orderid", "symbol", "action", "order_status", "filled_quantity", "pending_quantity", "average_price", "rejection_reason", ...}`.

Behaviour to know:

- **Reconnects are automatic and endless,** with backoff 1, 2, 5, 10, 30, 60 s,
  re-authenticating and re-subscribing everything. The strategy gets **no
  callback** for a drop; poll `client.connected` and `client.authenticated`.
- **The socket thread is a daemon.** When the main thread ends, the feed ends.
  Keep the main thread in a loop.
- **No ticks outside market hours;** subscribing still succeeds.
- **Unknown message types are dropped silently** by the SDK.
- Subscribe to order updates **before** placing orders, or early fills and
  rejections are missed.

## Telegram

`client.telegram(username=..., message=..., priority=5)` sends through the
platform's bot. It goes through the server, so it cannot report the server
itself being down.
