# The `/python` Host

All logic is in `blueprints/python_strategy.py`. The host is a process manager:
it never imports or inspects a strategy beyond its file name.

## State the host keeps

| Where | What |
| --- | --- |
| `RUNNING_STRATEGIES` (memory) | strategy id to process handle, pid, start time, log file |
| `STRATEGY_CONFIGS` (memory) mirrored to `strategies/strategy_configs.json` | name, file path, exchange, owner, schedule, `is_running`, `pid`, `manually_stopped`, `is_error`, `error_message`, `paused_reason` |
| `strategies/scripts/<name>_<YYYYMMDDHHMMSS>.py` | the uploaded file |
| `log/strategies/<id>_<YYYYMMDD>_<HHMMSS>_IST.log` | one file per run |

One reentrant lock (`PROCESS_LOCK`) guards both dictionaries; the JSON file is
rewritten on every change.

## Upload

- `.py` only; the file name is sanitised and the id becomes
  `<name>_<YYYYMMDDHHMMSS>`.
- **Every upload gets a schedule.** Default 09:00-16:00 Mon-Fri (00:00-23:59,
  all days, for CRYPTO). Scheduling cannot be switched off.
- There is no settings field at upload. A strategy declares its settings in a
  `PARAMS` block and they are edited from the settings icon on its card (below).

## Settings and saved state

- **Reading `PARAMS`:** `extract_params_schema(source)` parses the file with
  `ast` and evaluates only the `PARAMS` literal (`ast.literal_eval`); the
  strategy is never run. It is checked with the kit's own
  `check_params_schema`, loaded from `strategies/lib/strategy_kit.py` by
  `strategy_kit()`, so the form and the running strategy apply the same rules.
- **Routes** (session and ownership checked like the others):
  - `GET /python/api/strategy/<id>/params`: fields in declaration order with
    current values, any `PARAMS` error, saved values that no longer fit, and a
    summary of the saved state (date, open positions, pending orders).
  - `POST /python/api/strategy/<id>/params` with `{"values": {...}}`: validated
    with the kit's `validate_params`, stored under `"params"` in the strategy's
    record in `strategy_configs.json`. Names no longer declared are dropped.
    Allowed while running; applies at the next start.
  - `POST /python/api/strategy/<id>/state/clear`: renames
    `strategies/state/<id>.json` to `<id>.cleared-<timestamp>.json`. Refused while running.
- **At start** the saved values go to the strategy as `OPENALGO_STRATEGY_PARAMS`
  (JSON, always set, `{}` when nothing is saved, so a value inherited from the
  server's environment cannot leak in).
- **Deleting a strategy** archives its state as `<id>.deleted-<timestamp>.json`.
- **UI:** the settings icon on the card opens
  `frontend/src/components/python-strategy/PythonStrategySettingsDialog.tsx`,
  which builds the form from the fields and holds the Clear saved state action.

## Start

`start_strategy_process(strategy_id)`:

1. Refuses if already running, still stopping, or the master contract is not
   downloaded.
2. Opens a new log file and writes a header.
3. Builds the child environment: a copy of the server's environment (so every
   `.env` value), plus:
   - `STRATEGY_ID`, `STRATEGY_NAME`
   - `OPENALGO_STRATEGY_EXCHANGE` (from the upload form)
   - `OPENALGO_API_KEY` (decrypted from the database; the key at `/apikey`)
   - `OPENALGO_HOST` (set only if absent, default `http://127.0.0.1:5000`)
   - `PYTHONPATH` with the absolute `strategies/lib` first, so `import strategy_kit` works
     (any existing value is kept after it)
   - `OPENALGO_STRATEGY_STATE_DIR`: absolute `strategies/state`, where the kit saves state
   - `OPENALGO_STRATEGY_PARAMS`: the settings saved from the card, as JSON (`{}` if none)
   - `OPENBLAS_NUM_THREADS`, `OMP_NUM_THREADS`, `MKL_NUM_THREADS` = `1`, only if `.env`
     does not set them (halves committed memory for numpy)
4. Runs `[sys.executable, "-u", <file>]` with the working directory at the
   repository root. stdout and stderr both go to the log file. The interpreter
   is the platform's own, so every installed package is available.
5. Linux only: new session and limits of 1 GB virtual memory
   (`STRATEGY_MEMORY_LIMIT_MB`), 1 hour of CPU time, 256 open files, 256
   processes. Windows: a new process group, no limits.
6. Records the pid, saves the config, broadcasts "running" on the
   `/python/api/events` server-sent event stream.

Python imports from the script's own folder (`strategies/scripts/`) and from
`PYTHONPATH`, not from the working directory. That is why the kit lives in
`strategies/lib` and the host puts that folder on `PYTHONPATH`.

### Start button versus schedule

The `/python/start/<id>` route:

