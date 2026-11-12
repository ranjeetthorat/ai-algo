"""Desktop license gate: register this PC, and check it may run the server.

**Windows desktop installs only.** Server installs are operated by TinyCompute,
so they are not gated (``keeper`` only calls this on Windows).

**What this is, honestly.** A deterrent against casual redistribution, not a
strong control. The source ships with every install, so anyone who can read it
can remove this check. It raises the effort of passing the app around; it does
not prevent it. Do not describe it, in code or to anyone, as something it is not.

**What it never does.** It does not delete, encrypt or alter the user's files,
settings, ``.env``, databases or source. A revoked license only refuses to
*start* the server, and nothing more: restoring the license on the server lets
it start again on the next try. There is no destructive path here, by design.

The check calls a small HTTP API (``check.php``/``add.php``) that answers with an
action:

- ``ok``       the device is registered and allowed. Start normally.
- ``not_ok``   the device is not registered, or the request failed. Refuse to start.
- ``erase``    the device is registered but blocked. Refuse to start (reversible).

Unreachable server counts as *refuse* (the operator chose block-on-offline).
With no API key configured, the gate is **off** and the server starts, so an
unconfigured build is never bricked.

Standard library only; see ``launcher/__init__.py``.
"""

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

if __package__ in (None, ""):  # run as a file rather than with -m
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from launcher.branding import display_name

#: Where the license API lives. Override for testing with FASTALGO_LICENSE_URL.
BASE_URL = "https://cbroz.co.in/algo-api"

#: The API key the build ships with. Set it before cutting a release, or set
#: FASTALGO_LICENSE_API_KEY in the environment. Empty here means the gate is
#: OFF: the server starts and nothing is registered, so an unconfigured build
#: keeps working. A real key turns the gate on.
API_KEY = "TEST"


def api_key() -> str:
    return (os.environ.get("FASTALGO_LICENSE_API_KEY") or API_KEY or "").strip()


def base_url() -> str:
    return (os.environ.get("FASTALGO_LICENSE_URL") or BASE_URL).rstrip("/")


def enabled() -> bool:
    """True when an API key is configured, so the gate should run."""
    return bool(api_key())


@dataclass(frozen=True)
class Result:
    """The outcome of a check or a registration."""

    action: str  # "ok" | "not_ok" | "erase" | "unreachable" | "disabled"
    message: str
    http: int | None = None

    @property
    def allowed(self) -> bool:
        """Whether the server may start: only a clear ok, or the gate being off."""
        return self.action in ("ok", "disabled")


def machine_mac() -> str | None:
    """This PC's MAC as AA:BB:CC:DD:EE:FF, or None if only a random one is available.

    uuid.getnode() sets the multicast bit of the first octet when it had to
    invent an address; such a value is not stable, so the gate treats it as no
    identity rather than registering something that changes next boot.
    """
    node = uuid.getnode()
    if (node >> 40) & 0x01:  # locally-administered / multicast: not a real NIC
        return None
    return ":".join(f"{(node >> shift) & 0xFF:02X}" for shift in range(40, -1, -8))


def _request(endpoint: str, params: dict, timeout: float) -> Result:
    """Call one endpoint. Network or protocol failure becomes action "unreachable"."""
    url = f"{base_url()}/{endpoint}?{urllib.parse.urlencode(params)}"
    if not url.lower().startswith("https://") and "127.0.0.1" not in url and "localhost" not in url:
        return Result("unreachable", "The license address is not secure (https).")
    request = urllib.request.Request(url, headers={"User-Agent": "FastAlgo-license"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - https enforced above
            body = response.read(8192)
            http = response.status
    except urllib.error.HTTPError as e:
        http = e.code
        try:
            body = e.read(8192)
        except OSError:
            body = b""
    except (urllib.error.URLError, OSError, ValueError):
        return Result("unreachable", "Could not reach the license server.")
    try:
        data = json.loads(body.decode("utf-8"))
        action = str(data["action"])
        message = str(data.get("message", ""))
    except (ValueError, KeyError, TypeError):
        return Result("unreachable", "The license server gave an unreadable answer.", http)
    if action not in ("ok", "not_ok", "erase"):
        return Result("unreachable", f"The license server gave an unknown answer ({action}).", http)
    return Result(action, message, http)


def check(timeout: float = 15.0) -> Result:
    """Check whether this PC may run. "disabled" when no key is configured."""
    if not enabled():
        return Result("disabled", "Licensing is not configured.")
    mac = machine_mac()
    if mac is None:
        return Result("unreachable", "This PC has no stable network address to license against.")
    return _request("check.php", {"apikey": api_key(), "mac": mac}, timeout)


def register(remark: str = "", timeout: float = 15.0) -> Result:
    """Add this PC to the allowed list. An existing entry counts as success."""
    if not enabled():
        return Result("disabled", "Licensing is not configured.")
    mac = machine_mac()
    if mac is None:
        return Result("unreachable", "This PC has no stable network address to license against.")
    params = {"apikey": api_key(), "mac": mac}
    if remark:
        params["remark"] = remark[:255]
    result = _request("add.php", params, timeout)
    # add.php answers not_ok + HTTP 409 when the MAC is already registered; that
    # is "already done", not a failure.
    if result.action == "not_ok" and result.http == 409:
        return Result("ok", "This PC is already registered.", 409)
    return result


def gate(app: Path, timeout: float = 15.0) -> tuple[bool, str]:
    """Whether the server may start now, and the message to show if not.

    The message is for a trader: it names what is wrong and what to do, never a
    status code or the MAC. See CLAUDE.md on user-facing messages.
    """
    name = display_name(app)
    result = check(timeout)
    if result.allowed:
        return True, ""
    if result.action == "not_ok":
        return False, f"This copy of {name} is not licensed. Contact support to activate it."
    if result.action == "erase":
        return False, f"This {name} license has been turned off. Contact support to restore it."
    return (
        False,
        f"{name} could not verify its license. Connect this PC to the internet and start again. "
        "If this continues, contact support.",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m launcher.license")
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register", help="add this PC to the allowed list")
    reg.add_argument(
        "--remark", default=f"{socket.gethostname()} / {os.environ.get('USERNAME', '')}"
    )
    sub.add_parser("check", help="check whether this PC may run")
    args = parser.parse_args(argv)

    if not enabled():
        print("Licensing is not configured; nothing to do.")
        return 0
    if args.command == "register":
        result = register(args.remark)
        print(result.message or result.action)
        return 0 if result.allowed else 1
    result = check()
    print(f"{result.action}: {result.message}")
    return 0 if result.allowed else 1


if __name__ == "__main__":
    sys.exit(main())
