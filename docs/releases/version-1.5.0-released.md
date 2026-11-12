# Version 1.5.0 Released

**Date: 13th November 2026**

**A license gate for Windows desktop installs: the PC is registered at install and checked before every start, as a deterrent against casual redistribution.**

2 commits since 1.4.0. This release adds a license control to the Windows
desktop build. It changes nothing for server installs, the API, the SDK or
webhooks, and needs no database migration.

**Highlights**

- **Desktop license gate (`387e0df02`)** - `launcher/license.py`, Windows desktop
  only:
  - **At install:** the installer registers the PC's MAC address with the license
    API (`add.php`). An already-registered PC is fine, and a registration that
    cannot be reached does not stop the install.
  - **At every server start:** the keeper checks the MAC (`check.php`). `ok`
    starts normally; `not_ok` ("this copy is not licensed") and `erase` ("this
    license has been turned off") refuse to start and tell the user to contact
    support; an unreachable license server also refuses to start.
  - **It is a deterrent, not a strong control.** The source ships with the app,
    so a determined user can remove the check. It raises the effort of passing
    the app around; it does not prevent it.
  - **It is never destructive.** A blocked license only refuses to start the
    server. It does not touch the user's files, settings, `.env`, databases or
    source, and restoring the license on the server lets it start again on the
    next try. Revoking and restoring a client is a flag on the server's allowed
    list, with no remote wipe.
  - **Off unless configured.** The gate runs only when a license key is set; it
    ships as a test key for internal builds, which the backend recognises as a
    test key. Server (Ubuntu) installs are not gated.
- **Documentation and the no-bypass rule (`e1a866562`)** - `CLAUDE.md` records
  that the gate is a paid-license control that must stay non-destructive and must
  not be removed, disabled or bypassed on request; the Windows install guide
  covers turning the gate on and revoking or restoring a client.

**Upgrading**

- **Windows desktop clients on 1.4.0:** the control panel offers 1.5.0; click
  **Update now**. The license key ships with the build, so no client action is
  needed.
- **Servers:** not affected.

**Dependencies**

No dependencies changed.

**Contributors**

- **@ranjeetthorat** - the license design: register at install, check at start,
  and the decision that a revoked license refuses to start rather than doing
  anything destructive (`387e0df02`, `e1a866562`).

**Links**

- Repository: https://github.com/ranjeetthorat/ai-algo
- Product site: https://fastalgo.tinycompute.site
- Support: https://www.tinycompute.site
- Telegram: https://t.me/RanjT55
