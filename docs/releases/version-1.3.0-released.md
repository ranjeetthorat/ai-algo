# Version 1.3.0 Released

**Date: 6th November 2026**

**Python strategies that stop safely and resume correctly, and desktop installs that update themselves with one click.**

9 commits since 1.2.0, plus two pull request merges and one automatic frontend
build. This release reworks the Python strategy host (`/python`) and adds an
in-place updater to the Windows desktop distribution:

- **Strategy kit:** a helper every strategy can import for settings, saved
  state, resuming after a restart, safe orders and a clean stop with a reason.
- **Strategy host:** the card says why a strategy stopped, and a strategy that
  stopped on an error waits for the user instead of restarting on its schedule.
  After a crash, a strategy restarts only inside its own schedule.
- **Settings form:** each strategy's settings are edited from its card.
- **Navigation:** Python strategies have their own place in the top navbar.
- **Desktop updates:** the control panel offers new versions and updates in place,
  keeping the client's data.
- **Server installs:** the Linux installers now fetch FastAlgo instead of the
  upstream project.

No database migration, no new required setting and no change to the API, the
SDK or webhooks.

**Highlights**

- **Strategy kit (`ccdee0b80`)** - `strategies/lib/strategy_kit.py`, on every
  strategy's import path. A strategy declares its settings in a `PARAMS` block and
  gets:
  - **Settings:** values checked against their type and range before the strategy
    runs.
  - **Saved state:** written safely to `strategies/state/<id>.json`, so a crash
    mid-write never leaves a broken file.
  - **Resume:** at start, today's saved orders are compared with the broker's
    positions. A match continues; a mismatch, or an order with an unknown
    outcome, stops with the reason. A day with no open position starts fresh.
  - **Safe orders:** each order waits for its fill and stops the strategy on a
    rejection or an unknown outcome. Orders are never retried blindly.
  - **Feed watch:** stops the strategy when live prices go silent during market
    hours.
  - **Clean stop:** the strategy ends with a reason the card can show.

  The sanity test example is rewritten on the kit.
- **Stop reasons and safe restarts (`6ffeebe5b`)** - the host reads how a strategy
  ended and shows it on the card as "Stopped: <reason>".
  - **Errors:** a strategy that stopped on an error waits for Start instead of
    starting on its next scheduled day.
  - **After a crash or power cut:** a strategy that was running is restarted only
    if today is a scheduled trading day and the time is inside its own window. The
    card then says "Restarted after the server stopped".
  - **Pending restarts:** the server no longer forgets them when it comes back
    before the broker login.
- **Strategy settings form (`6ffeebe5b`)** - a settings icon on each card opens a
  form built from the script's `PARAMS`.
  - **Safe to read:** the form reads `PARAMS` without running the script.
  - **Same rules:** values are checked with the same rules the strategy applies.
  - **Saved state:** the form shows the strategy's saved state and can clear it,
    after confirming. A deleted strategy's state is archived, not lost.
- **`/python` page (`6ffeebe5b`)** - a larger IST clock and shorter summary cards,
  leaving more room for strategies.
- **Python strategies in the navbar (`0c2858585`)** - Python takes the top-level
  slot Trading had. Trading moves to the profile menu, so the charting terminal
  stays one click away.
- **Desktop in-place update (`9d6b35e56`)** - the control panel checks for a new
  version when it opens and every 6 hours, then offers **Update now**. **Check for
  updates** and **Update from file** (for a zip sent by hand) are also there.
  - **What is kept:** settings, login, databases, logs, strategies and installed
    packages. Only packages whose version changed are downloaded.
  - **Checks:** the download is verified against its published checksum, and the
    old program files are kept aside.
  - **Databases:** they are copied before the migrations run.
  - **On failure:** any failure puts the previous version, databases and
    dependencies back.
  - **Publishing:** `scripts/build_release.py` now writes `latest.json` and fills
    in the public site's download link.
- **Server installs from FastAlgo (`c54ea07d7`)** - `install.sh` and
  `install-multi.sh` cloned the upstream OpenAlgo repository, so a server installed
  with them ran OpenAlgo and `update.sh` pulled its changes. Both now clone
  FastAlgo. Upstream links shown to users point to TinyCompute support.
- **Public site download (`a953e3889`)** - the static site offers the Windows
  download in place of a log-in link.
- **Strategy reference (`70d130492`)** - `docs/strategycontext/`, a guide to
  writing and hosting Python strategies for people and AI agents.
- **Publishing and updating guide (`36e653088`)** - the Windows install guide now
  covers publishing a release and updating a client.

**Upgrading**

- **Servers installed with these scripts before this release:** they track the
  upstream repository. Point them at FastAlgo once, in the install folder, with
  `git remote set-url origin https://github.com/ranjeetthorat/ai-algo.git`, then
  run `install/update.sh`. A server that has only ever run upstream OpenAlgo has
  a different history; treat the move as a reinstall that keeps `.env` and `db/`.
- **Windows desktop clients:** install 1.3.0 from the zip. 1.2.0 was never
  distributed. From 1.3.0 on, clients update from the control panel.
- **Strategies:** existing scripts run unchanged. To use the kit, follow
  `docs/strategycontext/writing-strategies.md`.

**Dependencies**

No dependencies changed.

**Contributors**

- **@ranjeetthorat** - direction and decisions for the strategy host: the settings
  form, resuming from saved orders matched against broker positions, stopping on
  any error instead of retrying, and restarting only inside the schedule. Also the
  `/python` and navbar layout, the one-click desktop update, and the report that
  led to the installer fix (`ccdee0b80`, `6ffeebe5b`, `0c2858585`, `70d130492`,
  `a953e3889`, `9d6b35e56`, `36e653088`, `c54ea07d7`).

**Links**

- Repository: https://github.com/ranjeetthorat/ai-algo
- Product site: https://fastalgo.tinycompute.site
- Support: https://www.tinycompute.site
- Telegram: https://t.me/RanjT55
