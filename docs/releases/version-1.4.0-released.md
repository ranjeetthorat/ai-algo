# Version 1.4.0 Released

**Date: 13th November 2026**

**Python strategies: you choose whether a start is new or continues where it left off, a ready-made short straddle strategy, and strike selection that matches the Node app.**

4 commits since 1.3.0. This release changes how a strategy built on the
strategy kit resumes after a stop. It also adds a reusable strike selection
module and a complete example strategy that sells, watches and repeats:

- **Start mode:** a setting on the strategy card. "new" starts fresh; "old"
  continues the saved state. The strategy no longer compares the saved state
  with the broker's positions.
- **Short Straddle Window:** sells a call and a put, buys both back when either
  premium rises by a set percent, and repeats.
- **Strike selection:** the Node app's rounding, for any underlying, shared by
  every strategy.

No database migration, no new required setting and no change to the API, the
SDK or webhooks.

**Highlights**

- **Start mode: new or old (`a55cb8182`)** - the kit used to compare a
  strategy's saved orders with the broker's position book on every start, and
  stopped on any difference. After positions were closed by hand, that left
  the strategy unable to start until its saved state was cleared. Now the user
  chooses with a Start mode setting:
  - **new:** a fresh start. The saved state is renamed aside, never deleted. The
    log says `Starting in NEW mode: fresh start`.
  - **old:** continues the saved state exactly as it is, including open legs,
    even on another day. The log says `Starting in OLD mode: continuing the saved
    state last used on <date>` and lists what is open. With nothing saved, it
    starts fresh and says so.
  - **What old leaves to you:** the broker is not asked, so you are responsible
    for the saved state matching your positions. A leg closed by hand and then
    started with old is still treated as open. Close by hand, then start with new.
  - **Warnings:** in old mode, an order still in flight when the last run ended,
    or a switch between Analyze and Live since the saved orders, is logged as a
    warning. A switch during a run still stops it.
  - **Already-written strategies:** they run unchanged and start as new. Add the
    `start_mode` setting to offer the choice.
- **Short Straddle Window (`9e56cb124`)** - `strategies/examples/short_straddle_window.py`,
  ready to upload at `/python`:
  - **Entry:** after the first-entry time, sells the ATM call and put, or with
    "ATM offset" N, one strike N steps up and the other N steps down.
  - **Window:** when either leg's premium rises by the window percent above its
    sell price, buys back both legs. A fall does not trigger it.
  - **Repeat:** sells a fresh pair at the new strike, up to "Cycles per day".
    Raising the limit takes effect the same day.
  - **Square-off:** at the square-off time it buys back what is open and stops.
  - **Settings:** start mode, underlying (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY,
    SENSEX, BANKEX), expiry (empty means the nearest), ATM offset, lots,
    product, window percent, cycles per day, first entry and square-off time.
  - **Orders:** market orders. Each one waits for its fill, and a rejection
    stops the run with the reason on the strategy card.
- **Strike selection matching the Node app (`ee74fea1e`)** - `strategies/lib/option_strikes.py`,
  importable by every strategy:
  - **Rounding:** paise are dropped, then half a step or more rounds up, so
    24,525 gives 24,550. This is checked against the original JavaScript
    across 120,000 prices.
  - **Offset:** moves a call up and a put down by whole strikes.
  - **Underlyings:** strike steps for the indices, and any other step can be
    passed in.
- **Strategy reference (`90ba36238`)** - `docs/strategycontext/` now covers start
  mode and strike selection.

**Upgrading**

- **Windows desktop clients on 1.3.0:** the control panel offers 1.4.0; click
  **Update now**.
- **Servers:** `git pull` on `main`, then restart. No migration is needed.
- **Strategies already uploaded:** upload a strategy again after changing it,
  since the host runs its own copy. The kit itself is shared, so the new resume
  behaviour applies to every kit strategy at its next start.

**Dependencies**

No dependencies changed.

**Contributors**

- **@ranjeetthorat** - the straddle strategy's rules (rise-only window, both
  legs bought back, daily cycle limit, square-off time), the Node app rounding
  to match, and the choice to replace the broker check with a user-chosen start
  mode, found while testing the strategy (`ee74fea1e`, `a55cb8182`, `9e56cb124`,
  `90ba36238`).

**Links**

- Repository: https://github.com/ranjeetthorat/ai-algo
- Product site: https://fastalgo.tinycompute.site
- Support: https://www.tinycompute.site
- Telegram: https://t.me/RanjT55
