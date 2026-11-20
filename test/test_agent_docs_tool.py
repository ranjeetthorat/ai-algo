"""The documentation-grounding toolkit, and the prompt sections that drive it.

Three things are pinned here.

**Grounding ranks the focused reference above the sprawling plan.** Before this
tool existed the agent answered "how do I ..." from memory and invented routes.
The tool searches ``docs/`` instead, and the ranking test is the point: a query
about the strategy kit must surface ``strategycontext/writing-strategies.md`` and
not the long implementation plan that merely mentions "strategy" forty times,
which is exactly what BM25 length-normalisation plus excluding the contributor
trees buys. A regression in either sends the plan back to the top.

**The containment check is the control.** ``get_doc`` takes a model-supplied path,
so the tests feed it ``../CLAUDE.md`` and ``../../.env`` and assert they are
refused. The tool is read-only and reaches no secret, but reading a file outside
``docs/`` would still be a disclosure the operator did not ask for.

**A surface is never taught a tool it does not have.** The docs toolkit is
chat-only, like the generators, so ``DOCS_SECTION`` and ``STRATEGY_BUILD_SECTION``
must be chat-only too. The prompt tests assert both appear on chat and on neither
voice nor chart, and that the strategy section names documents that actually exist.
"""

from __future__ import annotations

import json
import math

import pytest

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
from services.agent.tools import docs as docs_tool

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


def _rank(query: str, k: int = 5) -> list[str]:
    """Rank the real docs for a query using the module's own scorer.

    Exercises the ranking without constructing the toolkit, so it runs whether or
    not agno is installed.

    Args:
        query: The search query.
        k: How many top paths to return.

    Returns:
        The top matching document paths, best first.
    """
    index = docs_tool._load_index()
    avgdl = sum(doc.length for doc in index) / len(index)
    total = len(index)
    idf = {
        term: math.log(1 + total / (1 + sum(1 for doc in index if term in doc.lower)))
        for term in docs_tool._terms(query)
    }
    scored = [(doc, docs_tool._score(doc, docs_tool._terms(query), idf, avgdl)) for doc in index]
    scored = [pair for pair in scored if pair[1] > 0]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [doc.path for doc, _score in scored[:k]]


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
# The index and the ranking
# ---------------------------------------------------------------------------


class TestTheIndex:
    def test_it_indexes_the_product_docs(self):
        paths = {doc.path for doc in docs_tool._load_index()}
        assert "INDEX.md" in paths
        assert any(p.startswith("strategycontext/") for p in paths)
        assert any(p.startswith("api/") for p in paths)

    def test_it_excludes_the_contributor_trees(self):
        paths = {doc.path for doc in docs_tool._load_index()}
        for excluded in docs_tool.EXCLUDE_DIRS:
            assert not any(p.startswith(f"{excluded}/") for p in paths), (
                f"{excluded}/ should not be indexed"
            )

    def test_it_degrades_when_there_is_no_docs_tree(self, monkeypatch):
        monkeypatch.setattr(docs_tool, "_docs_root", lambda: None)
        assert docs_tool._load_index() == ()


class TestRankingFavoursTheFocusedDoc:
    """The failure this tool exists to prevent: a plan outranking the reference."""

    def test_strategy_kit_query_surfaces_the_strategy_reference(self):
        top = _rank("python strategy kit PARAMS settings")
        assert top[0] == "strategycontext/writing-strategies.md"

    def test_placing_an_order_surfaces_the_order_api(self):
        top = _rank("how do I place an order")
        assert any(p.startswith("api/order-management/placeorder") for p in top[:3])

    def test_option_chain_surfaces_the_option_chain_api(self):
        top = _rank("option chain greeks")
        assert top[0].startswith("api/options-services/optionchain")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("docs/INDEX.md", "INDEX.md"),
            ("<prompt/openalgo python sdk.md>", "prompt/openalgo python sdk.md"),
            ("/strategycontext/sdk.md", "strategycontext/sdk.md"),
            ("INDEX.md", "INDEX.md"),
            ("'strategycontext/host.md'", "strategycontext/host.md"),
        ],
    )
    def test_path_is_normalised(self, raw, expected):
        assert docs_tool._normalise_path(raw) == expected

    def test_terms_drop_stopwords_and_short_tokens(self):
        terms = docs_tool._terms("How do I write a strategy")
        assert "strategy" in terms
        assert "write" in terms
        assert "how" not in terms and "do" not in terms and "i" not in terms

    def test_section_extraction(self):
        text = "# Title\n\nintro\n\n## Orders\n\nbody about orders\n\n## Quotes\n\nother\n"
        section = docs_tool._section_of(text, "orders")
        assert section is not None
        assert "body about orders" in section
        assert "other" not in section
        assert docs_tool._section_of(text, "nonexistent") is None


# ---------------------------------------------------------------------------
# The toolkit end to end, including containment
# ---------------------------------------------------------------------------


@requires_agno
class TestTheToolkit:
    def _kit(self):
        from services.agent.tools.docs import DocsToolkit

        return DocsToolkit(ToolContext(api_key="k", surface=SURFACE_CHAT))

    def test_search_returns_ranked_results(self):
        result = _unwrap(self._kit().search_docs("python strategy kit PARAMS"))
        assert result["ok"] is True
        assert result["count"] >= 1
        first = result["results"][0]
        assert first["path"] == "strategycontext/writing-strategies.md"
        assert first["snippet"]

    def test_search_rejects_an_empty_query(self):
        result = _unwrap(self._kit().search_docs("   "))
        assert result["ok"] is False

    def test_get_doc_reads_a_document(self):
        result = _unwrap(self._kit().get_doc("strategycontext/sdk.md"))
        assert result["ok"] is True
        assert result["path"] == "strategycontext/sdk.md"
        assert result["content"]

    def test_get_doc_can_narrow_to_a_section(self):
        whole = _unwrap(self._kit().get_doc("strategycontext/sdk.md"))
        section = _unwrap(self._kit().get_doc("strategycontext/sdk.md", section="order"))
        assert section["ok"] is True
        assert section.get("section") == "order"
        assert len(section["content"]) < len(whole["content"])

    def test_index_prefix_is_accepted(self):
        result = _unwrap(self._kit().get_doc("docs/INDEX.md"))
        assert result["ok"] is True
        assert result["path"] == "INDEX.md"

    @pytest.mark.parametrize("path", ["../CLAUDE.md", "../../.env", "../pyproject.toml"])
    def test_a_path_outside_docs_is_refused(self, path):
        result = _unwrap(self._kit().get_doc(path))
        assert result["ok"] is False

    def test_a_nonexistent_doc_is_refused(self):
        result = _unwrap(self._kit().get_doc("strategycontext/not-a-real-doc.md"))
        assert result["ok"] is False


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
        root = docs_tool._docs_root()
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
