#!/usr/bin/env python3
"""
Layer Module

Base class for anything drawn on screen. Every layer owns its own offscreen
RGBA surface and redraws it only when its own cadence comes around, which is
what keeps a thirty frame per second channel affordable.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Optional

from PIL import Image


class Layer:
    """
    One drawable element with its own surface and refresh cadence
    """

    # where this sits in the stack, higher draws later
    z: int = 0

    def __init__(self, x: int, y: int, w: int, h: int,
                 min_interval: float = 1.0, scale: float = 1.0):
        """
        Build the layer and allocate its surface

        @param x: int Left edge within the frame
        @param y: int Top edge within the frame
        @param w: int Surface width
        @param h: int Surface height
        @param min_interval: float Shortest gap between redraws, in seconds
        @param scale: float Multiplier applied to every design dimension
        """

        # where we live and how big we are
        self.bounds = (int(x), int(y), int(w), int(h))
        self.min_interval = max(0.001, float(min_interval))

        # our own transparent canvas, never smaller than a single pixel
        self.surface = Image.new("RGBA", (max(1, int(w)), max(1, int(h))),
                                 (0, 0, 0, 0))

        # visibility and change tracking
        self.visible: bool = True
        self._last_signature: Optional[int] = None

        # everything is designed at 1080p and scaled from there
        try:
            self.scale = float(scale or 1.0)
        except (TypeError, ValueError):
            self.scale = 1.0

    def s(self, value: float, minimum: int = 0) -> int:
        """
        Scale a design dimension to the current output resolution

        @param value: float The dimension as designed at 1080p
        @param minimum: int Floor applied after scaling
        @return int: The scaled value
        """

        # scale it and keep it above the floor
        return max(minimum, int(round(value * self.scale)))

    def clear(self) -> None:
        """
        Wipe the surface back to fully transparent

        @return None
        """

        # paste transparency over the whole thing
        self.surface.paste((0, 0, 0, 0), (0, 0) + self.surface.size)

    def tick(self, now: float) -> bool:
        """
        Redraw the surface if anything has changed

        Subclasses override this, redraw into self.surface, and return whether
        the frame needs recompositing.

        @param now: float Current wall clock time
        @return bool: True when the surface changed
        """

        # the base layer never draws anything
        return False

    def changed(self) -> bool:
        """
        Whether the surface differs from the last time we were asked

        @return bool: True when the pixels have moved
        """

        # hash the pixels and compare against what we saw last
        signature = hash(self.surface.tobytes())
        if signature != self._last_signature:
            self._last_signature = signature
            return True
        return False

    def set_visible(self, visible: bool) -> None:
        """
        Show or hide the layer

        @param visible: bool Whether the layer should be composited
        @return None
        """

        # nothing to do when it already matches
        flag = bool(visible)
        if flag == self.visible:
            return

        # flip it, and force the next tick to count as a change when showing
        self.visible = flag
        if self.visible:
            self._last_signature = None
