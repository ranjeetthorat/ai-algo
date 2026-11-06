# Python Strategy Kit and Host Improvements: Implementation Plan

Date: 2026-11-06
Status: approved 2026-11-06 (answers recorded in section 9); M1 to M4 done 2026-11-06
Background: [2026-11-06-python-strategy-config-and-recovery-report.md](2026-11-06-python-strategy-config-and-recovery-report.md)
Knowledge base for implementers: [docs/strategycontext/](../strategycontext/README.md)

## 1. Goal

Give every Python strategy the same plumbing, so a strategy author writes only
trading logic:

- read its settings from a form on the strategy card;
- keep its own saved state, and continue its own position after a restart only
  when the saved state and the broker agree;
- stop cleanly, with a reason the user can read on the card, on any runtime
  exception or order failure.

The platform does not know or care what a strategy trades. It starts and stops
processes, passes settings in, and shows why a run ended.

## 2. Decisions already taken

| Topic | Decision |
| --- | --- |
| Run model | Every Start is a new process that runs the file from the top. Nothing in memory survives a stop. Only the strategy's saved state file and the broker's positions carry over. |
| Scheduling | No change. Start inside the schedule window runs immediately (verified: 13:00 on a weekday with 09:00-15:30 starts at once); the scheduled stop ends it. Outside the window, Start arms it for the next start time. |
| Faults | Any runtime exception or order failure stops the strategy cleanly. No automatic recovery inside a run. |
| OLD mode | No manual OLD/NEW setting. At start the strategy compares its saved state with the broker's positions; both agree means continue, neither exists means fresh, anything else means stop with a reason. |
| Settings UI | A settings icon on each strategy card opens a form generated from the strategy's declared settings. |
| Position alarms | Out of scope. The platform reports why a strategy stopped; it does not track positions. |

## 3. Milestones

| # | Milestone | Main files | Depends on |
| --- | --- | --- | --- |
| M1 | Strategy kit and the sanity test rebuilt on it | `strategies/lib/strategy_kit.py` (new), host env, `strategies/examples/sanity_test.py` | none |
| M2 | Stop reasons on the card | `blueprints/python_strategy.py`, `PythonStrategyIndex.tsx` | M1 (exit codes) |
| M3 | Settings icon, form and saved-state reset | `blueprints/python_strategy.py`, new dialog component, `PythonStrategyIndex.tsx` | M1 (`PARAMS`, state dir) |
| M4 | Cosmetic changes on `/python` | `PythonStrategyIndex.tsx` | none |
| M5 | Documentation | `docs/strategycontext/`, `strategies/README.md`, `docs/INDEX.md` | each milestone updates its part |

Each milestone ends with a report to the owner before the next one starts.

## 4. M1: the strategy kit

### 4.1 How strategies get it

- New tracked file `strategies/lib/strategy_kit.py`. `strategies/scripts/` is
  the user upload folder and is gitignored, so the kit cannot live there.
- When the host starts a strategy it prepends the absolute path of
  `strategies/lib` to `PYTHONPATH` in the child environment, keeping any
  existing value. A strategy then writes `from strategy_kit import Strategy`.
- The host also sets:
  - `OPENALGO_STRATEGY_STATE_DIR` = absolute `strategies/state` (new folder,
    gitignored with its own `.gitignore`, created by `ensure_directories()`).
  - `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS` = `1` with
    `setdefault`, so a user can still override them in `.env`. Measured on the
    owner's laptop, this halves committed memory (209 MB to 112 MB).
- The kit's public names are a contract once released. Changes after release
  only add; they never rename or change meaning, because a platform update
  replaces the kit under every installed strategy.

### 4.2 What a strategy looks like

```python
from strategy_kit import Strategy

PARAMS = {
    "lots":    {"type": "int",    "default": 1,  "min": 1, "label": "Lots per leg"},
    "expiry":  {"type": "str",    "default": "09NOV26",    "label": "Expiry (DDMMMYY)"},
    "product": {"type": "choice", "default": "MIS", "options": ["MIS", "NRML"]},
}

def main(s):
    lots = s.params["lots"]
    ...
    fill = s.order("NIFTY09NOV2624550CE", "NFO", "SELL", 65)   # stops the run on rejection
    s.state["legs"] = [...]; s.save_state()
    while s.sleep(1):          # False once the host asks the strategy to stop
        price = s.ltp("NFO", "NIFTY09NOV2624550CE")
        ...

Strategy(PARAMS).run(main)
```

