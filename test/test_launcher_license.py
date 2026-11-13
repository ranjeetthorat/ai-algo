"""The desktop license gate (launcher.license), and the keeper's use of it.

The network is never touched: the HTTP call is faked. The gate is a deterrent,
not a strong control, and it must never do anything destructive, so these tests
pin that it only ever allows or refuses a start.

Run:
    uv run pytest test/test_launcher_license.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from launcher import keeper, license

REAL_MAC = 0xAABBCCDDEE01  # top bit of the first octet clear: a real NIC


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    # A key present by default, and no stray environment override of the URL.
    monkeypatch.setattr(license, "API_KEY", "test-key")
    monkeypatch.delenv("FASTALGO_LICENSE_API_KEY", raising=False)
    monkeypatch.delenv("FASTALGO_LICENSE_URL", raising=False)
    monkeypatch.setattr(license.uuid, "getnode", lambda: REAL_MAC)


def fake_http(result_by_endpoint):
    def _request(endpoint, params, timeout):
        return result_by_endpoint[endpoint.split(".")[0]]

    return _request


# --- the MAC -------------------------------------------------------------------------


def test_mac_is_formatted(monkeypatch):
    monkeypatch.setattr(license.uuid, "getnode", lambda: REAL_MAC)
    assert license.machine_mac() == "AA:BB:CC:DD:EE:01"


def test_a_random_mac_is_treated_as_no_identity(monkeypatch):
    # uuid.getnode sets the multicast bit when it had to invent an address.
    monkeypatch.setattr(license.uuid, "getnode", lambda: 0x010000000000 | REAL_MAC)
    assert license.machine_mac() is None


# --- the request parser --------------------------------------------------------------


class FakeResponse:
    def __init__(self, body, status=200):
        self._body = body.encode()
        self.status = status

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize("action", ["ok", "not_ok", "erase"])
def test_request_reads_each_action(monkeypatch, action):
    monkeypatch.setattr(
        license.urllib.request,
        "urlopen",
        lambda *a, **k: FakeResponse(f'{{"action": "{action}", "message": "hi"}}'),
    )
    r = license._request("check.php", {"apikey": "k", "mac": "M"}, 5)
    assert (r.action, r.message) == (action, "hi")


def test_unknown_action_is_unreachable_not_allowed(monkeypatch):
    monkeypatch.setattr(
        license.urllib.request,
        "urlopen",
        lambda *a, **k: FakeResponse('{"action": "delete_everything"}'),
    )
    assert license._request("check.php", {}, 5).action == "unreachable"


def test_network_error_is_unreachable(monkeypatch):
    def boom(*a, **k):
        raise OSError("no route")

    monkeypatch.setattr(license.urllib.request, "urlopen", boom)
    assert license._request("check.php", {}, 5).action == "unreachable"


def test_a_plain_http_url_is_refused(monkeypatch):
    monkeypatch.setattr(license, "BASE_URL", "http://insecure.example")
    assert license.check().action == "unreachable"


# --- check and register --------------------------------------------------------------


def test_check_is_disabled_without_a_key(monkeypatch):
    monkeypatch.setattr(license, "API_KEY", "")
    result = license.check()
    assert result.action == "disabled" and result.allowed is True


def test_check_sends_the_mac_and_key(monkeypatch):
    seen = {}

    def _request(endpoint, params, timeout):
        seen.update(endpoint=endpoint, params=params)
        return license.Result("ok", "")

    monkeypatch.setattr(license, "_request", _request)
    assert license.check().action == "ok"
    assert seen["endpoint"] == "check.php"
    assert seen["params"] == {"apikey": "test-key", "mac": "AA:BB:CC:DD:EE:01"}


def test_register_treats_an_existing_entry_as_success(monkeypatch):
    monkeypatch.setattr(
        license, "_request", lambda *a, **k: license.Result("not_ok", "exists", 409)
    )
    result = license.register("Office PC")
    assert result.action == "ok" and result.allowed is True


def test_register_truncates_a_long_remark(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        license, "_request", lambda e, p, t: seen.update(p) or license.Result("ok", "")
    )
    license.register("x" * 500)
    assert len(seen["remark"]) == 255


# --- the gate ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "allowed", "needle"),
    [
        ("ok", True, ""),
        ("disabled", True, ""),
        ("not_ok", False, "not licensed"),
        ("erase", False, "turned off"),
        ("unreachable", False, "internet"),
    ],
)
def test_gate_maps_each_action_to_a_trader_message(monkeypatch, tmp_path, action, allowed, needle):
    monkeypatch.setattr(license, "check", lambda timeout=15.0: license.Result(action, "x"))
    ok, message = license.gate(tmp_path)
    assert ok is allowed
    assert needle in message.lower()
    # Never leak the MAC or a status code to a trader.
    assert "AA:BB" not in message and "40" not in message


def test_gate_never_returns_a_destructive_instruction(monkeypatch, tmp_path):
    # The gate's whole contract: it decides start / no-start, nothing else.
    for action in ("ok", "not_ok", "erase", "unreachable", "disabled"):
        monkeypatch.setattr(license, "check", lambda timeout=15.0, a=action: license.Result(a, "x"))
        result = license.gate(tmp_path)
        assert isinstance(result, tuple) and isinstance(result[0], bool)


# --- the keeper uses it --------------------------------------------------------------


def test_keeper_refuses_to_start_when_the_license_is_blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(keeper, "IS_WINDOWS", True)
    monkeypatch.setattr(
        keeper.license, "gate", lambda app, timeout=15.0: (False, "License revoked.")
    )
    k = keeper.Keeper(keeper.paths_for(tmp_path))
    assert k.start_server() is False
    status = keeper.read_json(k.paths.status)
    assert status["state"] == "error" and status["message"] == "License revoked."
    # Nothing was launched, and nothing of the user's was touched.
    assert keeper.read_json(k.paths.server_pid) is None


def test_an_html_error_page_is_reported_as_an_error_page(monkeypatch):
    # add.php can return a PHP fatal as HTML with HTTP 200; not our JSON.
    html = "<br />\n<b>Fatal error</b>: Call to undefined function mb_strlen()"
    monkeypatch.setattr(license.urllib.request, "urlopen", lambda *a, **k: FakeResponse(html))
    r = license._request("add.php", {"apikey": "k", "mac": "M"}, 5)
    assert r.action == "unreachable" and "error page" in r.message


def test_a_bom_or_whitespace_prefixed_body_still_parses(monkeypatch):
    monkeypatch.setattr(
        license.urllib.request,
        "urlopen",
        lambda *a, **k: FakeResponse('﻿  {"action": "ok", "message": "hi"}\n'),
    )
    assert license._request("check.php", {}, 5).action == "ok"
