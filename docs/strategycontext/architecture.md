# Architecture: Where a Strategy Sits

## The components

`python app.py` (or gunicorn in production) starts:

1. **Flask web server, port 5000.** The UI, login, and the REST API under
   `/api/v1/` (orders, positions, quotes, option helpers). It holds the broker
   session token after login.
2. **WebSocket proxy, port 8765.** Started by `app.py` (a thread on the
   development server, a child process under gunicorn with eventlet). It owns
   the **single** connection to the broker's market-data WebSocket and fans
   ticks out to every client.
3. **ZeroMQ bus, port 5555.** Internal pub/sub between the broker adapter and
   the proxy. Strategies never touch it.

Strategy processes are started later by the `/python` host, one process per
strategy.

```
 Flask :5000 (REST /api/v1, UI)        WebSocket proxy :8765
   ^          |                          |   holds THE broker feed
   |          | broker REST              |   (one per installation)
   |          v                          v
   |      Broker REST API           Broker market-data WebSocket
   |
   |  HTTP POST + apikey             ws://127.0.0.1:8765 (own socket each)
   +-------------------+   +------------------------------+
                       |   |
                  strategy process A      strategy process B      browser pages
```

## One broker connection, many clients

- The broker connection opens when the first client authenticates with the
  proxy, and is then reused (`self.broker_adapters[user_id]` in
  `websocket_proxy/server.py`; pooled per `{broker}_{user_id}` in
  `broker_factory.py`).
- Each strategy's `client.connect()` opens a socket **to the proxy only**.
- When several clients subscribe the same symbol, the proxy subscribes it at the
  broker once and copies each tick to all of them. The broker sees one
  connection and one subscription.
- The proxy limits each symbol to one message per 50 ms per client.

## The path of one tick

1. The broker sends a trade on its WebSocket.
2. The broker adapter (`broker/<name>/streaming/`) converts it to the common
   format (symbol `NIFTY09NOV2624550CE`, exchange `NFO`, `ltp`).
3. The adapter publishes it on the ZeroMQ bus.
4. The proxy sends it to every client subscribed to that symbol.
5. In the strategy, the SDK's background thread stores it in `ltp_data` and
   calls the strategy's callback.

## The path of one order

1. The strategy calls `client.placeorder(...)`: an HTTP POST to
   `/api/v1/placeorder` with the API key in the body.
2. Flask validates the key and the fields, finds the broker session.
3. If the platform is in Analyze mode, the order goes to the sandbox; otherwise
   to the broker.
4. The response carries an order id. Fills and rejections arrive later on the
   order-update stream (`subscribe_orders`) or through `orderstatus`.
5. The `strategy` label on the order feeds the per-strategy position book
   (`database/strategy_book_db.py`) through the event bus, which is how
   per-strategy P&L is computed. The broker only sees one netted position per
   contract.

## Compared with a single-process Node.js bot

| Single-process bot | FastAlgo |
| --- | --- |
| Auto-login at startup | Login through the UI; Flask stores the broker token |
| Global broker socket variable | The proxy owns the broker socket |
| `app.listen()` | Flask on port 5000 |
| `brokerSocket.subscribe(tokens, cb)` | `client.connect()` then `client.subscribe_ltp(instruments, on_data_received=cb)` |
| Strategy function in the same process | Strategy is a separate process using REST for orders and the proxy for prices |

The split exists because many consumers (scripts, option chain, charts, Flow,
scalping terminal, external tools) need the same feed at once, and the broker
should see only one connection. The extra local hop costs about a millisecond.

## Feed health, as it is today

- Broker adapters retry on their own and then give up silently (Zerodha after
  50 tries, Angel after 10).
- The proxy records per user whether the adapter reports connected and when the
  last tick was delivered (`last_tick_time`, `get_adapter_health()`), but only
  logs silence at debug level, because it has no market calendar. Clients are
  never told.
- A connected adapter can deliver nothing (issues #1226, #1419, #1421), so tick
  silence during market hours is the reliable signal. A strategy can watch it
  itself; see [writing-strategies.md](writing-strategies.md).