### 4.3 Kit surface

| Name | Behaviour |
| --- | --- |
| `Strategy(PARAMS)` | Reads the host environment, builds the SDK client, merges `OPENALGO_STRATEGY_PARAMS` over the declared defaults, validates types and limits, loads saved state. A missing API key or an invalid setting stops with a readable reason. |
| `s.params` | The merged settings (read-only mapping). |
| `s.client` | The underlying `openalgo` client for anything the kit does not wrap. |
| `s.log(msg)` | Timestamped, flushed line in the run log. |
| `s.run(main)` | Calls `main(s)`. Turns every outcome into an exit code and, for faults, one `FATAL: <reason>` line (section 4.4). Always disconnects the WebSocket. |
| `s.stop(reason)` | Raises the kit's stop exception: a deliberate, clean stop with a reason. |
| `s.read(fn, ...)` | Calls a read-only SDK method with up to 3 tries over about 5 s on a network error or timeout; an error answer from the server is not retried. Stops the run if all tries fail. |
| `s.order(symbol, exchange, action, quantity, price_type="MARKET", price=None, trigger_price=None, product=None)` | Records a pending order in state, places it, waits for a final status from the order stream (falling back to `orderstatus`), records the fill in state. Stops the run on rejection, cancellation, a timeout waiting for the outcome, or an unclear placement result (a timeout on `placeorder` is never retried, because the order may have reached the broker). Returns order id, filled quantity and average price. |
| `s.subscribe(instruments)` | Connects on first use, subscribes LTP, keeps the latest price and arrival time per symbol. The callback only stores; nothing heavy runs on the SDK thread. |
| `s.ltp(exchange, symbol)` / `s.ltp_age(exchange, symbol)` | Latest price, and seconds since it arrived. |
| `s.watch_feed(heartbeat=("NSE_INDEX", "NIFTY"), max_silence=20, max_link_down=30)` | Optional. During the exchange session (from `client.timings()`), stop the run when the platform link has been down, or the heartbeat symbol silent, longer than the limits. |
| `s.sleep(seconds)` | Sleeps in short slices, runs the feed watch, returns False once a stop was requested (SIGTERM on Linux). |
| `s.state` / `s.save_state()` | The strategy's own JSON dictionary in `<state dir>/<STRATEGY_ID>.json`, written atomically (temporary file, then `os.replace`). The kit keeps its own keys under `"_kit"`: trading date, pending orders, filled orders. |
| `s.resume()` | Returns `"fresh"` or `"continue"`, or stops the run (section 4.5). |

### 4.4 Exit-code contract (shared with M2)

| Code | Meaning | Printed |
| --- | --- | --- |
| 0 | `main` returned, or the host asked the strategy to stop | nothing extra |
| 3 | Deliberate clean stop: `s.stop()`, an order failure, a failed read, a feed watch trip, an invalid setting | `FATAL: <reason>` |
| 4 | Uncaught exception in strategy code | `FATAL: <exception type>: <message>` and the traceback |
| other | Killed from outside (memory, operating system, crash of the interpreter) | nothing; the host infers it |

The reason is written for a trader: what happened and which symbol, never only
an exception class.

### 4.5 Resume rule

The kit records every filled order in state, exits included, and a pending
record before each order is sent. At start, `s.resume()` compares the net
position implied by state with the broker's position book for the same
symbols, exchanges and products:

| State for today | Broker | Result |
| --- | --- | --- |
| none, or from an earlier trading day | flat in every symbol the state names (none to check if no state) | `"fresh"`; old state is archived as `<id>.<date>.json` |
| present, no pending order | net quantities equal for every symbol | `"continue"`; the strategy reads its saved prices from `s.state` |
| a pending order exists | any | stop: "an order was in flight when the last run ended; check the order book, then clear saved state" |
| present | any quantity differs | stop, naming the symbol and both quantities |

Known limit: the broker nets positions per contract. A manual trade or another
strategy in the same contract changes the quantity, so the rule stops rather
than continuing. That is the intended, safe outcome.

