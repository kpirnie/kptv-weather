#!/usr/bin/env python3
"""
Theme Module

The palette, the type scale, and the font loader. Everything drawn on screen
pulls its colours and faces from here so a restyle is a single file change.

@package KPTV Weather
@author Kevin Pirnie <me@kpirnie.com>
@copyright Copyright (c) 2026
"""

# setup the imports
from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from PIL import ImageFont

logger = logging.getLogger(__name__)

# backdrop and panel fills
BACKGROUND = (8, 12, 24, 255)
PANEL = (18, 26, 46, 235)
PANEL_ALT = (26, 36, 60, 235)
PANEL_LINE = (54, 72, 108, 255)

# the accent that carries the branding through the chrome
ACCENT = (56, 168, 236, 255)
ACCENT_DIM = (32, 104, 150, 255)

# alerting
ALERT = (232, 96, 64, 255)
ALERT_DIM = (150, 56, 36, 255)

# type
TEXT = (238, 244, 252, 255)
TEXT_DIM = (156, 174, 200, 255)
TEXT_FAINT = (104, 124, 154, 255)
SHADOW = (0, 0, 0, 140)

# the temperature ramp, in Fahrenheit so one table covers every unit system
TEMP_RAMP = (
    (-20.0, (108, 72, 196, 255)),
    (10.0, (64, 112, 220, 255)),
    (32.0, (72, 172, 228, 255)),
    (50.0, (72, 196, 168, 255)),
    (68.0, (128, 204, 96, 255)),
    (80.0, (240, 196, 72, 255)),
    (92.0, (240, 132, 56, 255)),
    (104.0, (228, 72, 64, 255)),
)

# where the bundled faces live, resolved relative to the package
_ASSET_ROOT = Path(__file__).resolve().parent.parent / "assets"

# the face files we look for, in the order we would rather have them
_FACES = {
    "black": ("Inter-Black.ttf", "Inter-Bold.ttf"),
    "bold": ("Inter-Bold.ttf", "Inter-SemiBold.ttf"),
    "semibold": ("Inter-SemiBold.ttf", "Inter-Medium.ttf"),
    "medium": ("Inter-Medium.ttf", "Inter-Regular.ttf"),
    "regular": ("Inter-Regular.ttf", "Inter-Medium.ttf"),
}


def asset_root() -> Path:
    """
    Where bundled artwork and faces are read from

    Overridable so the whole assets tree can be bind mounted somewhere else.

    @return Path: The asset directory
    """

    # an override wins, otherwise it sits alongside the package
    override = (os.environ.get("KPTVW_ASSET_DIR") or "").strip()
    return Path(override) if override else _ASSET_ROOT


def font_dir() -> Path:
    """
    Where the type faces live

    @return Path: The font directory
    """

    # always a fonts folder under the asset root
    return asset_root() / "fonts"


def icon_dir() -> Path:
    """
    Where the condition icons live

    @return Path: The icon directory
    """

    # always an icons folder under the asset root
    return asset_root() / "icons"


@lru_cache(maxsize=256)
def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    """
    Load a face at a size, cached for the life of the process

    Falls back to Pillow's built-in bitmap face when nothing is installed, so
    a missing font never stops the channel from going out.

    @param weight: str One of black, bold, semibold, medium, regular
    @param size: int Point size
    @return FreeTypeFont: The loaded face
    """

    # clamp the size and pick the candidate list
    points = max(6, int(size))
    candidates = _FACES.get(weight, _FACES["regular"])

    # try each candidate in turn
    directory = font_dir()
    for name in candidates:
        path = directory / name
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), points)
            except OSError:
                continue

    # then anything at all that is sitting in there
    if directory.is_dir():
        for path in sorted(directory.glob("*.ttf")):
            try:
                return ImageFont.truetype(str(path), points)
            except OSError:
                continue

    # and give up gracefully
    logger.warning("no usable font found in %s, falling back to the default",
                   directory)
    return ImageFont.load_default()


def temp_color(fahrenheit: Optional[float]) -> tuple:
    """
    Map a temperature onto the ramp

    @param fahrenheit: float|None The temperature in Fahrenheit
    @return tuple: An RGBA colour
    """

    # unknown temperatures just take the dim text colour
    if fahrenheit is None:
        return TEXT_DIM

    # below and above the ends of the ramp clamp to the ends
    value = float(fahrenheit)
    if value <= TEMP_RAMP[0][0]:
        return TEMP_RAMP[0][1]
    if value >= TEMP_RAMP[-1][0]:
        return TEMP_RAMP[-1][1]

    # otherwise blend between the two stops it falls between
    for index in range(len(TEMP_RAMP) - 1):
        low_temp, low_color = TEMP_RAMP[index]
        high_temp, high_color = TEMP_RAMP[index + 1]
        if low_temp <= value <= high_temp:
            span = high_temp - low_temp
            ratio = 0.0 if span <= 0 else (value - low_temp) / span
            return tuple(
                int(round(low_color[channel] +
                          (high_color[channel] - low_color[channel]) * ratio))
                for channel in range(4)
            )

    # unreachable, but keep the return type honest
    return TEXT_DIM


def with_alpha(color: tuple, alpha: int) -> tuple:
    """
    Restate a colour at a different opacity

    @param color: tuple An RGBA colour
    @param alpha: int The new alpha channel, 0 to 255
    @return tuple: The colour at the requested opacity
    """

    # keep the rgb, swap the alpha
    return (color[0], color[1], color[2], max(0, min(255, int(alpha))))
