# Copyright (c) 2026 OceanBase.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

"""Offline, query-dependent selection of literal, versioned Memory evidence."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from powercontext.artifacts import ArtifactAddress
from powercontext.builtin.runtime.errors import PreparedContextInvariantError
from powercontext.builtin.runtime.prepared_text import TRUST_POLICY

if TYPE_CHECKING:
    from powercontext.builtin.runtime.prepared_context import PreparedMemoryCandidates

_STOP_WORDS = frozenset([
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "by",
    "can",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "had",
    "has",
    "have",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "may",
    "of",
    "on",
    "or",
    "our",
    "should",
    "than",
    "that",
    "the",
    "their",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "would",
])
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z\d\u3400-\u9fff])|(?<=[。！？])\s*|\n+")  # noqa: RUF001
_BEGIN = "BEGIN_POWERCONTEXT_PREPARED_CONTEXT_V1"
_END = "END_POWERCONTEXT_PREPARED_CONTEXT_V1"


@dataclass(frozen=True)
class MemoryEntryAddress:
    """Identify one exact Memory entry version across Scope boundaries."""

    memory: ArtifactAddress
    entry_id: str
    entry_version_id: str


@dataclass(frozen=True)
class PreparedEvidenceFragment:
    """A verbatim half-open Python character interval in an exact Memory version."""

    address: MemoryEntryAddress
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class EvidenceSelection:
    """Literal output and fitting pressure, counted in relevant sentence candidates."""

    content: str | None
    fragments: tuple[PreparedEvidenceFragment, ...]
    truncated_items: int = 0
    dropped_items: int = 0


@dataclass(frozen=True)
class _Sentence:
    document: int
    start: int
    end: int
    terms: frozenset[str]
    score: float = 0.0


@dataclass(frozen=True)
class _Document:
    address: MemoryEntryAddress
    text: str


def _terms(text: str) -> frozenset[str]:
    terms: set[str] = set()
    for match in _WORD.finditer(text.casefold()):
        word = match.group()
        if word in _STOP_WORDS:
            continue
        if any("\u3400" <= char <= "\u9fff" for char in word):
            terms.update(word[index : index + 2] for index in range(max(1, len(word) - 1)))
            continue
        # Conservative inflection folding keeps numbers and short scientific identifiers intact.
        if len(word) > 5 and word.endswith("ies"):
            word = word[:-3] + "y"
        elif len(word) > 5 and word.endswith("ing"):
            word = word[:-3]
        elif len(word) > 4 and word.endswith("ed"):
            word = word[:-2]
        elif len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "is", "us")):
            word = word[:-1]
        if len(word) > 4:
            word = word.removesuffix("e")
        terms.add(word)
    return frozenset(terms)


def _sentences(document: int, text: str) -> list[_Sentence]:
    spans = []
    start = 0
    for match in _BOUNDARY.finditer(text):
        if match.start() > start:
            spans.append((start, match.end()))
        # Retain delimiter whitespace on both sides. Historical sentence intervals may
        # include it, and merging selected neighbors removes the overlap without rewriting.
        start = match.start()
    if start < len(text):
        spans.append((start, len(text)))
    result = []
    for start, end in spans:
        if text[start:end].strip():
            result.append(_Sentence(document, start, end, _terms(text[start:end])))
    return result


def _documents(candidates: Sequence[PreparedMemoryCandidates]) -> list[_Document]:
    documents = []
    seen: set[tuple[str, str, str, int, str, str]] = set()
    for group in candidates:
        if group.hits and group.memory_ref is None:
            raise PreparedContextInvariantError("memory-ref-missing")
        for hit in group.hits:
            if hit.memory_ref != group.memory_ref:
                raise PreparedContextInvariantError("memory-ref-mismatch")
            if not hit.entry_id.strip() or not hit.entry_version_id.strip() or not hit.text.strip():
                continue
            address = MemoryEntryAddress(
                ArtifactAddress(scope_id=group.scope_id, artifact=hit.memory_ref), hit.entry_id, hit.entry_version_id
            )
            identity = (
                group.scope_id,
                hit.memory_ref.family,
                hit.memory_ref.artifact_id,
                hit.memory_ref.revision,
                hit.entry_id,
                hit.entry_version_id,
            )
            if identity not in seen:
                documents.append(_Document(address, hit.text))
                seen.add(identity)
    return documents


def _rank(documents: Sequence[_Document], query: str) -> list[_Sentence]:
    query_terms = _terms(query)
    sentences = [sentence for index, doc in enumerate(documents) for sentence in _sentences(index, doc.text)]
    document_terms = [_terms(doc.text) for doc in documents]
    frequency = Counter(term for terms in document_terms for term in terms & query_terms)
    weights = {term: math.log(1 + (len(documents) + 1) / (frequency[term] + 0.5)) ** 2 for term in query_terms}
    total = sum(weights.values()) or 1.0
    document_coverage = [sum(weights[term] for term in terms & query_terms) / total for terms in document_terms]
    first = {index: next((s.start for s in sentences if s.document == index), 0) for index in range(len(documents))}
    last = {index: max((s.end for s in sentences if s.document == index), default=0) for index in range(len(documents))}
    ranked = []
    for sentence in sentences:
        coverage = sum(weights[term] for term in sentence.terms & query_terms) / total
        if not coverage:
            continue
        score = coverage**1.4 * document_coverage[sentence.document] ** 3
        body = documents[sentence.document].text[sentence.start : sentence.end].casefold()
        # Abstract headings and discourse cues distinguish reported findings from background.
        if sentence.start == first[sentence.document] and sentence.end != last[sentence.document]:
            score *= 0.55
        if sentence.end == last[sentence.document]:
            score *= 1.25
        if re.match(r"(?:background|objective|aim|purpose|method|introduction)\b", body):
            score *= 0.6
        if re.match(r"(?:result|conclusion|finding)s?\b", body) or re.search(
            r"\b(?:we (?:show|found|find|demonstrate|report)|these (?:results|findings))\b", body
        ):
            score *= 1.4
        # Length normalization is gentle: complete result sentences often carry several clauses.
        score /= 1 + len(sentence.terms) / 100
        ranked.append(_Sentence(sentence.document, sentence.start, sentence.end, sentence.terms, score))
    return sorted(ranked, key=lambda sentence: -sentence.score)[:64]


def _fragments(documents: Sequence[_Document], selected: Sequence[_Sentence]) -> tuple[PreparedEvidenceFragment, ...]:
    intervals: dict[int, list[tuple[int, int]]] = {}
    for sentence in selected:
        intervals.setdefault(sentence.document, []).append((sentence.start, sentence.end))
    fragments = []
    for index, spans in intervals.items():
        doc = documents[index]
        merged: list[tuple[int, int]] = []
        for start, end in sorted(spans):
            # Joining adjacent sentences preserves the whitespace in the source and saves a citation.
            if merged and not doc.text[merged[-1][1] : start].strip():
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        fragments.extend(
            PreparedEvidenceFragment(doc.address, start, end, doc.text[start:end]) for start, end in merged
        )
    return tuple(fragments)


def render_evidence(fragments: Sequence[PreparedEvidenceFragment]) -> str:
    """Render the complete trust envelope; JSON escaping is included in the budget."""
    items = [
        {
            "citation": {
                "scope_id": fragment.address.memory.scope_id,
                "memory_ref": fragment.address.memory.artifact.model_dump(mode="json"),
                "entry_id": fragment.address.entry_id,
                "entry_version_id": fragment.address.entry_version_id,
            },
            "content": fragment.text,
            "start": fragment.start,
            "end": fragment.end,
        }
        for fragment in fragments
    ]
    encoded = json.dumps({"trust": "untrusted_history", "items": items}, ensure_ascii=False, separators=(",", ":"))
    # Escape line separators so historical text cannot introduce additional envelope lines.
    encoded = encoded.replace("\x85", "\\u0085").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    return f"{TRUST_POLICY}\n\n{_BEGIN}\n{encoded}\n{_END}"


def _query_matches(text: str, start: int, end: int, query_terms: frozenset[str]) -> list[tuple[int, int]]:
    """Locate query mentions without changing offsets during token normalization."""
    matches: list[tuple[int, int]] = []
    for match in _WORD.finditer(text, start, end):
        word = match.group()
        if any("\u3400" <= char <= "\u9fff" for char in word):
            matches.extend(
                (match.start() + index, match.start() + min(index + 2, len(word)))
                for index in range(max(1, len(word) - 1))
                if word[index : index + 2].casefold() in query_terms
            )
        elif _terms(word) & query_terms:
            matches.append(match.span())
    return matches


def _fit_window(
    sentence: _Sentence, documents: Sequence[_Document], selected: Sequence[_Sentence], query: str, max_bytes: int
) -> _Sentence | None:
    """Fit a query-centered literal window when a complete sentence cannot fit."""
    text = documents[sentence.document].text
    query_terms = _terms(query)
    matches = _query_matches(text, sentence.start, sentence.end, query_terms)
    if not matches:
        return None
    # Bound fitting work independently of repeated mentions in a long entry.
    anchors = sorted(
        matches,
        key=lambda span: (
            -len(_terms(text[max(sentence.start, span[0] - 80) : min(sentence.end, span[1] + 160)]) & query_terms)
        ),
    )[:16]
    best = None
    for anchor_start, anchor_end in anchors:
        start = max(sentence.start, anchor_start - 80)
        # Prefer word boundaries while leaving the query mention inside the interval.
        while start < anchor_start and not text[start].isspace():
            start += 1
        low, high = anchor_end, sentence.end
        fitted = None
        while low <= high:
            end = (low + high) // 2
            window = _Sentence(sentence.document, start, end, _terms(text[start:end]), sentence.score)
            cost = len(render_evidence(_fragments(documents, [*selected, window])).encode("utf-8"))
            if cost <= max_bytes:
                fitted = window
                low = end + 1
            else:
                high = end - 1
        if fitted is None:
            continue
        retained = len(fitted.terms & query_terms)
        if best is None or retained > len(best.terms & query_terms):
            best = fitted
    return best


def select_evidence(
    candidates: Sequence[PreparedMemoryCandidates], query: str, max_bytes: int, entry_limit: int
) -> EvidenceSelection:
    """Rank sentences, then spend the actual serialized budget on complementary evidence.

    Scanning/tokenizing is linear in input size. At most 64 ranked sentences participate
    in fitting; each successful step consumes a sentence. No model, corpus or I/O is used.
    """
    documents = _documents(candidates)
    remaining = _rank(documents, query)
    selected: list[_Sentence] = []
    fragments: tuple[PreparedEvidenceFragment, ...] = ()
    content = None
    truncated_items = 0
    dropped_items = 0
    used = len(render_evidence(()).encode("utf-8"))
    while remaining:
        best = None
        for index, sentence in enumerate(remaining):
            proposed = _fragments(documents, [*selected, sentence])
            if len(proposed) > entry_limit:
                continue
            rendered = render_evidence(proposed)
            cost = len(rendered.encode("utf-8"))
            if cost > max_bytes:
                continue
            utility = sentence.score / max(1, cost - used) ** 0.25
            if best is None or utility > best[0]:
                best = (utility, index, proposed, rendered, cost)
        if best is None:
            # The entry ceiling is a selection policy, not byte-budget pressure.
            blocked = [s for s in remaining if len(_fragments(documents, [*selected, s])) <= entry_limit]
            windows = [
                window
                for sentence in blocked
                if (window := _fit_window(sentence, documents, selected, query, max_bytes)) is not None
            ]
            dropped_items = len(blocked)
            if windows:
                window = max(windows, key=lambda item: item.score * len(item.terms & _terms(query)))
                proposed = _fragments(documents, [*selected, window])
                if len(proposed) <= entry_limit:
                    fragments = proposed
                    content = render_evidence(fragments)
                    truncated_items = 1
                    dropped_items -= 1
            break
        _, index, fragments, content, used = best
        selected.append(remaining.pop(index))
    return EvidenceSelection(content, fragments, truncated_items, dropped_items)