### 4.6 Sanity test on the kit

`strategies/examples/sanity_test.py` is rewritten to use the kit, with
`PARAMS` for expiry, lots and product, `s.resume()` instead of its own
position check, the order stream subscribed before entry (the 2026-11-05 run
missed both rejections because it subscribed afterwards), and `s.watch_feed()`.

### 4.7 Tests

- `test/test_strategy_kit.py`, with a fake client:
  - settings merge, type and limit validation, invalid setting gives exit 3;
  - rejected, cancelled and unclear orders give exit 3 with the symbol in the reason;
  - a pending record is written before `placeorder` is called;
  - every row of the resume table;
  - atomic save leaves the old file intact when the write fails;
  - feed watch trips only inside the session;
  - uncaught exception gives exit 4 and a `FATAL:` line.
- Host: the child environment contains `strategies/lib` on `PYTHONPATH`, the
  state directory and the thread variables, without overwriting values set in
  `.env`.
- `fd-audit` skill after the host change.

## 5. M2: stop reasons on the card

Today the reaper marks a dead strategy as not running, keeps no exit code,
records no reason and broadcasts nothing, so the card keeps saying "Running"
until the page is reloaded.

1. **Collect the exit.** In `cleanup_dead_processes`, read `returncode` from the
   `Popen`. A strategy re-adopted after a server restart is a `psutil.Process`
   with no exit code; treat it as "other".
2. **Tell host stops apart.** Stops started by the host (Stop button, scheduled
   stop, closed-exchange enforcer, shutdown) already go through
   `stop_strategy_process`; those are never errors, whatever the code.
3. **Read the reason.** For code 3 or 4, read the last `FATAL:` line from the
   tail (last 8 KB) of the run's log file.
4. **Record it.** Code 0: `last_stopped` only. Code 3: `is_error`,
   `error_message` = the reason. Code 4: `is_error`, "Strategy code failed:
   <reason>". Other: `is_error`, "Strategy stopped unexpectedly (exit code N).
   See the latest log." Plus `last_exit_code` and `error_time`.
5. **Broadcast** on the existing `/python/api/events` stream, so the card
   updates within the 60-second reaper interval without a reload.
6. **Show it.** The card already renders `error_message` in a red banner with a
   Clear button when status is `error`. Check that `get_schedule_status` and
   `/python/api/strategies` report `error` for these strategies, and that Start
   clears the error.
7. **Scheduled start of an errored strategy:** see question 1.
8. **Restore after a hard server crash or power cut:** see question 2.
9. Tests in `test/` for each exit code, for host stops never becoming errors,
   and for the broadcast. `fd-audit` after.

## 6. M3: settings icon, form and saved-state reset

### 6.1 Backend (`blueprints/python_strategy.py`)

- `extract_params_schema(source) -> dict | None`: parse the file with `ast`, find
  a top-level `PARAMS = {...}` assignment, evaluate it with `ast.literal_eval`.
  The strategy is never executed. Accepted types: `int`, `float`, `str`,
  `bool`, `choice` (needs `options`). Optional keys: `default`, `min`, `max`,
  `label`, `help`. Anything else is reported as a schema error, shown in the form.
- Read on upload, on save from the editor, and on demand.
- Values stored in the strategy's record in `strategies/strategy_configs.json`
  under `"params"`. A JSON file, so no migration script; a missing key means
  defaults. Values whose names are no longer in the schema are dropped on save.
- `GET /python/api/strategy/<id>/params` returns `{schema, values, error}`.
- `POST /python/api/strategy/<id>/params` validates against the schema and
  saves. Ownership check and session check as on the other routes.
- `POST /python/api/strategy/<id>/state/clear` archives the state file. Refused
  while the strategy runs.
- `start_strategy_process` passes the saved values as `OPENALGO_STRATEGY_PARAMS`
  (JSON).
- Deleting a strategy also archives its state file.

### 6.2 Frontend

- A settings icon button in the card header, beside the status badge, with
  `aria-label="Strategy settings"`. Shown for every strategy; a strategy
  without `PARAMS` opens the dialog with "This strategy declares no settings"
  and a one-line hint on how to add them.
