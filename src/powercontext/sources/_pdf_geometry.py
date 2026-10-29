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

"""Horizontal CID geometry used as independent evidence for extraction boundaries.

This deliberately supports a subset of PDF text operations. Unsupported fonts,
Forms, rotations or state changes disable this evidence, never page extraction.
No reference text or scoring data is consumed here.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, cast

from pypdf._text_extraction._layout_mode._text_state_manager import TextStateManager
from pypdf.errors import PdfReadError
from pypdf.generic import ContentStream


def coordinate_text(page: Any, plain: str) -> str | None:
    """Return complete coordinate evidence, or None for unsupported pages.

    The text state helper is internal to the supported pypdf 6.x dependency;
    original CID widths, rather than decoded Unicode widths, drive advances.
    Character conservation also checks for incomplete or ambiguous decoding.
    """
    try:
        candidate = _coordinate_text(page)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, NotImplementedError, PdfReadError):
        return None
    if Counter(c for c in plain if not c.isspace()) != Counter(c for c in candidate if not c.isspace()):
        return None
    return candidate


def _cid_widths(font: Any) -> tuple[dict[int, float], float]:
    descendant = font["/DescendantFonts"][0].get_object()
    raw = descendant.get("/W", [])
    widths: dict[int, float] = {}
    index = 0
    while index < len(raw):
        start, value = int(raw[index]), raw[index + 1].get_object()
        if isinstance(value, list):
            widths.update({start + offset: float(width) for offset, width in enumerate(cast(list[Any], value))})
            index += 2
        else:
            widths.update(dict.fromkeys(range(start, int(value) + 1), float(raw[index + 2])))
            index += 3
    return widths, float(descendant.get("/DW", 1000))


def _fragments(page: Any) -> list[dict[str, Any]]:
    """Reconstruct horizontal runs using original CID advances and space widths.

    Unsupported font encodings, Form XObjects and rotation are rejected rather
    than silently emitting a seemingly complete experimental page.
    """
    fonts = page._layout_mode_fonts()
    resources = page["/Resources"]
    if any(obj.get_object().get("/Subtype") == "/Form" for obj in resources.get("/XObject", {}).values()):
        raise ValueError("Coordinate evidence does not interpret Form XObjects")  # noqa: TRY003
    pdf_fonts = resources["/Font"]
    metrics = {}
    for name, font in pdf_fonts.items():
        font = font.get_object()
        if font.get("/Encoding") != "/Identity-H":
            raise ValueError("Coordinate evidence requires horizontal Identity-H fonts")  # noqa: TRY003
        metrics[name] = _cid_widths(font)
    return _interpret_shows(page, fonts, metrics)


def _fragment(show: Any, metrics: Any, name: str) -> tuple[dict[str, Any], float]:
    if (
        show.rotated
        or abs(show.transform[1]) > 1e-6
        or abs(show.transform[2]) > 1e-6
        or show.transform[0] <= 0
        or show.Tz <= 0
    ):
        raise ValueError("Coordinate evidence does not interpret rotated or skewed text")  # noqa: TRY003
    if not isinstance(show.value, bytes) or len(show.value) % 2:
        raise ValueError("Coordinate evidence requires complete two-byte character codes")  # noqa: TRY003
    widths, default_width = metrics[name]
    codes = [int.from_bytes(show.value[i : i + 2], "big") for i in range(0, len(show.value), 2)]
    space_codes = {
        ord(code)
        for code, text in show.font.character_map.items()
        if isinstance(code, str) and len(code) == 1 and text in {" ", "\N{NO-BREAK SPACE}"}
    }
    # A PDF may encode all inter-word spaces as NBSP. Use their declared
    # advance as geometry evidence, without deleting or rewriting those glyphs.
    space = min((widths[code] for code in space_codes if code in widths and widths[code] > 0), default=0)
    if space <= 0:
        raise ValueError("Coordinate evidence requires an explicit positive space width")  # noqa: TRY003
    advance = (
        (sum(widths.get(code, default_width) for code in codes) * show.font_size / 1000 + len(codes) * show.Tc)
        * show.Tz
        / 100
    )
    return {
        "text": show.text,
        "font": name,
        "x": show.tx,
        "y": show.ty,
        "end_x": show.tx + advance * show.transform[0],
        "font_height": show.font_height,
        "space_width": abs(space * show.font_size / 1000 * show.Tz / 100 * show.transform[0]),
    }, advance


def _position(state: Any, args: list[Any], op: bytes) -> None:
    state.reset_trm()
    if op == b"Tm":
        state.reset_tm()
    elif op == b"TD":
        state.set_state_param(b"TL", -args[1])
    elif op == b"T*":
        args = [0, -state.TL]
    state.add_tm(args)


def _interpret_shows(page: Any, fonts: Any, metrics: Any) -> list[dict[str, Any]]:
    state = TextStateManager()
    name = ""
    names = []
    fragments = []
    for args, op in ContentStream(page["/Contents"], page.pdf, "bytes").operations:
        if op == b"q":
            state.add_q()
            names.append((name, {key: getattr(state, key) for key in ("Tc", "Tw", "Tz", "TL", "Ts")}))
        elif op == b"Q":
            state.remove_q()
            name, parameters = names.pop()
            for key, value in parameters.items():
                setattr(state, key, value)
        elif op == b"cm":
            state.add_cm(*args)
        elif op in {b"BT", b"ET"}:
            state.reset_tm()
        elif op == b"Tf":
            name = args[0]
            state.set_font(fonts[name], float(args[1]))
        elif op in {b"Tm", b"Td", b"TD", b"T*"}:
            _position(state, args, op)
        elif op in {b"Tj", b"TJ"}:
            fragments.extend(_show_operands(state, args if op == b"Tj" else args[0], metrics, name))
        else:
            _other_operator(page, state, args, op)
    return fragments


def _other_operator(page: Any, state: Any, args: list[Any], op: bytes) -> None:
    if op in {b"'", b'"', b"Do"} or (op == b"gs" and "/Font" in page["/Resources"]["/ExtGState"][args[0]]):
        raise ValueError("Unsupported coordinate evidence operator")  # noqa: TRY003
    state.set_state_param(op, args)


def _show_operands(state: Any, values: Any, metrics: Any, name: str) -> list[dict[str, Any]]:
    fragments = []
    for value in values:
        if isinstance(value, bytes):
            fragment, advance = _fragment(state.text_state_params(value), metrics, name)
            fragments.append(fragment)
        else:
            advance = -float(value) * state.font_size / 1000 * state.Tz / 100
        state.add_trm([1, 0, 0, 1, advance, 0])
    return fragments


def _coordinate_text(page: Any) -> str:
    fragments = _fragments(page)
    pieces: list[str] = []
    previous = None
    for fragment in fragments:
        separator = ""
        if previous is not None:
            height = min(previous["font_height"], fragment["font_height"])
            gap = fragment["x"] - previous["end_x"]
            if abs(fragment["y"] - previous["y"]) > height * 0.25 or gap < -height:
                separator = "\n"
            elif (
                gap > min(previous["space_width"], fragment["space_width"]) * 0.5
                or previous["font"] != fragment["font"]
                or abs(previous["font_height"] - fragment["font_height"]) > 1e-6
            ):
                separator = " "
        pieces.extend((separator, fragment["text"]))
        previous = fragment
    return "".join(pieces)
