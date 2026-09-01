#!/usr/bin/env python3
"""
Drawing Helpers Module

The small painting routines every layer shares: panels, labelled text, and
the measurement helpers that keep type inside its box.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Optional

from PIL import ImageDraw, ImageFont

from . import theme


def measure(pen: ImageDraw.ImageDraw, text: str,
            face: ImageFont.FreeTypeFont) -> tuple:
    """
    Measure a string in a given face

    @param pen: ImageDraw The drawing context
    @param text: str The string to measure
    @param face: FreeTypeFont The face to measure in
    @return tuple: The width and height in pixels
    """

    # the bounding box is anchored at the origin, so the extents are the size
    box = pen.textbbox((0, 0), str(text or ""), font=face)
    return (box[2] - box[0], box[3] - box[1])


def text(pen: ImageDraw.ImageDraw, xy: tuple, value: str,
         face: ImageFont.FreeTypeFont, color: tuple = theme.TEXT,
         anchor: str = "la", shadow: bool = True) -> None:
    """
    Draw a string, with a drop shadow behind it by default

    Broadcast graphics sit over photographic radar and map imagery, so the
    shadow is what keeps small type readable across every backdrop.

    @param pen: ImageDraw The drawing context
    @param xy: tuple Where to anchor the string
    @param value: str The string to draw
    @param face: FreeTypeFont The face to draw in
    @param color: tuple The fill colour
    @param anchor: str A Pillow text anchor
    @param shadow: bool Whether to draw the shadow
    @return None
    """

    # nothing to draw
    content = str(value or "")
    if not content:
        return

    # the shadow first, offset by a pixel or two
    if shadow:
        offset = max(1, face.size // 24)
        pen.text((xy[0] + offset, xy[1] + offset), content, font=face,
                 fill=theme.SHADOW, anchor=anchor)

    # then the type itself
    pen.text(xy, content, font=face, fill=color, anchor=anchor)


def fit_face(pen: ImageDraw.ImageDraw, value: str, weight: str, size: int,
             max_width: int, minimum: int = 10) -> ImageFont.FreeTypeFont:
    """
    Find the largest size of a face that keeps a string inside a width

    @param pen: ImageDraw The drawing context
    @param value: str The string that has to fit
    @param weight: str The face weight to use
    @param size: int The size to start from
    @param max_width: int The width the string must fit inside
    @param minimum: int The smallest size we will drop to
    @return FreeTypeFont: The chosen face
    """

    # step down until it fits or we hit the floor
    points = max(minimum, int(size))
    while points > minimum:
        face = theme.font(weight, points)
        if measure(pen, value, face)[0] <= max_width:
            return face
        points -= max(1, points // 16)
    return theme.font(weight, minimum)


def panel(pen: ImageDraw.ImageDraw, box: tuple, fill: tuple = theme.PANEL,
          outline: Optional[tuple] = theme.PANEL_LINE, radius: int = 0,
          width: int = 1) -> None:
    """
    Draw one of the flat panels the pages are built from

    @param pen: ImageDraw The drawing context
    @param box: tuple Left, top, right, and bottom
    @param fill: tuple The panel fill
    @param outline: tuple|None The border colour, or None for no border
    @param radius: int Corner radius, zero for square corners
    @param width: int Border width
    @return None
    """

    # a degenerate box would raise rather than simply draw nothing
    left, top, right, bottom = box
    if right <= left or bottom <= top:
        return

    # square corners are the house style, but the radius is there if wanted
    if radius > 0:
        pen.rounded_rectangle(box, radius=radius, fill=fill, outline=outline,
                              width=width)
    else:
        pen.rectangle(box, fill=fill, outline=outline, width=width)


def accent_bar(pen: ImageDraw.ImageDraw, box: tuple,
               color: tuple = theme.ACCENT) -> None:
    """
    Draw the accent rule that heads a panel

    @param pen: ImageDraw The drawing context
    @param box: tuple Left, top, right, and bottom
    @param color: tuple The bar colour
    @return None
    """

    # just a filled rectangle, but it appears often enough to name
    left, top, right, bottom = box
    if right <= left or bottom <= top:
        return
    pen.rectangle(box, fill=color)


def stat_tile(pen: ImageDraw.ImageDraw, box: tuple, label: str, value: str,
              scale: float, value_color: tuple = theme.TEXT) -> None:
    """
    Draw one labelled value tile

    @param pen: ImageDraw The drawing context
    @param box: tuple Left, top, right, and bottom
    @param label: str The small caption above the value
    @param value: str The value itself
    @param scale: float The output scale factor
    @param value_color: tuple Colour for the value
    @return None
    """

    # the tile body
    left, top, right, bottom = box
    if right <= left or bottom <= top:
        return
    panel(pen, box, fill=theme.PANEL_ALT, outline=theme.PANEL_LINE)

    # its accent rule
    rule = max(2, int(round(3 * scale)))
    accent_bar(pen, (left, top, right, top + rule))

    # the caption
    pad = max(6, int(round(14 * scale)))
    label_face = theme.font("semibold", max(10, int(round(20 * scale))))
    text(pen, (left + pad, top + rule + pad), str(label).upper(), label_face,
         theme.TEXT_FAINT)

    # and the value, shrunk to fit if it has to be
    value_size = max(12, int(round(38 * scale)))
    face = fit_face(pen, str(value), "bold", value_size,
                    max(10, (right - left) - pad * 2))
    text(pen, (left + pad, bottom - pad), str(value), face, value_color,
         anchor="ls")