- `PythonStrategySettingsDialog.tsx`: fields generated from the schema (number
  inputs with min and max, text, switch, select), defaults shown, Save, and a
  note "Changes apply the next time the strategy starts". Editing is allowed
  while running, because it only affects the next start.
- In the same dialog, "Clear saved state" with a confirmation ("The next start
  will be a fresh start, not a continuation"). Disabled while running.
- No new page, so no `App.tsx`, `react_app.py` or navigation registration.
- Client calls through the existing API helper, so CSRF handling matches the
  other `/python` calls.

### 6.3 Tests

- Schema extraction: valid, missing, malformed, non-literal, wrong types.
- Validation of saved values, ownership, refused clear while running.
- Environment carries the saved values.
- Frontend build (`npm run build`); tests run in CI.

## 7. M4: cosmetic changes on `/python`

File: `frontend/src/pages/python-strategy/PythonStrategyIndex.tsx`.

1. **Current IST line (around line 346):** from `text-sm text-muted-foreground`
   with a 16 px icon to `text-base font-medium text-foreground` with a 20 px
   icon, and the time in a tabular-number font so it does not jitter every
   second.
2. **Four summary cards (around line 287):** the base `Card` adds `py-6` and
   `gap-6`, and each card adds `pt-4` on its content, so each card is roughly
   100 px tall. Target about 56 px:
   - `Card className="py-3 gap-0"`, `CardContent className="px-4"` without `pt-4`;
   - value text `text-2xl` to `text-xl`, label stays `text-sm`;
   - icons `h-8 w-8` to `h-5 w-5`;
   - grid gap `gap-4` to `gap-3`.
   The Master Contract card keeps its badge and Check button inside the same height.
3. Same changes in the loading skeleton (around line 248), so the page does not
   jump when data arrives.
4. Check light and dark themes and phone width.

## 8. M5: documentation

- `docs/strategycontext/` (created with this plan) is the single reference for
  writing and hosting Python strategies, for people and AI agents. Each
  milestone updates the pages it changes; sections describing planned work are
  marked as planned until they land.
- `strategies/README.md`: remove the claim that upload parameters become
  environment variables (true only after M3, and then as
  `OPENALGO_STRATEGY_PARAMS`), and point to `docs/strategycontext/`.
- `docs/INDEX.md`: add a row for `docs/strategycontext/`.
- The AI strategy writer (`services/agent/tools/strategy_gen.py`): teach it the
  kit and `PARAMS` after M3, in a follow-up.

## 9. Questions for the owner

Answered 2026-11-06:

| # | Decision |
| --- | --- |
| 1 | An errored strategy is **not** started by the schedule; it waits for the user to press Start, which clears the error. |
| 2 | Keep restarting strategies after a hard server crash or power cut (the resume rule makes it safe), and show "Restarted after the server stopped" on the card. |
| 3 | No Telegram for now. |
| 4 | Memory limit left as it is for now. |
| 5 | `docs/strategycontext/` is the location. |

The original questions, for reference:

1. **Errored strategy and the schedule.** After a strategy stops with a reason
   (exit 3, 4 or other), should the next scheduled day start it again
   automatically, or wait until the user presses Start (which also clears the
   error)? Recommendation: wait for the user. The run stopped for a reason
   somebody should read first.
2. **Hard server crash or power cut.** Today the host restarts strategies that
   were running when the server went down. With the kit's resume rule that
   restart is safe: it continues only when state and broker agree. Keep the
   restart, or mark them "Interrupted: the server stopped while this strategy
   was running" and wait for the user? Recommendation: keep the restart now that
   the resume rule exists, and show "Restarted after the server stopped" on
   the card so it is never silent.
3. **Telegram.** Send a Telegram message when a strategy stops with a reason?
   The bot is already part of the platform. Default off, switch in settings?
4. **Memory limit.** Add the resident-memory check (`psutil`, default 300 MB,
   per-strategy override, stop with a reason at the limit) in M2, or leave the
   current behaviour (1024 MB virtual on Linux, none on Windows) for now?
5. **Folder location.** The knowledge folder is `docs/strategycontext/`, because
   project documentation lives under `docs/`. Is that acceptable, or should it
   sit at the repository root?
