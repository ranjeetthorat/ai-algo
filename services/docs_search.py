"""Pure documentation search over ``docs/``, shared by every consumer.

This is the engine behind the agent's ``docs`` toolkit and the MCP server's
``search_docs`` / ``get_doc`` tools. It is deliberately free of any optional or
heavy dependency - no ``agno``, no Flask, no broker SDK, only the standard
library and :mod:`utils.logging` - so the MCP server can call it in a process
where ``agno`` is not installed, and a test can exercise the ranking without a
running platform. The two adapters on top of it (the agent toolkit and the MCP
tools) only translate: they call :func:`search` and :func:`read_doc`, then wrap
the plain dict in whatever envelope their surface uses.

``docs/`` is the single source of truth for the installed version, and
``docs/INDEX.md`` is its map, written for humans and agents alike. Grounding a
how-to answer or a generated strategy in the installed docs beats recalling an
older version from training.

Read-only. It serves text documents under ``docs/`` and nothing else: no write,
no network, no broker call, no credential ever enters or leaves it.

Containment: :func:`read_doc` resolves the requested path and refuses anything
that is not a text file inside ``docs/``. :func:`search` only ever returns paths
from inside ``docs/``, but the containment check lives on :func:`read_doc`
because a caller could pass a model-supplied path straight in, and the check
costs nothing.
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from utils.logging import get_logger

logger = get_logger(__name__)

#: Text document extensions worth serving. Markdown is the documentation format.
DOC_EXTENSIONS: frozenset[str] = frozenset({".md"})

#: Top-level ``docs/`` subtrees that are contributor- and design-facing, not
#: product documentation. ``docs/INDEX.md`` itself files these under
#: "Architecture, design & specs (contributors)", and they describe intent -
#: sometimes unbuilt, sometimes stale by the project's own rule that the code
#: wins over a design doc - so grounding an operator's how-to answer in them
#: would mislead. They are skipped at index time, which also stops a long PRD
#: from crowding out the focused reference an operator actually needs.
EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        "plans",
        "prd",
        "design",
        "bdd",
        "audit",
        "benchmarks",
        "migration",
        "devsprint",
        "superpowers",
        "releases",
        "test",
    }
)

#: BM25 term-frequency saturation and length-normalisation constants, the
#: standard defaults. ``k1`` bounds how much a repeated term keeps helping; ``b``
#: sets how hard a long document is penalised for its length.
_BM25_K1 = 1.5
_BM25_B = 0.75

#: Most results one search returns. A caller that needs more should search again
#: with a sharper query rather than wade through a long list.
MAX_RESULTS = 6

#: Upper bound on the text one :func:`read_doc` returns by default. Consumers cap
#: their own JSON envelope too, so the body is held under that; a larger document
#: is truncated with a note telling the caller to narrow with a section.
MAX_DOC_CHARS = 10_000

#: Characters of context shown around the first query match in a search snippet.
SNIPPET_RADIUS = 160

#: Longest file this module will read into memory. Documentation files are tiny;
#: this only stops a stray large file in the tree from being slurped.
MAX_FILE_BYTES = 2_000_000

#: Low-signal query words dropped before ranking. Kept deliberately small - idf
#: already discounts common words, so this only removes the ones that carry no
#: topic at all and appear in almost every "how do I ..." question.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "is",
        "are",
        "do",
        "i",
        "my",
        "me",
        "with",
        "how",
        "what",
        "can",
        "where",
        "it",
        "this",
        "that",
        "be",
        "by",
        "use",
        "using",
        "get",
        "set",
    }
)

_TOKEN = re.compile(r"[a-z0-9]+")


@dataclass
class _Doc:
    """One indexed document.

    Attributes:
        path: Path relative to the docs root, forward-slashed, e.g.
            ``strategycontext/sdk.md``. This is what :func:`read_doc` takes back.
        title: First level-one heading, or the filename when there is none.
        text: Full file text.
        lower: Lower-cased body, for match counting.
        lower_title: Lower-cased title.
        lower_headings: Lower-cased headings joined, for a heading-weighted score.
        length: Word count of the body, for BM25 length normalisation.
    """

    path: str
    title: str
    text: str
    lower: str = ""
    lower_title: str = ""
    lower_headings: str = ""
    length: int = 0

    def __post_init__(self) -> None:
        self.lower = self.text.lower()
        self.lower_title = self.title.lower()
        self.length = len(self.lower.split()) or 1


def _docs_root() -> Path | None:
    """Locate the ``docs/`` directory, preferring the working directory.

    The platform runs with the project root as its working directory, exactly
    like ``blueprints/python_strategy.py`` resolving ``strategies/scripts``. A
    second candidate derived from this file's location covers a process started
    from elsewhere.

    Returns:
        The docs directory, or None when neither candidate exists, which each
        consumer reports as "documentation is not available on this install".
    """
    candidates = [Path("docs"), Path(__file__).resolve().parents[1] / "docs"]
    for candidate in candidates:
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    return None


def available() -> bool:
    """Report whether a documentation tree is present on this install.

    Returns:
        True when ``docs/`` can be located.
    """
    return _docs_root() is not None


def _signature(root: Path) -> tuple:
    """Cheap fingerprint of the docs tree, so the index rebuilds when docs change.

    Walks the tree and records each document's size and mtime. The walk is the
    same one the build does; only re-reading bodies is expensive, and that is
    what the signature gates. In production docs are static, so this is stable
    and the cached index is reused for the life of the worker; in development an
    edited doc changes the signature and the next call rebuilds.

    Args:
        root: The docs directory.

    Returns:
        A hashable signature of the tree's documents.
    """
    items: list[tuple[str, int, int]] = []
    root_resolved = root.resolve()
    for dirpath, dirs, files in os.walk(root):
        # Prune contributor-only subtrees at the top level, in place so os.walk
        # does not descend into them.
        if Path(dirpath).resolve() == root_resolved:
            dirs[:] = [name for name in dirs if name not in EXCLUDE_DIRS]
        for name in files:
            if Path(name).suffix.lower() not in DOC_EXTENSIONS:
                continue
            full = Path(dirpath) / name
            try:
                stat = full.stat()
            except OSError:
                continue
            items.append((str(full), int(stat.st_size), int(stat.st_mtime)))
    items.sort()
    return tuple(items)


@lru_cache(maxsize=4)
def _index_cached(root_str: str, signature: tuple) -> tuple[_Doc, ...]:
    """Build and cache the parsed index for one docs tree and signature.

    Keyed by the signature as well as the path, so a changed tree produces a new
    key and the stale entry ages out of the small LRU rather than lingering.

    Args:
        root_str: The docs directory as a string (the cache key).
        signature: The tree signature from :func:`_signature`.

    Returns:
        The parsed documents.
    """
    root = Path(root_str)
    docs: list[_Doc] = []
    for rel_size_mtime in signature:
        full = Path(rel_size_mtime[0])
        if rel_size_mtime[1] > MAX_FILE_BYTES:
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            logger.exception("Could not read documentation file %s", full)
            continue
        try:
            rel = full.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        docs.append(
            _Doc(
                path=rel,
                title=_title_of(text, full.name),
                text=text,
                lower_headings=_headings_of(text).lower(),
            )
        )
    return tuple(docs)


def _load_index() -> tuple[_Doc, ...]:
    """Return the parsed documentation index, rebuilding only when docs change.

    Returns:
        The parsed documents, or an empty tuple when there is no docs tree.
    """
    root = _docs_root()
    if root is None:
        return ()
    return _index_cached(str(root), _signature(root))


def _title_of(text: str, filename: str) -> str:
    """First level-one heading in a markdown file, else the filename.

    Args:
        text: The file text.
        filename: Fallback when the file has no ``# `` heading.

    Returns:
        A display title.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or filename
    return filename


