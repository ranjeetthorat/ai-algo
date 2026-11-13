# Version 1.5.1 Released

**Date: 13th November 2026**

**Fixes for the desktop update check and the license gate: updates are read from a host that resolves, errors read clearly, and a refused start shows in red.**

1 commit since 1.5.0. A fix-only release for the Windows desktop launcher. No
database migration, no new setting, and no change to the API, the SDK or
webhooks.

**Highlights**

- **The update check now works (`58967e27d`).** The control panel read the update
  announcement from `fastalgo.tinycompute.site`, which had no DNS record, so
  **Check for updates** always failed and wrongly blamed the internet. It now
  reads `latest.json` from the same Vercel blob store as the release zip, which
  resolves. This is the first build that looks in the right place, so it is the
  first that should be distributed.
- **Honest update messages (`58967e27d`).** A reachable update service that returns
  an error or has no release information now says so, instead of telling the user
  to check a connection that is fine. Only a real connection failure mentions the
  connection.
- **The license check is more robust (`58967e27d`).** It tolerates a byte-order
  mark or stray whitespace before the JSON, reads the whole reply, and reports a
  server error page (such as a PHP fatal) as an error page rather than a vague
  "unreadable answer".
- **Refused starts show in red (`58967e27d`).** A crash, or a start refused by the
  license (not licensed, or turned off), is shown in red in the control panel.

**Upgrading**

- **Windows desktop:** this is the first build to distribute with a working update
  check. Earlier internal builds (1.5.0 and before) cannot find updates on their
  own, so install 1.5.1 from the zip.
- **Servers:** not affected.

**Dependencies**

No dependencies changed.

**Contributors**

- **@ranjeetthorat** - found the update check and license-gate problems while
  testing the first desktop builds (`58967e27d`).

**Links**

- Repository: https://github.com/ranjeetthorat/ai-algo
- Product site: https://fastalgo.tinycompute.site
- Support: https://www.tinycompute.site
- Telegram: https://t.me/RanjT55
