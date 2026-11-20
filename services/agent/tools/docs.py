"""The agent's ``docs`` toolkit: a thin wrapper over :mod:`services.docs_search`.

The search engine, the ranking, the containment check and the index all live in
:mod:`services.docs_search`, which has no ``agno`` dependency so the MCP server
can share it. This module only adapts that engine to an agno toolkit: it exposes
``search_docs`` and ``get_doc`` as tools and wraps each plain-dict result in the
``<tool_result>`` envelope the agent labels data with.

The agent uses this to ground "how do I ..." answers in the installed docs rather
than in training, and to read the real strategy-kit and Flow references before it
generates a file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from services import docs_search
from services.agent.prompts import wrap_tool_result
from services.agent.tools.base import OpenAlgoToolkit

if TYPE_CHECKING:  # pragma: no cover - typing only
    from services.agent.tools import ToolContext


class DocsToolkit(OpenAlgoToolkit):
    """Read the FastAlgo documentation to ground an answer or a generated file."""

    #: No service function is called, so there is no api_key to inject.
    inject_api_key = False

    def __init__(self, context: ToolContext) -> None:
        """Register the two read-only documentation tools.

        Args:
            context: The run's tool context.
        """
        super().__init__(
            context,
            name="docs",
            tools=[self.search_docs, self.get_doc],
        )

    # -- tools ---------------------------------------------------------------

    def search_docs(self, query: str) -> str:
        """Search the FastAlgo documentation and return the best-matching documents.

        Use this to ground any "how do I ...", "what is ...", "does FastAlgo
        support ..." or "where do I configure ..." question in the platform's own
        docs instead of answering from memory, and to find the exact reference
        before you write a strategy, an indicator or a Flow workflow. The docs are
        the single source of truth for this installed version; your training is
        not.

        After searching, call get_doc on the most relevant path to read it, then
        answer from what it says and name the document you used.

        Args:
            query: What you are looking for, in a few words. Topic words beat a
                full sentence: "python strategy kit PARAMS" finds more than "how
                do I write a strategy that takes settings".

        Returns:
            JSON with ``results``: each has ``path`` (pass it to get_doc),
            ``title``, ``score`` and a ``snippet``. ``docs/INDEX.md`` is the map
            of the whole documentation set if a search is too broad.
        """
        return self._result("search_docs", docs_search.search(query))

    def get_doc(self, path: str, section: str = "") -> str:
        """Read one FastAlgo documentation file (optionally a single section).

        Call this on a ``path`` from search_docs, or on ``INDEX.md`` to see the
        map of the whole set. For a long reference, pass ``section`` to read only
        the part you need rather than the whole file.

        Args:
            path: The document to read, relative to the docs folder, exactly as
                search_docs returned it, for example ``strategycontext/sdk.md`` or
                ``INDEX.md``. A leading ``docs/`` is accepted and ignored.
            section: Optional heading to narrow to. A case-insensitive substring
                of a heading, for example ``orders`` to read the "Placing orders"
                section alone. Omit it to read the whole document.

        Returns:
            JSON with ``path``, ``title`` and ``content`` (markdown). Long
            documents are truncated with a note; pass ``section`` to read a
            specific part instead.
        """
        return self._result("get_doc", docs_search.read_doc(path, section=section))

    # -- helpers -------------------------------------------------------------

    def _result(self, tool: str, payload: Any) -> str:
        """Serialise a payload and label it as data for the model.

        Args:
            tool: The tool name, written into the block's opening tag.
            payload: The result to return.

        Returns:
            A ``<tool_result>`` block wrapping the capped JSON.
        """
        return wrap_tool_result(tool, self.to_json(payload))
