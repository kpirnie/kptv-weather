#!/usr/bin/env python3
"""
Compositor Module

Flattens every visible layer into one frame. Double buffered so the encoder
is always handed a surface nothing is currently drawing onto.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Iterable

from PIL import Image


class Compositor:
    """
    Builds finished frames from a stack of layers
    """

    def __init__(self, w: int, h: int):
        """
        Allocate the two frame buffers

        @param w: int Frame width
        @param h: int Frame height
        """

        # the surface size and the pair of buffers we swap between
        self.w, self.h = int(w), int(h)
        self.front = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 255))
        self.back = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 255))

    def compose(self, layers: Iterable) -> None:
        """
        Rebuild the back buffer from the visible layers

        @param layers: Iterable The layer stack, already sorted by z
        @return None
        """

        # start from opaque black so nothing from the last frame bleeds through
        self.back.paste((0, 0, 0, 255), (0, 0, self.w, self.h))

        # then paste each visible layer using its own alpha as the mask
        for layer in layers:
            if not getattr(layer, "visible", True):
                continue
            x, y, w, h = layer.bounds
            if w <= 0 or h <= 0:
                continue
            self.back.paste(layer.surface, (x, y), layer.surface)

    def present(self) -> Image.Image:
        """
        Swap the buffers and hand back the finished frame

        @return Image: The completed frame
        """

        # flip them and return whatever just became the front
        self.front, self.back = self.back, self.front
        return self.front
