# Python Strategy Host: Settings, Fault Detection and Alarms, Memory, Start Now

Date: 2026-11-06 (revision 2, after the owner chose the manual-intervention model)
Scope: research and design. Nothing in the platform has been changed by this report.
Code read: `blueprints/python_strategy.py`, `launcher/keeper.py`,
`websocket_proxy/server.py`, broker streaming adapters, the `openalgo` 2.0.5 SDK,
`frontend/src/hooks/useSocket.ts`, `frontend/src/pages/python-strategy/`,
`services/strategy_module/`, `services/risk/`.

## 1. Summary

**Decision taken (section 3):** a client who uses Python strategies accepts that
a server crash, a power cut, or a broker feed that stays down needs a person to
step in. The platform does not resume strategies. Its job is to **detect the
fault fast and make it impossible to miss**, with an alarm in the browser and a
Telegram message.

| Question | Answer |
| --- | --- |
| Can the Node strategy run as a Python strategy? | **Yes, today**, with the SDK alone (section 4). |
| Can users edit lots, expiry, exit % in a UI? | **No.** Needs a host and frontend change (section 5). |
| Does the platform detect a dead broker feed? | **Half.** The WebSocket proxy already tracks "adapter connected" and "seconds since last tick" per user, but only writes it to the debug log. Nobody is told. Brokers stop retrying after a limit (Zerodha 50 tries, Angel 10) and then go silent (section 6.2). |
| Does the platform tell anyone when a strategy crashes? | **No.** The reaper marks it stopped within 60 s, records no error, sends no event, and the strategy page keeps showing it as running until refreshed (section 6.3). |
| Is "stop and do not resume" what the host does today? | **No, it does the opposite in two places.** After a hard server crash or power cut it restarts strategies that were running, and the next day's schedule starts a crashed strategy again. Both must be blocked for this model (section 6.3). |
| Is 150 MB enough memory? | **As a cap on resident memory for this strategy, yes, with about 40 MB to spare.** Measured: 107 MB. But today's limit is on *virtual* memory (1024 MB, Linux only, none on Windows); 150 MB of virtual memory would stop the script from even importing the SDK (section 8). |
| Start on a button while others keep schedules? | **Partly.** Start works only inside the schedule window. Small change (section 9). |

## 2. The requirement

From the owner's Node.js implementation:

- **R1 Settings per strategy**, edited in a UI and stored as JSON on the server:
  lots, expiry date, exit percent (50-80%).
- **R2 Entry:** read live NIFTY spot, round to the nearest 50, build the CE and
  PE symbols for the configured expiry, SELL both at MARKET, record the fill
  prices (CE 120 + PE 100 = 220).
- **R3 Watch** both legs' LTP continuously.
- **R4 Exit** when either leg's LTP reaches X% of the combined entry premium
  (70% of 220 = 154).
- **R5 Fault handling (revised):** detect process crash and broker feed loss,
  alarm the user, stop cleanly, never resume on its own.
- **R6 Stability:** 09:00 to 15:00 on an ordinary laptop without running out of
  memory.
- **R7 Start now** on a button, while other users keep scheduled starts.

## 3. Operating model (decided 2026-11-06)

**Rule:** any fault the strategy cannot handle with certainty ends the strategy.
It is not restarted by anything until a person acknowledges the alarm.

Consequences that shape every design below:

1. **Stopping is not the same as safe.** A stopped short-straddle strategy
   leaves its options sold. The alarm is therefore the safety mechanism, and it
   must say what is still open ("CE 24550 short 65, PE 24550 short 65"), not
   only that something stopped.
2. **Nothing may restart a stopped strategy behind the user's back:** not the
   restore-after-restart path, not the next day's schedule, not the reaper.
3. **"Clean slate" means the next start is a fresh entry.** To keep that safe,
   the start-up check from the sanity test becomes a **guard, not a resume**: if
   the account already holds a position in the contracts the strategy is about
   to sell, the strategy refuses to start and alarms. It never adopts the
   position. This uses the owner's idea (check whether the same sell exists)
   in its safe direction.
4. **Resume (OLD mode) is deferred, not discarded.** Section 10 keeps the
   design. The guard in point 3 is the first piece of it, so nothing built now
   is thrown away later.

## 4. Can it run today?

