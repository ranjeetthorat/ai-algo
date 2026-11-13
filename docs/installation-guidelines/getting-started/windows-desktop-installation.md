# Windows Desktop Installation

For the TinyCompute team installing and supporting FastAlgo on a client's
Windows PC. The design and its reasons are in
[2026-11-05-desktop-panel-and-reset-plan.md](../../plans/2026-11-05-desktop-panel-and-reset-plan.md).

## Build a release

On a development machine, with the frontend built and the work committed:

```sh
uv run python scripts/build_release.py
```

This writes `release/FastAlgo-<version>.zip`, a `.sha256` file and
`latest.json` beside it. `release/` is gitignored. It also copies `latest.json`
into `static/` and fills in the download link and note in
`static/site-config.js`, taking the upload folder from the current link (pass
`--url-base https://...` to change it, `--no-announce` to build the zip only).

Bump the version first: installed panels offer only a newer version, and the
zip's name comes from it.

- The zip holds the source exactly as Git tracks it, plus the built
  `frontend/dist`. It never contains `.git`, `.env`, databases or logs.
- `app/RELEASE_FILES` lists every shipped file. The reset uses it to tell the
  client's data apart from the program, so never hand-edit a release.
- The build runs `scripts/brand-check.mjs` when Node.js is present and stops if
  it fails.
- `--allow-dirty` builds from uncommitted work. Use it for test builds only.

## License gate

Windows desktop builds can be gated against casual redistribution
(`launcher/license.py`). It is a deterrent, not a strong control: the source
ships with the app, so a determined user can remove it. It is **never
destructive** — a blocked license only refuses to start the server; nothing of
the client's is deleted or changed, and restoring the license lets it start again.

- **Turn it on** by setting `API_KEY` in `launcher/license.py` (or
  `FASTALGO_LICENSE_API_KEY` in the environment) to the key for the
  `cbroz.co.in/algo-api` endpoints, before building. Left empty, the gate is
  **off** and the server starts for everyone.
- **At install** the installer registers the PC's MAC with `add.php`. An
  already-registered PC is fine.
- **At every server start** the keeper checks the MAC with `check.php`:
  `ok` starts; `not_ok` ("not licensed") and `erase` ("turned off") refuse to
  start and tell the user to contact support. If the API cannot be reached, the
  start is refused (contact support / check the connection).
- **Revoke a client** by setting their entry's `allowed` to `false` in the
  server's `allowed.json`; **restore** by setting it back to `true`. The next
  start the client attempts picks up the change. There is no remote wipe, by
  design.
- **Server (Ubuntu) installs are not gated.** They are operated by TinyCompute.

## Publish a release

In this order, so a panel never sees an announcement before its zip exists:

1. Upload the zip (`release/FastAlgo-<version>.zip`) to the Vercel blob store.
2. Upload `release/latest.json` to the same store, overwriting the existing
   `latest.json`. Installed panels read it from a fixed path
   (`.../latest.json`), check it when they open and every 6 hours, and show the
   update from then on.
3. If you serve a public website, commit `static/latest.json` and
   `static/site-config.js` and upload `static/` too, for the download button.

Both files sit on the blob store at a stable host that resolves; the panel's
`MANIFEST_URL` points there. `latest.json` holds the version, link, size,
SHA-256 and the bold summary line of
`docs/releases/version-<version>-released.md`, which the panel shows beside the
offer. One installation can read a different announcement with
`"update_url": "https://..."` in its `panel.json`.

## Update a client

The client clicks **Update now** in the control panel, or **Check for updates**,
or **Update from file** for a zip sent to them. A running server is stopped
first, after asking, and started again afterwards; running Python strategies
stop and do not restart by themselves. The panel reopens on the new version.

What happens (`launcher/update.py`), and what it keeps:

- The zip is checked: its size and SHA-256 against `latest.json`, that it is a
  release of this product, and that it is newer than what is installed.
- Every program file listed in the installed `RELEASE_FILES` is moved aside to
  `C:\FastAlgo\updates\previous-<old version>-<time>`, then the new files are
  moved in. Everything else stays: `.env`, databases, logs, saved strategies,
  `.venv`, Python and the cache.
- The SQLite databases are copied into that same folder, then `uv sync` installs
  only the packages whose version changed and `upgrade/migrate_all.py` runs.
- Any failure puts the previous program, databases and dependencies back, and
  says so. The last `previous-*` folder is kept for support.

