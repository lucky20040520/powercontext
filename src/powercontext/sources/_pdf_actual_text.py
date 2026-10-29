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

"""Recover NUL character mappings from fully covered PDF ActualText spans."""

from __future__ import annotations

import copy
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pypdf import PageObject


@dataclass
class _Span:
    text: str | None
    glyphs: list[tuple[str, bytes]] = field(default_factory=list)
    ambiguous: bool = False

    def mark_nested_replacement(self, parents: list[_Span]) -> None:
        for parent in parents:
            if parent.text is not None and self.text is not None:
                parent.ambiguous = self.ambiguous = True


def repair_actual_text(page: PageObject) -> PageObject | None:
    """Repair only Identity-H NUL bfchar entries certified by the PDF itself.

    Every use of a repaired character code on this page must be inside a
    single-glyph ActualText span with the same replacement. Conflicts, uncovered
    uses, nested replacements, and unsupported mappings stay unchanged. Original
    bytes and font streams are never mutated.
    """
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    resources = page.get("/Resources", DictionaryObject()).get_object()
    fonts = resources.get("/Font", DictionaryObject()).get_object()
    xobjects = resources.get("/XObject", DictionaryObject()).get_object()
    graphics = resources.get("/ExtGState", DictionaryObject()).get_object()
    if any(ref.get_object().get("/Subtype") == "/Form" for ref in xobjects.values()) or any(
        "/Font" in ref.get_object() for ref in graphics.values()
    ):
        # A Form can inherit page fonts. Do not change its interpretation based
        # on spans seen only in the page's own content stream.
        return None
    uses, replacements = _actual_text_coverage(page)
    updated_fonts = DictionaryObject(fonts)
    changed = False
    for name, ref in fonts.items():
        font = ref.get_object()
        if font.get("/Encoding") != "/Identity-H" or "/ToUnicode" not in font:
            continue
        cmap = font["/ToUnicode"].get_data()
        patched = _patch_null_entries(str(name), cmap, uses, replacements)
        if patched != cmap:
            replacement = DecodedStreamObject()
            replacement.set_data(patched)
            updated = DictionaryObject(font)
            updated[NameObject("/ToUnicode")] = replacement
            updated_fonts[NameObject(name)] = updated
            changed = True
    if not changed:
        return None
    result = copy.copy(page)
    updated_resources = DictionaryObject(resources)
    updated_resources[NameObject("/Font")] = updated_fonts
    result[NameObject("/Resources")] = updated_resources
    return result


def _patch_null_entries(
    font: str,
    cmap: bytes,
    uses: Counter[tuple[str, bytes]],
    replacements: dict[tuple[str, bytes], Counter[str]],
) -> bytes:
    def patch_block(block: re.Match[bytes]) -> bytes:
        def patch_entry(entry: re.Match[bytes]) -> bytes:
            code = bytes.fromhex(entry[1].decode("ascii"))
            observed = replacements.get((font, code), Counter())
            if len(observed) != 1 or observed.total() != uses[font, code]:
                return entry[0]
            text = next(iter(observed))
            return b"<" + entry[1] + b"> <" + text.encode("utf-16-be").hex().encode("ascii") + b">"

        return re.sub(rb"<([0-9A-Fa-f]{4})>\s*<0000>", patch_entry, block[0])

    return re.sub(rb"\bbeginbfchar\b.*?\bendbfchar\b", patch_block, cmap, flags=re.DOTALL)


def _replacement_text(value: Any, resources: Any) -> str | None:
    from pypdf.generic import ByteStringObject, NameObject, TextStringObject, create_string_object

    if isinstance(value, NameObject):
        value = resources.get("/Properties", {}).get_object().get(value) if "/Properties" in resources else None
    if value is None:
        return None
    value = value.get_object()
    if not isinstance(value, dict):
        return None
    text = value.get("/ActualText")
    if isinstance(text, ByteStringObject):
        text = create_string_object(bytes(text))
    return str(text) if isinstance(text, TextStringObject) and text and "\0" not in text else None


def _draw_codes(args: list[Any], op: bytes) -> list[bytes]:
    if op == b"TJ":
        values = args[0] if args else []
    elif op in {b"Tj", b"'", b'"'}:
        values = args[-1:]
    else:
        return []
    codes = []
    for value in values:
        if isinstance(value, bytes):
            # Odd lengths must never accidentally certify a two-byte code.
            codes.extend(value[index : index + 2] for index in range(0, len(value), 2))
    return codes


def _actual_text_coverage(page: PageObject) -> tuple[Counter[tuple[str, bytes]], dict[tuple[str, bytes], Counter[str]]]:
    from pypdf.generic import ContentStream, DictionaryObject

    resources = page.get("/Resources", DictionaryObject()).get_object()
    uses: Counter[tuple[str, bytes]] = Counter()
    replacements: dict[tuple[str, bytes], Counter[str]] = defaultdict(Counter)
    spans: list[_Span] = []
    fonts = [""]
    operations = ContentStream(page["/Contents"], page.pdf, "bytes").operations
    for args, op in operations:
        if op == b"q":
            fonts.append(fonts[-1])
        elif op == b"Q":
            if len(fonts) > 1:
                fonts.pop()
        elif op == b"Tf" and args:
            fonts[-1] = str(args[0])
        elif op in {b"BDC", b"BMC"}:
            span = _Span(_replacement_text(args[1], resources) if op == b"BDC" and len(args) > 1 else None)
            span.mark_nested_replacement(spans)
            spans.append(span)
        elif op == b"EMC" and spans:
            span = spans.pop()
            if span.text is not None and not span.ambiguous and len(span.glyphs) == 1:
                replacements[span.glyphs[0]][span.text] += 1
        else:
            glyphs = [(fonts[-1], code) for code in _draw_codes(args, op)]
            uses.update(glyphs)
            for span in spans:
                span.glyphs.extend(glyphs)
    return uses, replacements
