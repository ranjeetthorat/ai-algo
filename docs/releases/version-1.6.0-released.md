# Version 1.6.0 Released

**Date: 20th November 2026**

**A Linux fleet-operations kit for running client servers, and a broker-connection alarm that raises a visible, audible warning on both desktop and server when the live feed drops.**

3 commits since 1.5.1. Two additions: tooling for operating hosted Linux client
servers (switch a client's broker, back up each instance, roll an update across a
fleet, with an operator runbook), and a connection-loss alarm that is shared by
the desktop build and the Linux servers alike. No database migration and no API,
SDK or webhook change.

**Highlights**

- **Broker-connection alarm (`9da63a3a7`).** Disconnecting the internet used to
  stop the algo silently - the feed dropped with no warning on screen. The server
  now reports the broker feed going down, and the UI raises a banner: a quiet
  "reconnecting" notice at first, escalating to a red banner and a repeating
  alarm sound if the link stays down, until it recovers or the trader dismisses
  the sound. It also catches this device losing its own connection to the server.
  A browser opened during an outage is told the current state on load, so the
  alarm shows there too. Shared code, so it reaches both the desktop build and
  Linux servers.
- **Linux broker-switch reset (`00d6574a9`).** An operator can move a client's
  server to a different broker in one step. It clears the old broker session and
  trading history but keeps the client's login and saved work (strategies, flows,
  settings), backs up the `.env` and databases first, and restores them if
  anything fails.
- **Fleet update, per-instance backup, and operator runbook (`0181d2318`).** A
  single command rolls an update across every server in a hosts list; per-instance
  backups archive each deployment's databases and `.env` on a schedule with
  retention; and a runbook documents provisioning a server, handing it over,
  updating one or many, switching broker, changing domain, and restore.

**Upgrading**

- **Windows desktop:** install 1.6.0 from the zip to get the connection alarm.
- **Servers:** a plain `git pull` brings the alarm and the operator tooling. The
  new scripts live under `install/` (`change-broker.sh`, `backup.sh`,
  `update-all.sh`); none runs unless invoked.

**Dependencies**

No dependencies changed.

**Contributors**

- **@ranjeetthorat** - specified and tested the connection alarm (found it silent
  on a live Wi-Fi disconnect) and the Linux fleet-operations kit, and directed
  the keep-login broker reset (`9da63a3a7`, `0181d2318`, `00d6574a9`).

**Links**

- Repository: https://github.com/ranjeetthorat/ai-algo
- Product site: https://fastalgo.tinycompute.site
- Support: https://www.tinycompute.site
- Telegram: https://t.me/RanjT55
