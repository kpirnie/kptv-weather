#!/usr/bin/env python3
"""
Map Layers

The two map pages: current temperatures at nearby cities, and tomorrow's
highs at those same cities. Both share the plotting code and differ only in
which field they label the markers with.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Callable, Optional

from PIL import Image, ImageDraw

from .. import draw, map_tiles, theme
from ..core.layer import Layer


class _MapLayer(Layer):
    """
    Shared plotting for both map pages
    """

    # which field the marker prints, filled in by the subclasses
    value_field = "temp"

    def __init__(self, x: int, y: int, w: int, h: int, get_points: Callable,
                 get_map: Callable, get_bounds: Callable,
                 min_interval: float = 20.0, scale: float = 1.0):
        """
        Build the page

        @param x: int Left edge within the frame
        @param y: int Top edge within the frame
        @param w: int Surface width
        @param h: int Surface height
        @param get_points: Callable Returns the markers to plot
        @param get_map: Callable Returns the base map image
        @param get_bounds: Callable Returns the base map's bounds
        @param min_interval: float Shortest gap between redraws
        @param scale: float The output scale factor
        """

        # the surface and its data sources
        super().__init__(x, y, w, h, min_interval, scale)
        self.get_points = get_points
        self.get_map = get_map
        self.get_bounds = get_bounds
        self._last: Optional[tuple] = None

    def tick(self, now: float) -> bool:
        """
        Redraw when the markers or the base map change

        @param now: float Current wall clock time
        @return bool: True when the surface changed
        """

        # the markers plus whether we have a map yet
        points = list(self.get_points() or [])
        base = self.get_map()
        key = (tuple((p.get("name"), p.get(self.value_field)) for p in points),
               base is not None)
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

        # the map area
        inset = self.s(16, 4)
        top = self.s(10) + inset
        bottom = height - self.s(40, 14)
        box_w = max(1, width - inset * 2)
        box_h = max(1, bottom - top)

        # the backdrop, when we managed to fetch one
        if base is not None:
            self._paste_base(base, inset, top, box_w, box_h)

        # nothing to plot
        if not points:
            face = theme.font("medium", self.s(30, 12))
            draw.text(pen, (width // 2, height // 2), "Regional data unavailable",
                      face, theme.TEXT_DIM, anchor="mm")
            return True

        # the markers
        bounds = self.get_bounds()
        if bounds:
            for point in points:
                self._draw_marker(pen, point, bounds, inset, top, box_w, box_h)

        # and the map credit
        credit_face = theme.font("medium", self.s(16, 8))
        draw.text(pen, (width - self.s(20), height - self.s(28)),
                  map_tiles.ATTRIBUTION, credit_face, theme.TEXT_FAINT,
                  anchor="ra")
        return True

    def _paste_base(self, base: Image.Image, inset: int, top: int, box_w: int,
                    box_h: int) -> None:
        """
        Scale and paste the base map

        @param base: Image The stitched base map
        @param inset: int The horizontal inset
        @param top: int The top of the map area
        @param box_w: int The map area width
        @param box_h: int The map area height
        @return None
        """

        # cover the box and crop whatever hangs over
        scale = max(box_w / base.width, box_h / base.height)
        resized = base.resize(
            (max(1, int(round(base.width * scale))),
             max(1, int(round(base.height * scale)))),
            Image.LANCZOS,
        )
        left = max(0, (resized.width - box_w) // 2)
        crop_top = max(0, (resized.height - box_h) // 2)
        cropped = resized.crop((left, crop_top, left + box_w, crop_top + box_h))
        self.surface.paste(cropped, (inset, top), cropped)

    def _draw_marker(self, pen: ImageDraw.ImageDraw, point: dict, bounds: tuple,
                     inset: int, top: int, box_w: int, box_h: int) -> None:
        """
        Draw one city marker

        @param pen: ImageDraw The drawing context
        @param point: dict The marker's data
        @param bounds: tuple The base map's bounds
        @param inset: int The horizontal inset
        @param top: int The top of the map area
        @param box_w: int The map area width
        @param box_h: int The map area height
        @return None
        """

        # place it, skipping anything that landed outside the box
        lat, lon = point.get("lat"), point.get("lon")
        if lat is None or lon is None:
            return
        x, y = map_tiles.project(lat, lon, bounds, box_w, box_h)
        x += inset
        y += top
        if not (inset <= x <= inset + box_w and top <= y <= top + box_h):
            return

        # the value chip
        value = str(point.get(self.value_field) or "--")
        face = theme.font("black", self.s(28, 11))
        text_w, text_h = draw.measure(pen, value, face)
        pad = self.s(10, 3)
        chip = (x - text_w // 2 - pad, y - text_h // 2 - pad,
                x + text_w // 2 + pad, y + text_h // 2 + pad)
        draw.panel(pen, chip, fill=theme.with_alpha(theme.PANEL, 240),
                   outline=theme.temp_color(point.get("temp_f")),
                   width=max(2, self.s(3)))
        draw.text(pen, (x, y), value, face,
                  theme.temp_color(point.get("temp_f")), anchor="mm")

        # and the city name under it
        name = str(point.get("name") or "").split(",")[0]
        name_face = theme.font("semibold", self.s(20, 9))
        draw.text(pen, (x, chip[3] + self.s(4)), name, name_face, theme.TEXT)


class RegionalLayer(_MapLayer):
    """
    Current temperatures at nearby cities
    """

    # the marker prints the current reading
    value_field = "temp"


class ForecastMapLayer(_MapLayer):
    """
    Tomorrow's highs at those same cities
    """

    # the marker prints the forecast high instead
    value_field = "forecast_temp"