Every step maps to an SDK call that already works (verified by the 2026-11-05
sanity test run, `log/strategies/sanity_test_*`):

| Step | SDK | Notes |
| --- | --- | --- |
| Live spot | `subscribe_ltp([{"exchange": "NSE_INDEX", "symbol": "NIFTY"}])`, wait for the first tick | Shared broker feed, no broker rate limit. The same subscription doubles as the feed watchdog (section 6.2). |
| Strike and symbols | Round to 50 locally, or `optionsymbol(offset="ATM", expiry_date=...)`; derive the PE from the CE | `symbol()` validates and gives the lot size. |
| Start-up guard | `positionbook()` | Refuse to start if either contract is already held (section 3). |
| Sell both | `placeorder(action="SELL", price_type="MARKET", ...)` | Returns an order id, not a fill. |
| Fill prices | `subscribe_orders()` gives `average_price`; `orderstatus()` as fallback | Subscribe **before** placing, or early fills and rejections are missed (seen in the 2026-11-05 run). |
| Watch | `subscribe_ltp` callback | Runs on the SDK thread; record the price there, decide in the main loop. |
| Exit | `placeorder(action="BUY", price_type="MARKET", quantity=held)` per leg | Never `closeposition()`: it squares off the whole account. |
| Alert | `client.telegram(username=..., message=...)` | Goes through the server, so it cannot report the server itself being down. |
| Market hours | `client.timings(date=...)` | So the feed watchdog stays quiet outside the session. |

**Platform hazard to know:** every order from a script follows the platform-wide
Analyze switch at the moment it is sent. If someone flips it while a live script
holds positions, exits go to the sandbox and report success. The script should
read `analyzerstatus()` at entry and treat a change as a fatal fault.

## 5. Configurable settings (R1)

**Today:** upload stores only name, file, exchange and schedule. The script gets
five variables plus a copy of `.env`, which every strategy shares.
`strategies/README.md` claims "parameters available as environment variables";
that is not implemented and should be corrected.

**Proposed:**

1. The script declares its settings as a literal at the top:

   ```python
   PARAMS = {
       "lots":     {"type": "int",    "default": 1,  "min": 1, "label": "Lots per leg"},
       "expiry":   {"type": "str",    "default": "",           "label": "Expiry (DDMMMYY)"},
       "exit_pct": {"type": "float",  "default": 70, "min": 50, "max": 80, "label": "Exit at % of combined premium"},
       "product":  {"type": "choice", "default": "MIS", "options": ["MIS", "NRML"]},
   }
   ```

2. The host reads it with `ast.literal_eval` on upload and save, **without
   running the script**. No `PARAMS` means today's behaviour.
3. Values are stored under `"params"` in the strategy's record in
   `strategy_configs.json`. It is a JSON file, so no migration script.
4. The New, Edit and a Settings view render a form from the declaration.
5. At start the host passes `OPENALGO_STRATEGY_PARAMS` (JSON) and the template
   merges it over the defaults. Changes apply on the next start.

The AI strategy writer (`services/agent/tools/strategy_gen.py`) should learn the
same convention.

## 6. Fault detection and the alarm (R5)

### 6.1 What can fail, and who can notice

| Fault | Who can notice | How | Can the server alarm? |
| --- | --- | --- | --- |
| Broker feed dead or silent | Proxy and the script | No ticks during market hours while subscribed; adapter reports disconnected | Yes |
| Script's link to the proxy down (proxy crashed) | The script | `client.authenticated` stays False | Yes (Flask is still up) |
| Script hits an error, stops itself | Host | Process exits with an agreed code | Yes |
| Script crashes (uncaught exception, killed for memory) | Host | Process exits with any other code | Yes |
| Script hangs | Host, only with a heartbeat | Heartbeat older than N seconds | Yes, once built |
| Server (Flask) down | **The browser** | SocketIO link to the server drops and stays down | **No**: the browser must alarm by itself |
| Laptop power cut | Nobody | Everything is off | No; obvious on return. The guard in section 3 stops a blind re-entry |

### 6.2 Broker feed loss

**Findings:**

- Each broker adapter retries on its own and then **gives up silently**:
  Zerodha after 50 tries, Angel after 10. After that the proxy holds a dead
  adapter and keeps clients connected; ticks just stop.
