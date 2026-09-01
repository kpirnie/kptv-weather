#!/usr/bin/env python3
"""
Radar Layer

The animated radar loop. Frames arrive already composited over the base map,
and this layer only paces them and draws the surrounding furniture.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Callable, Optional

from PIL import Image, ImageDraw

from .. import draw, theme
from ..core.layer import Layer

# the reflectivity key drawn along the bottom
LEGEND = (
    ("5", (100, 180, 250)),
    ("20", (64, 200, 120)),
    ("35", (240, 216, 80)),
    ("50", (240, 130, 60)),
    ("65", (224, 64, 72)),
    ("75", (220, 90, 220)),
)


class RadarLayer(Layer):
    """
    The radar page
    """

    def __init__(self, x: int, y: int, w: int, h: int,
                 get_new_frames: Callable, get_source: Callable,
                 frame_hold: int = 3, min_interval: float = 0.25,
                 scale: float = 1.0):
        """
        Build the page

        @param x: int Left edge within the frame
        @param y: int Top edge within the frame
        @param w: int Surface width
        @param h: int Surface height
        @param get_new_frames: Callable Returns any newly fetched frames
        @param get_source: Callable Returns the credit for the current source
        @param frame_hold: int How many ticks each frame is held for
        @param min_interval: float Shortest gap between redraws
        @param scale: float The output scale factor
        """

        # the surface and its data sources
        super().__init__(x, y, w, h, min_interval, scale)
        self.get_new_frames = get_new_frames
        self.get_source = get_source
        self.frame_hold = max(1, int(frame_hold))

        # the loop we are playing and where we are in it
        self._frames: list = []
        self._index = 0
        self._held = 0

    def tick(self, now: float) -> bool:
        """
        Advance the loop and repaint

        @param now: float Current wall clock time
        @return bool: True when the surface changed
        """

        # pick up anything the fetcher has produced since last time
        fresh = self.get_new_frames() or []
        if fresh:
            self._frames = list(fresh)
            self._index = 0
            self._held = 0

        # start clean
        self.clear()
        pen = ImageDraw.Draw(self.surface)
        width, height = self.surface.size

        # the panel
        draw.panel(pen, (0, 0, width, height))
        draw.accent_bar(pen, (0, 0, width, max(2, self.s(4))))

        # nothing fetched yet
        if not self._frames:
            face = theme.font("medium", self.s(30, 12))
            draw.text(pen, (width // 2, height // 2), "Radar loading\u2026", face,
                      theme.TEXT_DIM, anchor="mm")
            return True

        # hold each frame for a few ticks so the loop is watchable
        self._held += 1
        if self._held >= self.frame_hold:
            self._held = 0
            self._index = (self._index + 1) % len(self._frames)

        # the map area, leaving room for the legend
        inset = self.s(16, 4)
        map_top = self.s(10) + inset
        map_bottom = height - self.s(54, 20)
        self._paste_frame(map_top, map_bottom, inset, width)

        # the frame time and the source credit
        entry = self._frames[self._index]
        self._draw_footer(pen, entry, width, height, map_bottom)
        return True

    def _paste_frame(self, top: int, bottom: int, inset: int,
                     width: int) -> None:
        """
        Scale the current frame into the map area and paste it

        @param top: int The top of the map area
        @param bottom: int The bottom of the map area
        @param inset: int The horizontal inset
        @param width: int The surface width
        @return None
        """

        # the box we have to fill
        box_w = max(1, width - inset * 2)
        box_h = max(1, bottom - top)

        # scale the frame to cover it, then crop the overflow
        image = self._frames[self._index].get("image")
        if image is None:
            return
        scale = max(box_w / image.width, box_h / image.height)
        resized = image.resize(
            (max(1, int(round(image.width * scale))),
             max(1, int(round(image.height * scale)))),
            Image.LANCZOS,
        )
        left = max(0, (resized.width - box_w) // 2)
        crop_top = max(0, (resized.height - box_h) // 2)
        cropped = resized.crop((left, crop_top, left + box_w, crop_top + box_h))
        self.surface.paste(cropped, (inset, top), cropped)

    def _draw_footer(self, pen: ImageDraw.ImageDraw, entry: dict, width: int,
                     height: int, map_bottom: int) -> None:
        """
        Draw the frame time, the legend, and the source credit

        @param pen: ImageDraw The drawing context
        @param entry: dict The current frame
        @param width: int The surface width
        @param height: int The surface height
        @param map_bottom: int Where the map area ended
        @return None
        """

        # the frame's timestamp
        face = theme.font("bold", self.s(24, 10))
        label = str(entry.get("label") or "")
        draw.text(pen, (self.s(20), map_bottom + self.s(14)), label, face,
                  theme.TEXT)

        # the reflectivity key
        swatch = self.s(34, 12)
        swatch_h = self.s(14, 6)
        cursor = self.s(160, 60)
        key_face = theme.font("semibold", self.s(16, 8))
        for text, color in LEGEND:
            if cursor + swatch > width - self.s(240):
                break
            top = map_bottom + self.s(18)
            pen.rectangle([cursor, top, cursor + swatch, top + swatch_h],
                          fill=color + (255,))
            draw.text(pen, (cursor + swatch // 2, top + swatch_h + self.s(2)),
                      text, key_face, theme.TEXT_FAINT, anchor="ma")
            cursor += swatch + self.s(4)

        # and the credit, right aligned
        source = str(self.get_source() or "")
        if source:
            credit_face = theme.font("medium", self.s(18, 8))
            draw.text(pen, (width - self.s(20), map_bottom + self.s(18)), source,
                      credit_face, theme.TEXT_FAINT, anchor="ra")
