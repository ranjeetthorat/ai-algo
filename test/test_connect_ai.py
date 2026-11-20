"""The 'Connect your AI' backend wiring.

The page itself is React; this pins the two server-side pieces it depends on: the
JSON config route exists on the API-key blueprint, the page route exists on the
React blueprint (so a logged-out bookmark hit is a known route, not an
Error404Tracker ban candidate), and the API-key-bearer flag parses from the
environment the same way the MCP transport reads it.
"""

from __future__ import annotations

import pytest
from flask import Flask

from blueprints.apikey import _mcp_apikey_auth_enabled, api_key_bp
from blueprints.react_app import react_bp


def test_apikey_auth_flag_defaults_on(monkeypatch):
    monkeypatch.delenv("MCP_APIKEY_AUTH_ENABLED", raising=False)
    assert _mcp_apikey_auth_enabled() is True


@pytest.mark.parametrize(
    "value,expected", [("false", False), ("0", False), ("true", True), ("on", True)]
)
def test_apikey_auth_flag_parses_env(monkeypatch, value, expected):
    monkeypatch.setenv("MCP_APIKEY_AUTH_ENABLED", value)
    assert _mcp_apikey_auth_enabled() is expected


def test_config_route_is_registered():
    app = Flask(__name__)
    app.register_blueprint(api_key_bp)
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/connect-ai/config" in rules


def test_page_route_is_registered():
    app = Flask(__name__)
    app.register_blueprint(react_bp)
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/connect-ai" in rules