- The proxy already records per user whether the adapter says it is connected
  and when the last tick was delivered (`last_tick_time`,
  `get_adapter_health()`, `_log_stale_adapters()` in `websocket_proxy/server.py`).
  It deliberately only logs at debug level: a feed is legitimately silent every
  night, weekend and holiday, and the check has no market calendar.
- "Adapter says connected" is not enough. Issues #1226, #1419 and #1421 were a
  connected adapter delivering nothing, so **tick silence is the real signal**.
- The SDK reconnects its own link to the proxy forever, with backoff
  1, 2, 5, 10, 30, 60 s, and gives the script **no callback** for it. A script
  can only poll `client.connected` and `client.authenticated`.
- The SDK silently drops any message type it does not know. A new proxy message
  is safe to add, but scripts on the pinned SDK cannot receive it.

**Design, two layers:**

**Layer 1, in the script (works today, no platform change).** Use NIFTY spot as
a heartbeat. During market hours the index ticks about every second, unlike an
illiquid option that can go quiet for a while. In the main loop, once a second:

```python
in_session = session_open <= now <= session_close        # from client.timings()
if in_session and not client.authenticated and down_for > 30:
    fatal("Lost connection to the platform's market feed for 30s")
if in_session and secs_since_index_tick > 20:
    fatal("No NIFTY ticks for 20s during market hours: broker feed is down")
```

Short blips (one SDK reconnect, 1-5 s) do not trip it. 20-30 s is a starting
point to tune against real broker behaviour.

**Layer 2, in the platform (alarm even without a strategy running).** Give the
proxy's existing check a market calendar (`database/market_calendar_db`, which
the proxy can reach since it already reads the database for authentication).
During the session, if a user with active subscriptions has had no tick for N
seconds, or the adapter has given up, the proxy sends
`{"type": "feed_status", "status": "down", "broker": ..., "silent_for": ...}` to
that user's WebSocket clients, and `"status": "up"` when ticks return. The React
app holds a small app-wide connection to the proxy and raises the alarm.

Why the browser hears it straight from the proxy: messages flow from Flask to
the proxy today (order updates), not back, and the proxy runs in a separate
process under production. Sending to WebSocket clients needs no new channel.

### 6.3 Script errors and crashes