def _headings_of(text: str) -> str:
    """All markdown heading texts in a file, newline-joined.

    Args:
        text: The file text.

    Returns:
        The heading lines with their leading ``#`` markers removed.
    """
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            out.append(stripped.lstrip("#").strip())
    return "\n".join(out)


def _terms(query: str) -> list[str]:
    """Topic tokens from a query: lower-cased, de-stopworded, length >= 2.

    Args:
        query: The raw query string.

    Returns:
        The terms to rank on, in order, duplicates removed.
    """
    seen: list[str] = []
    for token in _TOKEN.findall(query.lower()):
        if len(token) < 2 or token in _STOPWORDS:
            continue
        if token not in seen:
            seen.append(token)
    return seen


def _normalise_path(path: str) -> str:
    """Clean a caller-supplied doc path to one relative to the docs root.

    Strips angle brackets and quotes that ``docs/INDEX.md`` uses to wrap paths
    containing spaces, a leading ``docs/`` the caller may have included, and any
    leading slashes. Does not resolve or validate - :func:`read_doc` does the
    containment check.

    Args:
        path: The path as the caller gave it.

    Returns:
        A cleaned relative path.
    """
    cleaned = path.strip().strip("<>").strip().strip("'\"").strip()
    cleaned = cleaned.replace("\\", "/")
    while cleaned.startswith("/"):
        cleaned = cleaned[1:]
    if cleaned.lower().startswith("docs/"):
        cleaned = cleaned[len("docs/") :]
    return cleaned


