"""The shared documentation-search core (services/docs_search.py).

This is the engine behind both the agent's ``docs`` toolkit and the MCP server's
``search_docs`` / ``get_doc`` tools, so it is tested on its own, with no agno and
no platform running.

Two things are pinned.

**Ranking surfaces the focused reference, not the sprawling plan.** A query about
the strategy kit must return ``strategycontext/writing-strategies.md`` and not a
long internal plan that merely mentions "strategy" many times - which is what BM25
length-normalisation plus excluding the contributor trees buys. A regression in
either sends the plan back to the top.

**Containment is the control.** ``read_doc`` takes a caller-supplied path, so the
tests feed it ``../CLAUDE.md`` and ``../../.env`` and assert they are refused.
"""

from __future__ import annotations

import math

import pytest

from services import docs_search


def _rank(query: str, k: int = 5) -> list[str]:
    """Rank the real docs for a query using the module's own scorer.

    Args:
        query: The search query.
        k: How many top paths to return.

    Returns:
        The top matching document paths, best first.
    """
    index = docs_search._load_index()
    avgdl = sum(doc.length for doc in index) / len(index)
    total = len(index)
    terms = docs_search._terms(query)
    idf = {
        term: math.log(1 + total / (1 + sum(1 for doc in index if term in doc.lower)))
        for term in terms
    }
    scored = [(doc, docs_search._score(doc, terms, idf, avgdl)) for doc in index]
    scored = [pair for pair in scored if pair[1] > 0]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [doc.path for doc, _score in scored[:k]]


class TestTheIndex:
    def test_it_indexes_the_product_docs(self):
        paths = {doc.path for doc in docs_search._load_index()}
        assert "INDEX.md" in paths
        assert any(p.startswith("strategycontext/") for p in paths)
        assert any(p.startswith("api/") for p in paths)

    def test_it_excludes_the_contributor_trees(self):
        paths = {doc.path for doc in docs_search._load_index()}
        for excluded in docs_search.EXCLUDE_DIRS:
            assert not any(p.startswith(f"{excluded}/") for p in paths), (
                f"{excluded}/ should not be indexed"
            )

    def test_it_degrades_when_there_is_no_docs_tree(self, monkeypatch):
        monkeypatch.setattr(docs_search, "_docs_root", lambda: None)
        assert docs_search._load_index() == ()
        assert docs_search.available() is False
        assert docs_search.search("anything")["ok"] is False
        assert docs_search.read_doc("INDEX.md")["ok"] is False


class TestRankingFavoursTheFocusedDoc:
    """The failure this engine exists to prevent: a plan outranking the reference."""

    def test_strategy_kit_query_surfaces_the_strategy_reference(self):
        assert _rank("python strategy kit PARAMS settings")[0] == (
            "strategycontext/writing-strategies.md"
        )

    def test_placing_an_order_surfaces_the_order_api(self):
        top = _rank("how do I place an order")
        assert any(p.startswith("api/order-management/placeorder") for p in top[:3])

    def test_option_chain_surfaces_the_option_chain_api(self):
        assert _rank("option chain greeks")[0].startswith("api/options-services/optionchain")


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
        assert docs_search._normalise_path(raw) == expected

    def test_terms_drop_stopwords_and_short_tokens(self):
        terms = docs_search._terms("How do I write a strategy")
        assert "strategy" in terms
        assert "write" in terms
        assert "how" not in terms and "do" not in terms and "i" not in terms

    def test_section_extraction(self):
        text = "# Title\n\nintro\n\n## Orders\n\nbody about orders\n\n## Quotes\n\nother\n"
        section = docs_search._section_of(text, "orders")
        assert section is not None
        assert "body about orders" in section
        assert "other" not in section
        assert docs_search._section_of(text, "nonexistent") is None


class TestSearchAndReadDoc:
    def test_search_returns_ranked_results(self):
        result = docs_search.search("python strategy kit PARAMS")
        assert result["ok"] is True
        assert result["count"] >= 1
        assert result["results"][0]["path"] == "strategycontext/writing-strategies.md"
        assert result["results"][0]["snippet"]

    def test_search_rejects_an_empty_query(self):
        assert docs_search.search("   ")["ok"] is False

    def test_read_doc_reads_a_document(self):
        result = docs_search.read_doc("strategycontext/sdk.md")
        assert result["ok"] is True
        assert result["path"] == "strategycontext/sdk.md"
        assert result["content"]

    def test_read_doc_can_narrow_to_a_section(self):
        whole = docs_search.read_doc("strategycontext/sdk.md")
        section = docs_search.read_doc("strategycontext/sdk.md", section="order")
        assert section["ok"] is True
        assert section.get("section") == "order"
        assert len(section["content"]) < len(whole["content"])

    def test_read_doc_accepts_a_docs_prefix(self):
        result = docs_search.read_doc("docs/INDEX.md")
        assert result["ok"] is True
        assert result["path"] == "INDEX.md"

    @pytest.mark.parametrize("path", ["../CLAUDE.md", "../../.env", "../pyproject.toml"])
    def test_a_path_outside_docs_is_refused(self, path):
        assert docs_search.read_doc(path)["ok"] is False

    def test_a_nonexistent_doc_is_refused(self):
        assert docs_search.read_doc("strategycontext/not-a-real-doc.md")["ok"] is False

    def test_a_long_document_is_truncated(self):
        result = docs_search.read_doc("INDEX.md", max_chars=200)
        assert result["ok"] is True
        assert len(result["content"]) <= 200
        assert result.get("truncated") is True