**Findings (today's host):**

- The reaper (`cleanup_dead_processes`, every 60 s) marks a dead strategy as not
  running. It records no error, keeps no exit code, and **broadcasts nothing**.
  The `/python` page refreshes only on events, so it keeps showing the strategy
  as running until someone reloads it.
- After a **hard** server crash or power cut, `restore_strategy_states`
  **restarts** every strategy that was running, as soon as the broker is logged
  in and contracts are loaded.
- After a **clean** server stop, every strategy is stopped and **not**
  restarted, with no alert.
- `scheduled_start_strategy` checks `manually_stopped` but **not** `is_error`, so
  a crashed strategy is started again by the next day's schedule.
- On the Windows desktop build, the keeper ends every strategy process whenever
  it restarts the server.
- An error state and a clear-error route already exist
  (`/python/clear-error/<id>`), used today only for "waiting for master
  contract". They are the right hooks for "acknowledge".

**Design:**

1. **Exit-code contract**, so the host knows why a script ended:

   | Exit code | Meaning | Host action |
   | --- | --- | --- |
   | 0 | Finished normally (for example, exited its positions) | Mark stopped. No alarm. |
   | 3 | Strategy stopped itself on a fault it detected | Mark **error**, alarm with the script's reason |
   | anything else | Crash (uncaught exception, killed for memory, killed by the OS) | Mark **error**, alarm "crashed", include the last lines of its log |

   The script prints its reason as one line before exiting, for example
   `FATAL: Exit order for NIFTY09NOV2624550CE rejected: insufficient margin. Open: CE short 65, PE short 65`,
   and the host puts that line in the alarm. No new API is needed.

2. **The reaper records and reports.** Keep `returncode`, set `is_error` with the
   reason, broadcast on the `/python` events stream, emit an app-wide SocketIO
   event (`strategy_alert`), and send a Telegram message. A strategy the host
   re-adopted after a server restart has no exit code; treat its death as a
   crash.

3. **Nothing restarts an errored strategy.** `restore_strategy_states` must not
   restart strategies under this model. It should mark them errored with the
   reason "the server stopped while this strategy was running", and alarm.
   `scheduled_start_strategy` must skip `is_error`. Starting again requires
   acknowledging the error in the UI.

4. **Make the clean-stop case loud too.** A clean server stop while strategies
   run should mark them the same way, so the user sees "stopped because the
   server stopped" rather than a quiet "stopped".

### 6.4 Server down

When Flask itself is down, nothing on the server can alarm. The browser has to:
if its SocketIO link drops and stays down for more than about 15 seconds, play
the alarm with "FastAlgo is not reachable". No global handler exists today;
only the strategy module and the order blotter listen for disconnect. On the
desktop build the keeper's panel already reports a crashed server.

### 6.5 The alarm itself

- **Where:** app-wide, not only on `/python`. `frontend/src/hooks/useSocket.ts`
  already plays `/sounds/alert.mp3` for system events, with per-category
  sound settings (`useAlertStore`); add a "strategy" category there.
- **How it differs from today's sounds:** today's are one-shot and throttled.
  An alarm must **loop until acknowledged**, with a banner that names the
  strategy, the reason and the open positions, and an Acknowledge button. That
  button clears the error state.
- **Browser limit:** browsers block sound until the user has clicked on the
  page once. `useSocket` already has an enable-audio step; the alarm needs a
  visible "alarm armed / click to enable sound" indicator, or it may be silent.
- **Backup channel:** if the tab is closed, only Telegram reaches the user.
  Send every alarm there too.

## 7. Fatal-stop policy (owner's rule, with recommendations)

The owner's rule: any runtime exception or rejected order stops the strategy
cleanly, no resume, and the user is told. Recommended refinements:

1. **Fatal immediately:** a rejected entry or exit order, a missing symbol,
   a change in Analyze/Live mode, a position mismatch at start, feed down past
   the threshold, any exception in the strategy's own logic.
2. **Retry briefly, then fatal:** a network error or timeout on a call that
   **reads** (quotes, order status, position book): 3 tries over about 5 s.
   One slow position-book call at 11:00 should not end the day.
3. **Never retry blindly on orders.** A timeout on `placeorder` does not prove
   the order did not reach the broker. Check `orderbook()` before deciding.
   If that cannot be confirmed either, it is fatal.
4. **A rejected second entry leg is the worst case:** one naked short is open.
   It is fatal like any other rejection, and the alarm must lead with the open
   leg. Optionally (a setting, off by default) the script buys back the filled
   leg before stopping. Off by default because an automatic action during a
   fault can make it worse.
5. **One wrapper in the template**, so every strategy behaves the same:
   `main()` runs inside a `try` that turns any exception into `FATAL:` plus exit
   code 3, after collecting the open legs from `positionbook()` if the server
   answers.

## 8. Memory (R6)

**Measured on this laptop (Windows, 4 cores)** for an SDK-only script like the
sanity test:

| Point | Resident | Committed | Threads |
| --- | --- | --- | --- |
| Bare Python | 16 MB | 10 MB | 4 |
| After `import openalgo` (it loads pandas and numpy) | 99 MB | 203 MB | 10 |
| Client, WebSocket thread, a REST call | 107 MB | 209 MB | 12 |
| Same, with numpy's math threads limited to 1 | 107 MB | 112 MB | 9 |

**What this means for 150 MB:**

- **The limit today is something else.** `STRATEGY_MEMORY_LIMIT_MB=1024` is a
  cap on **virtual** memory, applied on **Linux only**. Windows has no limit.
  So 150 would be lower than today, not higher.
- **150 MB of virtual memory would break every script on Linux.** Virtual size
  is always far above resident: about twice here, and more on a many-core
  server. The SDK import alone would fail.
- **150 MB of resident memory fits this strategy** with about 40 MB to spare.
  It is too tight for any strategy that pulls history into pandas.

**Recommendation:**

1. Have the host measure **resident** memory with `psutil` in the reaper loop,
   every 60 s. This works on Windows too, unlike the current limit.
2. Default limit 300 MB per strategy, editable per strategy. Warn in the log and
   UI at 80%. At the limit, stop the strategy as a crash (alarm, section 6.3),
   which is far better than the OS killing it silently.
3. Keep the virtual-memory cap only as a high backstop on Linux (1-2 GB), or
   drop it.
4. Set `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1` in
   every strategy's environment. Measured here, that halves committed memory and
   removes 3 threads. A trading script gains nothing from parallel matrix maths.

Laptop budget: five such strategies come to about 550 MB plus the server's
0.5-1 GB, comfortable on 8 GB.

## 9. Start now, while keeping schedules (R7)

**Today:** every upload gets a schedule (09:00-16:00 Mon-Fri). Start runs
immediately only inside that window; outside it, it only "arms". Stop sets
`manually_stopped`, which suppresses scheduled starts until the next manual
Start. The scheduled stop always runs.

**Proposed:** a per-strategy schedule on/off switch; a Start that runs now
regardless of the window (with a warning when the exchange is closed, since
orders will be rejected); the scheduled stop still applies if a schedule is on.
Under section 6.3, Start on an errored strategy first asks the user to
acknowledge the error.

## 10. Resume (OLD mode), deferred

Kept for later; the start-up guard of section 3 is its first piece.

- **State file:** `strategies/state/<STRATEGY_ID>.json`, written atomically
  (temporary file, then `os.replace`) after each fill: date, mode at entry, legs,
  quantities, fill prices, combined premium, exit level, status.
- **Decided at start against the broker's position book:** today's state with
  matching positions resumes; matching state with flat positions records the
  exit and does not re-enter; any mismatch stops and alarms.
- **Alternatives considered:** broker position book only (netted per contract,
  ambiguous when two strategies share one); the platform's per-strategy book in
  `database/strategy_book_db.py` (exact per strategy, but no REST read endpoint
  for scripts today).

## 11. Alternative: the `/strategy` module

`/strategy` already offers ATM/expiry legs, lots, a scheduler, live or sandbox
per run (unaffected by the Analyze switch) and durable recovery. The exit rule
R4 does not fit: its stops are per leg relative to **that leg's** entry, or a
combined stop in **rupees**. "Either leg at X% of the combined premium" would be
a new rule in `services/risk/` with a case in `test/risk/vectors.json`. Python
strategies remain the right home for custom logic of this kind.

## 12. Proposed changes, in order

| # | Change | Where | Size |
| --- | --- | --- | --- |
| 1 | Strategy template: fatal wrapper and exit code 3, `FATAL:` line, start-up guard, feed watchdog on NIFTY spot, order stream before entry, read retries, mode check | `strategies/examples/` | Small, no platform change |
| 2 | Reaper records exit code and reason, sets error, broadcasts, emits `strategy_alert`, sends Telegram | `python_strategy.py` | Small |
| 3 | No automatic restart of errored or interrupted strategies (restore path and schedule) | `python_strategy.py` | Small |
| 4 | App-wide alarm: looping sound, banner with reason and open positions, Acknowledge that clears the error; server-unreachable alarm | `useSocket.ts`, a new banner component | Medium |
| 5 | Resident-memory limit via `psutil`, per-strategy override, single-thread maths variables | `python_strategy.py` | Small |
| 6 | Proxy `feed_status` with market calendar, browser listener | `websocket_proxy/server.py`, frontend | Medium |
| 7 | `PARAMS` settings form and `OPENALGO_STRATEGY_PARAMS` | host, 3 pages, README | Medium |
| 8 | Schedule switch and Start now | `start_strategy`, `new_strategy`, pages | Small to medium |
| 9 | Heartbeat hang detection | host and template | Medium, later |

1 to 3 first: they make faults visible and stop silent restarts, and item 1
already protects users with no platform change. Item 4 is what the user hears.
Each host change needs tests and an `fd-audit` pass.

## 13. Open questions for the owner

1. **R4 exit:** square off both legs when one hits the level, or only that leg?
2. **Exit level basis:** X% of the combined **fill** premium (recommended), or
   of LTP at order time?
3. **Second entry leg rejected:** alarm only (recommended default), or also buy
   back the filled leg automatically?
4. **Feed watchdog thresholds:** 20 s without NIFTY ticks, 30 s without the
   platform link. Acceptable starting values?
5. **Acknowledge:** should acknowledging an alarm also require confirming that
   the positions were handled, or is one button enough?
6. **Memory default:** 300 MB resident with per-strategy override, or 150 MB as
   you suggested?
7. **Platforms:** Windows desktop only, or Linux servers too? The memory limit
   and the Stop behaviour differ.
