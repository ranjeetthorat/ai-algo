"""Bearer authentication on the HTTP MCP transport.

The transport accepts two kinds of bearer: an OAuth access token (unchanged) and
a FastAlgo API key pasted straight into the header, which is the simple
copy-paste path for a desktop or IDE MCP client. These tests pin that path:

* an OAuth token still authenticates (no regression);
* a valid API key yields the configured scopes, defaulting to read + docs +
  strategy and never ``write:orders``;
* an invalid token is rejected;
* the key never appears in the claims or the rate-limit key - only a hash;
* the whole API-key path can be switched off to force OAuth only.
"""

from __future__ import annotations

import hashlib

import pytest

from blueprints import mcp_http
from utils.oauth_tokens import AccessTokenError


def _sentinel_verify_api_key(valid_for: str | None):
    """A stand-in verify_api_key returning a user for one key, else None."""

    def _fake(key: str):
        return "user-1" if key == valid_for else None

    return _fake


class TestConfigHelpers:
    def test_apikey_auth_on_by_default(self, monkeypatch):
        monkeypatch.delenv("MCP_APIKEY_AUTH_ENABLED", raising=False)
        assert mcp_http._apikey_auth_enabled() is True

    def test_apikey_auth_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("MCP_APIKEY_AUTH_ENABLED", "false")
        assert mcp_http._apikey_auth_enabled() is False

    def test_default_scopes_exclude_write(self, monkeypatch):
        monkeypatch.delenv("MCP_APIKEY_SCOPES", raising=False)
        assert "write:orders" not in mcp_http._apikey_scopes()
        assert "read:market" in mcp_http._apikey_scopes()
        assert "read:account" in mcp_http._apikey_scopes()


class TestAuthenticate:
    def test_oauth_token_still_authenticates(self, monkeypatch):
        monkeypatch.setattr(
            mcp_http, "verify_access_token", lambda t: {"scope": "read:market", "jti": "abc"}
        )
        claims = mcp_http._authenticate("a.valid.jwt")
        assert claims["jti"] == "abc"
        assert claims["scope"] == "read:market"

    def test_valid_api_key_grants_default_scope(self, monkeypatch):
        monkeypatch.delenv("MCP_APIKEY_SCOPES", raising=False)
        monkeypatch.setenv("MCP_APIKEY_AUTH_ENABLED", "true")
        monkeypatch.setattr("database.auth_db.verify_api_key", _sentinel_verify_api_key("good-key"))
        claims = mcp_http._authenticate("good-key")
        assert claims["client_id"] == "api_key"
        assert "read:account" in claims["scope"]
        assert "write:orders" not in claims["scope"]

    def test_the_key_never_appears_in_the_claims(self, monkeypatch):
        monkeypatch.setattr(
            "database.auth_db.verify_api_key", _sentinel_verify_api_key("secret-key")
        )
        claims = mcp_http._authenticate("secret-key")
        assert "secret-key" not in repr(claims)
        # jti carries only a hash prefix of the key.
        digest = hashlib.sha256(b"secret-key").hexdigest()[:16]
        assert claims["jti"] == f"apikey:{digest}"

    def test_scopes_are_configurable(self, monkeypatch):
        monkeypatch.setenv("MCP_APIKEY_SCOPES", "read:market read:account write:orders")
        monkeypatch.setattr("database.auth_db.verify_api_key", _sentinel_verify_api_key("k"))
        claims = mcp_http._authenticate("k")
        assert "write:orders" in claims["scope"]

    def test_an_invalid_token_is_rejected(self, monkeypatch):
        monkeypatch.setattr("database.auth_db.verify_api_key", _sentinel_verify_api_key("good"))
        with pytest.raises(AccessTokenError):
            mcp_http._authenticate("not-a-jwt-and-not-a-key")

    def test_disabling_apikey_auth_skips_the_key_check(self, monkeypatch):
        monkeypatch.setenv("MCP_APIKEY_AUTH_ENABLED", "false")

        def _must_not_be_called(_key):
            raise AssertionError("verify_api_key called while API-key auth disabled")

        monkeypatch.setattr("database.auth_db.verify_api_key", _must_not_be_called)
        with pytest.raises(AccessTokenError):
            mcp_http._authenticate("not-a-jwt")


class TestRateLimitKey:
    def test_api_key_bearer_is_keyed_by_hash(self):
        # An opaque (non-JWT) bearer is keyed by a hash of the token, so the key is
        # stable per token and computed without verifying it.
        from flask import Flask

        app = Flask(__name__)
        with app.test_request_context(headers={"Authorization": "Bearer some-opaque-key"}):
            key = mcp_http._rate_limit_key()
        assert key == f"key:{hashlib.sha256(b'some-opaque-key').hexdigest()[:16]}"

    def test_no_bearer_falls_back_to_ip(self):
        from flask import Flask

        app = Flask(__name__)
        with app.test_request_context():
            key = mcp_http._rate_limit_key()
        assert not key.startswith("key:") and not key.startswith("jti:")
