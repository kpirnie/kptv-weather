#!/usr/bin/env python3
"""
Layout Module

Shared geometry. Every dimension here is expressed against the 1920x1080
design surface and scaled at draw time, so one set of numbers covers every
output resolution.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

from typing import Callable

# the surface everything is designed against
BASE_WIDTH = 1920
BASE_HEIGHT = 1080

# the persistent header band
HEADER_H = 196
LABEL_Y = 96
MARGIN = 48

# the ticker that sits along the bottom
TICKER_H = 64
TICKER_GAP = 22

# where page content starts, below the header
CONTENT_TOP = 262

# how far apart the four header columns sit
COLUMN_GAP = 24


def header_columns(width: int, scale: Callable[[float, int], int]) -> list:
    """
    Work out the four header column positions for a given frame width

    Column one carries the identity and location, two the page title, three
    the current temperature, and four the clock.

    @param width: int The frame width in pixels
    @param scale: Callable Scales a design dimension to this resolution
    @return list: Four tuples of left edge and column width
    """

    # the band runs between the margins
    left = scale(MARGIN, 1)
    usable = max(scale(320, 1), width - scale(MARGIN * 2))
    gap = scale(COLUMN_GAP, 1)

    # identity gets the most room, the clock and temperature are fixed-ish
    weights = (0.38, 0.26, 0.16, 0.20)

    # lay them out left to right
    columns: list[tuple[int, int]] = []
    cursor = left
    total_gap = gap * (len(weights) - 1)
    available = max(4, usable - total_gap)
    for index, weight in enumerate(weights):
        column_width = int(round(available * weight))
        columns.append((cursor, max(1, column_width)))
        cursor += column_width + gap

    return columns


def content_bounds(width: int, height: int, scale: Callable[[float, int], int],
                   top: int = CONTENT_TOP, bottom_extra: int = 24) -> tuple:
    """
    The rectangle a page body may draw into

    @param width: int The frame width in pixels
    @param height: int The frame height in pixels
    @param scale: Callable Scales a design dimension to this resolution
    @param top: int Where the body starts, as designed
    @param bottom_extra: int Extra breathing room above the ticker
    @return tuple: Left, top, width, and height
    """

    # inset by the margins
    x = scale(MARGIN, 1)
    y = scale(top, 1)
    w = max(scale(320, 1), width - scale(MARGIN * 2))

    # and stop short of the ticker
    reserved = scale(TICKER_H, 1) + scale(TICKER_GAP, 1) + scale(bottom_extra, 0)
    h = max(scale(160, 1), height - (y + reserved))
    return (x, y, w, h)
