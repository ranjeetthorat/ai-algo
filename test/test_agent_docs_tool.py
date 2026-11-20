"""The agent's ``docs`` toolkit wrapper, and the prompt sections that drive it.

The ranking, containment and index live in ``services/docs_search.py`` and are
tested in ``test_docs_search.py``. This file pins the agent-side adapter: that the
toolkit is registered chat-only, that it wraps the shared core's results, and that
the prompt teaches the tools on the chat surface and nowhere else.

**A surface is never taught a tool it does not have.** The docs toolkit is
chat-only, like the generators, so ``DOCS_SECTION`` and ``STRATEGY_BUILD_SECTION``
must be chat-only too. The prompt tests assert both appear on chat and on neither
voice nor chart, and that the strategy section names documents that actually exist.
"""

from __future__ import annotations

import json

import pytest

from services import docs_search
from services.agent import prompts
from services.agent.builder import DEFAULT_MAX_PROMPT_CHARS
from services.agent.tools import (
    CHAT_ONLY,
    SURFACE_CHART,
    SURFACE_CHAT,
    SURFACE_VOICE,
    TOOLKITS,
    ToolContext,
    agno_available,
    select_specs,
)

requires_agno = pytest.mark.skipif(not agno_available(), reason="the agno package is not installed")


def _unwrap(block: str) -> dict:
    """Parse the JSON out of a ``<tool_result ...>...</tool_result>`` block.

    Args:
        block: The wrapped tool result the toolkit returns.

    Returns:
        The decoded payload.
    """
    start = block.index(">") + 1
    end = block.rindex("</")
    return json.loads(block[start:end])


# ---------------------------------------------------------------------------
# The registry: chat only, no capability
# ---------------------------------------------------------------------------


class TestTheDocsToolkitIsRegistered:
    def test_it_is_in_the_registry(self):
        spec = next((s for s in TOOLKITS if s.key == "docs"), None)
        assert spec is not None
        assert spec.module == "services.agent.tools.docs"
        assert spec.attr == "DocsToolkit"

    def test_it_is_chat_only_like_the_generators(self):
        spec = next(s for s in TOOLKITS if s.key == "docs")
        assert spec.surfaces == CHAT_ONLY

        chat = {s.key for s in select_specs(ToolContext(api_key="k", surface=SURFACE_CHAT))}
        voice = {s.key for s in select_specs(ToolContext(api_key="k", surface=SURFACE_VOICE))}
        chart = {s.key for s in select_specs(ToolContext(api_key="k", surface=SURFACE_CHART))}
        assert "docs" in chat
        assert "docs" not in voice
        assert "docs" not in chart

    def test_it_needs_no_capability(self):
        # Reading docs mutates nothing, so a read-only session gets it.
        spec = next(s for s in TOOLKITS if s.key == "docs")
        assert spec.requires == frozenset()
        keys = {
            s.key
            for s in select_specs(
                ToolContext(api_key="k", surface=SURFACE_CHAT, trading_enabled=False)
            )
        }
        assert "docs" in keys


# ---------------------------------------------------------------------------
# The toolkit wraps the shared core
# ---------------------------------------------------------------------------


@requires_agno
class TestTheToolkit:
    def _kit(self):
        from services.agent.tools.docs import DocsToolkit

        return DocsToolkit(ToolContext(api_key="k", surface=SURFACE_CHAT))

    def test_search_returns_ranked_results(self):
        result = _unwrap(self._kit().search_docs("python strategy kit PARAMS"))
        assert result["ok"] is True
        assert result["results"][0]["path"] == "strategycontext/writing-strategies.md"

    def test_get_doc_reads_a_document(self):
        result = _unwrap(self._kit().get_doc("strategycontext/sdk.md"))
        assert result["ok"] is True
        assert result["content"]

    def test_get_doc_refuses_a_path_outside_docs(self):
        result = _unwrap(self._kit().get_doc("../CLAUDE.md"))
        assert result["ok"] is False

    def test_index_prefix_is_accepted(self):
        result = _unwrap(self._kit().get_doc("docs/INDEX.md"))
        assert result["ok"] is True
        assert result["path"] == "INDEX.md"


# ---------------------------------------------------------------------------
# The prompt sections
# ---------------------------------------------------------------------------


class TestThePromptSections:
    def test_the_sections_are_chat_only(self):
        chat = {s.key for s in prompts.sections_for(SURFACE_CHAT)}
        voice = {s.key for s in prompts.sections_for(SURFACE_VOICE)}
        chart = {s.key for s in prompts.sections_for(SURFACE_CHART)}
        for key in ("docs", "strategy_build"):
            assert key in chat
            assert key not in voice
            assert key not in chart

    def test_the_chat_prompt_teaches_the_docs_tools(self):
        prompt = prompts.build_system_prompt(surface=SURFACE_CHAT)
        assert "search_docs" in prompt
        assert "get_doc" in prompt

    def test_the_strategy_section_names_documents_that_exist(self):
        # The section tells the model to get_doc these before writing a strategy;
        # a stale path would send it to read nothing.
        body = prompts.STRATEGY_BUILD_SECTION.body
        root = docs_search._docs_root()
        assert root is not None
        for rel in ("strategycontext/writing-strategies.md", "strategycontext/sdk.md"):
            assert rel in body
            assert (root / rel).is_file()

    def test_the_identity_section_asks_to_mirror_the_operators_language(self):
        body = prompts.IDENTITY_SECTION.body
        assert "Hindi" in body and "Marathi" in body

    @pytest.mark.parametrize("surface", [SURFACE_CHAT, SURFACE_CHART, SURFACE_VOICE])
    @pytest.mark.parametrize("trading", [False, True])
    def test_every_surface_renders_whole_inside_the_budget(self, surface, trading):
        whole = prompts.build_system_prompt(surface=surface, trading_enabled=trading)
        capped = prompts.build_system_prompt(
            surface=surface, trading_enabled=trading, max_chars=DEFAULT_MAX_PROMPT_CHARS
        )
        assert whole == capped, (
            f"the {surface} prompt is {len(whole)} characters and the budget is "
            f"{DEFAULT_MAX_PROMPT_CHARS}; a whole section was dropped to fit."
        )