def _section_of(text: str, wanted: str) -> str | None:
    """Return the markdown section whose heading matches ``wanted``.

    A section runs from the matching heading to the next heading of the same or a
    higher level. Matching is a case-insensitive substring of the heading text,
    so "risk" finds "## Risk guard".

    Args:
        text: The full document text.
        wanted: The heading text to look for.

    Returns:
        The section text including its heading, or None when no heading matches.
    """
    want = wanted.strip().lower()
    if not want:
        return None
    lines = text.splitlines()
    start = -1
    start_level = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        level = len(stripped) - len(stripped.lstrip("#"))
        heading = stripped.lstrip("#").strip().lower()
        if want in heading:
            start = index
            start_level = level
            break
    if start < 0:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            if level <= start_level:
                end = index
                break
    return "\n".join(lines[start:end]).strip()


def _snippet(doc: _Doc, terms: list[str]) -> str:
    """A short, whitespace-collapsed excerpt around the first query match.

    Args:
        doc: The document.
        terms: The query terms.

    Returns:
        An excerpt with ellipses where it was cut, or the document's opening when
        no term appears in the body (a title-only or heading-only match).
    """
    position = -1
    for term in terms:
        found = doc.lower.find(term)
        if found >= 0 and (position < 0 or found < position):
            position = found
    if position < 0:
        excerpt = doc.text[: SNIPPET_RADIUS * 2]
        prefix, suffix = "", "..." if len(doc.text) > SNIPPET_RADIUS * 2 else ""
    else:
        begin = max(0, position - SNIPPET_RADIUS)
        finish = min(len(doc.text), position + SNIPPET_RADIUS)
        excerpt = doc.text[begin:finish]
        prefix = "..." if begin > 0 else ""
        suffix = "..." if finish < len(doc.text) else ""
    collapsed = " ".join(excerpt.split())
    return f"{prefix}{collapsed}{suffix}"


def _score(doc: _Doc, terms: list[str], idf: dict[str, float], avgdl: float) -> float:
    """Rank one document against the query terms, BM25 on the body.

    The body uses BM25, so a repeated term saturates rather than piling up and a
    long document is penalised for its length - which is what stops a sprawling
    plan that mentions "strategy" forty times from outranking the focused
    strategy reference. A term appearing in the title, a heading or the path adds
    a bounded idf-weighted bonus on top (presence, not count, so repetition in
    headings cannot dominate), because a document named for the topic is far more
    likely the right one than one that merely mentions it.

    Args:
        doc: The document.
        terms: The query terms.
        idf: Inverse document frequency per term.
        avgdl: Average document length across the corpus, for normalisation.

    Returns:
        The document's score. Zero means no term appeared anywhere.
    """
    total = 0.0
    norm = _BM25_K1 * (1 - _BM25_B + _BM25_B * doc.length / avgdl)
    for term in terms:
        term_idf = idf.get(term, 1.0)
        tf = doc.lower.count(term)
        if tf:
            total += term_idf * (tf * (_BM25_K1 + 1)) / (tf + norm)
        if term in doc.lower_title:
            total += term_idf * 4
        if term in doc.lower_headings:
            total += term_idf * 2
        if term in doc.path.lower():
            total += term_idf * 2
    return total