From a prompt, for support:

```sh
python -m launcher.update --home C:\FastAlgo check
python -m launcher.update --home C:\FastAlgo install
python -m launcher.update --home C:\FastAlgo apply FastAlgo-1.3.0.zip
```

## Install on a client PC

1. Download the zip, right-click it, and choose **Extract All**.
2. Double-click **Install FastAlgo.cmd**. Allow 3 to 10 minutes, mostly for the
   download. Windows asks "Yes" once, to allow the server through the firewall on
   Private networks.
3. The control panel opens and shows **Not set up yet**. Click **Set up your
   broker**, choose the broker, and enter its API key and secret. XTS brokers
   also need the market data pair.
4. In the broker's developer portal, set the redirect URL the panel shows.
5. Start FastAlgo from the panel, create the login, and log in to the broker.

If the internet drops during step 2, double-click the installer again. It
continues where it stopped and reuses everything already downloaded.

## What goes where

| Path | What it is |
| --- | --- |
| `C:\FastAlgo\app` | The source code. Inspect it freely. |
| `C:\FastAlgo\app\.venv` | Dependencies. Rebuilt by **Repair dependencies**. |
| `C:\FastAlgo\python` | A private Python 3.12, installed by uv. |
| `C:\FastAlgo\cache` | Download cache. Makes re-runs and repairs fast. Safe to delete. |
| `C:\FastAlgo\run` | Keeper state: `status.json`, `keeper.log`, `server.json`, locks. |
| `C:\FastAlgo\backups` | A zip from every reset (the last 5 are kept). |
| `C:\FastAlgo\updates` | The previous version's program files and databases from the last update, and a download in progress. |
| `C:\FastAlgo\panel.json` | Panel options (auto-restart, keep awake, start at sign-in). |
| `C:\FastAlgo\install.log` | Every installer run, for support. |
| `C:\FastAlgo\install.ok` | Written when the install finishes. Without it the panel offers **Finish installation**. |

## Where to look when something is wrong

1. **The panel.** Its status line gives the cause and the next step. The log
   pane shows the newest server log.
2. **`C:\FastAlgo\run\keeper.log`.** Every start, stop, crash, restart and missed
   health check, one line each, in plain words.
3. **`C:\FastAlgo\app\log\server-<date>.log`.** The server's own output (the last
   10 are kept).
4. **`C:\FastAlgo\app\log\errors.jsonl`.** Every error with its traceback.

The same controls work from a prompt, which helps on a remote session:

```bat
cd C:\FastAlgo\app
..\python\cpython-3.12*\python.exe -m launcher.control --home C:\FastAlgo status
..\python\cpython-3.12*\python.exe -m launcher.control --home C:\FastAlgo stop
..\python\cpython-3.12*\python.exe -m launcher.eject --dry-run
```

## How it stays up

- **The panel owns nothing.** Closing it never stops trading.
- **The keeper runs the server, with no window.**
  - It restarts the server after a crash. It waits 2, 5, 10, 30, then 60 seconds
    between tries, and gives up after 5 crashes in 10 minutes.
  - It restarts the server if `/health/status` misses four checks in a row.
  - It keeps the PC from idle sleep. A closed laptop lid still sleeps, so a client
    who needs guaranteed auto square-off belongs on a server, not a laptop.
- **Stop ends the server and every strategy process it started**, using a
  Windows job object.
- **A keeper that dies leaves the server running.** The panel then shows
  **Running without supervision**, and **Start** takes the server over.

## Switching broker (reset)

**Switch broker** in the panel (or `python -m launcher.eject --broker <name>`)
returns the install to a fresh state for a new broker:

- **Removed, after a backup zip:** the login, settings, orders, logs, keys and
  Flow workflows.
- **Kept:** the program and its dependencies.
- **Kept by default, removable with a checkbox:** scripts and chart indicators,
  and downloaded historical data.

Stop FastAlgo first. The reset refuses while it runs, and rolls everything back
if any file is still in use.

## Other devices on the network

Allowed by default. The panel shows the address to type on a phone, for example
`http://192.168.1.20:5000`. Turn it off with **Allow phones and other computers on
my network**.

- It works on networks Windows marks as Private, not Public ones such as a
  cafe or hotel.
- The broker login must be done on the PC itself, because the broker sends the
  login back to `127.0.0.1`.
