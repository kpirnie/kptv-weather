#!/usr/bin/env python3
"""
Hourly Trend Layer

The twelve hour page: a temperature curve with precipitation chance and
cloud cover plotted underneath it.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Callable, Optional

from PIL import ImageDraw

from .. import draw, theme
from ..core.layer import Layer


class HourlyGraphLayer(Layer):
    """
    The twelve hour trend page
    """

    def __init__(self, x: int, y: int, w: int, h: int, get_points: Callable,
                 min_interval: float = 15.0, scale: float = 1.0):
        """
        Build the page

        @param x: int Left edge within the frame
        @param y: int Top edge within the frame
        @param w: int Surface width
        @param h: int Surface height
        @param get_points: Callable Returns the hourly series
        @param min_interval: float Shortest gap between redraws
        @param scale: float The output scale factor
        """

        # the surface, the data source, and the last state we drew
        super().__init__(x, y, w, h, min_interval, scale)
        self.get_points = get_points
        self._last: Optional[tuple] = None

    def tick(self, now: float) -> bool:
        """
        Redraw when the series changes

        @param now: float Current wall clock time
        @return bool: True when the surface changed
        """

        # the whole series as one comparable key
        points = [p for p in (self.get_points() or []) if p.get("temp") is not None]
        key = tuple((p.get("label"), p.get("temp"), p.get("precip"),
                     p.get("cloud")) for p in points)
        if key == self._last:
            return False
        self._last = key

        # start clean
        self.clear()
        pen = ImageDraw.Draw(self.surface)
        width, height = self.surface.size

        # the panel the graph sits in
        draw.panel(pen, (0, 0, width, height))
        draw.accent_bar(pen, (0, 0, width, max(2, self.s(4))))

        # nothing to plot
        if len(points) < 2:
            face = theme.font("medium", self.s(30, 12))
            draw.text(pen, (width // 2, height // 2), "Hourly data unavailable",
                      face, theme.TEXT_DIM, anchor="mm")
            return True

        # the plot area, leaving room for the axis labels
        pad_x = self.s(60, 16)
        top = self.s(56, 16)
        bottom = height - self.s(96, 30)
        plot_w = width - pad_x * 2
        plot_h = max(self.s(60), bottom - top)

        # the temperature range, padded so the curve never touches the edges
        temps = [float(p["temp"]) for p in points]
        low, high = min(temps), max(temps)
        if high - low < 1.0:
            high, low = high + 1.0, low - 1.0
        span = high - low
        low -= span * 0.15
        high += span * 0.15
        span = high - low

        # the horizontal step between readings
        step = plot_w / float(len(points) - 1)

        # gridlines behind everything
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = int(top + plot_h * fraction)
            pen.line([pad_x, y, pad_x + plot_w, y],
                     fill=theme.with_alpha(theme.PANEL_LINE, 150), width=1)

        # the cloud cover and precipitation bars, drawn under the curve
        self._draw_bars(pen, points, pad_x, step, top, plot_h)

        # the temperature curve itself
        coords = []
        for index, point in enumerate(points):
            x = pad_x + step * index
            y = top + plot_h * (1.0 - (float(point["temp"]) - low) / span)
            coords.append((x, y))
        pen.line(coords, fill=theme.ACCENT, width=max(2, self.s(5)), joint="curve")

        # the readings themselves
        dot = max(3, self.s(7))
        value_face = theme.font("bold", self.s(24, 10))
        for index, (x, y) in enumerate(coords):
            color = theme.temp_color(points[index].get("temp_f"))
            pen.ellipse([x - dot, y - dot, x + dot, y + dot], fill=color)
            draw.text(pen, (x, y - dot - self.s(8)),
                      f"{int(round(points[index]['temp']))}\u00b0", value_face,
                      theme.TEXT, anchor="mb")

        # and the hour labels along the bottom
        label_face = theme.font("semibold", self.s(22, 9))
        for index, point in enumerate(points):
            x = pad_x + step * index
            draw.text(pen, (x, bottom + self.s(16)), str(point.get("label") or ""),
                      label_face, theme.TEXT_DIM, anchor="ma")

        # a small legend so the two bar series are readable
        self._draw_legend(pen, width, height)
        return True

    def _draw_bars(self, pen: ImageDraw.ImageDraw, points: list, pad_x: int,
                   step: float, top: int, plot_h: int) -> None:
        """
        Draw the precipitation and cloud cover bars

        @param pen: ImageDraw The drawing context
        @param points: list The hourly series
        @param pad_x: int The left inset of the plot
        @param step: float The horizontal gap between readings
        @param top: int The top of the plot area
        @param plot_h: int The plot height
        @return None
        """

        # the bars occupy the lower half of the plot so they never fight the curve
        base = top + plot_h
        max_bar = plot_h * 0.55
        half = max(2, int(step * 0.18))

        # cloud cover first, in the dimmer colour
        for index, point in enumerate(points):
            x = pad_x + step * index
            cloud = point.get("cloud")
            if cloud is not None:
                bar_h = max_bar * (float(cloud) / 100.0)
                pen.rectangle([x - half * 2, base - bar_h, x - half * 0.2, base],
                              fill=theme.with_alpha(theme.TEXT_FAINT, 120))

            # then the precipitation chance
            precip = point.get("precip")
            if precip is not None:
                bar_h = max_bar * (float(precip) / 100.0)
                pen.rectangle([x + half * 0.2, base - bar_h, x + half * 2, base],
                              fill=theme.with_alpha(theme.ACCENT_DIM, 200))

    def _draw_legend(self, pen: ImageDraw.ImageDraw, width: int,
                     height: int) -> None:
        """
        Draw the small key for the two bar series

        @param pen: ImageDraw The drawing context
        @param width: int The surface width
        @param height: int The surface height
        @return None
        """

        # a swatch and a caption for each series
        face = theme.font("semibold", self.s(20, 9))
        swatch = self.s(18, 6)
        y = self.s(22)
        cursor = width - self.s(60)
        for label, color in (("PRECIP", theme.ACCENT_DIM),
                             ("CLOUD", theme.TEXT_FAINT)):
            text_w = draw.measure(pen, label, face)[0]
            cursor -= text_w
            draw.text(pen, (cursor, y), label, face, theme.TEXT_DIM)
            cursor -= swatch + self.s(8)
            pen.rectangle([cursor, y, cursor + swatch, y + swatch], fill=color)
            cursor -= self.s(24)