- Inside the schedule window (today is a scheduled day, the time is between
  start and stop, and the exchange is open today): starts immediately. Example:
  13:00 on a weekday with a 09:00-15:30 schedule starts at once and is stopped
  by the scheduled stop at 15:30.
- Outside the window: does not start; replies "armed for scheduled start" and
  the strategy starts at the next scheduled start time.
- Clears `manually_stopped`.

## Stop

`stop_strategy_process(strategy_id)`:

- Linux: SIGTERM, wait 5 s, then kill and wait 2 s. A strategy can catch
  SIGTERM to finish cleanly.
- Windows: terminated immediately; no cleanup code in the strategy runs.
- Marks `is_running = False`, broadcasts the new status, prunes old logs.
- The Stop button also sets `manually_stopped`, which blocks scheduled starts
  until the user presses Start again.

## Scheduler

APScheduler with the IST time zone:

| Job | When | Does |
| --- | --- | --- |
| Per-strategy start | `schedule_start` on `schedule_days` | Starts unless `manually_stopped`, errored (`is_error`), not a scheduled day, or the exchange is closed today |
| Per-strategy stop | `schedule_stop` | Always stops |
| `market_hours_enforcer` | every minute | Stops scheduled strategies whose exchange is closed today; resumes ones paused for that reason when it reopens |
| `daily_trading_day_check` | 00:01 | Stops strategies on weekends and holidays |
| `cleanup_dead_processes` | every 60 s | Records how exited strategies ended (see below) |

## When a strategy ends on its own

The reaper (`cleanup_dead_processes`, every 60 s, and on every strategy list
request) collects the exit code and reads the last 8 KB of the run log:

| Exit | Card | Config |
| --- | --- | --- |
| 0 | back to its schedule status | `last_exit_code`, no error |
| 3 (strategy kit: stopped with a reason) | "Stopped: \<FATAL reason\>" | `is_error`, `error_message` = reason |
| 4 (strategy kit: code error) | "Stopped: Strategy code failed: \<reason\>" | same |
| anything else, or unknown (process re-adopted after a restart) | "Stopped: Strategy stopped unexpectedly (exit code N). Last log line: ..." | same |

The change is broadcast on `/python/api/events` at once, so the card updates
without a reload. Stops made by the host (Stop button, scheduled stop,
enforcer, shutdown) never count as errors: `stop_strategy_process` removes the
strategy from tracking before terminating it, so the reaper never sees them.
If a new run starts while the reaper is reading the old run's log, the new run
is left alone.

**An errored strategy waits for the user.** The scheduled start and the
closed-exchange enforcer skip it. Pressing Start (or Clear on the banner)
acknowledges the stop (`acknowledge_strategy_stop`) and clears the error.

## When the server stops

| Event | Host behaviour |
| --- | --- |
| Server stops cleanly | `atexit` stops every strategy and marks it not running. It is not restarted when the server comes back. |
| Server crashes hard, or power is cut | Strategies stay marked running. If the server comes up without a broker session, the reaper turns that into `restore_pending` so it is not lost. After login (`restore_strategies_after_login`, triggered by `database/master_contract_cache_hook.py`), each such strategy is restarted **only if today is a scheduled trading day and the time is inside its own start-stop window**; the card then says "Restarted after the server stopped (HH:MM IST)". Outside the window it is left for its next scheduled start. A failed restart becomes an error. |
| Master contracts not ready at restore | Interrupted strategies wait as "Waiting for master contracts to be downloaded" and are restarted, under the same window rule, once the download finishes. |
| Windows desktop keeper restarts the server | The keeper ends its whole job object, strategy processes included (`launcher/keeper.py`); they then follow the hard-crash row. |
| Stop pressed on a strategy with a pending restart | Cancels the restart and the notice. |

A restarted strategy is a fresh run from the top of its file. Strategies using
the kit decide with `s.resume()` whether to continue today's position.

## Logs

- One file per run in `log/strategies/`. Everything the strategy prints, plus
  tracebacks.
- Viewed at `/python/<id>/logs`; the page refreshes every 3 s while the strategy
  runs.
- Pruned when a strategy stops: `STRATEGY_LOG_MAX_FILES` (10),
  `STRATEGY_LOG_MAX_SIZE_MB` (50), `STRATEGY_LOG_RETENTION_DAYS` (7).
- Reasons a strategy could not start (contract not ready, file missing) are in
  the platform log (`log/errors.jsonl`), not the strategy log.

## Other modules that reach into the host

- `app.py`: registers the blueprint and calls `initialize_with_app_context()`
  after the databases are ready.
- `database/master_contract_cache_hook.py`: calls
  `restore_strategies_after_login()` after the master contract downloads.
- `services/telegram_bot_service.py`: lists and stops strategies.
- `utils/shutdown.py`: stops the scheduler on exit.
- `services/agent/tools/strategy_gen.py`: the AI agent writes strategy files
  using the same naming rules.
