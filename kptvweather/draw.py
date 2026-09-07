#!/usr/bin/env python3
"""
Drawing Helpers Module

The small painting routines every layer shares: panels, cards, gradients,
labelled text, and the measurement helpers that keep type inside its box.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Optional

from PIL import Image, ImageDraw, ImageFont

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


def gradient(surface: Image.Image, box: tuple, top_color: tuple,
             bottom_color: tuple, radius: int = 0) -> None:
    """
    Fill a box with a vertical gradient, optionally rounded

    Painted a row at a time into a scratch image and pasted through a mask,
    which keeps the corners clean without touching the surface underneath.

    @param surface: Image The surface to paint onto
    @param box: tuple Left, top, right, and bottom
    @param top_color: tuple The colour at the top edge
    @param bottom_color: tuple The colour at the bottom edge
    @param radius: int Corner radius, zero for square corners
    @return None
    """

    # a degenerate box has nothing to fill
    left, top, right, bottom = (int(value) for value in box)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        return

    # walk the rows, blending as we go
    tile = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pen = ImageDraw.Draw(tile)
    span = max(1, height - 1)
    for row in range(height):
        pen.line([(0, row), (width, row)],
                 fill=theme.mix(top_color, bottom_color, row / span))

    # square corners paste straight on, rounded ones go through a mask
    if radius > 0:
        mask = Image.new("L", (width, height), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, width - 1, height - 1), radius=radius, fill=255
        )
        surface.paste(tile, (left, top), mask)
    else:
        surface.paste(tile, (left, top), tile)


def card(surface: Image.Image, box: tuple, scale: float,
         accent: Optional[tuple] = None,
         top_color: tuple = theme.CARD_TOP,
         bottom_color: tuple = theme.CARD_BOTTOM,
         outline: Optional[tuple] = theme.CARD_LINE) -> None:
    """
    Draw one of the rounded gradient cards the pages are built from

    @param surface: Image The surface to paint onto
    @param box: tuple Left, top, right, and bottom
    @param scale: float The output scale factor
    @param accent: tuple|None Colour for the rule along the top edge
    @param top_color: tuple The gradient's top stop
    @param bottom_color: tuple The gradient's bottom stop
    @param outline: tuple|None The hairline border colour, or None
    @return None
    """

    # a degenerate box would raise rather than simply draw nothing
    left, top, right, bottom = (int(value) for value in box)
    if right <= left or bottom <= top:
        return

    # the body
    radius = max(4, int(round(theme.RADIUS * scale)))
    gradient(surface, (left, top, right, bottom), top_color, bottom_color,
             radius)

    # the hairline that lifts it off the backdrop
    pen = ImageDraw.Draw(surface)
    if outline is not None:
        pen.rounded_rectangle((left, top, right - 1, bottom - 1),
                              radius=radius, outline=outline, width=1)

    # and the accent rule, clipped to the rounded top corners
    if accent is None:
        return
    rule = max(2, int(round(4 * scale)))
    strip = Image.new("RGBA", (right - left, bottom - top), (0, 0, 0, 0))
    ImageDraw.Draw(strip).rectangle((0, 0, right - left, rule), fill=accent)
    mask = Image.new("L", (right - left, bottom - top), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, right - left - 1, bottom - top - 1), radius=radius, fill=255
    )
    surface.paste(strip, (left, top), Image.composite(
        mask, Image.new("L", mask.size, 0), strip.split()[3]
    ))

def rounded_paste(surface: Image.Image, image: Image.Image, xy: tuple,
                  radius: int) -> None:
    """
    Paste an image with its corners rounded off

    @param surface: Image The surface to paint onto
    @param image: Image The image to paste
    @param xy: tuple Where the image's top left corner lands
    @param radius: int The corner radius
    @return None
    """

    # a square paste when there is nothing to round
    if radius <= 0:
        surface.paste(image, xy, image)
        return

    # mask the corners off and paste through it
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, image.size[0] - 1, image.size[1] - 1), radius=radius, fill=255
    )
    surface.paste(image, xy, mask)

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


def stat_tile(surface: Image.Image, box: tuple, label: str, value: str,
              scale: float, value_color: tuple = theme.TEXT) -> None:
    """
    Draw one labelled value tile

    @param surface: Image The surface to paint onto
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
    card(surface, box, scale, accent=theme.ACCENT,
         top_color=theme.PANEL_ALT, bottom_color=theme.CARD_BOTTOM)

    # everything else prints over it
    pen = ImageDraw.Draw(surface)

    # the caption and the room the pair have to share
    pad = max(6, int(round(14 * scale)))
    rule = max(2, int(round(3 * scale)))
    label_face = theme.font("semibold", max(10, int(round(20 * scale))))
    label_size = getattr(label_face, "size", 10)
    value_size = max(12, int(round(38 * scale)))
    inner_h = (bottom - top) - rule - pad * 2

    # a short tile puts the two side by side instead of stacking them
    if inner_h < label_size + value_size:
        value_face = fit_face(pen, str(value), "bold",
                              max(12, int(inner_h * 0.86)),
                              max(10, (right - left) - pad * 3 -
                                  measure(pen, str(label).upper(),
                                          label_face)[0]))
        center = top + rule + (bottom - top - rule) // 2
        text(pen, (left + pad, center), str(label).upper(), label_face,
             theme.TEXT_FAINT, anchor="lm")
        text(pen, (right - pad, center), str(value), value_face, value_color,
             anchor="rm")
        return

    # otherwise the caption sits over the value
    text(pen, (left + pad, top + rule + pad), str(label).upper(), label_face,
         theme.TEXT_FAINT)
    face = fit_face(pen, str(value), "bold", value_size,
                    max(10, (right - left) - pad * 2))
    text(pen, (left + pad, bottom - pad), str(value), face, value_color,
         anchor="ls")
         