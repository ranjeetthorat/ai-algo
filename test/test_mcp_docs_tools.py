"""The MCP docs-grounding tools: search_docs, get_doc, check_connection.

These are the thin MCP wrappers over ``services/docs_search.py`` (the ranking and
containment are tested in ``test_docs_search.py``) plus the connection self-check.
test_mcp_integrity.py already pins their scope, annotations and toolset; this file
pins behaviour: that the wrappers reach the shared core and return the trust
envelope, that containment holds through the MCP surface, and that
``check_connection`` degrades to a clear "could not authenticate" when the SDK
client is not wired (as it is not in this import-only test).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# mcp/mcpserver.py raises at import time unless it sees stdio argv or this flag.
os.environ.setdefault("OPENALGO_MCP_HTTP_BOOT", "1")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _ensure_sdk_openalgo() -> None:
    """Stop the repo root (also named ``openalgo``) from masking the SDK.

    Mirrors the guard in test_mcp_integrity.py: the repo root carries an empty
    ``__init__.py`` so pytest can treat it as a package and shadow the installed
    ``openalgo`` SDK that mcp/mcpserver.py imports.
    """
    parent = str(PROJECT_ROOT.parent)
    while parent in sys.path:
        sys.path.remove(parent)
    shadow = sys.modules.get("openalgo")
    if shadow is not None and not hasattr(shadow, "api"):
        for name in [n for n in sys.modules if n == "openalgo" or n.startswith("openalgo.")]:
            del sys.modules[name]
    import openalgo

    assert hasattr(openalgo, "api")


_ensure_sdk_openalgo()

from utils.mcp_tool_registry import TOOL_SCOPES, _load_mcpserver_module  # noqa: E402


@pytest.fixture(scope="module")
def server():
    _ensure_sdk_openalgo()
    module = _load_mcpserver_module()
    assert module is not None, "could not load mcp/mcpserver.py"
    return module


def _data(enveloped: str) -> dict:
    """Unwrap the trust envelope the MCP tools return and give back ``data``."""
    parsed = json.loads(enveloped)
    return parsed.get("data", parsed)


_DOC_TOOLS = ("search_docs", "get_doc", "check_connection", "get_strategy_guide")


class TestTheToolsAreRegisteredAndScoped:
    def test_the_tools_are_present(self, server):
        for name in _DOC_TOOLS:
            assert name in server.TOOL_META, f"{name} not registered"
            assert name in TOOL_SCOPES, f"{name} has no scope"

    def test_they_are_read_only_utility_tools(self, server):
        for name in _DOC_TOOLS:
            meta = server.TOOL_META[name]
            assert meta.read_only is True
            assert meta.toolset == "utility"

    def test_the_doc_tools_carry_the_documentation_risk_class(self, server):
        for name in ("search_docs", "get_doc", "get_strategy_guide"):
            assert server.TOOL_META[name].risk == server.RISK_DOCUMENTATION


class TestBehaviour:
    def test_search_docs_reaches_the_shared_core(self, server):
        result = _data(server.search_docs("python strategy kit PARAMS"))
        assert result["ok"] is True
        assert result["results"][0]["path"].startswith("strategycontext/")

    def test_get_doc_reads_the_index(self, server):
        result = _data(server.get_doc("INDEX.md"))
        assert result["ok"] is True
        assert result["content"]

    def test_get_doc_refuses_a_path_outside_docs(self, server):
        result = _data(server.get_doc("../CLAUDE.md"))
        assert result["ok"] is False

    def test_check_connection_reports_reachable_and_unauthenticated(self, server):
        # The HTTP-boot path leaves client=None until init_for_http runs, which it
        # has not here, so the key cannot be verified. The tool must say so clearly
        # rather than raise.
        result = _data(server.check_connection())
        assert result["server"] == "reachable"
        assert result["tools_available"] > 0
        assert result["api_key"] == "could not authenticate"

    def test_strategy_guide_returns_the_authoring_doc(self, server):
        result = _data(server.get_strategy_guide())
        assert result["ok"] is True
        assert result["path"] == "strategycontext/ai-strategy-authoring.md"
        assert "strategy kit" in result["content"]
