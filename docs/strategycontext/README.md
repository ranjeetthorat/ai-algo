# Strategy Context: Python Strategies in FastAlgo

The single reference for writing, hosting and debugging Python strategies on
FastAlgo, for people and AI agents. Read this page first, then open only the
page you need.

| Page | Read it when |
| --- | --- |
| [architecture.md](architecture.md) | You need the big picture: Flask, the WebSocket proxy, the one broker feed, and where a strategy process sits |
| [host.md](host.md) | You touch the `/python` host or need to know how a strategy is started, stopped, scheduled, restored and logged |
| [sdk.md](sdk.md) | You write strategy code: client, orders, positions, options helpers, live prices |
| [writing-strategies.md](writing-strategies.md) | You write or review a strategy: the run model, the template, the rules, the pitfalls |

## Facts to keep in mind

- **A strategy is a separate process.** The host runs `python -u <file>` and
  never imports it. The strategy talks to the platform only through the public
  REST API (`/api/v1/`, port 5000) and the WebSocket proxy (port 8765), exactly
  like an external client.
- **Every Start is a fresh run from the top of the file.** Nothing in memory
  survives a stop. Only files the strategy writes and the broker's positions
  carry over.
- **There is one broker market-data connection per installation.** Every
  strategy, browser page and tool shares it through the proxy. Subscribing
  from a script does not open a broker connection and is not rate limited.
- **Every order follows the platform-wide Analyze switch** at the moment it is
  sent. A script cannot choose live or sandbox.
- **SDK calls never raise.** They return a dict; check `status` every time.

## Status of planned work

Plan: [docs/plans/2026-11-06-python-strategy-kit-implementation-plan.md](../plans/2026-11-06-python-strategy-kit-implementation-plan.md)

| Feature | Status |
| --- | --- |
| Strategy kit (`strategies/lib/strategy_kit.py`): settings, saved state, resume rule, safe orders, clean stop with reason | Done (M1) |
| Stop reason shown on the strategy card; errored strategies wait for Start; restart after a server stop only inside the schedule window, with a notice | Done (M2) |
| Settings icon and form per strategy, `OPENALGO_STRATEGY_PARAMS`, Clear saved state | Done (M3) |
| Larger IST clock, shorter summary cards on `/python` | Done (M4) |

Pages describe today's behaviour unless a section is marked **Planned**.
Update this table and the affected page when a milestone lands.

## Source files

| Area | File |
| --- | --- |
| Host (all logic) | `blueprints/python_strategy.py` |
| Host UI | `frontend/src/pages/python-strategy/` |
| Uploaded scripts | `strategies/scripts/` (gitignored) |
| Strategy records | `strategies/strategy_configs.json` |
| Run logs | `log/strategies/<id>_<YYYYMMDD>_<HHMMSS>_IST.log` |
| Strategy kit | `strategies/lib/strategy_kit.py` (tests: `test/test_strategy_kit.py`) |
| Saved strategy state | `strategies/state/<STRATEGY_ID>.json` (gitignored) |
| Example strategies | `strategies/examples/` (`sanity_test.py` uses the kit; `simple_ema_strategy.py` uses the SDK directly) |
| SDK | the `openalgo` package in the project environment (2.0.5 at the time of writing) |
| WebSocket proxy | `websocket_proxy/server.py`, `websocket_proxy/broker_factory.py` |
| Windows desktop keeper | `launcher/keeper.py` |
| Upload and scheduling steps for users | `strategies/README.md` |
| Resource limits | `strategies/RESOURCE_LIMITS.md` |
| Background research | `docs/plans/2026-11-06-python-strategy-config-and-recovery-report.md` |