def search(query: str, *, max_results: int = MAX_RESULTS) -> dict[str, Any]:
    """Search the documentation and return the best-matching documents.

    Args:
        query: What to look for; topic words rank better than a full sentence.
        max_results: Most results to return.

    Returns:
        A plain dict payload. On success: ``ok`` True, ``query``, ``count``,
        ``results`` (each ``path``/``title``/``score``/``snippet``) and a
        ``note``. On failure: ``ok`` False with an ``error`` and sometimes a
        ``hint``.
    """
    docs = _load_index()
    if not docs:
        return {"ok": False, "error": "Documentation is not available on this install."}

    terms = _terms(query)
    if not terms:
        return {
            "ok": False,
            "error": "Give at least one topic word to search for.",
            "hint": "Try read a document path 'INDEX.md' to see the documentation map.",
        }

    total = len(docs)
    avgdl = sum(doc.length for doc in docs) / total
    idf: dict[str, float] = {}
    for term in terms:
        df = sum(1 for doc in docs if term in doc.lower)
        idf[term] = math.log(1 + total / (1 + df))

    scored = [(doc, _score(doc, terms, idf, avgdl)) for doc in docs]
    scored = [pair for pair in scored if pair[1] > 0]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    results = [
        {
            "path": doc.path,
            "title": doc.title,
            "score": round(score, 3),
            "snippet": _snippet(doc, terms),
        }
        for doc, score in scored[:max_results]
    ]

    return {
        "ok": True,
        "query": query,
        "count": len(results),
        "results": results,
        "note": (
            "Read a result in full by its path. 'INDEX.md' is the map of all documentation."
            if results
            else "Nothing matched. Read 'INDEX.md' for the documentation map."
        ),
    }


def read_doc(path: str, *, section: str = "", max_chars: int = MAX_DOC_CHARS) -> dict[str, Any]:
    """Read one documentation file, optionally a single section.

    Args:
        path: The document relative to the docs folder, e.g.
            ``strategycontext/sdk.md`` or ``INDEX.md``. A leading ``docs/`` is
            accepted and ignored.
        section: Optional heading substring to narrow to. Omit for the whole file.
        max_chars: Truncation bound for the returned content.

    Returns:
        A plain dict payload. On success: ``ok`` True, ``path``, ``title``,
        ``content``, and optionally ``section`` / ``note`` / ``truncated``. On
        failure: ``ok`` False with an ``error`` and sometimes a ``hint``.
    """
    root = _docs_root()
    if root is None:
        return {"ok": False, "error": "Documentation is not available on this install."}

    relative = _normalise_path(path)
    if not relative:
        return {"ok": False, "error": "Give a document path, for example 'INDEX.md'."}

    try:
        root_resolved = root.resolve()
        target = (root / relative).resolve()
    except OSError:
        logger.exception("Could not resolve documentation path %r", path)
        return {"ok": False, "error": "That path could not be read."}

    if not target.is_relative_to(root_resolved):
        return {
            "ok": False,
            "error": "That path is outside the documentation folder.",
            "hint": "Use a path from a search, or 'INDEX.md'.",
        }
    if target.suffix.lower() not in DOC_EXTENSIONS or not target.is_file():
        return {
            "ok": False,
            "error": f"No documentation file at {relative!r}.",
            "hint": "Search first, then pass a path it returned.",
        }

    try:
        text = target.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        logger.exception("Could not read documentation file %s", target)
        return {"ok": False, "error": "That document could not be read."}

    title = _title_of(text, target.name)
    section_used = ""
    if section.strip():
        found = _section_of(text, section)
        if found is not None:
            text = found
            section_used = section.strip()

    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars]

    payload: dict[str, Any] = {
        "ok": True,
        "path": relative,
        "title": title,
        "content": text,
    }
    if section_used:
        payload["section"] = section_used
    elif section.strip():
        payload["note"] = f"No heading matched {section.strip()!r}; returning the whole document."
    if truncated:
        payload["truncated"] = True
        payload["truncation_note"] = (
            "Document truncated. Read it again with a section to narrow to a specific part."
        )
    return payload
