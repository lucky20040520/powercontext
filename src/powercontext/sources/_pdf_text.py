# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Conservative PDF text candidate selection using only the input document."""

from __future__ import annotations

import copy
import re
import unicodedata
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pypdf import PageObject

_SHORT_WORDS = frozenset([
    "a",
    "i",
    "an",
    "as",
    "at",
    "be",
    "by",
    "do",
    "go",
    "he",
    "if",
    "in",
    "is",
    "it",
    "me",
    "my",
    "no",
    "of",
    "on",
    "or",
    "so",
    "to",
    "up",
    "us",
    "we",
])
# Expand only alphabetic presentation ligatures, not compatibility characters
# such as circled numbers, fractions, or units with different textual meaning.
_LIGATURES = str.maketrans({chr(code): unicodedata.normalize("NFKC", chr(code)) for code in range(0xFB00, 0xFB07)})


@dataclass(frozen=True)
class TextMetrics:
    text_length: int
    non_whitespace_characters: int
    alphabetic_words: int
    abnormal_short_words: int
    abnormal_single_letters: int
    short_word_ratio: float
    single_letter_ratio: float
    repeated_text_ratio: float
    broken_short_word_lines: int

    @property
    def fragmented(self) -> bool:
        # A few footnote labels or table units are insufficient evidence.
        return (
            (self.abnormal_single_letters >= 4 and self.single_letter_ratio >= 0.035)
            or (self.abnormal_short_words >= 8 and self.short_word_ratio >= 0.10)
            or self.broken_short_word_lines >= 3
        )


