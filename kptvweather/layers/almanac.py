#!/usr/bin/env python3
"""
Almanac Layer

The detail page: sun times, the moon at its actual phase, and the readings
that do not earn a place on the current conditions page.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Callable, Optional

from PIL import ImageDraw

from .. import draw, icons, theme
from ..core.layer import Layer


class AlmanacLayer(Layer):
    """
    The almanac page
    """

    def __init__(self, x: int, y: int, w: int, h: int, get_rows: Callable,
                 min_interval: float = 20.0, scale: float = 1.0):
        """
        Build the page

        @param x: int Left edge within the frame
        @param y: int Top edge within the frame
        @param w: int Surface width
        @param h: int Surface height
        @param get_rows: Callable Returns the almanac rows
        @param min_interval: float Shortest gap between redraws
        @param scale: float The output scale factor
        """

        # the surface, the data source, and the last state we drew
        super().__init__(x, y, w, h, min_interval, scale)
        self.get_rows = get_rows
        self._last: Optional[tuple] = None

    def tick(self, now: float) -> bool:
        """
        Redraw when any row changes

        @param now: float Current wall clock time
        @return bool: True when the surface changed
        """

        # every row as one comparable key
        rows = list(self.get_rows() or [])
        key = tuple((r.get("name"), r.get("value")) for r in rows)
        if key == self._last:
            return False
        self._last = key

        # start clean
        self.clear()
        pen = ImageDraw.Draw(self.surface)
        width, height = self.surface.size

        # the panel
        draw.panel(pen, (0, 0, width, height))
        draw.accent_bar(pen, (0, 0, width, max(2, self.s(4))))

        # nothing to show
        if not rows:
            face = theme.font("medium", self.s(30, 12))
            draw.text(pen, (width // 2, height // 2), "Almanac unavailable",
                      face, theme.TEXT_DIM, anchor="mm")
            return True

        # the moon sits in its own block on the right
        moon_width = self.s(280, 80)
        table_right = max(self.s(200), width - moon_width)
        self._draw_moon(pen, rows, table_right, width, height)

        # everything else is a two column table
        self._draw_rows(pen, rows, table_right, height)
        return True

    def _draw_rows(self, pen: ImageDraw.ImageDraw, rows: list, right: int,
                   height: int) -> None:
        """
        Draw the reading table

        @param pen: ImageDraw The drawing context
        @param rows: list The almanac rows
        @param right: int Where the table has to end
        @param height: int The surface height
        @return None
        """

        # two columns of rows, split down the middle of the table area
        pad = self.s(30, 8)
        columns = 2
        gap = self.s(28, 8)
        column_w = (right - pad * 2 - gap) // columns
        per_column = (len(rows) + columns - 1) // columns

        # work out a row height that fills the panel
        usable = height - pad * 2 - self.s(40)
        row_h = max(self.s(30, 12), usable // max(1, per_column))

        # lay them out down each column in turn
        label_face = theme.font("semibold", self.s(24, 10))
        value_face = theme.font("bold", self.s(26, 10))
        for index, row in enumerate(rows):
            column, position = divmod(index, per_column)
            if column >= columns:
                break
            left = pad + column * (column_w + gap)
            top = pad + self.s(30) + position * row_h

            # a hairline under each row keeps the pairs readable
            pen.line([left, top + row_h - self.s(6), left + column_w,
                      top + row_h - self.s(6)],
                     fill=theme.with_alpha(theme.PANEL_LINE, 160), width=1)

            # the caption and its value
            draw.text(pen, (left, top + row_h // 2 - self.s(4)),
                      str(row.get("name") or ""), label_face, theme.TEXT_FAINT,
                      anchor="lm")
            draw.text(pen, (left + column_w, top + row_h // 2 - self.s(4)),
                      str(row.get("value") or "--"), value_face, theme.TEXT,
                      anchor="rm")

    def _draw_moon(self, pen: ImageDraw.ImageDraw, rows: list, left: int,
                   width: int, height: int) -> None:
        """
        Draw the moon block

        @param pen: ImageDraw The drawing context
        @param rows: list The almanac rows, one of which carries the phase
        @param left: int The block's left edge
        @param width: int The surface width
        @param height: int The surface height
        @return None
        """

        # find the phase and its name
        fraction = None
        name = "--"
        for row in rows:
            if row.get("name") == "Moon Phase":
                fraction = row.get("moon_phase")
                name = str(row.get("value") or "--")
                break

        # the block body
        pad = self.s(24, 6)
        box = (left, pad, width - pad, height - pad)
        draw.panel(pen, box, fill=theme.PANEL_ALT)

        # the moon itself, drawn at the actual phase
        size = min(self.s(180, 40), (box[2] - box[0]) - pad * 2,
                   (box[3] - box[1]) - self.s(90))
        if size > 0:
            art = icons.moon_icon(size, fraction)
            self.surface.paste(
                art,
                (box[0] + ((box[2] - box[0]) - size) // 2, box[1] + self.s(28)),
                art,
            )

        # and its name underneath
        face = draw.fit_face(pen, name, "bold", self.s(28, 11),
                             (box[2] - box[0]) - pad)
        draw.text(pen, ((box[0] + box[2]) // 2, box[3] - self.s(28)), name, face,
                  theme.TEXT, anchor="ms")