def text_metrics(text: str) -> TextMetrics:
    words = re.findall(r"[A-Za-z]+", text)
    short = sum(len(word) <= 2 and word.lower() not in _SHORT_WORDS for word in words)
    single = sum(len(word) == 1 and word.lower() not in {"a", "i"} for word in words)
    broken_lines = sum(
        any(len(word) <= 2 and word.lower() not in _SHORT_WORDS for word in match.groups())
        for match in re.finditer(r"([A-Za-z]+)[ \t]*\r?\n[ \t]*([A-Za-z]+)", text)
    )
    nonspace = "".join(text.split())
    # Measure repeated character sequences independently of word/line breaks:
    # repairing letter spacing must not look like newly duplicated headings.
    windows = Counter(nonspace[index : index + 24] for index in range(max(0, len(nonspace) - 23)))
    repeated = sum(count - 1 for count in windows.values()) / max(1, windows.total())
    # Whole short labels are sometimes drawn twice without an intervening newline.
    if (
        len(nonspace) >= 8
        and len(nonspace) % 2 == 0
        and nonspace[: len(nonspace) // 2] == nonspace[len(nonspace) // 2 :]
    ):
        repeated = max(repeated, 0.5)
    return TextMetrics(
        len(text),
        len(nonspace),
        len(words),
        short,
        single,
        short / max(1, len(words)),
        single / max(1, len(words)),
        repeated,
        broken_lines,
    )


def select_page_text(page: PageObject) -> str:
    """Keep plain extraction unless a complete, less fragmented alternative wins."""
    plain = page.extract_text().translate(_LIGATURES)
    if "\0" in plain:
        from powercontext.sources._pdf_actual_text import repair_actual_text

        repaired = repair_actual_text(page)
        if repaired is not None:
            page = repaired
            plain = page.extract_text().translate(_LIGATURES)
    metrics = text_metrics(plain)
    if metrics.repeated_text_ratio:
        deduplicated = _remove_exact_overprints(page)
        if deduplicated is not None:
            # This removes only proven duplicate drawing operations. It does not
            # discard repeated words at different coordinates, colors or sizes.
            page = deduplicated
            plain = page.extract_text().translate(_LIGATURES)
            metrics = text_metrics(plain)
    selected = plain
    geometry = None
    if metrics.fragmented or (metrics.abnormal_short_words and metrics.broken_short_word_lines):
        from powercontext.sources._pdf_geometry import coordinate_text

        geometry = coordinate_text(page, plain)
        if geometry is not None:
            geometry = geometry.translate(_LIGATURES)
    # Sparse pages cannot meet a large absolute fragment count. In that case,
    # require independent position/width evidence before trying another mode.
    sparse_risk = geometry is not None and candidate_improves(plain, geometry, numeric_text=geometry)
    if metrics.fragmented or sparse_risk:
        selected = _select_fragment_candidate(page, plain, geometry)
    return re.sub(r"[ \t]+", " ", selected) if selected.strip() else ""


def _select_fragment_candidate(page: PageObject, plain: str, geometry: str | None) -> str:
    layout = page.extract_text(extraction_mode="layout").translate(_LIGATURES)
    if geometry is not None:
        layout = _repair_numeric_boundaries(layout, geometry)
    if candidate_improves(plain, layout, numeric_text=geometry):
        return layout
    if (
        geometry is not None
        and _numbers(layout) != _numbers(geometry)
        and candidate_improves(plain, geometry, numeric_text=geometry)
    ):
        # Layout can insert a nearby footnote inside a number. Preserve the
        # complete content-stream order instead of accepting that regrouping
        # or falling back to a demonstrably fragmented default result.
        return geometry
    return plain


def _numbers(text: str) -> Counter[str]:
    return Counter(re.findall(r"\d+(?:[,.]\d+)*", text))


def _repair_numeric_boundaries(candidate: str, geometry: str) -> str:
    """Join only uniquely located splits certified by complete PDF geometry.

    Both the removed pieces and the resulting number must account for the
    numeric multiset difference. Adjacent table values already present in the
    geometry are therefore not eligible. Ambiguous occurrences remain intact.
    """
    expected = _numbers(geometry)
    for number, count in sorted((expected - _numbers(candidate)).items(), key=lambda item: (-len(item[0]), item[0])):
        pattern = r"(?<![\d.,])" + r"[ \t]*".join(re.escape(c) for c in number) + r"(?!\d|[,.]\d)"
        matches = [match for match in re.finditer(pattern, candidate) if match[0] != number]
        if len(matches) != count:
            continue
        pieces = sum((_numbers(match[0]) for match in matches), Counter())
        if pieces - (_numbers(candidate) - expected):
            continue
        for match in reversed(matches):
            candidate = candidate[: match.start()] + number + candidate[match.end() :]
    return candidate


def candidate_improves(plain: str, candidate: str, *, numeric_text: str | None = None) -> bool:
    before, after = text_metrics(plain), text_metrics(candidate)
    if not candidate.strip() or after.repeated_text_ratio > before.repeated_text_ratio + 0.02:
        return False
    # Whitespace can change, but all decoded characters (including financial
    # signs and unresolved NULs) must survive. Nonempty layout can omit a Form.
    if Counter(c for c in plain if not c.isspace()) != Counter(c for c in candidate if not c.isspace()):
        return False
    # Character counts alone miss table cells fused into a different number.
    # Preserve existing multi-digit anchors exactly; isolated digit fragments
    # may legitimately become a complete number in a less fragmented candidate.
    if numeric_text is None:
        anchors = Counter({number: count for number, count in _numbers(plain).items() if re.search(r"\d{2}", number)})
        if anchors - _numbers(candidate):
            return False
    elif _numbers(candidate) != _numbers(numeric_text):
        return False
    # Counts use the conserved character inventory as their common basis.
    # Dividing by each candidate's word count penalizes successful joins by
    # shrinking the denominator, particularly on pages with legal initials.
    return (
        (
            after.abnormal_single_letters < before.abnormal_single_letters
            and after.abnormal_short_words <= before.abnormal_short_words
        )
        or (
            after.abnormal_short_words <= before.abnormal_short_words - 2
            and after.abnormal_single_letters <= before.abnormal_single_letters
        )
        or (
            after.broken_short_word_lines < before.broken_short_word_lines
            and after.abnormal_short_words < before.abnormal_short_words
            and after.abnormal_single_letters <= before.abnormal_single_letters
        )
    )


def _remove_exact_overprints(page: PageObject) -> PageObject | None:
    """Remove identical explicitly positioned draws inside one text object.

    Restrict removal to draws followed by a position reset or ET: suppressing a
    draw must not change the position of subsequent implicitly advanced text.
    Font dictionaries must match, rather than just their displayed font names.
    """
    from pypdf.generic import ArrayObject, ContentStream, DictionaryObject, NameObject

    resources = page.get("/Resources", DictionaryObject()).get_object()
    fonts = resources.get("/Font", DictionaryObject()).get_object()
    equivalents: list[DictionaryObject] = []
    font_ids: dict[str, int] = {}
    for name, ref in fonts.items():
        font = ref.get_object()
        if font not in equivalents:
            equivalents.append(font)
        font_ids[str(name)] = equivalents.index(font)
    contents = page.get_contents()
    if contents is None:
        return None
    operations = list(contents.operations)
    seen: set[tuple[object, ...]] = set()
    changed = False
    for index, key in _explicit_draws(operations, font_ids):
        if key in seen and _position_resets_before_draw(operations, index):
            _, op = operations[index]
            operations[index] = ([ArrayObject()] if op == b"TJ" else [b""], op)
            changed = True
        seen.add(key)
    if not changed:
        return None
    result = copy.copy(page)
    replacement = ContentStream(None, page.pdf)
    replacement.operations = operations
    result[NameObject("/Contents")] = replacement
    return result


def _position_resets_before_draw(operations: list[tuple[list[Any], bytes]], index: int) -> bool:
    for position in range(index + 1, len(operations)):
        _, following = operations[position]
        if following in {b"Tm", b"Td", b"TD", b"T*", b"ET", b"BT"}:
            return True
        if following in {b"Tj", b"TJ", b"'", b'"', b"q", b"Q", b"cm"}:
            return False
    return False


def _explicit_draws(
    operations: list[tuple[list[Any], bytes]], font_ids: dict[str, int]
) -> Iterator[tuple[int, tuple[object, ...]]]:
    state: dict[bytes, object] = {}
    matrix: tuple[float, ...] | None = None
    inside = False
    segment = 0
    for index, (args, op) in enumerate(operations):
        if op in {b"BT", b"ET"}:
            inside = op == b"BT"
            segment += 1
            matrix = None
        elif op == b"Tf":
            state[op] = (font_ids.get(str(args[0]), str(args[0])), float(args[1]))
        elif op in {b"Tc", b"Tw", b"Tz", b"Ts", b"Tr", b"TL"}:
            state[op] = tuple(float(value) for value in args)
        elif inside and op == b"Tm":
            matrix = tuple(float(value) for value in args)
        elif inside and op in {b"Tj", b"TJ"} and matrix is not None:
            yield index, (segment, matrix, tuple(sorted(state.items())), op, repr(args))
            matrix = None
        elif inside:
            # In particular, never deduplicate across graphics/clipping changes
            # or infer a position after a relative movement we did not interpret.
            segment += 1
            matrix = None
